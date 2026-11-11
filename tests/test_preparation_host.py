"""Host integration uses real local contracts; never native model/image services."""
import copy,json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'skills/vertical-comic-preproduction/scripts'),str(ROOT/'skills/vertical-comic-preproduction/tests')]
try:from preparation_host import Host,serve
except ImportError:Host=None
from input_dependencies import file_hash,fingerprint

class HostTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.env=patch.dict(os.environ,{'COMIC_RESOURCE_HOME':str(self.root/'resources')});self.env.start();self.addCleanup(self.env.stop)
  from machine_resources import boot_id
  self.probe=patch('machine_resources.sample_system',lambda disk:{'at':time.monotonic(),'boot':boot_id(),'cpus':8,'known':True,'total':32*1024**3,'available':24*1024**3,'compressed':0,'swapout':0,'pressure':1,'disk_free':20*1024**3});self.probe.start();self.addCleanup(self.probe.stop)
 def marker(self,states=()):
  folder=self.root/'00_任务协调';folder.mkdir(exist_ok=True)
  (folder/'preparation-host.json').write_text(json.dumps({'policy':'preparation_scheduler_v1','book_id':'BOOK','episode_ids':['E001'],'states':[str(p) for p in states]}))
 def host(self):
  self.assertIsNotNone(Host,'preparation host implementation missing');self.marker();h=Host(self.root);self.addCleanup(h.close);return h
 def request(self,h,action,**data):
  if action=='plan' and 'capacities' not in data:data['capacities']={'model':2}
  if action=='status':data.setdefault('details',True)
  return h.handle({'request_id':action+'-'+str(time.time_ns()),'action':action,**data})
 def fixture(self):
  ids=['P001','P002','P003'];locked={p:'SYNTHETIC '+p for p in ids}
  snapshot=self.root/'snapshot.json';snapshot.write_text(json.dumps({'panel_ids':ids,'locked_scripts':locked}))
  ref={'path':snapshot.name,'sha256':file_hash(snapshot)}
  ratios=[{'panel_id':p,'frame_ratio':r,'frame_ratio_reason':'SYNTHETIC crop '+p} for p,r in zip(ids,['9:16','3:4','4:5'])]
  plan=self.root/'ratios.json';plan.write_text(json.dumps({'policy':'content_balanced_ratios_v1','book_id':'BOOK','episode_id':'E001','source_snapshot':ref,'panel_ids':ids,'panels':ratios}))
  rows=[]
  for p,r in zip(ids,ratios):
   shot={'panel_id':p,'locked_script':locked[p],**r};execution={'prompt':'SYNTHETIC '+p}
   rows.append({'panel_id':p,'shot':shot,'execution':execution,'packet_header':{'book_id':'BOOK','episode_id':'E001'},'render_mode':'preserved_import','import_panel_key':fingerprint({**shot,**execution})})
  return {'episode_id':'E001','source_snapshot':ref,'shared':{},'shot_header':{'book_id':'BOOK','episode_id':'E001'},'frame_ratio_plan':{'path':plan.name,'sha256':file_hash(plan)},'scenes':[{'scene_id':'scene','panel_ids':ids}]},rows
 def test_unmarked_frozen_run_is_not_enabled(self):
  self.assertIsNotNone(Host,'preparation host implementation missing')
  with self.assertRaisesRegex(ValueError,'POLICY'):Host(self.root)
 def test_request_retry_is_durable_and_conflict_fails_closed(self):
  h=self.host();r={'request_id':'same','action':'status'};first=h.handle(r)
  self.assertEqual(h.handle(r),first)
  changed=h.handle({**r,'action':'plan'});self.assertEqual(changed['status'],'HOLD');self.assertIn('CONFLICT',changed['errors'][0])
 def test_initial_model_work_needs_real_host_and_preserves_identity(self):
  h=self.host();plan=self.request(h,'plan');t=plan['ready'][0]
  self.assertEqual(t['kind'],'semantic_authoring')
  claim=self.request(h,'claim',task_id=t['task_id']);self.assertEqual(claim['wait_reason'],'HOST_NEEDED')
  attached=self.request(h,'attach-host',task_id=t['task_id'],host_id='native-real-123',operation_id=claim['operation_id'])
  self.assertEqual(attached['host_id'],'native-real-123');self.assertEqual(attached['status'],'RUNNING')
 def test_configuration_requires_real_header_refs_and_full_ratio_plan(self):
  h=self.host();config,rows=self.fixture();bad={**config};bad.pop('frame_ratio_plan')
  result=self.request(h,'configure-episode',**bad);self.assertEqual(result['status'],'HOLD')
  result=self.request(h,'configure-episode',**config);self.assertEqual(result['status'],'CONFIGURED')
  tasks=self.request(h,'plan')['ready'];self.assertTrue(any(t['kind']=='shot_fragment' for t in tasks))
  status=self.request(h,'status')['episodes']['E001'];self.assertEqual(status['pending_panel_ids'],['P001','P002','P003'])
 def test_inbox_advances_derivation_without_a_root_model_poll(self):
  h=self.host();config,rows=self.fixture();self.request(h,'configure-episode',**config)
  fragment={'operation_id':'fragment-one','base_revision':0,'shared_version':0,'row_versions':{'P002':0},'consumed_rows':{},'panels':[rows[1]]}
  queued=self.request(h,'submit-fragments',episode_id='E001',fragment=fragment);self.assertEqual(queued['status'],'QUEUED')
  self.assertTrue(h.wait_idle(12))
  current=self.request(h,'status')['episodes']['E001'];self.assertEqual(current['pending_panel_ids'],['P001','P003'])
  self.assertEqual(current['collected_panel_ids'],['P002'])
  record=current['panels']['P002'];self.assertTrue(Path(record['package_manifest']['path']).is_file());self.assertEqual(record['technical_status'],'HOLD')
  self.assertFalse((self.root/'.preparation-host/episodes/E001/full-authoring.json').exists())
 def test_bad_fragment_does_not_stop_later_inbox_work(self):
  h=self.host();config,rows=self.fixture();self.request(h,'configure-episode',**config)
  for i in [0,1]:
   row=copy.deepcopy(rows[i]);row['shot']['locked_script']='invented' if i==0 else row['shot']['locked_script']
   self.request(h,'submit-fragments',episode_id='E001',fragment={'operation_id':'f'+str(i),'base_revision':0,'shared_version':0,'row_versions':{row['panel_id']:0},'panels':[row]})
  self.assertTrue(h.wait_idle(12));current=self.request(h,'status')['episodes']['E001'];self.assertEqual(current['collected_panel_ids'],['P002']);self.assertTrue(self.request(h,'status')['inbox_errors'])
 def test_seal_pending_returns_exact_missing_rows_and_never_succeeds(self):
  h=self.host();config,rows=self.fixture();self.request(h,'configure-episode',**config)
  result=self.request(h,'seal',episode_id='E001');self.assertEqual(result['status'],'HOLD');self.assertEqual(result['missing_panel_ids'],['P001','P002','P003'])
 def test_malformed_direct_inbox_preserves_exact_raw_bytes(self):
  h=self.host();original=b'{"unfinished":';path=h.folder/'inbox/malformed.json';path.write_bytes(original);h.wake.set();self.assertTrue(h.wait_idle(10))
  error=json.loads((h.folder/'errors/malformed.json').read_text());saved=Path(error['raw_reference']['path'])
  self.assertEqual(saved.read_bytes(),original);self.assertEqual(error['raw_reference']['sha256'],file_hash(saved))
 def test_text_intake_rejects_source_changed_after_read(self):
  source=self.root/'source.txt';source.write_text('OLD factual text');config=self.root/'config.json';config.write_text(json.dumps({'inputs':{'script_path':str(source)}}));self.marker()
  marker=self.root/'00_任务协调/preparation-host.json';value=json.loads(marker.read_text());value['config']=str(config);marker.write_text(json.dumps(value));original=Path.read_bytes
  def changed(path):
   raw=original(path)
   if path==source.resolve():path.write_text('NEW changed text')
   return raw
  with patch.object(Path,'read_bytes',changed):
   with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED_DURING_PARSE'):Host(self.root)
  self.assertFalse((self.root/'.preparation-host/source-evidence.json').exists())
 def test_public_invoke_guard_request_id_never_replays_permission(self):
  from test_asset_runtime import AssetTests
  from platform_io import atomic_json
  fixture=AssetTests();fixture.setUp();self.addCleanup(fixture.doCleanups);root=fixture.root
  state=root/'00_输入审计/生产流程.json';state.parent.mkdir();atomic_json(state,{'book_id':'BOOK','episode_id':'E001','visual_basis':fixture.basis})
  atomic_json(root/'00_任务协调/preparation-host.json',{'policy':'preparation_scheduler_v1','book_id':'BOOK','episode_ids':['E001'],'states':[str(state)]})
  h=Host(root);self.addCleanup(h.close)
  registered=self.request(h,'register-assets',definitions=[fixture.definition]);task=registered['image_task_ids'][0]
  channel=fixture.put('channel.json',{'source_kind':'observed_native_channel','source_locator':'synthetic://native-ready','tool':'image_gen.imagegen','ready':True,'host_id':'synthetic-channel'})
  prepared=self.request(h,'asset-prepare-invoke',task_id=task,channel={'host_id':'synthetic-channel','evidence':channel});self.assertIn('job',prepared,prepared)
  request={'request_id':'one-shot','action':'asset-invoke-guard','task_id':task};first=h.handle(request);self.assertTrue(first.get('invoke_allowed'),first)
  replay=h.handle(request);self.assertEqual(replay['status'],'ASSET_INVOKE_OUTCOME_UNKNOWN');self.assertFalse(replay['invoke_allowed'])
 def test_incoming_fragment_is_saved_even_when_runtime_is_paused(self):
  h=self.host();config,rows=self.fixture();self.request(h,'configure-episode',**config)
  fragment={'operation_id':'late-save','base_revision':0,'shared_version':0,'row_versions':{'P001':0},'panels':[rows[0]]}
  with patch.object(h,'_budget',side_effect=ValueError('RUNTIME_CLOCK_PAUSED')):
   result=self.request(h,'submit-fragments',episode_id='E001',fragment=fragment);self.assertEqual(result['status'],'QUEUED');self.assertTrue(h.wait_idle(10))
  files=list((h.folder/'errors').glob('*.json'));self.assertEqual(json.loads(files[0].read_text())['request']['fragment'],fragment)
  self.request(h,'reconcile');self.assertTrue(h.wait_idle(10));self.assertEqual(h._config('E001')['panels']['P001']['row_version'],1)
 def test_compact_status_is_incremental_and_contains_no_prompt_payloads(self):
  h=self.host();config,rows=self.fixture();self.request(h,'configure-episode',**config)
  result=h.handle({'request_id':'compact','action':'status'});self.assertNotIn('tasks',result['scheduler']);self.assertNotIn('panels',result['episodes']['E001'])
  same=h.handle({'request_id':'compact-next','action':'status','after_revision':result['revision']});self.assertEqual(same['status'],'UNCHANGED')
 def test_compact_status_excludes_historical_inflight_curve(self):
  h=self.host();compact=self.request(h,'status',details=False)
  self.assertNotIn('inflight_curve',compact['scheduler']['metrics'])
  self.assertIn('inflight_curve',h.status()['scheduler']['metrics'])
 def test_bootstrap_parses_actual_workbook_once_before_native_semantics(self):
  from openpyxl import Workbook
  book=Workbook();book.active.append(['E001','P001','SYNTHETIC source']);source=self.root/'source.xlsx';book.save(source)
  config=self.root/'config.json';config.write_text(json.dumps({'inputs':{'script_path':str(source)}}));self.marker()
  marker=self.root/'00_任务协调/preparation-host.json';value=json.loads(marker.read_text());value['config']=str(config);marker.write_text(json.dumps(value))
  h=Host(self.root);self.addCleanup(h.close);tasks=h.scheduler.status()['tasks']
  self.assertIn('batch:source-parse',tasks);self.assertEqual(tasks['batch:source-parse']['status'],'COMMITTED')
  semantic=tasks['E001:semantic'];self.assertIn('batch:source-parse',semantic['dependencies'])
  evidence=next(r for r in semantic['input_refs'] if r['path'].endswith('source-evidence.json'));raw=json.loads(Path(evidence['path']).read_text())
  self.assertEqual(raw['raw']['sheets'][0]['rows'][0][2]['value'],'SYNTHETIC source')
 def test_unknown_native_capacity_admits_no_model_tasks(self):
  h=self.host();result=h.handle({'request_id':'no-capacity','action':'plan'});self.assertEqual(result['host_adapter_status'],'HOST_NEEDED');self.assertEqual(result['ready'],[])
 def test_configuration_recovers_commit_before_semantic_ack(self):
  h=self.host();config,rows=self.fixture();original=h._finish_task
  with patch.object(h,'_finish_task',side_effect=OSError('synthetic lost acknowledgement')):
   self.assertEqual(self.request(h,'configure-episode',**config)['status'],'HOLD')
  result=self.request(h,'configure-episode',**config);self.assertEqual(result['status'],'CONFIGURED',result)
  tasks=h.scheduler.status()['tasks'];self.assertEqual(tasks['E001:semantic']['status'],'COMMITTED');self.assertTrue(any(t['kind']=='shot_fragment' for t in tasks.values()))
 def test_reconcile_replays_domain_commit_after_local_io_failure(self):
  h=self.host();config,rows=self.fixture();self.request(h,'configure-episode',**config);original=h._finish_task
  def fail(task,*args):
   if ':derive:' in task:raise OSError('synthetic crash after domain commit')
   return original(task,*args)
  with patch.object(h,'_finish_task',side_effect=fail):
   self.request(h,'submit-fragments',episode_id='E001',fragment={'operation_id':'crash','base_revision':0,'shared_version':0,'row_versions':{'P002':0},'panels':[rows[1]]});self.assertTrue(h.wait_idle(10))
  self.assertEqual(len(self.request(h,'status')['inbox_errors']),1)
  self.request(h,'reconcile',retry_errors=True);self.assertTrue(h.wait_idle(10));status=self.request(h,'status')
  self.assertEqual(status['inbox_errors'],[]);self.assertEqual(status['episodes']['E001']['collected_panel_ids'],['P002'])
  task=next(t for t in status['scheduler']['tasks'].values() if t['kind']=='derive');self.assertEqual(task['status'],'COMMITTED')
 def test_configuration_cannot_target_an_external_frozen_state(self):
  h=self.host();config,rows=self.fixture();external=self.root.parent/(self.root.name+'-frozen.json')
  external.write_text(json.dumps({'book_id':'BOOK','episode_id':'E001'}));self.addCleanup(external.unlink)
  before=external.read_bytes();result=self.request(h,'configure-episode',**config,state_path=str(external))
  self.assertEqual(result['status'],'HOLD');self.assertIn('STATE_PATH_OUTSIDE_DESCRIPTOR',result['errors'][0]);self.assertEqual(external.read_bytes(),before)
 def test_fast_panel_is_collected_before_slow_same_fragment_returns(self):
  import panel_derivation
  h=self.host();config,rows=self.fixture();self.request(h,'configure-episode',**config)
  original=panel_derivation.render
  def render(*args):
   if args[1]['panel_id']=='P001':
    deadline=time.monotonic()+6
    while time.monotonic()<deadline:
     if 'P002' in h._config('E001')['panels']:break
     time.sleep(.01)
    else:raise ValueError('FAST_PANEL_NOT_COLLECTED_WHILE_SLOW_RENDERING')
   return original(*args)
  with patch.object(panel_derivation,'render',render):
   self.request(h,'submit-fragments',episode_id='E001',fragment={'operation_id':'stream','base_revision':0,'shared_version':0,'row_versions':{'P001':0,'P002':0},'panels':rows[:2]})
   self.assertTrue(h.wait_idle(15));status=self.request(h,'status')
  self.assertEqual(status['inbox_errors'],[],[json.loads(Path(p).read_text())['error'] for p in status['inbox_errors']])
  self.assertEqual(status['episodes']['E001']['collected_panel_ids'],['P001','P002'])
 def real_flow(self,measured=None,authority=False,task=False,fresh_a=False,a_phase=True):
  from test_exception_preparation import Flow
  from panel_source import import_state,expand
  fixture=Flow();fixture.setUp();self.addCleanup(fixture.doCleanups)
  f=fixture.f
  if task:f.scope_task()
  self.root=f.template;folder=f.base/'00_任务协调';folder.mkdir()
  (folder/'preparation-host.json').write_text(json.dumps({'policy':'preparation_scheduler_v1','book_id':f.state['book_id'],'episode_ids':['E000'],'states':[str(fixture.path)]}))
  source=import_state(fixture.path);fresh=json.loads(fixture.path.read_text());fresh.update(preparation_scheduler_policy='preparation_scheduler_v1',frame_ratio_policy='content_balanced_ratios_v1',frame_ratio_plan=None,source_script=None,source_snapshot=None,shot_manifest=None,semantic_audit=None,batch_plan=None,panels=[]);
  if fresh_a:fresh.update(gates={},approval_index=None,generation_packages={},visual_basis=None)
  fixture.path.write_text(json.dumps(fresh))
  h=Host(f.base);self.addCleanup(h.close);ids=source['panel_ids'];ratios=['9:16','3:4','4:5','9:16'];ratio_rows=[]
  for row,ratio in zip(source['panels'],ratios):
   row['shot'].update(frame_ratio=ratio,frame_ratio_reason='SYNTHETIC approved crop '+row['panel_id'])
   from frame_ratio_plan import execution_block
   block=execution_block(row['shot']);row['shot']['frame_ratio_execution_block']=block
   for key in ('prompt','camera_execution_block'):
    if key in row['shot']:row['shot'][key]=row['shot'][key].replace('画幅比例：9:16','画幅比例：'+ratio)
   row['shot']['prompt']+='\n'+block
   row['import_panel_key']=fingerprint({**expand(row['shot'],source['shared']),**expand(row['execution'],source['shared'])})
   ratio_rows.append({k:row['shot'][k] for k in ('panel_id','frame_ratio','frame_ratio_reason')})
  source_ref=f.state['source_snapshot'];plan=self.root/'host-ratio-plan.json'
  plan.write_text(json.dumps({'policy':'content_balanced_ratios_v1','book_id':f.state['book_id'],'episode_id':'E000','source_snapshot':source_ref,'panel_ids':ids,'panels':ratio_rows}))
  grant=None
  if authority:
   path=self.root/'host-delegation.json';path.write_text(json.dumps({'policy':'user_delegation_v1','status':'AUTHORIZED','source_kind':'user_message','source_locator':'SYNTHETIC_NOT_REAL_USER','quote':'SYNTHETIC scoped adoption','constraints':['SYNTHETIC exact inputs only'],'book_id':f.state['book_id'],'episode_ids':['E000'],'panel_ids':{'E000':ids},'phases':(['visual_basis'] if a_phase else [])+['shot_design','generation_package']}));grant={'path':path.name,'sha256':file_hash(path)}
  result=self.request(h,'configure-episode',state_updates={'visual_basis':f.state['visual_basis']} if fresh_a else {},authority=grant,reviewer='SYNTHETIC delegated operator' if authority else None,episode_id='E000',source_script=f.state['source_script'],source_snapshot=source_ref,shared=source['shared'],shot_header=source['shot_header'],frame_ratio_plan={'path':plan.name,'sha256':file_hash(plan)},scenes=[{'scene_id':'synthetic','panel_ids':ids,**({'measured_seconds_per_panel':measured} if measured else {})}])
  self.assertEqual(result['status'],'CONFIGURED',result)
  return fixture,h,source
 def test_real_exception_fixture_streams_and_seals_full_existing_contract(self):
  fixture,h,source=self.real_flow()
  for i in [2,0,3,1]:
   row=source['panels'][i];self.request(h,'submit-fragments',episode_id='E000',fragment={'operation_id':'real-'+str(i),'base_revision':0,'shared_version':0,'row_versions':{row['panel_id']:0},'panels':[row]})
  self.assertTrue(h.wait_idle(30));status=self.request(h,'status');self.assertEqual(status['inbox_errors'],[],[json.loads(Path(p).read_text())['error'] for p in status['inbox_errors']])
  panels=status['episodes']['E000']['panels'];self.assertEqual(len(panels),4)
  self.assertTrue(all(p['technical_status']=='TECHNICALLY_READY' for p in panels.values()),[json.loads(Path(p).read_text())['result']['scope_result'].get('input_errors') for p in (h.folder/'done').glob('*.json')])
  result=self.request(h,'seal',episode_id='E000',operation_id='seal-real')
  self.assertEqual(result['status'],'HOLD',result);self.assertTrue(result.get('missing_keys'),result)
  self.assertEqual(result['domain_status'],'PREPRODUCTION_INPUTS_READY',result)
  self.assertEqual(result['derivation_metrics']['compiled_panels'],0,result)
  state=json.loads(fixture.path.read_text());audit=json.loads((self.root/state['semantic_audit']['path']).read_text())
  self.assertTrue(all(p['execution_review']['review_performed'] is False for p in audit['panels']))
  self.assertTrue(all('reused_from' in p['execution_review'] for p in audit['panels']))
 def basis_observation(self,fixture,source):
  from input_dependencies import references
  before=json.loads(fixture.path.read_text());basis=json.loads((fixture.f.template/before['visual_basis']['path']).read_text())
  return {'policy':'visual_basis_observation_v1','status':'PASS','source_kind':'observed_visual_basis_review','source_locator':'SYNTHETIC actual A review','reviewer':'SYNTHETIC actual A observer','observed_at':'2026-11-08T12:00:00+08:00','evidence':'SYNTHETIC actual source assets and basis reviewed once','book_id':before['book_id'],'episode_id':'E000','panel_ids':source['panel_ids'],'source_script':before['source_script'],'source_snapshot':before['source_snapshot'],'visual_basis':before['visual_basis'],'checked_references':[dict(path=r['path'],sha256=r['sha256']) for r in references([basis])]}
 def test_basis_observation_cas_rejects_current_basis_changed_during_decision(self):
  import review_policy
  fixture,h,source=self.real_flow(authority=True,fresh_a=True);observation=self.basis_observation(fixture,source);original=review_policy.delegated_decisions
  def change(*args,**kw):
   proof=original(*args,**kw);state=json.loads(fixture.path.read_text());basis=json.loads((fixture.f.template/state['visual_basis']['path']).read_text());basis['synthetic_revision']='changed during actual review';path=fixture.f.template/'racing-basis.json';path.write_text(json.dumps(basis));state['visual_basis']={'path':path.name,'sha256':file_hash(path)};fixture.path.write_text(json.dumps(state));return proof
  with patch.object(review_policy,'delegated_decisions',side_effect=change):
   with self.assertRaisesRegex(ValueError,'STATE_CHANGED'):h._basis_observation({'episode_id':'E000','operation_id':'racing-A','observation':observation})
  self.assertIsNone(json.loads(fixture.path.read_text())['approval_index'])
 def test_basis_result_replay_rejects_individually_revoked_A_decision(self):
  from authority_updates import update_approvals
  fixture,h,source=self.real_flow(authority=True,fresh_a=True);observation=self.basis_observation(fixture,source);request={'episode_id':'E000','operation_id':'revoked-A','observation':observation}
  result=h._basis_observation(request)
  update_approvals(fixture.path,file_hash(fixture.path),revoke=[{'approval':result['decision'],'message':{'source_kind':'user_message','source_locator':'SYNTHETIC scoped revocation','quote':'SYNTHETIC revoke this A decision only'}}])
  with self.assertRaisesRegex(ValueError,'REVOKED'):h._basis_observation(request)
  self.assertFalse(h._basis_ready('E000'))
 def test_basis_adoption_recovers_after_authority_commit_before_result_receipt(self):
  import preparation_host
  fixture,h,source=self.real_flow(authority=True,fresh_a=True);observation=self.basis_observation(fixture,source);original=preparation_host.atomic_json
  def crash(path,value):
   if Path(path).name=='result.json' and 'basis-reviews' in str(path):raise OSError('synthetic result acknowledgement lost after A commit')
   return original(path,value)
  with patch.object(preparation_host,'atomic_json',side_effect=crash):
   self.request(h,'submit-basis-observation',episode_id='E000',operation_id='crash-A',observation=observation);self.assertTrue(h.wait_idle(10))
  state=json.loads(fixture.path.read_text());self.assertTrue(state['approval_index']);revision=state['authority_revision']
  self.request(h,'reconcile');self.assertTrue(h.wait_idle(10));state=json.loads(fixture.path.read_text());self.assertEqual(state['authority_revision'],revision)
  self.assertEqual(self.request(h,'status')['inbox_errors'],[]);task=next(t for t in h.scheduler.status()['tasks'].values() if t['kind']=='basis_observation');self.assertEqual(task['status'],'COMMITTED')
 def test_basis_observation_requires_visual_phase_delegation(self):
  fixture,h,source=self.real_flow(authority=True,fresh_a=True,a_phase=False);observation=self.basis_observation(fixture,source)
  self.request(h,'submit-basis-observation',episode_id='E000',operation_id='no-A-authority',observation=observation);self.assertTrue(h.wait_idle(10))
  self.assertIsNone(json.loads(fixture.path.read_text())['approval_index']);errors=self.request(h,'status')['inbox_errors'];self.assertTrue(errors)
  self.assertIn('授权',json.loads(Path(errors[0]).read_text())['error'])
 def test_old_basis_observation_cannot_approve_changed_basis_or_source(self):
  fixture,h,source=self.real_flow(authority=True,fresh_a=True);observation=self.basis_observation(fixture,source);original=json.loads(fixture.path.read_text())
  for field in ('visual_basis','source_snapshot'):
   state=copy.deepcopy(original);old=json.loads((fixture.f.template/state[field]['path']).read_text());old['synthetic_revision']='new factual version';path=fixture.f.template/(field+'-new.json');path.write_text(json.dumps(old));state[field]={'path':path.name,'sha256':file_hash(path)};fixture.path.write_text(json.dumps(state))
   self.request(h,'submit-basis-observation',episode_id='E000',operation_id='stale-'+field,observation=observation);self.assertTrue(h.wait_idle(10))
   self.assertIsNone(json.loads(fixture.path.read_text())['approval_index'])
  errors=self.request(h,'status')['inbox_errors'];self.assertEqual(len(errors),2);self.assertTrue(all('BASIS_OBSERVATION_SCOPE_OR_BYTES_CHANGED' in json.loads(Path(p).read_text())['error'] for p in errors))
 def test_public_host_seal_release_publish_and_current_receive(self):
  import handoff_zip,handoff_delivery,delivery_contract,comic_start
  from types import SimpleNamespace
  fixture,h,source=self.real_flow(authority=True,task=True,fresh_a=True);f=fixture.f
  before=json.loads(fixture.path.read_text());self.assertEqual(before['gates'],{});self.assertIsNone(before['approval_index'])
  observation=self.basis_observation(fixture,source)
  self.request(h,'submit-basis-observation',episode_id='E000',operation_id='real-A-observation',observation=observation);self.assertTrue(h.wait_idle(10))
  after=json.loads(fixture.path.read_text());self.assertTrue(after.get('approval_index'),self.request(h,'status'))
  self.request(h,'submit-fragments',episode_id='E000',fragment={'operation_id':'complete-public','base_revision':0,'shared_version':0,'row_versions':{p['panel_id']:0 for p in source['panels']},'panels':source['panels']});self.assertTrue(h.wait_idle(15))
  settings={'package_id':'SYNTHETIC_HOST_PUBLIC','assembly_destination':str(f.base/'host-package'),'runtime_manifest':{'path':str(f.package/'runtime/manifest.json'),'sha256':file_hash(f.package/'runtime/manifest.json')},'candidate_zip':str(f.base/'host-candidate.zip')}
  missing=self.request(h,'seal',episode_id='E000',operation_id='seal-missing-runtime',package_id=settings['package_id'],assembly_destination=settings['assembly_destination'],runtime_manifest={'path':str(f.base/'missing-runtime.json'),'sha256':'0'*64})
  self.assertEqual(missing['status'],'HOLD',missing)
  first=self.request(h,'seal',episode_id='E000',operation_id='seal-public',**settings)
  self.assertEqual(first.get('missing_keys'),['export_authorization'],first)
  sealed_files={p:file_hash(p) for p in (f.template/'.preparation-pipeline/sealed').rglob('*') if p.is_file() and p.name in {'semantic-audit.json','scope-history.json','domain-receipt.json'}}
  state_hash=file_hash(fixture.path)
  package=Path(first['package_root']);index=handoff_zip.audit_index(package);approval=f.base/'host-export.json'
  approval.write_text(json.dumps({'status':'APPROVED','source_kind':'user_message','source_locator':'SYNTHETIC_NOT_REAL_USER','quote':'SYNTHETIC exact final input content export','authorization_mode':'approved_inputs_content_export_v1','package_id':index['package_id'],'approved_input_digest':handoff_delivery.input_review(package,index)['approved_input_digest']}))
  released=self.request(h,'seal',episode_id='E000',operation_id='seal-public-release',export_authorization=str(approval),output=str(f.base/'formal-host.zip'),**settings)
  self.assertEqual(released['status'],'RELEASED_DIRECT_DELIVERY_ZIP',released)
  self.assertEqual(file_hash(fixture.path),state_hash);self.assertTrue(all(file_hash(p)==sha for p,sha in sealed_files.items()))
  self.assertTrue(all(t['status'] in {'COMMITTED','SUPERSEDED','STOPPED'} for t in h.scheduler.status()['tasks'].values() if t['kind']=='handoff_assembly_plan'))
  contract=delivery_contract.initialize(f.base/'host-delivery','preparation',[fixture.path])
  published=self.request(h,'publish',source_zip=released['zip'],contract=contract['path'],output=str(f.base/'published-host'))
  self.assertEqual(published['status'],'DELIVERY_READY',published)
  with patch.object(handoff_zip.shutil,'disk_usage',return_value=SimpleNamespace(free=10*1024**3)):
   received=comic_start.receive(published['artifacts'][0]['path'],runtime_limit_seconds=None,output=f.base/'host-received',eager_audit=True,audit_timeout=30)
  self.assertEqual(received['status'],'READY_FOR_PRODUCTION_ROUTING',received);self.assertEqual(received['image_calls'],0)
 def test_actual_accepted_host_span_repartitions_only_unclaimed_scene_tasks(self):
  fixture,h,source=self.real_flow(measured=90);tasks=[t for t in h.scheduler.status()['tasks'].values() if t['kind']=='shot_fragment'];first=tasks[0]
  self.request(h,'plan',capacities={'model':4});self.request(h,'claim',task_id=first['task_id'])
  with patch.object(h.scheduler,'clock',side_effect=lambda:time.time()-360):self.request(h,'attach-host',task_id=first['task_id'],host_id='SYNTHETIC-native-duration')
  for i in [0,1]:
   row=source['panels'][i];self.request(h,'submit-fragments',episode_id='E000',task_id=first['task_id'],fragment={'operation_id':'tune-'+str(i),'base_revision':0,'shared_version':0,'row_versions':{row['panel_id']:0},'panels':[row]})
  self.assertTrue(h.wait_idle(15));current=h.scheduler.status()['tasks'];self.assertEqual(current[first['task_id']]['status'],'COMMITTED')
  self.assertEqual(current[tasks[1]['task_id']]['status'],'SUPERSEDED')
  adapted=[t for t in current.values() if ':adaptive:' in t['task_id']];self.assertEqual([len(t['payload']['panel_ids']) for t in adapted],[1,1])
 def test_observations_automatically_settle_assigned_author_and_risk_tasks(self):
  import preparation_scope
  fixture,h,source=self.real_flow();task=next(t for t in h.scheduler.status()['tasks'].values() if t['kind']=='shot_fragment')
  self.request(h,'claim',task_id=task['task_id']);self.request(h,'attach-host',task_id=task['task_id'],host_id='SYNTHETIC-author')
  original=preparation_scope.technical_inputs
  def inputs(*args,**kw):
   value=original(*args,**kw)
   if args[2]['panel_id']=='P001':value['preparation_requirements']=[{'id':'contact:0','expected':{'kind':'contact'}}]
   return value
  with patch.object(preparation_scope,'technical_inputs',side_effect=inputs):
   self.request(h,'submit-fragments',episode_id='E000',task_id=task['task_id'],fragment={'operation_id':'risk-author','base_revision':0,'shared_version':0,'row_versions':{p['panel_id']:0 for p in source['panels']},'panels':source['panels']});self.assertTrue(h.wait_idle(15))
  self.assertEqual(h.scheduler.status()['tasks'][task['task_id']]['status'],'RUNNING')
  risk=next(t for t in h.scheduler.status()['tasks'].values() if t['kind']=='risk_observation')
  self.request(h,'submit-observations',episode_id='E000',operation_id='actual-observation',reviewer='SYNTHETIC real observer',observations={'P001':{'evidence':'SYNTHETIC contact observed once','issues':[]}})
  self.assertTrue(h.wait_idle(10));current=h.scheduler.status()['tasks']
  self.assertEqual(current[task['task_id']]['status'],'COMMITTED');self.assertEqual(current[risk['task_id']]['status'],'COMMITTED')
  self.assertEqual(h._config('E000')['panels']['P001']['review']['reviewer'],'SYNTHETIC real observer')
 def test_saved_business_receipt_is_replayed_without_domain_reexecution(self):
  h=self.host();t=self.request(h,'plan')['ready'][0];claim=self.request(h,'claim',task_id=t['task_id'])
  out=self.root/'saved.json';out.write_text('{}');refs=[{'path':str(out),'sha256':file_hash(out)}]
  receipt=h.save_business_receipt(t['task_id'],refs,{'saved':True})
  self.request(h,'reconcile');task=self.request(h,'status')['scheduler']['tasks'][t['task_id']]
  self.assertEqual(task['status'],'COMMITTED');self.assertEqual(task['business_receipt'],receipt)

if __name__=='__main__':unittest.main()
