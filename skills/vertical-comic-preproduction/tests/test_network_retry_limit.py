"""Bounded network retries and explicit missing-image delivery, with synthetic evidence."""
import copy, csv, io, json, sys, unittest, zipfile
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import test_no_image_recovery as recovery_tests
from codex_reference_contract import read_json,digest,checked_file
from platform_io import atomic_json
from no_image_recovery import recover,network_exhaustion,network_error,NETWORK_POLICY
from production_runtime import commit_updates,submit
from episode_dispatch_queue import reserve_ready
from _historical_fixture import compile_jobs

class NetworkRetryTests(unittest.TestCase):
    def test_four_retries_then_terminal_gap_and_idempotent_replay(self):
        helper=recovery_tests.RecoveryTests();self.addCleanup(helper.doCleanups)
        f=helper.fixture('FAILED_NO_OUTPUT')
        auth=read_json(checked_file(f.root,f.request['authorization']))
        auth['operations'].append('network_failure_delivery')
        f.request['authorization']=f.write('gap-authority.json',auth)
        initial=read_json(f.state_path)
        for failure in range(5):
            row=read_json(f.state_path)['panels'][0]
            raw=f.write('network-'+str(failure)+'.json',{'attempt_id':row['attempt_id'],
                'error':{'message':'image generation failed: network error: error sending request'}})
            report={**read_json(checked_file(f.root,f.request['evidence'])),
                    'attempt_id':row['attempt_id'],'evidence_files':[raw]}
            f.request={**f.request,'request_id':'network-'+str(failure),'original_attempt_id':row['attempt_id'],
                       'evidence':f.write('report-'+str(failure)+'.json',report)}
            if failure==4:
                original=read_json(f.state_path);changed=copy.deepcopy(original)
                packet=read_json(checked_file(f.root,row['package_manifest']))
                packet['panels'][0]['generation_execution']={'status':'COMPLETED'}
                changed['panels'][0]['package_manifest']=f.write('late-actual-return.json',packet)
                atomic_json(f.state_path,changed)
                with self.assertRaisesRegex(ValueError,'HAS_ACTUAL_RETURN'):
                    recover(f.state_path,digest(f.state_path),f.request)
                atomic_json(f.state_path,original)
            before=digest(f.state_path);result=recover(f.state_path,before,f.request)
            if failure==4:
                self.assertEqual(result['status'],'NETWORK_RETRY_EXHAUSTED')
                state=read_json(f.state_path);target=state['panels'][0]
                self.assertEqual(target['attempt_id'],row['attempt_id'])
                self.assertEqual(target['status'],'CALL_FAILED');self.assertNotIn('output',target)
                self.assertEqual(network_exhaustion(state,f.root,target)['failure_count'],5)
                self.assertEqual(state['panels'][1:],initial['panels'][1:])
                after=digest(f.state_path)
                self.assertEqual(recover(f.state_path,before,f.request)['status'],'NETWORK_RETRY_EXHAUSTED')
                self.assertEqual(digest(f.state_path),after)
                f.request['request_id']='another-session'
                self.assertEqual(recover(f.state_path,after,f.request)['status'],'NETWORK_RETRY_EXHAUSTED')
                self.assertEqual(digest(f.state_path),after)
                target['status']='RESULT_UNKNOWN'
                with self.assertRaises(ValueError):network_exhaustion(state,f.root,target)
                break
            self.assertEqual(result['status'],'NO_IMAGE_RETRY_READY')
            reserve_ready(f.state_path,digest(f.state_path),digest(f.control_path),max_count=1)
            job=compile_jobs(read_json(f.state_path),f.root,['P001'])['jobs'][0];submit(f.state_path,job)
            evidence=f.write('call-'+str(failure)+'.json',{'attempt_id':job['attempt_id'],'status':'CALL_FAILED',
                'source_locator':'synthetic://network','evidence':'Synthetic failed terminal with no output'})
            commit_updates(f.state_path,digest(f.state_path),[{'panel_id':'P001','attempt_id':job['attempt_id'],
                'round_id':1,'status':'CALL_FAILED','call_evidence':evidence}])

    def test_request_builder_preserves_original_network_error_evidence(self):
        from no_image_recovery import prepare_request
        helper=recovery_tests.RecoveryTests();self.addCleanup(helper.doCleanups)
        f=helper.fixture('FAILED_NO_OUTPUT');state=read_json(f.state_path);row=state['panels'][0]
        row['prepared_registration_id']='synthetic-registration';atomic_json(f.state_path,state)
        terminal=read_json(checked_file(f.root,f.request['evidence']))
        terminal['registration_id']=row['prepared_registration_id']
        terminal['evidence_files']=[f.write('actual-error.json',{'attempt_id':row['attempt_id'],
            'error':{'message':'network error: error sending request'}})]
        ref=f.write('terminal-with-error-ref.json',terminal)
        request=prepare_request(f.state_path,'P001',ref,f.request['authorization'])
        report=read_json(checked_file(f.root,request['evidence']))
        self.assertIn(terminal['evidence_files'][0],report['evidence_files'])
        self.assertIsNotNone(network_error(f.root,report))

    def test_classifier_never_uses_prompt_diagnosis_or_other_attempt(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'error.json'
            atomic_json(p,{'attempt_id':'other','error':'network error'})
            report={'attempt_id':'actual','outcome':'FAILED_NO_OUTPUT','evidence_files':[{'path':p.name,'sha256':digest(p)}],
                    'evidence':'network error','diagnosis':'network error','prompt':'network error'}
            self.assertIsNone(network_error(root,report))
            report['error']='network error';self.assertEqual(network_error(root,report),'network error')
            for outcome in ('NOT_INVOKED','REJECTED_NO_OUTPUT'):
                self.assertIsNone(network_error(root,{**report,'outcome':outcome}))
            self.assertIsNone(network_error(root,{**report,'rejection_kind':'content_policy'}))


def make_exhausted(state,root,row,write):
    """Synthetic five verified terminal attempts, preserving source/round identity."""
    from no_image_recovery import put
    for key in ('output','qa_report','adoption','production_decisions','attempt_history'):row.pop(key,None)
    row['status']='CALL_FAILED';row['no_image_history']=[]
    auth=write(row['panel_id']+'-auth.json',{'source_kind':'user_message','source_locator':'synthetic://user',
        'quote':'SYNTHETIC four retries then deliver with network gaps','book_id':state['book_id'],
        'episode_ids':[state['episode_id']],'panel_ids':[row['panel_id']],
        'operations':['no_image_retry','network_failure_delivery']})
    for i in range(5):
        attempt=row['panel_id']+'-network-'+str(i)
        packet=copy.deepcopy(read_json(checked_file(root,row['package_manifest'])))
        packet['round_context']['attempt_id']=attempt
        packet['panels'][0]['generation_execution']={'status':'NOT_RUN'}
        packet_ref=write(attempt+'-packet.json',packet)
        raw=write(attempt+'-error.json',{'attempt_id':attempt,'error':'network error: error sending request'})
        report={'book_id':state['book_id'],'episode_id':state['episode_id'],'panel_id':row['panel_id'],
            'attempt_id':attempt,'round_id':1,'no_image_confirmed':True,'outcome':'FAILED_NO_OUTPUT',
            'source_kind':'observed_tool_error','source_locator':'synthetic://terminal',
            'evidence':'Synthetic observed no-output terminal','evidence_files':[raw]}
        evidence=write(attempt+'-report.json',report)
        call=write(attempt+'-call.json',{'attempt_id':attempt,'status':'CALL_FAILED',
            'source_locator':'synthetic://terminal','evidence':'Synthetic terminal error'})
        old={**{k:v for k,v in row.items() if k!='no_image_history'},'attempt_id':attempt,
             'package_manifest':packet_ref,'call_evidence':call}
        if i<4:row['no_image_history'].append({'policy':'confirmed_no_image_recovery_v1',
            'panel_id':row['panel_id'],'round_id':1,'original_attempt':old,
            'new_attempt_id':row['panel_id']+'-network-'+str(i+1),'evidence':evidence,'authorization':auth})
        else:row.update(attempt_id=attempt,package_manifest=packet_ref,call_evidence=call)
    row['network_retry_exhausted']=write(row['panel_id']+'-exhausted.json',{'policy':NETWORK_POLICY,
        'attempt_id':row['attempt_id'],'max_retries':4,'failure_count':5,'last_error':'network error: error sending request',
        'evidence':evidence,'authorization':auth})
    network_exhaustion(state,root,row)

class NetworkDeliveryTests(unittest.TestCase):
    def fixture(self):
        from test_light_review import LightReviewTests
        from review_pipeline import save
        from panel_delivery import build
        helper=LightReviewTests();self.addCleanup(helper.doCleanups)
        h,sp,row,proposal=helper.fixture();save(sp,digest(sp),proposal)
        state=read_json(sp)
        for row in state['panels'][1:]:make_exhausted(state,h.root,row,h.h.f.write)
        report=build(state,h.root);ref=h.h.f.write('network-delivery-review.json',report)
        state['delivery_review']=ref
        state['gates']['final']={**h.h.approve([*report['artifacts'],ref]),'panel_ids':report['panel_ids']}
        atomic_json(sp,state)
        return h,sp,state

    def test_zip_and_finish_with_real_images_and_explicit_gaps(self):
        import delivery_contract as dc,delivery_publish as pub,production_progress as progress
        h,sp,state=self.fixture();task=h.root.parent/'network-delivery-task'
        ref=dc.initialize(task,'production',[sp]);out=task/'output'
        report=pub.publish_production(ref['path'],out)
        self.assertEqual(report['status'],'DELIVERY_READY')
        archive=report['artifacts'][0]['path']
        with zipfile.ZipFile(archive) as z:
            overview=list(csv.DictReader(io.StringIO(z.read('图片问题总览.csv').decode('utf-8-sig'))))
            self.assertEqual(len(overview),len(state['panels']))
            self.assertEqual(sum(bool(r['图片路径']) for r in overview),1)
            self.assertTrue(all('网络错误' in r['问题摘要'] for r in overview[1:]))
            self.assertIn('网络错误',z.read('问题明细.csv').decode('utf-8-sig'))
        display=task/'00_显示进度';progress.initialize(display,'production',[sp])
        result=progress.complete_validated(display,Path(archive),read_json(display/'task.json'),
            dc.load_identity(ref['path']),ref,out/pub.REPORT)
        self.assertEqual(result['percent'],100)
        self.assertEqual(result['completion_basis'],'AVAILABLE_IMAGES_WITH_AUTHORIZED_NETWORK_GAPS')
        self.assertEqual(result['episodes'][0]['counts']['images'],1)
        # An ordinary missing panel or unknown outcome is never exempted.
        state['panels'][-1].pop('network_retry_exhausted');atomic_json(sp,state)
        with self.assertRaises(ValueError):pub.publish_production(ref['path'],task/'bad')

    def test_deadline_zip_completes_with_gaps_without_fake_qa(self):
        import delivery_contract as dc,deadline_delivery as dd,runtime_clock as clock
        h,sp,state=self.fixture();task=h.root.parent/'deadline-network-task'
        ref=dc.initialize(task,'production',[sp]);folder=task/'00_任务协调'
        clock.initialize(folder,'production',hard_deadline=True,delivery_deadline=True)
        clock.event(folder,'start','synthetic-start')
        report=dd.export(ref['path'],task/'output')
        self.assertTrue(report['task_completed']);self.assertFalse(report['images_complete'])
        self.assertEqual(report['image_count'],1)
        receipt=folder/dd.POINTER
        self.assertTrue(dd.complete(ref['path'],receipt,report['archive']['path'])['task_completed'])
        with zipfile.ZipFile(report['archive']['path']) as z:
            index=json.loads(z.read(state['episode_id']+'/交付索引.json'))
            self.assertTrue(all(r['qa_status']=='UNREVIEWED' for r in index['panels'][1:]))

    def test_tampered_evidence_and_missing_permission_rejected(self):
        h,sp,state=self.fixture();row=state['panels'][-1]
        marker=read_json(checked_file(h.root,row['network_retry_exhausted']))
        auth=read_json(checked_file(h.root,marker['authorization']));auth['operations']=['no_image_retry']
        marker['authorization']=h.h.f.write('no-gap-authority.json',auth)
        row['network_retry_exhausted']=h.h.f.write('changed-marker.json',marker)
        with self.assertRaisesRegex(ValueError,'NOT_PROVEN'):network_exhaustion(state,h.root,row)

if __name__=='__main__':unittest.main()
