"""Scoped production decisions and image-quality regressions; synthetic, no image calls."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests')]
from codex_reference_contract import digest
from review_policy import proposal,delegated_decisions,decision_errors,DECIDED,technical_errors
from staged_workflow import approval_errors
from scoped_inputs import approval_for,build_plan,resolve_context
from visual_evidence import review_errors,execution_block
from input_quality import scene_reference_errors
from production_metrics import build,union_seconds
import test_visual_evidence as ve
import test_execution_quality as eq
import test_production_runtime as rt
import test_repair_input_guard as guard_fixture


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.artifact=self.write('shots.json',{})
        self.grant={'policy':'user_delegation_v1','status':'AUTHORIZED','source_kind':'user_message',
            'quote':'SYNTHETIC explicit delegation of listed phases and panels',
            'source_locator':'synthetic-message:1','book_id':'T','episode_ids':['E1'],
            'panel_ids':{'E1':['P001','P002']},'phases':['shot_design','generation_package','state_review','final','technical_operations'],
            'operations':['information_preserving_crop'],'constraints':['Keep story, identity and real QA']}
        self.review=proposal('T','E1',[{'item_id':'B','phase':'shot_design','panel_ids':['P001'],
            'artifacts':[self.artifact],'summary':'Synthetic reviewed shot'}],self.root)

    def write(self,name,value):
        p=self.root/name;p.write_text(json.dumps(value), encoding='utf-8', newline='\n');return {'path':name,'sha256':digest(p)}

    def decide(self):
        return delegated_decisions(self.review,['B'],self.write('grant.json',self.grant),'synthetic agent',
                                   'Synthetic actually scoped decision',self.root)[0]

    def test_actual_authority_keeps_agent_decision_distinct_and_gate_scoped(self):
        p=self.decide();self.assertEqual(p['status'],DECIDED);self.assertNotIn('quote',p)
        s={'book_id':'T','episode_id':'E1'}
        self.assertEqual(approval_for(s,self.root,'shot_design',[self.artifact],['P001'],p),[])
        self.assertTrue(approval_for(s,self.root,'generation_package',[self.artifact],['P001'],p))
        self.assertTrue(approval_for(s,self.root,'shot_design',[self.artifact],['P002'],p))
        self.assertTrue(approval_errors(p,self.root,[self.artifact],'T','E1'))

    def test_missing_message_scope_retained_phase_and_technical_budget_fail(self):
        original=copy.deepcopy(self.grant)
        for change in ['message','book','episode','panel','retained','phase']:
            self.grant=copy.deepcopy(original)
            if change=='message':self.grant.pop('source_locator')
            if change=='book':self.grant['book_id']='OTHER'
            if change=='episode':self.grant['episode_ids']=[]
            if change=='panel':self.grant['excluded_panel_ids']={'E1':['P001']}
            if change=='retained':self.grant['retained_user_phases']=['shot_design']
            if change=='phase':self.grant['phases']=[]
            with self.assertRaises(ValueError,msg=change):self.decide()

    def test_grant_tamper_and_foreign_artifact_do_not_release(self):
        p=self.decide();other=self.write('other.json',{'different':True})
        self.assertTrue(approval_errors(p,self.root,[other],'T','E1',phase='shot_design'))
        (self.root/'grant.json').write_text('{}', encoding='utf-8', newline='\n')
        self.assertTrue(decision_errors(p,self.root,'T','E1'))

    def test_technical_operation_and_exact_additional_attempts(self):
        item=self.review['items'][0]
        item.update(phase='technical_operations',operations=['information_preserving_crop'],constraints=['Keep all required action'])
        self.review=proposal('T','E1',self.review['items'],self.root);p=self.decide()
        self.assertEqual(technical_errors(p,self.root,'T','E1','P001','information_preserving_crop',[self.artifact]),[])
        self.assertTrue(technical_errors(p,self.root,'T','E1','P001','equal_scale_normalize',[self.artifact]))
        self.grant['phases'].append('additional_repair')
        self.grant['additional_attempt_ids']={'E1':{'P001':['manual-total3']}}
        item.update(phase='additional_repair',attempt_ids={'P001':['manual-total3']})
        self.review=proposal('T','E1',[item],self.root);p=self.decide()
        self.assertEqual(decision_errors(p,self.root,'T','E1'),[])
        p['attempt_ids']['P001']=['manual-total4']
        self.assertTrue(decision_errors(p,self.root,'T','E1'))

    def test_readiness_index_keeps_same_phase_and_row_authority(self):
        p=self.decide();proof=self.write('decision.json',p)
        state={'book_id':'T','episode_id':'E1','readiness_policy':'panel_readiness_v1',
               'approval_index':self.write('index.json',{'policy':'approval_index_v1','entries':[
                   {'phase':'shot_design','book_id':'T','episode_ids':['E1'],'panel_ids':['P001'],'approval':proof}]})}
        self.assertEqual(approval_for(state,self.root,'shot_design',[self.artifact],['P001']),[])
        self.assertTrue(approval_for(state,self.root,'final',[self.artifact],['P001']))

    def test_real_package_gate_accepts_covered_decision_without_fake_user_approval(self):
        h=rt.RuntimeTests('test_bulk_same_verdict_as_full_single_panel_gate_and_real_arguments')
        h.setUp();self.addCleanup(h.doCleanups)
        s=h.scoped();h.enable_package(s)
        from scoped_inputs import half_view
        v=half_view(s,'H001');bundle=s['generation_packages']['H001'][0]
        grant=copy.deepcopy(self.grant);grant.update(book_id=s['book_id'],episode_ids=[s['episode_id']],panel_ids={s['episode_id']:['P001']})
        g=h.h.h.f.write('actual-delegation.json',grant)
        rev=proposal(s['book_id'],s['episode_id'],[{'item_id':'PACKAGE','phase':'generation_package','panel_ids':['P001'],
            'artifacts':[bundle,v['visual_basis'],v['shot_manifest']],'summary':'Exact synthetic package'}],h.root)
        p=delegated_decisions(rev,['PACKAGE'],g,'synthetic agent','Synthetic package observed',h.root)[0]
        ref=h.h.h.f.write('actual-agent-decision.json',p)
        s['approval_index']=h.h.h.f.write('actual-index.json',{'policy':'approval_index_v1','entries':[
            {'phase':'generation_package','book_id':s['book_id'],'episode_ids':[s['episode_id']],'panel_ids':['P001'],'approval':ref}]})
        from _historical_fixture import compile_jobs
        self.assertEqual(len(compile_jobs(s,h.root)['jobs']),1)

    def test_delegated_prior_context_keeps_accurate_A_and_B_scope(self):
        from continuity_context import load_context
        script=self.write('script.json',{'synthetic':'source'})
        locked={'P001':'first','P002':'second'}
        source=self.write('snapshot.json',{'source_sha256':script['sha256'],'panel_ids':list(locked),'locked_scripts':locked})
        basis=self.write('basis.json',{'book_id':'T','episode_id':'E1'})
        shots=self.write('shots.json',{'book_id':'T','episode_id':'E1','panels':[{'panel_id':p,'locked_script':s} for p,s in locked.items()]})
        self.grant['phases'].append('visual_basis');grant=self.write('grant.json',self.grant)
        review=proposal('T','E1',[
            {'item_id':'A','phase':'visual_basis','panel_ids':list(locked),'artifacts':[script,source,basis],'summary':'Synthetic A'},
            {'item_id':'B','phase':'shot_design','panel_ids':list(locked),'artifacts':[basis,shots],'summary':'Synthetic B'}],self.root)
        a,b=delegated_decisions(review,['A','B'],grant,'synthetic reviewer','Synthetic source inspected',self.root)
        ctx={'policy':'approved_shot_context_v1','book_id':'T','current':{'episode_id':'E1','panel_id':'P002'},
             'episode_order':['E1'],'sources':[{'root':str(self.root),'episode_id':'E1','source_script':script,
                'source_snapshot':source,'visual_basis':basis,'shot_manifest':shots,'visual_approval':a,'shot_approval':b}],
             'entries':[{'source':0,'panel_id':'P001'}]}
        manifest={'book_id':'T','episode_id':'E1','panels':[{'panel_id':'P002'}],'continuity_context':self.write('context.json',ctx)}
        prior,errors=load_context(manifest,self.root);self.assertEqual(errors,[]);self.assertIn('E1-P001',prior)

    def test_user_additional_proof_retains_attempts_and_rejects_duplicate_ids(self):
        from review_policy import approvals
        item={'item_id':'EXTRA','phase':'additional_repair','panel_ids':['P001'],'artifacts':[self.artifact],
              'summary':'Synthetic extra','constraints':['one exact attempt'],'attempt_ids':{'P001':['extra3']}}
        review=proposal('T','E1',[item],self.root)
        proof=approvals(review,['EXTRA'],{'source_kind':'user_message','quote':'SYNTHETIC explicit extra3','source_locator':'synthetic:2'},self.root)[0]
        self.assertEqual(proof['attempt_ids'],item['attempt_ids'])
        item['attempt_ids']['P001']=['extra3','extra3']
        with self.assertRaises(ValueError):proposal('T','E1',[item],self.root)


class QualityTests(unittest.TestCase):
    def test_atlas_detail_readability_stays_inside_owning_character(self):
        import test_execution_contract as ec
        from reference_atlas import verify_owner
        h=ec.Contracts();h.setUp();self.addCleanup(h.doCleanups);ref,assets=h.atlas()
        ref['detail_readability']=[{'subject_id':'A','detail_id':'earring','region':[0,0,2,2],
                                   'status':'PASS','observed':'Synthetic original pixels inspected'}]
        self.assertEqual(verify_owner(ref,assets['A'],'A','identity',h.root),[])
        ref['detail_readability'][0]['region']=[4,0,6,2]
        self.assertTrue(verify_owner(ref,assets['A'],'A','identity',h.root))

    def test_roi_must_cover_frozen_targets_and_not_claim_resampled_pixels(self):
        _,p=eq.fx();hand=next(c for c in p['visual_evidence']['checks'] if c['kind']=='hand')
        hand['inspection_targets']=['wrist and owning forearm','cup contact']
        item=ve.reviewed(p)
        self.assertTrue(any('未覆盖' in e for e in review_errors(p,item)))
        observed=next(c for c in item['visual_evidence_review']['observations'] if c['kind']=='hand')
        observed['view']['covered_targets']=hand['inspection_targets']
        self.assertEqual(review_errors(p,item),[])
        observed['view']['resampled']=True
        self.assertTrue(any('重采样' in e for e in review_errors(p,item)))

    def test_structural_repair_requires_old_removal_and_new_connection_in_actual_prompt(self):
        from repair_input_guard import repair_errors
        p=guard_fixture.RepairInputGuardTests().panel()
        structure={'remove':'remove the old hanging arm','replace':'replace with the raised forearm','connect':'connect wrist to the same elbow'}
        p['repair_focus']['structural_change']=structure
        self.assertTrue(repair_errors(p))
        p['prompt']+=';'.join(structure.values())
        self.assertEqual(repair_errors(p),[])

    def test_local_edit_requires_explicit_preservation_observations(self):
        _,p=eq.fx();p.update(operation='repair',repair_source={'image_sha256':'base','source_attempt_id':'first',
            'selection_reason':'clearest original','preserved_features':['face and costume'],
            'preservation_regions':{'face':[0,0,100,100]}})
        item=ve.reviewed(p);r=item['visual_evidence_review']
        r['repair_comparison']={'base_image_sha256':'base','clarity_status':'PASS','observed':'Synthetic same-scale comparison',
                                'preserved_features':['face and costume']}
        self.assertTrue(any('保留区域' in e for e in review_errors(p,item)))
        r['repair_comparison']['preserved_observations']={'face':{'status':'PASS','observed':'Synthetic face unchanged'}}
        self.assertEqual(review_errors(p,item),[])
        r['repair_comparison']['preserved_observations']['face']['status']='FAIL'
        self.assertTrue(review_errors(p,item))

    def test_actual_reference_validator_itself_rejects_missing_scene(self):
        _,p=eq.fx();p['reference_images']=[]
        self.assertTrue(scene_reference_errors(p,Path('.')))

    def test_preservation_regions_are_checked_against_real_base_not_declared_size(self):
        from PIL import Image
        from visual_evidence import repair_basis
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);base=root/'base.png';Image.new('RGB',(100,100)).save(base)
            ref={'path':'base.png','sha256':digest(base)}
            basis,p=eq.fx();pid=p['panel_id'];p['operation']='repair'
            p['repair_source']={'image_sha256':ref['sha256'],'source_attempt_id':'first',
                'selection_reason':'Synthetic clearest base','preserved_features':['keep face'],
                'preservation_regions':{'face':[1000,1000,1100,1100]}}
            p['prompt']+='keep face'
            p['reference_images'].append({**ref,'alias':'@REPAIR_TARGET','role':'edit_target'})
            p.setdefault('reference_bindings',[]).append({'alias':'@REPAIR_TARGET','purpose':'framing','subject_ids':[pid]})
            state={'visual_evidence_policy':'visual_evidence_v1'};records={pid:{'attempt_id':'first','output':ref}}
            with self.assertRaises(ValueError):repair_basis(state,root,p,basis,records)
            p['repair_source']['preservation_regions']['face']=[0,0,80,80]
            self.assertEqual(repair_basis(state,root,p,basis,records)['reference_files'][-1],ref)

    def test_concise_prompt_preserves_executable_constraints_once(self):
        from repair_prompt_package_v2 import build_prompt
        _,p=eq.fx();p['locked_script']='Synthetic hold cup'
        p['visible_region']='waist up, wrist and cup visible'
        block=execution_block(p)
        prompt,_,_=build_prompt(p,'three_quarter_left','medium_close','3:4','near table','toward A','eye level',
                               p['visible_region'],['@SCENE','@A'],None,None,'INTERNAL-SIGNATURE','A holds cup')
        self.assertIn(block,prompt);self.assertEqual(prompt.count(block),1)
        self.assertNotIn('INTERNAL-SIGNATURE',prompt);self.assertNotIn('本次唯一第二轮',prompt)


class ContextAndMetricTests(unittest.TestCase):
    def test_context_is_source_ordered_read_only_and_rejects_ambiguous_records(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            def w(name,v):p=root/name;p.write_text(json.dumps(v), encoding='utf-8', newline='\n');return {'path':name,'sha256':digest(p)}
            source={'panel_ids':['P001','P002']}
            state={'execution_mode':'episode_async_v1','preparation_policy':'episode_preparation_v1',
                   'source_snapshot':w('source.json',source),'visual_basis':w('basis.json',{}),
                   'shot_manifest':w('shots.json',{'panels':[{'panel_id':p} for p in source['panel_ids']]}),
                   'panels':[{'panel_id':p,'attempt_history':[{'package_manifest':{'path':'old.json','sha256':'old'}}]} for p in source['panel_ids']]}
            state['batch_plan']=w('plan.json',build_plan(state,source));before=copy.deepcopy(state)
            ctx=resolve_context(state,root,'EPISODE')
            self.assertEqual(list(ctx['records']),source['panel_ids']);self.assertEqual(state,before)
            state['panels'].reverse()
            with self.assertRaises(ValueError):resolve_context(state,root,'EPISODE')

    def test_concurrent_phase_union_is_not_sum_and_missing_times_stay_unknown(self):
        self.assertEqual(union_seconds([(0,10),(5,12),(20,21)]),13)
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);folder=root/'00_输入审计';folder.mkdir();p=folder/'state.json'
            p.write_text(json.dumps({'book_id':'T','episode_id':'E1','panels':[
                {'panel_id':'P001','attempt_id':'a','round_id':1,'status':'GENERATED','submitted_at':'2026-10-01T00:00:00Z','returned_at':'2026-10-01T00:00:10Z'},
                {'panel_id':'P002','attempt_id':'b','round_id':1,'status':'GENERATED','submitted_at':'2026-10-01T00:00:05Z','returned_at':'2026-10-01T00:00:15Z'}]}), encoding='utf-8', newline='\n')
            stats=build([p]);phases=stats['timing']['phase_windows']
            self.assertEqual(phases['submit_to_return']['union_seconds'],15)
            self.assertEqual(phases['submit_to_return']['sum_seconds_not_wall_time'],20)
            self.assertIsNone(phases['ready_to_submit']['union_seconds'])
            self.assertIsNone(stats['edit_regression']['rate'])


if __name__=='__main__':unittest.main()
