"""Synthetic contract regressions; no image-service calls or actual QA approval."""
import copy
import json
import sys
import unittest
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts'), str(Path(__file__).parent)]
import spatial_contract as sp
import visual_evidence as ve
import test_appearance_lock as appearance
from input_semantics import scoped_input_signals, conflict_errors
from repair_routes import plan
from repair_prompt_package_v2 import build_prompt, character_details


def fixture():
    b, p = appearance.fixture()
    p.update(camera_angle_family='level', shot_scale='medium', frame_ratio='3:4',
             camera_position='SEAT-2', facing_direction='TABLE', camera_height='eye',
             visible_region='人物与桌缘', camera_view_signature='scene-v1',
             locked_script={'event_text':'人物坐在桌边握杯'})
    ev = p['visual_evidence']
    ev['selected_relation_ids'] = ['table-stage']
    ev['checks'][0]['relation_ids'] = ['table-stage']
    bind_projection(p)
    p['prompt'] = p['visual_execution_block'] = ve.execution_block(p)
    return b, p


def bind_projection(p):
    for row in p['visual_evidence']['detail_visibility'].values():
        if row['status'] == 'visible':
            row['projection']['basis_sha256'] = sp.projection_signature(p)


def decision(kind='rigid_edge', action='local_edit'):
    return {'policy':'first_batch_production_v1', 'action':action,
            'method_key':'spatial_local_edge', 'image':{'sha256':'synthetic'}, 'attempt_id':'P001-r1',
            'fix_now':['space'], 'opportunistic':[], 'manual':[],
            'issues':[{'id':'space','kind':'overall_structure' if kind in sp.GLOBAL_KINDS else 'local_geometry',
                       'category':1 if kind in sp.GLOBAL_KINDS else 2, 'certainty':'confirmed',
                       'repair_scope':'global_space' if kind in sp.GLOBAL_KINDS else 'local_structure',
                       'spatial_kind':kind}],
            'spatial_assessment':{'evidence':'SYNTHETIC实际观察位置', 'target_basis':'SYNTHETIC批准结构',
                'input_evidence':'SYNTHETIC已核对相关执行文字', 'input_status':'no_conflict_signal',
                'layout_status':'confirmed', 'camera_status':'confirmed'}}


class SpatialTests(unittest.TestCase):
    def test_relation_is_carried_even_with_offscreen_endpoint(self):
        b, p = fixture()
        # Neither endpoint has to be a character or required screen anchor.
        p['visual_evidence']['visibility']['STAGE']['status']='offscreen'
        bind_projection(p)
        line=b['scene_layouts']['HALL']['relations'][0]['expected']
        self.assertEqual(sp.selection_errors(p), [])
        self.assertIn(line, ve.execution_block(p))
        self.assertNotIn('STAGE', p['visual_evidence']['blocking'])

    def test_unselected_relations_do_not_leak(self):
        _, p = fixture()
        p['visual_evidence_context']['layout']['relations'].append(
            {'id':'unused','subject':'TABLE','object':'STAGE','expected':'UNSELECTED SYNTHETIC RELATION','reference_sha256':'scene'})
        self.assertNotIn('UNSELECTED SYNTHETIC RELATION', ve.execution_block(p))

    def test_invalid_foreign_duplicate_or_unreviewed_relation_rejected(self):
        for selected in [['foreign'],['table-stage','table-stage'],None,[{}]]:
            _, p=fixture();p['visual_evidence']['selected_relation_ids']=selected
            self.assertTrue(sp.selection_errors(p))
        _,p=fixture();p['visual_evidence']['checks'][0].pop('relation_ids')
        with self.assertRaises(ValueError):ve.execution_block(p)

    def test_projection_invalidates_on_camera_blocking_crop_and_action(self):
        _,p=fixture();before=copy.deepcopy(p)
        self.assertEqual(sp.projection_errors(p),[])
        for change in ('camera','blocking','crop','action'):
            q=copy.deepcopy(p)
            if change=='camera':q['camera_position']='opposite wall'
            if change=='blocking':q['visual_evidence']['blocking']['A']['position']='SEAT-3'
            if change=='crop':q['framing']['body_crop']='face_detail'
            if change=='action':q['characters_visible']=[{'character_id':'A','action':'standing'}]
            self.assertTrue(sp.projection_errors(q),change)
            self.assertTrue(conflict_errors(q,q['prompt']),change)
        self.assertEqual(p,before)  # No checker auto-rebinds projections.

    def test_rechecked_projection_compiles_and_hidden_detail_needs_no_fake_proof(self):
        _,p=fixture();p['camera_position']='opposite wall';bind_projection(p)
        self.assertEqual(sp.projection_errors(p),[])
        p['visual_evidence']['detail_visibility']['earring']={'status':'occluded','basis':'头发遮挡'}
        self.assertEqual(sp.projection_errors(p),[])
        self.assertIn('本细节投影位置',ve.execution_block(p))

    def test_changed_selected_reference_invalidates_projection(self):
        _,p=fixture();context=copy.deepcopy(p['visual_evidence_context'])
        context['layout']['relations'][0]['reference_sha256']='new-approved-reference'
        self.assertTrue(sp.projection_errors(p,context))
        self.assertEqual(sp.projection_errors(p),[])

    def test_changed_builder_arguments_cannot_reuse_projection_signature(self):
        _,p=fixture()
        args=[p,p['camera_angle_family'],p['shot_scale'],p['frame_ratio'],p['camera_position'],
              p['facing_direction'],p['camera_height'],p['visible_region'],[],None,None,p['camera_view_signature'],'']
        self.assertIn('主桌',build_prompt(*args)[0])
        args[4]='different camera'
        with self.assertRaisesRegex(ValueError,'投影'):build_prompt(*args)

    def test_derived_positions_use_current_blocking_and_visibility(self):
        _,p=fixture()
        p['characters_visible']=[{'character_id':'A','name':'甲','screen_position':'STALE LOCATION',
                                 'relative_position':'STALE ORIENTATION','action':'握杯'}]
        bind_projection(p)
        result=character_details(p,'握杯','level',p['visible_region'])
        self.assertNotIn('STALE',result)
        self.assertIn('SEAT-1',result)
        self.assertIn(p['visual_evidence']['visibility']['A']['expected'],result)

    def test_derivation_rejects_silent_execution_override(self):
        from panel_derivation import effective
        _,p=fixture();row={'shot':p,'execution':{'camera_position':'other'},'packet_header':{}}
        with self.assertRaisesRegex(ValueError,'重复定义'):effective({'shared':{}},row)
        row['execution']={'camera_position':p['camera_position']}
        self.assertEqual(effective({'shared':{}},row)[1]['camera_position'],p['camera_position'])

    def test_location_hint_does_not_claim_semantic_failure(self):
        _,p=fixture();p['visual_evidence']['detail_visibility']['coat']['projection']['screen_position']='甲在目的地门外，退路沿楼梯'
        self.assertTrue(any(x['kind']=='appearance_location_leak' for x in scoped_input_signals(p,p['prompt'])))
        self.assertEqual(conflict_errors(p,p['prompt']),[])

    def test_raw_request_location_hint_and_negation(self):
        prompt='衣装｜本镜头位置=人物已在目的地门外，退路沿楼梯；遮挡=手臂。'
        self.assertTrue(any(x['kind']=='appearance_location_leak' for x in scoped_input_signals({},prompt)))
        self.assertEqual(scoped_input_signals({},'不要沿用'+prompt),[])
        self.assertEqual(conflict_errors({},prompt),[])

    def test_new_risk_tags_require_explicit_selection(self):
        for tag in ('fixed_spatial_relations','framing_space_conflict'):
            b,p=appearance.fixture();p['memory_tags']=[tag]
            self.assertTrue(sp.selection_errors(p))
            with self.assertRaises(ValueError):ve.execution_block(p)
        self.assertEqual(sp.selection_errors({'memory_tags':['camera_change']}),[])

    def test_spatial_repair_requires_whole_subject_recheck(self):
        _,p=fixture();p['operation']='repair';p['repair_focus']={'spatial_issue_checks':{'space':['S1']}}
        review=ve.review_template(p)
        self.assertEqual(review['repair_comparison']['whole_subject_recheck']['status'],'UNREVIEWED')

    def test_existing_gate_rejects_omitted_selection_and_stale_qa(self):
        b,p=fixture();self.assertEqual(ve.packet_errors(b,p,p,b),[])
        q=copy.deepcopy(p);q['visual_evidence'].pop('selected_relation_ids')
        self.assertTrue(ve.packet_errors(b,p,q,b))
        item=appearance.reviewed(p);self.assertEqual(ve.review_errors(p,item),[])
        p['visual_evidence']['checks'][0]['expected']='changed structure'
        self.assertTrue(ve.review_errors(p,item))

    def test_local_global_and_unknown_routes(self):
        d=decision();r={'output':d['image'],'attempt_id':d['attempt_id'],'round_id':1}
        self.assertEqual(plan(d,r)['route'],'local_edit')
        for kind in sp.GLOBAL_KINDS:
            bad=decision(kind)
            with self.assertRaises(ValueError):plan(bad,r)
            self.assertEqual(plan(decision(kind,'rebuild_inputs'),r)['route'],'rebuild_inputs')
        with self.assertRaises(ValueError):plan(decision('uncertain'),r)
        self.assertEqual(plan(decision('uncertain','stop_diagnose'),r)['route'],'stop_diagnose')

    def test_local_edge_requires_established_layout_and_camera(self):
        for key in ('layout_status','camera_status'):
            d=decision();d['spatial_assessment'][key]='unknown'
            self.assertTrue(sp.decision_errors(d))
        d=decision();d['spatial_assessment']['input_status']='resolved'
        self.assertTrue(sp.decision_errors(d))
        d['spatial_assessment']['resolution_evidence']='SYNTHETIC corrected conflicting source'
        self.assertEqual(sp.decision_errors(d),[])

    def test_global_problem_cannot_be_hidden_in_manual_group(self):
        d=decision();row=decision('layout_connection')['issues'][0];row['id']='global'
        d['issues'].append(row);d['manual']=['global']
        self.assertTrue(sp.decision_errors(d))

    def test_coordinate_route_cannot_bypass_spatial_scope(self):
        import coordinate_repair as cr
        d=decision('layout_connection');d['method_key']=cr.METHOD
        self.assertTrue(cr.decision_errors(d))

    def test_production_decision_guard_calls_same_spatial_validator(self):
        from production_decisions import decision_errors
        d=decision('layout_connection');d['issues'][0].update(location='wall',problem='wrong connection',
            target='approved connection',basis='approved image',handling='repair',observations=['/space'])
        result=decision_errors(d,{'output':d['image'],'attempt_id':d['attempt_id']},{'space':{'status':'FAIL'}})
        self.assertTrue(any('SPATIAL_HOLD' in x for x in result))

    def test_actual_repair_targets_must_reach_existing_qa(self):
        _,p=fixture();d=decision()
        self.assertTrue(sp.binding_errors(d,p))
        p['repair_focus']={'spatial_issue_checks':{'space':['S1']}}
        self.assertEqual(sp.binding_errors(d,p),[])
        p['repair_focus']['spatial_issue_checks']['space']=['Q1']
        self.assertTrue(sp.binding_errors(d,p))

    def test_round_limit_is_not_reset(self):
        d=decision();r={'output':d['image'],'attempt_id':d['attempt_id'],'round_id':2}
        self.assertEqual(plan(d,r)['route'],'stop_diagnose')
        r['round_id']=1;d['same_problem_persists']=True
        self.assertEqual(plan(d,r)['route'],'stop_diagnose')

    def test_ordinary_and_old_panels_remain_unchanged(self):
        b,p=appearance.fixture()
        original=p['prompt']
        self.assertEqual(sp.selection_errors(p),[])
        self.assertEqual(sp.projection_errors(p),[])
        self.assertEqual(ve.execution_block(p),original)
        self.assertEqual(sp.decision_errors({'action':'local_edit'}),[])

    def test_rules_are_selected_not_loaded_as_global_constraints(self):
        from rule_memory import select, source_index
        root=Path(__file__).resolve().parents[1]/'assets/rule-memory/内置规则'
        source={'policy':'triggered_rules_v1','root':str(root),'index':'记忆索引.json',
                'loading_policy':'stage_baseline_loading_v1'}
        source_index(source)
        self.assertEqual(select(source,'generation',{'memory_tags':[]}),[])
        picked=select(source,'generation',{'memory_tags':['fixed_spatial_relations','framing_space_conflict']})
        self.assertEqual({x['rule']['id'] for x in picked},{'MEM-003','MEM-009'})


if __name__=='__main__':unittest.main()
