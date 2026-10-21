"""Real gates for explicit managed admission, conflicts and lost responses."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'scripts'), str(Path(__file__).parent)]
from dispatch_fixture import DispatchFixture
from codex_reference_contract import digest, read_json
from platform_io import atomic_json
import managed_dispatch as managed
from episode_dispatch_queue import reserve_ready

class ManagedDispatchTests(unittest.TestCase):
    def setUp(self):
        self.f = DispatchFixture(); self.addCleanup(self.f.close)

    def admit(self):
        return managed.admit(self.f.state_path, digest(self.f.state_path), digest(self.f.control_path),
            old_writers_stopped=True, immutable_inputs=True, saver_protocol='exclusive_evidence_v1', reason='SYNTHETIC fixture only')

    def reserve(self, request_id='request-1', **kwargs):
        return managed.reserve(self.f.state_path, digest(self.f.state_path), digest(self.f.control_path),
                               max_count=kwargs.pop('max_count', 1), request_id=request_id, **kwargs)

    def test_admission_is_explicit_and_active_requests_cannot_migrate(self):
        with self.assertRaisesRegex(ValueError, 'ADMISSION_HOLD'):
            managed.admit(self.f.state_path, digest(self.f.state_path), digest(self.f.control_path))
        reserve_ready(self.f.state_path, digest(self.f.state_path), digest(self.f.control_path), 1)
        with self.assertRaisesRegex(ValueError, 'active/unknown'): self.admit()

    def test_real_gates_short_reserve_and_lost_response_recovery(self):
        self.admit(); old_state = digest(self.f.state_path); old_control = digest(self.f.control_path)
        first = self.reserve()
        self.assertEqual(first['status'], 'RESERVED'); self.assertEqual(len(first['reserved']), 1)
        recovered = managed.reserve(self.f.state_path, old_state, old_control, max_count=1, request_id='request-1')
        self.assertEqual(recovered['status'], 'ALREADY_RESERVED'); self.assertEqual(first['reserved'], recovered['reserved'])
        self.assertEqual(len(read_json(self.f.state_path)['dispatch_ledger']), 1)
        self.assertIn('last_dispatch_read_set', read_json(self.f.state_path))
        with self.assertRaisesRegex(ValueError, 'REQUEST_ID_CONFLICT'): self.reserve(max_count=2)

    def test_native_legacy_entry_cannot_silently_use_managed_state(self):
        self.admit()
        with self.assertRaisesRegex(ValueError, 'DISPATCH_PROTOCOL_UNSUPPORTED'):
            reserve_ready(self.f.state_path, digest(self.f.state_path), digest(self.f.control_path), 1)
        from production_runtime import commit_updates
        with self.assertRaisesRegex(ValueError, 'DISPATCH_PROTOCOL_UNSUPPORTED'):
            commit_updates(self.f.state_path, digest(self.f.state_path), [{'panel_id':'P001'}])

    def test_gate_and_publication_are_not_under_shared_lock(self):
        import episode_dispatch_queue as queue
        import dispatch_publication as pub
        from contextlib import contextmanager
        actual_lock=queue._timed_locks; actual_gate=queue._prepare; actual_pub=pub.publish
        held=[]
        @contextmanager
        def locks(*args):
            with actual_lock(*args):
                held.append(True)
                try: yield
                finally: held.pop()
        def gate(*args):
            self.assertFalse(held); return actual_gate(*args)
        def publish(*args):
            self.assertFalse(held); return actual_pub(*args)
        self.admit()
        with patch.object(queue, '_timed_locks', locks), patch.object(queue, '_prepare', gate), patch.object(pub, 'publish', publish):
            self.assertEqual(self.reserve()['status'], 'RESERVED')

    def test_state_or_control_conflict_discards_and_retries_are_bounded(self):
        import dispatch_publication as pub
        original=pub.publish; calls=[]
        self.admit()
        def changed(*args):
            ref=original(*args); calls.append(True)
            value=read_json(self.f.control_path);value['unrelated_revision']=len(calls)
            atomic_json(self.f.control_path,value);return ref
        with patch.object(pub,'publish',side_effect=changed):
            value=self.reserve(max_retries=2)
        self.assertEqual(value['status'],'PREFLIGHT_CONFLICT');self.assertEqual(len(calls),3)
        self.assertEqual(len(value['dispatch_metrics']['conflicts']),3)
        self.assertEqual(read_json(self.f.state_path).get('dispatch_ledger',[]),[])

    def test_actual_toolchain_and_unknown_markers_fail_closed(self):
        self.admit(); state=read_json(self.f.state_path);state['toolchain']['files']=[]
        atomic_json(self.f.state_path,state)
        with self.assertRaisesRegex(ValueError,'exact frozen tools'):self.reserve()

    def test_submission_acknowledgement_is_one_shot_and_wrong_receipt_cannot_invoke(self):
        self.admit();reserved=self.reserve()['reserved'][0]
        jobs=managed.call(self.f.state_path,'compile',panel_ids=['P001'])['jobs']
        self.assertEqual(len(jobs),1);self.assertTrue(jobs[0]['managed_submission_required'])
        self.assertEqual(jobs[0]['dispatch_receipt'],reserved['receipt'])
        with self.assertRaisesRegex(ValueError,'exact receipt'):
            managed.submit(self.f.state_path,'P001','P001-r1',1,'invalid')
        first=managed.submit(self.f.state_path,'P001','P001-r1',1,reserved['permit_id'])
        second=managed.submit(self.f.state_path,'P001','P001-r1',1,reserved['permit_id'])
        self.assertTrue(first['invoke_allowed']);self.assertFalse(second['invoke_allowed'])
        self.assertEqual(second['status'],'ALREADY_REGISTERED')
        self.assertEqual(read_json(self.f.state_path)['dispatch_ledger'][0]['status'],'IN_FLIGHT')

    def test_frozen_input_overwrite_and_new_negative_dependency_are_rejected(self):
        self.admit();state=read_json(self.f.state_path)
        source=self.f.root/state['source_snapshot']['path'];old=source.read_bytes()
        source.write_bytes(old+b' ')
        with self.assertRaisesRegex(ValueError,'IMMUTABLE_INPUT_CHANGED'):self.reserve()
        source.write_bytes(old)
        from task_context import ORIGIN_FILE
        (self.f.root/ORIGIN_FILE).write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'CHECK_SNAPSHOT_CHANGED'):self.reserve()
        self.assertEqual(read_json(self.f.state_path).get('dispatch_ledger',[]),[])

    def test_mutable_result_evidence_cannot_be_adopted_by_managed_writer(self):
        self.admit();self.reserve()
        source=self.f.root/'mutable-log.json';atomic_json(source,{'synthetic':True})
        update={'panel_id':'P001','attempt_id':'P001-r1','round_id':1,'status':'RESULT_UNKNOWN',
                'call_evidence':{'path':source.name,'sha256':digest(source)}}
        with self.assertRaisesRegex(ValueError,'publish new evidence exclusively'):
            managed.save(self.f.state_path,[update],'mutable-return')
        self.assertEqual(read_json(self.f.state_path)['panels'][0]['status'],'PENDING')

    def test_admission_binds_the_captured_state_and_control_even_after_aba_restore(self):
        import immutable_inputs
        capture=immutable_inputs.capture
        for target in (self.f.state_path,self.f.control_path):
            with self.subTest(target=target):
                original=target.read_bytes()
                def transient(*args,**kwargs):
                    value=read_json(target);value['synthetic_transient_version']=1;atomic_json(target,value)
                    try:return capture(*args,**kwargs)
                    finally:target.write_bytes(original)
                with patch.object(immutable_inputs,'capture',side_effect=transient):
                    with self.assertRaisesRegex(ValueError,'captured state/control'):self.admit()
                self.assertEqual(target.read_bytes(),original)
                self.assertNotIn('dispatch_consistency',read_json(self.f.state_path))

    def test_incomplete_preparation_is_rejected_before_admission(self):
        row=self.f.state['panels'][-1]
        (self.f.root/row['package_manifest']['path']).write_bytes(b'{}')
        before=self.f.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError,'fully prepared request scope'):self.admit()
        self.assertEqual(self.f.state_path.read_bytes(),before)
        self.assertNotIn('dispatch_consistency',read_json(self.f.state_path))

    def test_submission_cannot_replace_the_preflighted_packet(self):
        self.admit();self.reserve();state=read_json(self.f.state_path);row=state['panels'][0]
        packet=read_json(self.f.root/row['package_manifest']['path'])
        packet['panels'][0]['prompt']+=' SYNTHETIC changed after preflight'
        source=self.f.root/'new-packet.json';atomic_json(source,packet)
        ref=managed.publish_evidence(self.f.state_path,source.name,source,digest(source))
        before=self.f.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError,'locked execution evidence'):
            managed.call(self.f.state_path,'commit',expected_sha256=digest(self.f.state_path),updates=[{
                'panel_id':'P001','attempt_id':'P001-r1','round_id':1,'status':'IN_FLIGHT','package_manifest':ref}])
        self.assertEqual(self.f.state_path.read_bytes(),before)

    def test_real_cli_admit_and_reserve(self):
        script=Path(managed.__file__); args=self.f.root/'managed-arguments.json'
        args.write_text(json.dumps({'expected_state':digest(self.f.state_path),'expected_control':digest(self.f.control_path),
            'old_writers_stopped':True,'immutable_inputs':True,'saver_protocol':'exclusive_evidence_v1','reason':'SYNTHETIC CLI'}), encoding='utf-8')
        def run(action,ok=True):
            p=subprocess.run([sys.executable,'-B',str(script),'--state',str(self.f.state_path),'--action',action,
                '--arguments',str(args)],capture_output=True,text=True,timeout=30, encoding='utf-8')
            self.assertEqual(p.returncode,0 if ok else 1,p.stdout+p.stderr);return json.loads(p.stdout)
        self.assertEqual(run('admit')['status'],'ADMITTED')
        args.write_text(json.dumps({'expected_state':digest(self.f.state_path),'expected_control':digest(self.f.control_path),
                                   'max_count':1,'request_id':'cli-request'}), encoding='utf-8')
        self.assertEqual(run('reserve')['status'],'RESERVED')
        proof=self.f.root/'cli-revoked-proof.json';atomic_json(proof,self.f.state['gates']['shot_design'])
        managed.call(self.f.state_path,'approvals',expected_state_sha256=digest(self.f.state_path),revoke=[{
            'approval':{'path':proof.name,'sha256':digest(proof)},'message':{'source_kind':'user_message',
            'source_locator':'SYNTHETIC_CLI','quote':'SYNTHETIC withdraw exact approval'}}])
        args.write_text(json.dumps({'expected_state':digest(self.f.state_path),'expected_control':digest(self.f.control_path),
                                   'max_count':1,'request_id':'cli-held-request'}), encoding='utf-8')
        held=run('reserve',ok=False);self.assertEqual(held['reserved'],[])

if __name__=='__main__':unittest.main()
