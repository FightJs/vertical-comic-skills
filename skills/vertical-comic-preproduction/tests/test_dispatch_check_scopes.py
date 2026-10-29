"""Full global checks, bounded candidates, intact dependencies; synthetic only."""
import _historical_fixture
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts'), str(Path(__file__).parent)]
from dispatch_fixture import DispatchFixture
from codex_reference_contract import checked_file, digest, file_session, read_json
from panel_readiness import report as preparation
from platform_io import atomic_json
from _historical_fixture import evaluate
from episode_dispatch_queue import reserve_ready
from test_dispatch_preflight import original_selection
import production_evidence as batch_workflow


class DispatchCheckScopeTests(unittest.TestCase):
    def setUp(self):
        self.f = DispatchFixture(slots=4)
        self.addCleanup(self.f.close)
        self.state, self.root = self.f.state, self.f.root

    def bounded(self, limit=1, excluded=()):
        with file_session():
            return evaluate(self.state, self.root, 'reservation_batch',
                            {'limit': limit, 'excluded': list(excluded)})

    def reserve(self, limit=1):
        return reserve_ready(self.f.state_path, digest(self.f.state_path), digest(self.f.control_path), limit)

    def rewrite_packet(self, pid, change):
        row = next(r for r in self.state['panels'] if r['panel_id'] == pid)
        path = checked_file(self.root, row['package_manifest'])
        packet = read_json(path)
        change(packet)
        atomic_json(path, packet)
        row['package_manifest'] = {'path': path.relative_to(self.root).as_posix(), 'sha256': digest(path)}
        row['shot_subset'] = copy.deepcopy(row['package_manifest'])
        self.f.flush()

    def publish_shots(self, shots):
        # Preserve the original approvals; only unchanged rows can reuse them.
        path = self.root / 'scope-test-shots.json'
        atomic_json(path, shots)
        self.state['shot_manifest'] = {'path': path.name, 'sha256': digest(path)}
        audit = read_json(checked_file(self.root, self.state['semantic_audit']))
        audit['shot_manifest'] = self.state['shot_manifest']
        audit_path = self.root / 'scope-test-audit.json'
        atomic_json(audit_path, audit)
        self.state['semantic_audit'] = {'path': audit_path.name, 'sha256': digest(audit_path)}
        self.f.control['jobs'][0]['frozen_inputs']['shot_manifest'] = copy.deepcopy(self.state['shot_manifest'])
        self.f.flush()

    def assert_no_writes(self, expected_action=None, *, exception=None):
        before_state, before_control = self.f.state_path.read_bytes(), self.f.control_path.read_bytes()
        before_packets = set(self.root.glob('*.dispatch-*.json'))
        with patch.object(batch_workflow, 'input_errors', wraps=batch_workflow.input_errors) as deep:
            if exception:
                with self.assertRaisesRegex(ValueError, exception):
                    self.reserve()
            else:
                result = self.reserve()
                self.assertEqual(result['status'], expected_action, result)
                self.assertEqual(result['reserved'], [])
        self.assertEqual(deep.call_count, 0)
        self.assertEqual(self.f.state_path.read_bytes(), before_state)
        self.assertEqual(self.f.control_path.read_bytes(), before_control)
        self.assertEqual(set(self.root.glob('*.dispatch-*.json')), before_packets)

    def test_later_packet_local_error_does_not_block_first_and_is_not_deep_checked(self):
        self.rewrite_packet('P004', lambda p: p['round_context'].update(attempt_id='WRONG'))
        self.assertEqual(original_selection(self.state, self.root, 1), ['P001'])
        with patch.object(batch_workflow, 'input_errors', wraps=batch_workflow.input_errors) as deep:
            result = self.reserve()
        self.assertEqual([r['panel_id'] for r in result['reserved']], ['P001'])
        self.assertEqual([c.args[2]['panel_id'] for c in deep.call_args_list], ['P001'])

    def test_later_risk_error_is_local_and_remains_visible_after_early_stop(self):
        shots = read_json(checked_file(self.root, self.state['shot_manifest']))
        shots['panels'][-1]['production_risks'] = 'UNREVIEWED'
        self.publish_shots(shots)
        prep = preparation(self.state, self.root)
        self.assertEqual(prep['global_errors'], [])
        self.assertEqual(prep['blocked_panel_ids'], ['P004'])
        self.assertIn('production_risks', str(prep['blockers']['P004']))
        report = self.bounded()
        self.assertEqual(report['ready_panel_ids'], ['P001'], report)
        self.assertIn('P004', report['blocked_panel_ids'])
        self.assertEqual(report['checked_panel_count'], 1)
        self.assertEqual([r['panel_id'] for r in self.reserve()['reserved']], ['P001'])

    def test_risk_error_propagates_actual_design_dependency_chain(self):
        shots = read_json(checked_file(self.root, self.state['shot_manifest']))
        shots['panels'][1]['production_risks'] = [{'kind': [], 'constraint': 'SYNTHETIC invalid kind'}]
        self.publish_shots(shots)
        prep = preparation(self.state, self.root)
        self.assertEqual(prep['global_errors'], [])
        self.assertEqual(prep['blocked_panel_ids'], ['P002', 'P003', 'P004'])
        self.assertIn('dependency', str(prep['blockers']['P004']))
        self.assertEqual(self.bounded()['ready_panel_ids'], ['P001'])
        self.assertEqual(self.bounded(excluded=['P001']).get('ready_panel_ids', []), [])

    def test_last_third_round_blocks_even_when_excluded_and_first_is_ready(self):
        self.state['panels'][-1]['round_id'] = 3
        self.f.flush()
        self.assertEqual(original_selection(self.state, self.root, 1), [])
        report = self.bounded(excluded=['P004'])
        self.assertEqual(report['next_action'], 'STOP_DIAGNOSE', report)
        self.assertEqual(report.get('ready_panel_ids', []), [])
        self.assert_no_writes('STOP_DIAGNOSE')

    def test_last_disguised_repair_history_blocks_before_candidate_scan(self):
        self.state['panels'][-1]['attempt_history'] = [{'attempt_id': 'old-attempt', 'status': 'VISUAL_FAIL'}]
        self.f.flush()
        self.assertEqual(original_selection(self.state, self.root, 1), [])
        self.assert_no_writes('ROUND_HOLD')

    def test_last_unknown_state_blocks_before_candidate_scan(self):
        self.state['panels'][-1]['status'] = 'UNRECOGNIZED'
        self.f.flush()
        self.assert_no_writes('RESOLVE_EPISODE_HOLD')

    def test_source_record_order_is_checked_in_full(self):
        self.state['panels'][-2:] = reversed(self.state['panels'][-2:])
        self.f.flush()
        self.assert_no_writes('COMPLETE_INPUT_AUDIT')

    def test_later_audit_identity_error_remains_global(self):
        audit_path = checked_file(self.root, self.state['semantic_audit'])
        audit = read_json(audit_path)
        audit['panels'][-1]['panel_id'] = 'FOREIGN_PANEL'
        atomic_json(audit_path, audit)
        self.state['semantic_audit']['sha256'] = digest(audit_path)
        self.f.flush()
        self.assert_no_writes('GLOBAL_PREPARATION_HOLD')

    def test_global_hold_cannot_be_downgraded_to_later_panel_scope(self):
        self.state['holds'] = [{'scope': 'book', 'panel_ids': ['P004'], 'evidence': 'SYNTHETIC shared style withdrawn'}]
        self.f.flush()
        self.assertEqual(self.bounded()['next_action'], 'RESOLVE_HOLD')
        self.assert_no_writes(exception='HOLD')

    def test_selected_last_panel_reads_all_declared_prior_context_rows(self):
        import continuity_context
        actual = continuity_context._load_context
        observed = []
        def context(*args, **kwargs):
            result = actual(*args, **kwargs)
            if args[0].get('panels', [{}])[0].get('panel_id') == 'P004':
                observed.append(list(result[0]))
            return result
        with patch.object(continuity_context, '_load_context', side_effect=context), \
                patch.object(batch_workflow, 'input_errors', wraps=batch_workflow.input_errors) as deep:
            result = self.bounded(excluded=['P001', 'P002', 'P003'])
        self.assertEqual(result['ready_panel_ids'], ['P004'], result)
        self.assertEqual(deep.call_count, 1)
        self.assertTrue(observed)
        self.assertTrue(all(rows == ['E000-P001', 'E000-P002', 'E000-P003'] for rows in observed), observed)

    def test_invalid_nonadjacent_prior_context_is_not_ignored(self):
        row = self.state['panels'][-1]
        packet = read_json(checked_file(self.root, row['package_manifest']))
        path = checked_file(self.root, packet['continuity_context'])
        context = read_json(path)
        context['entries'][0]['panel_id'] = 'P999'
        atomic_json(path, context)
        self.rewrite_packet('P004', lambda p: p['continuity_context'].update(sha256=digest(path)))
        result = self.bounded(excluded=['P001', 'P002', 'P003'])
        self.assertEqual(result.get('ready_panel_ids', []), [], result)
        self.assertIn('CONTINUITY', str(result))

    def test_excluded_predecessor_is_not_treated_as_an_accepted_image(self):
        shots = read_json(checked_file(self.root, self.state['shot_manifest']))
        shots['panels'][-1]['generation_dependencies'] = ['P002']
        self.publish_shots(shots)
        # Explicitly update the synthetic B proof so absence of image evidence,
        # rather than an unrelated approval mismatch, is what blocks P004.
        self.state['gates']['shot_design']['artifacts'] = [self.state['visual_basis'],
            self.state['shot_manifest'], self.state['semantic_audit']]
        self.f.flush()
        from scoped_inputs import approval_for
        self.assertEqual(approval_for(self.state, self.root, 'shot_design',
            self.state['gates']['shot_design']['artifacts'], ['P004'], self.state['gates']['shot_design']), [])
        self.assertEqual(preparation(self.state, self.root)['blocked_panel_ids'], [])
        with patch.object(batch_workflow, 'input_errors', wraps=batch_workflow.input_errors) as deep:
            result = self.bounded(excluded=['P001', 'P002', 'P003'])
        self.assertEqual(result.get('ready_panel_ids', []), [], result)
        self.assertEqual(deep.call_count, 0)
        self.assertEqual(self.state['panels'][1]['status'], 'PENDING')

    def test_global_last_record_error_is_rejected_by_real_cli(self):
        self.state['panels'][-1]['round_id'] = 3
        self.f.flush()
        before = self.f.state_path.read_bytes()
        script = Path(__file__).resolve().parents[1] / 'scripts/episode_dispatch_queue.py'
        proc = subprocess.run([sys.executable, '-B', str(script), '--state', str(self.f.state_path),
                               '--expected-state-sha256', digest(self.f.state_path),
                               '--expected-control-sha256', digest(self.f.control_path), '--max-count', '1'],
                              capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['status'], 'STOP_DIAGNOSE')
        self.assertEqual(self.f.state_path.read_bytes(), before)
        self.assertEqual(list(self.root.glob('*.dispatch-*.json')), [])

    def test_late_authorized_repair_keeps_source_order_behind_earlier_pending(self):
        self.f.authorize_synthetic_repair('P004')
        self.state = self.f.state
        old = original_selection(self.state, self.root, 4)
        new = self.bounded(limit=4)
        self.assertEqual(old, ['P001', 'P002', 'P003', 'P004'])
        self.assertEqual(new['ready_panel_ids'], old, new)
        with patch.object(batch_workflow, 'input_errors', wraps=batch_workflow.input_errors) as deep:
            result = self.reserve()
        self.assertEqual([r['panel_id'] for r in result['reserved']], ['P001'])
        self.assertEqual([c.args[2]['panel_id'] for c in deep.call_args_list], ['P001'])

    def test_early_repair_and_first_round_receipts_keep_distinct_rounds_and_attempts(self):
        self.f.authorize_synthetic_repair('P001')
        self.state = self.f.state
        old = original_selection(self.state, self.root, 2)
        self.assertEqual(old, ['P001', 'P002'])
        self.assertEqual(self.bounded(limit=2)['ready_panel_ids'], old)
        result = self.reserve(limit=2)
        self.assertEqual([r['panel_id'] for r in result['reserved']], old)
        self.assertEqual([(r['receipt']['round_id'], r['receipt']['attempt_id']) for r in result['reserved']],
                         [(2, 'P001-r2'), (1, 'P002-r1')])
        self.assertEqual(len({r['permit_id'] for r in result['reserved']}), 2)
        after = read_json(self.f.state_path)
        self.assertEqual(after['panels'][0]['attempt_history'][0]['attempt_id'], 'P001-r1')

    def test_reserved_repair_is_excluded_without_reopening_its_failed_first_attempt(self):
        self.f.authorize_synthetic_repair('P001')
        self.state = self.f.state
        self.assertEqual([r['panel_id'] for r in self.reserve()['reserved']], ['P001'])
        self.state = read_json(self.f.state_path)
        self.assertEqual([r['panel_id'] for r in self.reserve()['reserved']], ['P002'])
        after = read_json(self.f.state_path)
        permits = [r for r in after['dispatch_ledger'] if r['panel_id'] == 'P001']
        self.assertEqual([(r['round_id'], r['status']) for r in permits], [(1, 'COMPLETED'), (2, 'RESERVED')])

    def test_invalid_late_repair_lineage_still_blocks_all_new_claims(self):
        self.f.authorize_synthetic_repair('P004')
        self.state = self.f.state
        self.state['panels'][-1]['attempt_history'][0]['attempt_id'] = 'UNBOUND_FAILURE'
        self.f.flush()
        self.assertEqual(original_selection(self.state, self.root, 1), [])
        self.assert_no_writes('ROLLING_REPAIR_HOLD')


if __name__ == '__main__':
    unittest.main()
