#!/usr/bin/env python3
"""Bulk reservation for approved, preflight-ready episode panels.

This never calls imagegen. Legacy mode is coordinator-only with two-file CAS.
In slot-lease mode the owner writes only its state/ledger in one atomic replace;
control is locked and read, never changed. Immutable packet copies carry receipts.
"""
from __future__ import annotations

import argparse
import copy
from platform_io import file_lock, atomic_json
import json
import time
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path

from codex_reference_contract import checked_file, digest, read_json, file_session, resolve_path, _changed


def _atomic_json(path, value):
    atomic_json(path, value)


@contextmanager
def _dispatch_reads(metrics):
    started = time.perf_counter()
    memo = None
    metrics['read_dependencies_verified'] = False
    try:
        with file_session() as memo:
            yield memo
        metrics['read_dependencies_verified'] = True
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        # Preserve measurements when the whole read set rejects a preflight.
        # The enclosing lock context fills its durations before main prints it.
        exc.dispatch_metrics = metrics
        raise
    finally:
        metrics['preflight_seconds'] = round(time.perf_counter() - started, 6)
        if memo is not None:
            metrics['file_reuse_statistics'] = {k: memo[k] for k in (
                'hash_reads', 'hash_hits', 'hash_bytes', 'json_parses', 'json_hits', 'validation_runs', 'validation_hits',
                'dependency_checks', 'dependency_invalidations', 'negative_observations', 'directory_scans', 'content_read_bytes')}
            metrics['audit_reuse_statistics'] = copy.deepcopy(memo['audit_statistics'])
            metrics['discarded_preflights'] = int(memo['invalidated'] is not None)


@contextmanager
def _timed_locks(paths, timings):
    started = time.perf_counter()
    timings.setdefault('locks', [])
    @contextmanager
    def timed_lock(path):
        waiting = time.perf_counter()
        with file_lock(path):
            acquired = time.perf_counter()
            row = {'kind': 'episode_state' if path.name.endswith('.runtime.lock') else 'shared_dispatch',
                   'path': str(path), 'wait_seconds': round(acquired - waiting, 6)}
            timings['locks'].append(row)
            try:
                yield
            finally:
                row['hold_seconds'] = round(time.perf_counter() - acquired, 6)
    with ExitStack() as stack:
        for path in paths:
            stack.enter_context(timed_lock(path))
        acquired = time.perf_counter()
        timings['lock_wait_seconds'] = round(timings.get('lock_wait_seconds', 0) + acquired - started, 6)
        try:
            yield
        finally:
            timings['lock_hold_seconds'] = round(timings.get('lock_hold_seconds', 0) + time.perf_counter() - acquired, 6)


def _prepare(state_reference, state_path, control_reference, control_path, context,
             expected_state_sha256, expected_control_sha256, max_count, metrics):
    from staged_workflow import evaluate
    from parallel_dispatch import ACTIVE_PERMITS, context_errors
    from dispatch_publication import require_legacy
    root = state_path.parent.parent
    if resolve_path(state_reference) != state_path or resolve_path(control_reference) != control_path:
        _changed('dispatch state/control reference target changed')
    if digest(state_path) != expected_state_sha256 or digest(control_path) != expected_control_sha256:
        raise ValueError('STATE_OR_CONTROL_CHANGED')
    state = read_json(state_path)
    control = read_json(control_path)
    require_legacy(state)
    require_legacy(control)
    from authority_updates import state_errors as authority_errors
    errors = authority_errors(state)
    if errors: raise ValueError(';'.join(errors))
    from slot_leases import enabled as leased, effective_control
    lease_mode = leased(control)
    control = effective_control(control,state,context)
    if state.get('execution_mode') != 'episode_async_v1' or state.get('optimization_policy') != 'scoped_episode_review_v1':
        raise ValueError('此入口只用于整话模式')
    if state.get('parallel_context') != context:
        raise ValueError('调度上下文已换版')
    errors = context_errors(context, root, state['book_id'], state['episode_id'])
    if errors:
        raise ValueError(';'.join(errors))
    job = next((j for j in control['jobs'] if j.get('job_id') == context['job_id']), None)
    if not job or job.get('active_batch_id') != 'EPISODE' or job.get('status') not in {'ASSIGNED', 'RUNNING'}:
        raise ValueError('当前整话任务尚未可提交')
    if job.get('dispatch_pause') is True:
        return {'status': 'DISPATCH_PAUSED', 'reserved': [], 'state_sha256': expected_state_sha256,
                'control_sha256': expected_control_sha256, 'image_calls': 0, 'dispatch_metrics': metrics}
    if type(control.get('max_inflight')) is not int or type(job.get('max_inflight')) is not int:
        raise ValueError('总控/本话并发容量须已核定')
    active = [p for p in control['permits'] if p.get('status') in ACTIVE_PERMITS]
    own = [p for p in active if p.get('job_id') == job['job_id']]
    own_limit = job.get('slot_lease',{}).get('slots',0) if lease_mode else job['max_inflight']
    free = min(control['max_inflight'] - len(active), own_limit - len(own))
    if max_count is not None:
        free = min(free, max_count)
    if free <= 0:
        return {'status': 'CAPACITY_FULL', 'reserved': [], 'state_sha256': expected_state_sha256,
                'control_sha256': expected_control_sha256, 'image_calls': 0, 'dispatch_metrics': metrics}
    records = {r['panel_id']: r for r in state['panels']}
    used = {(p.get('panel_id'), p.get('batch_id'), p.get('round_id')) for p in control['permits']
            if p.get('job_id') == job['job_id'] and p.get('epoch') == context['epoch']
            and p.get('status') in {'RESERVED', 'IN_FLIGHT', 'RESULT_UNKNOWN', 'COMPLETED'}}
    excluded = [pid for pid, row in records.items() if (pid, 'EPISODE', row['round_id']) in used]
    preflight = evaluate(state, root, 'reservation_batch', {'limit': free, 'excluded': excluded})
    # Process-local observations only: never persist clock epochs or
    # infer historical readiness from PENDING/ready_at wall timestamps.
    ready_observed = preflight.pop('_ready_observed_monotonic', {})
    selected = [pid for pid in preflight.get('ready_panel_ids', []) if pid in records and pid not in excluded][:free]
    metrics.update(candidate_count=preflight.get('candidate_count'),
                   checked_panel_count=preflight.get('checked_panel_count'), reserved_count=len(selected),
                   common_check_seconds=preflight.get('common_check_seconds'),
                   panel_check_seconds=preflight.get('panel_check_seconds'))
    metrics['qa_reuse_statistics'] = preflight.get('qa_reuse_statistics', {})
    if not selected:
        return {'status': preflight.get('next_action', 'INPUT_HOLD'), 'reserved': [],
                'reports': preflight.get('reports', []), 'errors': preflight.get('errors', []),
                'failure_domain': preflight.get('failure_domain'),
                'state_sha256': expected_state_sha256, 'control_sha256': expected_control_sha256,
                'image_calls': 0, 'dispatch_metrics': metrics}
    # Load and validate every selected packet inside the read-only transaction.
    # The transaction must finish before ANY packet/state writes take place.
    packets = {}
    for pid in selected:
        row = records[pid]
        original = checked_file(root, row['package_manifest'])
        packet = read_json(original)
        if packet.get('dispatch_receipt') or packet.get('dispatch_source_package') or packet.get('round_context') != {
                'batch_id': 'EPISODE', 'round_id': row['round_id'], 'attempt_id': row['attempt_id']}:
            raise ValueError(f'{pid}:执行包已有回执或轮次不一致')
        packets[pid] = (original, packet)
    return {'prepared': True, 'state': state, 'control': control, 'job': job,
            'selected': selected, 'packets': packets, 'lease_mode': lease_mode,
            'ready_observed': ready_observed}


def _commit(prepared, state_path, control_path, context, expected_state_sha256, metrics, *, request_id=None, _stage_only=False):
    from runtime_clock import require_dispatch
    require_dispatch(state_path)
    state, control, job = (prepared[k] for k in ('state', 'control', 'job'))
    selected, packets, lease_mode, ready_observed = (prepared[k] for k in ('selected', 'packets', 'lease_mode', 'ready_observed'))
    root = state_path.parent.parent
    write_started = time.perf_counter()
    new_state = copy.deepcopy(state)
    new_control = copy.deepcopy(control)
    by_id = {r['panel_id']: r for r in new_state['panels']}
    created = []
    reserved = []
    try:
        for pid in selected:
            row = by_id[pid]
            original, packet = packets[pid]
            permit_id = uuid.uuid4().hex
            receipt = {'job_id': job['job_id'], 'worker_id': context['worker_id'],
                       'epoch': context['epoch'], 'permit_id': permit_id,
                       'batch_id': 'EPISODE', 'round_id': row['round_id'],
                       'attempt_id': row['attempt_id']}
            if lease_mode:receipt['lease_id']=job['slot_lease']['lease_id']
            permit = {**receipt, 'panel_id': pid, 'status': 'RESERVED'}
            packet['dispatch_source_package'] = row['package_manifest']
            packet['dispatch_receipt'] = receipt
            new_path = original.with_name(original.stem + '.dispatch-' + permit_id + original.suffix)
            _atomic_json(new_path, packet)
            created.append(new_path)
            row['package_manifest'] = {'path': new_path.relative_to(root).as_posix(), 'sha256': digest(new_path)}
            from execution_timing import observe
            observe(new_state,row,'ready')
            new_control['permits'].append(permit)
            reserved.append({'panel_id': pid, 'permit_id': permit_id, 'receipt': receipt,
                             'package_manifest': row['package_manifest']})
        if lease_mode:new_state['dispatch_ledger']=new_control['permits']
        if request_id is not None:
            new_state.setdefault('reservation_requests', {})[request_id] = {'reserved': copy.deepcopy(reserved), 'max_count': metrics.get('requested_max_count')}
        if _stage_only:
            return {'new_state':new_state,'new_control':new_control,'reserved':reserved,
                    'ready_observed':ready_observed,'created':created}
        _atomic_json(state_path, new_state)
        if not lease_mode:_atomic_json(control_path, new_control)
        committed = time.perf_counter()
    except Exception:
        # Orphan packet copies are safe to remove only if no state row points to them.
        if digest(state_path) == expected_state_sha256:
            for path in created:
                path.unlink(missing_ok=True)
        raise
    metrics['ready_wait']['panels'] = [
        {'episode_id': state['episode_id'], 'panel_id': item['panel_id'],
         'round_id': item['receipt']['round_id'], 'attempt_id': item['receipt']['attempt_id'],
         'permit_id': item['permit_id'],
         'observed_ready_to_reserve_seconds': round(committed - ready_observed[item['panel_id']], 6)
            if item['panel_id'] in ready_observed else None}
        for item in reserved]
    metrics['write_seconds'] = round(time.perf_counter() - write_started, 6)
    return {'status': 'RESERVED', 'reserved': reserved, 'state_sha256': digest(state_path),
            'control_sha256': digest(control_path), 'image_calls': 0, 'dispatch_metrics': metrics,
            'next_step': 'compile_jobs并再次完整预检，通过后立即提交真实请求'}


def reserve_ready(state_path, expected_state_sha256, expected_control_sha256, max_count=None):
    """Reserve up to the actual free slots, with no guessed backend capacity."""
    from staged_workflow import evaluate
    from parallel_dispatch import ACTIVE_PERMITS, context_errors
    from codex_reference_contract import _FILE_SESSION
    from dispatch_publication import require_legacy

    # A caller-owned read transaction could otherwise validate only after this
    # function has committed. Reservation owns and closes its read set first.
    if _FILE_SESSION.get() is not None:
        raise ValueError('RESERVATION_REQUIRES_OWN_TRANSACTION')

    from runtime_clock import require_dispatch
    require_dispatch(state_path)
    state_reference = Path(state_path).absolute()
    state_path = state_reference.resolve()
    if not state_path.is_file() or not expected_state_sha256 or not expected_control_sha256:
        raise ValueError('须提供实际状态及两份当前哈希')
    root = state_path.parent.parent
    initial = read_json(state_path)
    context = initial.get('parallel_context')
    if not isinstance(context, dict) or not Path(context.get('control_file', '')).is_absolute():
        raise ValueError('只允许具有真实并行调度上下文的整话任务')
    control_reference = Path(context['control_file'])
    control_path = control_reference.resolve()
    if max_count is not None and (type(max_count) is not int or max_count < 1):
        raise ValueError('max_count须为正整数')
    metrics = {'policy': 'dispatch_metrics_v1', 'not_authorization': True,
               'ready_wait': {'policy': 'observed_ready_to_reserve_v1',
                              'clock': 'perf_counter', 'historical_ready_to_reserve_seconds': None,
                              'panels': []}}
    lock_paths = sorted((state_path.with_suffix('.runtime.lock'), control_path.with_suffix('.dispatch.lock')))
    from runtime_pipeline import POLICY as PIPELINE_POLICY, reserve
    from slot_leases import enabled as leased
    if initial.get('runtime_pipeline_policy')==PIPELINE_POLICY and leased(read_json(control_path)):
        return reserve(state_reference,state_path,control_reference,control_path,context,
                       expected_state_sha256,expected_control_sha256,max_count,metrics,lock_paths)
    with _timed_locks(lock_paths, metrics):
        with _dispatch_reads(metrics):
            prepared = _prepare(state_reference, state_path, control_reference, control_path, context,
                                expected_state_sha256, expected_control_sha256, max_count, metrics)
        if not prepared.get('prepared'): return prepared
        require_dispatch(state_path)
        return _commit(prepared, state_path, control_path, context, expected_state_sha256, metrics)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--expected-state-sha256', required=True)
    parser.add_argument('--expected-control-sha256', required=True)
    parser.add_argument('--max-count', type=int)
    args = parser.parse_args()
    try:
        value = reserve_ready(args.state, args.expected_state_sha256,
                              args.expected_control_sha256, args.max_count)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value['status'] in {'RESERVED', 'CAPACITY_FULL'} else 1
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        value = {'status': 'HOLD', 'errors': [str(exc)], 'image_calls': 0}
        if hasattr(exc, 'dispatch_metrics'):
            value['dispatch_metrics'] = exc.dispatch_metrics
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 1


if __name__ == '__main__':
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
