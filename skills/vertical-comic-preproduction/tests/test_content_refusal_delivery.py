import sys,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).parents[1]/'scripts'),str(Path(__file__).parent)]
from codex_reference_contract import read_json,checked_file,digest
from no_image_recovery import recover,content_refusal
from platform_io import atomic_json
from test_no_image_recovery import RecoveryTests

class ContentRefusalTests(unittest.TestCase):
 def fixture(self):
  helper=RecoveryTests();self.addCleanup(helper.doCleanups);f=helper.fixture('REJECTED_NO_OUTPUT')
  row=read_json(f.state_path)['panels'][0]
  auth=read_json(checked_file(f.root,f.request['authorization']));auth['operations'].append('content_failure_delivery')
  f.request['authorization']=f.write('content-auth.json',auth)
  raw=f.write('content-error.json',{'attempt_id':row['attempt_id'],'error':{'message':'Image rejected by content policy'}})
  report=read_json(checked_file(f.root,f.request['evidence']));report.update(rejection_kind='content_policy',evidence_files=[raw])
  f.request['evidence']=f.write('content-report.json',report)
  return f
 def test_refusal_preserves_attempt_and_replays_without_retry(self):
  f=self.fixture();before=read_json(f.state_path);result=recover(f.state_path,digest(f.state_path),f.request)
  self.assertEqual(result['status'],'CONTENT_REFUSAL_DELIVERY');self.assertFalse(result['invoke_allowed'])
  state=read_json(f.state_path);row=state['panels'][0];self.assertEqual(row['attempt_id'],before['panels'][0]['attempt_id'])
  self.assertEqual(row['status'],'CALL_FAILED');self.assertNotIn('output',row);self.assertFalse(row.get('no_image_history'))
  self.assertIn('content policy',content_refusal(state,f.root,row)['last_error'])
  self.assertEqual(recover(f.state_path,digest(f.state_path),f.request)['status'],'CONTENT_REFUSAL_DELIVERY')
 def test_wrong_attempt_or_missing_authority_cannot_close(self):
  f=self.fixture();report=read_json(checked_file(f.root,f.request['evidence']))
  report['evidence_files']=[f.write('wrong.json',{'attempt_id':'other','error':'content policy'})]
  bad={**f.request,'request_id':'wrong','evidence':f.write('wrong-report.json',report)}
  with self.assertRaisesRegex(ValueError,'NOT_PROVEN'):recover(f.state_path,digest(f.state_path),bad)
  auth=read_json(checked_file(f.root,f.request['authorization']));auth['operations']=['no_image_retry']
  bad={**f.request,'request_id':'no-auth','authorization':f.write('no-content-auth.json',auth)}
  with self.assertRaisesRegex(ValueError,'CONTENT_RESTRICTION'):recover(f.state_path,digest(f.state_path),bad)
  state=read_json(f.state_path);state['panels'][0]['status']='RESULT_UNKNOWN';atomic_json(f.state_path,state)
  with self.assertRaisesRegex(ValueError,'UNKNOWN_MUST_BE_RESOLVED'):recover(f.state_path,digest(f.state_path),f.request)

class ContentDeliveryTests(unittest.TestCase):
 def fixture(self):
  from test_network_retry_limit import NetworkDeliveryTests
  from panel_delivery import build
  from platform_io import atomic_json
  htest=NetworkDeliveryTests();self.addCleanup(htest.doCleanups);h,sp,state=htest.fixture();write=h.h.f.write
  for row in state['panels'][1:]:
   row.pop('network_retry_exhausted');aid=row['attempt_id'];pid=row['panel_id']
   raw=write(pid+'-actual-content.json',{'attempt_id':aid,'error':'Image rejected by content policy'})
   auth=write(pid+'-auth-content.json',{'source_kind':'user_message','source_locator':'synthetic://user','quote':'SYNTHETIC deliver refusal gap','book_id':state['book_id'],'episode_ids':[state['episode_id']],'panel_ids':[pid],'operations':['no_image_retry','content_failure_delivery']})
   evidence=write(pid+'-content-report.json',{'book_id':state['book_id'],'episode_id':state['episode_id'],'panel_id':pid,'attempt_id':aid,'round_id':row['round_id'],'no_image_confirmed':True,'outcome':'REJECTED_NO_OUTPUT','rejection_kind':'content_policy','source_kind':'observed_tool_error','source_locator':'synthetic://service','evidence':'SYNTHETIC error','evidence_files':[raw]})
   row['content_refusal_delivery']=write(pid+'-marker-content.json',{'policy':'content_refusal_delivery_v1','attempt_id':aid,'last_error':'Image rejected by content policy','evidence':evidence,'authorization':auth})
  report=build(state,h.root);ref=write('content-delivery-review.json',report);state['delivery_review']=ref
  state['gates']['final']={**h.h.approve([*report['artifacts'],ref]),'panel_ids':report['panel_ids']};atomic_json(sp,state)
  return h,sp,state
 def test_formal_and_deadline_zip_report_original_refusal(self):
  import csv,io,zipfile
  import delivery_contract as dc,delivery_publish as pub,production_progress as progress,deadline_delivery as dd,runtime_clock as clock
  h,sp,state=self.fixture();task=h.root.parent/'content-delivery-task';ref=dc.initialize(task,'production',[sp]);out=task/'output'
  report=pub.publish_production(ref['path'],out);self.assertEqual(report['status'],'DELIVERY_READY');archive=report['artifacts'][0]['path']
  with zipfile.ZipFile(archive) as z:
   overview=list(csv.DictReader(io.StringIO(z.read('图片问题总览.csv').decode('utf-8-sig'))))
   self.assertEqual(sum(bool(r['图片路径']) for r in overview),1)
   self.assertTrue(all('内容审核' in r['问题摘要'] for r in overview[1:]))
   self.assertIn('content policy',z.read('问题明细.csv').decode('utf-8-sig'))
   self.assertTrue(any('内容审核拒绝证据/' in name and b'content policy' in z.read(name) for name in z.namelist()))
  display=task/'00_显示进度';progress.initialize(display,'production',[sp])
  result=progress.complete_validated(display,Path(archive),read_json(display/'task.json'),dc.load_identity(ref['path']),ref,out/pub.REPORT)
  self.assertEqual(result['completion_basis'],'AVAILABLE_IMAGES_WITH_AUTHORIZED_FAILURE_GAPS')
  task2=h.root.parent/'content-deadline-task';ref2=dc.initialize(task2,'production',[sp]);folder=task2/'00_任务协调'
  clock.initialize(folder,'production',hard_deadline=True,delivery_deadline=True);clock.event(folder,'start','synthetic-start')
  result=dd.export(ref2['path'],task2/'output');self.assertTrue(result['task_completed']);self.assertFalse(result['images_complete'])
  self.assertTrue(dd.complete(ref2['path'],folder/dd.POINTER,result['archive']['path'])['task_completed'])
