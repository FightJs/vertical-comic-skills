"""Bulk permits must bind immutable episode attempts and respect real capacity."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'tests')]
from codex_reference_contract import digest
from episode_dispatch_queue import reserve_ready
from parallel_dispatch import receipt_errors
from test_parallel_dispatch import DispatchTests


class EpisodeDispatchQueueTests(unittest.TestCase):
    def setUp(self):
        self.h = DispatchTests('test_valid_snapshot_read_only')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.h.state.update(execution_mode='episode_async_v1',
                            optimization_policy='scoped_episode_review_v1',
                            preparation_policy='episode_preparation_v1',
                            panels=[{'panel_id': p, 'status': 'PENDING', 'round_id': 1,
                                     'attempt_id': p+'-r1'} for p in ('P001', 'P002')])
        self.h.state['batch_plan'] = self.h.write(self.h.episode, 'episode-plan.json',
            {'batches': [{'batch_id': 'EPISODE', 'panel_ids': ['P001', 'P002']}]})
        self.h.control['jobs'][0].update(active_batch_id='EPISODE', max_inflight=2)
        self.h.control['permits'][0].update(batch_id='EPISODE', round_id=1, attempt_id='P001-r1')
        packet = {'execution_mode': 'episode_async_v1',
                  'round_context': {'batch_id': 'EPISODE', 'round_id': 1, 'attempt_id': 'P002-r1'},
                  'panels': [{'panel_id': 'P002'}]}
        self.h.state['panels'][1]['package_manifest'] = self.h.write(self.h.episode, 'P002-package.json', packet)
        self.h.flush()

    @staticmethod
    def gate(state, root, check='status', requested=None):
        if check == 'status':
            return {'next_action': 'SUBMIT_READY_EPISODE_REQUESTS', 'eligible_panel_ids': ['P002']}
        return {'ready_panel_ids': ['P002'], 'reports': []}

    def reserve(self, state_hash=None, control_hash=None):
        with patch('scoped_episode_workflow.evaluate_episode', side_effect=self.gate):
            return reserve_ready(self.h.state_path, state_hash or digest(self.h.state_path),
                                 control_hash or digest(self.h.control_path))

    def test_reserves_one_eligible_panel_and_binds_round_receipt(self):
        result = self.reserve()
        self.assertEqual(result['status'], 'RESERVED')
        self.assertEqual([r['panel_id'] for r in result['reserved']], ['P002'])
        state = json.loads(self.h.state_path.read_text(encoding='utf-8-sig'))
        control = json.loads(self.h.control_path.read_text(encoding='utf-8-sig'))
        ref = state['panels'][1]['package_manifest']
        packet = json.loads((self.h.episode / ref['path']).read_text(encoding='utf-8-sig'))
        self.assertEqual(packet['dispatch_receipt'], result['reserved'][0]['receipt'])
        self.assertEqual(control['permits'][-1]['attempt_id'], 'P002-r1')
        self.assertEqual(receipt_errors(self.h.context, self.h.episode, 'book', 'E021',
            'P002', packet['dispatch_receipt']), [])

    def test_stale_control_hash_cannot_reserve(self):
        old_hash = digest(self.h.control_path)
        self.h.control['max_inflight'] = 1
        self.h.flush()
        with self.assertRaisesRegex(ValueError, 'STATE_OR_CONTROL_CHANGED'):
            self.reserve(control_hash=old_hash)
        self.assertEqual(len(json.loads(self.h.control_path.read_text(encoding='utf-8-sig'))['permits']), 1)

    def test_real_global_capacity_is_respected(self):
        self.h.control['max_inflight'] = 1
        self.h.flush()
        self.assertEqual(self.reserve()['status'], 'CAPACITY_FULL')

    def test_observed_ready_wait_ends_after_both_legacy_commits(self):
        import episode_dispatch_queue as queue
        clock = [10.0]
        write = queue._atomic_json
        def gate(*args, **kwargs):
            return {**self.gate(*args, **kwargs), '_ready_observed_monotonic': {'P002': clock[0]}}
        def timed_write(*args):
            write(*args)
            clock[0] += 2.0
        with patch('scoped_episode_workflow.evaluate_episode', side_effect=gate), \
                patch.object(queue, '_atomic_json', side_effect=timed_write), \
                patch.object(queue.time, 'perf_counter', side_effect=lambda: clock[0]):
            result = queue.reserve_ready(self.h.state_path, digest(self.h.state_path), digest(self.h.control_path))
        row = result['dispatch_metrics']['ready_wait']['panels'][0]
        self.assertEqual(row['observed_ready_to_reserve_seconds'], 6.0)
        self.assertEqual(row['permit_id'], result['reserved'][0]['permit_id'])
        self.assertEqual((row['episode_id'], row['panel_id'], row['round_id'], row['attempt_id']),
                         ('E021', 'P002', 1, 'P002-r1'))
        self.assertIsNone(result['dispatch_metrics']['ready_wait']['historical_ready_to_reserve_seconds'])

    def test_unobserved_readiness_is_unknown_and_capacity_full_has_no_samples(self):
        result = self.reserve()
        self.assertIsNone(result['dispatch_metrics']['ready_wait']['panels'][0]['observed_ready_to_reserve_seconds'])
        full = self.reserve()
        self.assertEqual(full['status'], 'CAPACITY_FULL')
        self.assertEqual(full['dispatch_metrics']['ready_wait']['panels'], [])


if __name__ == '__main__':
    unittest.main()
