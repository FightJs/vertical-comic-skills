"""Actual compile -> CLI writer -> JS runner, with no real image service."""
import copy,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
BASE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(BASE/'scripts'),str(Path(__file__).parent)]
from dispatch_fixture import DispatchFixture
from episode_dispatch_queue import reserve_ready
from codex_reference_contract import read_json,digest
from platform_io import atomic_json
import managed_dispatch as managed
import runtime_clock as clock
from production_runtime import compile_jobs,submit


def simultaneous_submit(state,job,barrier,queue):
    barrier.wait(20)
    try:queue.put(submit(state,job))
    except Exception as exc:queue.put({'error':str(exc)})


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)/'home'
        p=patch.dict(os.environ,{'CODEX_HOME':str(self.home)});p.start();self.addCleanup(p.stop)

    def fixture(self,protocol='ordinary',mode='running'):
        f=DispatchFixture(slots=2);self.addCleanup(f.close)
        ref=clock.initialize_context(f.root,'production',10)
        d=f.root/'00_任务协调';now=clock.instant()
        clock.initialize(d,'production',10,at=now);clock.bind(d,'synthetic-'+f.root.name+__import__('uuid').uuid4().hex,self.home)
        clock.event(d,'start','start',at=now)
        f.state['runtime_execution_context']=ref;f.flush()
        if protocol=='managed':
            managed.admit(f.state_path,digest(f.state_path),digest(f.control_path),old_writers_stopped=True,
                          immutable_inputs=True,saver_protocol='exclusive_evidence_v1',reason='SYNTHETIC test')
        # Reserve/compile before introducing the blocked condition.
        reserve=managed.reserve if protocol=='managed' else reserve_ready
        reserve(f.state_path,digest(f.state_path),digest(f.control_path),max_count=1,
                **({'request_id':'synthetic-boundary'} if protocol=='managed' else {}))
        state=read_json(f.state_path)
        job=(managed.call(f.state_path,'compile',panel_ids=['P001']) if protocol=='managed'
             else compile_jobs(state,f.root,['P001']))['jobs'][0]
        if mode=='paused':clock.event(d,'pause','pause')
        if mode=='wait_user':clock.event(d,'wait_user','wait-user')
        if mode=='uncertain':clock.event(d,'uncertain','uncertain')
        if mode=='missing_context':(d/'execution-context.json').unlink()
        if mode=='unbound':clock.release(d)
        if mode=='expired':
            # Synthetic elapsed timestamps in this isolated fixture, never a live clock.
            for p in [d/'runtime-clock.json',*(d/'clock-events').glob('*.json')]:
                x=read_json(p)
                stamps=([x['created']]+[e['at'] for e in x['events']]) if 'events' in x else [x['at']]
                for stamp in stamps:stamp['wall']-=120;stamp['mono']-=120
                atomic_json(p,x)
        if mode=='missing':(d/'runtime-clock.json').unlink()
        return f,job

    def boundary(self,f,job,protocol='ordinary',omit=False):
        cfg=Path(self.temp.name)/'boundary.json'
        atomic_json(cfg,{'scripts':str(BASE/'scripts'),'python':sys.executable,'state':str(f.state_path),
                         'job':job,'protocol':protocol,'omitCallback':omit})
        p=subprocess.run(['node',str(Path(__file__).with_name('submission_boundary_probe.js')),str(cfg)],
                         capture_output=True,text=True,encoding='utf-8',timeout=60)
        self.assertEqual(p.returncode,0,p.stderr);return json.loads(p.stdout)

    def test_original_compiled_jobs_cannot_omit_registration(self):
        for protocol in ('ordinary','managed'):
            with self.subTest(protocol=protocol):
                f,job=self.fixture(protocol)
                before=(digest(f.state_path),digest(f.control_path))
                out=self.boundary(f,job,protocol,True)
                self.assertEqual(out['touches'],0,out);self.assertIn('onBeforeInvoke',out['error'])
                self.assertEqual(before,(digest(f.state_path),digest(f.control_path)))

    def test_real_cli_registration_and_blocked_modes(self):
        for protocol in ('ordinary','managed'):
            for mode in ('running','paused','expired','missing','missing_context','unbound','wait_user','uncertain'):
                with self.subTest(protocol=protocol,mode=mode):
                    f,job=self.fixture(protocol,mode)
                    before=(digest(f.state_path),digest(f.control_path))
                    out=self.boundary(f,job,protocol)
                    self.assertEqual(out['touches'],int(mode=='running'),out)
                    if mode!='running':self.assertEqual(before,(digest(f.state_path),digest(f.control_path)))
                    else:
                        self.assertEqual(read_json(f.state_path)['panels'][0]['status'],'IN_FLIGHT')
                        repeat=self.boundary(f,job,protocol)
                        self.assertEqual(repeat['touches'],0,repeat)
                        self.assertIn('ALREADY_REGISTERED',json.dumps(repeat))

    def test_changed_input_and_old_attempt_do_not_register(self):
        f,job=self.fixture()
        before=digest(f.state_path)
        for key,value in (('arguments',{'prompt':'changed'}),('attempt_id','old')):
            changed=copy.deepcopy(job);changed[key]=value
            out=self.boundary(f,changed)
            self.assertEqual(out['touches'],0,out);self.assertEqual(before,digest(f.state_path))

    def test_pause_during_preflight_is_rechecked_before_write(self):
        f,job=self.fixture();before=digest(f.state_path)
        import staged_workflow
        original=staged_workflow.preflight_many
        def pause(*a,**kw):
            value=original(*a,**kw);clock.event(f.root/'00_任务协调','pause','during-preflight');return value
        with patch.object(staged_workflow,'preflight_many',side_effect=pause):
            with self.assertRaisesRegex(ValueError,'RUNTIME_CLOCK_PAUSED'):submit(f.state_path,job)
        self.assertEqual(before,digest(f.state_path))

    def test_same_attempt_concurrently_registers_only_once(self):
        import multiprocessing
        f,job=self.fixture();ctx=multiprocessing.get_context('spawn')
        barrier=ctx.Barrier(2);queue=ctx.Queue()
        processes=[ctx.Process(target=simultaneous_submit,args=(str(f.state_path),job,barrier,queue)) for _ in range(2)]
        try:
            for p in processes:p.start()
            values=[queue.get(timeout=30) for _ in processes]
            for p in processes:p.join(10);self.assertEqual(p.exitcode,0)
            self.assertEqual(sum(v.get('invoke_allowed') is True for v in values),1,values)
            self.assertEqual(sum(v.get('status')=='ALREADY_REGISTERED' for v in values),1,values)
            self.assertEqual(len(read_json(f.state_path)['submission_registrations']),1)
        finally:
            for p in processes:
                if p.is_alive():p.terminate();p.join(5)
            queue.close()

    def test_registered_attempt_survives_lost_ack_and_status_never_authorizes(self):
        from production_runtime import submission_status
        f,job=self.fixture();submit(f.state_path,job)
        before=digest(f.state_path)
        value=submission_status(f.state_path,job)
        self.assertEqual(value['status'],'REGISTRATION_FOUND');self.assertFalse(value['invoke_allowed'])
        self.assertFalse(submit(f.state_path,job)['invoke_allowed'])
        self.assertEqual(before,digest(f.state_path))

    def test_pause_immediately_after_commit_retains_registration_without_permission(self):
        import production_runtime
        f,job=self.fixture();write=production_runtime.atomic_json
        def pause_after_write(path,value):
            write(path,value)
            if Path(path)==f.state_path and value.get('submission_registrations'):
                clock.event(f.root/'00_任务协调','pause','after-durable-registration')
        with patch.object(production_runtime,'atomic_json',side_effect=pause_after_write):
            with self.assertRaisesRegex(ValueError,'SUBMISSION_REGISTERED_NO_INVOKE'):submit(f.state_path,job)
        state=read_json(f.state_path)
        self.assertEqual(state['panels'][0]['status'],'IN_FLIGHT')
        self.assertEqual(len(state['submission_registrations']),1)
        self.assertEqual(clock.status(f.root/'00_任务协调')['state'],'PAUSED')

    def test_round_two_repair_uses_same_mandatory_registration(self):
        f=DispatchFixture(slots=1);self.addCleanup(f.close)
        f.authorize_synthetic_repair('P001')
        reserve_ready(f.state_path,digest(f.state_path),digest(f.control_path),max_count=1)
        job=compile_jobs(read_json(f.state_path),f.root,['P001'])['jobs'][0]
        self.assertEqual((job['kind'],job['round_id']),('repair',2))
        self.assertEqual(self.boundary(f,job,omit=True)['touches'],0)
        out=self.boundary(f,job);self.assertEqual(out['touches'],1,out)
        self.assertEqual(self.boundary(f,job)['touches'],0)

    def test_existing_return_is_saved_after_clock_expiration(self):
        from codex_reference_contract import checked_file,validate_panel
        from production_runtime import commit_updates
        from PIL import Image
        for protocol in ('ordinary','managed'):
            with self.subTest(protocol=protocol):
                f,job=self.fixture(protocol)
                if protocol=='managed':managed.submit(f.state_path,job=job)
                else:submit(f.state_path,job)
                d=f.root/'00_任务协调'
                for p in [d/'runtime-clock.json',*(d/'clock-events').glob('*.json')]:
                    x=read_json(p);stamps=([x['created']]+[e['at'] for e in x['events']]) if 'events' in x else [x['at']]
                    for stamp in stamps:stamp['wall']-=120;stamp['mono']-=120
                    atomic_json(p,x)
                self.assertEqual(clock.status(d)['remaining_seconds'],0)
                state=read_json(f.state_path);row=state['panels'][0]
                packet=read_json(checked_file(f.root,row['package_manifest']))
                _,plan=validate_panel(packet['panels'][0],f.root)
                def evidence(name,value):
                    p=f.root/name;atomic_json(p,value);ref={'path':name,'sha256':digest(p)}
                    return managed.publish_evidence(f.state_path,name,p,ref['sha256']) if protocol=='managed' else ref
                p=f.root/'synthetic-return.png';Image.new('RGB',(90,160),'white').save(p)
                output={'path':p.name,'sha256':digest(p)}
                if protocol=='managed':output=managed.publish_evidence(f.state_path,p.name,p,output['sha256'])
                request=evidence('synthetic-request.json',{'attempt_id':row['attempt_id'],'backend_id':'codex_builtin_imagegen',
                    'panel_id':row['panel_id'],**plan,'source_kind':'observed_tool_call','source_locator':'synthetic://NO-REAL-REQUEST'})
                response=evidence('synthetic-response.json',{'attempt_id':row['attempt_id'],'status':'COMPLETED',
                    'outputs':[output],'source_kind':'observed_tool_result','source_locator':'synthetic://NO-REAL-RESULT'})
                packet['panels'][0]['generation_execution']={'status':'COMPLETED','attempt_id':row['attempt_id'],
                    'request_evidence':request,'response_evidence':response}
                update={'panel_id':row['panel_id'],'attempt_id':row['attempt_id'],'round_id':row['round_id'],'status':'GENERATED',
                    'output':output,'package_manifest':evidence('synthetic-return-packet.json',packet)}
                result=(managed.save(f.state_path,[update],'late-return') if protocol=='managed'
                        else commit_updates(f.state_path,digest(f.state_path),[update]))
                self.assertEqual(result['status'],'UPDATES_SAVED')
                self.assertEqual(read_json(f.state_path)['dispatch_ledger'][0]['status'],'COMPLETED')


if __name__=='__main__':unittest.main()
