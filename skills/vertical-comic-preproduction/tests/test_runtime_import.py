"""Real state/approval bytes through import; no image service or production data."""
import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
from runtime_import import plan_import,apply_import,verify_binding
from runtime_snapshot import create
from codex_reference_contract import read_json
import test_generation_host as fixtures

class RuntimeImportTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.HostTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.path=self.f.state_path;self.root=self.f.root
        self.executor=create(self.f.f.base/'current-executor')
    def test_import_preserves_original_panels_approvals_and_time(self):
        original=self.path.read_bytes();before=read_json(self.path)
        result=apply_import(self.path,plan_import(self.path,self.executor))
        self.assertEqual(result['status'],'IMPORTED');after=read_json(self.path)
        for field in ('panels','gates','production_authorization','runtime_execution_context','runtime_snapshot','repair_authorizations'):
            self.assertEqual(before.get(field),after.get(field),field)
        receipt,old=verify_binding(after,self.root)
        self.assertEqual((self.root/receipt['source_state']['path']).read_bytes(),original)
        self.assertEqual(after['image_review_profile'],'light_story_review_v1')
        saved=self.path.read_bytes();apply_import(self.path,plan_import(self.path,self.executor))
        self.assertEqual(saved,self.path.read_bytes())
    def test_imported_real_compile_and_submit_use_new_pinned_executor(self):
        apply_import(self.path,plan_import(self.path,self.executor))
        job=self.f.host('compile','--panels','P001')['jobs'][0]
        jp=self.f.write(self.root/'import-job.json',job)
        self.assertTrue(self.f.host('prepare-submit','--job',jp)['invoke_allowed'])
        self.assertFalse(self.f.host('prepare-submit','--job',jp)['invoke_allowed'])
    def test_inflight_never_restarts_as_a_fresh_attempt(self):
        state=read_json(self.path);state['panels'][0]['status']='IN_FLIGHT';self.f.write(self.path,state)
        before=self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'INFLIGHT_RECONCILIATION'):plan_import(self.path,self.executor)
        self.assertEqual(before,self.path.read_bytes())
    def test_compare_and_swap_prevents_overwriting_new_state(self):
        plan=plan_import(self.path,self.executor);state=read_json(self.path);state['cancelled']=True;self.f.write(self.path,state)
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):apply_import(self.path,plan)
        self.assertEqual(before,self.path.read_bytes())
    def test_failed_publication_keeps_source_and_can_resume(self):
        plan=plan_import(self.path,self.executor);before=self.path.read_bytes()
        import runtime_import
        real=runtime_import.atomic_json
        def fail(path,data):
            if Path(path)==self.path:raise OSError('synthetic publication failure')
            return real(path,data)
        with patch.object(runtime_import,'atomic_json',fail),self.assertRaises(OSError):apply_import(self.path,plan)
        self.assertEqual(before,self.path.read_bytes())
        self.assertEqual(apply_import(self.path,plan)['status'],'IMPORTED')

class HistoricalEvidenceTests(unittest.TestCase):
    def test_import_preserves_actual_full_qa_failure_without_requiring_new_light_qa(self):
        from test_first_batch_production import FirstBatchTests
        from light_review import evidence_errors
        f=FirstBatchTests();self.addCleanup(f.doCleanups)
        h,state,row,item,decision=f.fixture()
        path=h.root/'00_输入审计/生产流程.json'
        path.write_text(json.dumps(state),encoding='utf-8')
        qa=(h.root/row['qa_report']['path']).read_bytes()
        image=(h.root/row['output']['path']).read_bytes()
        executor=create(h.root.parent/'import-current')
        apply_import(path,plan_import(path,executor))
        after=read_json(path)
        self.assertEqual(after['panels'][0],row)
        self.assertEqual(evidence_errors(h.root,after['panels'][0]),[])
        self.assertTrue(evidence_errors(h.root,after['panels'][0],require_pass=True))
        self.assertEqual((h.root/row['qa_report']['path']).read_bytes(),qa)
        self.assertEqual((h.root/row['output']['path']).read_bytes(),image)
        forged=copy.deepcopy(row);forged['qa_report']={'path':'different.json','sha256':'0'*64}
        from runtime_import import historical_record
        self.assertIsNone(historical_record(after,h.root,forged))

if __name__=='__main__':unittest.main()
