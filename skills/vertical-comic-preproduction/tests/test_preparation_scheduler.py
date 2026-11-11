import hashlib
import json
import multiprocessing
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
try:
    import preparation_scheduler as ps
except ImportError:
    ps = None


def ref(path):
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def append_race(root, ready, release, results, key):
    journal=ps.Journal(root);ready.set();release.wait(15)
    try:
        journal.append({'event_id':key,'action':'test'},0);results.put('appended')
    except ValueError as exc:results.put('stale' if 'STALE' in str(exc) else str(exc))


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
    def journal(self):
        self.assertIsNotNone(ps, 'preparation scheduler implementation missing')
        j = ps.Journal(self.root); j.initialize(['book', 'E001']); return j
    def test_response_lost_replay_is_idempotent_and_conflicts_are_rejected(self):
        j = self.journal(); event = {'event_id': 'one', 'action': 'test', 'value': 3}
        first = j.append(event, 0)
        self.assertEqual(j.append(event, 0), first)
        with self.assertRaisesRegex(ValueError, 'CONFLICT'): j.append({**event, 'value': 4}, 1)
        with self.assertRaisesRegex(ValueError, 'STALE'): j.append({**event, 'event_id': 'two'}, 0)
    def test_only_torn_tail_can_be_recovered_not_complete_corruption(self):
        j = self.journal(); j.append({'event_id':'one', 'action':'test'}, 0)
        with j.path.open('ab') as f: f.write(b'{"seq":2')
        self.assertEqual(ps.Journal(self.root).read()['revision'], 1)
        j.append({'event_id':'two', 'action':'test'}, 1)
        lines = j.path.read_bytes().splitlines(keepends=True)
        lines[0] = lines[0].replace(b'"test"', b'"evil"')
        j.path.write_bytes(b''.join(lines))
        with self.assertRaisesRegex(ValueError, 'CORRUPT'): ps.Journal(self.root).read()
    def test_competing_processes_cannot_append_the_same_revision(self):
        journal=self.journal();ctx=multiprocessing.get_context('spawn');release=ctx.Event();results=ctx.Queue()
        signals=[ctx.Event(),ctx.Event()]
        workers=[ctx.Process(target=append_race,args=(str(self.root),signals[i],release,results,str(i))) for i in range(2)]
        try:
            for worker in workers:worker.start()
            for signal in signals:self.assertTrue(signal.wait(15))
            release.set();self.assertEqual(sorted(results.get(timeout=15) for _ in workers),['appended','stale'])
            for worker in workers:worker.join(15);self.assertEqual(worker.exitcode,0)
            self.assertEqual(journal.read()['revision'],1)
        finally:
            for worker in workers:
                if worker.is_alive():worker.terminate();worker.join()
    def test_snapshot_is_disposable_and_warm_reads_never_rewrite(self):
        j = self.journal(); j.append({'event_id':'one','action':'test'}, 0)
        j.snapshot_path.write_text('broken')
        self.assertEqual(ps.Journal(self.root).read()['revision'], 1)
        before = {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        for _ in range(5): j.read()
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()})


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ps, 'preparation scheduler implementation missing')
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.now = 100.; self.live = True
        self.input = self.root/'input.txt'; self.input.write_text('source')
        self.s = ps.Scheduler(self.root, clock=lambda:self.now, liveness=lambda i:self.live,
                              identity={'pid':99999,'birth':'test'})
        self.epoch = self.s.start_owner(['book', 'E001'])
    def task(self, key, **extra):
        return {'task_id':key,'kind':'shot_fragment','scope':['book','E001',key],
                'input_refs':[ref(self.input)], 'input_digest':ref(self.input)['sha256'], **extra}
    def save(self, key):
        out=self.root/(key+'.txt');out.write_text(key)
        return self.s.record_result(key,[ref(out)])
    def receipt(self, key):
        t=self.s.status()['tasks'][key];path=self.root/(key+'.receipt.json')
        path.write_text(json.dumps({'policy':'preparation_business_receipt_v1','status':'COMMITTED',
            'task_id':key,'operation_id':t['operation_id'],'output_refs':t['output_refs']}))
        return ref(path)
    def complete(self, key):
        self.s.claim(key);self.save(key);self.s.commit(key,self.receipt(key))
    def test_live_owner_rejected_dead_takeover_fences_old_callback(self):
        other=ps.Scheduler(self.root,clock=lambda:self.now,liveness=lambda i:self.live,
                           identity={'pid':99998,'birth':'new'})
        with self.assertRaisesRegex(ValueError,'OWNER_ALIVE'): other.start_owner()
        self.s.register([self.task('a')]);self.s.claim('a');self.s.attach_host('a','native-1')
        self.live=False;new=other.start_owner()
        self.assertGreater(new,self.epoch)
        with self.assertRaisesRegex(ValueError,'STALE_OWNER'): self.save('a')
        self.assertEqual(other.status()['tasks']['a']['status'],'UNKNOWN')
    def test_dag_blocks_real_dependencies_but_not_comparisons_or_prior_images(self):
        self.s.register([self.task('b',dependencies=['a']),self.task('a',comparison_links=['b'],prior_image_plan=['b'])])
        self.assertEqual([t['task_id'] for t in self.s.plan({'model':2})['ready']],['a'])
        self.complete('a')
        self.assertEqual([t['task_id'] for t in self.s.plan({'model':2})['ready']],['b'])
        with self.assertRaisesRegex(ValueError,'CYCLE'):
            self.s.register([self.task('c',dependencies=['d']),self.task('d',dependencies=['c'])])
        self.assertNotIn('c',self.s.status()['tasks'])
    def test_file_changes_block_claim_and_result_hash_is_verified(self):
        self.s.register([self.task('a')]);self.input.write_text('changed')
        with self.assertRaisesRegex(ValueError,'HASH'):self.s.claim('a')
    def test_registration_and_commit_replay_do_not_create_new_work(self):
        task=self.task('a');self.s.register([task]);self.s.register([task])
        self.s.claim('a');self.save('a');r=self.receipt('a')
        first=self.s.commit('a',r);rev=self.s.status()['revision']
        self.assertEqual(self.s.commit('a',r),first)
        self.assertEqual(self.s.status()['revision'],rev)
        self.assertEqual(self.s.query_receipt(first['operation_id']),r)
        with self.assertRaises(ValueError):self.s.register([{**task,'kind':'derive'}])
    def test_saved_result_requires_receipt_and_cannot_be_reclaimed(self):
        self.s.register([self.task('a')]);self.s.claim('a');self.save('a')
        with self.assertRaisesRegex(ValueError,'NOT_READY'):self.s.claim('a')
        with self.assertRaises(ValueError):self.s.commit('a',{'stdout':'PASS'})
        r=self.receipt('a');self.s.commit('a',r)
        self.assertEqual(self.s.status()['tasks']['a']['status'],'COMMITTED')
    def test_unknown_host_is_never_resubmitted_after_elapsed_time(self):
        self.s.register([self.task('a',lane='image')]);self.s.claim('a');self.s.attach_host('a','img-1')
        ev=self.root/'host.json';ev.write_text('{"status":"UNKNOWN"}')
        self.s.reconcile({'a':{'status':'UNKNOWN','host_id':'img-1','evidence':ref(ev)}})
        self.now+=100000
        self.assertEqual(self.s.plan({'model':6,'image':20})['ready'],[])
        self.assertEqual(self.s.status()['tasks']['a']['host_id'],'img-1')
        with self.assertRaisesRegex(ValueError,'NOT_READY'):self.s.claim('a')
    def test_stale_epoch_rejected_even_with_new_instance(self):
        self.s.register([self.task('a')])
        with self.assertRaisesRegex(ValueError,'STALE_OWNER'):self.s.claim('a',epoch=self.epoch-1)
    def test_three_lanes_use_delegated_coordinator_capacity(self):
        self.s.register([self.task('m'+str(i)) for i in range(4)]+[self.task('l',lane='local'),self.task('i',lane='image')])
        plan=self.s.plan({'model':8,'coordinator':{'limits':{'compile':3,'image':5},'active':{'compile':2,'image':4}}})
        self.assertEqual(plan['lanes'],{'model':2,'local':1,'image':1})
        self.assertEqual(len(plan['ready']),4)
        self.assertEqual(self.s.plan({'model':1})['lanes']['model'],1)
    def test_model_reduction_recovers_with_real_accepted_panel_throughput(self):
        self.s.register([self.task('a'),self.task('b')])
        self.s.reconcile(health={'model_capacity':8,'pressure':True})
        self.assertEqual(self.s.plan({'model':8})['lanes']['model'],1)
        self.complete('a');self.now+=65
        self.s.reconcile(health={'model_capacity':8,'pressure':False})
        self.assertEqual(self.s.plan({'model':8})['lanes']['model'],2)
        self.now+=65;self.complete('b')
        self.s.reconcile(health={'model_capacity':8,'pressure':False})
        self.assertGreaterEqual(self.s.status()['metrics']['accepted_panels'],2)
    def test_priority_and_cross_episode_fairness(self):
        self.s.register([self.task('a'+str(i)) for i in range(4)]+[self.task('other',scope=['book','E002','1']),self.task('recover',kind='save_result')])
        ready=self.s.plan({'model':3,'coordinator':{'limits':{'compile':1,'image':1},'active':{}}})['ready']
        self.assertEqual(ready[0]['task_id'],'recover')
        self.assertIn('other',[t['task_id'] for t in ready])
    def test_claim_response_lost_replays_same_event_without_new_lease(self):
        self.s.register([self.task('a')]);first=self.s.claim('a',event_id='claim-one')
        self.now+=10;revision=self.s.status()['revision']
        self.assertEqual(self.s.claim('a',event_id='claim-one'),first)
        self.assertEqual(self.s.status()['revision'],revision)
        with self.assertRaisesRegex(ValueError,'CONFLICT'):
            self.s.record_result('a',[ref(self.input)],event_id='claim-one')
    def test_same_pid_different_scheduler_is_not_same_owner(self):
        other=ps.Scheduler(self.root,identity={'pid':99999,'birth':'test'},liveness=lambda i:True)
        with self.assertRaisesRegex(ValueError,'OWNER_ALIVE'):other.start_owner()
    def test_commit_cannot_bind_wrong_task_operation_or_outputs(self):
        self.s.register([self.task('a')]);self.s.claim('a');self.save('a')
        receipt=self.receipt('a');path=Path(receipt['path']);body=json.loads(path.read_text())
        body['operation_id']='other';path.write_text(json.dumps(body))
        with self.assertRaisesRegex(ValueError,'MISMATCH'):self.s.commit('a',ref(path))
    def test_non_panel_model_work_does_not_inflate_accepted_panels(self):
        self.s.register([self.task('asset',kind='asset_definition')]);self.complete('asset')
        self.assertEqual(self.s.status()['metrics']['accepted_panels'],0)
    def test_fairness_survives_repeated_single_slot_plans(self):
        self.s.register([self.task('a'+str(i)) for i in range(4)]+[self.task('z',scope=['book','E002','1'])])
        self.complete('a0')
        self.assertEqual(self.s.plan({'model':1})['ready'][0]['task_id'],'z')
    def test_blocked_work_needs_explicit_evidence_to_recover(self):
        self.s.register([self.task('a')]);evidence=self.root/'blocked.json';evidence.write_text('{}')
        self.s.reconcile({'a':{'status':'BLOCKED','evidence':ref(evidence),'wait_reason':'missing approved asset'}})
        self.assertEqual(self.s.plan({'model':6})['ready'],[])
        with self.assertRaisesRegex(ValueError,'NOT_READY'):self.s.claim('a')
    def test_warm_metrics_are_read_only_and_journal_cache_is_reused(self):
        self.s.register([self.task(str(i)) for i in range(165)])
        before=self.s.status()['metrics']['journal_io']['disk_reads']
        for _ in range(20):self.s.status();self.s.plan({'model':6})
        self.assertEqual(self.s.status()['metrics']['journal_io']['disk_reads'],before)
    def test_result_replay_rechecks_saved_bytes(self):
        self.s.register([self.task('a')]);self.s.claim('a');out=self.root/'out.txt';out.write_text('first')
        output=ref(out);self.s.record_result('a',[output],event_id='saved')
        out.write_text('changed')
        with self.assertRaisesRegex(ValueError,'HASH'):self.s.record_result('a',[output],event_id='saved')
    def test_external_receipt_query_must_still_bind_task_and_operation(self):
        self.s.register([self.task('a')]);self.s.claim('a');self.save('a')
        receipt=self.receipt('a');path=Path(receipt['path']);body=json.loads(path.read_text());body['task_id']='wrong'
        path.write_text(json.dumps(body));receipt=ref(path)
        self.s.receipt_query=lambda operation_id:receipt
        with self.assertRaisesRegex(ValueError,'MISMATCH'):self.s.commit('a',receipt)
    def test_ready_dependencies_update_after_reopening_journal(self):
        self.s.register([self.task('a'),self.task('b',dependencies=['a'])]);self.complete('a')
        reopened=ps.Scheduler(self.root)
        self.assertEqual(reopened.status()['tasks']['b']['status'],'READY')
        self.assertEqual(reopened.query_receipt(self.s.status()['tasks']['a']['operation_id']),self.receipt('a'))
    def test_transient_zero_model_capacity_can_recover(self):
        self.s.register([self.task('a')]);self.s.reconcile(health={'model_capacity':0,'pressure':True})
        self.assertEqual(self.s.plan({'model':0})['ready'],[])
        self.now+=65;self.s.reconcile(health={'model_capacity':6,'pressure':False})
        self.assertEqual(len(self.s.plan({'model':6})['ready']),1)
    def test_recovery_priority_precedes_fairness_debt(self):
        self.s.register([self.task('a')]);self.complete('a')
        self.s.register([self.task('recover',kind='save_result'),self.task('other',scope=['book','E002','1'])])
        capacities={'model':1,'coordinator':{'limits':{'compile':1},'active':{}}}
        self.assertEqual(self.s.plan(capacities)['ready'][0]['task_id'],'recover')
    def test_dispatch_gap_starts_when_true_dependency_is_committed(self):
        self.s.register([self.task('a'),self.task('b',dependencies=['a'])])
        self.now+=10;self.complete('a');self.now+=3;self.s.claim('b')
        self.assertEqual(self.s.status()['tasks']['b']['timestamps']['ready'],110)
        gaps=self.s.status()['metrics']['dispatch_gaps']
        self.assertEqual(next(g['seconds'] for g in gaps if g['task_id']=='b'),3)
    def test_stop_new_work_does_not_discard_returned_images(self):
        self.s.register([self.task('a',lane='image')]);self.s.claim('a');self.s.attach_host('a','native-image')
        evidence=self.root/'stop.json';evidence.write_text('{}')
        self.s.reconcile({'a':{'status':'STOPPED','host_id':'native-image','evidence':ref(evidence)}})
        self.save('a')
        self.assertEqual(self.s.status()['tasks']['a']['status'],'RESULT_SAVED')
    def test_longer_real_critical_path_unlocks_before_short_path(self):
        self.s.register([self.task('aa'),self.task('bb',dependencies=['aa']),self.task('zz'),
            self.task('yy',dependencies=['zz']),self.task('xx',dependencies=['yy'])])
        self.assertEqual(self.s.plan({'model':1})['ready'][0]['task_id'],'zz')
    def test_resolved_predispatch_block_can_be_made_ready_with_evidence(self):
        self.s.register([self.task('a')]);evidence=self.root/'resolved.json';evidence.write_text('{}')
        self.s.reconcile({'a':{'status':'BLOCKED','evidence':ref(evidence)}})
        self.s.reconcile({'a':{'status':'READY','evidence':ref(evidence)}})
        self.assertEqual(self.s.plan({'model':1})['ready'][0]['task_id'],'a')
    def test_unknown_cannot_be_made_ready_by_status_observation(self):
        self.s.register([self.task('a')]);self.s.claim('a');self.s.attach_host('a','native')
        evidence=self.root/'unknown.json';evidence.write_text('{}')
        self.s.reconcile({'a':{'status':'UNKNOWN','evidence':ref(evidence)}})
        with self.assertRaises(ValueError):self.s.reconcile({'a':{'status':'READY','evidence':ref(evidence)}})
    def test_stopped_or_blocked_submitted_host_keeps_native_occupancy(self):
        self.s.register([self.task('a'),self.task('b')]);self.s.claim('a');self.s.attach_host('a','native')
        evidence=self.root/'unknown.json';evidence.write_text('{}')
        self.s.reconcile({'a':{'status':'UNKNOWN','evidence':ref(evidence)}})
        for status in ['STOPPED','BLOCKED','SUPERSEDED']:
            self.s.reconcile({'a':{'status':status,'evidence':ref(evidence)}})
            self.assertEqual(self.s.plan({'model':1})['ready'],[])
            self.assertTrue(self.s.status()['tasks']['a']['native_inflight'])
    def test_failed_external_receipt_never_commits_saved_task(self):
        self.s.register([self.task('a')]);self.s.claim('a');self.save('a')
        receipt=self.receipt('a');path=Path(receipt['path']);body=json.loads(path.read_text())
        body.update(status='FAILED',output_refs=[]);path.write_text(json.dumps(body));receipt=ref(path)
        self.s.receipt_query=lambda operation_id:receipt
        with self.assertRaisesRegex(ValueError,'MISMATCH'):self.s.commit('a',receipt)
        self.assertEqual(self.s.status()['tasks']['a']['status'],'RESULT_SAVED')
    def test_exact_bound_terminal_no_image_proof_can_release_native_occupancy(self):
        self.s.register([self.task('a'),self.task('b')]);task=self.s.claim('a');self.s.attach_host('a','native')
        evidence=self.root/'terminal.json';evidence.write_text(json.dumps({'policy':'preparation_host_observation_v1',
            'task_id':'a','operation_id':task['operation_id'],'host_id':'native','status':'FAILED_NO_IMAGE','confirmed_no_image':True}))
        self.s.reconcile({'a':{'status':'STOPPED','evidence':ref(evidence),'terminal':True}})
        self.assertFalse(self.s.status()['tasks']['a']['native_inflight'])
        self.assertEqual(self.s.plan({'model':1})['ready'][0]['task_id'],'b')
    def test_read_only_35_and_165_warm_status(self):
        for count in [35,165]:
            tasks=[self.task(str(i)) for i in range(count)]
            self.s.register(tasks)
            self.s.status();before=self.s.journal.path.read_bytes()
            for _ in range(5): self.s.status();self.s.plan({'model':6})
            self.assertEqual(before,self.s.journal.path.read_bytes())
            self.assertEqual(len(self.s.status()['tasks']),count)

if __name__=='__main__':unittest.main()
