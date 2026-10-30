"""Real frozen gates and synthetic no-output evidence. Never calls image services."""
import copy,json,sys,tempfile,unittest,subprocess
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
from dispatch_fixture import DispatchFixture
from codex_reference_contract import digest,read_json,checked_file
from platform_io import atomic_json
from episode_dispatch_queue import reserve_ready
from production_runtime import submit, commit_updates, package_signature
from _historical_fixture import compile_jobs
from no_image_recovery import recover,history_errors
import managed_dispatch as managed

class RecoveryTests(unittest.TestCase):
    def fixture(self, mode='NOT_INVOKED', repair=False, admitted=False):
        f=DispatchFixture(slots=2);self.addCleanup(f.close)
        if repair:f.authorize_synthetic_repair('P001')
        if admitted:
            managed.admit(f.state_path,digest(f.state_path),digest(f.control_path),old_writers_stopped=True,
                          immutable_inputs=True,saver_protocol='exclusive_evidence_v1',reason='SYNTHETIC recovery')
            managed.reserve(f.state_path,digest(f.state_path),digest(f.control_path),max_count=1,request_id='synthetic-first')
            job=managed.call(f.state_path,'compile',panel_ids=['P001'])['jobs'][0]
            managed.submit(f.state_path,job=job)
        else:
            reserve_ready(f.state_path,digest(f.state_path),digest(f.control_path),max_count=1)
            job=compile_jobs(read_json(f.state_path),f.root,['P001'])['jobs'][0];submit(f.state_path,job)
        row=read_json(f.state_path)['panels'][0]
        def write(name,value):
            path=f.root/name;atomic_json(path,value);return {'path':name,'sha256':digest(path)}
        raw=write('synthetic-error.json',{'source_kind':'observed_executor_outcome','actual_fixture_only':True})
        evidence={'book_id':f.state['book_id'],'episode_id':f.state['episode_id'],'panel_id':'P001',
                  'attempt_id':row['attempt_id'],'round_id':row['round_id'],'no_image_confirmed':True,
                  'outcome':mode,'source_kind':'observed_executor_outcome' if mode=='NOT_INVOKED' else 'observed_tool_error',
                  'source_locator':'synthetic://observed-no-output','evidence':'Fixture actual no-output event',
                  'evidence_files':[raw],'invocation_started':False if mode=='NOT_INVOKED' else True}
        auth=write('synthetic-recovery-auth.json',{'source_kind':'user_message','source_locator':'synthetic://user',
             'quote':'SYNTHETIC user authorizes no-image recovery and scoped compatibility execution',
             'book_id':f.state['book_id'],'episode_ids':[f.state['episode_id']],'panel_ids':['P001'],
             'operations':['no_image_retry','compatibility_execution']})
        if mode!='NOT_INVOKED':
            call=write('synthetic-call-failed.json',{'attempt_id':row['attempt_id'],'status':'CALL_FAILED',
                 'source_locator':'synthetic://service-error','evidence':'SYNTHETIC confirmed no image'})
            update={k:row[k] for k in ('panel_id','attempt_id','round_id')};update.update(status='CALL_FAILED',call_evidence=call)
            if admitted:managed.call(f.state_path,'commit',expected_sha256=digest(f.state_path),updates=[update])
            else:commit_updates(f.state_path,digest(f.state_path),[update])
        request={'request_id':'recover-one','panel_id':'P001','original_attempt_id':row['attempt_id'],
                 'evidence':write('synthetic-no-image.json',evidence),'authorization':auth}
        f.job=job;f.request=request;f.write=write;return f

    def test_not_invoked_and_rejected_retry_without_consuming_quality_round(self):
        for mode in ('NOT_INVOKED','REJECTED_NO_OUTPUT'):
            with self.subTest(mode=mode):
                f=self.fixture(mode);before=read_json(f.state_path);original=copy.deepcopy(before['panels'][1:])
                result=recover(f.state_path,digest(f.state_path),f.request)
                self.assertEqual(result['status'],'NO_IMAGE_RETRY_READY')
                state=read_json(f.state_path);row=state['panels'][0]
                self.assertEqual(row['round_id'],1);self.assertEqual(row.get('attempt_history',[]),[])
                self.assertEqual(len(row['no_image_history']),1);self.assertNotEqual(row['attempt_id'],f.job['attempt_id'])
                self.assertEqual(state['panels'][1:],original)
                for key in ('source_snapshot','toolchain','runtime_snapshot','gates','runtime_execution_context','production_authorization'):
                    self.assertEqual(state.get(key),before.get(key),key)
                self.assertFalse(history_errors(state,f.root,row))
                reserve_ready(f.state_path,digest(f.state_path),digest(f.control_path),max_count=1)
                newjob=compile_jobs(read_json(f.state_path),f.root,['P001'])['jobs'][0]
                self.assertEqual(newjob['arguments'],f.job['arguments'])
                self.assertTrue(submit(f.state_path,newjob)['invoke_allowed'])
                self.assertFalse(submit(f.state_path,newjob)['invoke_allowed'])
                self.assertEqual(read_json(f.state_path)['dispatch_ledger'][0]['status'],'RELEASED')

    def test_stable_id_replay_and_conflict(self):
        f=self.fixture();expected=digest(f.state_path);first=recover(f.state_path,expected,f.request);after=digest(f.state_path)
        second=recover(f.state_path,expected,f.request)
        self.assertEqual(second['status'],'NO_IMAGE_RECOVERY_ALREADY_SAVED');self.assertEqual(first['attempt_id'],second['attempt_id'])
        self.assertEqual(digest(f.state_path),after)
        changed={**f.request,'request_id':'recover-one','original_attempt_id':'different'}
        with self.assertRaisesRegex(ValueError,'REQUEST_CONFLICT'):recover(f.state_path,after,changed)

    def test_unknown_needs_actual_resolution_not_timeout(self):
        f=self.fixture();state=read_json(f.state_path);row=state['panels'][0];row['status']='RESULT_UNKNOWN';row['call_evidence']=f.write('unknown-call.json',{'attempt_id':row['attempt_id'],'status':'RESULT_UNKNOWN','source_locator':'synthetic://unknown','evidence':'synthetic uncertain outcome'});atomic_json(f.state_path,state)
        before=digest(f.state_path)
        with self.assertRaisesRegex(ValueError,'UNKNOWN_MUST_BE_RESOLVED'):recover(f.state_path,before,f.request)
        self.assertEqual(digest(f.state_path),before)
        proof=read_json(checked_file(f.root,f.request['evidence']));proof.update(outcome='RESOLVED_NO_OUTPUT',source_kind='observed_resolution',original_call_evidence=row['call_evidence'])
        f.request['evidence']=f.write('resolved.json',proof)
        self.assertEqual(recover(f.state_path,before,f.request)['status'],'NO_IMAGE_RETRY_READY')

    def test_terminal_request_builder_preserves_restrictions_and_identity(self):
        from no_image_recovery import prepare_request
        f=self.fixture();state=read_json(f.state_path)
        state['panels'][0]['prepared_registration_id']='synthetic-registration'
        atomic_json(f.state_path,state)
        terminal=read_json(checked_file(f.root,f.request['evidence']))
        terminal['registration_id']='synthetic-registration'
        terminal_ref=f.write('terminal.json',terminal)
        request=prepare_request(f.state_path,'P001',terminal_ref,f.request['authorization'])
        again=prepare_request(f.state_path,'P001',terminal_ref,f.request['authorization'])
        self.assertEqual(request,again)
        self.assertEqual(request['original_attempt_id'],state['panels'][0]['attempt_id'])
        terminal['rejection_kind']='content_policy'
        terminal_ref=f.write('restricted-terminal.json',terminal)
        with self.assertRaisesRegex(ValueError,'CONTENT_RESTRICTION'):
            prepare_request(f.state_path,'P001',terminal_ref,f.request['authorization'])
        terminal.pop('rejection_kind');terminal['no_image_confirmed']=False
        terminal_ref=f.write('unknown-terminal.json',terminal)
        with self.assertRaisesRegex(ValueError,'NO_IMAGE_NOT_PROVEN'):
            prepare_request(f.state_path,'P001',terminal_ref,f.request['authorization'])

    def test_output_or_changed_authority_never_retries(self):
        f=self.fixture();state=read_json(f.state_path);state['panels'][0]['output']={'path':'existing.png','sha256':'x'};atomic_json(f.state_path,state)
        with self.assertRaisesRegex(ValueError,'ONLY_CONFIRMED_NO_IMAGE'):recover(f.state_path,digest(f.state_path),f.request)
        state['panels'][0].pop('output');atomic_json(f.state_path,state)
        auth=read_json(checked_file(f.root,f.request['authorization']));auth['panel_ids']=['P002']
        f.request['authorization']=f.write('wrong-auth.json',auth)
        with self.assertRaisesRegex(ValueError,'AUTHORIZATION_SCOPE'):recover(f.state_path,digest(f.state_path),f.request)

    def test_second_quality_round_stays_second_after_technical_retry(self):
        f=self.fixture(repair=True);before=read_json(f.state_path);history=copy.deepcopy(before['panels'][0]['attempt_history'])
        recover(f.state_path,digest(f.state_path),f.request);state=read_json(f.state_path)
        self.assertEqual(state['panels'][0]['attempt_history'],history);self.assertEqual(state['panels'][0]['round_id'],2)
        reserve_ready(f.state_path,digest(f.state_path),digest(f.control_path),max_count=1)
        job=compile_jobs(read_json(f.state_path),f.root,['P001'])['jobs'][0]
        self.assertEqual(job['round_id'],2);self.assertEqual(job['kind'],'repair')
        self.assertTrue(submit(f.state_path,job)['invoke_allowed'])

    def test_managed_gateway_preserves_authority(self):
        f=self.fixture(admitted=True)
        with self.assertRaisesRegex(ValueError,'DISPATCH_PROTOCOL_UNSUPPORTED'):recover(f.state_path,digest(f.state_path),f.request)
        result=managed.call(f.state_path,'recover-no-image',expected_sha256=digest(f.state_path),request=f.request)
        self.assertEqual(result['status'],'NO_IMAGE_RETRY_READY')
        reserved=managed.reserve(f.state_path,digest(f.state_path),digest(f.control_path),max_count=1,request_id='synthetic-retry')
        self.assertEqual(reserved['status'],'RESERVED')
        job=managed.call(f.state_path,'compile',panel_ids=['P001'])['jobs'][0]
        self.assertTrue(managed.submit(f.state_path,job=job)['invoke_allowed'])

    def test_old_job_cannot_overwrite_new_attempt(self):
        f=self.fixture();recover(f.state_path,digest(f.state_path),f.request);before=digest(f.state_path)
        with self.assertRaises(ValueError):submit(f.state_path,f.job)
        self.assertEqual(before,digest(f.state_path))

    def test_repeated_failure_requires_new_diagnosis_after_two_retries(self):
        f=self.fixture()
        for index in range(2):
            self.assertEqual(recover(f.state_path,digest(f.state_path),f.request)['status'],'NO_IMAGE_RETRY_READY')
            reserve_ready(f.state_path,digest(f.state_path),digest(f.control_path),max_count=1)
            job=compile_jobs(read_json(f.state_path),f.root,['P001'])['jobs'][0];submit(f.state_path,job)
            evidence=read_json(checked_file(f.root,f.request['evidence']));evidence['attempt_id']=job['attempt_id']
            f.request={**f.request,'request_id':'retry-'+str(index),'original_attempt_id':job['attempt_id'],
                       'evidence':f.write('no-image-'+str(index)+'.json',evidence)}
        before=digest(f.state_path)
        self.assertEqual(recover(f.state_path,before,f.request)['status'],'NO_IMAGE_DIAGNOSIS_REQUIRED')
        self.assertEqual(before,digest(f.state_path))
        f.request['diagnosis']={'cause':'SYNTHETIC host transport interruption','remediation':'SYNTHETIC restored host transport',
                               'evidence':f.write('diagnosis.json',{'synthetic_actual_diagnosis':True})}
        self.assertEqual(recover(f.state_path,before,f.request)['status'],'NO_IMAGE_RETRY_READY')

    def test_paused_clock_blocks_new_attempt_without_resetting_clock(self):
        import runtime_clock as clock
        f=self.fixture();state=read_json(f.state_path)
        state['runtime_execution_context']=clock.initialize_context(f.root,'production',14400)
        atomic_json(f.state_path,state);folder=f.root/'00_任务协调'
        with tempfile.TemporaryDirectory() as temp, patch.dict(__import__('os').environ,{'CODEX_HOME':temp}):
            clock.initialize(folder,'production',14400);clock.bind(folder,'synthetic-recovery-pause',Path(temp))
            clock.event(folder,'start','start');clock.event(folder,'pause','user-pause')
            before=digest(f.state_path);elapsed=clock.status(folder)['active_seconds']
            with self.assertRaisesRegex(ValueError,'PAUSED'):recover(f.state_path,before,f.request)
            self.assertEqual(before,digest(f.state_path));self.assertEqual(elapsed,clock.status(folder)['active_seconds'])

    def test_changed_evidence_and_stale_cas_cannot_recover(self):
        f=self.fixture();before=digest(f.state_path)
        with self.assertRaisesRegex(ValueError,'STATE_CHANGED'):recover(f.state_path,'0'*64,f.request)
        (f.root/f.request['evidence']['path']).write_text('{}')
        with self.assertRaises(ValueError):recover(f.state_path,before,f.request)
        self.assertEqual(before,digest(f.state_path))

    def test_native_cli_recovery_returns_once_without_fallthrough(self):
        f=self.fixture();request=f.root/'request.json';atomic_json(request,f.request)
        script=Path(__file__).resolve().parents[1]/'scripts/production_runtime.py'
        proc=subprocess.run([sys.executable,'-B',str(script),'--action','recover-no-image','--state',str(f.state_path),
             '--expected-state-sha256',digest(f.state_path),'--recovery-request',str(request)],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['status'],'NO_IMAGE_RETRY_READY')


class RecoveryHostTests(unittest.TestCase):
    def test_host_adapter_keeps_frozen_snapshot_and_saves_new_return(self):
        from test_generation_host import HostTests
        import base64,io
        from PIL import Image
        fixture=HostTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        root=fixture.root;state_path=fixture.state_path
        before=read_json(state_path);snapshot=Path(before['runtime_snapshot']['path'])
        job=fixture.host('compile','--panels','P001')['jobs'][0];jp=fixture.write(root/'job.json',job)
        fixture.host('prepare-submit','--job',jp)
        def ref(name,value):
            fixture.write(root/name,value);return {'path':name,'sha256':digest(root/name)}
        original=ref('actual-executor.json',{'synthetic':True,'actual_invocations':0})
        evidence=ref('no-image.json',{'book_id':before['book_id'],'episode_id':before['episode_id'],
            'panel_id':'P001','attempt_id':job['attempt_id'],'round_id':job['round_id'],
            'no_image_confirmed':True,'outcome':'NOT_INVOKED','invocation_started':False,
            'source_kind':'observed_executor_outcome','source_locator':'synthetic://executor',
            'evidence':'synthetic observed not invoked','evidence_files':[original]})
        auth=ref('retry-auth.json',{'source_kind':'user_message','source_locator':'synthetic://user','quote':'SYNTHETIC explicit no-image recovery',
            'book_id':before['book_id'],'episode_ids':[before['episode_id']],'panel_ids':['P001'],
            'operations':['no_image_retry','compatibility_execution']})
        request=fixture.write(root/'recover.json',{'request_id':'host-one','panel_id':'P001','original_attempt_id':job['attempt_id'],
                     'evidence':evidence,'authorization':auth})
        expected=digest(state_path)
        result=fixture.host('recover-no-image','--recovery-request',request,'--expected-state-sha256',expected)
        self.assertEqual(result['status'],'NO_IMAGE_RETRY_READY')
        self.assertNotIn('compatibility_adapter',result)
        self.assertFalse((state_path.parent/'recovery_execution').exists())
        after=read_json(state_path);self.assertEqual(after['runtime_snapshot'],before['runtime_snapshot']);self.assertEqual(digest(snapshot),before['runtime_snapshot']['sha256'])
        retry=fixture.host('recover-no-image','--recovery-request',request,'--expected-state-sha256',expected)
        self.assertEqual(retry['status'],'NO_IMAGE_RECOVERY_ALREADY_SAVED')
        new=fixture.host('compile','--panels','P001')['jobs'][0]
        self.assertEqual(new['arguments'],job['arguments']);jp2=fixture.write(root/'job2.json',new)
        fixture.host('prepare-submit','--job',jp2)
        stream=io.BytesIO();Image.new('RGB',(90,160),'white').save(stream,format='PNG')
        raw=fixture.write(root/'returned.json',{'image_url':'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode()})
        fixture.host('save-return','--job',jp2,'--raw-result',raw,'--call-locator','synthetic://new-call','--result-locator','synthetic://new-result')
        final=read_json(state_path)['panels'][0]
        self.assertEqual(final['status'],'GENERATED');self.assertEqual(final['attempt_id'],new['attempt_id'])
        self.assertEqual(len(final['no_image_history']),1)

class RecoveryDeliveryTests(unittest.TestCase):
    def test_light_qa_delivery_retains_recovery_evidence_and_still_rejects_missing_panels(self):
        from test_light_review import LightReviewTests
        from review_pipeline import save
        from panel_delivery import build
        fixture=LightReviewTests();h,path,row,proposal=fixture.fixture();self.addCleanup(fixture.doCleanups)
        state=read_json(path);root=h.root;target=state['panels'][0]
        def ref(name,value):
            atomic_json(root/name,value);return {'path':name,'sha256':digest(root/name)}
        previous=copy.deepcopy(target)
        for name in ('output','qa_report','adoption','production_decisions','failure_diagnosis'):previous.pop(name,None)
        previous.update(attempt_id='synthetic-confirmed-no-image',status='IN_FLIGHT')
        packet=read_json(checked_file(root,target['package_manifest']));packet=copy.deepcopy(packet)
        packet['panels'][0]['generation_execution']={'status':'NOT_RUN'}
        packet['round_context']['attempt_id']=previous['attempt_id']
        previous['package_manifest']=ref('previous-no-image-package.json',packet)
        event=ref('previous-executor-event.json',{'synthetic':True,'invocation_started':False})
        evidence=ref('delivery-no-image.json',{'book_id':state['book_id'],'episode_id':state['episode_id'],
            'panel_id':row['panel_id'],'attempt_id':previous['attempt_id'],'round_id':1,'no_image_confirmed':True,
            'outcome':'NOT_INVOKED','invocation_started':False,'source_kind':'observed_executor_outcome',
            'source_locator':'synthetic://previous-executor','evidence':'SYNTHETIC fixture no-image event','evidence_files':[event]})
        auth=ref('delivery-recovery-auth.json',{'source_kind':'user_message','source_locator':'synthetic://user',
            'quote':'SYNTHETIC explicit recovery authorization','book_id':state['book_id'],
            'episode_ids':[state['episode_id']],'panel_ids':[row['panel_id']],'operations':['no_image_retry']})
        target['no_image_history']=[{'policy':'confirmed_no_image_recovery_v1','panel_id':row['panel_id'],'round_id':1,
            'original_attempt':previous,'new_attempt_id':target['attempt_id'],'evidence':evidence,'authorization':auth}]
        atomic_json(path,state);save(path,digest(path),proposal);state=read_json(path)
        report=build(state,root)
        self.assertEqual(report['panels'][0]['outcome'],'DELIVERABLE')
        self.assertFalse(report['handoff_complete'])
        self.assertIn(evidence,report['artifacts']);self.assertIn(auth,report['artifacts']);self.assertIn(event,report['artifacts'])
        (root/event['path']).write_text('changed')
        with self.assertRaises(ValueError):build(state,root)
