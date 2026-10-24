"""Scoped synthetic A-stage inputs; actual writer and executor, no image service."""
import copy,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
BASE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(BASE/'scripts'),str(Path(__file__).parent)]
from platform_io import atomic_json
from codex_reference_contract import digest,read_json
from submission_contract import fingerprint
import asset_runtime as assets
import runtime_clock as clock


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()/'run';self.root.mkdir()
        self.home=Path(self.temp.name)/'home'
        env=patch.dict(os.environ,{'CODEX_HOME':str(self.home)});env.start();self.addCleanup(env.stop)
        clock.initialize_context(self.root,'preparation',None)
        from PIL import Image
        Image.new('RGB',(20,20),'white').save(self.root/'approved.png')
        self.ref={'path':'approved.png','sha256':digest(self.root/'approved.png')}
        self.basis=self.put('basis.json',{'book_id':'BOOK','episode_id':'E001','asset_tasks':[
            {'asset_id':'VIEW','episode_id':'E001','panel_ids':['P001'],'source_basis':'SYNTHETIC script need'}]})
        self.auth=self.put('authorization.json',{'source_kind':'user_message','quote':'SYNTHETIC authorized asset test',
            'source_locator':'synthetic://not-human-production-approval','book_id':'BOOK','episode_ids':['E001'],
            'asset_ids':['VIEW'],'operations':['generate','repair','retry'],'max_asset_calls':2,'max_inflight':1})
        self.spec={'policy':'asset_call_definition_v1','operation':'generate','book_id':'BOOK','episode_id':'E001',
            'asset_id':'VIEW','attempt_id':'VIEW-A1','visual_basis':self.basis,'authorization':self.auth,
            'reference_files':[self.ref], 'arguments':{'prompt':'SYNTHETIC asset test',
                'referenced_image_paths':[str(self.root/'approved.png')]}}
        self.definition=self.put('asset-definition.json',self.spec)
        self.job=assets.compile_job(self.root,self.definition)[0]

    def put(self,name,value):
        p=self.root/name;atomic_json(p,value);return {'path':name,'sha256':digest(p)}

    def boundary(self,job=None,omit=False):
        cfg=Path(self.temp.name)/'boundary.json'
        atomic_json(cfg,{'scripts':str(BASE/'scripts'),'root':str(self.root),'python':sys.executable,
                        'protocol':'asset','job':job or self.job,'omitCallback':omit})
        p=subprocess.run(['node',str(Path(__file__).with_name('submission_boundary_probe.js')),str(cfg)],
                         capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(p.returncode,0,p.stderr);return json.loads(p.stdout)

    def result(self,status='GENERATED',attempt='VIEW-A1'):
        if status=='GENERATED':
            from PIL import Image
            Image.new('RGB',(20,20),'white').save(self.root/'returned.png')
            output={'path':'returned.png','sha256':digest(self.root/'returned.png')}
            request=self.put('request.json',{'source_kind':'observed_tool_call','source_locator':'synthetic://NO-REAL-REQUEST',
                'attempt_id':attempt,'arguments':self.spec['arguments']})
            response=self.put('response.json',{'source_kind':'observed_tool_result','source_locator':'synthetic://NO-REAL-RESULT',
                'attempt_id':attempt,'status':'COMPLETED','outputs':[output]})
            return {'status':status,'attempt_id':attempt,'output':output,'request_evidence':request,'response_evidence':response}
        return {'status':status,'attempt_id':attempt,'response_evidence':self.put('unknown.json',{
            'source_kind':'observed_tool_error','source_locator':'synthetic://error','attempt_id':attempt,
            'no_image_confirmed':status=='CALL_FAILED',
            'error':'explicit input rejection' if status=='CALL_FAILED' else 'connection unknown'})}

    def test_missing_callback_cannot_bypass_asset_registration(self):
        out=self.boundary(omit=True);self.assertEqual(out['touches'],0,out)
        self.assertFalse(assets.ledger_path(self.root).exists())

    def test_real_asset_cli_registers_once_and_replay_cannot_invoke(self):
        out=self.boundary();self.assertEqual(out['touches'],1,out)
        before=digest(assets.ledger_path(self.root))
        again=self.boundary();self.assertEqual(again['touches'],0,again)
        self.assertEqual(before,digest(assets.ledger_path(self.root)))

    def test_timed_paused_expired_and_missing_ledger_do_not_write(self):
        # Replace only this synthetic disabled context with a fresh timed fixture.
        (self.root/'00_任务协调/execution-context.json').unlink()
        clock.initialize_context(self.root,'preparation',1)
        d=self.root/'00_任务协调';clock.initialize(d,'preparation',1);clock.bind(d,'asset-test',self.home)
        clock.event(d,'start','start');self.job=assets.compile_job(self.root,self.definition)[0]
        clock.event(d,'pause','pause')
        self.assertEqual(self.boundary()['touches'],0)
        clock.event(d,'resume','resume')
        for p in [d/'runtime-clock.json',*(d/'clock-events').glob('*.json')]:
            x=read_json(p);stamps=([x['created']]+[e['at'] for e in x['events']]) if 'events' in x else [x['at']]
            for stamp in stamps:stamp['wall']-=30;stamp['mono']-=30
            atomic_json(p,x)
        out=self.boundary();self.assertEqual(out['touches'],0,out);self.assertIn('LIMIT_REACHED',json.dumps(out))
        (d/'runtime-clock.json').unlink()
        out=self.boundary();self.assertEqual(out['touches'],0,out);self.assertIn('LEDGER_MISSING',json.dumps(out))
        self.assertFalse(assets.ledger_path(self.root).exists())

    def test_saved_return_is_idempotent_and_conflicts_rejected(self):
        ack=assets.submit(self.root,self.job)
        result=self.result();assets.save(self.root,ack['registration_id'],result)
        self.assertEqual(assets.save(self.root,ack['registration_id'],result)['status'],'ASSET_RESULT_ALREADY_SAVED')
        with self.assertRaises(ValueError):assets.save(self.root,ack['registration_id'],self.result('CALL_FAILED'))
        self.assertFalse(read_json(assets.ledger_path(self.root)).get('asset_approval'))

    def test_asset_late_return_after_expiration_remains_savable(self):
        (self.root/'00_任务协调/execution-context.json').unlink()
        clock.initialize_context(self.root,'preparation',10)
        d=self.root/'00_任务协调';clock.initialize(d,'preparation',10);clock.bind(d,'late-return',self.home)
        clock.event(d,'start','start');job=assets.compile_job(self.root,self.definition)[0]
        ack=assets.submit(self.root,job)
        for p in [d/'runtime-clock.json',*(d/'clock-events').glob('*.json')]:
            x=read_json(p);stamps=([x['created']]+[e['at'] for e in x['events']]) if 'events' in x else [x['at']]
            for stamp in stamps:stamp['wall']-=120;stamp['mono']-=120
            atomic_json(p,x)
        self.assertEqual(clock.status(d)['remaining_seconds'],0)
        self.assertEqual(assets.save(self.root,ack['registration_id'],self.result())['status'],'ASSET_RESULT_SAVED')

    def test_unknown_holds_slot_requires_resolution_and_keeps_attempt(self):
        ack=assets.submit(self.root,self.job);unknown=self.result('RESULT_UNKNOWN')
        assets.save(self.root,ack['registration_id'],unknown)
        new=copy.deepcopy(self.spec);new['attempt_id']='VIEW-A2'
        job=assets.compile_job(self.root,self.put('new.json',new))[0]
        with self.assertRaisesRegex(ValueError,'CAPACITY_FULL'):assets.submit(self.root,job)
        result=self.result()
        with self.assertRaisesRegex(ValueError,'resolution'):assets.save(self.root,ack['registration_id'],result)
        token=fingerprint({k:result.get(k) for k in ('status','attempt_id','request_evidence','response_evidence','output')})
        proof=self.put('resolution.json',{'registration_id':ack['registration_id'],'attempt_id':'VIEW-A1',
            'source_kind':'observed_resolution','source_locator':'synthetic://located-original-output','result_digest':token})
        assets.save(self.root,ack['registration_id'],result,resolution=proof)
        self.assertEqual(len(read_json(assets.ledger_path(self.root))['attempts']),1)

    def test_repair_keeps_source_budget_and_cannot_reset_calls(self):
        ack=assets.submit(self.root,self.job);assets.save(self.root,ack['registration_id'],self.result())
        repair=copy.deepcopy(self.spec);repair.update(operation='repair',attempt_id='VIEW-A2',source_attempt_id='VIEW-A1',
            repair_evidence=self.put('diagnosis.json',{'source_attempt_id':'VIEW-A1','asset_id':'VIEW','episode_id':'E001',
                                                      'evidence':'SYNTHETIC failed view'}))
        job=assets.compile_job(self.root,self.put('repair.json',repair))[0]
        ack2=assets.submit(self.root,job);self.assertTrue(ack2['invoke_allowed'])
        assets.save(self.root,ack2['registration_id'],self.result('CALL_FAILED',attempt='VIEW-A2'))
        third=copy.deepcopy(self.spec);third['attempt_id']='VIEW-A3'
        with self.assertRaisesRegex(ValueError,'BUDGET_EXHAUSTED'):
            assets.submit(self.root,assets.compile_job(self.root,self.put('third.json',third))[0])

    def test_changed_inputs_and_out_of_scope_authorization_rejected(self):
        changed=copy.deepcopy(self.job);changed['arguments']['prompt']='changed'
        with self.assertRaisesRegex(ValueError,'binding changed'):assets.submit(self.root,changed)
        (self.root/'approved.png').write_bytes(b'changed')
        with self.assertRaises(ValueError):assets.submit(self.root,self.job)
        self.assertFalse(assets.ledger_path(self.root).exists())

    def test_wrong_owner_ledger_and_out_of_scope_authorization_are_rejected(self):
        path=assets.ledger_path(self.root)
        atomic_json(path,{'policy':'asset_call_ledger_v1','run_id':'another-owner','attempts':{}})
        before=digest(path)
        with self.assertRaisesRegex(ValueError,'another run'):assets.submit(self.root,self.job)
        self.assertEqual(before,digest(path))
        auth=read_json(self.root/'authorization.json');auth['asset_ids']=['OTHER']
        spec=copy.deepcopy(self.spec);spec['authorization']=self.put('other-auth.json',auth)
        with self.assertRaisesRegex(ValueError,'authorization'):
            assets.compile_job(self.root,self.put('other-definition.json',spec))

    def test_known_no_image_retry_retains_budget_and_original_attempt(self):
        ack=assets.submit(self.root,self.job)
        assets.save(self.root,ack['registration_id'],self.result('CALL_FAILED'))
        retry=copy.deepcopy(self.spec);retry.update(operation='retry',attempt_id='VIEW-A2',source_attempt_id='VIEW-A1',
            retry_evidence=self.put('retry-proof.json',{'source_attempt_id':'VIEW-A1','asset_id':'VIEW','episode_id':'E001',
                'no_image_confirmed':True,'evidence':'SYNTHETIC explicit request rejection'}))
        job=assets.compile_job(self.root,self.put('retry.json',retry))[0]
        self.assertTrue(assets.submit(self.root,job)['invoke_allowed'])
        rows=read_json(assets.ledger_path(self.root))['attempts'].values()
        self.assertEqual({r['attempt_id'] for r in rows},{'VIEW-A1','VIEW-A2'})


if __name__=='__main__':unittest.main()
