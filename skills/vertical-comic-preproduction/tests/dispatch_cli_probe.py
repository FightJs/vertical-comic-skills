#!/usr/bin/env python3
"""Instrument the unmodified dispatch CLI on an isolated synthetic fixture only.

This runs its real argparse/main and write path via runpy; wrappers observe real
operations, never substitute validation decisions. Timings include probe cost.
"""
import argparse
from contextlib import contextmanager, ExitStack, redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import runpy
import sys
import time
from unittest.mock import patch


def sample(scripts, state_path, limit, managed=False):
    scripts = Path(scripts).resolve()
    sys.path.insert(0, str(scripts))
    import codex_reference_contract as contract
    import execution_contract
    import batch_workflow
    import panel_readiness
    import platform_io
    import task_context
    state_path = Path(state_path).resolve()
    root = state_path.parent.parent
    state = contract.read_json(state_path)
    if state.get('parallel_context', {}).get('job_id') != 'synthetic-job':
        raise ValueError('Benchmark accepts only DispatchFixture synthetic inputs')
    # Only checker binding changes between code versions. All creative inputs
    # and approvals stay byte-identical in the same fixture directory.
    state['toolchain'] = execution_contract.toolchain()
    platform_io.atomic_json(state_path, state)
    control_path = Path(state['parallel_context']['control_file'])
    control_before = control_path.read_bytes()
    packets = {r['panel_id']: contract.read_json(contract.checked_file(root, r['package_manifest']))
               for r in state['panels']}
    args = [str(scripts / 'episode_dispatch_queue.py'), '--state', str(state_path),
            '--expected-state-sha256', contract.digest(state_path),
            '--expected-control-sha256', contract.digest(control_path), '--max-count', str(limit)]
    if managed:
        import managed_dispatch
        managed_dispatch.admit(state_path, contract.digest(state_path), contract.digest(control_path),
            old_writers_stopped=True, immutable_inputs=True, saver_protocol='exclusive_evidence_v1',
            reason='SYNTHETIC CLI benchmark')
        state = contract.read_json(state_path)
        arguments = root/'benchmark-managed-arguments.json'
        platform_io.atomic_json(arguments, {'expected_state':contract.digest(state_path),
            'expected_control':contract.digest(control_path),'max_count':limit,'request_id':'benchmark-request'})
        args = [str(scripts/'managed_dispatch.py'),'--state',str(state_path),'--action','reserve','--arguments',str(arguments)]
    counts = {'json_parses': 0, 'file_hashes': 0, 'hash_bytes': 0,
              'input_checks': 0, 'preparation_checks': 0, 'contract_checks': 0, 'task_checks': 0}
    locks = []
    actual_bytes, actual_open, actual_loads = Path.read_bytes, Path.open, json.loads
    actual_sha256 = hashlib.sha256
    file_buffers = {}
    actual_lock = platform_io.file_lock
    def remember(data):
        if isinstance(data, bytes):
            file_buffers[id(data)] = data  # Retain identity only inside this probe.
        return data
    def read_bytes(path):
        return remember(actual_bytes(path))
    class BinaryReader:
        def __init__(self, value): self.value = value
        def read(self, *args): return remember(self.value.read(*args))
        def __enter__(self): self.value.__enter__(); return self
        def __exit__(self, *args): return self.value.__exit__(*args)
        def __getattr__(self, name): return getattr(self.value, name)
    def open_path(path, *args, **kwargs):
        value = actual_open(path, *args, **kwargs)
        mode = args[0] if args else kwargs.get('mode', 'r')
        return BinaryReader(value) if mode == 'rb' else value
    class MeasuredHash:
        def __init__(self, value): self.value, self.counted = value, False
        def observe(self, data):
            if id(data) in file_buffers and file_buffers[id(data)] is data:
                if not self.counted:
                    counts['file_hashes'] += 1
                    self.counted = True
                counts['hash_bytes'] += len(data)
        def update(self, data): self.observe(data); return self.value.update(data)
        def __getattr__(self, name): return getattr(self.value, name)
    def sha256(data=None, **kwargs):
        value = MeasuredHash(actual_sha256(**kwargs) if data is None else actual_sha256(data, **kwargs))
        if data is not None: value.observe(data)
        return value
    def loads(*args, **kwargs):
        counts['json_parses'] += 1
        return actual_loads(*args, **kwargs)
    def counted(key, actual):
        def run(*args, **kwargs):
            counts[key] += 1
            return actual(*args, **kwargs)
        return run
    @contextmanager
    def lock(path, *args, **kwargs):
        started = time.perf_counter()
        with actual_lock(path, *args, **kwargs):
            acquired = time.perf_counter()
            name=Path(path).name
            kind=('episode_state' if name.endswith('.runtime.lock') else
                  'shared_dispatch' if name.endswith('.dispatch.lock') else
                  'immutable_publication' if name=='publication.lock' else
                  'result_intents' if name=='intents.lock' else 'other')
            row = {'kind':kind,'path':str(path),'wait_seconds': acquired - started}
            locks.append(row)
            try:
                yield
            finally:
                row['hold_seconds'] = time.perf_counter() - acquired
    output = io.StringIO()
    started, cpu = time.perf_counter(), time.process_time()
    with ExitStack() as stack:
        for owner, name, value in (
                (Path, 'read_bytes', read_bytes), (Path, 'open', open_path),
                (hashlib, 'sha256', sha256), (json, 'loads', loads),
                (platform_io, 'file_lock', lock),
                (batch_workflow, 'input_errors', counted('input_checks', batch_workflow.input_errors)),
                (panel_readiness, '_report', counted('preparation_checks', panel_readiness._report)),
                (execution_contract, 'state_errors', counted('contract_checks', execution_contract.state_errors)),
                (task_context, 'state_errors', counted('task_checks', task_context.state_errors))):
            stack.enter_context(patch.object(owner, name, value))
        # Managed admission preloads publisher modules before timing. Observe
        # their independent locks too, without counting them as dispatch locks.
        for module_name in ('dispatch_publication','authority_updates'):
            module=sys.modules.get(module_name)
            if module is not None:stack.enter_context(patch.object(module,'file_lock',lock))
        stack.enter_context(patch.object(sys, 'argv', args))
        stack.enter_context(redirect_stdout(output))
        try:
            runpy.run_path(args[0], run_name='__main__')
        except SystemExit as exc:
            exit_code = exc.code
        else:
            raise AssertionError('Dispatch CLI must terminate through main')
    seconds, cpu_seconds = time.perf_counter() - started, time.process_time() - cpu
    result = json.loads(output.getvalue())
    if exit_code != 0 or result.get('status') != 'RESERVED':
        raise AssertionError(result)
    after = contract.read_json(state_path)
    if control_before != control_path.read_bytes():
        raise AssertionError('Slot-lease dispatch changed shared control')
    receipts, permit_ids = [], set()
    for item in result['reserved']:
        pid, receipt = item['panel_id'], item['receipt']
        permit_id = item['permit_id']
        if permit_id in permit_ids or receipt['permit_id'] != permit_id:
            raise AssertionError('Duplicate or unbound receipt')
        permit_ids.add(permit_id)
        row = next(r for r in after['panels'] if r['panel_id'] == pid)
        packet = contract.read_json(contract.checked_file(root, row['package_manifest']))
        if packet.pop('dispatch_receipt') != receipt:
            raise AssertionError('Packet/receipt mismatch')
        source = packet.pop('dispatch_source_package')
        original = next(r for r in state['panels'] if r['panel_id'] == pid)
        context = state['parallel_context']
        for key, value in {'job_id': context['job_id'], 'worker_id': context['worker_id'],
                           'epoch': context['epoch'], 'batch_id': 'EPISODE',
                           'round_id': original['round_id'], 'attempt_id': original['attempt_id']}.items():
            if receipt.get(key) != value:
                raise AssertionError('Receipt is not bound to original job/round/attempt: ' + key)
        if source != original['package_manifest'] or packet != packets[pid]:
            raise AssertionError('Dispatch changed approved packet content')
        expected = {**receipt, 'panel_id': pid, 'status': 'RESERVED'}
        if after['dispatch_ledger'].count(expected) != 1:
            raise AssertionError('Receipt must occur once in ledger')
        receipts.append({'panel_id': pid, 'receipt': {k: v for k, v in receipt.items() if k != 'permit_id'},
                         'source_package': source})
        row['package_manifest'] = copy.deepcopy(source)
    after.pop('dispatch_ledger', None)
    if managed:
        after.pop('reservation_requests', None); after.pop('last_dispatch_read_set', None)
    expected_state = copy.deepcopy(state)
    expected_state.pop('dispatch_ledger', None)
    if after != expected_state:
        raise AssertionError('Unexpected state mutation beyond receipt ledger and packet references')
    return {'selected': [r['panel_id'] for r in result['reserved']], 'seconds': seconds,
            'cpu_seconds': cpu_seconds, 'operations': counts, 'locks': locks,
            'file_hash_counter': 'sha256_over_file_buffers_including_legacy_streaming_v2',
            'dispatch_metrics': result.get('dispatch_metrics'),
            'normalized_result': {'status': result['status'], 'image_calls': result['image_calls'],
                                  'receipts': receipts}, 'receipt_binding_verified': True,
            'dispatch_script_sha256': contract.digest(scripts / 'episode_dispatch_queue.py'),
            'outer_run_lock': None, 'image_calls': result['image_calls']}


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scripts', required=True)
    parser.add_argument('--fixture-state', required=True)
    parser.add_argument('--limit', type=int, default=1)
    parser.add_argument('--managed', action='store_true')
    args = parser.parse_args()
    print(json.dumps(sample(args.scripts, args.fixture_state, args.limit, args.managed), ensure_ascii=False))
