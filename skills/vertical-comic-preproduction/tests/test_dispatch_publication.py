"""Stage-2 candidate publication cannot opt a production RV into short locks."""
from pathlib import Path
import json
import multiprocessing
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'scripts'), str(Path(__file__).parent)]
import dispatch_publication as pub
from codex_reference_contract import digest

SCOPE = {'book_id': 'SYNTHETIC', 'episode_id': 'E000'}


def competing_switch(root, version, token, ready, go, result):
    ready.set()
    if not go.wait(15):
        result.put('SYNC_TIMEOUT'); return
    try:
        pub.switch_candidate(root, SCOPE, version, token)
        result.put('SWITCHED')
    except ValueError as exc:
        result.put(str(exc).split(':')[0])


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()/'publication'

    def publish(self, raw=b'approved original bytes'):
        return pub.publish(self.root, SCOPE, {'prompt.txt': raw, 'references/image.png': b'image bytes'})['version']

    def test_versions_preserve_exact_bytes_and_never_activate_a_runtime(self):
        v1 = self.publish(); before = (self.root/'versions'/v1/'manifest.json').read_bytes()
        self.assertEqual(self.publish(), v1)
        v2 = self.publish(b'changed bytes')
        self.assertNotEqual(v1, v2)
        self.assertEqual((self.root/'versions'/v1/'manifest.json').read_bytes(), before)
        self.assertEqual((self.root/'versions'/v1/'files/prompt.txt').read_bytes(), b'approved original bytes')
        self.assertIsNone(pub.read_head(self.root, SCOPE)['head'])
        selected = pub.switch_candidate(self.root, SCOPE, v1, None)
        self.assertFalse(selected['production_enabled'])
        self.assertEqual(selected['head']['status'], pub.STATUS)
        selected['head']['version'] = 'caller mutation'
        self.assertEqual(pub.read_head(self.root, SCOPE)['head']['version'], v1)

    def test_stale_head_and_aba_rejected_without_automatic_retry(self):
        v1 = self.publish(); v2 = self.publish(b'new')
        a = pub.switch_candidate(self.root, SCOPE, v1, None)
        b = pub.switch_candidate(self.root, SCOPE, v2, a['head_sha256'])
        c = pub.switch_candidate(self.root, SCOPE, v1, b['head_sha256'])
        self.assertEqual(c['head']['revision'], 3)
        self.assertNotEqual(c['head_sha256'], a['head_sha256'])
        with self.assertRaisesRegex(ValueError, 'PUBLICATION_CONFLICT'):
            pub.switch_candidate(self.root, SCOPE, v2, a['head_sha256'])
        self.assertEqual(pub.read_head(self.root, SCOPE), c)

    def test_mutation_and_new_member_block_reuse_or_switch(self):
        v1 = self.publish()
        path = self.root/'versions'/v1/'files/prompt.txt'; original = path.read_bytes()
        path.write_bytes(b'tampered')
        for operation in (lambda: self.publish(), lambda: pub.switch_candidate(self.root, SCOPE, v1, None)):
            with self.assertRaisesRegex(ValueError, 'PUBLICATION_CONTENT_CHANGED'): operation()
        self.assertFalse((self.root/'candidate.json').exists())
        path.write_bytes(original)
        extra = path.with_name('extra.txt'); extra.write_bytes(b'new')
        with self.assertRaisesRegex(ValueError, 'membership'): pub.verify(self.root, v1, SCOPE)

    def test_wrong_scope_and_nonportable_or_alias_paths_rejected(self):
        v1 = self.publish()
        with self.assertRaisesRegex(ValueError, 'MANIFEST_HOLD'):
            pub.verify(self.root, v1, {**SCOPE, 'episode_id': 'E999'})
        for files in ({'../escape': b'x'}, {'CON.txt': b'x'}, {'A/x': b'x', 'a/y': b'y'},
                      {'a': b'x', 'a/b': b'y'}, {'x': 'not bytes'}):
            with self.subTest(files=files), self.assertRaises(ValueError):
                pub.publish(self.root, SCOPE, files)

    def test_symlink_store_or_member_rejected(self):
        v1 = self.publish()
        link = self.root.parent/'alias'
        try: link.symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError): self.skipTest('symlink unavailable')
        with self.assertRaisesRegex(ValueError, 'PATH_HOLD'): pub.read_head(link, SCOPE)
        path = self.root/'versions'/v1/'files/prompt.txt'; path.unlink()
        path.symlink_to(self.root/'versions'/v1/'manifest.json')
        with self.assertRaisesRegex(ValueError, 'PATH_HOLD'): pub.verify(self.root, v1, SCOPE)

    def test_failed_publication_or_switch_leaves_old_head_and_versions(self):
        v1 = self.publish(); head = pub.switch_candidate(self.root, SCOPE, v1, None)
        with patch.object(pub.os, 'rename', side_effect=OSError('synthetic publication interruption')):
            with self.assertRaises(OSError): self.publish(b'not published')
        self.assertFalse(list((self.root/'versions').glob('.staging-*')))
        v2 = self.publish(b'unreferenced candidate')
        with patch.object(pub, 'atomic_json', side_effect=OSError('synthetic pre-replace interruption')):
            with self.assertRaises(OSError): pub.switch_candidate(self.root, SCOPE, v2, head['head_sha256'])
        self.assertEqual(pub.read_head(self.root, SCOPE), head)
        pub.verify(self.root, v1, SCOPE); pub.verify(self.root, v2, SCOPE)

    def test_processes_competing_for_same_head_have_exactly_one_winner(self):
        v1 = self.publish(); v2 = self.publish(b'new')
        head = pub.switch_candidate(self.root, SCOPE, v1, None)
        ctx = multiprocessing.get_context('spawn'); go = ctx.Event(); result = ctx.Queue()
        ready = [ctx.Event(), ctx.Event()]
        processes = [ctx.Process(target=competing_switch,
            args=(self.root, v2, head['head_sha256'], event, go, result)) for event in ready]
        try:
            for process in processes: process.start()
            self.assertTrue(all(event.wait(15) for event in ready)); go.set()
            self.assertCountEqual([result.get(timeout=15), result.get(timeout=15)], ['SWITCHED', 'PUBLICATION_CONFLICT'])
            for process in processes: process.join(15); self.assertEqual(process.exitcode, 0)
        finally:
            for process in processes:
                if process.is_alive(): process.terminate(); process.join(5)
            result.close(); result.join_thread()
        self.assertEqual(pub.read_head(self.root, SCOPE)['head']['revision'], 2)


class UnsupportedProtocolTests(unittest.TestCase):
    def setUp(self):
        from dispatch_fixture import DispatchFixture
        self.f = DispatchFixture(); self.addCleanup(self.f.close)

    def mark(self, value=None):
        self.f.state['dispatch_consistency'] = value
        self.f.flush()

    def test_standard_gate_rejects_marker_even_without_full_execution_contract(self):
        from execution_contract import state_errors
        for marker in (None, False, {}, {'policy': pub.POLICY}, {'policy': 'future'}):
            self.assertIn('DISPATCH_PROTOCOL_UNSUPPORTED', ';'.join(state_errors({'dispatch_consistency': marker}, self.f.root)))

    def test_marked_state_cannot_reserve_even_if_capacity_full(self):
        from episode_dispatch_queue import reserve_ready
        reserved = reserve_ready(self.f.state_path, digest(self.f.state_path), digest(self.f.control_path), 2)
        self.assertEqual(len(reserved['reserved']), 2)
        self.f.state = json.loads(self.f.state_path.read_text())
        packets = set(self.f.root.rglob('*.dispatch-*.json'))
        self.mark({'policy': pub.POLICY})
        before = self.f.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'DISPATCH_PROTOCOL_UNSUPPORTED'):
            reserve_ready(self.f.state_path, digest(self.f.state_path), digest(self.f.control_path))
        self.assertEqual(self.f.state_path.read_bytes(), before)
        self.assertEqual(set(self.f.root.rglob('*.dispatch-*.json')), packets)

    def test_marked_state_cannot_accept_a_new_lease(self):
        from slot_leases import allocate
        self.mark()
        before = self.f.control_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'DISPATCH_PROTOCOL_UNSUPPORTED'):
            allocate(self.f.control_path, digest(self.f.control_path), {'synthetic-job': 1}, old_writers_stopped=True)
        self.assertEqual(self.f.control_path.read_bytes(), before)

    def test_configuration_cannot_silently_drop_protocol_marker(self):
        from usage_config import read_config
        path = self.f.root/'candidate-config.json'; path.write_text(json.dumps({'dispatch_consistency': None}))
        with self.assertRaisesRegex(ValueError, 'DISPATCH_PROTOCOL_UNSUPPORTED'): read_config(path)

    def test_marked_control_cannot_silently_use_old_lease_or_reserve(self):
        from episode_dispatch_queue import reserve_ready
        from slot_leases import allocate
        control = json.loads(self.f.control_path.read_text()); control['dispatch_consistency'] = None
        self.f.control_path.write_text(json.dumps(control))
        token = digest(self.f.control_path); before = self.f.control_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'DISPATCH_PROTOCOL_UNSUPPORTED'):
            reserve_ready(self.f.state_path, digest(self.f.state_path), token)
        with self.assertRaisesRegex(ValueError, 'DISPATCH_PROTOCOL_UNSUPPORTED'):
            allocate(self.f.control_path, token, {j['job_id']: 0 for j in control['jobs']})
        self.assertEqual(self.f.control_path.read_bytes(), before)

    def test_marked_state_writers_reject_before_evidence_or_history_writes(self):
        from production_runtime import commit_updates, authorize_episode_repair, record_episode_diagnosis
        from slot_leases import release_unsubmitted
        self.mark()
        before = self.f.state_path.read_bytes(); token = digest(self.f.state_path)
        for operation in (lambda: commit_updates(self.f.state_path, token, [{'panel_id': 'P001'}]),
                          lambda: authorize_episode_repair(self.f.state_path, token, 'missing.json'),
                          lambda: record_episode_diagnosis(self.f.state_path, token, 'missing.json'),
                          lambda: release_unsubmitted(self.f.state_path, token, ['P001'])):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, 'DISPATCH_PROTOCOL_UNSUPPORTED'):
                operation()
        self.assertEqual(self.f.state_path.read_bytes(), before)
        self.assertFalse((self.f.state_path.parent/'runtime_history').exists())


if __name__ == '__main__': unittest.main()
