"""Synchronized real-process tests; synthetic evidence, never image services."""
from contextlib import contextmanager
import copy
import json
import multiprocessing
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
from dispatch_fixture import DispatchFixture
from codex_reference_contract import digest, read_json, checked_file, validate_panel
from platform_io import atomic_json
import managed_dispatch as managed


def admit(f):
    return managed.admit(f.state_path,digest(f.state_path),digest(f.control_path),old_writers_stopped=True,
                         immutable_inputs=True,saver_protocol='exclusive_evidence_v1',reason='SYNTHETIC process fixture')



def retarget_synthetic_episode(f, episode):
    """Rebuild synthetic artifact hashes, never edit actual approvals or RVs."""
    import hashlib
    texts={p:p.read_bytes().decode('utf-8') for p in f.root.rglob('*')
           if p.is_file() and p.suffix in {'.json','.txt','.md'}}
    replacements={}
    for path,old in texts.items():
        spellings=list(dict.fromkeys((str(f.root),json.dumps(str(f.root))[1:-1],f.root.as_posix())))
        new=old
        for i,spelling in enumerate(spellings):new=new.replace(spelling,'SYNTHETIC_ROOT_TOKEN_'+str(i))
        new=new.replace('E000',episode)
        for i,spelling in enumerate(spellings):new=new.replace('SYNTHETIC_ROOT_TOKEN_'+str(i),spelling)
        if new!=old:
            path.write_text(new,encoding='utf-8',newline='')
            replacements[hashlib.sha256(old.encode()).hexdigest()]=digest(path)
    for _ in range(40):
        changed=False;next_replacements={}
        for path in texts:
            old=path.read_bytes().decode('utf-8');new=old
            for before,after in replacements.items():new=new.replace(before,after)
            if new!=old:
                before=digest(path);path.write_text(new,encoding='utf-8',newline='')
                next_replacements[before]=digest(path);changed=True
        if not changed:break
        replacements=next_replacements
    else:raise AssertionError('synthetic dependency graph did not converge')
    f.state=read_json(f.state_path)


def reserve_process(path, request, ready, go, result, crash=None):
    import episode_dispatch_queue as queue
    actual_prepare=queue._prepare; actual_write=queue._atomic_json
    def gate(*args):
        value=actual_prepare(*args)
        if ready is not None:
            ready.set()
            if not go.wait(20):raise ValueError('SYNC_TIMEOUT')
        return value
    def write(target,value):
        actual_write(target,value)
        if crash=='packet' and '.dispatch-' in Path(target).name:os._exit(71)
        if crash=='ledger' and Path(target)==Path(path):os._exit(72)
    try:
        with patch.object(queue,'_prepare',side_effect=gate),patch.object(queue,'_atomic_json',side_effect=write):
            state=read_json(Path(path))
            value=managed.reserve(path,digest(Path(path)),digest(Path(state['parallel_context']['control_file'])),
                                  max_count=1,request_id=request,max_retries=1)
        result.put(value)
    except Exception as exc:result.put({'error':str(exc)})


def save_process(path, updates, save_id, ready, go, result, crash=False):
    import production_runtime as runtime
    actual=runtime.commit_updates; once=[]
    def commit(*args,**kwargs):
        if crash:os._exit(73)
        if not once:
            once.append(True);ready.set()
            if not go.wait(20):raise ValueError('SYNC_TIMEOUT')
        return actual(*args,**kwargs)
    try:
        with patch.object(runtime,'commit_updates',side_effect=commit):
            result.put(managed.save(path,updates,save_id))
    except Exception as exc:result.put({'error':str(exc)})


def submit_exit_process(path, receipt):
    managed.submit(path,'P001','P001-r1',1,receipt)
    os._exit(74)


def authority_process(kind,path,token,changes,entered,proceed,attempted,result):
    import authority_updates as authority
    import production_runtime as runtime
    original=authority.state_write_lock;lock=authority.file_lock
    @contextmanager
    def observed(path,**kwargs):
        if path.name.endswith('.dispatch.lock'):attempted.set()
        with lock(path,**kwargs) as stream:yield stream
    @contextmanager
    def held(*args,**kwargs):
        with original(*args,**kwargs):
            entered.set()
            if not proceed.wait(20):raise ValueError('SYNC_TIMEOUT')
            yield
    try:
        with patch.object(authority,'file_lock',side_effect=observed), \
             patch.object(authority,'state_write_lock',side_effect=held), \
             patch.object(runtime,'state_write_lock',side_effect=held):
            if kind=='revoke':value=managed.call(path,'approvals',expected_state_sha256=token,revoke=changes)
            else:value=managed.submit(path,'P001','P001-r1',1,changes)
        result.put((kind,value['status']))
    except Exception as exc:result.put((kind,str(exc)))


class ManagedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f=DispatchFixture(slots=4);self.addCleanup(self.f.close)
        self.ctx=multiprocessing.get_context('spawn')

    def reserve(self, request='request', count=1):
        return managed.reserve(self.f.state_path,digest(self.f.state_path),digest(self.f.control_path),
                               max_count=count,request_id=request)

    def start(self,target,args):
        process=self.ctx.Process(target=target,args=args);process.start()
        def finish():
            if process.is_alive():process.terminate()
            process.join(5)
        self.addCleanup(finish);return process

    def write(self,name,value):
        source=self.f.root/('source-'+name)
        if isinstance(value,bytes):source.write_bytes(value)
        else:atomic_json(source,value)
        return managed.publish_evidence(self.f.state_path,name,source,digest(source))

    def generated_update(self,pid):
        from PIL import Image
        import io
        state=read_json(self.f.state_path);row=next(r for r in state['panels'] if r['panel_id']==pid)
        packet=copy.deepcopy(read_json(checked_file(self.f.root,row['package_manifest'])))
        errors,submission=validate_panel(packet['panels'][0],self.f.root);self.assertEqual(errors,[])
        out=io.BytesIO();Image.new('RGB',(90,160),'white').save(out,format='PNG')
        image=self.write(pid+'.png',out.getvalue())
        request=self.write(pid+'-request.json',{'attempt_id':row['attempt_id'],'backend_id':'codex_builtin_imagegen',
            'panel_id':pid,**submission,'source_kind':'observed_tool_call','source_locator':'synthetic://not-a-real-call'})
        response=self.write(pid+'-response.json',{'attempt_id':row['attempt_id'],'status':'COMPLETED','outputs':[image],
            'source_kind':'observed_tool_result','source_locator':'synthetic://not-a-real-return'})
        packet['panels'][0]['generation_execution']={'status':'COMPLETED','attempt_id':row['attempt_id'],
            'request_evidence':request,'response_evidence':response}
        returned=self.write(pid+'-returned.json',packet)
        return {'panel_id':pid,'attempt_id':row['attempt_id'],'round_id':row['round_id'],'status':'GENERATED',
                'package_manifest':returned,'output':image}

    def inflight(self,pids):
        state=read_json(self.f.state_path)
        updates=[{'panel_id':r['panel_id'],'round_id':r['round_id'],'attempt_id':r['attempt_id'],'status':'IN_FLIGHT'}
                 for r in state['panels'] if r['panel_id'] in pids]
        managed.call(self.f.state_path,'commit',expected_sha256=digest(self.f.state_path),updates=updates)

    def test_crash_after_packet_before_ledger_preserves_orphan_and_retry_claims_once(self):
        admit(self.f);before=digest(self.f.state_path);q=self.ctx.Queue()
        process=self.start(reserve_process,(self.f.state_path,'crash-request',None,None,q,'packet'))
        process.join(20);self.assertEqual(process.exitcode,71);self.assertEqual(digest(self.f.state_path),before)
        orphan=list(self.f.root.glob('*.dispatch-*.json'));self.assertEqual(len(orphan),1)
        value=self.reserve('crash-request');self.assertEqual(value['status'],'RESERVED')
        self.assertEqual(len(read_json(self.f.state_path)['dispatch_ledger']),1)
        self.assertTrue(orphan[0].exists()) # Never remove files without reference proof.

    def test_crash_after_ledger_lost_ack_recovers_same_receipt(self):
        admit(self.f);q=self.ctx.Queue()
        process=self.start(reserve_process,(self.f.state_path,'lost-ack',None,None,q,'ledger'))
        process.join(20);self.assertEqual(process.exitcode,72)
        expected=read_json(self.f.state_path)['reservation_requests']['lost-ack']['reserved']
        recovered=self.reserve('lost-ack');self.assertEqual(recovered['status'],'ALREADY_RESERVED')
        self.assertEqual(recovered['reserved'],expected);self.assertEqual(len(read_json(self.f.state_path)['dispatch_ledger']),1)

    def test_unknown_submission_keeps_attempt_slot_and_cannot_be_reclaimed(self):
        admit(self.f);receipt=self.reserve()['reserved'][0]['permit_id']
        process=self.start(submit_exit_process,(self.f.state_path,receipt));process.join(20)
        self.assertEqual(process.exitcode,74)
        state=read_json(self.f.state_path);row=state['panels'][0]
        log=self.write('unknown.json',{'attempt_id':row['attempt_id'],'status':'RESULT_UNKNOWN',
                                     'source_locator':'synthetic://lost-transport','evidence':'SYNTHETIC service receipt unknown'})
        update={'panel_id':'P001','round_id':1,'attempt_id':row['attempt_id'],'status':'RESULT_UNKNOWN','call_evidence':log}
        managed.save(self.f.state_path,[update],'unknown-save')
        after=read_json(self.f.state_path)
        self.assertEqual(after['panels'][0]['attempt_id'],row['attempt_id'])
        self.assertEqual(after['dispatch_ledger'][0]['status'],'RESULT_UNKNOWN')
        with self.assertRaisesRegex(ValueError,'已进入提交窗口'):
            managed.call(self.f.state_path,'release',expected_sha256=digest(self.f.state_path),panel_ids=['P001'])

    def test_image_saved_before_generated_registration_is_recoverable_and_idempotent(self):
        admit(self.f);self.reserve();self.inflight(['P001']);update=self.generated_update('P001')
        q=self.ctx.Queue();process=self.start(save_process,(self.f.state_path,[update],'durable-return',None,None,q,True))
        process.join(20);self.assertEqual(process.exitcode,73)
        self.assertEqual(read_json(self.f.state_path)['panels'][0]['status'],'IN_FLIGHT')
        intent=next((self.f.state_path.parent/'saved_intents').glob('*.json'))
        first=managed.recover_saved(self.f.state_path,intent)
        self.assertEqual(first['status'],'UPDATES_SAVED')
        second=managed.recover_saved(self.f.state_path,intent)
        self.assertEqual(second['status'],'UPDATES_ALREADY_SAVED')
        before=self.f.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError,'locked execution evidence'):
            managed.save(self.f.state_path,[{**update,'status':'VISUAL_PASS','output':{**update['output'],'sha256':'0'*64}}],'qa-must-not-replace-output')
        self.assertEqual(self.f.state_path.read_bytes(),before)
        state=read_json(self.f.state_path);self.assertEqual(state['dispatch_ledger'][0]['status'],'COMPLETED')
        events=state['dispatch_ledger'][0]['events'];self.assertEqual(len(events),2)
        bad={**update,'output':{**update['output'],'sha256':'0'*64}}
        with self.assertRaisesRegex(ValueError,'SAVE_ID_CONFLICT'):managed.save(self.f.state_path,[bad],'durable-return')
        with self.assertRaisesRegex(ValueError,'状态转换无效|SHA256'):managed.save(self.f.state_path,[bad],'conflicting-return')
        with self.assertRaisesRegex(ValueError,'旧返回不得覆盖'):
            managed.save(self.f.state_path,[{**update,'attempt_id':'old-attempt'}],'old-return')

    def test_two_simultaneous_returns_are_both_saved_with_exact_attempts(self):
        admit(self.f);self.reserve(count=2);self.inflight(['P001','P002'])
        updates=[self.generated_update(p) for p in ('P001','P002')]
        q=self.ctx.Queue();go=self.ctx.Event();events=[self.ctx.Event(),self.ctx.Event()]
        processes=[self.start(save_process,(self.f.state_path,[u],'return-'+u['panel_id'],e,go,q)) for u,e in zip(updates,events)]
        for event in events:self.assertTrue(event.wait(20))
        go.set()
        values=[q.get(timeout=30) for _ in processes]
        for process in processes:process.join(20);self.assertEqual(process.exitcode,0)
        self.assertTrue(all(v.get('status')=='UPDATES_SAVED' for v in values),values)
        state=read_json(self.f.state_path)
        self.assertEqual([r['status'] for r in state['panels'][:2]],['GENERATED','GENERATED'])
        self.assertEqual([r['status'] for r in state['dispatch_ledger']],['COMPLETED','COMPLETED'])

    def qa_update(self,pid):
        from contextlib import redirect_stdout
        import io
        from make_generation_qa import _main
        state=read_json(self.f.state_path);row=next(r for r in state['panels'] if r['panel_id']==pid)
        out=self.f.root/(pid+'-qa-materials')
        image=checked_file(self.f.root,row['output'])
        with managed.authority([self.f.state_path]),redirect_stdout(io.StringIO()):
            code=_main(['--package',str(self.f.root),'--manifest',row['package_manifest']['path'],
                        '--images',str(image.parent),'--image-path',str(image),'--output',str(out),'--skip-contact-sheet'])
        self.assertEqual(code,0)
        qa=read_json(out/'生成图QA报告.json');item=qa['panels'][0]
        for review in [*item['dimension_review'].values(),item['style_review']]:
            if review['status']=='UNREVIEWED':review.update(status='PASS',reviewer='SYNTHETIC',evidence='Fixture only')
        for key in ('camera_match','shot_scale_match','background_view_match','body_crop_match',
                    'required_visible_information_preserved','no_extra_offscreen_characters'):item[key]=True
        return {'panel_id':pid,'attempt_id':row['attempt_id'],'round_id':row['round_id'],'status':'VISUAL_PASS',
                'qa_report':self.write(pid+'-reviewed.json',qa)}

    def test_qa_update_concurrent_with_claim_preserves_both(self):
        admit(self.f);self.reserve();self.inflight(['P001'])
        managed.save(self.f.state_path,[self.generated_update('P001')],'returned')
        qa=self.qa_update('P001');q=self.ctx.Queue();ready=self.ctx.Event();go=self.ctx.Event()
        process=self.start(reserve_process,(self.f.state_path,'qa-race',ready,go,q));self.assertTrue(ready.wait(20))
        managed.save(self.f.state_path,[qa],'qa-save');go.set();value=q.get(timeout=30);process.join(20)
        self.assertEqual(value.get('status'),'RESERVED',value)
        self.assertEqual(read_json(self.f.state_path)['panels'][0]['status'],'VISUAL_PASS')
        self.assertEqual(value['reserved'][0]['panel_id'],'P002')

    def test_stop_new_dispatch_still_accepts_existing_return_and_qa(self):
        admit(self.f);reserved=self.reserve();self.inflight(['P001']);update=self.generated_update('P001')
        managed.coordinator(self.f.control_path,'control',expected_control_sha256=digest(self.f.control_path),
            expected_states={'synthetic-job':digest(self.f.state_path)},changes={'cancelled':True,'holds':['SYNTHETIC stop']},reason='SYNTHETIC stop')
        managed.save(self.f.state_path,[update],'return-after-stop')
        managed.save(self.f.state_path,[self.qa_update('P001')],'qa-after-stop')
        from parallel_dispatch import receipt_errors
        state=read_json(self.f.state_path);context=state['parallel_context'];receipt=reserved['reserved'][0]['receipt']
        with managed.authority([self.f.state_path]):
            self.assertEqual(receipt_errors(context,self.f.root,state['book_id'],state['episode_id'],'P001',receipt,update['output']['sha256']),[])
            self.assertTrue(receipt_errors(context,self.f.root,state['book_id'],state['episode_id'],'P001',receipt))

    def approval_race(self,first):
        proof=self.f.root/'original-proof.json';atomic_json(proof,self.f.state['gates']['shot_design'])
        revoke={'approval':{'path':proof.name,'sha256':digest(proof)},'message':{'source_kind':'user_message',
            'source_locator':'SYNTHETIC_NOT_REAL_USER','quote':'SYNTHETIC withdraw exact proof'}}
        admit(self.f);receipt=self.reserve()['reserved'][0]['permit_id'];token=digest(self.f.state_path)
        q=self.ctx.Queue();names=('revoke','submit');entered={k:self.ctx.Event() for k in names}
        proceed={k:self.ctx.Event() for k in names};attempted={k:self.ctx.Event() for k in names}
        second='submit' if first=='revoke' else 'revoke'
        def start(kind):return self.start(authority_process,(kind,self.f.state_path,token,[revoke] if kind=='revoke' else receipt,
            entered[kind],proceed[kind],attempted[kind],q))
        a=start(first);self.assertTrue(entered[first].wait(20));b=start(second);self.assertTrue(attempted[second].wait(20))
        self.assertFalse(entered[second].is_set());proceed[second].set();proceed[first].set()
        values=dict(q.get(timeout=30) for _ in names)
        for process in (a,b):process.join(20);self.assertEqual(process.exitcode,0)
        self.assertEqual(values[first],'AUTHORITY_UPDATED' if first=='revoke' else 'SUBMISSION_REGISTERED',values)
        self.assertIn('STATE_CHANGED',values[second])
        if first=='revoke':
            with self.assertRaisesRegex(ValueError,'完整门禁'):managed.submit(self.f.state_path,'P001','P001-r1',1,receipt)
            self.assertEqual(read_json(self.f.state_path)['dispatch_ledger'][0]['status'],'RESERVED')
        else:
            managed.call(self.f.state_path,'approvals',expected_state_sha256=digest(self.f.state_path),revoke=[revoke])
            self.assertEqual(read_json(self.f.state_path)['dispatch_ledger'][0]['status'],'IN_FLIGHT')

    def test_revocation_wins_against_submission(self):self.approval_race('revoke')
    def test_submission_wins_then_revocation_keeps_original_slot(self):self.approval_race('submit')

    def test_two_simultaneous_reservations_do_not_duplicate_or_exceed_capacity(self):
        admit(self.f);q=self.ctx.Queue();go=self.ctx.Event();events=[self.ctx.Event(),self.ctx.Event()]
        processes=[self.start(reserve_process,(self.f.state_path,'request-'+str(i),event,go,q)) for i,event in enumerate(events)]
        for event in events:self.assertTrue(event.wait(20))
        go.set();values=[q.get(timeout=30) for _ in processes]
        for process in processes:process.join(20);self.assertEqual(process.exitcode,0)
        self.assertTrue(all(v.get('status')=='RESERVED' for v in values),values)
        ledger=read_json(self.f.state_path)['dispatch_ledger']
        self.assertEqual(len(ledger),2);self.assertEqual(len({r['panel_id'] for r in ledger}),2)
        self.assertEqual(len({r['permit_id'] for r in ledger}),2)

    def test_pause_between_preflight_and_commit_cannot_be_missed(self):
        admit(self.f);q=self.ctx.Queue();ready=self.ctx.Event();go=self.ctx.Event()
        process=self.start(reserve_process,(self.f.state_path,'pause-race',ready,go,q))
        self.assertTrue(ready.wait(20))
        managed.coordinator(self.f.control_path,'control',expected_control_sha256=digest(self.f.control_path),
            expected_states={'synthetic-job':digest(self.f.state_path)},
            changes={'jobs':{'synthetic-job':{'dispatch_pause':True}}},reason='SYNTHETIC pause race')
        go.set();value=q.get(timeout=30);process.join(20)
        self.assertEqual(value.get('status'),'DISPATCH_PAUSED',value)
        self.assertEqual(read_json(self.f.state_path).get('dispatch_ledger',[]),[])

    def test_lease_change_between_preflight_and_commit_revalidates_new_grant(self):
        admit(self.f);q=self.ctx.Queue();ready=self.ctx.Event();go=self.ctx.Event()
        old=read_json(self.f.control_path)['jobs'][0]['slot_lease']['lease_id']
        process=self.start(reserve_process,(self.f.state_path,'lease-race',ready,go,q));self.assertTrue(ready.wait(20))
        managed.coordinator(self.f.control_path,'allocate',expected_sha256=digest(self.f.control_path),
                            allocations={'synthetic-job':1},old_writers_stopped=True)
        go.set();value=q.get(timeout=30);process.join(20)
        self.assertEqual(value.get('status'),'RESERVED',value)
        self.assertNotEqual(value['reserved'][0]['receipt']['lease_id'],old)
        self.assertEqual(len(read_json(self.f.state_path)['dispatch_ledger']),1)

    def test_slow_episode_preflight_does_not_block_other_episode_reservation(self):
        from slot_leases import allocate
        other=DispatchFixture(slots=4);self.addCleanup(other.close)
        retarget_synthetic_episode(other,'E001')
        control=read_json(self.f.control_path);second=copy.deepcopy(read_json(other.control_path)['jobs'][0])
        second.update(job_id='second-job',worker_id='second-worker',episode_id='E001',frozen_inputs={k:copy.deepcopy(other.state[k]) for k in ('source_script','source_snapshot','visual_basis','shot_manifest')});control['jobs'].append(second);control['max_workers']=2
        state=read_json(other.state_path);state['parallel_context'].update(control_file=str(self.f.control_path),
            job_id='second-job',worker_id='second-worker');atomic_json(other.state_path,state)
        atomic_json(self.f.control_path,control)
        allocate(self.f.control_path,digest(self.f.control_path),{'synthetic-job':2,'second-job':2},old_writers_stopped=True)
        other.control_path=self.f.control_path
        admit(self.f);admit(other)
        ready=self.ctx.Event();go=self.ctx.Event();q=self.ctx.Queue()
        process=self.start(reserve_process,(self.f.state_path,'slow-A',ready,go,q))
        self.assertTrue(ready.wait(20))
        # The event is held after A's real gate, before publication/commit.
        value=managed.reserve(other.state_path,digest(other.state_path),digest(other.control_path),max_count=1,request_id='fast-B')
        self.assertEqual(value['status'],'RESERVED');self.assertTrue(process.is_alive())
        go.set();result=q.get(timeout=30);process.join(20)
        self.assertEqual(result.get('status'),'RESERVED',result)

if __name__=='__main__':unittest.main()
