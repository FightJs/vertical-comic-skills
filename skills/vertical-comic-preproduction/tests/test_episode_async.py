"""The new episode scope must not inherit the H001/C barrier."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'tests')]

from scoped_inputs import build_plan, EPISODE_MODE, EPISODE_POLICY, STATE_DISPATCH
from scoped_episode_workflow import evaluate_episode
from test_episode_preparation import EpisodePreparationTests


class EpisodeAsyncTests(unittest.TestCase):
    def setUp(self):
        self.fixture = EpisodePreparationTests('test_35_panel_shots_are_one_source_with_18_and_17_production_views')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def state(self, count=30):
        state, shots = self.fixture.state(count)
        state.update(execution_mode=EPISODE_MODE, optimization_policy=EPISODE_POLICY,
                     state_dispatch_policy=STATE_DISPATCH,
                     repair_authorizations={}, episode_failure_diagnosis={})
        for shot in shots: shot['state_review_policy'] = 'merge_into_D'
        state['shot_manifest'] = self.fixture.write('episode-shots.json', {
            'execution_mode': EPISODE_MODE, 'optimization_policy': EPISODE_POLICY,
            'preparation_policy': 'episode_preparation_v1', 'panels': shots})
        state['gates']['shot_design'] = self.fixture.approval([state['visual_basis'], state['shot_manifest']])
        source = json.loads((self.root / state['source_snapshot']['path']).read_text())
        state['batch_plan'] = self.fixture.write('episode-plan.json', build_plan(state, source))
        return state, shots

    def test_thirty_five_panels_have_one_episode_scope(self):
        state, _ = self.state(35)
        plan = json.loads((self.root / state['batch_plan']['path']).read_text())
        self.assertEqual([(b['batch_id'], len(b['panel_ids'])) for b in plan['batches']], [('EPISODE', 35)])

    def test_later_independent_panels_ready_before_first_images_or_C(self):
        state, _ = self.state(30)
        with patch('execution_contract.state_errors', return_value=[]), \
             patch('scoped_episode_workflow.binding_errors', return_value=[]), \
             patch('batch_workflow.completed_errors', return_value=[]):
            initial = evaluate_episode(state, self.root)
            self.assertEqual(initial['next_action'], 'SUBMIT_READY_EPISODE_REQUESTS', initial)
            self.assertEqual(len(initial['eligible_panel_ids']), 30)
            for row in state['panels'][:15]:
                row.update(status='VISUAL_PASS', round_id=1, attempt_id=row['panel_id']+'-r1',
                           output=self.fixture.write(row['panel_id']+'-output.json', {'test': True}))
            later = evaluate_episode(state, self.root)
            self.assertEqual(later['eligible_panel_ids'], [f'P{i:03d}' for i in range(16,31)], later)
            self.assertNotEqual(later['next_action'], 'WAIT_FIRST_HALF_APPROVAL')

    def test_high_risk_and_real_image_dependencies_still_wait(self):
        state, shots = self.state(6)
        shots[1].update(visual_state_keys=['new:costume'], state_review_policy='user_required', requires_state_review=True)
        shots[2]['visual_state_keys'] = ['new:costume']
        shots[4]['generation_dependencies'] = ['P004']
        state['shot_manifest'] = self.fixture.write('risk-shots.json', {
            'execution_mode': EPISODE_MODE, 'optimization_policy': EPISODE_POLICY,
            'preparation_policy': 'episode_preparation_v1', 'panels': shots})
        state['gates']['shot_design'] = self.fixture.approval([state['visual_basis'], state['shot_manifest']])
        with patch('execution_contract.state_errors', return_value=[]), \
             patch('scoped_episode_workflow.binding_errors', return_value=[]):
            report = evaluate_episode(state, self.root)
        self.assertEqual(report['eligible_panel_ids'], ['P001','P002','P004','P006'], report)
        self.assertIn('P003', report['blocked_panel_ids'])
        self.assertNotIn('P005', report['eligible_panel_ids'])

    def test_reviewed_high_risk_anchor_requests_human_state_review(self):
        state, shots = self.state(2)
        shots[0].update(requires_state_review=True, state_review_policy='user_required')
        shots[1]['visual_state_keys'] = shots[0]['visual_state_keys']
        state['shot_manifest'] = self.fixture.write('state-review-shots.json', {
            'execution_mode': EPISODE_MODE, 'optimization_policy': EPISODE_POLICY,
            'preparation_policy': 'episode_preparation_v1', 'panels': shots})
        state['gates']['shot_design'] = self.fixture.approval([state['visual_basis'], state['shot_manifest']])
        state['panels'][0].update(status='VISUAL_PASS', round_id=1, attempt_id='P001-r1',
            output=self.fixture.write('P001-output.json', {'synthetic': True}))
        with patch('execution_contract.state_errors', return_value=[]), \
             patch('scoped_episode_workflow.binding_errors', return_value=[]), \
             patch('batch_workflow.completed_errors', return_value=[]):
            report = evaluate_episode(state, self.root)
        self.assertEqual(report['next_action'], 'WAIT_NEW_STATE_APPROVAL', report)
        self.assertIn('P002', report['blocked_panel_ids'])


if __name__ == '__main__': unittest.main()
