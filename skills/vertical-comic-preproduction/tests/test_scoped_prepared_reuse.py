"""Real prepared cache regressions; synthetic inputs, no image service."""
import copy, json, sys, unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).parents[1]/'scripts'),str(Path(__file__).parent)]
from test_generation_host import HostTests
from codex_reference_contract import digest
from prepared_job_store import PreparedStore


class ScopedReuse(unittest.TestCase):
    def setUp(self):
        self.f=HostTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.prepared=self.f.host('prepare-inputs','--panels','P001','P002')
        self.store=PreparedStore(self.f.state_path)
        self.ref=self.prepared['jobs'][0]

    def revise_audit(self,pid):
        f=self.f;s=json.loads(f.state_path.read_text())
        audit=json.loads((f.root/s['semantic_audit']['path']).read_text())
        row=next(r for r in audit['panels'] if r['panel_id']==pid)
        row['evidence']=str(row.get('evidence',''))+' SYNTHETIC note revision'
        p=f.write(f.root/'revised-audit.json',audit)
        s['semantic_audit']={'path':p.relative_to(f.root).as_posix(),'sha256':digest(p)}
        f.write(f.state_path,s);return s

    def test_unrelated_note_refreshes_without_compilation_and_claims(self):
        before=self.store.get(self.ref);self.revise_audit('P002')
        with patch('production_runtime.validate_panel',side_effect=AssertionError('must not compile')):
            after=self.store.get(self.ref)
            warm=self.store.prepare(['P001'])
        self.assertEqual(before['arguments'],after['arguments'])
        self.assertEqual(warm['reused_panel_ids'],['P001'])
        self.assertEqual(self.store.statistics['prepared'],0)
        result=self.f.host('claim-and-register','--job',self.f.write(self.f.root/'ref.json',self.ref))
        self.assertTrue(result['ack']['invoke_allowed'])

    def test_current_panel_note_reuses_but_verdict_change_blocks(self):
        self.revise_audit('P001')
        self.store.get(self.ref)
        f=self.f;s=json.loads(f.state_path.read_text());p=f.root/s['semantic_audit']['path']
        audit=json.loads(p.read_text());audit['panels'][0]['execution_review']['status']='UNREVIEWED'
        q=f.write(f.root/'negative-audit.json',audit);s['semantic_audit']={'path':q.name,'sha256':digest(q)};f.write(f.state_path,s)
        with self.assertRaisesRegex(ValueError,'SCOPED_INPUT_CHANGED'):self.store.get(self.ref)

    def test_unknown_global_field_is_not_ignored(self):
        f=self.f;s=json.loads(f.state_path.read_text());s['new_input_contract']='changed';f.write(f.state_path,s)
        with self.assertRaisesRegex(ValueError,'SCOPED_INPUT_CHANGED'):self.store.get(self.ref)

    def test_authority_removal_blocks_without_recompilation(self):
        f=self.f;s=self.revise_audit('P002');s['approval_index']={'path':'missing.json','sha256':'0'*64};f.write(f.state_path,s)
        with self.assertRaises((ValueError,OSError)):
            with patch('production_runtime.validate_panel',side_effect=AssertionError('must not compile')):self.store.get(self.ref)

    def test_restart_reuses_unchanged_inputs_after_note_revision(self):
        self.revise_audit('P002')
        r=self.f.host('prepare-inputs','--panels','P001')
        self.assertEqual(r['reused_panel_ids'],['P001'])
        self.assertEqual(r['jobs'][0],self.ref)

    def test_cached_refresh_still_checks_new_audit_file(self):
        s=self.revise_audit('P002');self.store.get(self.ref)
        (self.f.root/s['semantic_audit']['path']).write_text('{}')
        with self.assertRaises(ValueError):self.store.get(self.ref)

    def test_real_revocation_rejects_prepared_input(self):
        import subprocess
        f=self.f;s=json.loads(f.state_path.read_text())
        grant=f.write(f.root/'grant.json',s['gates']['shot_design'])
        changes=f.write(f.root/'changes.json',{'revoke':[{
            'approval':{'path':grant.name,'sha256':digest(grant)},
            'message':{'source_kind':'user_message','source_locator':'SYNTHETIC','quote':'SYNTHETIC revoke'}}]})
        code="""import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import generation_host
path,*_=generation_host.activate(sys.argv[2])
from authority_updates import update_approvals
from codex_reference_contract import digest
update_approvals(path,digest(path),**json.loads(Path(sys.argv[3]).read_text()))
"""
        result=subprocess.run([sys.executable,'-B','-c',code,str(Path(__file__).parents[1]/'scripts'),str(f.state_path),str(changes)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        with self.assertRaisesRegex(ValueError,'PREPARED_AUTHORITY_HOLD'):self.store.get(self.ref)

    def test_change_between_check_and_lock_cannot_register(self):
        from contextlib import contextmanager
        import runtime_pipeline as pipeline
        original=pipeline.state_write_lock
        @contextmanager
        def racing(*args,**kwargs):
            self.revise_audit('P002')
            with original(*args,**kwargs):yield
        with patch.object(pipeline,'state_write_lock',racing):
            with self.assertRaisesRegex(ValueError,'PREPARED_INPUT_OR_AUTHORITY_CHANGED'):
                pipeline.claim_and_register(self.f.state_path,self.ref)
        self.assertFalse(json.loads(self.f.state_path.read_text()).get('submission_registrations'))


if __name__=='__main__':unittest.main()
