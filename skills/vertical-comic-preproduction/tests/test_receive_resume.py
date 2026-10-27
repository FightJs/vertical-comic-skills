"""Content-bound audit reuse and original-run recovery, without services."""
import copy,json,sys,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
from codex_reference_contract import file_session,read_json,path_exists,scan_directory,export_read_set,verify_exported_read_set
import test_direct_handoff as fixture
import comic_start

class ReadSetTests(unittest.TestCase):
    def test_bytes_negative_paths_and_directory_changes_invalidate_proof(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'input.json';p.write_text('{"approved":true}', encoding='utf-8')
            with file_session() as memo:
                read_json(p);path_exists(root/'missing.json');scan_directory(root)
                proof=export_read_set(memo)
            self.assertTrue(verify_exported_read_set(proof,[root]))
            p.write_text('{"approved":false}', encoding='utf-8')
            self.assertFalse(verify_exported_read_set(proof,[root]))
            p.write_text('{"approved":true}', encoding='utf-8');(root/'missing.json').write_text('{}', encoding='utf-8')
            self.assertFalse(verify_exported_read_set(proof,[root]))
    def test_external_paths_and_nonreusable_proofs_do_not_authorize_reuse(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'input.json';p.write_text('{}', encoding='utf-8')
            with file_session() as memo:read_json(p);proof=export_read_set(memo)
            self.assertFalse(verify_exported_read_set(proof,[root/'other']))
            empty={**proof,'files':[]}
            self.assertFalse(verify_exported_read_set(empty,[root]))
            proof['reusable']=False;self.assertFalse(verify_exported_read_set(proof,[root]))

class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.DirectHandoffTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
    def test_rehearsal_reuses_only_content_reverified_results(self):
        z,received,bound,first=self.f.pipeline()
        second=fixture.h.rehearse(z,received,bound['run_root'],bound['run_index'],self.f.base/'resume',
                                 resume_report=self.f.base/'rehearsal/演练报告.json',timeout=20)
        self.assertEqual(second['status'],'RELEASE_CANDIDATE',second)
        self.assertEqual(second['results'][0].get('audit_reuse'),'CONTENT_REVERIFIED',second['results'][0].keys())
        self.assertTrue((self.f.base/'rehearsal/演练报告.json').exists())
        self.assertTrue((self.f.base/'resume/previous/演练报告.json').exists())
    def test_receive_resume_keeps_same_run_state_clock_and_source_files(self):
        self.f.test_direct_bound_run_real_full_episode_gates_and_conditional_release()
        root=next((self.f.base/'接包输出').glob('RV_*'))
        journal=json.loads((root/'接包恢复索引.json').read_text(encoding='utf-8'));local=Path(journal['run_root'])
        before=fixture.h.files(local);clock=(root/'00_任务协调/execution-context.json').read_bytes()
        result=comic_start.receive_resume(root,audit_timeout=20)
        self.assertEqual(result['status'],'READY_FOR_PRODUCTION_ROUTING',result)
        self.assertEqual(before,fixture.h.files(local));self.assertEqual(clock,(root/'00_任务协调/execution-context.json').read_bytes())
        state=local/'E000/00_输入审计/生产流程.json';value=json.loads(state.read_text(encoding='utf-8'));value['panels'][0]['status']='RESULT_UNKNOWN';state.write_text(json.dumps(value), encoding='utf-8')
        before=state.read_bytes();result=comic_start.receive_resume(root)
        self.assertEqual(result['status'],'CONTINUE_ORIGINAL_PRODUCTION');self.assertEqual(before,state.read_bytes())

    def test_protocol_hold_precedes_expensive_rehearsal(self):
        self.f.test_direct_bound_run_real_full_episode_gates_and_conditional_release()
        incompatible=([{'episode_id':'E000'}],[{'episode_id':'E000','status':'HOLD','error':'Unsupported test protocol'}])
        with patch.object(comic_start,'inspect_received_runtime',return_value=incompatible),patch.object(comic_start,'rehearse') as audit:
            result=comic_start.receive(self.f.base/'正式交接包.zip',runtime_limit_seconds=None,output=self.f.base/'unsupported')
        self.assertEqual(result['status'],'HOLD');audit.assert_not_called()


if __name__=='__main__':unittest.main()
