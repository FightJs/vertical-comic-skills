"""Synthetic behavior tests. No image-service calls or production-state changes."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts'), str(Path(__file__).parent)]
import coordinate_repair as cr
from repair_routes import plan
from repair_input_guard import repair_errors
from input_semantics import scoped_input_signals


def panel():
    source = {'image_sha256': 'a'*64,'source_attempt_id':'P001-r1','selection_reason':'SYNTHETIC清晰底图',
              'preserved_features':['保留脸和批准伤势'], 'preservation_regions':{'face':[0,0,20,20]}}
    c = {'policy':cr.POLICY,'coordinate_system':'percent_top_left','source_image_sha256':'a'*64,
         'source_size':[100,200],'issue_ids':['limb'],
         'edit_regions':[{'id':'A','issue_id':'limb','object':'近侧动物后肢','box':[30,40,90,95],
                          'instruction':'清除侧腹旧肢，恢复鳞皮；重建后肢'}],
         'anchors':[{'id':'hip','region_id':'A','kind':'point','points':[[70,60]],'purpose':'从骨盆连接'}],
         'expected_observations':{'attachment':'唯一后肢连接骨盆','toes':'脚趾符合批准物种及遮挡'}}
    p = {'panel_id':'P001','operation':'repair','visual_evidence_policy':'visual_evidence_v1',
         'repair_source':source,'repair_focus':{'failed_transfers':['pose'], 'coordinate_edit':c,
          'structural_change':{'remove':'清除旧后肢及残留','replace':'只画一条新后肢','connect':'从骨盆经膝踝到足，足贴地'}},
         'reference_images':[{'alias':'@REPAIR_TARGET','sha256':'a'*64,'role':'edit_target'}],
         'reference_bindings':[{'alias':'@REPAIR_TARGET','purpose':'pose_interaction','allowed_transfer':['composition'],'forbidden_transfer':['pose']}],
         'prompt':''}
    p['prompt']=cr.execution_block(p)
    return p


def decision():
    return {'policy':'first_batch_production_v1','action':'local_edit','method_key':cr.METHOD,
            'image':{'sha256':'a'*64},'attempt_id':'P001-r1',
            'fix_now':['limb'],'opportunistic':[],'manual':[],
            'issues':[{'id':'limb','kind':'extra_limb','certainty':'confirmed','repair_scope':'local_structure'}],
            'coordinate_assessment':{'evidence':'已看局部归属错误，房间无整体问题','target_basis':'批准物种参考',
                'input_status':'no_conflict_signal','input_evidence':'相关肢体任务一致，沿用前期审查'}}


class CoordinateTests(unittest.TestCase):
    def test_local_animal_and_actual_prompt(self):
        p=panel();self.assertEqual(repair_errors(p),[])
        self.assertEqual(cr.binding_errors(decision(),p),[])
        self.assertIn('骨盆',p['prompt'])

    def test_global_or_uncertain_never_routes_to_coordinate(self):
        for scope in ['global_space','uncertain']:
            d=decision();d['issues'][0]['repair_scope']=scope
            self.assertTrue(cr.decision_errors(d))
        d=decision();d['issues'].append({'id':'room','repair_scope':'global_space','kind':'camera'})
        d['manual']=['room'];self.assertTrue(cr.decision_errors(d))

    def test_input_suspicion_and_resolution(self):
        d=decision();d['coordinate_assessment']['input_status']='suspected'
        self.assertTrue(cr.decision_errors(d))
        d['coordinate_assessment']['input_status']='resolved';self.assertTrue(cr.decision_errors(d))
        d['coordinate_assessment']['resolution_evidence']='已按原授权修正冲突并绑定新输入'
        self.assertEqual(cr.decision_errors(d),[])

    def test_budget_route_preserves_round_limit(self):
        d=decision();r={'attempt_id':d['attempt_id'],'output':d['image'],'round_id':1}
        self.assertEqual(plan(d,r)['route'],'local_edit')
        self.assertEqual(plan(d,{**r,'round_id':2})['route'],'stop_diagnose')
        self.assertEqual(plan({**d,'same_problem_persists':True},r)['route'],'stop_diagnose')

    def test_source_and_numeric_validation(self):
        p=panel();self.assertTrue(cr.errors(p,actual_size=[200,100]))
        for v in [[0,0,101,80],[0,0,0,10],[False,0,80,90],[0,0,float('nan'),90]]:
            q=copy.deepcopy(p);cr.spec(q)['edit_regions'][0]['box']=v
            self.assertTrue(cr.errors(q))
        cr.spec(p)['source_image_sha256']='b'*64;self.assertTrue(cr.errors(p))

    def test_overlap_requires_explanation(self):
        p=panel();p['repair_source']['preservation_regions']['body']=[20,70,80,180]
        self.assertTrue(cr.errors(p))
        cr.spec(p)['edit_regions'][0]['preservation_overlap']={'body':'只调整肢根连接处，保留躯干纹理与轮廓'}
        self.assertEqual(cr.errors(p),[])

    def test_stale_coordinates_and_method_mismatch(self):
        p=panel();cr.spec(p)['anchors'][0]['points']=[[72,61]]
        self.assertTrue(repair_errors(p))
        p['prompt']=cr.execution_block(p);self.assertEqual(repair_errors(p),[])
        self.assertTrue(cr.binding_errors({**decision(),'method_key':'ordinary_edit'},p))
        cr.spec(p)['issue_ids']=['different'];self.assertTrue(cr.binding_errors(decision(),p))

    def test_expected_partial_success_does_not_pass(self):
        p=panel();comparison={'coordinate_observations':{'attachment':{'status':'PASS','observed':'根部已改'},
                   'toes':{'status':'FAIL','observed':'趾数仍错'}}}
        self.assertTrue(cr.review_errors(p,comparison))
        self.assertEqual(cr.review_errors(p,comparison,False),[])
        comparison['coordinate_observations'].pop('toes');self.assertTrue(cr.review_errors(p,comparison,False))

    def test_ordinary_packets_are_unchanged(self):
        self.assertEqual(cr.errors({'operation':'generate'}),[])
        self.assertEqual(cr.execution_block({'operation':'generate'}),'')
        self.assertEqual(cr.decision_errors({'method_key':'old_method'}),[])

    def test_actual_image_dimensions_checked_in_existing_basis_gate(self):
        from PIL import Image
        from visual_evidence import repair_basis
        from codex_reference_contract import digest
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);image=root/'source.png';Image.new('RGB',(100,200)).save(image)
            p=panel();sha=digest(image)
            p['repair_source']['image_sha256']=sha;cr.spec(p)['source_image_sha256']=sha
            p['reference_images'][0]['sha256']=sha;p['prompt']=cr.execution_block(p)
            record={'attempt_id':'P001-r1','output':{'path':'source.png','sha256':sha}}
            state={'visual_evidence_policy':'visual_evidence_v1'}
            self.assertEqual(len(repair_basis(state,root,p,{'reference_files':[]},{'P001':record})['reference_files']),1)
            cr.spec(p)['source_size']=[100,201];p['prompt']=cr.execution_block(p)
            with self.assertRaises(ValueError):repair_basis(state,root,p,{'reference_files':[]},{'P001':record})

    def test_existing_builder_compiles_coordinate_block(self):
        from repair_prompt_package_v2 import build_prompt
        from test_visual_evidence import fixture
        _,base=fixture();p=panel();base.update(p);base['locked_script']={'event_text':'动物后足贴地'}
        result=build_prompt(base,'平视','medium','1:2','窗内','朝动物','平视','后肢局部', ['@REPAIR_TARGET'],None,None,'approved','动物保持姿态')
        self.assertIn(cr.execution_block(base),result[0])

    def test_qa_template_has_unreviewed_animal_targets(self):
        from test_visual_evidence import fixture
        from visual_evidence import review_template
        _,base=fixture();base.update(panel());qa=review_template(base)
        rows=qa['repair_comparison']['coordinate_observations']
        self.assertEqual(set(rows),{'attachment','toes'})
        self.assertTrue(all(v['status']=='UNREVIEWED' for v in rows.values()))

    def test_scoped_signals_are_not_a_generic_failure_detector(self):
        p={'visual_evidence':{'checks':[{'actor':'A','actor_limb':'right_hand','target':'A','target_part':'shoulder'}]}}
        self.assertEqual(len(scoped_input_signals(p,'世界固定依据：窗台承托双手。')),1)
        self.assertEqual(scoped_input_signals(p,'世界固定依据：不要画窗台承托双手。'),[])
        self.assertEqual(scoped_input_signals({},'台面保持笔直'),[])
        context={'details':{'scales':{'expected':'粗鳞背','placement':{'attachment':'领口、肩袖与身体连续连接'}}}}
        self.assertEqual(len(scoped_input_signals({},'',context)),1)

    def test_explicit_animal_no_clothing_rejects_human_template(self):
        from appearance_lock import detail_errors
        d={'subject_kind':'animal','clothing_applicable':False,'placement':{'attachment':'领口、肩袖与身体连续连接'}}
        self.assertTrue(any('动物体表' in e for e in detail_errors('scales',d)))
        d['clothing_applicable']=True
        self.assertFalse(any('动物体表' in e for e in detail_errors('coat',d)))

if __name__=='__main__':unittest.main()
