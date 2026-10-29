"""New production boundary, real local registration, no image service."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]

class UnifiedBoundaryTests(unittest.TestCase):
    def test_retired_modes_cannot_route_to_old_engine(self):
        from staged_workflow import _evaluate_impl
        for mode in (None,'sequential_v1','batch5_v1','half_episode_async_v1'):
            with self.subTest(mode=mode):
                result=_evaluate_impl({'execution_mode':mode},Path('.'),'generate','P001')
                self.assertEqual(result['next_action'],'IMPORT_HISTORICAL_DATA')
                self.assertFalse(result['dispatch_authorized'])

    def test_source_protocol_is_data_only(self):
        from generation_host import protocol
        with self.assertRaisesRegex(ValueError,'IMPORT_REQUIRED'):
            protocol(Path('.'),{'policy':'comic_runtime_capabilities_v1'})

    def test_compile_submit_reuses_internal_preflight_but_revoked_job_does_not(self):
        import test_direct_handoff as fixtures
        from production_runtime import compile_jobs,submit
        import staged_workflow
        from validation_pool import ValidationPool,session
        from codex_reference_contract import read_json
        f=fixtures.DirectHandoffTests();f.setUp();self.addCleanup(f.doCleanups)
        path=f.template/'00_输入审计/生产流程.json';state=read_json(path)
        state['runtime_pipeline_policy']='observed_incremental_pipeline_v1'
        path.write_text(json.dumps(state),encoding='utf-8')
        with session(ValidationPool()),patch.object(staged_workflow,'evaluate',wraps=staged_workflow.evaluate) as gate:
            jobs=compile_jobs(state,f.template,['P001'])['jobs']
            self.assertEqual(len(jobs),1)
            first=gate.call_count
            ack=submit(path,jobs[0])
            self.assertTrue(ack['invoke_allowed']);self.assertEqual(gate.call_count,first)
            self.assertFalse(submit(path,jobs[0])['invoke_allowed'])
        # Registered identity remains exact, even if a caller rewrites a job.
        bad=copy.deepcopy(jobs[0]);bad['arguments']['prompt']+=' forged'
        with self.assertRaises(ValueError):submit(path,bad)

class ReturnPreservationTests(unittest.TestCase):
    def test_old_capability_cannot_dispatch_but_actual_return_can_be_saved(self):
        import base64,io
        from PIL import Image
        from codex_reference_contract import digest,read_json
        import test_generation_host as fixtures
        f=fixtures.HostTests();f.setUp();self.addCleanup(f.doCleanups)
        job=f.host('compile','--panels','P001')['jobs'][0]
        jp=f.write(f.root/'job.json',job);f.host('prepare-submit','--job',jp)
        state=read_json(f.state_path);manifest=Path(state['runtime_snapshot']['path'])
        cap=manifest.parent/'skills/vertical-comic-preproduction/scripts/runtime_capabilities.json'
        caps=read_json(cap);caps.pop('production_executor');f.write(cap,caps)
        contents=read_json(manifest)
        for row in contents['files']:
            if row['path']==cap.relative_to(manifest.parent).as_posix():
                row['sha256']=digest(cap)
                if 'bytes' in row:row['bytes']=cap.stat().st_size
        f.write(manifest,contents);state['runtime_snapshot']['sha256']=digest(manifest);f.write(f.state_path,state)
        before=manifest.read_bytes()
        self.assertIn('IMPORT_REQUIRED',f.host('compile','--panels','P001',ok=False)['error'])
        buf=io.BytesIO();Image.new('RGB',(90,160),'white').save(buf,format='PNG')
        raw=f.write(f.root/'actual-return.json',{'image_url':'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()})
        result=f.host('save-return','--job',jp,'--raw-result',raw,'--call-locator','synthetic://call','--result-locator','synthetic://result')
        self.assertEqual(result['visual_review'],'UNREVIEWED')
        self.assertEqual(read_json(f.state_path)['panels'][0]['status'],'GENERATED')
        self.assertEqual(manifest.read_bytes(),before)

class SchedulingTests(unittest.TestCase):
    def test_forecast_uses_shared_active_clock_and_keeps_first_round_running(self):
        from stage_deadlines import forecast
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);paths=[]
            for e in range(2):
                p=root/f'E{e}.json';p.write_text(json.dumps({'episode_id':str(e),'panels':[{'panel_id':str(i)} for i in range(10)]}));paths.append(p)
            context={'run_id':'synthetic-shared','clock_directory':str(root)}
            with patch('runtime_clock.execution_context',return_value=context):
                forecast(paths,{'active_seconds':0,'remaining_seconds':14400})
                v=json.loads(paths[0].read_text())
                for r in v['panels'][:5]:r['output']={'synthetic_schedule_marker':True}
                paths[0].write_text(json.dumps(v))
                result=forecast(paths,{'active_seconds':10800,'remaining_seconds':3600})
                self.assertEqual(result['status'],'AT_RISK');self.assertEqual(result['missing_panels'],15)
                self.assertFalse(result['stop_first_round']);self.assertFalse(result['real_image_service_guarantee'])
                with self.assertRaisesRegex(ValueError,'CLOCK_RESET'):
                    forecast(paths,{'active_seconds':0,'remaining_seconds':14400})

if __name__=='__main__':unittest.main()
