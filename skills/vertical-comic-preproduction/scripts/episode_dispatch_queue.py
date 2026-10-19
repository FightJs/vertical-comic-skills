#!/usr/bin/env python3
"""Bulk reservation for approved, preflight-ready episode panels.

This never calls imagegen. Legacy mode is coordinator-only with two-file CAS.
In slot-lease mode the owner writes only its state/ledger in one atomic replace;
control is locked and read, never changed. Immutable packet copies carry receipts.
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import json
import os
import tempfile
import uuid
from contextlib import ExitStack
from pathlib import Path

from codex_reference_contract import checked_file, digest, read_json


def _atomic_json(path, value):
    path = Path(path)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
        temp = Path(stream.name)
    try:
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def reserve_ready(state_path, expected_state_sha256, expected_control_sha256, max_count=None):
    """Reserve up to the actual free slots, with no guessed backend capacity."""
    from scoped_episode_workflow import evaluate_episode
    from parallel_dispatch import ACTIVE_PERMITS, context_errors

    state_path = Path(state_path).resolve()
    if not state_path.is_file() or not expected_state_sha256 or not expected_control_sha256:
        raise ValueError('须提供实际状态及两份当前哈希')
    root = state_path.parent.parent
    initial = read_json(state_path)
    context = initial.get('parallel_context')
    if not isinstance(context, dict) or not Path(context.get('control_file', '')).is_absolute():
        raise ValueError('只允许具有真实并行调度上下文的整话任务')
    control_path = Path(context['control_file']).resolve()
    if max_count is not None and (type(max_count) is not int or max_count < 1):
        raise ValueError('max_count须为正整数')
    lock_paths = sorted((state_path.with_suffix('.runtime.lock'), control_path.with_suffix('.dispatch.lock')))
    with ExitStack() as stack:
        for lock_path in lock_paths:
            lock = stack.enter_context(lock_path.open('a'))
            fcntl.flock(lock, fcntl.LOCK_EX)
        if digest(state_path) != expected_state_sha256 or digest(control_path) != expected_control_sha256:
            raise ValueError('STATE_OR_CONTROL_CHANGED')
        state = read_json(state_path)
        control = read_json(control_path)
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
                    'control_sha256': expected_control_sha256, 'image_calls': 0}
        status = evaluate_episode(state, root)
        if status.get('next_action') != 'SUBMIT_READY_EPISODE_REQUESTS':
            return {'status': status.get('next_action'), 'reserved': [], 'errors': status.get('errors', []),
                    'state_sha256': expected_state_sha256, 'control_sha256': expected_control_sha256,
                    'image_calls': 0}
        ids = status['eligible_panel_ids']
        preflight = evaluate_episode(state, root, 'candidate_batch', ids)
        ready = set(preflight.get('ready_panel_ids', []))
        records = {r['panel_id']: r for r in state['panels']}
        used = {(p.get('panel_id'), p.get('batch_id'), p.get('round_id')) for p in control['permits']
                if p.get('job_id') == job['job_id'] and p.get('epoch') == context['epoch']
                and p.get('status') in {'RESERVED', 'IN_FLIGHT', 'RESULT_UNKNOWN', 'COMPLETED'}}
        selected = [pid for pid in ids if pid in ready and (pid, 'EPISODE', records[pid]['round_id']) not in used][:free]
        if not selected:
            return {'status': 'INPUT_HOLD', 'reserved': [], 'reports': preflight.get('reports', []),
                    'state_sha256': expected_state_sha256, 'control_sha256': expected_control_sha256,
                    'image_calls': 0}
        new_state = copy.deepcopy(state)
        new_control = copy.deepcopy(control)
        by_id = {r['panel_id']: r for r in new_state['panels']}
        created = []
        reserved = []
        try:
            for pid in selected:
                row = by_id[pid]
                original = checked_file(root, row['package_manifest'])
                packet = read_json(original)
                if packet.get('dispatch_receipt') or packet.get('dispatch_source_package') or packet.get('round_context') != {
                        'batch_id': 'EPISODE', 'round_id': row['round_id'], 'attempt_id': row['attempt_id']}:
                    raise ValueError(f'{pid}:执行包已有回执或轮次不一致')
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
                row['package_manifest'] = {'path': str(new_path.relative_to(root)), 'sha256': digest(new_path)}
                new_control['permits'].append(permit)
                reserved.append({'panel_id': pid, 'permit_id': permit_id, 'receipt': receipt,
                                 'package_manifest': row['package_manifest']})
            if lease_mode:new_state['dispatch_ledger']=new_control['permits']
            _atomic_json(state_path, new_state)
            if not lease_mode:_atomic_json(control_path, new_control)
        except Exception:
            # Orphan packet copies are safe to remove only if no state row points to them.
            if digest(state_path) == expected_state_sha256:
                for path in created:
                    path.unlink(missing_ok=True)
            raise
        return {'status': 'RESERVED', 'reserved': reserved, 'state_sha256': digest(state_path),
                'control_sha256': digest(control_path), 'image_calls': 0,
                'next_step': 'compile_jobs并再次完整预检，通过后立即提交真实请求'}


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
        print(json.dumps({'status': 'HOLD', 'errors': [str(exc)], 'image_calls': 0}, ensure_ascii=False, indent=2))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
