"""Official JSONL envelope adapters with real fixture state; no image service."""
import base64,io,json,subprocess,sys,unittest
from pathlib import Path
from PIL import Image
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import test_prepared_dispatch as fixtures
from test_generation_host import HOST
from codex_reference_contract import digest

class EnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.p=fixtures.PreparedDispatchTests();self.p.setUp();self.addCleanup(self.p.doCleanups);self.f=self.p.f
        state=json.loads(self.f.state_path.read_text());state['runtime_pipeline_policy']='observed_incremental_pipeline_v1'
        self.f.write(self.f.state_path,state)
    def action(self,action,**kw):
        req={'request_id':'envelope','action':action,**kw}
        proc=subprocess.run([sys.executable,'-B',str(HOST),'serve','--state',str(self.f.state_path)],
            input=json.dumps(req)+'\n',capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
        return json.loads(proc.stdout)['result']
    def job(self):
        return self.p.claim(self.p.prepare(('P001',))['jobs'][0])['job']
    def authorization(self):
        st=json.loads(self.f.state_path.read_text())
        value={'source_kind':'user_message','source_locator':'synthetic://user','quote':'synthetic recovery authorization',
          'book_id':st['book_id'],'episode_ids':[st['episode_id']],'panel_ids':['P001'],
          'operations':['no_image_retry','network_failure_delivery','content_failure_delivery']}
        p=self.f.write(self.f.root/'authorization.json',value)
        return {'path':p.name,'sha256':digest(p)}
    def test_official_bootstrap_with_real_jsonl_hosts(self):
        scripts=HOST.parent
        st=json.loads(self.f.state_path.read_text());st['image_review_profile']='light_story_review_v1';self.f.write(self.f.state_path,st)
        manifest={'book_id':self.f.state['book_id'],'dispatch_mode':'all_ready','compile_workers':'all','finalize_delivery':False,
            'python':sys.executable,'episodes':[{'episode_id':self.f.state['episode_id'],'panel_count':len(self.f.state['panels']),
                'state':str(self.f.state_path),'frozen_scripts':str(scripts),'generation_host':str(HOST)}]}
        mp=self.f.write(self.f.root/'batch.json',manifest)
        data=io.BytesIO();Image.new('RGB',(90,160),'blue').save(data,format='PNG')
        rp=self.f.write(self.f.root/'synthetic-result.json',{'image_url':'data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()})
        proc=subprocess.run(['node',str(Path(__file__).with_name('test_batch_bootstrap.js')),str(mp),str(rp)],
            capture_output=True,text=True,timeout=60)
        self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)

    def test_capture_register_and_prepare_actual_review(self):
        j=self.job();data=io.BytesIO();Image.new('RGB',(90,160),'blue').save(data,format='PNG')
        packet={'result':{'image_url':'data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()},
            'call_locator':'synthetic://call','result_locator':'synthetic://return'}
        cap=self.action('capture-envelope',job=j,packet=packet,item={})
        self.assertEqual(cap['status'],'RETURN_CAPTURED',cap)
        # Starting another host automatically replays the persisted return.
        r=self.action('register-return',capture=cap['capture'])
        self.assertIn(r['status'],{'RETURN_ALREADY_SAVED','UPDATES_SAVED'},r)
        qa=self.action('prepare-qa',panels=['P001'])
        self.assertEqual(qa['items'][0]['panel_id'],'P001',qa)
        self.assertIn('qa_template',qa['items'][0])
        st=json.loads(self.f.state_path.read_text());self.assertEqual(st['panels'][0]['status'],'GENERATED')
    def test_compile_light_review_and_real_other_panel_save_overlap(self):
        st=json.loads(self.f.state_path.read_text());st['image_review_profile']='light_story_review_v1';st['source_input_policy']='formal_source_inputs_v1';st.pop('round_reviews',None);self.f.write(self.f.state_path,st)
        refs=self.p.prepare(('P001','P002'))['jobs'];jobs=[self.p.claim(r)['job'] for r in refs]
        stream=io.BytesIO();Image.new('RGB',(90,160),'blue').save(stream,format='PNG')
        raw=self.f.write(self.f.root/'overlap-raw.json',{'image_url':'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode()})
        paths=[self.f.write(self.f.root/('job-'+str(i)+'.json'),j) for i,j in enumerate(jobs)]
        self.f.host('save-return','--job',paths[0],'--raw-result',raw,'--call-locator','synthetic://one','--result-locator','synthetic://one-return')
        qa=self.action('prepare-qa',panels=['P001'])['items'][0]
        saved=self.action('review-submit-batch',observations=[{'review_ticket':qa['review_ticket'],'observation':{
            'reviewer':'SYNTHETIC','reason':'SYNTHETIC fixture','verdict':'PASS','adopt':True,
            'light_observations':{'checks':{k:{'status':'PASS','observed':'SYNTHETIC fixture'} for k in ('identity','story_readability')},'issues':[]}}}])
        self.assertNotEqual(saved['status'],'HOLD',saved)
        frozen=Path(self.f.state['runtime_snapshot']['path']).parent/'skills/vertical-comic-preproduction/scripts'
        code="""
import json,sys,subprocess
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
import scoped_episode_workflow as scope
from light_review import evidence_errors
from codex_reference_contract import _FILE_SESSION
from prepared_job_store import PreparedStore
path=Path(sys.argv[2]);root=path.parent.parent
original=scope._evaluate_episode
saved=[]
def overlap(state,*args,**kwargs):
    row=next(r for r in state['panels'] if r['panel_id']=='P001')
    assert not evidence_errors(root,row,require_pass=True)
    from source_input_contract import FIELDS,PROGRESS,_supported
    assert str(path) not in _FILE_SESSION.get()['files'], ('full state input',_supported(state),set(state)-FIELDS-PROGRESS,state.get('source_input_policy'))
    call=subprocess.run([sys.executable,'-B',str(Path(sys.argv[1])/'generation_host.py'),'save-return','--state',str(path),
        '--job',sys.argv[3],'--raw-result',sys.argv[4],'--call-locator','synthetic://two','--result-locator','synthetic://two-return'],capture_output=True,text=True)
    assert call.returncode==0,call.stdout+call.stderr
    saved.append(json.loads(call.stdout)['status'])
    return original(state,*args,**kwargs)
with patch.object(scope,'_evaluate_episode',overlap):
    result=PreparedStore(path).prepare(['P003','P004'],2)
assert result['status']=='READY',result
assert saved and json.loads(path.read_text())['panels'][1]['status']=='GENERATED'
print(json.dumps({'status':'PASS','compiled':result['ready_panel_ids'],'saved_during_validation':saved,'image_calls':0}))
"""
        # Spawn needs a real main file, not a stdin/-c multiprocessing parent.
        script=self.f.root/'overlap-test.py';script.write_text('if __name__ == "__main__":\n'+''.join('    '+line+'\n' for line in code.splitlines()))
        result=subprocess.run([sys.executable,'-B',str(script),str(frozen),str(self.f.state_path),str(paths[1]),str(raw)],capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['compiled'],['P003','P004'])

    def test_unknown_not_retried_and_evidence_preserved(self):
        j=self.job()
        r=self.action('record-envelope',job=j,packet=None,item={'error':{'message':'connection lost'},'call_locator':'synthetic://unknown'},authorization=self.authorization())
        self.assertEqual(r['status'],'UNKNOWN_RECORDED',r);self.assertNotIn('recovery',r)
        self.assertEqual(json.loads(self.f.state_path.read_text())['panels'][0]['status'],'RESULT_UNKNOWN')
    def test_content_refusal_automatically_records_gap(self):
        j=self.job();r=self.action('record-envelope',job=j,packet={'result':{'isError':True}},
            item={'error':{'message':'moderation_blocked'},'call_locator':'synthetic://refusal'},authorization=self.authorization())
        self.assertEqual(r['status'],'FAILURE_RECORDED',r)
        self.assertEqual(r['recovery']['status'],'CONTENT_REFUSAL_DELIVERY',r)
        st=json.loads(self.f.state_path.read_text());self.assertEqual(st['delivery_materials']['P001']['outcome'],'CONTENT_REFUSED')
    def test_foreign_attempt_terminal_is_unknown_not_retry_permission(self):
        j=self.job()
        terminal={'no_image_confirmed':True,'outcome':'FAILED_NO_OUTPUT','attempt_id':'foreign-attempt',
            'registration_id':'foreign-registration','source_kind':'observed_tool_error',
            'source_locator':'synthetic://other-call','evidence':'observed failure belongs to another attempt'}
        result=self.action('record-envelope',job=j,packet={'terminal':terminal},
            item={'error':{'message':'network error'},'call_locator':'synthetic://current-call'},authorization=self.authorization())
        self.assertEqual(result['status'],'UNKNOWN_RECORDED');self.assertNotIn('recovery',result)
        state=json.loads(self.f.state_path.read_text())
        self.assertEqual(state['panels'][0]['attempt_id'],j['attempt_id'])

    def test_confirmed_network_failure_retries_four_then_gap(self):
        auth=self.authorization()
        for i in range(5):
            j=self.job()
            terminal={'no_image_confirmed':True,'outcome':'FAILED_NO_OUTPUT','attempt_id':j['attempt_id'],
                'registration_id':j['submission'].get('registration_id'),'source_kind':'observed_tool_error',
                'source_locator':'synthetic://network','evidence':'observed completed network failure'}
            from submission_contract import registration
            terminal['registration_id']=registration(j)[0]
            r=self.action('record-envelope',job=j,packet={'terminal':terminal},
                item={'error':{'message':'image generation failed: network error: error sending request'},'call_locator':'synthetic://network'},authorization=auth)
            self.assertEqual(r['status'],'FAILURE_RECORDED',r)
            self.assertEqual(r['recovery']['status'],'NO_IMAGE_RETRY_READY' if i<4 else 'NETWORK_RETRY_EXHAUSTED',r)

if __name__=='__main__':unittest.main()
