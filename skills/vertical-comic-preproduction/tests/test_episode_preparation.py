"""Episode-wide preparation with half-only image production (synthetic evidence)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BASE / 'scripts'), str(BASE / 'tests')]

from codex_reference_contract import digest
from scoped_inputs import STATE_DISPATCH, build_plan, half_view, validate_shots, state_leads
from scoped_half_workflow import evaluate_scoped
from batch_round import snapshot
from production_runtime import episode_bundle
from execution_contract import semantic_template
import test_staged_workflow as staged_fixtures


class EpisodePreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8', newline='\n')
        return {'path': name, 'sha256': digest(path)}

    def approval(self, refs):
        return {'status': 'APPROVED', 'source_kind': 'user_message',
                'source_locator': 'synthetic://not-a-user', 'quote': 'SYNTHETIC TEST ONLY',
                'book_id': 'UNIT', 'episode_id': 'E000', 'artifacts': refs}

    def state(self, count):
        script = self.write('script.json', {'synthetic': True})
        ids = [f'P{i:03d}' for i in range(1, count + 1)]
        locked = {pid: {'event_text': pid} for pid in ids}
        source = self.write('source.json', {'source_sha256': script['sha256'],
                                           'panel_ids': ids, 'locked_scripts': locked})
        asset = self.root / 'style.png'
        asset.write_bytes(b'synthetic-style')
        basis = self.write('basis.json', {'book_id': 'UNIT', 'episode_id': 'E000',
                                          'reference_files': [{'path': asset.name, 'sha256': digest(asset)}]})
        panels = [{'panel_id': pid, 'locked_script': locked[pid],
                   'generation_dependencies': [], 'visual_state_keys': ['style:UNIT:v1'],
                   'requires_state_review': False} for pid in ids]
        shots = self.write('shots.json', {'execution_mode': 'half_episode_async_v1',
                                          'optimization_policy': 'scoped_half_review_v1',
                                          'preparation_policy': 'episode_preparation_v1',
                                          'panels': panels})
        state = {'policy': 'staged_comic_v1', 'book_id': 'UNIT', 'episode_id': 'E000',
                 'execution_mode': 'half_episode_async_v1',
                 'optimization_policy': 'scoped_half_review_v1',
                 'preparation_policy': 'episode_preparation_v1',
                 'source_script': script, 'source_snapshot': source,
                 'visual_basis': basis, 'shot_manifest': shots, 'gates': {},
                 'review_policy': {'systemic_failure_count_gt': 5, 'max_auto_correction_rounds': 1},
                 'panels': [{'panel_id': pid, 'status': 'PENDING'} for pid in ids],
                 'round_reviews': {}, 'state_reviews': {}, 'holds': [], 'cancelled': False}
        state['gates']['visual_basis'] = self.approval([script, source, basis])
        state['gates']['shot_design'] = self.approval([basis, shots])
        state['batch_plan'] = self.write('plan.json', build_plan(state, {'panel_ids': ids}))
        return state, panels

    def test_35_panel_shots_are_one_source_with_18_and_17_production_views(self):
        state, panels = self.state(35)
        plan = json.loads((self.root / state['batch_plan']['path']).read_text(encoding='utf-8-sig'))
        self.assertEqual([len(b['panel_ids']) for b in plan['batches']], [18, 17])
        self.assertEqual(half_view(state, 'H001')['shot_manifest'],
                         half_view(state, 'H002')['shot_manifest'])
        audit = semantic_template(state, self.root, 'EPISODE')
        self.assertEqual(audit['panel_ids'], [p['panel_id'] for p in panels])
        self.assertEqual(len(audit['panels']), 35)
        self.assertTrue(all(p['status']=='UNREVIEWED' for p in audit['panels']))
        full = json.loads((self.root / state['shot_manifest']['path']).read_text(encoding='utf-8-sig'))
        self.assertEqual(validate_shots(state, {'panel_ids': [p['panel_id'] for p in panels],
                                                'locked_scripts': {p['panel_id']: p['locked_script'] for p in panels}},
                                        plan['batches'][1], full), panels[18:])
        full['panels'] = full['panels'][:18]
        with self.assertRaisesRegex(ValueError, '准确覆盖'):
            validate_shots(state, {'panel_ids': [p['panel_id'] for p in panels],
                                   'locked_scripts': {p['panel_id']: p['locked_script'] for p in panels}},
                           plan['batches'][0], full)

    def test_C_opens_H002_without_second_asset_or_shot_approval(self):
        state, _ = self.state(4)
        with patch('execution_contract.state_errors', return_value=[]), \
             patch('scoped_half_workflow.binding_errors', return_value=[]), \
             patch('batch_workflow.completed_errors', return_value=[]), \
             patch('batch_workflow.batch_review_errors', return_value=[]), \
             patch('scoped_half_workflow.report_errors', return_value=[]):
            self.assertEqual(evaluate_scoped(state, self.root)['next_action'], 'SUBMIT_READY_HALF_REQUESTS')
            for row in state['panels'][:2]:
                row.update(status='VISUAL_PASS', round_id=1,
                           attempt_id=row['panel_id']+'-r1',
                           output=self.write(row['panel_id']+'-output.json', {'synthetic': True}))
            attempts = [snapshot(row) for row in state['panels'][:2]]
            state['round_reviews']['H001'] = {'1': self.write('round.json',
                {'strategy': 'ALL_PASS', 'repair_panel_ids': [], 'attempts': attempts})}
            before = evaluate_scoped(state, self.root)
            self.assertEqual(before['next_action'], 'WAIT_FIRST_HALF_APPROVAL', before)
            state['gates']['pilot'] = self.approval([state['visual_basis'], state['shot_manifest'],
                                                     *[row['output'] for row in state['panels'][:2]]])
            report = evaluate_scoped(state, self.root)
            self.assertEqual(report['next_action'], 'SUBMIT_READY_HALF_REQUESTS', report)
            self.assertEqual(report['batch_id'], 'H002')
            self.assertEqual(report['eligible_panel_ids'], ['P003', 'P004'])

    def test_opt_in_ordinary_first_states_do_not_serialize_eighteen_ready_panels(self):
        state, panels = self.state(36)
        state['state_dispatch_policy'] = STATE_DISPATCH
        for row in panels:
            row['state_review_policy'] = 'merge_into_C' if int(row['panel_id'][1:]) <= 18 else 'merge_into_D'
        for row in panels[3:18]:
            row['visual_state_keys'] = ['style:UNIT:v1', 'scene:living-room:v1']
        for row in panels[16:18]:
            row['visual_state_keys'] = ['style:UNIT:v1', 'identity:CH01:adult', 'costume:CH01:school']
        state['shot_manifest'] = self.write('parallel-shots.json',
            {'execution_mode':'half_episode_async_v1','optimization_policy':'scoped_half_review_v1',
             'preparation_policy':'episode_preparation_v1','panels':panels})
        state['gates']['shot_design'] = self.approval([state['visual_basis'], state['shot_manifest']])
        with patch('execution_contract.state_errors', return_value=[]), \
             patch('scoped_half_workflow.binding_errors', return_value=[]):
            report=evaluate_scoped(state,self.root)
            self.assertEqual(report['eligible_panel_ids'],[f'P{i:03d}' for i in range(1,19)],report)
        self.assertEqual(state_leads(panels[:18]),{'P001','P004','P017'})

    def test_opt_in_keeps_explicit_review_calibration_and_real_image_dependencies(self):
        state, panels = self.state(20)
        state['state_dispatch_policy'] = STATE_DISPATCH
        for i,row in enumerate(panels):
            row['state_review_policy'] = 'merge_into_C' if i<10 else 'merge_into_D'
        panels[2].update(visual_state_keys=['scene:risk'],state_review_policy='user_required')
        panels[3]['visual_state_keys']=['scene:risk']
        panels[5].update(visual_state_keys=['scene:calibration'],calibration_anchor=True)
        panels[6]['visual_state_keys']=['scene:calibration']
        panels[8]['generation_dependencies']=['P008']
        state['shot_manifest'] = self.write('guarded-shots.json',
            {'execution_mode':'half_episode_async_v1','optimization_policy':'scoped_half_review_v1',
             'preparation_policy':'episode_preparation_v1','panels':panels})
        state['gates']['shot_design'] = self.approval([state['visual_basis'], state['shot_manifest']])
        with patch('execution_contract.state_errors', return_value=[]), \
             patch('scoped_half_workflow.binding_errors', return_value=[]):
            report=evaluate_scoped(state,self.root)
        self.assertEqual(report['eligible_panel_ids'],['P001','P002','P003','P005','P006','P008','P010'],report)
        self.assertEqual(report['blocked_panel_ids'],['P004','P007'])

    def test_full_bundle_cannot_approve_only_first_half(self):
        fixture = staged_fixtures.StagedTests('test_actual_style_input_is_exported')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.real_input()
        state = fixture.state(1)
        shot_data = json.loads((fixture.root / state['shot_manifest']['path']).read_text(encoding='utf-8-sig'))
        shot_data.update(execution_mode='half_episode_async_v1',
                         optimization_policy='scoped_half_review_v1',
                         preparation_policy='episode_preparation_v1')
        shot_data['panels'][0].update(generation_dependencies=[], requires_state_review=False)
        state['shot_manifest'] = fixture.f.write('full-shots.json', shot_data)
        packet = fixture.manifest
        packet.update(execution_mode='half_episode_async_v1',
                      optimization_policy='scoped_half_review_v1',
                      preparation_policy='episode_preparation_v1')
        packet['panels'][0].update(generation_dependencies=[], requires_state_review=False)
        state['panels'][0]['package_manifest'] = fixture.f.write('full-panel.json', packet)
        state.update(execution_mode='half_episode_async_v1',
                     optimization_policy='scoped_half_review_v1',
                     preparation_policy='episode_preparation_v1')
        with patch('execution_contract.state_errors', return_value=[]), \
             patch('execution_contract.semantic_errors', return_value=[]):
            bundle = episode_bundle(state, fixture.root)
            self.assertEqual(bundle['panel_ids'], ['P001'])
            self.assertEqual(bundle['scope'], 'episode')
            state['panels'].append({'panel_id': 'P002', 'status': 'PENDING'})
            with self.assertRaisesRegex(ValueError, '源格序'):
                episode_bundle(state, fixture.root)

            state = fixture.state(2)
            shots = json.loads((fixture.root / state['shot_manifest']['path']).read_text(encoding='utf-8-sig'))
            shots.update(execution_mode='half_episode_async_v1',
                         optimization_policy='scoped_half_review_v1',
                         preparation_policy='episode_preparation_v1')
            for panel in shots['panels']:
                panel.update(generation_dependencies=['P001'] if panel['panel_id']=='P002' else [],
                             requires_state_review=False)
            state['shot_manifest'] = fixture.f.write('two-full-shots.json', shots)
            state['panels'][0]['package_manifest'] = fixture.f.write('two-first-panel.json', packet)
            state.update(execution_mode='half_episode_async_v1',
                         optimization_policy='scoped_half_review_v1',
                         preparation_policy='episode_preparation_v1')
            style = fixture.panel['reference_images'][-1]
            style_path = str((fixture.root / style['path']).resolve())
            token = '@DEPENDENCY:P001'
            row = {'panel_id':'P002', 'dependency_panel_ids':['P001'],
                   'arguments':{'prompt':'SYNTHETIC final text',
                                'transparent_background':False,
                                'referenced_image_paths':[style_path, token]},
                   'reference_files':[{'path':style_path,'sha256':style['sha256']},
                                      {'path':token}],
                   'output_spec':fixture.panel['output_spec']}
            plan = {'policy':'dependency_completion_plan_v1','scope':'episode',
                    'book_id':state['book_id'],'episode_id':state['episode_id'],
                    'visual_basis':state['visual_basis'],'shot_manifest':state['shot_manifest'],
                    'inputs':[row]}
            plan_ref = fixture.f.write('episode-dependencies.json', plan)
            bundle = episode_bundle(state, fixture.root, plan_ref)
            self.assertEqual(bundle['panel_ids'], ['P001','P002'])
            self.assertEqual([r['panel_id'] for r in bundle['inputs']], ['P001'])
            self.assertEqual(bundle['dependency_completion_plan'], plan_ref)
            row['arguments']['referenced_image_paths'] = [token]
            row['reference_files'] = [{'path':token}]
            plan_ref = fixture.f.write('missing-style-dependencies.json', plan)
            with self.assertRaisesRegex(ValueError, '画风样例'):
                episode_bundle(state, fixture.root, plan_ref)


if __name__ == '__main__':
    unittest.main()
