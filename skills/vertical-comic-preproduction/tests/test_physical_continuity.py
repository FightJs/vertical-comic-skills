"""Input and review regressions; synthetic records, never a visual model benchmark."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
from test_execution_quality import fx
from test_visual_evidence import fixture,reviewed
from input_quality import errors as input_errors,execution_block as input_block
from visual_evidence import (feasibility_questions,panel_errors,shot_collection_errors,
    review_template,review_errors,comparison_errors,continuity_targets)
from codex_reference_contract import digest


class PhysicalContinuityTests(unittest.TestCase):
    def hand_pair(self):
        _,p=fx();first=next(c for c in p['visual_evidence']['checks'] if c['kind']=='hand')
        first['actor_limb']='right_hand'
        second={**first,'id':'H2','target':'PHONE','target_part':'手机下缘','action_stage':'已接稳手机'}
        p['visual_evidence']['checks'].append(second)
        return p,first,second

    def test_same_limb_cannot_silently_hold_two_different_objects(self):
        p,_,_=self.hand_pair()
        self.assertTrue(any('同一肢体' in e for e in input_errors(p)))
        with self.assertRaises(ValueError):input_block(p)

    def test_two_hands_or_two_people_are_not_duplicate_limbs(self):
        for change in ({'actor_limb':'left_hand'},{'actor':'B'}):
            p,_,second=self.hand_pair();second.update(change)
            self.assertEqual(input_errors(p),[])

    def test_transfer_allows_two_people_touching_one_object(self):
        p,first,second=self.hand_pair();second.update(actor='B',target=first['target'])
        self.assertEqual(input_errors(p),[])

    def test_joint_grip_requires_one_concrete_shared_basis_and_compiles_it(self):
        p,first,second=self.hand_pair()
        first['combined_grip_basis']='SYNTHETIC共同夹持两件薄物；由同一掌面承重'
        self.assertTrue(input_errors(p))
        second['combined_grip_basis']=first['combined_grip_basis']
        self.assertEqual(input_errors(p),[])
        self.assertIn(first['combined_grip_basis'],input_block(p))
        second['combined_grip_basis']='SYNTHETIC不同解释'
        self.assertTrue(input_errors(p))

    def test_conditional_prompt_does_not_impose_people_on_empty_scene(self):
        _,p=fx();block=input_block(p)
        self.assertIn('不为递接或修复另生一只手',block)
        self.assertIn('俯拍不使人物自动仰头',block)
        self.assertIn('不为展示内容把屏幕翻向观众',block)
        p['visual_evidence']['checks']=[c for c in p['visual_evidence']['checks'] if c['kind'] not in {'hand','contact'}]
        p['visual_evidence']['blocking']={}
        p['visual_evidence']['hands'].update(narrative_role='not_visible',applicability='NOT_VISIBLE')
        block=input_block(p)
        self.assertNotIn('逐人物保持唯一',block);self.assertNotIn('俯拍不使人物',block)

    def test_staging_review_invalidates_when_gaze_or_persistent_state_changes(self):
        _,p=fx();old=feasibility_questions(p)
        p['characters_visible']=[{'character_id':'A','gaze':'对话者，不看摄影机'}]
        self.assertNotEqual(old,feasibility_questions(p))
        old=feasibility_questions(p);p['visual_evidence']['blocking']['A']['position']='SEAT-2'
        self.assertNotEqual(old,feasibility_questions(p))

    def test_optional_anchor_is_not_a_generation_dependency(self):
        _,p=fixture();p['panel_id']='P003';p['visual_evidence'].update(previous_panel_id='P002',comparison_panel_ids=['P001'])
        self.assertEqual(continuity_targets(p),['P002','P001'])
        self.assertNotIn('generation_dependencies',p)
        self.assertTrue(any('P001:' in e for e in review_errors(p,reviewed(p))))

    def test_anchor_must_be_earlier_and_in_same_space_and_state(self):
        b,p=fixture();panels=[]
        for n in range(1,4):
            q=copy.deepcopy(p);q['panel_id']=f'P{n:03d}'
            q['visual_evidence']['previous_panel_id']=f'P{n-1:03d}' if n>1 else None
            panels.append(q)
        panels[-1]['visual_evidence']['comparison_panel_ids']=['P001']
        shots={'visual_evidence_policy':b['visual_evidence_policy'],'panels':panels}
        self.assertEqual(shot_collection_errors(b,b,shots),[])
        panels[-1]['visual_evidence']['comparison_panel_ids']=['P004']
        self.assertTrue(any('补充比较' in e for e in shot_collection_errors(b,b,shots)))
        panels[-1]['visual_evidence'].update(comparison_panel_ids=['P001'],scene_run_id='later',run_change_basis='SYNTHETIC time jump')
        self.assertTrue(any('补充比较' in e for e in shot_collection_errors(b,b,shots)))

    def test_anchor_list_rejects_self_duplicates_and_malformed_ids(self):
        for value in (['P001'],['P000','P000'],[{}],None):
            _,p=fixture();p['visual_evidence']['comparison_panel_ids']=value
            self.assertTrue(any('补充连续性' in e for e in panel_errors(p)))

    def test_earlier_anchor_revision_invalidates_comparison_even_if_nearest_is_unchanged(self):
        _,p=fixture();p['visual_evidence'].update(previous_panel_id='P002',comparison_panel_ids=['P000'])
        item=reviewed(p)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);records={};rows=[]
            for pid in ['P000','P002']:
                path=root/(pid+'.png');path.write_bytes(b'SYNTHETIC file evidence '+pid.encode())
                ref={'path':path.name,'sha256':digest(path)};records[pid]={'output':ref}
                rows.append({'panel_id':pid,'image':copy.deepcopy(ref),'status':'PASS','observed':'SYNTHETIC固定锚点已比较'})
            item['visual_evidence_review']['continuity_comparisons']=rows
            self.assertEqual(review_errors(p,item),[])
            self.assertEqual(comparison_errors(p,item,records,root),[])
            records['P000']['output']['sha256']='new-output'
            errors=comparison_errors(p,item,records,root)
            self.assertEqual(len(errors),1);self.assertIn('P000:',errors[0])

    def test_structural_repair_needs_whole_subject_observation_not_just_local_pass(self):
        _,p=fixture();p['operation']='repair'
        p['repair_focus']={'structural_change':{'remove':'旧手臂','replace':'新前臂','connect':'同一肩肘'}}
        p['repair_source']={'image_sha256':'base','preserved_features':['衣装']}
        self.assertEqual(review_template(p)['repair_comparison']['whole_subject_recheck']['status'],'UNREVIEWED')
        item=reviewed(p);repair=item['visual_evidence_review']['repair_comparison']
        repair.update(base_image_sha256='base',clarity_status='PASS',observed='SYNTHETIC局部对比',preserved_features=['衣装'])
        self.assertTrue(any('结构返修' in e for e in review_errors(p,item)))
        repair['whole_subject_recheck']={'status':'PASS','observed':'SYNTHETIC按人计数，旧结构已除，连接及承托已比较'}
        self.assertEqual(review_errors(p,item),[])
        repair['whole_subject_recheck']['status']='FAIL'
        self.assertTrue(review_errors(p,item))
        self.assertEqual(review_errors(p,item,require_pass=False),[])

    def test_uncertain_visible_anatomy_is_not_pass_even_with_successful_file_check(self):
        _,p=fixture();item=reviewed(p)
        item['visual_evidence_review']['observations'][2].update(status='UNREVIEWED',observed='SYNTHETIC当前原图无法辨认连接')
        self.assertTrue(review_errors(p,item))

    def test_same_scale_reverse_shot_is_allowed_but_label_only_repeat_is_not(self):
        from validate_preproduction import Gate
        first={'panel_id':'P001','camera_angle_family':'eye_level','shot_scale':'close',
               'camera_position':'door','characters_visible':[{'id':'A'}],'visible_region':'A胸以上'}
        second={**first,'panel_id':'P002','camera_position':'window','characters_visible':[{'id':'B'}],
                'visible_region':'B胸以上','adjacent_change_reason':'SYNTHETIC B回答A'}
        gate=Gate(Path('.'));gate.check_adjacent(first,second);self.assertEqual(gate.errors,[])
        second={**first,'panel_id':'P002','camera_signature':'renamed','adjacent_change_reason':'changed label'}
        gate=Gate(Path('.'));gate.check_adjacent(first,second);self.assertTrue(gate.errors)

    def test_v2_rule_checks_do_not_rewrite_frozen_v1(self):
        from test_rule_memory import library
        from rule_memory import select,application_errors
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=library(root/'rules');index_path=root/'rules/记忆索引.json'
            index=json.loads(index_path.read_text());r=index['rules'][0]
            r.update(id='MEM-010',version='2.0.0');r['trigger']={'any_tags':['adjacent_panel_pair'],'any_visual_terms':[]}
            checks=['adjacent_pair_basis','narrative_coverage','framing_economy','physical_continuity_preserved']
            for req in r['requirements'].values():req.update(checks=checks,artifacts=[],prompt_constraints=False)
            index_path.write_text(json.dumps(index))
            p={'panel_id':'P002','memory_tags':['adjacent_panel_pair']};match=select(source,'shot_design',p)[0]
            app={'memory_id':'MEM-010','rule_version':r['version'],'rule_signature':match['rule_signature'],
                 'rule_sha256':r['file']['sha256'],'decision':'APPLIED','reviewer':'SYNTHETIC','evidence':'SYNTHETIC same-scale reply',
                 'checks':{c:{'status':'PASS','evidence':'SYNTHETIC record'} for c in checks},'artifacts':[],'prompt_constraints':[]}
            p['memory_applications']={'shot_design':[app]}
            self.assertEqual(application_errors(source,'shot_design',p,root),[])
            r['version']='1.1.0'
            for req in r['requirements'].values():req['checks']=['camera_view_distinct','shot_scale_distinct']
            index_path.write_text(json.dumps(index))
            self.assertTrue(application_errors(source,'shot_design',p,root))


if __name__=='__main__':unittest.main()
