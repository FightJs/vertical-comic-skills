"""Real frozen entrypoints, synthetic evidence, no service or production state."""
import base64,copy,io,json,sys,unittest
from pathlib import Path
from PIL import Image
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
from test_generation_host import HostTests

class PreparedDispatchTests(unittest.TestCase):
    def setUp(self):
        self.f=HostTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
    def prepare(self,ids=('P001','P002')):
        r=self.f.host('prepare-inputs','--panels',*ids)
        self.assertEqual(r['status'],'READY',r)
        return r
    def claim(self,ref,ok=True):
        p=self.f.write(self.f.root/'ref.json',ref)
        return self.f.host('claim-and-register','--job',p,ok=ok)
    def test_prepare_reuse_no_attempt_or_authority(self):
        before=self.f.state_path.read_bytes();first=self.prepare();second=self.prepare()
        self.assertEqual(before,self.f.state_path.read_bytes())
        self.assertFalse(first['dispatch_authorized'])
        self.assertEqual(first['jobs'],second['jobs'])
        self.assertEqual(second['reused_panel_ids'],['P001','P002'])
    def test_atomic_registration_replay_and_unrelated_progress(self):
        refs=self.prepare()['jobs'];a=self.claim(refs[0]);again=self.claim(refs[0])
        self.assertTrue(a['ack']['invoke_allowed']);self.assertFalse(again['ack']['invoke_allowed'])
        b=self.claim(refs[1]);self.assertTrue(b['ack']['invoke_allowed'])
        state=json.loads(self.f.state_path.read_text())
        self.assertEqual(len(state['submission_registrations']),2)
        self.assertEqual(state['panels'][0]['package_manifest'],a['job']['package_manifest'])
    def test_changed_reference_rejected_before_registration(self):
        ref=self.prepare(('P001',))['jobs'][0]
        folder=self.f.state_path.parent/'prepared_inputs'
        value=json.loads((folder/(ref['record_digest']+'.json')).read_text())
        image=Path(value['arguments']['referenced_image_paths'][0]);image.write_bytes(b'changed')
        before=self.f.state_path.read_bytes();r=self.claim(ref,ok=False)
        self.assertIn('CHANGED',r['error']);self.assertEqual(before,self.f.state_path.read_bytes())
    def test_changed_authority_rejected(self):
        ref=self.prepare(('P001',))['jobs'][0]
        state=json.loads(self.f.state_path.read_text());state['cancelled']=True;self.f.write(self.f.state_path,state)
        self.claim(ref,ok=False)
    def test_return_keeps_exact_identity_and_other_prepared_inputs(self):
        refs=self.prepare()['jobs'];out=self.claim(refs[0]);jp=self.f.write(self.f.root/'job.json',out['job'])
        b=io.BytesIO();Image.new('RGB',(90,160),'white').save(b,format='PNG')
        raw=self.f.write(self.f.root/'raw.json',{'image_url':'data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()})
        args=('--job',jp,'--raw-result',raw,'--call-locator','synthetic://call','--result-locator','synthetic://return')
        saved=self.f.host('save-return',*args)
        self.assertEqual(saved['visual_review'],'UNREVIEWED')
        self.assertEqual(self.f.host('save-return',*args)['status'],'RETURN_ALREADY_SAVED')
        self.assertTrue(self.claim(refs[1])['ack']['invoke_allowed'])
    def test_forged_job_cannot_save(self):
        out=self.claim(self.prepare(('P001',))['jobs'][0]);job=out['job'];job['arguments']['prompt']+='changed'
        jp=self.f.write(self.f.root/'job.json',job)
        b=io.BytesIO();Image.new('RGB',(90,160),'white').save(b,format='PNG')
        raw=self.f.write(self.f.root/'raw.json',{'image_url':'data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()})
        r=self.f.host('save-return','--job',jp,'--raw-result',raw,'--call-locator','synthetic://call','--result-locator','synthetic://return',ok=False)
        self.assertIn('REGISTRATION_MISMATCH',r['error'])
        self.assertEqual(json.loads(self.f.state_path.read_text())['panels'][0]['status'],'IN_FLIGHT')

    def test_lease_capacity_and_owner_change(self):
        from platform_io import atomic_json
        from codex_reference_contract import digest
        from slot_leases import allocate,POLICY
        state=json.loads(self.f.state_path.read_text());control_path=self.f.root.parent/'control.json'
        context={'control_file':str(control_path),'job_id':'job','worker_id':'worker','epoch':1}
        state['parallel_context']=context;state['runtime']['dispatch_policy']=POLICY
        basis=state['visual_basis']
        shared=[{'path':str(self.f.root/basis['path']),'sha256':basis['sha256'],'role':'style_basis'}]
        control={'policy':'parallel_episodes_v1','version':1,'book_id':state['book_id'],'epoch':1,
                 'cancelled':False,'holds':[],'max_workers':1,'max_inflight':1,'shared_files':shared,'permits':[],
                 'jobs':[{'job_id':'job','worker_id':'worker','episode_id':state['episode_id'],'root':str(self.f.root),
                          'status':'RUNNING','max_inflight':1,'active_batch_id':'EPISODE',
                          'frozen_inputs':{k:state[k] for k in ('source_script','source_snapshot','visual_basis','shot_manifest')}}]}
        atomic_json(self.f.state_path,state);atomic_json(control_path,control)
        allocate(control_path,digest(control_path),{'job':1})
        refs=self.prepare()['jobs'];one=self.claim(refs[0]);self.assertTrue(one['ack']['invoke_allowed'])
        self.assertEqual(self.claim(refs[1])['status'],'CAPACITY_FULL')
        control=json.loads(control_path.read_text());control['jobs'][0]['worker_id']='another';atomic_json(control_path,control)
        self.claim(refs[1],ok=False)

    def test_new_claim_never_runs_full_preflight(self):
        # The subprocess instrumentation fails if the new dispatch re-enters any whole gate.
        refs=self.prepare(('P001',))['jobs'];ref=self.f.write(self.f.root/'ref.json',refs[0])
        import subprocess
        script=Path(__file__).parents[1]/'scripts/generation_host.py'
        code="""import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import generation_host
path,state,root,scripts,kind=generation_host.activate(sys.argv[2])
import staged_workflow,scoped_episode_workflow
staged_workflow.preflight_many=lambda *a,**k:(_ for _ in ()).throw(AssertionError('full preflight'))
scoped_episode_workflow.evaluate_episode=lambda *a,**k:(_ for _ in ()).throw(AssertionError('whole episode'))
from runtime_pipeline import claim_and_register
print(json.dumps(claim_and_register(path,json.loads(Path(sys.argv[3]).read_text()))))
"""
        result=subprocess.run([sys.executable,'-B','-c',code,str(script.parent),str(self.f.state_path),str(ref)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(json.loads(result.stdout)['ack']['invoke_allowed'])

if __name__=='__main__':unittest.main()
