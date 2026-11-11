"""Synthetic local boundary tests; no real image service or approval."""
import base64
import copy
import json
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import asset_runtime as assets
from codex_reference_contract import digest, read_json
from platform_io import atomic_json
import test_asset_runtime as fixture


class AssetPipelineTests(unittest.TestCase):
    setUp=fixture.AssetTests.setUp
    put=fixture.AssetTests.put
    result=fixture.AssetTests.result

    def raw(self):
        p=self.root/'return.json'
        p.write_text(json.dumps({'image_url':'data:image/png;base64,'+base64.b64encode((self.root/'approved.png').read_bytes()).decode()}))
        return p

    def request(self):
        return self.put('actual-request.json',{'source_kind':'observed_tool_call','attempt_id':'VIEW-A1',
            'source_locator':'synthetic://actual-call','arguments':self.job['arguments']})

    def shared(self, **changes):
        spec=copy.deepcopy(self.spec)
        spec['shared_asset']={'subject_id':'CHAR-A','state_id':'normal','definition':{'view':'front'},
            'usage_basis':{'source_locator':'synthetic://script-lines','purpose':'identity'},
            'owner_episode_id':'E001','episode_ids':['E001','E002']}
        spec['shared_asset'].update(changes)
        return spec

    def test_compile_and_image_reads_happen_outside_write_lock(self):
        held=[]; original_lock=assets.file_lock; original_compile=assets.compile_job; original_checked=assets.checked_file
        @contextmanager
        def tracked(path):
            with original_lock(path):
                held.append(True)
                try:yield
                finally:held.pop()
        def compile_checked(*a,**kw):
            self.assertFalse(held,'compile under ledger lock');return original_compile(*a,**kw)
        def checked(*a,**kw):
            self.assertFalse(held,'image/evidence verification under ledger lock');return original_checked(*a,**kw)
        with patch.object(assets,'file_lock',tracked),patch.object(assets,'compile_job',compile_checked),patch.object(assets,'checked_file',checked):
            ack=assets.submit(self.root,self.job)
            assets.save(self.root,ack['registration_id'],self.result())

    def test_changed_authorization_between_compile_and_cas_is_rejected(self):
        original=assets.compile_job
        def changed(*a,**kw):
            value=original(*a,**kw)
            auth=read_json(self.root/'authorization.json');auth['max_asset_calls']=0
            atomic_json(self.root/'authorization.json',auth)
            return value
        with patch.object(assets,'compile_job',changed),self.assertRaisesRegex(ValueError,'SNAPSHOT_CHANGED'):
            assets.submit(self.root,self.job)
        self.assertFalse(assets.ledger_path(self.root).exists())

    def test_concurrent_submit_has_exactly_one_invocation(self):
        barrier=threading.Barrier(2);original=assets.compile_job
        def together(*a,**kw):
            value=original(*a,**kw);barrier.wait(timeout=5);return value
        with patch.object(assets,'compile_job',together),ThreadPoolExecutor(2) as pool:
            rows=list(pool.map(lambda _:assets.submit(self.root,self.job),range(2)))
        self.assertEqual(sum(r['invoke_allowed'] for r in rows),1)
        self.assertEqual(len(read_json(assets.ledger_path(self.root))['attempts']),1)

    def test_scheduler_requires_epoch_guard_and_final_recheck(self):
        atomic_json(self.root/'00_任务协调/preparation-host.json',{'policy':'preparation_scheduler_v1'})
        with self.assertRaisesRegex(ValueError,'EPOCH_GUARD_REQUIRED'):assets.submit(self.root,self.job)
        owner={'epoch':1}
        def guard():return owner['epoch']==1
        ack=assets.submit(self.root,self.job,epoch_guard=guard)
        self.assertTrue(ack['invoke_allowed'])
        owner['epoch']=2
        with self.assertRaisesRegex(ValueError,'STALE_OWNER'):assets.final_invoke_guard(self.root,self.job,epoch_guard=guard)

    def test_shared_key_content_scope_and_no_inferred_usage(self):
        spec=self.shared();key=assets.shared_asset_key(spec)
        migrated=copy.deepcopy(spec);migrated['episode_id']='E002';migrated['attempt_id']='different'
        self.assertEqual(key,assets.shared_asset_key(migrated))
        for field,value in [('state_id','rain'),('definition',{'view':'side'}),('usage_basis',{'source_locator':'synthetic://other'}),('owner_episode_id','E002')]:
            changed=copy.deepcopy(spec);changed['shared_asset'][field]=value
            self.assertNotEqual(key,assets.shared_asset_key(changed))
        changed=copy.deepcopy(spec);changed['reference_files'][0]['sha256']='a'*64
        self.assertNotEqual(key,assets.shared_asset_key(changed))
        spec['shared_asset'].pop('episode_ids')
        with self.assertRaisesRegex(ValueError,'explicit'):assets.shared_asset_key(spec)

    def test_shared_submit_deduplicates_without_approval(self):
        spec=self.shared();job=assets.compile_job(self.root,self.put('shared.json',spec))[0]
        first=assets.submit(self.root,job)
        spec['attempt_id']='VIEW-A2';other=assets.compile_job(self.root,self.put('shared2.json',spec))[0]
        second=assets.submit(self.root,other)
        self.assertFalse(second['invoke_allowed'])
        self.assertEqual(second['registration_id'],first['registration_id'])
        self.assertEqual(second['asset_approval'],'NOT_GRANTED')

    def test_capture_replay_after_registration_failure_never_submits(self):
        ack=assets.submit(self.root,self.job)
        captured=assets.capture(self.root,ack['registration_id'],self.raw(),request_evidence=self.request(),response_source_locator='synthetic://actual-return')
        with patch.object(assets,'save',side_effect=OSError('injected ledger failure')):
            with self.assertRaisesRegex(OSError,'injected'):assets.register_capture(self.root,captured)
        self.assertEqual(read_json(assets.ledger_path(self.root))['attempts'][ack['registration_id']]['status'],'IN_FLIGHT')
        with patch.object(assets,'submit',side_effect=AssertionError('must not regenerate')):
            receipt=assets.recover(self.root,ack['registration_id'])
            again=assets.recover(self.root,ack['registration_id'])
        self.assertEqual(receipt['status'],'ASSET_RESULT_SAVED')
        self.assertEqual(again['status'],'ASSET_RESULT_ALREADY_SAVED')
        row=read_json(assets.ledger_path(self.root))['attempts'][ack['registration_id']]
        self.assertTrue((self.root/row['output']['path']).is_file())
        self.assertFalse(row.get('asset_approval'))

    def test_capture_survives_failure_after_persist_before_result_manifest(self):
        ack=assets.submit(self.root,self.job)
        import image_return_io
        original=image_return_io.persist
        def failed(*a,**kw):original(*a,**kw);raise OSError('after durable persist')
        with patch.object(image_return_io,'persist',failed),self.assertRaisesRegex(OSError,'after durable'):
            assets.capture(self.root,ack['registration_id'],self.raw(),request_evidence=self.request(),response_source_locator='synthetic://actual-return')
        self.assertEqual(assets.recover(self.root,ack['registration_id'])['status'],'ASSET_RESULT_SAVED')

    def test_unknown_blocks_retry_and_capture_release_until_resolution(self):
        ack=assets.submit(self.root,self.job);assets.save(self.root,ack['registration_id'],self.result('RESULT_UNKNOWN'))
        captured=assets.capture(self.root,ack['registration_id'],self.raw(),request_evidence=self.request(),response_source_locator='synthetic://located-return')
        releases=[]
        with self.assertRaisesRegex(ValueError,'resolution'):assets.register_capture(self.root,captured,release_service=lambda:releases.append(1))
        self.assertEqual(releases,[])
        spec=copy.deepcopy(self.spec);spec['attempt_id']='VIEW-A2'
        with self.assertRaisesRegex(ValueError,'CAPACITY_FULL'):assets.submit(self.root,assets.compile_job(self.root,self.put('another.json',spec))[0])

    def test_capture_keeps_raw_when_call_evidence_invalid(self):
        ack=assets.submit(self.root,self.job);request=self.request();data=read_json(self.root/request['path']);data['source_locator']=''
        request=self.put(request['path'],data)
        with self.assertRaisesRegex(ValueError,'actual call'):
            assets.capture(self.root,ack['registration_id'],self.raw(),request_evidence=request,response_source_locator='synthetic://actual-return')
        self.assertTrue(list((self.root/'00_任务协调').rglob('raw-return.json')))

    def test_capture_after_clock_stop_does_not_require_admission(self):
        ack=assets.submit(self.root,self.job)
        with patch.object(assets,'require_dispatch',side_effect=ValueError('clock stopped')):
            captured=assets.capture(self.root,ack['registration_id'],self.raw(),request_evidence=self.request(),response_source_locator='synthetic://actual-return')
            self.assertEqual(assets.register_capture(self.root,captured)['status'],'ASSET_RESULT_SAVED')

    def test_final_guard_rechecks_input_snapshot_under_short_lock(self):
        assets.submit(self.root,self.job)
        original_lock=assets.file_lock
        @contextmanager
        def changed(path):
            with original_lock(path):
                (self.root/'approved.png').write_bytes(b'changed during final admission')
                yield
        with patch.object(assets,'file_lock',changed),self.assertRaisesRegex(ValueError,'SNAPSHOT_CHANGED'):
            assets.final_invoke_guard(self.root,self.job)

    def test_cross_episode_shared_root_keeps_explicit_consumer_scope(self):
        spec=self.shared();first=assets.submit(self.root,assets.compile_job(self.root,self.put('owner.json',spec))[0])
        spec=copy.deepcopy(spec);spec['episode_id']='E002';spec['attempt_id']='E002-A1'
        spec['visual_basis']=self.put('e2-basis.json',{'book_id':'BOOK','episode_id':'E002','asset_tasks':[
            {'asset_id':'VIEW','episode_id':'E002','source_basis':'synthetic need E2'}]})
        auth=read_json(self.root/'authorization.json');auth['episode_ids']=['E002']
        spec['authorization']=self.put('e2-auth.json',auth)
        second=assets.submit(self.root,assets.compile_job(self.root,self.put('consumer.json',spec))[0])
        self.assertFalse(second['invoke_allowed']);self.assertEqual(first['registration_id'],second['registration_id'])
        self.assertEqual(second['scope']['episode_id'],'E002');self.assertEqual(second['owner_episode_id'],'E001')
        self.assertEqual(len(read_json(assets.ledger_path(self.root))['attempts']),1)
        spec['shared_asset']['episode_ids']=['E001']
        with self.assertRaisesRegex(ValueError,'explicit'):assets.compile_job(self.root,self.put('outside.json',spec))

    def test_unknown_resolution_replays_saved_bytes_and_then_releases_service(self):
        ack=assets.submit(self.root,self.job);assets.save(self.root,ack['registration_id'],self.result('RESULT_UNKNOWN'))
        captured=assets.capture(self.root,ack['registration_id'],self.raw(),request_evidence=self.request(),response_source_locator='synthetic://located-original')
        value=read_json(self.root/captured['path'])['result']
        from submission_contract import fingerprint
        token=fingerprint({k:value.get(k) for k in ('status','attempt_id','request_evidence','response_evidence','output')})
        proof=self.put('located.json',{'registration_id':ack['registration_id'],'attempt_id':'VIEW-A1',
            'source_kind':'observed_resolution','source_locator':'synthetic://located-proof','result_digest':token})
        released=[]
        out=assets.recover(self.root,ack['registration_id'],resolution=proof,release_service=lambda:released.append(True))
        self.assertEqual(out['status'],'ASSET_RESULT_SAVED');self.assertEqual(released,[True])

    def test_register_checks_original_raw_integrity(self):
        ack=assets.submit(self.root,self.job)
        captured=assets.capture(self.root,ack['registration_id'],self.raw(),request_evidence=self.request(),response_source_locator='synthetic://actual-return')
        next((self.root/'00_任务协调').rglob('raw-return.json')).write_text('{}')
        with self.assertRaises(ValueError):assets.register_capture(self.root,captured)

    def test_shared_identity_binds_compiled_character_format(self):
        spec=self.shared();job=assets.compile_job(self.root,self.put('plain.json',spec))[0]
        assets.submit(self.root,job)
        basis=read_json(self.root/'basis.json');basis['asset_tasks'][0].update(character_id='C',costume_id='S')
        spec['visual_basis']=self.put('costume-basis.json',basis);spec['attempt_id']='VIEW-A2'
        formatted=assets.compile_job(self.root,self.put('formatted.json',spec))[0]
        self.assertNotEqual(job['arguments'],formatted['arguments'])
        with self.assertRaisesRegex(ValueError,'CAPACITY_FULL'):assets.submit(self.root,formatted)

    def test_shared_dedup_points_to_current_attempt_and_exposes_unknown(self):
        spec=self.shared();job=assets.compile_job(self.root,self.put('plain.json',spec))[0]
        first=assets.submit(self.root,job);assets.save(self.root,first['registration_id'],self.result())
        spec.update(operation='repair',attempt_id='VIEW-A2',source_attempt_id='VIEW-A1',
            repair_evidence=self.put('repair-proof.json',{'source_attempt_id':'VIEW-A1','asset_id':'VIEW','episode_id':'E001','evidence':'synthetic repair need'}))
        repair=assets.submit(self.root,assets.compile_job(self.root,self.put('repair.json',spec))[0])
        assets.save(self.root,repair['registration_id'],self.result('RESULT_UNKNOWN',attempt='VIEW-A2'))
        consumer=self.shared();consumer['attempt_id']='VIEW-CONSUMER'
        out=assets.submit(self.root,assets.compile_job(self.root,self.put('consumer.json',consumer))[0])
        self.assertEqual(out['registration_id'],repair['registration_id'])
        self.assertEqual(out['shared_asset_status'],'RESULT_UNKNOWN')
        self.assertFalse(out['invoke_allowed'])

if __name__=='__main__':unittest.main()
