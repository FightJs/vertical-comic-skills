"""Scoped progress and approval reuse with isolated artifacts; no production or image calls."""
import copy,json,subprocess
from pathlib import Path
import sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import test_half_workflow as fixtures
import test_rule_memory as config_fixtures
from scoped_inputs import POLICY,build_plan,half_view,approval_for
from staged_workflow import evaluate,qa_errors
from review_reuse import session,fingerprint
from review_queue import build_queue
from usage_config import read_config

class ScopedTests(unittest.TestCase):
    def setUp(self):
        self.h=fixtures.HalfTests('test_all_fifteen_independent_pending_panels_are_eligible');self.h.setUp();self.addCleanup(self.h.doCleanups);self.root=self.h.root

    def state(self,n=4):
        state=self.h.state(n);state.update(optimization_policy=POLICY,half_inputs={},half_gates={})
        source=json.loads((self.root/state['source_snapshot']['path']).read_text(encoding='utf-8-sig'));self.h.plan=build_plan(state,source);state['batch_plan']=self.h.h.f.write('stable-plan.json',self.h.plan)
        for batch in self.h.plan['batches']:self.freeze(state,batch)
        return state

    def freeze(self,state,batch):
        ids=batch['panel_ids'];data={'execution_mode':'half_episode_async_v1','optimization_policy':POLICY,'panels':[p for p in self.h.h.shots if p['panel_id'] in ids]}
        shot=self.h.h.f.write(batch['batch_id']+'-shots.json',data);basis=state['visual_basis']
        state['half_inputs'][batch['batch_id']]={'visual_basis':basis,'shot_manifest':shot}
        state['half_gates'][batch['batch_id']]={'visual_basis':self.h.h.approve([state['source_script'],state['source_snapshot'],basis]),'shot_design':self.h.h.approve([basis,shot])}

    def record(self,state,i,status='VISUAL_PASS',round_id=1):
        r=self.h.record(state,i,status,round_id);path=self.root/r['package_manifest']['path'];data=json.loads(path.read_text(encoding='utf-8-sig'));data['optimization_policy']=POLICY;r['package_manifest']=self.h.h.f.write(path.name,data);return r

    def route(self,state,check='status',pid=None):return self.h.route(state,check,pid)

    def test_later_half_robe_hold_does_not_stop_first_half(self):
        state=self.state();state['holds']=[{'scope':'panels','panel_ids':['P003'],'evidence':'SYNTHETIC later costume only'}]
        self.assertEqual(self.route(state)['eligible_panel_ids'],['P001','P002'])

    def test_one_local_hold_allows_other_independent_current_panel(self):
        state=self.state();state['holds']=[{'scope':'panels','panel_ids':['P001'],'evidence':'SYNTHETIC one panel'}]
        result=self.route(state);self.assertEqual(result['eligible_panel_ids'],['P002']);self.assertEqual(result['blocked_panel_ids'],['P001'])

    def test_unscoped_or_bad_scoped_hold_fails_closed(self):
        state=self.state()
        for hold in ['old hold',{'scope':'panels','panel_ids':['P001']},{'scope':'book','evidence':'shared style'}]:
            state['holds']=[hold];self.assertEqual(self.route(state)['next_action'],'RESOLVE_HOLD')
        state['holds']=[{'scope':'panels','panel_ids':['P099'],'evidence':'invalid scope'}]
        self.assertEqual(self.route(state)['next_action'],'SCOPED_HOLD')

    def test_dependency_inherits_scoped_hold(self):
        state=self.state();self.h.h.shots[1]['generation_dependencies']=['P001'];self.freeze(state,self.h.plan['batches'][0])
        state['holds']=[{'scope':'panels','panel_ids':['P001'],'evidence':'SYNTHETIC affects predecessor'}]
        self.assertEqual(self.route(state)['next_action'],'SCOPED_HOLD')


    def test_user_required_state_at_half_end_cannot_be_bypassed_by_C(self):
        state=self.state();self.h.h.shots[1]['visual_state_keys']=['costume:NEW'];self.h.h.shots[2]['visual_state_keys']=['costume:NEW'];self.freeze(state,self.h.plan['batches'][0]);self.freeze(state,self.h.plan['batches'][1])
        self.record(state,0);self.record(state,1);view=half_view(state,'H001');self.h.review(view);self.h.continuity(view)
        state['gates']['pilot']=self.h.h.approve([view['visual_basis'],view['shot_manifest'],*[r['output'] for r in state['panels'][:2]]])
        result=self.route(state);self.assertEqual(result['next_action'],'SCOPED_HOLD');self.assertIn('P002',result['blocked_panel_ids'])

    def test_source_plan_does_not_require_second_half_input(self):
        state=self.state();state['half_inputs'].pop('H002');state['half_gates'].pop('H002')
        self.assertEqual(self.route(state)['eligible_panel_ids'],['P001','P002'])

    def test_new_state_only_waits_its_followers_not_other_scene(self):
        state=self.state(6)
        self.h.h.shots[1]['visual_state_keys']=['costume:B'];self.h.h.shots[2]['visual_state_keys']=['style:UNIT:v1']
        self.freeze(state,self.h.plan['batches'][0])
        self.record(state,1)
        result=self.route(state);self.assertEqual(result['eligible_panel_ids'],['P001','P003'])

    def test_B_approved_state_merge_uses_self_qa_before_followers(self):
        state=self.state(6)
        self.h.h.shots[1].update(visual_state_keys=['costume:B'],state_review_policy='merge_into_C')
        self.h.h.shots[2]['visual_state_keys']=['costume:B'];self.freeze(state,self.h.plan['batches'][0])
        self.assertEqual(self.route(state)['eligible_panel_ids'],['P001','P002'])
        self.record(state,1)
        self.assertEqual(self.route(state)['eligible_panel_ids'],['P001','P003'])

    def test_explicit_high_risk_state_cannot_merge_into_C(self):
        state=self.state();self.h.h.shots[0].update(requires_state_review=True,state_review_policy='merge_into_C')
        self.freeze(state,self.h.plan['batches'][0])
        result=self.route(state);self.assertEqual(result['status'],'HOLD')
        self.assertIn('明确高风险实图停点',str(result['errors']))

    def test_unknown_optimization_policy_does_not_silently_downgrade(self):
        state=self.state();state['optimization_policy']='unknown'
        self.assertEqual(self.route(state)['next_action'],'OPTIMIZATION_POLICY_HOLD')

    def test_approval_index_reuses_literal_original_proof(self):
        state=self.state();gate=state['half_gates']['H001'].pop('shot_design')
        proof=self.h.h.f.write('original-B-approval.json',gate)
        state['approval_index']=self.h.h.f.write('approvals.json',{'policy':'approval_index_v1','entries':[{'phase':'shot_design','book_id':'UNIT','episode_ids':['E000'],'panel_ids':['P001','P002'],'approval':proof}]})
        self.assertEqual(self.route(state)['eligible_panel_ids'],['P001','P002'])
        original=json.loads((self.root/'original-B-approval.json').read_text(encoding='utf-8-sig'));self.assertEqual(original,gate)

    def test_index_metadata_cannot_expand_original_panel_scope(self):
        state=self.state();gate=state['half_gates']['H001'].pop('shot_design');gate['panel_ids']=['P001'];proof=self.h.h.f.write('limited.json',gate)
        state['approval_index']=self.h.h.f.write('approvals.json',{'policy':'approval_index_v1','entries':[{'phase':'shot_design','book_id':'UNIT','episode_ids':['E000'],'panel_ids':['P001','P002'],'approval':proof}]})
        self.assertEqual(self.route(state)['next_action'],'WAIT_HALF_SHOT_APPROVAL')

    def test_second_half_update_does_not_invalidate_first_half_C(self):
        state=self.state();self.record(state,0);self.record(state,1);view=half_view(state,'H001')
        self.h.review(view);self.h.continuity(view)
        state['gates']['pilot']=self.h.h.approve([view['visual_basis'],view['shot_manifest'],*[r['output'] for r in state['panels'][:2]]])
        before=copy.deepcopy(state['half_gates']['H001']);self.h.h.shots[2]['framing']={'later_new_camera':'SYNTHETIC'};self.freeze(state,self.h.plan['batches'][1])
        self.assertEqual(self.route(state)['batch_id'],'H002');self.assertEqual(state['half_gates']['H001'],before)

    def test_unprepared_second_half_waits_after_actual_first_half_C(self):
        state=self.state();self.record(state,0);self.record(state,1);view=half_view(state,'H001');self.h.review(view);self.h.continuity(view)
        self.assertEqual(self.route(state)['next_action'],'WAIT_FIRST_HALF_APPROVAL')
        state['gates']['pilot']=self.h.h.approve([view['visual_basis'],view['shot_manifest'],*[r['output'] for r in state['panels'][:2]]])
        state['half_inputs'].pop('H002');self.assertEqual(self.route(state)['next_action'],'WAIT_HALF_INPUT')

class ReuseTests(unittest.TestCase):
    def setUp(self):
        self.h=fixtures.ActualHalfGateTests('test_real_qa_round_report_and_first_half_approval');self.h.setUp();self.addCleanup(self.h.doCleanups);self.root=self.h.root;self.r=self.h.returned()

    def test_actual_qa_is_validated_once_then_reused_within_gate(self):
        with session(True) as memo:
            self.assertEqual(qa_errors(self.root,self.r),[]);self.assertEqual(qa_errors(self.root,self.r),[])
            self.assertEqual(memo['misses'],1);self.assertEqual(memo['hits'],1)

    def test_inspection_display_pass_cannot_override_original_style_fail(self):
        qa=json.loads((self.root/self.r['qa_report']['path']).read_text(encoding='utf-8-sig'));item=qa['panels'][0]
        item['inspection_plan']={'policy':'single_observation_v1','status':'PASS','groups':[]}
        item['style_review']['status']='FAIL';self.r['qa_report']=self.h.h.f.write('native-fail-plan-pass.json',qa)
        self.assertTrue(qa_errors(self.root,self.r))

    def test_cached_qa_invalidates_when_selected_rule_changes(self):
        source=config_fixtures.library(self.root/'library');path=self.root/self.r['package_manifest']['path'];packet=json.loads(path.read_text(encoding='utf-8-sig'));panel=packet['panels'][0]
        # Empty actual conditions leave the synthetic bed rule unselected.
        packet['memory_source']=source;panel['memory_tags']=[];panel['locked_script']['event_text']='SYNTHETIC neutral frame'
        self.r['package_manifest']=self.h.h.f.write('neutral-memory-packet.json',packet)
        from codex_reference_contract import digest
        qa=json.loads((self.root/self.r['qa_report']['path']).read_text(encoding='utf-8-sig'));qa['source_manifest_sha256']=self.r['package_manifest']['sha256'];self.r['qa_report']=self.h.h.f.write('neutral-memory-qa.json',qa)
        # Fingerprint routing is the behavior under test; no image verdict is fabricated.
        before=fingerprint(self.root,self.r)
        index_path=self.root/'library/记忆索引.json';index=json.loads(index_path.read_text(encoding='utf-8-sig'));index['rules'][0]['trigger']['any_tags']=['all_test_frames'];index['rules'][0]['trigger']['any_visual_terms']=['SYNTHETIC'];index['rules'][0]['version']='2';index_path.write_text(json.dumps(index), encoding='utf-8', newline='\n')
        self.assertNotEqual(before,fingerprint(self.root,self.r))

    def test_output_tamper_invalidates_memo(self):
        with session(True):
            self.assertEqual(qa_errors(self.root,self.r),[])
            (self.root/'synthetic-output.png').write_bytes(b'changed')
            with self.assertRaises(ValueError):qa_errors(self.root,self.r)

    def test_new_QA_version_does_not_reuse_old_pass(self):
        with session(True) as memo:
            self.assertEqual(qa_errors(self.root,self.r),[])
            qa=json.loads((self.root/'qa.json').read_text(encoding='utf-8-sig'));qa['panels'][0]['style_review']['status']='UNREVIEWED';self.r['qa_report']=self.h.h.f.write('qa-new.json',qa)
            self.assertTrue(qa_errors(self.root,self.r));self.assertEqual(memo['hits'],0)

    def test_actual_prompt_file_change_invalidates_memo(self):
        manifest=json.loads((self.root/self.r['package_manifest']['path']).read_text(encoding='utf-8-sig'))
        panel=manifest['panels'][0];prompt=self.root/panel.get('prompt_file',f"{panel['panel_id']}/prompt.txt")
        with session(True) as memo:
            self.assertEqual(qa_errors(self.root,self.r),[])
            prompt.write_text('changed actual prompt',encoding='utf-8', newline='\n')
            self.assertTrue(qa_errors(self.root,self.r));self.assertEqual(memo['hits'],0)

    def test_shot_snapshot_package_relative_refs_do_not_disable_reuse(self):
        self.r['shot_subset']=self.h.h.f.write('nested-shot-snapshot.json',{'panels':[{'reference_images':[{'path':'package-relative/ref.png','sha256':'0'*64}]}]})
        with session(True) as memo:
            self.assertEqual(qa_errors(self.root,self.r),[]);self.assertEqual(qa_errors(self.root,self.r),[])
            self.assertEqual(memo['hits'],1)

    def test_review_queue_appears_before_other_images_return(self):
        state=self.h.state;self.r['status']='GENERATED';state['panels'].append({'panel_id':'P002','status':'IN_FLIGHT'})
        queue=build_queue(state,self.root,{'batch_id':'H001','panel_ids':['P001','P002']})
        self.assertEqual(len(queue['items']),1);self.assertEqual(queue['items'][0]['action'],'REVIEW_SIX_DIMENSIONS');self.assertEqual(queue['user_approval'],'NOT_GRANTED')

    def test_real_scoped_single_panel_preflight_preserves_full_gates(self):
        state=self.h.state;self.h.panel['generation_execution']['status']='NOT_RUN'
        self.h.h.manifest['optimization_policy']=POLICY;self.h.sync()
        state.update(optimization_policy=POLICY,half_inputs={},half_gates={})
        original=json.loads((self.root/'shots.json').read_text(encoding='utf-8-sig'));original['optimization_policy']=POLICY;shot=self.h.h.f.write('scoped-shot.json',original)
        state['half_inputs']={'H001':{'visual_basis':state['visual_basis'],'shot_manifest':shot}};state['half_gates']={'H001':{'visual_basis':self.h.h.approve([state['source_script'],state['source_snapshot'],state['visual_basis']]),'shot_design':self.h.h.approve([state['visual_basis'],shot])}}
        source=json.loads((self.root/'snapshot.json').read_text(encoding='utf-8-sig'));state['batch_plan']=self.h.h.f.write('scoped-plan.json',build_plan(state,source));self.r['status']='PENDING'
        result=evaluate(state,self.root,'generate','P001');self.assertEqual(result['status'],'PASS',result)
        self.h.h.manifest.pop('optimization_policy');self.r['package_manifest']=self.h.h.f.write('全话提示词索引.json',self.h.h.manifest)
        self.assertEqual(evaluate(state,self.root,'generate','P001')['status'],'HOLD')

class ScopedConfigTests(unittest.TestCase):
    def setUp(self):
        self.h=config_fixtures.ConfigTests('test_init_binds_sources_without_approving_or_overwriting');self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.h.config['generation']={'execution_mode':'half_episode_async_v1','batch_strategy':'half_episode','episode_workers':5,'max_inflight_per_episode':'half_episode','max_inflight_images':'auto'}
        self.h.config['review']={'systemic_failure_count_gt':5,'max_auto_correction_rounds':1}

    def initialize(self,name):
        self.h.save();out=self.h.root/name
        result=subprocess.run([sys.executable, '-X', 'utf8',str(Path(__file__).resolve().parents[1]/'scripts/init_preproduction.py'),'--config',str(self.h.path),'--output',str(out),'--book','UNIT','--episode','E001'],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        return out,json.loads((out/'00_输入审计/生产流程.json').read_text(encoding='utf-8-sig'))

    def test_opted_new_scaffold_has_scoped_inputs_but_no_approvals(self):
        self.h.config['optimization']={'policy':POLICY,'approval_scope':'half_episode','review_strategy':'on_return','unchanged_qa':'reuse_recorded'}
        out,state=self.initialize('new-scoped')
        self.assertEqual(state['optimization_policy'],POLICY);self.assertEqual(state['half_inputs'],{});self.assertEqual(state['half_gates'],{});self.assertEqual(state['gates'],{})
        index=json.loads((out/state['approval_index']['path']).read_text(encoding='utf-8-sig'));self.assertEqual(index['entries'],[])

    def test_episode_preparation_scaffold_has_one_basis_and_no_half_inputs(self):
        self.h.config['preparation']={'policy':'episode_preparation_v1'}
        self.h.config['optimization']={'policy':POLICY,'approval_scope':'generation_half_only','review_strategy':'on_return','unchanged_qa':'reuse_recorded'}
        self.h.config['execution']={'contract':'comic_execution_v2','request_log':'structured','semantic_audit':'before_freeze','id_mapping':'source_preserving'}
        out,state=self.initialize('new-episode-preparation')
        self.assertEqual(state['preparation_policy'],'episode_preparation_v1')
        self.assertNotIn('half_inputs',state)
        self.assertNotIn('half_gates',state)
        self.assertIsNone(state['semantic_audit'])
        self.assertEqual(state['generation_packages'],{})
        self.assertEqual(state['gates'],{})
        self.assertNotIn('readiness_policy',state)

    def test_readiness_scaffold_is_explicit_and_does_not_grant_approvals(self):
        self.h.config['preparation']={'policy':'episode_preparation_v1'}
        self.h.config['readiness']={'policy':'panel_readiness_v1'}
        self.h.config['optimization']={'policy':POLICY,'approval_scope':'generation_half_only','review_strategy':'on_return','unchanged_qa':'reuse_recorded'}
        self.h.config['execution']={'contract':'comic_execution_v2','request_log':'structured','semantic_audit':'before_freeze','id_mapping':'source_preserving'}
        out,state=self.initialize('new-readiness')
        self.assertEqual(state['readiness_policy'],'panel_readiness_v1');self.assertEqual(state['gates'],{});self.assertEqual(state['generation_packages'],{})
        for value in ([],{'policy':'unknown'}):
            self.h.config['readiness']=value;self.h.save()
            with self.assertRaises(ValueError):read_config(self.h.path)

    def test_old_half_config_does_not_silently_enable_optimization(self):
        _,state=self.initialize('old-half');self.assertNotIn('optimization_policy',state);self.assertNotIn('approval_index',state)

    def test_malformed_or_unknown_optimization_fails_closed(self):
        for value in ([],{'policy':'unknown'}):
            self.h.config['optimization']=value;self.h.save()
            with self.assertRaises(ValueError):read_config(self.h.path)

if __name__=='__main__':unittest.main()
