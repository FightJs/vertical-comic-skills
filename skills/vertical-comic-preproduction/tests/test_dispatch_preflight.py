"""Compare bounded reservation checks with the original full selection algorithm."""
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
from episode_dispatch_queue import reserve_ready
from staged_workflow import evaluate, preflight_many
from scoped_episode_workflow import evaluate_episode
from platform_io import atomic_json
import batch_workflow


def original_selection(state, root, limit, excluded=()):
    """Original status -> full candidate check -> filter/slice, read-only."""
    status = evaluate_episode(state, root)
    if status.get('next_action') != 'SUBMIT_READY_EPISODE_REQUESTS':
        return []
    ids = status['eligible_panel_ids']
    report = evaluate_episode(state, root, 'candidate_batch', ids)
    ready = set(report.get('ready_panel_ids', []))
    return [pid for pid in ids if pid in ready and pid not in excluded][:limit]


class DispatchPreflightTests(unittest.TestCase):
    def setUp(self):
        self.fixture = DispatchFixture()
        self.addCleanup(self.fixture.close)
        self.state, self.root = self.fixture.state, self.fixture.root

    def reserve(self, limit=1):
        f = self.fixture
        return reserve_ready(f.state_path, digest(f.state_path), digest(f.control_path), limit)

    def bounded(self, limit=1, excluded=()):
        with file_session():
            return evaluate_episode(self.state, self.root, 'reservation_batch',
                                    {'limit': limit, 'excluded': list(excluded)})

    def test_real_gate_selects_same_first_panel_but_checks_only_one(self):
        with patch.object(batch_workflow, 'input_errors', wraps=batch_workflow.input_errors) as calls:
            old = original_selection(self.state, self.root, 1)
            old_count = calls.call_count
            calls.reset_mock()
            new = self.bounded()
            self.assertEqual(new['ready_panel_ids'], old)
            self.assertEqual(calls.call_count, 1)
            self.assertEqual(old_count, 4)
        self.assertEqual(new['deferred_panel_ids'], ['P002', 'P003', 'P004'])
        self.assertIs(new['dispatch_authorized'], False)
        self.assertIs(new['candidate_only'], True)

    def test_real_reservation_preserves_control_and_packet_inputs(self):
        before = self.fixture.control_path.read_bytes()
        original_ref = copy.deepcopy(self.state['panels'][0]['package_manifest'])
        original = read_json(checked_file(self.root, original_ref))
        result = self.reserve()
        self.assertEqual(result['status'], 'RESERVED', result)
        self.assertEqual([r['panel_id'] for r in result['reserved']], ['P001'])
        self.assertEqual(before, self.fixture.control_path.read_bytes())
        packet = read_json(checked_file(self.root, result['reserved'][0]['package_manifest']))
        self.assertEqual(packet.pop('dispatch_source_package'), original_ref)
        self.assertEqual(packet.pop('dispatch_receipt'), result['reserved'][0]['receipt'])
        self.assertEqual(packet, original)
        metrics = result['dispatch_metrics']
        self.assertEqual(metrics['checked_panel_count'], 1)
        self.assertGreater(metrics['file_reuse_statistics']['hash_hits'], 0)
        self.assertGreaterEqual(metrics['lock_hold_seconds'], metrics['preflight_seconds'])
        wait = metrics['ready_wait']
        self.assertIsNone(wait['historical_ready_to_reserve_seconds'])
        self.assertEqual(len(wait['panels']), 1)
        self.assertEqual(wait['panels'][0]['permit_id'], result['reserved'][0]['permit_id'])
        self.assertGreaterEqual(wait['panels'][0]['observed_ready_to_reserve_seconds'], 0)
        self.assertLessEqual(wait['panels'][0]['observed_ready_to_reserve_seconds'], metrics['lock_hold_seconds'])
        self.assertNotIn('_ready_observed_monotonic', json.dumps(result))

    def test_standard_entry_owns_task_contract_and_qa_contexts(self):
        import task_context
        import execution_contract
        import review_reuse
        from codex_reference_contract import _FILE_SESSION
        from staged_workflow import _evaluate_impl
        self.fixture.source.scope_task()
        self.fixture.flush()
        def task_check(*args):
            self.assertIsNotNone(_FILE_SESSION.get())
            return task_check_actual(*args)
        def routed(*args):
            self.assertIsNotNone(_FILE_SESSION.get())
            self.assertIsNotNone(review_reuse._SESSION.get())
            return _evaluate_impl(*args)
        def inputs(*args, **kwargs):
            self.assertIsNotNone(_FILE_SESSION.get())
            self.assertIsNotNone(review_reuse._SESSION.get())
            self.assertTrue(kwargs['candidate'])
            return input_actual(*args, **kwargs)
        task_check_actual = task_context.state_errors
        input_actual = batch_workflow.input_errors
        with patch.object(task_context, 'state_errors', side_effect=task_check) as task_calls, \
                patch('staged_workflow._evaluate_impl', side_effect=routed), \
                patch.object(execution_contract, 'state_errors', wraps=execution_contract.state_errors) as contracts, \
                patch.object(batch_workflow, 'input_errors', side_effect=inputs):
            result = self.reserve()
        self.assertEqual(result['status'], 'RESERVED', result)
        self.assertEqual(task_calls.call_count, 1)
        self.assertEqual(contracts.call_count, 1)
        self.assertIn('validated', result['dispatch_metrics']['qa_reuse_statistics'])

    def test_real_task_identity_mismatch_cannot_reserve(self):
        self.fixture.source.scope_task()
        self.state['task_context']['task_id'] = 'OTHER_TASK'
        self.fixture.flush()
        before = self.fixture.state_path.read_bytes()
        result = self.reserve()
        self.assertEqual(result['status'], 'TASK_SCOPE_HOLD', result)
        self.assertEqual(result['failure_domain'], 'INPUT_OR_REVIEW_CONTEXT')
        self.assertEqual(result['reserved'], [])
        self.assertEqual(before, self.fixture.state_path.read_bytes())
        self.assertEqual(list(self.root.glob('*.dispatch-*.json')), [])

    def test_task_origin_is_revalidated_before_any_write(self):
        from task_context import ORIGIN_FILE
        self.fixture.source.scope_task()
        self.fixture.flush()
        before = self.fixture.state_path.read_bytes()
        def replaced_origin(*args, **kwargs):
            result = evaluate(*args, **kwargs)
            path = self.root / ORIGIN_FILE
            atomic_json(path, read_json(path))
            return result
        with patch('staged_workflow.evaluate', side_effect=replaced_origin):
            with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
                self.reserve()
        self.assertEqual(before, self.fixture.state_path.read_bytes())
        self.assertEqual(list(self.root.glob('*.dispatch-*.json')), [])

    def test_all_production_writes_follow_both_context_exits(self):
        import episode_dispatch_queue as queue
        from codex_reference_contract import _FILE_SESSION
        from review_reuse import _SESSION
        actual = queue._atomic_json
        def write(path, value):
            self.assertIsNone(_FILE_SESSION.get())
            self.assertIsNone(_SESSION.get())
            actual(path, value)
        with patch.object(queue, '_atomic_json', side_effect=write) as writes:
            self.assertEqual(self.reserve()['status'], 'RESERVED')
        self.assertGreaterEqual(writes.call_count, 2)

    def test_shared_read_transaction_does_not_upgrade_candidate_to_formal(self):
        with file_session():
            candidate = preflight_many(self.state, self.root, ['P001'], candidate=True)
            formal = preflight_many(self.state, self.root, ['P001'])
        self.assertEqual(candidate['ready_panel_ids'], ['P001'], candidate)
        self.assertIs(candidate['dispatch_authorized'], False)
        self.assertEqual(formal['ready_panel_ids'], [], formal)
        self.assertEqual(formal['status'], 'HOLD')

    def test_real_cli_traverses_standard_gates_and_writes_bound_receipt(self):
        f = self.fixture
        self.fixture.source.scope_task()
        self.fixture.flush()
        script = Path(__file__).resolve().parents[1] / 'scripts/episode_dispatch_queue.py'
        proc = subprocess.run([sys.executable, '-B', str(script), '--state', str(f.state_path),
                               '--expected-state-sha256', digest(f.state_path),
                               '--expected-control-sha256', digest(f.control_path), '--max-count', '1'],
                              capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result['status'], 'RESERVED', result)
        row = result['reserved'][0]
        state = read_json(f.state_path)
        packet = read_json(checked_file(self.root, row['package_manifest']))
        self.assertEqual(row['receipt'], packet['dispatch_receipt'])
        self.assertEqual(state['dispatch_ledger'][0]['permit_id'], row['permit_id'])
        self.assertEqual(state['dispatch_ledger'][0]['attempt_id'], state['panels'][0]['attempt_id'])
        self.assertEqual(result['image_calls'], 0)
        metrics = result['dispatch_metrics']
        self.assertEqual(metrics['checked_panel_count'], 1)
        self.assertGreater(metrics['file_reuse_statistics']['json_parses'], 0)
        self.assertGreater(metrics['file_reuse_statistics']['json_hits'], 0)
        self.assertGreater(metrics['file_reuse_statistics']['hash_bytes'], 0)
        self.assertEqual({r['kind'] for r in metrics['locks']}, {'episode_state', 'shared_dispatch'})
        wait = metrics['ready_wait']['panels'][0]
        self.assertEqual(wait['permit_id'], row['permit_id'])
        self.assertEqual(wait['attempt_id'], row['receipt']['attempt_id'])
        self.assertGreaterEqual(wait['observed_ready_to_reserve_seconds'], 0)
        self.assertIsNone(metrics['ready_wait']['historical_ready_to_reserve_seconds'])
        for lock in metrics['locks']:
            self.assertGreaterEqual(lock['hold_seconds'], 0)
            self.assertGreaterEqual(lock['wait_seconds'], 0)

    def test_cli_probe_counts_real_gates_without_substituting_results(self):
        self.fixture.source.scope_task()
        self.fixture.flush()
        tests = Path(__file__).resolve().parent
        proc = subprocess.run([sys.executable, '-B', str(tests / 'dispatch_cli_probe.py'),
                               '--scripts', str(tests.parent / 'scripts'),
                               '--fixture-state', str(self.fixture.state_path), '--limit', '1'],
                              capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        sample = json.loads(proc.stdout)
        self.assertEqual(sample['selected'], ['P001'])
        self.assertTrue(sample['receipt_binding_verified'])
        for key in ('input_checks', 'preparation_checks', 'contract_checks', 'task_checks'):
            self.assertEqual(sample['operations'][key], 1)
        self.assertGreater(sample['operations']['file_hashes'], 0)
        self.assertGreater(sample['operations']['json_parses'], 0)

    def test_standard_contract_failure_is_preserved_and_runs_once(self):
        import execution_contract
        state = copy.deepcopy(self.state)
        state['toolchain'] = {'invalid': True}
        expected = evaluate_episode(state, self.root, 'reservation_batch', {'limit': 1, 'excluded': []})
        with patch.object(execution_contract, 'state_errors', wraps=execution_contract.state_errors) as calls:
            report = evaluate(state, self.root, 'reservation_batch', {'limit': 1, 'excluded': []})
        self.assertEqual(report['next_action'], 'EXECUTION_CONTRACT_HOLD')
        self.assertEqual(report['errors'], expected['errors'])
        self.assertEqual(report['failure_domain'], 'RUNTIME_OR_FROZEN_INPUT')
        self.assertEqual(calls.call_count, 1)

    def test_reserved_panel_is_filtered_before_input_validation(self):
        self.reserve()
        self.state = read_json(self.fixture.state_path)
        with patch.object(batch_workflow, 'input_errors', wraps=batch_workflow.input_errors) as calls:
            result = self.reserve()
        self.assertEqual([r['panel_id'] for r in result['reserved']], ['P002'])
        self.assertEqual([call.args[2]['panel_id'] for call in calls.call_args_list], ['P002'])

    def test_bad_first_packet_does_not_starve_later_approved_panels(self):
        # This field is outside the creative approval signature but still fails the input gate.
        row = self.state['panels'][0]
        path = checked_file(self.root, row['package_manifest'])
        packet = read_json(path)
        packet['round_context']['attempt_id'] = 'wrong-attempt'
        atomic_json(path, packet)
        row['package_manifest']['sha256'] = digest(path)
        row['shot_subset'] = copy.deepcopy(row['package_manifest'])
        self.fixture.flush()
        old = original_selection(self.state, self.root, 1)
        new = self.bounded()
        self.assertEqual(old, ['P002'])
        self.assertEqual(new['ready_panel_ids'], old)
        self.assertEqual(new['checked_panel_count'], 2)

    def test_revoked_package_approval_and_global_cancel_never_reserve(self):
        self.state['generation_packages'] = {}
        self.fixture.flush()
        before = self.fixture.state_path.read_bytes()
        result = self.reserve()
        self.assertEqual(result['reserved'], [])
        self.assertEqual(result['status'], 'WAIT_GENERATION_PACKAGE_APPROVAL')
        self.assertEqual(before, self.fixture.state_path.read_bytes())
        self.state['cancelled'] = True
        self.fixture.flush()
        with self.assertRaises(ValueError):
            self.reserve()

    def test_missing_B_does_not_turn_reservation_into_candidate_authorization(self):
        self.state['gates']['shot_design'] = None
        self.fixture.flush()
        self.assertEqual(self.reserve()['reserved'], [])

    def test_outer_read_transaction_cannot_delay_validation_until_after_write(self):
        before = self.fixture.state_path.read_bytes()
        with file_session():
            with self.assertRaisesRegex(ValueError, 'RESERVATION_REQUIRES_OWN_TRANSACTION'):
                self.reserve()
        self.assertEqual(before, self.fixture.state_path.read_bytes())

    def test_state_write_failure_leaves_no_success_or_orphan_packet(self):
        import episode_dispatch_queue as queue
        before = self.fixture.state_path.read_bytes()
        original_write = queue._atomic_json
        def fail_state(path, value):
            if Path(path).resolve() == self.fixture.state_path.resolve():
                raise OSError('synthetic failed state replace')
            original_write(path, value)
        with patch.object(queue, '_atomic_json', side_effect=fail_state):
            with self.assertRaisesRegex(OSError, 'synthetic failed'):
                self.reserve()
        self.assertEqual(before, self.fixture.state_path.read_bytes())
        self.assertEqual(list(self.root.glob('*.dispatch-*.json')), [])

    def test_snapshot_change_after_preflight_cannot_write_packets_or_state(self):
        from scoped_episode_workflow import evaluate_episode as actual
        before = self.fixture.state_path.read_bytes()
        path = checked_file(self.root, self.state['approval_index'])
        def changed(*args, **kwargs):
            result = actual(*args, **kwargs)
            # Even replacement with equal bytes invalidates this read transaction.
            atomic_json(path, read_json(path))
            return result
        with patch('scoped_episode_workflow.evaluate_episode', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
                self.reserve()
        self.assertEqual(before, self.fixture.state_path.read_bytes())
        self.assertEqual(list(self.root.glob('*.dispatch-*.json')), [])

    def test_limits_exclusions_and_no_approval_do_not_expand_scope(self):
        for limit, excluded in [(2, ()), (1, ('P001', 'P002')), (4, ('P004',))]:
            old = original_selection(self.state, self.root, limit, excluded)
            self.assertEqual(self.bounded(limit, excluded)['ready_panel_ids'], old)
        for limit in (0, -1, True, '1'):
            self.assertEqual(self.bounded(limit).get('ready_panel_ids', []), [])

    def test_hold_dependency_closure_is_preserved(self):
        # This fixture's design context forms a chain; first-panel uncertainty
        # invalidates its followers, while a last-panel hold leaves P001 ready.
        for pid, selected in [('P001', []), ('P004', ['P001'])]:
            self.state['holds'] = [{'scope': 'panels', 'panel_ids': [pid],
                                    'dimension': 'generation', 'evidence': 'SYNTHETIC unresolved pose'}]
            self.fixture.flush()
            expected = original_selection(self.state, self.root, 1)
            self.assertEqual(expected, selected)
            self.assertEqual(self.bounded().get('ready_panel_ids', []), expected)

    def test_two_processes_with_same_snapshot_can_only_reserve_once(self):
        f = self.fixture
        state_hash, control_hash = digest(f.state_path), digest(f.control_path)
        script = Path(__file__).resolve().parents[1] / 'scripts/episode_dispatch_queue.py'
        args = [sys.executable, '-B', str(script), '--state', str(f.state_path),
                '--expected-state-sha256', state_hash, '--expected-control-sha256', control_hash,
                '--max-count', '1']
        processes = []
        try:
            for _ in range(2):
                processes.append(subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                  text=True, encoding='utf-8'))
            results = []
            for proc in processes:
                stdout, stderr = proc.communicate(timeout=30)
                self.assertIn(proc.returncode, (0, 1), stderr)
                results.append(json.loads(stdout))
        finally:
            for proc in processes:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()
        self.assertEqual(sorted(r['status'] for r in results), ['HOLD', 'RESERVED'])
        failure = next(r for r in results if r['status'] == 'HOLD')
        self.assertIn('STATE_OR_CONTROL_CHANGED', failure['errors'])
        self.assertEqual(len(read_json(f.state_path)['dispatch_ledger']), 1)


if __name__ == '__main__':
    unittest.main()
