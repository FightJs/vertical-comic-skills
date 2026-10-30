"""Deterministic pressure/throughput and cross-process admission; no service calls."""
from pathlib import Path
import json,os,sys,tempfile,time,unittest,multiprocessing
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from machine_resources import Coordinator,GiB,MiB,boot_id

def normal_sample(disk):
    return {'known':True,'at':time.monotonic(),'boot':boot_id(),'cpus':8,'total':8*GiB,'available':5*GiB,
            'compressed':GiB,'swapout':0,'pressure':1,'disk_free':30*GiB}

def contender(home,ready,start,release):
    c=Coordinator(home,probe=normal_sample)
    start.wait(10);r=c.acquire('compile',str(os.getpid()),30)
    ready.put((r['status'],r.get('units',0)))
    release.wait(10)
    if r['status']=='RESOURCE_GRANTED':c.release(r['token'])

class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.now=100.;self.sample=normal_sample(self.tmp.name)
        self.c=Coordinator(self.tmp.name,probe=self.probe,clock=lambda:self.now)
    def probe(self,disk):return {**self.sample,'at':self.now}
    def step(self,seconds=3):self.now+=seconds
    def test_five_episodes_share_two_workers_and_images_are_independent(self):
        first=self.c.acquire('compile','E1',30);self.assertEqual(first['units'],2)
        for episode in range(2,6):self.assertEqual(self.c.acquire('compile',str(episode),30)['status'],'RESOURCE_WAIT')
        images=[self.c.acquire('image',str(i)) for i in range(4)]
        self.assertTrue(all(x['status']=='RESOURCE_GRANTED' for x in images))
        self.assertEqual(self.c.acquire('image','fifth')['status'],'RESOURCE_WAIT')
        self.assertEqual(self.c.status()['active'],{'compile':2,'image':4,'host':0})
    def test_measured_probe_grows_then_rolls_back_without_gain(self):
        a=self.c.acquire('compile','E1',30)
        for _ in range(5):self.c.progress(a['token'],completed=1)
        self.step(61);s=self.c.status();self.assertEqual(s['limits']['compile'],3)
        self.c.release(a['token']);a=self.c.acquire('compile','E1',30)
        self.assertEqual(a['units'],3)
        for _ in range(5):self.c.progress(a['token'],completed=1)
        self.step(61);s=self.c.status();self.assertEqual(s['limits']['compile'],2)
    def test_pressure_drains_without_revoking_existing_calls(self):
        c=self.c.acquire('compile','E1',30);i=self.c.acquire('image','P1')
        self.sample.update(pressure=4,available=100*MiB);self.step()
        s=self.c.progress(c['token']);self.assertTrue(s['drain'])
        self.assertEqual(s['active']['image'],1)
        self.assertEqual(self.c.acquire('image','P2')['status'],'RESOURCE_WAIT')
        self.assertEqual(self.c.release(i['token'])['status'],'RESOURCE_RELEASED')
        self.assertEqual(self.c.release(i['token'])['status'],'RESOURCE_RELEASED')
    def test_capture_bytes_and_age_block_new_calls_but_allow_save(self):
        r=self.c.acquire('image','P1');self.c.returned(r['token'],600*MiB)
        self.assertEqual(self.c.acquire('image','P2')['status'],'RESOURCE_WAIT')
        self.c.release(r['token'],preserved=False)
        self.assertEqual(self.c.status()['active']['image'],1)
        self.c.release(r['token'],preserved=True)
        self.assertEqual(self.c.status()['pending_bytes'],0)
        r=self.c.acquire('image','P2');self.c.returned(r['token'],MiB);self.step(11)
        self.assertTrue(self.c.status()['backlog'])
    def test_lost_parent_does_not_release_a_live_compile_child(self):
        r=self.c.acquire('compile','E1');data=json.loads(self.c.path.read_text())
        data['leases'][r['token']]['owner']={'pid':123456,'birth':'old'}
        data['leases'][r['token']]['children']=[{'pid':123457,'birth':'child'}]
        self.c.path.write_text(json.dumps(data));self.c.liveness=lambda i:i['pid']==123457
        self.assertEqual(self.c.status()['active']['compile'],1)
        self.c.liveness=lambda i:False;self.step()
        self.assertEqual(self.c.status()['active']['compile'],0)
    def test_unknown_probe_is_bounded_and_explicit_low_request_kept(self):
        self.sample={'known':False,'boot':boot_id(),'cpus':100};self.step()
        self.assertEqual(self.c.status()['hard'],{'compile':1,'image':2,'host':1})
        self.assertEqual(self.c.acquire('compile','E1',1)['units'],1)
    def test_reboot_drops_only_local_machine_leases(self):
        self.c.acquire('image','old');d=json.loads(self.c.path.read_text());d['boot']='old-boot';self.c.path.write_text(json.dumps(d))
        self.assertEqual(self.c.status()['active']['image'],0)
    def test_low_disk_and_large_snapshot_prevent_new_work(self):
        self.sample['disk_free']=GiB;self.step()
        self.assertEqual(self.c.acquire('compile','E1',35)['status'],'RESOURCE_WAIT')
        self.sample['disk_free']=30*GiB;self.step(65)
        self.assertEqual(self.c.acquire('compile','E1',35,estimated_bytes=6*GiB)['status'],'RESOURCE_WAIT')
        self.assertEqual(self.c.status()['active']['compile'],0)
    def test_saved_replay_releases_only_exact_attempt_debt(self):
        one=self.c.acquire('image','E1/P1/A1');two=self.c.acquire('image','E1/P1/A2')
        self.c.returned(one['token'],MiB);self.c.release(one['token'],preserved=False)
        self.c.release_image_key('E1/P1/A1')
        self.assertEqual(self.c.status()['active']['image'],1)
        self.assertEqual(self.c.acquire('image','E1/P1/A2')['token'],two['token'])

    def test_degraded_one_probes_before_four_slow_returns(self):
        self.sample.update(pressure=4,available=100*MiB);self.c.status()
        self.step(6);self.c.status()
        self.sample.update(pressure=1,available=5*GiB);self.step(3)
        a=self.c.acquire('image','slow')
        self.assertEqual(a['limits']['image'],1)
        self.step(61);self.assertEqual(self.c.status()['limits']['image'],2)
        b=self.c.acquire('image','second');self.assertEqual(b['status'],'RESOURCE_GRANTED')
        self.step(240);self.assertEqual(self.c.status()['limits']['image'],2)
        self.assertEqual(self.c.status()['active']['image'],2)
        self.c.release(a['token'],completed=True);self.c.release(b['token'],completed=True)

    def test_idle_does_not_reset_learned_limit_and_failures_are_not_throughput(self):
        self.c.status();s=json.loads(self.c.path.read_text());s['limits']['image']=1;s['adaptive_limits_v2']['image']=1
        self.c.path.write_text(json.dumps(s));self.step(1000)
        self.assertEqual(self.c.status()['limits']['image'],1)
        for i in range(5):
            a=self.c.acquire('image',str(i));self.c.release(a['token'],completed=False)
        self.assertEqual(json.loads(self.c.path.read_text())['windows']['image']['done'],0)
        self.assertFalse(any(h['reason']=='measured_throughput' for h in self.c.status()['history']))

    def test_host_admission_recovers_and_dead_parent_keeps_live_owner(self):
        a=self.c.acquire('host','E1');self.assertEqual(a['units'],1)
        self.assertEqual(self.c.acquire('host','E2')['status'],'RESOURCE_WAIT')
        self.step(59);self.c.acquire('host','E2');self.step(2);b=self.c.acquire('host','E2');self.assertEqual(b['status'],'RESOURCE_GRANTED')
        self.sample.update(pressure=4,available=100*MiB);self.step()
        s=self.c.status();self.assertEqual(s['limits']['host'],1);self.assertEqual(s['active']['host'],2)
        self.c.release(b['token']);self.c.release(a['token'])

    def test_legacy_idle_reset_does_not_erase_adaptive_target_or_live_leases(self):
        a=self.c.acquire('image','existing')
        state=json.loads(self.c.path.read_text());state['adaptive_limits_v2']['image']=1
        state['limits']['image']=4  # An unchanged frozen v1 coordinator wrote its idle reset.
        self.c.path.write_text(json.dumps(state))
        value=self.c.status();self.assertEqual(value['limits']['image'],1)
        self.assertEqual(value['active']['image'],1)
        self.assertEqual(self.c.acquire('image','existing')['token'],a['token'])

    def test_resume_resets_probe_only_not_leases_or_learned_capacity(self):
        a=self.c.acquire('image','slow');self.c.observe_run('run',{'wall':100})
        self.step(61);self.c.status()
        before=self.c.status()['limits'].copy()
        self.c.observe_run('run',{'wall':500})
        state=json.loads(self.c.path.read_text())
        self.assertEqual(state['limits'],before);self.assertIn(a['token'],state['leases'])
        self.assertTrue(all(w.get('probe') is None for w in state['windows'].values()))
        self.assertEqual(state['history'][-1]['reason'],'resume_observation_reset')

    def test_actual_processes_cannot_each_take_a_full_episode(self):
        Coordinator(self.tmp.name,probe=normal_sample).status() # Establish the shared probe before the admission race.
        ctx=multiprocessing.get_context('spawn');q=ctx.Queue();start=ctx.Event();release=ctx.Event()
        ps=[ctx.Process(target=contender,args=(self.tmp.name,q,start,release)) for _ in range(5)]
        for p in ps:p.start()
        try:
            start.set();rows=[q.get(timeout=15) for _ in ps]
            self.assertEqual(sum(n for status,n in rows),2)
        finally:
            release.set()
            for p in ps:p.join(10)
            for p in ps:
                if p.is_alive():p.terminate();p.join()
        self.assertTrue(all(p.exitcode==0 for p in ps))

if __name__=='__main__':unittest.main()
