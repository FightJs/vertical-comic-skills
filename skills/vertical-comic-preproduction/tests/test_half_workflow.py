"""Half-window scheduling, correction boundaries and full image evidence in temporary fixtures."""
import _historical_fixture
import copy
import json
from pathlib import Path
import sys
import subprocess
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import test_staged_workflow as staged
from historical_engines.half_workflow import build_plan
from historical_engines.batch_round import MODE, snapshot, template, decision, report_errors
from _historical_fixture import evaluate
from codex_reference_contract import digest, validate_panel
from usage_config import runtime_limits
SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
REVIEW={'systemic_failure_count_gt':5,'max_auto_correction_rounds':1}


class HalfTests(unittest.TestCase):
    def setUp(self):
        self.h=staged.StagedTests('test_actual_style_input_is_exported'); self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.root=self.h.root

    def state(self,n=30):
        state=self.h.state(n); state.update(execution_mode=MODE,review_policy=REVIEW,round_reviews={},batch_reviews={})
        for p in self.h.shots: p.update(generation_dependencies=[],requires_state_review=False)
        self.replan(state)
        return state

    def replan(self,state):
        state['shot_manifest']=self.h.f.write('shots.json',{'execution_mode':MODE,'panels':self.h.shots})
        state['gates']['shot_design']=self.h.approve([state['visual_basis'],state['shot_manifest']])
        self.plan=build_plan(state,{'panels':self.h.shots}); state['batch_plan']=self.h.f.write('plan.json',self.plan)

    def route(self,state,check='status',pid=None):
        # Routing fixtures isolate scheduling; the full-gate suite below uses actual QA.
        with patch('historical_engines.batch_workflow.completed_errors',return_value=[]),patch('historical_engines.batch_workflow.input_errors',return_value=[]),patch('historical_engines.batch_round.attempt_errors',return_value=[]):
            return evaluate(state,self.root,check,pid)

    def record(self,state,index,status='VISUAL_PASS',round_id=1):
        r=state['panels'][index]; pid=r['panel_id']; batch='H001' if index<len(self.plan['pilot_panel_ids']) else 'H002'
        r.update(status=status,attempt_id=f'{pid}-R{round_id}',round_id=round_id)
        r['package_manifest']=self.h.f.write(f'{pid}-r{round_id}-packet.json',{'execution_mode':MODE,'round_context':{'batch_id':batch,'round_id':round_id,'attempt_id':r['attempt_id']},'panels':[{'prompt':'fix target','operation':'repair' if round_id==2 else 'generate'}]})
        r['qa_report']=self.h.f.write(f'{pid}-r{round_id}-qa.json',{'SYNTHETIC':True})
        r['output']=self.h.f.write(f'{pid}-r{round_id}-output.json',{'SYNTHETIC':round_id})
        return r

    def review(self,state,bidx=0,round_id=1):
        batch=self.plan['batches'][bidx]; report=template(state,batch,{r['panel_id']:r for r in state['panels']},round_id)
        report.update(status='REVIEWED',reviewer='SYNTHETIC',evidence='SYNTHETIC test only')
        if report['repair_panel_ids']:
            report['diagnosis']={'reviewer':'SYNTHETIC','evidence':'TEST ONLY','earliest_layer':'output','requires_basis_change':False,
                'repair_constraints':{p:['fix target'] for p in report['repair_panel_ids']},'common_cause_analysis':'TEST reference/style/state/space/prompt reviewed'}
        state['round_reviews'].setdefault(batch['batch_id'],{})[str(round_id)]=self.h.f.write(f'{batch["batch_id"]}-round{round_id}.json',report)
        return report

    def continuity(self,state,bidx=0):
        batch=self.plan['batches'][bidx]; by={r['panel_id']:r for r in state['panels']}; prior=self.plan['batches'][bidx-1]['panel_ids'] if bidx else []
        report={'policy':'batch_review_v1','book_id':'UNIT','episode_id':'E000',**batch,'status':'PASS','reviewer':'SYNTHETIC','evidence':'TEST ONLY',
            'visual_basis':state['visual_basis'],'shot_manifest':state['shot_manifest'],'outputs':[by[p]['output'] for p in batch['panel_ids']], 'previous_outputs':[by[p]['output'] for p in prior]}
        state['batch_reviews'][batch['batch_id']]=self.h.f.write(f'{batch["batch_id"]}-continuity.json',report)

    def test_real_count_splits_30_35_28_and_single_panel(self):
        for n,lengths in [(30,[15,15]),(35,[18,17]),(28,[14,14]),(1,[1])]:
            self.state(n); self.assertEqual([len(b['panel_ids']) for b in self.plan['batches']],lengths)

    def test_all_fifteen_independent_pending_panels_are_eligible(self):
        result=self.route(self.state()); self.assertEqual(len(result['eligible_panel_ids']),15)

    def test_active_request_does_not_block_independent_siblings(self):
        state=self.state(); state['panels'][0]['status']='IN_FLIGHT'
        self.assertEqual(self.route(state)['eligible_panel_ids'],[f'P{i:03d}' for i in range(2,16)])

    def test_no_early_second_half_submission(self):
        self.assertEqual(self.route(self.state(),'generate','P016')['next_action'],'SOURCE_HALF_HOLD')

    def test_partial_first_five_approval_cannot_release_second_half(self):
        state=self.state()
        for i in range(15): self.record(state,i)
        self.review(state); self.continuity(state)
        state['gates']['pilot']=self.h.approve([state['visual_basis'],state['shot_manifest'],*[r['output'] for r in state['panels'][:5]]])
        self.assertEqual(self.route(state,'generate','P016')['next_action'],'WAIT_FIRST_HALF_APPROVAL')
        state['gates']['pilot']=self.h.approve([state['visual_basis'],state['shot_manifest'],*[r['output'] for r in state['panels'][:15]]])
        self.assertEqual(self.route(state)['batch_id'],'H002')

    def test_new_state_barrier_does_not_change_half_boundary(self):
        state=self.state(); self.h.shots[3]['requires_state_review']=True; self.replan(state)
        self.assertEqual(len(self.plan['batches'][0]['panel_ids']),15)
        self.assertEqual(self.route(state)['eligible_panel_ids'],['P001','P002','P003','P004'])
        self.record(state,3)
        self.assertEqual(self.route(state)['next_action'],'WAIT_NEW_STATE_APPROVAL')

    def test_failed_dependency_has_explicit_hold_instead_of_impossible_report(self):
        state=self.state(4); self.h.shots[1]['generation_dependencies']=['P001']; self.replan(state); self.record(state,0,'VISUAL_FAIL')
        self.assertEqual(self.route(state)['next_action'],'DEPENDENCY_FAILURE_HOLD')


    def test_failed_new_state_barrier_has_explicit_diagnostic_hold(self):
        state=self.state(4);self.h.shots[0]['requires_state_review']=True;self.replan(state)
        self.record(state,0,'VISUAL_FAIL')
        self.assertEqual(self.route(state)['next_action'],'STATE_FAILURE_HOLD')

    def test_repair_cannot_masquerade_as_first_round(self):
        state=self.state(2); self.record(state,0,'REPAIR_AUTHORIZED',1)
        self.assertEqual(self.route(state,'generate','P001')['next_action'],'ROUND_HOLD')

    def test_failure_threshold_is_distinct_image_count(self):
        for count,expected in [(0,'ALL_PASS'),(5,'LOCAL_REPAIR'),(6,'SYSTEMIC_REPAIR')]:
            attempts=[{'panel_id':f'P{i:03d}','status':'VISUAL_FAIL' if i<count else 'VISUAL_PASS'} for i in range(15)]
            self.assertEqual(decision(attempts,1)['strategy'],expected)
        self.assertEqual(decision([{'panel_id':'P001','status':'CALL_FAILED'}],1)['strategy'],'CALL_HOLD')
        self.assertEqual(decision([{'panel_id':'P001','status':'VISUAL_FAIL'}],2)['strategy'],'STOP_DIAGNOSE')

    def test_second_round_uses_failed_scope_and_retains_successes(self):
        state=self.state(4)
        old=self.record(state,0,'VISUAL_FAIL'); self.record(state,1)
        self.review(state)
        self.assertEqual(self.route(state)['next_action'],'PREPARE_CORRECTION')
        original=snapshot(old); self.record(state,0,'REPAIR_AUTHORIZED',2)['attempt_history']=[original]
        self.assertEqual(self.route(state,'generate','P001')['status'],'PASS')
        self.record(state,1,'REPAIR_AUTHORIZED',2)
        self.assertEqual(self.route(state)['next_action'],'ROUND_HOLD')

    def test_round_two_still_failed_stops_without_third_call(self):
        state=self.state(2); r=self.record(state,0,'VISUAL_FAIL'); self.review(state); old=snapshot(r)
        self.record(state,0,'VISUAL_FAIL',2)['attempt_history']=[old]
        self.assertEqual(self.route(state)['next_action'],'STOP_DIAGNOSE')

    def test_systemic_failures_require_common_cause_diagnosis(self):
        state=self.state(14)
        for i in range(7): self.record(state,i,'VISUAL_FAIL' if i<6 else 'VISUAL_PASS')
        report=self.review(state); report['diagnosis'].pop('common_cause_analysis')
        state['round_reviews']['H001']['1']=self.h.f.write('bad-round.json',report)
        self.assertEqual(self.route(state)['next_action'],'ROUND_HOLD')

    def test_capacity_uses_actual_active_episode_and_current_half(self):
        config={'production':{'episodes':['E001','E002','E003','E004','E005']},'generation':{'execution_mode':MODE,'episode_workers':5,'max_inflight_per_episode':'half_episode','max_inflight_images':'auto'}}
        first=runtime_limits(config,6,100,{'E001':30,'E002':35,'E003':30,'E004':30,'E005':28})
        self.assertEqual(first['target_max_inflight'],77)
        second=runtime_limits(config,3,100,active_episodes=['E004','E005'],current_half_counts={'E004':15,'E005':14})
        self.assertEqual(second['target_max_inflight'],29)
        odd=runtime_limits(config,2,100,active_episodes=['E002'],current_half_counts={'E002':17})
        self.assertEqual(odd['max_inflight'],17)


class ActualHalfGateTests(unittest.TestCase):
    def setUp(self):
        self.h=staged.StagedTests('test_actual_style_input_is_exported'); self.h.setUp();self.addCleanup(self.h.doCleanups);self.root=self.h.root
        self.state=self.h.real_input();self.state.update(execution_mode=MODE,review_policy=REVIEW,round_reviews={},batch_reviews={})
        self.panel=self.h.panel;self.panel.update(generation_dependencies=[],requires_state_review=False)
        for p in self.h.shots: p.update(generation_dependencies=[],requires_state_review=False)
        self.h.manifest.update(execution_mode=MODE,round_context={'batch_id':'H001','round_id':1,'attempt_id':'UNIT-R1'})
        self.state['panels'][0].update(attempt_id='UNIT-R1',round_id=1)
        self.sync()

    def sync(self):
        self.h.f.write('P001/提示词.json',self.panel)
        shots={**self.h.manifest,'panels':self.h.shots}
        self.state['shot_manifest']=self.h.f.write('shots.json',shots); self.state['gates']['shot_design']=self.h.approve([self.state['visual_basis'],self.state['shot_manifest']])
        r=self.state['panels'][0];r['shot_subset']=self.h.f.write('subset.json',shots);r['package_manifest']=self.h.f.write('全话提示词索引.json',self.h.manifest)
        self.plan=build_plan(self.state,shots);self.state['batch_plan']=self.h.f.write('plan.json',self.plan)

    def returned(self,fail=False):
        from PIL import Image
        _,plan=validate_panel(self.panel,self.root);output=self.root/'synthetic-output.png';Image.new('RGB',(90,160),'white').save(output)
        req={'attempt_id':'UNIT-R1','backend_id':'codex_builtin_imagegen','panel_id':'P001',**plan,'source_kind':'observed_tool_call','source_locator':'synthetic://not-real'}
        res={'attempt_id':'UNIT-R1','status':'COMPLETED','outputs':[{'path':output.name,'sha256':digest(output)}],'source_kind':'observed_tool_result','source_locator':'synthetic://not-real'}
        self.panel['generation_execution']={'status':'COMPLETED','attempt_id':'UNIT-R1','request_evidence':self.h.f.write('req.json',req),'response_evidence':self.h.f.write('res.json',res)}
        report,_=self.h.f.qa_report();item=report['panels'][0]
        for review in [*item['dimension_review'].values(),item['style_review']]: review.update(status='PASS',reviewer='SYNTHETIC',evidence='TEST ONLY')
        for key in ('camera_match','shot_scale_match','background_view_match','body_crop_match','required_visible_information_preserved','no_extra_offscreen_characters'):item[key]=True
        if fail:item['style_review']['status']='FAIL'
        r=self.state['panels'][0];r.update(status='VISUAL_FAIL' if fail else 'VISUAL_PASS',package_manifest={'path':'全话提示词索引.json','sha256':digest(self.root/'全话提示词索引.json')},output={'path':output.name,'sha256':digest(output)},qa_report=self.h.f.write('qa.json',report))
        if fail:r['failure_diagnosis']={'reviewer':'SYNTHETIC','evidence':'TEST wrong style','layer':'output'}
        return r

    def test_actual_generate_and_wrong_round_binding(self):
        self.assertEqual(evaluate(self.state,self.root,'generate','P001')['status'],'PASS')
        self.h.manifest['round_context']['attempt_id']='wrong';self.sync()
        self.assertEqual(evaluate(self.state,self.root,'generate','P001')['status'],'HOLD')

    def test_first_round_repair_blocked_with_full_preflight(self):
        self.state['panels'][0]['status']='REPAIR_AUTHORIZED';self.panel['operation']='repair';self.sync()
        self.assertEqual(evaluate(self.state,self.root,'generate','P001')['next_action'],'ROUND_HOLD')

    def test_real_qa_round_report_and_first_half_approval(self):
        r=self.returned();batch=self.plan['batches'][0];report=template(self.state,batch,{'P001':r},1)
        self.assertEqual(report['status'],'UNREVIEWED');report.update(status='REVIEWED',reviewer='SYNTHETIC',evidence='TEST ONLY')
        self.assertEqual(report_errors(self.state,self.root,batch,report,1,{'P001':r}),[])
        self.state['round_reviews']={'H001':{'1':self.h.f.write('round.json',report)}}
        self.assertEqual(evaluate(self.state,self.root)['next_action'],'REVIEW_HALF_CONTINUITY')
        cont={'policy':'batch_review_v1','book_id':'UNIT','episode_id':'E000',**batch,'status':'PASS','reviewer':'SYNTHETIC','evidence':'TEST ONLY','visual_basis':self.state['visual_basis'],'shot_manifest':self.state['shot_manifest'],'outputs':[r['output']],'previous_outputs':[]}
        self.state['batch_reviews']={'H001':self.h.f.write('continuity.json',cont)}
        self.assertEqual(evaluate(self.state,self.root)['next_action'],'WAIT_FIRST_HALF_APPROVAL')
        artifacts=[self.state['visual_basis'],self.state['shot_manifest'],r['output']];self.state['gates']['pilot']=self.h.approve(artifacts);self.state['gates']['final']=self.h.approve(artifacts)
        self.assertEqual(evaluate(self.state,self.root,'deliver')['next_action'],'READY_TO_PACKAGE')

    def test_real_failure_qa_and_hash_tamper_not_counted_as_valid(self):
        r=self.returned(True);batch=self.plan['batches'][0];report=template(self.state,batch,{'P001':r},1)
        report.update(status='REVIEWED',reviewer='SYNTHETIC',evidence='TEST ONLY',diagnosis={'reviewer':'SYNTHETIC','evidence':'TEST','earliest_layer':'output','requires_basis_change':False,'repair_constraints':{'P001':['preserve style']}})
        self.assertEqual(report_errors(self.state,self.root,batch,report,1,{'P001':r}),[])
        (self.root/'qa.json').write_text('{}', encoding='utf-8', newline='\n')
        with self.assertRaises(ValueError):report_errors(self.state,self.root,batch,report,1,{'P001':r})


    def test_failed_image_with_other_unreviewed_dimensions_cannot_finish_round(self):
        r=self.returned(True);batch=self.plan['batches'][0]
        qa=json.loads((self.root/'qa.json').read_text(encoding='utf-8-sig'));qa['panels'][0]['dimension_review']['identity']['status']='UNREVIEWED'
        r['qa_report']=self.h.f.write('qa.json',qa)
        report=template(self.state,batch,{'P001':r},1);report.update(status='REVIEWED',reviewer='SYNTHETIC',evidence='TEST',diagnosis={'reviewer':'SYNTHETIC','evidence':'TEST','earliest_layer':'output','requires_basis_change':False,'repair_constraints':{'P001':['fix']}})
        self.assertTrue(report_errors(self.state,self.root,batch,report,1,{'P001':r}))


    def test_actual_half_contact_sheet_uses_selected_current_outputs_and_no_overwrite(self):
        from historical_engines.batch_round import write_contact_sheet
        self.returned();dest=self.root/'half-review.jpg'
        result=write_contact_sheet(self.root,self.plan['batches'][0],{'P001':self.state['panels'][0]},dest)
        self.assertEqual(result['status'],'UNREVIEWED_CONTACT_SHEET_CREATED')
        self.assertTrue(dest.is_file())
        with self.assertRaises(FileExistsError):write_contact_sheet(self.root,self.plan['batches'][0],{'P001':self.state['panels'][0]},dest)

    def test_initializer_default_episode_without_approval(self):
        out=self.root/'new'
        command=[sys.executable, '-X', 'utf8',str(SCRIPTS/'init_preproduction.py'),'--output',str(out),'--book','UNIT','--episode','E000']
        result=subprocess.run(command,capture_output=True);self.assertEqual(result.returncode,0,result.stderr)
        state=json.loads((out/'00_输入审计/生产流程.json').read_text(encoding='utf-8-sig'));self.assertEqual(state['execution_mode'],'episode_async_v1');self.assertEqual(state['gates'],{})

if __name__=='__main__':unittest.main()
