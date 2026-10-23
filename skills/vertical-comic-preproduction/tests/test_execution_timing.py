"""Observe real reservation/QA commits without inventing historical times."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts'), str(Path(__file__).parent)]
from execution_timing import POLICY, observe
from codex_reference_contract import digest
from production_metrics import build
from production_runtime import commit_updates
import test_episode_dispatch_queue as dispatch_fixtures
import test_production_runtime as runtime_fixtures


class ExecutionTimingTests(unittest.TestCase):
    def test_validated_reservation_records_ready_for_new_policy_only(self):
        case = dispatch_fixtures.EpisodeDispatchQueueTests()
        self.addCleanup(case.doCleanups)
        case.setUp()
        case.h.state['timing_policy'] = POLICY
        case.h.flush()
        result = case.reserve()
        self.assertEqual(result['status'], 'RESERVED')
        state = json.loads(case.h.state_path.read_text(encoding='utf-8'))
        row = state['panels'][1]
        self.assertEqual(row['ready_at'], row['timing_observations']['ready_at']['at'])
        self.assertNotIn('submitted_at', row)
        self.assertEqual(row['timing_observations']['attempt_id'], row['attempt_id'])

    def test_qa_registration_is_distinct_from_human_completion(self):
        case = runtime_fixtures.RuntimeTests()
        self.addCleanup(case.doCleanups)
        case.setUp()
        case.r['status'] = 'GENERATED'
        case.state['timing_policy'] = POLICY
        path = case.root / '00_输入审计/生产流程.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(case.state))
        commit_updates(path, digest(path), [{'panel_id': 'P001', 'attempt_id': case.r['attempt_id'],
                                            'round_id': 1, 'status': 'VISUAL_PASS'}])
        row = json.loads(path.read_text(encoding='utf-8'))['panels'][0]
        self.assertIn('qa_recorded_at', row)
        self.assertNotIn('qa_completed_at', row)
        self.assertEqual(row['timing_observations']['qa_recorded_at']['qa_report'], row['qa_report'])
        result = build([path])
        self.assertEqual(result['timing']['timestamp_coverage']['qa_recorded_at'], 1)
        self.assertEqual(result['timing']['timestamp_coverage']['qa_completed_at'], 0)

    def test_invalid_qa_commit_does_not_save_observation(self):
        case = runtime_fixtures.RuntimeTests()
        self.addCleanup(case.doCleanups)
        case.setUp()
        case.r['status'] = 'GENERATED'
        case.r.pop('qa_report', None)
        case.state['timing_policy'] = POLICY
        path = case.root / '00_输入审计/生产流程.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(case.state))
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            commit_updates(path, digest(path), [{'panel_id': 'P001', 'attempt_id': case.r['attempt_id'],
                                                'round_id': 1, 'status': 'VISUAL_PASS'}])
        self.assertEqual(before, path.read_bytes())

    def test_legacy_no_opt_in_and_repeated_observation_are_stable(self):
        row = {'attempt_id': 'r1'}
        observe({}, row, 'ready')
        self.assertEqual(row, {'attempt_id': 'r1'})
        observe({'timing_policy': POLICY}, row, 'ready')
        first = copy.deepcopy(row)
        observe({'timing_policy': POLICY}, row, 'ready')
        self.assertEqual(first, row)
        row['attempt_id'] = 'r2'
        observe({'timing_policy': POLICY}, row, 'ready')
        self.assertEqual(row['timing_observations']['attempt_id'], 'r2')


if __name__ == '__main__':
    unittest.main()
