"""Whole-episode handoff against real frozen gates, with isolated synthetic evidence."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts'), str(Path(__file__).parent)]
import test_direct_handoff as fixtures
from test_receiver_audit import decisions
import production_runtime as runtime
import handoff_scope as scope


class EpisodeHandoffTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DirectHandoffTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.fixture.index.update(policy=scope.EPISODE_POLICY, production_window_policy=scope.EPISODE_WINDOW)
        episode = self.fixture.index['episodes'][0]
        episode.pop('halves')
        for row in episode['panels']:
            row['classification'] = 'READY'
        self.fixture.save()
        self.ids = episode['panel_ids']

    def test_one_compile_same_full_decisions_no_half_scope(self):
        f = self.fixture
        before = fixtures.h.files(f.package)
        expected = runtime.compile_jobs(f.state, f.template, self.ids, input_audit=True)
        with patch.object(runtime, 'compile_jobs', wraps=runtime.compile_jobs) as compile_call:
            result = runtime.receiver_audit(f.state, f.template, None, self.ids)
        self.assertEqual(compile_call.call_count, 1)
        self.assertEqual(decisions(expected), decisions(result['all_inputs']))
        self.assertEqual(result['ready_panel_ids'], self.ids)
        self.assertNotIn('h001', result)
        self.assertFalse(result['dispatch_authorized'])
        self.assertEqual(before, fixtures.h.files(f.package))

    def test_real_zip_release_directory_and_transport_roundtrip(self):
        f = self.fixture
        f.scope_task()
        f.test_direct_bound_run_real_full_episode_gates_and_conditional_release()
        report = json.loads((f.base / 'rehearsal/演练报告.json').read_text())
        self.assertEqual(report['ready_panel_count'], 4)
        self.assertEqual(report['results'][0]['ready_panel_ids'], self.ids)
        self.assertIn('--episode-scope', report['results'][0]['argv'])
        self.assertNotIn('ready_h001_count', report)
        from comic_start import receive
        from handoff_transport import export
        # Use the public transport API, followed by the real package-only receiver.
        transported = export(f.base / '正式交接包.zip', f.base / 'transport', max_file_bytes=1024 * 1024)
        result = receive(f.base / 'transport' / transported['files'][0]['path'], output=f.base / 'transport-received')
        self.assertEqual(result['status'], 'READY_FOR_PRODUCTION_ROUTING', result)

    def test_mixed_formats_and_relabelled_old_approval_rejected(self):
        f = self.fixture
        digest = fixtures.d.input_review(f.package, f.index)['approved_input_digest']
        e = f.index['episodes'][0]
        e['halves'] = {'H001': self.ids[:2], 'H002': self.ids[2:]}
        f.save()
        with self.assertRaisesRegex(ValueError, 'halves'):
            fixtures.h.audit_index(f.package)
        e.pop('halves')
        e['panels'][-1]['classification'] = 'PREPARED_H002'
        f.save()
        with self.assertRaisesRegex(ValueError, '混合'):
            fixtures.h.audit_index(f.package)
        e['panels'][-1]['classification'] = 'READY'
        f.index['policy'] = scope.LEGACY_POLICY
        with self.assertRaises(ValueError):
            fixtures.d.input_review(f.package, f.index)
        f.index.pop('production_window_policy')
        e['halves'] = {'H001': self.ids[:2], 'H002': self.ids[2:]}
        for i, row in enumerate(e['panels']):
            row['classification'] = 'READY_H001' if i < 2 else 'PREPARED_H002'
        self.assertNotEqual(digest, fixtures.d.input_review(f.package, f.index)['approved_input_digest'])

    def test_later_missing_authority_is_not_hidden(self):
        f = self.fixture
        f.state['production_authorization']['panel_ids'].remove(self.ids[-1])
        result = runtime.receiver_audit(f.state, f.template, None, self.ids)
        self.assertNotIn(self.ids[-1], result['ready_panel_ids'])
        self.assertIn('当前格不在已授权生产范围', json.dumps(result, ensure_ascii=False))

    def test_unknown_attempt_still_blocks_formal_handoff(self):
        f = self.fixture
        f.scope_task()
        f.state['panels'][-1]['status'] = 'RESULT_UNKNOWN'
        f.refresh_template()
        with self.assertRaises(ValueError):
            fixtures.h.audit_index(f.package)

    def test_frozen_runtime_without_new_capability_cannot_fall_back(self):
        from test_receiver_audit import ReceiverAuditTests
        holder = ReceiverAuditTests()
        holder.fixture = self.fixture
        cap = self.fixture.package / 'runtime/skills/vertical-comic-preproduction/scripts/runtime_capabilities.json'
        data = json.loads(cap.read_text())
        data.pop('receiver_episode_audit')
        holder.set_capability(data)
        _, _, _, report = self.fixture.pipeline()
        self.assertEqual(report['status'], 'HOLD')
        self.assertIn('不能降级', str(report))

    def test_cli_full_scope_and_mixed_options(self):
        f = self.fixture
        cmd = [sys.executable, '-B', runtime.__file__, '--state', str(f.template / f.state_ref['path']),
               '--action', 'receiver-audit', '--episode-scope', '--panels', *self.ids]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['ready_panel_ids'], self.ids)
        mixed = subprocess.run(cmd + ['--h001-panels', self.ids[0]], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(mixed.returncode, 0)

    def test_source_order_and_read_snapshot_remain_strict(self):
        f = self.fixture
        for order in [self.ids[:1], list(reversed(self.ids))]:
            with self.assertRaises(ValueError):
                runtime.receiver_audit(f.state, f.template, None, order)
        original = runtime.preparation_report
        def mutate(state, root):
            result = original(state, root)
            path = root / state['shot_manifest']['path']
            path.write_text(path.read_text() + ' ')
            return result
        with patch.object(runtime, 'preparation_report', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
                runtime.receiver_audit(f.state, f.template, None, self.ids)

    def test_scope_lengths_and_dependency_classifications(self):
        index = {'policy': scope.EPISODE_POLICY, 'production_window_policy': scope.EPISODE_WINDOW}
        for count in (1, 3, 4, 35):
            ids = ['P%03d' % n for n in range(1, count + 1)]
            e = {'episode_id': 'E000', 'panel_ids': ids,
                 'panels': [{'panel_id': pid, 'classification': 'READY'} for pid in ids]}
            scope.validate_episode(index, e)
            self.assertEqual(scope.ready_ids(index, e), ids)
            e['panels'][-1]['classification'] = 'WAIT_DEPENDENCY'
            self.assertEqual(scope.ready_ids(index, e), ids[:-1])


if __name__ == '__main__':
    unittest.main()
