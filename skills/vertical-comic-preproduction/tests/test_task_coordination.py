import json
import multiprocessing
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import task_coordination as tc
import production_progress as progress

def concurrent_register(directory, name, ready, release, results):
    ready.set()
    if not release.wait(20):
        results.put('timeout'); return
    try:
        tc.update(directory, 0, {'action':'register','event_id':name,'task_id':name,
                                'host_id':name,'assignment':'并发演练'})
        results.put('committed')
    except ValueError:
        results.put('stale')

class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.display = self.root/'00_显示进度'
        self.display.mkdir(); (self.display/'task.json').write_text(json.dumps({'scope': [['书','E001']]}))
        self.directory = self.root/'00_任务协调'; tc.initialize(self.directory, self.display)
        self.counter = 0
        self.evidence = self.root/'观察.json'; self.evidence.write_text('{"observed":true}')
        self.artifact = self.root/'成果.txt'; self.artifact.write_text('成品', encoding='utf-8')
    def event(self, action, **kw):
        self.counter += 1
        event = {'event_id': str(self.counter), 'action': action, **kw}
        v = tc.read(self.directory/'coordination.json')
        return tc.update(self.directory, v['revision'], event)
    def register(self, key='A', **kw):
        return self.event('register', task_id=key, host_id='host:'+key, assignment='E001镜头', **kw)
    def ready(self):
        return self.event('observe',task_id='A',status='RESULT_READY',evidence=tc.reference(self.evidence),artifacts=[tc.reference(self.artifact)])
    def accept(self):
        return self.event('accept',task_id='A',evidence=tc.reference(self.evidence),reviewer='总控',conclusion='实际核对通过')
    def test_running_and_unreviewed_results_prevent_final_validation(self):
        v=self.register()
        with patch('production_progress.complete') as complete:
            self.assertEqual(tc.finish(self.directory,v['revision'],self.artifact)['status'],'CONTINUE_REQUIRED')
            v=self.ready()
            self.assertEqual(tc.finish(self.directory,v['revision'],self.artifact)['status'],'CONTINUE_REQUIRED')
            complete.assert_not_called()
    def test_acceptance_cannot_precede_host_completion(self):
        self.register()
        with self.assertRaises(ValueError): self.accept()
    def test_changed_artifact_invalidates_acceptance(self):
        self.register(); self.ready(); v=self.accept()
        self.artifact.write_text('changed')
        self.assertTrue(tc.pending(v))
    def test_resume_never_respawns_unknown_worker(self):
        self.register(); self.event('observe',task_id='A',status='UNKNOWN',evidence=tc.reference(self.evidence))
        old=(self.directory/'coordination.json').read_bytes()
        self.assertEqual(tc.resume(self.directory)['tasks']['A']['status'],'UNKNOWN')
        self.assertEqual(old,(self.directory/'coordination.json').read_bytes())
    def test_stale_coordinator_and_conflicting_event_rejected(self):
        v=self.register(); event=v['events'][0]
        self.assertEqual(tc.update(self.directory,0,event),v)
        with self.assertRaises(ValueError): tc.update(self.directory,0,{**event,'assignment':'other'})
        with self.assertRaises(ValueError): tc.update(self.directory,0,{**event,'event_id':'new','task_id':'B'})
    def test_required_stopped_task_still_blocks(self):
        self.register(); v=self.event('observe',task_id='A',status='STOPPED',evidence=tc.reference(self.evidence))
        self.assertTrue(tc.pending(v))
    def test_optional_stop_requires_evidence(self):
        self.register(required=False)
        v=self.event('observe',task_id='A',status='STOPPED',evidence=tc.reference(self.evidence))
        self.assertFalse(tc.pending(v))
        self.evidence.write_text('changed'); self.assertTrue(tc.pending(v))
    def test_delivery_validation_failure_does_not_mark_finished(self):
        self.register(); self.ready(); v=self.accept()
        with self.assertRaises(Exception): tc.finish(self.directory,v['revision'],self.artifact)
        self.assertNotIn('finish',tc.read(self.directory/'coordination.json'))
    def test_success_binds_archive_and_new_events_invalidate_finish(self):
        self.register(); self.ready(); v=self.accept()
        with patch('production_progress.complete',return_value={'percent':100}):
            result=tc.finish(self.directory,v['revision'],self.artifact)
        self.assertEqual(result['archive'],tc.reference(self.artifact))
        v=self.register('B'); self.assertNotIn('finish',v)
    def test_display_cannot_bypass_coordination(self):
        with self.assertRaisesRegex(ValueError,'finish-check'): progress.complete(self.display,self.artifact)
    def test_cli_round_trip_utf8_and_failed_cas(self):
        cli=Path(tc.__file__)
        result=subprocess.run([sys.executable,str(cli),'resume','--directory',str(self.directory)],capture_output=True)
        self.assertEqual(result.returncode,0)
        self.assertEqual(json.loads(result.stdout)['status'],'RECONCILE_BEFORE_RESUME')
    def test_two_processes_cannot_commit_same_revision(self):
        ctx=multiprocessing.get_context('spawn'); release=ctx.Event(); results=ctx.Queue()
        signals=[ctx.Event(),ctx.Event()]
        workers=[ctx.Process(target=concurrent_register,args=(str(self.directory),str(i),signals[i],release,results)) for i in range(2)]
        try:
            for worker in workers: worker.start()
            for signal in signals: self.assertTrue(signal.wait(20))
            release.set()
            outcomes=[results.get(timeout=20) for _ in workers]
            self.assertCountEqual(outcomes,['committed','stale'])
            for worker in workers:
                worker.join(20); self.assertEqual(worker.exitcode,0)
            self.assertEqual(len(tc.read(self.directory/'coordination.json')['tasks']),1)
        finally:
            for worker in workers:
                if worker.is_alive(): worker.terminate(); worker.join(10)
            results.close(); results.join_thread()

    def test_checkpoint_preserved_and_init_idempotent(self):
        self.event('checkpoint',next_action='核验B成果',evidence=tc.reference(self.evidence))
        before=(self.directory/'coordination.json').read_bytes()
        tc.initialize(self.directory,self.display)
        self.assertEqual(before,(self.directory/'coordination.json').read_bytes())
        self.assertEqual(tc.resume(self.directory)['checkpoint']['next_action'],'核验B成果')

if __name__=='__main__': unittest.main()
