"""Parallel preparation and bounded publication, synthetic only; no image calls."""
import copy, json, os, pickle, shutil, sys, tempfile, threading, time, unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).parents[1]/'scripts'),str(Path(__file__).parent)]
import prepared_job_store as prepared
from codex_reference_contract import file_session


def synthetic_panel(pid):
    # Top-level function is spawn-picklable; use the real worker initializer.
    state,original,root,batch,shots,basis,records=pickle.loads(prepared._WORKER_INPUTS)
    started=time.monotonic()
    time.sleep(.25 if pid=='P000' else .025)
    return pid,records[pid],{'synthetic':True},{},{'panel_id':pid,'status':'PASS','errors':[],
        'started':started,'ended':time.monotonic(),'process':os.getpid()}


class ParallelPreparation(unittest.TestCase):
    def test_changed_private_snapshot_is_rejected_before_deserialization(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'inputs.pickle';path.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'PREPARE_SNAPSHOT_CHANGED'):
                prepared._initialize_prepare_worker(path,'0'*64)

    def test_real_spawn_overlap_bounded_tasks_and_early_publication(self):
        ids=['P%03d'%i for i in range(16)];published=[]
        with tempfile.TemporaryDirectory() as folder, file_session(), patch.object(prepared,'_prepare_panel',synthetic_panel):
            from machine_resources import Coordinator
            from test_machine_resources import normal_sample
            home=Path(folder)/'resources';Coordinator(home,probe=normal_sample).status()
            with patch.dict(os.environ,{'COMIC_RESOURCE_HOME':str(home)}):
                result=prepared.parallel_checks(ids,ids,{}, {},folder,{}, {},{},
                    {p:{'panel_id':p} for p in ids},lambda pid,*args:published.append((pid,time.monotonic())),12)
        self.assertEqual(result['ready_panel_ids'],ids)
        self.assertEqual(len(published),len(ids));self.assertNotEqual(published[0][0],'P000')
        rows=result['reports'];self.assertGreater(len({r['process'] for r in rows}),1)
        self.assertTrue(any(a['process']!=b['process'] and max(a['started'],b['started'])<min(a['ended'],b['ended']) for a in rows for b in rows))
        self.assertLess(published[0][1],max(r['ended'] for r in rows))
        self.assertLessEqual(result['compilation']['peak_pending'],24)
        self.assertLessEqual(result['compilation']['workers'],2)
        self.assertEqual(result['compilation']['requested_workers'],12)
        self.assertEqual(result['compilation']['submitted'],16)
        self.assertFalse(result['dispatch_authorized']);self.assertEqual(result['image_calls'],0)

    def test_no_eligible_work_does_not_spawn_pool(self):
        with tempfile.TemporaryDirectory() as folder,file_session(),patch.object(prepared,'ProcessPoolExecutor',side_effect=AssertionError('no work')):
            result=prepared.parallel_checks(['blocked'],[],{}, {},folder,{}, {},{},{},None,4)
        self.assertEqual(result['status'],'HOLD');self.assertEqual(result['compilation']['workers'],0)

    def test_lifecycle_includes_cache_discovery_and_rejects_duplicate_prepare(self):
        with tempfile.TemporaryDirectory() as folder:
            store=prepared.PreparedStore(Path(folder)/'state.json');store.preparation_started=True
            entered=threading.Event();release=threading.Event();errors=[]
            def slow(*args):entered.set();release.wait(5);raise ValueError('synthetic discovery failure')
            def run():
                try:store.prepare()
                except ValueError as exc:errors.append(str(exc))
            with patch.object(store,'_prepare',slow):
                thread=threading.Thread(target=run);thread.start()
                try:
                    self.assertTrue(entered.wait(2));self.assertTrue(store.preparing)
                    with self.assertRaisesRegex(ValueError,'ALREADY_RUNNING'):store.prepare()
                finally:release.set();thread.join(5)
            self.assertFalse(store.preparing);self.assertEqual(errors,['synthetic discovery failure'])
            self.assertEqual(store.preparation_error,errors[0])


class RealPreparedEquivalence(unittest.TestCase):
    def test_one_and_four_workers_same_inputs_warm_reuse_and_ready_limit(self):
        from test_generation_host import HostTests
        import subprocess
        f=HostTests();f.setUp();self.addCleanup(f.doCleanups)
        frozen=Path(f.state['runtime_snapshot']['path']).parent/'skills/vertical-comic-preproduction/scripts'
        code="""
import sys,json,shutil
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
import prepared_job_store as prepared
from workflow_session import WorkflowSession
path=Path(sys.argv[2]);ids=['P001','P002','P003','P004']
first=prepared.PreparedStore(path);a=first.prepare(ids,1)
assert a['status']=='READY',a
expected={r['panel_id']:first.get(r)['arguments'] for r in a['jobs']}
shutil.rmtree(first.folder)
second=prepared.PreparedStore(path);b=second.prepare(ids,4)
assert b['status']=='READY',b
assert expected=={r['panel_id']:second.get(r)['arguments'] for r in b['jobs']}
with patch.object(prepared,'parallel_checks',side_effect=AssertionError('hot inputs must not compile')):
    warm=second.prepare(ids,4)
assert warm['reused_panel_ids']==ids
calls=[];real_get=second.get
def observe(ref,*args,**kwargs):calls.append(ref['panel_id']);return real_get(ref,*args,**kwargs)
with patch.object(prepared,'store',return_value=second),patch.object(second,'get',side_effect=observe):
    response=WorkflowSession().execute({'action':'ready-inputs','state':str(path),'record_timing':False,
        'limit':1,'panels':['P001','P002'],'exclude_record_digests':[b['jobs'][0]['record_digest']]})
assert [r['panel_id'] for r in response['jobs']]==['P002'],response
assert calls==['P002'],calls
assert response['preparation_complete']
print(json.dumps({'same_arguments':True,'warm_reused':warm['reused_panel_ids'],
    'one_worker':a['compilation'],'four_workers':b['compilation']}))
"""
        result=subprocess.run([sys.executable,'-B','-c',code,str(frozen),str(f.state_path)],capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        value=json.loads(result.stdout);self.assertTrue(value['same_arguments'])
        self.assertEqual(len(value['warm_reused']),4)



if __name__=='__main__':unittest.main()
