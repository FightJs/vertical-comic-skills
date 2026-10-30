"""Bounded capture and notification regressions; no image service calls."""
import io,json,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import generation_host
from prepared_job_store import PreparedStore

class TransportTests(unittest.TestCase):
    def test_saturated_capture_does_not_block_control_reader(self):
        control=threading.Event();observed=[];lines=[]
        class Session:
            def __init__(self,**kw):pass
            def execute(self,request):
                if request['action']=='capture-envelope':
                    observed.append(control.wait(2))
                    return {'status':'RETURN_CAPTURED'}
                return {'status':'CONTROL_READ'}
        class Output(io.StringIO):
            def write(self,value):
                lines.append(value)
                if 'CONTROL_READ' in value:control.set()
                return len(value)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'00/state.json'
            requests=[{'request_id':n,'action':'capture-envelope'} for n in range(9)]
            requests.append({'request_id':'control','action':'delivery-status'})
            with patch.object(generation_host,'activate',return_value=(path,{'runtime_pipeline_policy':'observed_incremental_pipeline_v1'},root,root,'test')), \
                 patch.object(generation_host,'recover_returns'),patch('workflow_session.WorkflowSession',Session), \
                 patch('sys.stdin',io.StringIO(''.join(json.dumps(r)+'\n' for r in requests))),patch('sys.stdout',Output()):
                generation_host.serve(path)
        results=[json.loads(l) for l in ''.join(lines).splitlines()]
        self.assertEqual(len(results),10)
        self.assertTrue(all(observed));self.assertEqual(len(observed),8)
        self.assertEqual(sum(r['result'].get('error')=='CAPTURE_CAPACITY_BUSY_RETAIN_RETURN' for r in results),1)
        self.assertLess(next(i for i,r in enumerate(results) if r['request_id']=='control'),
                        next(i for i,r in enumerate(results) if r['result']['status']=='RETURN_CAPTURED'))

    def test_saved_receipt_survives_resource_bookkeeping_failure(self):
        class Session:
            def __init__(self,**kw):pass
            def execute(self,request):return {'status':'RETURN_CAPTURED','capture':{'path':'synthetic-saved'}}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'00/state.json';out=io.StringIO()
            req={'action':'capture-envelope','request_id':'saved','resource_token':'synthetic'}
            with patch.object(generation_host,'activate',return_value=(path,{'runtime_pipeline_policy':'observed_incremental_pipeline_v1'},root,root,'test')), \
                 patch.object(generation_host,'recover_returns'),patch('workflow_session.WorkflowSession',Session), \
                 patch('machine_resources.Coordinator.release',side_effect=OSError('synthetic resource ledger failure')), \
                 patch('sys.stdin',io.StringIO(json.dumps(req)+'\n')),patch('sys.stdout',out):
                generation_host.serve(path)
            result=json.loads(out.getvalue())['result']
            self.assertEqual(result['status'],'RETURN_CAPTURED');self.assertIn('resource_release_error',result)

    def test_notification_no_lost_wakeup_and_no_busy_poll(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=PreparedStore(Path(tmp)/'00/state.json')
            old=store.revision;store.notify_change()
            self.assertTrue(store.wait_for_change(old,0.1)['changed'])
            waiting=threading.Event();result=[]
            def wait():
                with store.changed:
                    revision=store.revision;waiting.set();result.append(store.wait_for_change(revision,1))
            t=threading.Thread(target=wait);t.start();waiting.wait()
            store.notify_change();t.join(2)
            self.assertFalse(t.is_alive());self.assertTrue(result[0]['changed'])
            self.assertFalse(store.wait_for_change(store.revision,0.01)['changed'])
            for value in (-1,True,'0'):
                with self.assertRaises(ValueError):store.wait_for_change(value,1)
