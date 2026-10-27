"""Bounded scheduling with real active clock/QA evidence, synthetic images only."""
import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import test_light_review as light_fixture
import runtime_clock
from stage_deadlines import POLICY,checkpoint,CompileSliceExpired
from codex_reference_contract import read_json,digest

class StageDeadlineTests(unittest.TestCase):
    def fixture(self):
        f=light_fixture.LightReviewTests();self.addCleanup(f.doCleanups)
        h,path,row,p=f.fixture();state=read_json(path);state['speed_policy']=POLICY
        state.pop('runtime_execution_context',None);path.write_text(json.dumps(state))
        self.now=0
        def instant():return {'wall':1000+self.now,'mono':100+self.now,'host':'SYNTHETIC','boot':'SYNTHETIC'}
        patcher=patch.object(runtime_clock,'instant',side_effect=instant);patcher.start();self.addCleanup(patcher.stop)
        self.clock=h.root/'00_任务协调'
        runtime_clock.initialize(self.clock,'production',14400,hard_deadline=True)
        runtime_clock.event(self.clock,'start','start')
        return h,path,row,p

    def test_pause_excluded_and_reentry_never_resets_budget(self):
        h,path,row,p=self.fixture();checkpoint(path,'review','P001')
        self.now=10;runtime_clock.event(self.clock,'pause','pause')
        self.now=1010;runtime_clock.event(self.clock,'resume','resume')
        self.now=1020;mark=checkpoint(path,'review','P001')
        self.assertEqual(mark['active_elapsed_seconds'],20);self.assertFalse(mark['degraded'])
        self.now=1030;self.assertTrue(checkpoint(path,'review','P001')['degraded'])
        before=(path.parent/'stage-runtime.json').read_bytes()
        checkpoint(path,'review','P001');self.assertEqual(before,(path.parent/'stage-runtime.json').read_bytes())

    def test_remaining_half_hour_defers_repair_but_keeps_generation(self):
        h,path,row,p=self.fixture();self.now=12600
        self.assertTrue(checkpoint(path,'repair','P001')['degraded'])
        self.assertTrue(runtime_clock.require_dispatch(path)['new_calls_allowed'])

    def test_old_run_stays_unchanged(self):
        h,path,row,p=self.fixture();state=read_json(path);state.pop('speed_policy');path.write_text(json.dumps(state))
        self.assertIsNone(checkpoint(path,'review','P001'))
        self.assertFalse((path.parent/'stage-runtime.json').exists())

    def test_clock_origin_change_rejected(self):
        h,path,row,p=self.fixture();checkpoint(path,'review','P001')
        value=read_json(self.clock/'runtime-clock.json');value['created']['wall']+=1
        (self.clock/'runtime-clock.json').write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'ORIGIN_CHANGED'):checkpoint(path,'review','P001')

    def test_optional_work_skipped_not_held_and_required_work_not_skipped(self):
        h,path,row,p=self.fixture();self.now=601
        from workflow_session import WorkflowSession
        result=WorkflowSession().execute({'action':'expensive_optional_layout','state':str(path),'optional':True})
        self.assertEqual(result['status'],'OPTIONAL_WORK_SKIPPED');self.assertEqual(result['image_calls'],0)
        with self.assertRaisesRegex(ValueError,'unsupported workflow action'):
            WorkflowSession().execute({'action':'expensive_optional_layout','state':str(path)})

    def test_direct_optional_atlas_is_skipped_before_rendering(self):
        h,path,row,p=self.fixture();self.now=601
        import production_runtime,io
        from contextlib import redirect_stdout
        output=io.StringIO()
        with patch.object(sys,'argv',['production_runtime.py','--state',str(path),'--action','draft-atlas','--optional']),redirect_stdout(output):
            self.assertEqual(production_runtime.main(),0)
        self.assertEqual(json.loads(output.getvalue())['status'],'OPTIONAL_WORK_SKIPPED')

    def test_formal_entry_defaults_active_and_wall_requires_selection(self):
        import comic_start,io
        import inspect
        for entry in (comic_start.start_clock,comic_start.prepare,comic_start.receive):
            self.assertIs(inspect.signature(entry).parameters['wall_delivery'].default,False)
        from contextlib import redirect_stdout
        for extra,expected in (([],False),(['--clock-mode','wall'],True)):
            with self.subTest(wall=expected),patch.object(sys,'argv',['comic_start.py','prepare','--project','SYNTHETIC','--book','TEST','--episodes','E001',*extra]),patch('runtime_clock_context.resolve',return_value={'session_id':'SYNTHETIC'}),patch.object(comic_start,'prepare',return_value={'status':'INITIALIZED_NOT_PRODUCTION_APPROVAL'}) as prepare,redirect_stdout(io.StringIO()):
                self.assertEqual(comic_start.main(),0)
                self.assertEqual(prepare.call_args.kwargs['wall_delivery'],expected)
                self.assertEqual(prepare.call_args.kwargs['image_review_profile'],'light_story_review_v1')

    def test_no_real_pilot_repair_is_required_in_speed_mode(self):
        h,path,row,p=self.fixture()
        from workflow_session import WorkflowSession
        self.assertEqual(WorkflowSession().execute({'action':'pilot-check','state':str(path)})['status'],'OPTIONAL_WORK_SKIPPED')

    def test_compile_after_deadline_returns_explicit_remaining_scope(self):
        h,path,row,p=self.fixture();state=read_json(path)
        state['panels']=[{'panel_id':f'P{i:03d}','status':'PENDING'} for i in range(1,12)]
        checkpoint(path,'compile',state=state);self.now=91
        import production_runtime
        with patch.object(production_runtime,'_compile_jobs',return_value={'jobs':[],'preflight':{}}) as inner:
            result=production_runtime.compile_jobs(state,h.root)
        self.assertEqual(inner.call_args.args[2],[f'P{i:03d}' for i in range(1,6)])
        self.assertEqual(result['next_compile_panel_ids'],[f'P{i:03d}' for i in range(6,12)])
        self.assertFalse(result['compile_scope_complete'])

    def test_cooperative_compile_timeout_selects_fallback(self):
        h,path,row,p=self.fixture();state=read_json(path)
        import production_runtime
        with patch.object(production_runtime,'_compile_jobs',side_effect=[CompileSliceExpired('expired'),{'jobs':[],'preflight':{}}]) as inner:
            result=production_runtime.compile_jobs(state,h.root)
        self.assertEqual(inner.call_count,2);self.assertIn('compile_scope_complete',result)

    def test_review_timeout_saves_single_real_observation_without_contact_sheet(self):
        h,path,row,p=self.fixture()
        from production_runtime import prepare_review
        queue=prepare_review(read_json(path),h.root,{'items':[{'panel_id':row['panel_id'],'action':'REVIEW_STORY_ONCE'}]})
        self.assertNotIn('contact_sheet',queue);self.now=31
        p['light_observations']={'single_observation':'SYNTHETIC identity and action are readable','issues':[]}
        from review_pipeline import save
        save(path,digest(path),p);state=read_json(path);qa=read_json(h.root/state['panels'][0]['qa_report']['path'])
        self.assertEqual(qa['panels'][0]['light_review']['review_effort'],'deadline_single_observation')
        self.assertNotIn('checks',qa['panels'][0]['light_review'])

    def test_expired_serious_review_adopts_original_with_truthful_major_issue(self):
        h,path,row,p=self.fixture();checkpoint(path,'repair','P001');self.now=481
        p['verdict']='FAIL';p['light_observations']['checks']['story_readability']['status']='FAIL'
        p['light_observations']['issues']=[{'location':'action','problem':'wrong target','target':'correct target','story_critical':True}]
        from review_pipeline import save
        save(path,digest(path),p);state=read_json(path);new=state['panels'][0]
        self.assertEqual(new['attempt_id'],row['attempt_id']);self.assertEqual(new['round_id'],1)
        self.assertEqual(new['status'],'VISUAL_FAIL');self.assertEqual(new['output'],row['output'])
        from production_decisions import selected
        self.assertEqual(selected(h.root,new)[1]['action'],'defer_manual')
        from panel_delivery import build
        self.assertEqual(build(state,h.root)['panels'][0]['outcome'],'MANUAL_PRIORITY')

    def test_expired_authorization_defers_without_opening_second_attempt(self):
        h,path,row,p=self.fixture();checkpoint(path,'repair','P001')
        p['verdict']='FAIL';issue={'location':'action','problem':'wrong target','target':'correct target','story_critical':True}
        p['light_observations']['checks']['story_readability']['status']='FAIL';p['light_observations']['issues']=[issue]
        p['adopt']=False
        p['decision']={'action':'local_edit','reason':'SYNTHETIC serious story error','issues':[{**issue,'id':'I1','category':1,'kind':'story','certainty':'confirmed','basis':'actual observed story','handling':'repair','observations':['/light_review/issues/0']}],
            'fix_now':['I1'],'opportunistic':[],'manual':[],'method_key':'local-action','cause_key':'target','preserve_constraints':['keep identity']}
        from review_pipeline import save
        save(path,digest(path),p);old=read_json(path)['panels'][0]['qa_report']
        h.h.f.write('planned-repair.json',{'panel_id':'P001'})
        self.now=481
        from production_runtime import authorize_episode_repair
        result=authorize_episode_repair(path,digest(path),'planned-repair.json')
        new=read_json(path)['panels'][0]
        self.assertEqual(result['status'],'REPAIR_DEFERRED_TO_DELIVERY')
        self.assertFalse(result['new_attempt_created']);self.assertEqual(new['attempt_id'],row['attempt_id'])
        self.assertEqual(new['qa_revisions'][-1]['qa_report'],old)

    def test_complete_light_package_after_pack_timeout_preserves_all_images(self):
        import test_delivery_publish as delivery_fixture
        import stage_deadlines, delivery_publish, delivery_contract, zipfile, hashlib
        from light_review import template, FIELD, POLICY as LIGHT_POLICY
        from review_pipeline import save
        from panel_delivery import build
        h,state,path=delivery_fixture.complete_fixture(self)
        state.update(speed_policy=POLICY,image_review_profile=LIGHT_POLICY,runtime_pipeline_policy='observed_incremental_pipeline_v1')
        state.pop('runtime_execution_context',None);state.pop('delivery_review',None);state.pop('batch_reviews',None)
        templates={};images={r['output']['sha256'] for r in state['panels']}
        for row in state['panels']:
            row['status']='GENERATED'
            for key in ('qa_report','production_decisions','adoption','failure_diagnosis'):row.pop(key,None)
            templates[row['panel_id']]=h.h.f.write(row['panel_id']+'-light.json',{
                FIELD:LIGHT_POLICY,'source_manifest_sha256':row['package_manifest']['sha256'],'panels':[template(row)]})
        path.write_text(json.dumps(state));now=[0]
        def instant():return {'wall':1000+now[0],'mono':100+now[0],'host':'SYNTHETIC','boot':'SYNTHETIC'}
        with patch.object(runtime_clock,'instant',side_effect=instant):
            clock=h.root/'00_任务协调';runtime_clock.initialize(clock,'production',14400,hard_deadline=True);runtime_clock.event(clock,'start','start')
            for row in state['panels']:
                save(path,digest(path),{'panel_id':row['panel_id'],'attempt_id':row['attempt_id'],'base_qa':None,
                    'qa_template':templates[row['panel_id']],'reviewer':'SYNTHETIC','reason':'Synthetic single-image observation',
                    'verdict':'PASS','adopt':True,'light_observations':{'single_observation':'SYNTHETIC actor and action readable','issues':[]}})
            state=read_json(path);review=build(state,h.root);self.assertTrue(review['handoff_complete'])
            ref=h.h.f.write('light-delivery-review.json',review);state['delivery_review']=ref
            state['gates']['final']={**h.h.approve([*review['artifacts'],ref]),'panel_ids':review['panel_ids']}
            path.write_text(json.dumps(state))
            task=h.root.parent.parent/'light-delivery-task';identity=delivery_contract.initialize(task,'production',[path])
            real=stage_deadlines.checkpoint
            def tick(*args,**kwargs):
                result=real(*args,**kwargs)
                if args[1]=='pack':now[0]=31
                return result
            with patch.object(stage_deadlines,'checkpoint',side_effect=tick):
                report=delivery_publish.publish_production(identity['path'],task/'out')
            self.assertEqual(report['status'],'DELIVERY_READY');self.assertEqual(report['image_calls'],0)
            with zipfile.ZipFile(report['artifacts'][0]['path']) as z:
                delivered={hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if '/图片/' in n}
                self.assertEqual(delivered,images)
                self.assertTrue(all(i.compress_type==zipfile.ZIP_STORED for i in z.infolist()))

    def test_first_round_is_prioritized_over_repairs(self):
        from production_decisions import priority
        state={'speed_policy':POLICY,'image_review_profile':'light_story_review_v1'}
        self.assertLess(priority(state,{'status':'PENDING'},[],None),priority(state,{'status':'REPAIR_AUTHORIZED'},[],None))

if __name__=='__main__':unittest.main()
