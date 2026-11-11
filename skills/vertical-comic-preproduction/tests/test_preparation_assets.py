"""Actual local ledgers/resources and explicit synthetic tool/observer evidence."""
import base64,copy,json,sys,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import test_asset_runtime as fixture
from test_machine_resources import normal_sample
from platform_io import atomic_json
from input_dependencies import fingerprint
from codex_reference_contract import digest,read_json
from preparation_scheduler import Scheduler
from machine_resources import Coordinator
import asset_runtime
try:
    from preparation_assets import Assets
except ImportError:
    Assets=None


class LocalHost:
    def __init__(self,root,states,resources):
        self.root=root;self.folder=root/'.preparation-host';self.folder.mkdir()
        self.lock=threading.RLock();self.wake=threading.Event();self.closed=False
        self.descriptor={'book_id':'BOOK','episode_ids':['E001'],'states':states}
        self.scheduler=Scheduler(root/'00_任务协调/preparation-scheduler')
        self.epoch=self.scheduler.start_owner(['BOOK',['E001']])
        self.derivation=SimpleNamespace(resources=resources)
        self.stopped=False
    def epoch_guard(self):
        with self.lock:self.scheduler._owner(self.scheduler.status(),self.epoch)
        return True
    def _budget(self,action,preserve=False):
        if self.stopped and not preserve:raise ValueError('CLOCK_STOPPED')
    def _finish_task(self,task_id,outputs,result):
        with self.lock:
            task=self.scheduler.status()['tasks'][task_id]
            value={'policy':'preparation_business_receipt_v1','status':'COMMITTED','task_id':task_id,
                'operation_id':task['operation_id'],'output_refs':outputs,'result':result}
            p=self.folder/(fingerprint(task_id)+'.json');atomic_json(p,value)
            ref={'path':str(p),'sha256':digest(p)}
            self.scheduler.record_result(task_id,outputs,epoch=self.epoch)
            self.scheduler.commit(task_id,ref,epoch=self.epoch)
        return ref


class PreparationAssetsTests(unittest.TestCase):
    setUp_fixture=fixture.AssetTests.setUp
    put=fixture.AssetTests.put
    result=fixture.AssetTests.result
    def setUp(self):
        self.setUp_fixture()
        self.assertIsNotNone(Assets,'native asset scheduling bridge missing')
        basis=read_json(self.root/'basis.json');basis['asset_tasks'][0]['panel_ids']=['P001']
        self.spec['visual_basis']=self.put('basis.json',basis)
        self.definition=self.put('asset-definition.json',self.spec);self.job=asset_runtime.compile_job(self.root,self.definition)[0]
        state=self.root/'00_输入审计/生产流程.json';state.parent.mkdir()
        atomic_json(state,{'book_id':'BOOK','episode_id':'E001','visual_basis':self.spec['visual_basis']})
        atomic_json(self.root/'00_任务协调/preparation-host.json',{'policy':'preparation_scheduler_v1'})
        self.resources=Coordinator(self.root/'machine',probe=normal_sample)
        self.host=LocalHost(self.root,[{'path':str(state),'sha256':digest(state)}],self.resources)
        self.assets=Assets(self.host)
        self.state_path=state
    def action(self,action,**kw):return self.assets.handle(action,kw)
    def registered(self,definitions=None):
        out=self.action('register-assets',definitions=definitions or [self.definition])
        return out['image_task_ids'][0]
    def channel(self):
        ref=self.put('channel.json',{'source_kind':'observed_native_channel','source_locator':'synthetic://native-ready',
            'tool':'image_gen.imagegen','ready':True,'host_id':'synthetic-native-channel'})
        return {'host_id':'synthetic-native-channel','evidence':ref}
    def prepared(self):
        task=self.registered();out=self.action('asset-prepare-invoke',task_id=task,channel=self.channel())
        return task,out
    def captured(self,task,out):
        attempt=out['job']['attempt_id'];raw=self.root/('actual-return-'+attempt+'.json');raw.write_text(json.dumps({'image_url':'data:image/png;base64,'+base64.b64encode((self.root/'approved.png').read_bytes()).decode()}))
        request=self.put('actual-call-'+attempt+'.json',{'source_kind':'observed_tool_call','source_locator':'synthetic://tool-call',
            'attempt_id':attempt,'arguments':out['job']['arguments']})
        return self.action('asset-capture',task_id=task,raw_path=str(raw),request_evidence=request,response_source_locator='synthetic://tool-return')
    def saved(self):
        task,out=self.prepared();self.action('asset-invoke-guard',task_id=task)
        captured=self.captured(task,out)
        result=self.action('asset-register',task_id=task,capture_reference=captured['capture_reference'])
        return task,out,result
    def observation(self,review,image_hash,**changes):
        value={'policy':'asset_observation_v1','source_kind':'observed_image_review','source_locator':'synthetic://image-view',
            'reviewer':'synthetic-observer','observed_at':'2026-11-08T01:00:00Z','status':'PASS',
            'evidence':'Synthetic observer: full required view readable, no serious blank area.',
            'image_sha256':image_hash,'episode_id':'E001','asset_id':'VIEW','panel_ids':['P001']}
        value.update(changes)
        return self.put('observation.json',value)
    def approval(self,image_hash,**changes):
        value={'source_kind':'user_message','source_locator':'synthetic://adopt-message','quote':'Synthetic exact adoption authorization',
            'book_id':'BOOK','episode_ids':['E001'],'asset_ids':['VIEW'],'panel_ids':['P001'],'operations':['adopt'],
            'image_sha256':image_hash}
        value.update(changes)
        return self.put('adoption-authority.json',value)

    def test_register_schedules_exact_scoped_image_and_blocks_only_affected_panel(self):
        task=self.registered();row=self.host.scheduler.status()['tasks'][task]
        self.assertEqual(row['lane'],'image');self.assertEqual(self.assets.blocked_panels('E001'),['P001'])
        self.assertEqual(self.resources.status()['active']['image'],0)
        self.assertFalse(asset_runtime.ledger_path(self.root).exists())
    def test_missing_native_channel_does_not_allocate_or_submit(self):
        task=self.registered()
        with self.assertRaisesRegex(ValueError,'CHANNEL'):self.action('asset-prepare-invoke',task_id=task)
        self.assertEqual(self.resources.status()['active']['image'],0)
        self.assertFalse(asset_runtime.ledger_path(self.root).exists())
    def test_prepare_allocates_real_resource_and_final_guard_is_one_shot(self):
        task,out=self.prepared();self.assertTrue(out['ack']['invoke_allowed'])
        self.assertEqual(self.resources.status()['active']['image'],1)
        first=self.action('asset-invoke-guard',task_id=task);self.assertTrue(first['invoke_allowed'])
        again=self.action('asset-invoke-guard',task_id=task);self.assertFalse(again['invoke_allowed'])
        again=self.action('asset-prepare-invoke',task_id=task,channel=self.channel());self.assertFalse(again['ack']['invoke_allowed'])
        self.assertEqual(len(read_json(asset_runtime.ledger_path(self.root))['attempts']),1)
    def test_durable_register_releases_and_creates_review_with_actual_image(self):
        task,out,result=self.saved();self.assertEqual(self.resources.status()['active']['image'],0)
        rows=self.host.scheduler.status()['tasks'];self.assertEqual(rows[task]['status'],'COMMITTED')
        review=rows[result['review_task_ids'][0]]
        self.assertEqual(review['kind'],'asset_review');self.assertEqual(review['dependencies'],[task])
        self.assertTrue(any(ref['path'].endswith('.png') for ref in review['input_refs']))
        self.assertEqual(review['status'],'READY');self.assertEqual(self.assets.blocked_panels('E001'),['P001'])
    def test_register_failure_recovery_preserves_permit_and_never_resubmits(self):
        task,out=self.prepared();self.action('asset-invoke-guard',task_id=task);captured=self.captured(task,out)
        with patch.object(asset_runtime,'save',side_effect=OSError('injected ledger fault')):
            with self.assertRaises(OSError):self.action('asset-register',task_id=task,capture_reference=captured['capture_reference'])
        self.assertEqual(self.resources.status()['active']['image'],1)
        with patch.object(asset_runtime,'submit',side_effect=AssertionError('regenerate')):
            recovered=self.action('asset-recover',task_id=task)
            repeated=self.action('asset-recover',task_id=task)
        self.assertEqual(recovered['status'],'ASSET_REGISTERED');self.assertEqual(repeated['status'],'ASSET_REGISTERED')
        self.assertEqual(self.resources.status()['active']['image'],0)
        self.assertEqual(len(read_json(asset_runtime.ledger_path(self.root))['attempts']),1)
    def test_unknown_retains_real_permit_and_has_no_review_or_retry(self):
        task,out=self.prepared();self.action('asset-invoke-guard',task_id=task)
        evidence=self.result('RESULT_UNKNOWN')
        result=self.action('asset-register',task_id=task,outcome=evidence)
        self.assertEqual(result['status'],'ASSET_RESULT_UNKNOWN')
        self.assertEqual(self.resources.status()['active']['image'],1)
        self.assertFalse(any(t['kind']=='asset_review' for t in self.host.scheduler.status()['tasks'].values()))
        repeated=self.action('asset-prepare-invoke',task_id=task,channel=self.channel())
        self.assertFalse(repeated['ack']['invoke_allowed'])
    def test_noimage_requires_actual_confirmed_evidence_and_releases(self):
        task,out=self.prepared();self.action('asset-invoke-guard',task_id=task)
        bad=self.result('RESULT_UNKNOWN');bad['status']='CALL_FAILED'
        with self.assertRaisesRegex(ValueError,'uncertain'):self.action('asset-register',task_id=task,outcome=bad)
        self.assertEqual(self.resources.status()['active']['image'],1)
        result=self.action('asset-register',task_id=task,outcome=self.result('CALL_FAILED'))
        self.assertEqual(result['status'],'ASSET_CALL_FAILED');self.assertEqual(self.resources.status()['active']['image'],0)
    def test_clock_stop_still_saves_return_and_old_epoch_cannot_invoke(self):
        task,out=self.prepared();self.host.stopped=True
        with self.assertRaisesRegex(ValueError,'CLOCK_STOPPED'):self.action('asset-invoke-guard',task_id=task)
        captured=self.captured(task,out)
        result=self.action('asset-register',task_id=task,capture_reference=captured['capture_reference'])
        self.assertEqual(result['status'],'ASSET_REGISTERED')
        self.assertEqual(self.resources.status()['active']['image'],0)
    def test_owner_epoch_change_prevents_native_invocation(self):
        task,out=self.prepared()
        other=Scheduler(self.host.scheduler.root,liveness=lambda i:False)
        other.start_owner()
        with self.assertRaisesRegex(ValueError,'STALE_OWNER'):self.action('asset-invoke-guard',task_id=task)
        self.assertEqual(self.resources.status()['active']['image'],1)
    def test_real_observation_and_exact_authority_adopts_current_basis_then_unblocks(self):
        task,out,result=self.saved();review=result['review_task_ids'][0]
        image=read_json(asset_runtime.ledger_path(self.root))['attempts'][out['ack']['registration_id']]['output']
        self.host.scheduler.claim(review,epoch=self.host.epoch);self.host.scheduler.attach_host(review,'synthetic-observer',epoch=self.host.epoch)
        observation=self.observation(review,image['sha256']);approval=self.approval(image['sha256'])
        response=self.action('submit-asset-observations',task_id=review,observation=observation,adoption_authorization=approval)
        self.assertEqual(response['status'],'ASSET_ADOPTED');self.assertEqual(self.assets.blocked_panels('E001'),[])
        state=read_json(self.state_path);basis=read_json(self.root/state['visual_basis']['path']);row=basis['asset_tasks'][0]
        self.assertEqual(row['reference']['sha256'],image['sha256'])
        self.assertEqual(row['review']['reviewer'],'synthetic-observer')
        self.assertTrue(self.host.wake.is_set());self.assertEqual(self.host.scheduler.status()['tasks'][review]['status'],'COMMITTED')
    def test_observation_does_not_expand_panel_scope_or_auto_approve(self):
        task,out,result=self.saved();review=result['review_task_ids'][0]
        image=read_json(asset_runtime.ledger_path(self.root))['attempts'][out['ack']['registration_id']]['output']
        self.host.scheduler.claim(review,epoch=self.host.epoch)
        observation=self.observation(review,image['sha256'],panel_ids=['P001','P002'])
        with self.assertRaisesRegex(ValueError,'SCOPE'):self.action('submit-asset-observations',task_id=review,observation=observation,adoption_authorization=self.approval(image['sha256']))
        self.assertEqual(self.assets.blocked_panels('E001'),['P001'])
        self.assertEqual(read_json(self.state_path)['visual_basis'],self.spec['visual_basis'])
    def test_adoption_checks_current_authority_and_state_before_change(self):
        task,out,result=self.saved();review=result['review_task_ids'][0]
        image=read_json(asset_runtime.ledger_path(self.root))['attempts'][out['ack']['registration_id']]['output']
        self.host.scheduler.claim(review,epoch=self.host.epoch)
        observation=self.observation(review,image['sha256']);approval=self.approval(image['sha256'],operations=['generate'])
        with self.assertRaisesRegex(ValueError,'AUTHORIZATION'):self.action('submit-asset-observations',task_id=review,observation=observation,adoption_authorization=approval)
        self.assertEqual(read_json(self.state_path)['visual_basis'],self.spec['visual_basis'])
        self.assertTrue(list((self.host.folder/'assets').rglob('*observation*.json')))
    def test_shared_content_deduplicates_tasks_without_expanding_review_scope(self):
        spec=copy.deepcopy(self.spec);spec['shared_asset']={'subject_id':'C','state_id':'normal','definition':{'view':'front'},
            'usage_basis':{'source_locator':'synthetic://same-usage'},'owner_episode_id':'E001','episode_ids':['E001']}
        first=self.put('shared1.json',spec);spec['attempt_id']='other';second=self.put('shared2.json',spec)
        result=self.action('register-assets',definitions=[first,second])
        self.assertEqual(len(result['image_task_ids']),1)
        self.assertEqual(len(result['targets']),1)
    def test_character_review_requires_actual_format_observation(self):
        basis=read_json(self.root/'basis.json');basis['asset_tasks'][0].update(character_id='C',costume_id='S')
        self.spec['visual_basis']=self.put('basis2.json',basis);self.definition=self.put('definition2.json',self.spec)
        state=read_json(self.state_path);state['visual_basis']=self.spec['visual_basis'];atomic_json(self.state_path,state)
        task,out,result=self.saved();review=result['review_task_ids'][0]
        image=read_json(asset_runtime.ledger_path(self.root))['attempts'][out['ack']['registration_id']]['output']
        self.host.scheduler.claim(review,epoch=self.host.epoch)
        observation=self.observation(review,image['sha256'])
        with self.assertRaisesRegex(ValueError,'FORMAT'):self.action('submit-asset-observations',task_id=review,observation=observation,adoption_authorization=self.approval(image['sha256']))

    def test_noimage_terminal_clears_scheduler_native_occupancy(self):
        task,out=self.prepared();self.action('asset-invoke-guard',task_id=task)
        self.action('asset-register',task_id=task,outcome=self.result('CALL_FAILED'))
        self.assertFalse(self.host.scheduler.status()['tasks'][task]['native_inflight'])

    def test_observation_adoption_replay_after_state_write_never_recreates_image(self):
        task,out,result=self.saved();review=result['review_task_ids'][0]
        image=read_json(asset_runtime.ledger_path(self.root))['attempts'][out['ack']['registration_id']]['output']
        self.host.scheduler.claim(review,epoch=self.host.epoch)
        observation=self.observation(review,image['sha256']);approval=self.approval(image['sha256'])
        with patch.object(self.host,'_finish_task',side_effect=OSError('lost domain acknowledgement')):
            with self.assertRaises(OSError):self.action('submit-asset-observations',task_id=review,observation=observation,adoption_authorization=approval)
        with patch.object(asset_runtime,'submit',side_effect=AssertionError('regenerate')):
            response=self.action('submit-asset-observations',task_id=review,observation=observation,adoption_authorization=approval)
        self.assertEqual(response['status'],'ASSET_ADOPTED');self.assertEqual(self.assets.blocked_panels('E001'),[])

    def test_unrelated_asset_adoption_does_not_reject_second_definition(self):
        basis=read_json(self.root/'basis.json');basis['identity_registry']={'C':{'face':'unchanged'}}
        basis['asset_tasks'].append({'asset_id':'OTHER','episode_id':'E001','panel_ids':['P002'],'source_basis':'synthetic second need'})
        shared_basis=self.put('two-basis.json',basis)
        auth=read_json(self.root/'authorization.json');auth['asset_ids'].append('OTHER');auth['max_inflight']=2
        authref=self.put('two-auth.json',auth)
        first=copy.deepcopy(self.spec);first['visual_basis']=shared_basis;first['authorization']=authref
        second=copy.deepcopy(first);second.update(asset_id='OTHER',attempt_id='OTHER-A1')
        firstdef=self.put('first-two.json',first);seconddef=self.put('second-two.json',second)
        state=read_json(self.state_path);state['visual_basis']=shared_basis;atomic_json(self.state_path,state)
        out=self.action('register-assets',definitions=[firstdef,seconddef]);tasks=self.host.scheduler.status()['tasks']
        firstid=next(i for i in out['image_task_ids'] if tasks[i]['payload']['targets'][0]['asset_id']=='VIEW')
        secondid=next(i for i in out['image_task_ids'] if tasks[i]['payload']['targets'][0]['asset_id']=='OTHER')
        prepared=self.action('asset-prepare-invoke',task_id=firstid,channel=self.channel());self.action('asset-invoke-guard',task_id=firstid)
        captured=self.captured(firstid,prepared);registered=self.action('asset-register',task_id=firstid,capture_reference=captured['capture_reference'])
        review=registered['review_task_ids'][0];self.host.scheduler.claim(review,epoch=self.host.epoch)
        image=registered['output'];observation=self.observation(review,image['sha256'])
        self.action('submit-asset-observations',task_id=review,observation=observation,adoption_authorization=self.approval(image['sha256']))
        # Re-registering B's original immutable definition and preparing it must remain valid.
        self.action('register-assets',definitions=[seconddef])
        prepared2=self.action('asset-prepare-invoke',task_id=secondid,channel=self.channel())
        self.assertTrue(prepared2['ack']['invoke_allowed'])
        # Changes to a consumed non-task/unknown basis field must still fence invocation.
        state=read_json(self.state_path);current=read_json(self.root/state['visual_basis']['path']);current['identity_registry']['C']['face']='changed'
        state['visual_basis']=self.put('changed-consumed-basis.json',current);atomic_json(self.state_path,state)
        with self.assertRaisesRegex(ValueError,'BASIS_CHANGED'):self.action('asset-invoke-guard',task_id=secondid)

    def test_new_shared_repair_can_replace_failed_review_blocker(self):
        spec=copy.deepcopy(self.spec);spec['shared_asset']={'subject_id':'C','state_id':'normal','definition':{'view':'front'},
            'usage_basis':{'source_locator':'synthetic://usage'},'owner_episode_id':'E001','episode_ids':['E001']}
        self.definition=self.put('shared-generation.json',spec)
        task,out,result=self.saved();oldreview=result['review_task_ids'][0]
        repair=copy.deepcopy(spec);repair.update(operation='repair',attempt_id='VIEW-A2',source_attempt_id='VIEW-A1',
            repair_evidence=self.put('repair-proof.json',{'source_attempt_id':'VIEW-A1','asset_id':'VIEW','episode_id':'E001','evidence':'synthetic necessary repair'}))
        newtask=self.registered([self.put('repair-generation.json',repair)])
        self.assertNotEqual(task,newtask)
        prepared=self.action('asset-prepare-invoke',task_id=newtask,channel=self.channel());self.action('asset-invoke-guard',task_id=newtask)
        captured=self.captured(newtask,prepared);saved=self.action('asset-register',task_id=newtask,capture_reference=captured['capture_reference'])
        review=saved['review_task_ids'][0];self.host.scheduler.claim(review,epoch=self.host.epoch)
        image=saved['output'];observation=self.observation(review,image['sha256'])
        self.action('submit-asset-observations',task_id=review,observation=observation,adoption_authorization=self.approval(image['sha256']))
        self.assertEqual(self.assets.blocked_panels('E001'),[])
        self.assertEqual(self.host.scheduler.status()['tasks'][oldreview]['status'],'SUPERSEDED')
        self.assertNotIn(oldreview,[t['task_id'] for t in self.host.scheduler.plan({'model':8})['ready']])
        from task_coordination import scheduler_projection
        self.assertEqual(scheduler_projection(self.root/'00_任务协调')['blockers'],[])

    def _direct_attempt(self,spec,status='CALL_FAILED',failure_kind='network'):
        definition=self.put('direct-'+spec['attempt_id']+'.json',spec)
        job=asset_runtime.compile_job(self.root,definition)[0]
        ack=asset_runtime.submit(self.root,job,epoch_guard=self.host.epoch_guard)
        if status=='CALL_FAILED':
            response=self.put('failure-'+spec['attempt_id']+'.json',{'source_kind':'observed_tool_error','source_locator':'synthetic://original-error',
                'attempt_id':spec['attempt_id'],'no_image_confirmed':True,'failure_kind':failure_kind,'error':'synthetic original network error'})
            result={'status':status,'attempt_id':spec['attempt_id'],'response_evidence':response}
        else:
            result=self.result(attempt=spec['attempt_id'])
        asset_runtime.save(self.root,ack['registration_id'],result)
        return definition

    def test_network_retry_limit_counts_sibling_attempts_across_definition_versions(self):
        spec=copy.deepcopy(self.spec);auth=read_json(self.root/'authorization.json');auth['max_asset_calls']=20
        spec['authorization']=self.put('large-auth.json',auth)
        self._direct_attempt(spec)
        for index in range(4):
            retry=copy.deepcopy(spec);retry.update(operation='retry',attempt_id='RETRY-'+str(index),source_attempt_id='VIEW-A1',
                retry_evidence=self.put('retry-proof-'+str(index)+'.json',{'source_attempt_id':'VIEW-A1','asset_id':'VIEW','episode_id':'E001','evidence':'synthetic known no image','no_image_confirmed':True}))
            self._direct_attempt(retry)
        retry['attempt_id']='RETRY-5'
        with self.assertRaisesRegex(ValueError,'RETRY_LIMIT'):self.action('register-assets',definitions=[self.put('retry-five.json',retry)])

    def test_quality_repair_limit_counts_sibling_attempts(self):
        spec=copy.deepcopy(self.spec);auth=read_json(self.root/'authorization.json');auth['max_asset_calls']=20
        spec['authorization']=self.put('large-auth.json',auth)
        self._direct_attempt(spec,status='GENERATED')
        repair=copy.deepcopy(spec);repair.update(operation='repair',attempt_id='REPAIR-1',source_attempt_id='VIEW-A1',
            repair_evidence=self.put('repair-proof.json',{'source_attempt_id':'VIEW-A1','asset_id':'VIEW','episode_id':'E001','evidence':'synthetic needed repair'}))
        self._direct_attempt(repair,status='CALL_FAILED')
        repair['attempt_id']='REPAIR-2'
        with self.assertRaisesRegex(ValueError,'QUALITY_REPAIR_LIMIT'):self.action('register-assets',definitions=[self.put('second-repair.json',repair)])

    def test_content_moderation_original_error_is_terminal_without_retry(self):
        spec=copy.deepcopy(self.spec);self._direct_attempt(spec,failure_kind='content_moderation')
        retry=copy.deepcopy(spec);retry.update(operation='retry',attempt_id='MODERATION-RETRY',source_attempt_id='VIEW-A1',
            retry_evidence=self.put('moderation-retry-proof.json',{'source_attempt_id':'VIEW-A1','asset_id':'VIEW','episode_id':'E001','evidence':'synthetic no image','no_image_confirmed':True}))
        with self.assertRaisesRegex(ValueError,'CONTENT_MODERATION_TERMINAL.*original network error'):
            self.action('register-assets',definitions=[self.put('moderation-retry.json',retry)])
        self.assertEqual(len(read_json(asset_runtime.ledger_path(self.root))['attempts']),1)

    def _revoke(self,approval):
        from authority_updates import proof_signature
        proof=read_json(self.root/approval['path'])
        report=self.put('revocation.json',{'policy':'approval_revocation_v1','status':'REVOKED','book_id':'BOOK','episode_id':'E001',
            'source_kind':'user_message','quote':'synthetic revoke','source_locator':'synthetic://revoke',
            'approval':approval,'proof_signature':proof_signature(proof)})
        state=read_json(self.state_path);state.update(authority_policy='locked_authority_v1',authority_revision=1,
            approval_revocations=[report],execution_mode='episode_async_v1',toolchain={'files':[{'path':'authority_updates.py'}]})
        atomic_json(self.state_path,state)

    def test_current_generation_revocation_fences_final_call(self):
        task,out=self.prepared();self._revoke(self.spec['authorization'])
        with self.assertRaisesRegex(ValueError,'APPROVAL_REVOKED'):self.action('asset-invoke-guard',task_id=task)
        self.assertEqual(self.resources.status()['active']['image'],1)

    def test_current_adoption_revocation_keeps_observation_and_scope_blocked(self):
        task,out,result=self.saved();review=result['review_task_ids'][0];self.host.scheduler.claim(review,epoch=self.host.epoch)
        image=result['output'];observation=self.observation(review,image['sha256']);approval=self.approval(image['sha256'])
        self._revoke(approval)
        with self.assertRaisesRegex(ValueError,'APPROVAL_REVOKED'):
            self.action('submit-asset-observations',task_id=review,observation=observation,adoption_authorization=approval)
        self.assertEqual(self.assets.blocked_panels('E001'),['P001'])
        self.assertEqual(read_json(self.state_path)['visual_basis'],self.spec['visual_basis'])

    def test_final_current_state_readset_is_rechecked_at_asset_cas(self):
        task,out=self.prepared();original=asset_runtime.final_invoke_guard
        def changed(*args,**kwargs):
            state=read_json(self.state_path);state['authority_revision']=999;atomic_json(self.state_path,state)
            return original(*args,**kwargs)
        with patch.object(asset_runtime,'final_invoke_guard',changed),self.assertRaisesRegex(ValueError,'SNAPSHOT_CHANGED'):
            self.action('asset-invoke-guard',task_id=task)

    def test_paused_and_finished_clock_cannot_block_return_preservation(self):
        task,out=self.prepared();self.action('asset-invoke-guard',task_id=task)
        with patch.object(self.host,'_budget',side_effect=ValueError('CLOCK_PAUSED')):
            captured=self.captured(task,out)
            result=self.action('asset-register',task_id=task,capture_reference=captured['capture_reference'])
        with patch.object(self.host,'_budget',side_effect=ValueError('CLOCK_FINISHED')):
            recovered=self.action('asset-recover',task_id=task)
        self.assertEqual(result['status'],'ASSET_REGISTERED');self.assertEqual(recovered['status'],'ASSET_REGISTERED')
        self.assertEqual(self.resources.status()['active']['image'],0)

    def test_changed_selected_reference_cannot_be_overwritten_by_old_observation(self):
        task,out,result=self.saved();review=result['review_task_ids'][0];self.host.scheduler.claim(review,epoch=self.host.epoch)
        image=result['output'];state=read_json(self.state_path);basis=read_json(self.root/state['visual_basis']['path'])
        basis['asset_tasks'][0]['reference']={'path':'approved.png','sha256':digest(self.root/'approved.png')}
        state['visual_basis']=self.put('changed-selected-reference.json',basis);atomic_json(self.state_path,state)
        with self.assertRaisesRegex(ValueError,'TARGET_SCOPE_CHANGED'):
            self.action('submit-asset-observations',task_id=review,observation=self.observation(review,image['sha256']),adoption_authorization=self.approval(image['sha256']))

    def test_channel_persistence_failure_releases_unsubmitted_permit(self):
        import preparation_assets
        task=self.registered();original=preparation_assets.atomic_json
        def fail(path,value):
            if str(path).endswith('-channel.json'):raise OSError('injected channel save failure')
            return original(path,value)
        with patch.object(preparation_assets,'atomic_json',fail),self.assertRaises(OSError):
            self.action('asset-prepare-invoke',task_id=task,channel=self.channel())
        self.assertEqual(self.resources.status()['active']['image'],0)
        self.assertFalse(asset_runtime.ledger_path(self.root).exists())

    def test_shared_image_requires_separate_actual_consumer_observations(self):
        from platform_io import atomic_json
        e2root=self.root/'E002';(e2root/'00_输入审计').mkdir(parents=True)
        basis=read_json(self.root/'basis.json');basis['episode_id']='E002';basis['asset_tasks'][0]['episode_id']='E002'
        atomic_json(e2root/'basis.json',basis)
        e2ref={'path':'basis.json','sha256':digest(e2root/'basis.json')}
        state=e2root/'00_输入审计/生产流程.json';atomic_json(state,{'book_id':'BOOK','episode_id':'E002','visual_basis':e2ref})
        self.host.descriptor['episode_ids'].append('E002');self.host.descriptor['states'].append({'path':str(state),'sha256':digest(state)})
        auth=read_json(self.root/'authorization.json');auth['episode_ids']=['E001','E002'];authref=self.put('shared-auth.json',auth)
        one=copy.deepcopy(self.spec);one['authorization']=authref
        one['shared_asset']={'subject_id':'C','state_id':'normal','definition':{'view':'front'},'usage_basis':{'source_locator':'synthetic://explicit-both'},'owner_episode_id':'E001','episode_ids':['E001','E002']}
        two=copy.deepcopy(one);two.update(episode_id='E002',attempt_id='E2-A1',visual_basis={'path':'E002/basis.json','sha256':e2ref['sha256']})
        result=self.action('register-assets',definitions=[self.put('shared-one.json',one),self.put('shared-two.json',two)])
        self.assertEqual(len(result['image_task_ids']),1);task=result['image_task_ids'][0]
        prepared=self.action('asset-prepare-invoke',task_id=task,channel=self.channel());self.action('asset-invoke-guard',task_id=task)
        captured=self.captured(task,prepared);saved=self.action('asset-register',task_id=task,capture_reference=captured['capture_reference'])
        reviews=self.host.scheduler.status()['tasks'];review=next(i for i in saved['review_task_ids'] if reviews[i]['payload']['target']['episode_id']=='E001')
        self.host.scheduler.claim(review,epoch=self.host.epoch);image=saved['output']
        self.action('submit-asset-observations',task_id=review,observation=self.observation(review,image['sha256']),adoption_authorization=self.approval(image['sha256']))
        self.assertEqual(self.assets.blocked_panels('E001'),[]);self.assertEqual(self.assets.blocked_panels('E002'),['P001'])
        self.assertEqual(read_json(state)['visual_basis'],e2ref)

    def test_restart_clears_dead_local_permit_but_original_service_ledger_holds_capacity(self):
        self.resources.owner={'pid':912345,'birth':'synthetic-dead-host'}
        original_task,out=self.prepared();self.action('asset-invoke-guard',task_id=original_task)
        self.assertEqual(self.resources.status()['active']['image'],1)
        fresh=Coordinator(self.resources.home,probe=normal_sample,liveness=lambda identity:False)
        self.assertEqual(fresh.status()['active']['image'],0)
        scheduler=Scheduler(self.host.scheduler.root,liveness=lambda identity:False)
        self.host.scheduler=scheduler;self.host.epoch=scheduler.start_owner()
        self.host.derivation.resources=fresh;self.assets=Assets(self.host)
        basis=read_json(self.root/'basis.json');basis['asset_tasks'].append({'asset_id':'OTHER','episode_id':'E001','panel_ids':['P002'],'source_basis':'synthetic new independent need'})
        basisref=self.put('restart-basis.json',basis)
        state=read_json(self.state_path);state['visual_basis']=basisref;atomic_json(self.state_path,state)
        auth=read_json(self.root/'authorization.json');auth.update(asset_ids=['VIEW','OTHER'],max_asset_calls=10,max_inflight=1)
        spec=copy.deepcopy(self.spec);spec.update(asset_id='OTHER',attempt_id='OTHER-A1',visual_basis=basisref,authorization=self.put('restart-auth.json',auth))
        task=self.registered([self.put('restart-definition.json',spec)])
        with self.assertRaisesRegex(ValueError,'ASSET_CAPACITY_FULL'):
            self.action('asset-prepare-invoke',task_id=task,channel=self.channel())
        self.assertEqual(fresh.status()['active']['image'],0)
        repeated=self.action('asset-prepare-invoke',task_id=original_task,channel=self.channel())
        self.assertFalse(repeated['ack']['invoke_allowed'])
        attempts=read_json(asset_runtime.ledger_path(self.root))['attempts']
        self.assertEqual(len(attempts),1);self.assertEqual(attempts[out['ack']['registration_id']]['status'],'IN_FLIGHT')

    def test_successful_retry_supersedes_confirmed_failed_image_without_losing_attempt_evidence(self):
        task,out=self.prepared();self.action('asset-invoke-guard',task_id=task)
        failure=self.result('CALL_FAILED');body=read_json(self.root/failure['response_evidence']['path'])
        body['failure_kind']='network';failure['response_evidence']=self.put('network-original.json',body)
        self.action('asset-register',task_id=task,outcome=failure)
        retry=copy.deepcopy(self.spec);retry.update(operation='retry',attempt_id='VIEW-A2',source_attempt_id='VIEW-A1',
            retry_evidence=self.put('retry-proof.json',{'source_attempt_id':'VIEW-A1','asset_id':'VIEW','episode_id':'E001','no_image_confirmed':True,'evidence':'synthetic actual network no-image proof'}))
        replacement=self.registered([self.put('retry-definition.json',retry)])
        prepared=self.action('asset-prepare-invoke',task_id=replacement,channel=self.channel());self.action('asset-invoke-guard',task_id=replacement)
        captured=self.captured(replacement,prepared);saved=self.action('asset-register',task_id=replacement,capture_reference=captured['capture_reference'])
        review=saved['review_task_ids'][0];self.host.scheduler.claim(review,epoch=self.host.epoch);image=saved['output']
        self.action('submit-asset-observations',task_id=review,observation=self.observation(review,image['sha256']),adoption_authorization=self.approval(image['sha256']))
        from task_coordination import scheduler_projection
        self.assertEqual(scheduler_projection(self.root/'00_任务协调')['blockers'],[])
        old=self.host.scheduler.status()['tasks'][task];self.assertEqual(old['status'],'SUPERSEDED')
        self.assertEqual(old['superseded_by'],review);self.assertFalse(old['native_inflight'])
        ledger=read_json(asset_runtime.ledger_path(self.root))['attempts']
        self.assertEqual(ledger[out['ack']['registration_id']]['status'],'CALL_FAILED')
        self.assertEqual(ledger[out['ack']['registration_id']]['response_evidence'],failure['response_evidence'])
        self.assertTrue(Path(old['replacement_evidence']['path']).is_file())

    def test_unknown_original_cannot_be_superseded_by_uninvoked_retry_definition(self):
        task,out=self.prepared();self.action('asset-invoke-guard',task_id=task)
        self.action('asset-register',task_id=task,outcome=self.result('RESULT_UNKNOWN'))
        retry=copy.deepcopy(self.spec);retry.update(operation='retry',attempt_id='VIEW-A2',source_attempt_id='VIEW-A1',
            retry_evidence=self.put('unknown-retry-proof.json',{'source_attempt_id':'VIEW-A1','asset_id':'VIEW','episode_id':'E001','no_image_confirmed':True,'evidence':'synthetic unsupported claim'}))
        with self.assertRaisesRegex(ValueError,'UNKNOWN_CANNOT_RETRY'):
            self.registered([self.put('unknown-retry.json',retry)])
        old=self.host.scheduler.status()['tasks'][task]
        self.assertEqual(old['status'],'UNKNOWN');self.assertTrue(old['native_inflight'])
        self.assertEqual(self.resources.status()['active']['image'],1)

    def test_replacement_retires_saved_failed_review_but_preserves_actual_observation(self):
        task,out,result=self.saved();old_review=result['review_task_ids'][0]
        self.host.scheduler.claim(old_review,epoch=self.host.epoch)
        original_image=result['output'];observation=self.observation(old_review,original_image['sha256'],status='FAIL')
        self.action('submit-asset-observations',task_id=old_review,observation=observation)
        before=self.host.scheduler.status()['tasks'][old_review]
        self.assertEqual(before['status'],'RESULT_SAVED');original_outputs=copy.deepcopy(before['output_refs'])
        repair=copy.deepcopy(self.spec);repair.update(operation='repair',attempt_id='VIEW-A2',source_attempt_id='VIEW-A1',
            repair_evidence=self.put('saved-review-repair-proof.json',{'source_attempt_id':'VIEW-A1','asset_id':'VIEW','episode_id':'E001','evidence':'synthetic failed actual quick view'}))
        replacement=self.registered([self.put('saved-review-repair.json',repair)])
        prepared=self.action('asset-prepare-invoke',task_id=replacement,channel=self.channel());self.action('asset-invoke-guard',task_id=replacement)
        captured=self.captured(replacement,prepared);saved=self.action('asset-register',task_id=replacement,capture_reference=captured['capture_reference'])
        review=saved['review_task_ids'][0];self.host.scheduler.claim(review,epoch=self.host.epoch);image=saved['output']
        # A new observed result file keeps the original failed observation immutable.
        accepted=self.observation(review,image['sha256']);accepted_path=self.root/accepted['path']
        # Fixture overwrote its authored input only; bridge's saved actual proof remains unchanged.
        self.action('submit-asset-observations',task_id=review,observation=accepted,adoption_authorization=self.approval(image['sha256']))
        old=self.host.scheduler.status()['tasks'][old_review]
        self.assertEqual(old['status'],'SUPERSEDED');self.assertEqual(old['output_refs'],original_outputs)
        self.assertEqual(read_json(Path(original_outputs[0]['path']))['status'],'FAIL')
        from task_coordination import scheduler_projection
        self.assertEqual(scheduler_projection(self.root/'00_任务协调')['blockers'],[])

if __name__=='__main__':unittest.main()
