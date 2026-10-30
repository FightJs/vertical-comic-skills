import errno,sys,tempfile,unittest
from pathlib import Path
from concurrent.futures import Future
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import prepared_job_store as store
from codex_reference_contract import file_session

class AllCompileTests(unittest.TestCase):
    def test_full_scope_and_explicit_limits(self):
        self.assertEqual(store.worker_count('all',35),35)
        self.assertEqual(store.worker_count(30,35),30)
        self.assertEqual(store.worker_count('all',0),0)
        with self.assertRaises(ValueError):store.worker_count(0,35)
        with patch.object(store.os,'name','nt'):self.assertEqual(store.worker_count('all',165),61)
    def test_resource_retry_keeps_completed_results(self):
        calls=[];pools=[]
        class Pool:
            def __init__(self,max_workers,**kw):self.number=len(pools);pools.append(max_workers);self.count=0
            def __enter__(self):return self
            def __exit__(self,*a):return False
            def submit(self,fn,pid):
                self.count+=1
                if self.number==0 and self.count==3:raise OSError(errno.EAGAIN,'synthetic spawn limit')
                calls.append(pid);f=Future();f.set_result((pid,{},None,{}, {'panel_id':pid,'status':'PASS','errors':[]}));return f
        ids=['P1','P2','P3','P4']
        from machine_resources import Coordinator
        from test_machine_resources import normal_sample
        with tempfile.TemporaryDirectory() as t,file_session(),patch.object(store,'ProcessPoolExecutor',Pool):
            controller=Coordinator(Path(t)/'resources',probe=normal_sample)
            with patch('machine_resources.Coordinator',return_value=controller):
                r=store.parallel_checks(ids,ids,{}, {},Path(t),{}, {},{}, {},None,'all')
        self.assertEqual(r['status'],'READY');self.assertEqual(pools,[2,1]);self.assertEqual(calls,ids)
        self.assertEqual(len(r['compilation']['resource_fallbacks']),1)
    def test_35_165_unchanged_reuse_and_local_change_selection(self):
        import json
        from contextlib import nullcontext
        for count in (35,165):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);audit=root/'00_输入审计';audit.mkdir();path=audit/'生产流程.json'
                state={'book_id':'SYNTHETIC','episode_id':'E1','execution_mode':'episode_async_v1',
                    'panels':[{'panel_id':f'P{i:03}','status':'PENDING','attempt_id':f'A{i}',
                        'round_id':1,'package_manifest':{'path':f'p{i}.json','sha256':'a'*64}} for i in range(count)]}
                path.write_text(json.dumps(state));cache=store.PreparedStore(path)
                for i,row in enumerate(state['panels']):
                    key=f'{i+1:064x}';value={**row,'book_id':'SYNTHETIC','episode_id':'E1','prepared_input_id':key,
                        'record_digest':key,'state_basis':store.state_basis(state),'dependencies':{},
                        'common_reads':{'policy':'receiver_read_set_v1','reusable':True,'files':[],'observations':[]},
                        'panel_reads':{'policy':'receiver_read_set_v1','reusable':True,'files':[],'observations':[]}}
                    cache.entries[key]=value;cache.ready[row['panel_id']]=key
                with patch('scoped_episode_workflow._evaluate_episode',side_effect=AssertionError('must not compile')):
                    result=cache.prepare();self.assertEqual(len(result['reused_panel_ids']),count)
                state['panels'][3]['package_manifest']={**state['panels'][3]['package_manifest'],'sha256':'b'*64}
                path.write_text(json.dumps(state))
                def evaluate(state,root,check,selection,**kw):
                    self.assertEqual(selection,['P003']);return {'ready_panel_ids':[],'reports':[]}
                with patch('scoped_episode_workflow._evaluate_episode',side_effect=evaluate) as compiled, \
                     patch('panel_readiness.review_context',return_value=nullcontext()), \
                     patch('authority_updates.authority_context',return_value=nullcontext()):
                    result=cache.prepare();self.assertEqual(len(result['reused_panel_ids']),count-1);self.assertEqual(compiled.call_count,1)

    def test_broken_worker_is_not_invented_oom(self):
        from concurrent.futures.process import BrokenProcessPool
        self.assertFalse(store.resource_error(BrokenProcessPool('unknown cause')))
        self.assertFalse(store.resource_error(OSError(errno.EIO,'disk failure')))

if __name__=='__main__':unittest.main()
