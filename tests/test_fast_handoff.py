"""Real ZIP/relocation tests of content-only release and lazy receive."""
from pathlib import Path
import json,sys,unittest,zipfile
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'skills/vertical-comic-preproduction/scripts'),str(Path(__file__).resolve().parents[1]/'skills/vertical-comic-preproduction/tests')]
import test_direct_handoff as fixture
import comic_start

class FastHandoffTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.DirectHandoffTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
    def release(self,mode='approved_inputs_content_export_v1'):
        f=self.f;candidate=f.base/'candidate-fast.zip';fixture.h.pack(f.package,candidate)
        review=fixture.d.input_review(f.package,f.index)
        auth=f.base/'fast-auth.json';auth.write_text(json.dumps({'status':'APPROVED','source_kind':'user_message',
            'source_locator':'SYNTHETIC_ONLY','quote':'SYNTHETIC delegation: publish content without rehearsal',
            'authorization_mode':mode,'package_id':f.index['package_id'],
            'approved_input_digest':review['approved_input_digest'],'after_successful_rehearsal':True}))
        dest=f.base/'fast-formal.zip'
        with patch.object(fixture.h,'rehearse',side_effect=AssertionError('no duplicate rehearsal')):
            result=fixture.h.release(candidate,None,auth,dest)
        return dest,result
    def test_formal_release_is_receivable_without_fake_rehearsal(self):
        dest,result=self.release();self.assertEqual(result['status'],'RELEASED_DIRECT_DELIVERY_ZIP')
        checked=fixture.h.check_delivery_archive(dest);self.assertEqual(checked['format'],'self_contained_handoff_v1')
        with zipfile.ZipFile(dest) as z:
            top,_=fixture.h.zip_inventory(z);report=fixture.h.read_zip_json(z,top+'/演练与导出确认/演练报告.json')
            self.assertEqual(report['rehearsal'],'NOT_RUN');self.assertEqual(report['results'][0]['status'],'CONTENT_VERIFIED')
        with patch.object(comic_start,'rehearse',side_effect=AssertionError('lazy receive must not audit full batch')):
            reception=comic_start.receive(dest,runtime_limit_seconds=None,output=self.f.base/'fast-receiver')
        self.assertEqual(reception['status'],'READY_FOR_PRODUCTION_ROUTING',reception)
        self.assertEqual(reception['input_audit'],'DEFERRED_TO_COMPILE');self.assertFalse(reception['dispatch_authorized'])
        with patch.object(comic_start,'rehearse',side_effect=AssertionError('resume must preserve lazy policy')):
            resumed=comic_start.receive_resume(reception['run_root'])
        self.assertEqual(resumed['input_audit'],'DEFERRED_TO_COMPILE');self.assertFalse(resumed['rebound'])
        entry=reception['production_entrypoints'][0];state=json.loads(Path(entry['state']).read_text())
        self.assertEqual([r['status'] for r in state['panels']], [r['status'] for r in self.f.state['panels']])
    def test_rehearsal_conditional_permission_is_not_reused_for_fast_release(self):
        with self.assertRaisesRegex(ValueError,'导出确认'):self.release('approved_inputs_auto_export_v1')

if __name__=='__main__':unittest.main()
