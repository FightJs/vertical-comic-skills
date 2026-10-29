"""Real frozen gate replays, including missing live inputs and negative queries."""
from contextlib import contextmanager
import copy
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'scripts'), str(Path(__file__).parent)]
from dispatch_fixture import DispatchFixture
import immutable_inputs as immutable
import codex_reference_contract as contract


def corrupt_published_file(path, go, done):
    if go.wait(15): Path(path).write_bytes(b'SYNTHETIC_CHANGED_AFTER_READ'); done.set()


def semantic(value):
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items() if k not in {
            '_ready_observed_monotonic', 'file_reuse_statistics', 'qa_reuse_statistics', 'audit_reuse_statistics'}
            and not k.endswith('_seconds')}
    if isinstance(value, (list, tuple)): return [semantic(v) for v in value]
    return value


class ImmutableInputsTests(unittest.TestCase):
    def setUp(self):
        self.f = DispatchFixture(); self.addCleanup(self.f.close)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve(); self.store = self.base/'store'

    def capture(self, **kwargs): return immutable.capture(self.f.state_path, self.store, **kwargs)

    def test_real_gate_replay_is_semantically_equal_and_preserves_logical_paths(self):
        ref = self.capture(); replay = immutable.replay(ref)
        self.assertEqual(semantic(ref['result']), semantic(replay['result']))
        self.assertFalse(replay['dispatch_authorized']); self.assertEqual(replay['image_calls'], 0)
        self.assertEqual(replay['result']['ready_panel_ids'], ['P001', 'P002', 'P003', 'P004'])
        self.assertGreater(ref['captured_queries'], 0); self.assertGreater(ref['captured_files'], 0)
        with immutable.session(ref):
            logical = contract.checked_file(self.f.root, self.f.state['source_snapshot'])
            self.assertEqual(logical, self.f.root/self.f.state['source_snapshot']['path'])
            self.assertNotEqual(contract.physical_file(logical), logical)

    def test_entire_live_episode_and_control_tree_can_be_removed_before_replay(self):
        ref = self.capture()
        original = self.f.source.base.resolve(); original.rename(original.with_name(original.name+'-offline'))
        self.addCleanup(lambda: original.with_name(original.name+'-offline').rename(original))
        result = immutable.replay(ref)
        self.assertEqual(semantic(ref['result']), semantic(result['result']))

    def test_new_task_origin_and_changed_approval_index_do_not_leak_into_old_snapshot(self):
        from task_context import ORIGIN_FILE
        ref = self.capture(); index_path = self.f.root/self.f.state['approval_index']['path']
        old = contract.read_json(index_path)
        index_path.write_text(json.dumps({'policy': 'approval_index_v1', 'entries': []}), encoding='utf-8')
        (self.f.root/ORIGIN_FILE).write_text('{}', encoding='utf-8')
        with immutable.session(ref):
            self.assertFalse(contract.path_exists(self.f.root/ORIGIN_FILE))
            self.assertEqual(contract.read_json(index_path), old)
        self.assertEqual(immutable.replay(ref)['result']['ready_panel_ids'], ref['result']['ready_panel_ids'])

    def test_empty_directory_and_scan_filters_are_bound_exactly(self):
        empty = self.f.root/'empty'; empty.mkdir(); actual = immutable._run
        def observed(*args):
            contract.scan_directory(empty, recursive=True, suffixes=('.json',))
            return actual(*args)
        with patch.object(immutable, '_run', side_effect=observed): ref = self.capture()
        (empty/'new.json').write_text('{}', encoding='utf-8')
        with immutable.session(ref): self.assertEqual(contract.scan_directory(empty, recursive=True, suffixes=('.json',)), [])
        with self.assertRaisesRegex(ValueError, 'unrecorded directory'):
            with immutable.session(ref): contract.scan_directory(empty, recursive=True, suffixes=('.py',))

    def test_missing_observation_is_sticky_even_if_caller_catches_it(self):
        ref = self.capture()
        with self.assertRaisesRegex(ValueError, 'unrecorded'):
            with immutable.session(ref):
                try: contract.path_exists(self.f.root/'never-observed.json')
                except ValueError: pass
                contract.read_json(self.f.state_path)
        self.assertIsNone(contract._READ_VIEW.get()); self.assertIsNone(contract._FILE_SESSION.get())

    def test_raw_live_reads_directory_scans_and_writes_are_rejected(self):
        ref = self.capture()
        operations = [lambda: self.f.state_path.read_bytes(), lambda: list(self.f.root.iterdir()),
                      lambda: (self.f.root/'not-written.json').write_text('{}', encoding='utf-8')]
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, 'READ_SET_HOLD'):
                with immutable.session(ref): operation()
        self.assertFalse((self.f.root/'not-written.json').exists())

    def test_read_and_write_guards_do_not_require_optional_os_access_mask(self):
        ref=self.capture()
        # Some platforms do not export this optional constant. It must not be
        # needed for either permitted reads or the rejection of writes.
        with patch.object(immutable.os,'O_ACCMODE',None,create=True):
            self.assertEqual(immutable.replay(ref)['result']['ready_panel_ids'],['P001','P002','P003','P004'])
            with self.assertRaisesRegex(ValueError,'write attempted'):
                with immutable.session(ref):(self.f.root/'must-not-write').write_bytes(b'X')
        self.assertFalse((self.f.root/'must-not-write').exists())

    def test_mode_change_cannot_reuse_the_snapshot_as_formal_permission(self):
        from _historical_fixture import evaluate
        ref = self.capture()
        with self.assertRaisesRegex(ValueError, 'mode/options changed'):
            with immutable.session(ref): evaluate(self.f.state, self.f.root, 'generate_batch', ['P001'])

    def test_no_memo_or_view_can_wrap_a_snapshot_replay(self):
        ref = self.capture()
        with contract.file_session(), self.assertRaisesRegex(ValueError, 'OWN_TRANSACTION'): immutable.replay(ref)
        with immutable.session(ref), self.assertRaisesRegex(ValueError, 'OWN_TRANSACTION'): immutable.replay(ref)

    def test_content_tampering_and_wrong_scope_are_rejected_before_gate(self):
        ref = self.capture(); other = {**ref, 'scope': {**ref['scope'], 'episode_id': 'E999'}}
        with self.assertRaisesRegex(ValueError, 'MANIFEST_HOLD'): immutable.replay(other)
        view = immutable.ReadView(ref); physical = view.files[str(self.f.state_path)]
        physical.write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'CONTENT_CHANGED'): immutable.replay(ref)

    def test_actual_executing_toolchain_must_match_captured_version(self):
        from execution_contract import toolchain
        ref = self.capture(); changed = copy.deepcopy(toolchain()); changed['release'] = 'different'
        with patch('execution_contract.toolchain', return_value=changed):
            with self.assertRaisesRegex(ValueError, 'TOOLCHAIN_CHANGED'): immutable.replay(ref)

    def test_external_publication_mutation_after_preflight_discards_replay(self):
        from _historical_fixture import evaluate
        ref = self.capture(); view = immutable.ReadView(ref)
        target = view.files[str(self.f.state_path)]
        ctx = multiprocessing.get_context('spawn'); go = ctx.Event(); done = ctx.Event()
        process = ctx.Process(target=corrupt_published_file, args=(target, go, done)); process.start()
        def changed(*args, **kwargs):
            result = evaluate(*args, **kwargs); go.set()
            if not done.wait(15): raise ValueError('SYNC_TIMEOUT')
            return result
        try:
            with patch('staged_workflow.evaluate', side_effect=changed):
                with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'): immutable.replay(ref)
            process.join(15); self.assertEqual(process.exitcode, 0)
        finally:
            if process.is_alive(): process.terminate(); process.join(5)

    def test_real_cli_capture_and_cold_replay_after_live_data_removed(self):
        script = Path(immutable.__file__)
        make = subprocess.run([sys.executable, '-B', str(script), 'capture', '--state', str(self.f.state_path),
            '--store', str(self.store)], capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(make.returncode, 0, make.stdout+make.stderr)
        ref = json.loads(make.stdout); path = self.base/'reference.json'; path.write_text(json.dumps(ref), encoding='utf-8')
        original = self.f.source.base.resolve(); original.rename(original.with_name(original.name+'-offline'))
        self.addCleanup(lambda: original.with_name(original.name+'-offline').rename(original))
        replay = subprocess.run([sys.executable, '-B', str(script), 'replay', '--reference', str(path)],
            capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(replay.returncode, 0, replay.stdout+replay.stderr)
        value = json.loads(replay.stdout)
        self.assertEqual(semantic(ref['result']), semantic(value['result']))
        self.assertFalse(value['dispatch_authorized'])


    def bind(self, ref, head=None):
        return immutable.bind(ref, contract.digest(self.f.state_path), contract.digest(self.f.control_path), head)

    def test_bind_is_candidate_only_preserves_state_and_uses_head_cas(self):
        ref = self.capture(); before = [p.read_bytes() for p in (self.f.state_path, self.f.control_path)]
        first = self.bind(ref)
        self.assertEqual(first['status'], 'BOUND_NOT_DISPATCHABLE')
        self.assertFalse(first['dispatch_authorized'])
        self.assertEqual(before, [p.read_bytes() for p in (self.f.state_path, self.f.control_path)])
        self.assertEqual(immutable.head_status(self.f.state_path)['status'], 'HEAD_CURRENT_NOT_DISPATCHABLE')
        with self.assertRaisesRegex(ValueError, 'head changed'): self.bind(ref)
        second = self.bind(ref, first['head_sha256'])
        self.assertEqual(second['revision'], 2)
        self.assertNotEqual(first['head_sha256'], second['head_sha256'])
        with self.assertRaisesRegex(ValueError, 'head changed'): self.bind(ref, first['head_sha256'])

    def test_bind_rejects_changed_current_state_and_control(self):
        for attr in ('state_path', 'control_path'):
            with self.subTest(attr=attr):
                ref = self.capture(); source = getattr(self.f, attr); old = source.read_bytes()
                expected = (contract.digest(self.f.state_path), contract.digest(self.f.control_path))
                source.write_bytes(old+b' ')
                try:
                    with self.assertRaisesRegex(ValueError, 'BIND_CONFLICT'):
                        immutable.bind(ref, *expected, None)
                finally: source.write_bytes(old)
        self.assertFalse((self.f.state_path.parent/'input_read_head.json').exists())

    def test_limited_and_candidate_snapshots_cannot_bind_full_authority(self):
        for options in ({'requested': {'limit': 1, 'excluded': []}}, {'check': 'candidate_batch'}):
            with self.subTest(options=options):
                ref = self.capture(**options)
                with self.assertRaisesRegex(ValueError, 'full reservation scope'): self.bind(ref)

    def test_head_expires_on_owner_writes_without_restoring_old_state(self):
        self.assertEqual(immutable.head_status(self.f.state_path)['status'], 'HEAD_MISSING')
        ref = self.capture(); self.bind(ref)
        self.f.state_path.write_bytes(self.f.state_path.read_bytes()+b' ')
        value = immutable.head_status(self.f.state_path)
        self.assertEqual(value['status'], 'HEAD_STALE'); self.assertEqual(value['changed'], ['state'])
        self.f.control_path.write_bytes(self.f.control_path.read_bytes()+b' ')
        self.assertEqual(immutable.head_status(self.f.state_path)['changed'], ['state', 'control'])

    def test_expensive_publication_and_gate_run_outside_owner_lock(self):
        import authority_updates
        locked = []; actual_lock = authority_updates.state_write_lock
        actual_run = immutable._run; actual_verify = immutable.publication.verify
        @contextmanager
        def observed_lock(*args, **kwargs):
            with actual_lock(*args, **kwargs):
                locked.append(True)
                try: yield
                finally: locked.pop()
        def observed_run(*args, **kwargs):
            self.assertFalse(locked); return actual_run(*args, **kwargs)
        def observed_verify(*args, **kwargs):
            self.assertFalse(locked); return actual_verify(*args, **kwargs)
        ref = self.capture()
        with patch.object(authority_updates, 'state_write_lock', observed_lock), \
             patch.object(immutable, '_run', observed_run), \
             patch.object(immutable.publication, 'verify', observed_verify):
            self.bind(ref)

    def test_real_cli_bind(self):
        ref = self.capture(); path = self.base/'reference.json'; path.write_text(json.dumps(ref), encoding='utf-8')
        result = subprocess.run([sys.executable, '-B', str(Path(immutable.__file__)), 'bind',
            '--reference', str(path), '--expected-state-sha256', contract.digest(self.f.state_path),
            '--expected-control-sha256', contract.digest(self.f.control_path)],
            capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'BOUND_NOT_DISPATCHABLE')


if __name__ == '__main__': unittest.main()
