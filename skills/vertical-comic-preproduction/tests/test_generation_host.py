"""Frozen host integration using synthetic approved fixtures; zero service calls."""
import base64,copy,io,json,subprocess,sys,unittest
from pathlib import Path
from PIL import Image
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import test_direct_handoff as fixture
from codex_reference_contract import digest
from production_runtime import compile_jobs
from handoff_delivery import local_execution_view,bind
from runtime_snapshot import create,verify
from test_rule_memory import library
from image_return_io import put
HOST=Path(__file__).resolve().parents[1]/'scripts/generation_host.py'

class HostTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.DirectHandoffTests();self.f.FINAL_SEMANTICS=True
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        bound=bind(self.f.package,self.f.base/'host-run')
        self.root=Path(bound['run_root'])/'E000'
        self.state_path=self.root/'00_输入审计/生产流程.json';self.state=json.loads(self.state_path.read_text(encoding='utf-8'))
    def write(self,path,value):path.write_text(json.dumps(value,ensure_ascii=False), encoding='utf-8');return path
    def host(self,action,*args,ok=True):
        p=subprocess.run([sys.executable,'-X','utf8','-B',str(HOST),action,'--state',str(self.state_path),*map(str,args)],capture_output=True,text=True,encoding='utf-8')
        data=json.loads(p.stdout)
        if ok:self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        else:self.assertNotEqual(p.returncode,0,p.stdout)
        return data
    def test_inspection_and_binding_do_not_write_snapshot_or_state(self):
        before=self.state_path.read_bytes();files=fixture.h.files(self.f.package/'runtime')
        info=self.host('inspect-runtime');self.assertEqual(info['submission_protocol'],'durable_image_submission_v1')
        self.host('check-bindings')
        self.assertEqual(before,self.state_path.read_bytes());self.assertEqual(files,fixture.h.files(self.f.package/'runtime'))
    def test_real_runtime_submit_save_unreviewed_qa_and_idempotent_recovery(self):
        job=self.host('compile','--panels','P001')['jobs'][0];jp=self.write(self.root/'job.json',job)
        ack=self.host('prepare-submit','--job',jp);self.assertEqual(ack['status'],'SUBMISSION_REGISTERED')
        duplicate=self.host('prepare-submit','--job',jp);self.assertFalse(duplicate['invoke_allowed'])
        stream=io.BytesIO();Image.new('RGB',(90,160),'white').save(stream,format='PNG')
        raw=self.write(self.root/'return.json',{'image_url':'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode()})
        saved=self.host('save-return','--job',jp,'--raw-result',raw,'--call-locator','synthetic://call','--result-locator','synthetic://result')
        self.assertEqual(saved['visual_review'],'UNREVIEWED')
        state=json.loads(self.state_path.read_text(encoding='utf-8'));self.assertEqual(state['panels'][0]['status'],'GENERATED')
        again=self.host('save-return','--job',jp,'--raw-result',raw,'--call-locator','synthetic://call','--result-locator','synthetic://result')
        self.assertEqual(again['status'],'RETURN_ALREADY_SAVED')
        before=self.state_path.read_bytes()
        replay=self.host('replay-return','--job',jp,'--raw-result',raw,'--output',self.f.base/'isolated-replay')
        self.assertEqual(replay['image_calls'],0);self.assertEqual(replay['qa_status'],'HOLD_UNREVIEWED')
        self.assertEqual(before,self.state_path.read_bytes())
        q=self.host('prepare-qa','--panels','P001');item=next(i for i in q['items'] if i['panel_id']=='P001')
        qa=json.loads((self.root/item['qa_template']['path']).read_text(encoding='utf-8'))
        self.assertEqual(qa['source_manifest_sha256'],state['panels'][0]['package_manifest']['sha256'])
        self.assertEqual(qa['status'],'HOLD_UNREVIEWED')
    def test_bad_audit_job_does_not_mark_inflight(self):
        job=self.host('compile','--panels','P001')['jobs'][0];job['input_audit_only']=True
        jp=self.write(self.root/'audit-job.json',job);before=self.state_path.read_bytes()
        self.host('prepare-submit','--job',jp,ok=False);self.assertEqual(before,self.state_path.read_bytes())
    def test_local_rules_rebind_preserves_original_and_actual_input(self):
        source=library(self.f.base/'rules');source['index_sha256']=digest(self.f.base/'rules/记忆索引.json');snap=create(self.f.base/'with-rules',memory_source=source)
        state=copy.deepcopy(self.state);state.update(runtime_snapshot=snap,memory_source=verify(snap)['memory_source'])
        packet=fixture.f.fixtures.read(self.root,state['panels'][0]['package_manifest'])
        packet['memory_source']={**state['memory_source'],'root':str(self.f.base/'unavailable-source')}
        old=copy.deepcopy(packet);bound,proof=local_execution_view(state,self.root,packet,self.root)
        self.assertEqual(old,packet);self.assertNotEqual(bound['memory_source']['root'],packet['memory_source']['root'])
        self.assertTrue(proof['actual_input_signature_equal'])
        self.assertEqual(proof['semantic_digest_before'],proof['semantic_digest_after'])
        packet['memory_source']['index']='another-index.json'
        with self.assertRaisesRegex(ValueError,'CONTENT_CHANGED'):local_execution_view(state,self.root,packet,self.root)

    def test_audit_dependency_blocks_only_affected_submit(self):
        job=self.host('compile','--panels','P001')['jobs'][0]
        jp=self.write(self.root/'job.json',job);before=self.state_path.read_bytes()
        marker=self.root.parent/'接收审计活动.json'
        self.write(marker,{'policy':'receiver_active_read_scopes_v1','protected_state_paths':[str(self.state_path)]})
        held=self.host('prepare-submit','--job',jp,ok=False)
        self.assertIn('RECEIVER_READ_CONFLICT',held['error']);self.assertEqual(before,self.state_path.read_bytes())
        self.write(marker,{'policy':'receiver_active_read_scopes_v1','protected_state_paths':[str(self.root.parent/'independent.json')]})
        self.assertEqual(self.host('prepare-submit','--job',jp)['status'],'SUBMISSION_REGISTERED')


if __name__=='__main__':unittest.main()

class WorkerTests(unittest.TestCase):
    setUp=HostTests.setUp
    write=HostTests.write
    host=HostTests.host
    def test_new_worker_reuses_verified_facts_and_keeps_source_state(self):
        state=json.loads(self.state_path.read_text(encoding='utf-8'));state['runtime_pipeline_policy']='observed_incremental_pipeline_v1'
        self.write(self.state_path,state);before=self.state_path.read_bytes()
        lines='\n'.join(json.dumps({'request_id':i,'action':'compile','panels':['P001'],'record_timing':False}) for i in (1,2))+'\n'
        p=subprocess.run([sys.executable,'-X','utf8','-B',str(HOST),'serve','--state',str(self.state_path)],
                         input=lines,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);items=[json.loads(l) for l in p.stdout.splitlines()]
        self.assertEqual(len(items),2);self.assertEqual(len(items[1]['result']['jobs']),1)
        self.assertGreater(items[1]['result']['workflow_timing']['validation_pool']['hits'],0)
        self.assertEqual(before,self.state_path.read_bytes())
