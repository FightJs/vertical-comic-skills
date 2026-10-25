"""Real gates and files, synthetic images only; no service calls or hot migration."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
from codex_reference_contract import file_session,digest,read_json,path_exists,scan_directory
from audit_cache import derived
from validation_pool import ValidationPool,session
from runtime_pipeline import POLICY
import test_audit_cache as cache_fixtures
import test_production_runtime as commit_fixtures
import test_first_batch_production as review_fixtures

class ValidationPoolTests(unittest.TestCase):
    def test_reuses_actual_context_only_after_rehashing_new_transaction(self):
        f=cache_fixtures.AuditCacheTests();f.setUp();self.addCleanup(f.doCleanups)
        from continuity_context import load_context
        pool=ValidationPool()
        with session(pool):
            with file_session():first=load_context(f.packet,f.root)
            with file_session() as memo:second=load_context(f.packet,f.root)
        self.assertEqual(first,second);self.assertEqual(first[1],[])
        self.assertGreater(pool.statistics['hits'],0);self.assertGreater(memo['hash_reads'],0)

    def test_content_change_invalidates_across_operations(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'input';path.write_text('old')
            pool=ValidationPool();calls=[]
            def check():calls.append(1);return digest(path)
            with session(pool):
                with file_session():first=derived('approval_proof','test',check)
                path.write_text('new')
                with file_session():second=derived('approval_proof','test',check)
            self.assertNotEqual(first,second);self.assertEqual(len(calls),2)
            self.assertGreater(pool.statistics['invalidations'],0)

    def test_missing_file_and_empty_directory_are_cache_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pool=ValidationPool()
            def check():return [path_exists(root/'missing'),[str(p) for p in scan_directory(root,suffixes=('.json',))]]
            with session(pool):
                with file_session():self.assertEqual(derived('approval_proof','negative',check),[False,[]])
                (root/'missing').write_text('now exists');(root/'new.json').write_text('{}')
                with file_session():value=derived('approval_proof','negative',check)
            self.assertTrue(value[0]);self.assertEqual(len(value[1]),1)

    def test_scope_and_inline_proof_mutation_do_not_reuse_authority(self):
        f=cache_fixtures.AuditCacheTests();f.setUp();self.addCleanup(f.doCleanups)
        from staged_workflow import approval_errors
        proof=copy.deepcopy(f.source['shot_approval']);pool=ValidationPool()
        with session(pool):
            with file_session():self.assertEqual(approval_errors(proof,f.root,proof['artifacts'],'BENCH','E000',phase='shot_design'),[])
            proof['status']='REVOKED'
            with file_session():self.assertTrue(approval_errors(proof,f.root,proof['artifacts'],'BENCH','E000',phase='shot_design'))

    def test_pool_is_bounded_and_full_state_verdicts_are_not_shared(self):
        pool=ValidationPool(2)
        with session(pool):
            for i in range(4):
                with file_session():derived('approval_proof',i,lambda:i)
            with file_session():derived('preparation_report','not-shareable',lambda:True)
        self.assertEqual(len(pool.entries),2)

    def test_many_panel_subset_queries_do_not_evict_common_proof(self):
        pool=ValidationPool(2);calls=[]
        def common():calls.append(1);return True
        with session(pool):
            with file_session():derived('approval_proof','common',common)
            for i in range(8):
                with file_session():derived('approval_coverage',i,lambda:True)
            with file_session():self.assertTrue(derived('approval_proof','common',common))
        self.assertEqual(len(calls),1);self.assertLessEqual(len(pool.entries),2)

    def test_reviewed_image_reuse_rechecks_actual_qa_and_image_bytes(self):
        import staged_workflow
        f=commit_fixtures.RuntimeTests();f.setUp();self.addCleanup(f.doCleanups)
        pool=ValidationPool();actual=staged_workflow._qa_errors
        with patch.object(staged_workflow,'_qa_errors',wraps=actual) as check,session(pool):
            with file_session():self.assertEqual(staged_workflow.qa_errors(f.root,f.r),[])
            with file_session():self.assertEqual(staged_workflow.qa_errors(f.root,f.r),[])
            self.assertEqual(check.call_count,1)
            image=f.root/f.r['output']['path'];image.write_bytes(image.read_bytes()+b'changed')
            with self.assertRaises(ValueError):
                with file_session():staged_workflow.qa_errors(f.root,f.r)

    def test_pooled_operation_never_publishes_a_result_after_input_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'input';path.write_text('original');pool=ValidationPool()
            with session(pool):
                with self.assertRaisesRegex(ValueError,'CHECK_SNAPSHOT_CHANGED'):
                    with file_session():
                        derived('approval_proof','immutable-fact',lambda:digest(path))
                        path.write_text('changed')
                        derived('approval_proof','immutable-fact',lambda:digest(path))

    def test_reused_fact_keeps_nested_dependencies_for_optimistic_commit(self):
        from codex_reference_contract import verify_read_snapshot
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'input';path.write_text('original');pool=ValidationPool()
            with session(pool):
                with file_session():derived('approval_proof','nested',lambda:digest(path))
                with file_session() as snapshot:
                    derived('approval_coverage','outer',lambda:derived('approval_proof','nested',lambda:digest(path)))
            path.write_text('changed')
            with self.assertRaisesRegex(ValueError,'CHECK_SNAPSHOT_CHANGED'):verify_read_snapshot(snapshot)

class OptimisticCommitTests(unittest.TestCase):
    def fixture(self):
        f=commit_fixtures.RuntimeTests();f.setUp();self.addCleanup(f.doCleanups)
        f.r['status']='GENERATED';f.state['runtime_pipeline_policy']=POLICY
        path=f.root/'00_输入审计/生产流程.json';path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(f.state))
        update={'panel_id':'P001','attempt_id':f.r['attempt_id'],'round_id':1,'status':'VISUAL_PASS'}
        return f,path,update

    def test_actual_image_validation_runs_outside_write_lock(self):
        f,path,update=self.fixture()
        import staged_workflow,runtime_pipeline
        from production_runtime import commit_updates
        real_lock=runtime_pipeline.state_write_lock;real_qa=staged_workflow.qa_errors;held=[]
        @contextmanager
        def lock(*args,**kwargs):
            with real_lock(*args,**kwargs):
                held.append(True)
                try:yield
                finally:held.pop()
        def validate(*args,**kwargs):self.assertFalse(held);return real_qa(*args,**kwargs)
        with patch.object(runtime_pipeline,'state_write_lock',lock),patch.object(staged_workflow,'qa_errors',validate):
            result=commit_updates(path,digest(path),[update])
        self.assertEqual(read_json(path)['panels'][0]['status'],'VISUAL_PASS')
        self.assertIn('lock_wait',result['pipeline_timing'])

    def test_state_change_after_preflight_is_not_overwritten(self):
        f,path,update=self.fixture()
        import runtime_pipeline
        from production_runtime import commit_updates
        original=runtime_pipeline.state_write_lock
        @contextmanager
        def conflict(*args,**kwargs):
            value=read_json(path);value['peer_note']='keep me';path.write_text(json.dumps(value))
            with original(*args,**kwargs):yield
        with patch.object(runtime_pipeline,'state_write_lock',conflict):
            with self.assertRaisesRegex(ValueError,'CHANGED'):commit_updates(path,digest(path),[update])
        self.assertEqual(read_json(path)['peer_note'],'keep me')
        self.assertEqual(read_json(path)['panels'][0]['status'],'GENERATED')

    def test_actual_dependency_changed_before_lock_rejects_commit(self):
        f,path,update=self.fixture()
        import runtime_pipeline
        from production_runtime import commit_updates
        original=runtime_pipeline.state_write_lock;qa=f.root/f.r['qa_report']['path']
        @contextmanager
        def conflict(*args,**kwargs):
            qa.write_text(qa.read_text()+' ')
            with original(*args,**kwargs):yield
        before=path.read_bytes()
        with patch.object(runtime_pipeline,'state_write_lock',conflict):
            with self.assertRaisesRegex(ValueError,'CHANGED'):commit_updates(path,digest(path),[update])
        self.assertEqual(path.read_bytes(),before)

class ReviewPipelineTests(unittest.TestCase):
    def fixture(self):
        f=review_fixtures.FirstBatchTests();self.addCleanup(f.doCleanups)
        h,state,row,item,decision=f.fixture();state['runtime_pipeline_policy']=POLICY
        path=h.root/'00_输入审计/生产流程.json';path.write_text(json.dumps(state))
        request={'panel_id':row['panel_id'],'attempt_id':row['attempt_id'],'base_qa':row['qa_report'],
                 'reviewer':'SYNTHETIC','reason':'actual same-image QA correction','verdict':'FAIL',
                 'observations':{'dimension_review':{'action_interaction':{'evidence':'SYNTHETIC clearer observed hand detail'}}}}
        return h,path,row,request

    def test_revision_keeps_original_bytes_updates_decision_and_adoption(self):
        from review_pipeline import save
        h,path,row,request=self.fixture();original=copy.deepcopy(row);old_bytes=(h.root/row['qa_report']['path']).read_bytes()
        result=save(path,digest(path),request);updated=read_json(path)['panels'][0]
        self.assertEqual(result['status'],'QA_AND_DECISION_SAVED')
        self.assertEqual((h.root/original['qa_report']['path']).read_bytes(),old_bytes)
        self.assertNotEqual(updated['qa_report'],original['qa_report'])
        self.assertEqual(updated['qa_revisions'][0]['qa_report'],original['qa_report'])
        self.assertEqual(updated['output'],original['output']);self.assertEqual(updated['round_id'],1)
        self.assertEqual(updated['adoption']['decision'],updated['production_decisions'][row['attempt_id']])
        from production_decisions import selected
        self.assertEqual(selected(h.root,updated)[0]['attempt_id'],row['attempt_id'])

    def test_invalid_field_and_invalid_observed_time_reject_before_state_write(self):
        from review_pipeline import save
        h,path,row,request=self.fixture();before=path.read_bytes()
        request['observations']={'dimension_review':{'action_interaction':{'expected':{}}}}
        with self.assertRaisesRegex(ValueError,'bound field'):save(path,digest(path),request)
        self.assertEqual(path.read_bytes(),before)
        request['observations']={};request['observed_review_seconds']=-1
        with self.assertRaisesRegex(ValueError,'observed_review_seconds'):save(path,digest(path),request)
        self.assertEqual(path.read_bytes(),before)

    def test_stale_qa_and_unknown_attempt_cannot_be_relabelled(self):
        from review_pipeline import save
        h,path,row,request=self.fixture();request['base_qa']={'path':'wrong','sha256':'0'*64}
        with self.assertRaisesRegex(ValueError,'REVISION_CHANGED'):save(path,digest(path),request)
        state=read_json(path);state['panels'][0]['status']='RESULT_UNKNOWN';path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError,'ATTEMPT_CHANGED'):save(path,digest(path),request)

    def test_new_observation_requires_updated_issue_disposition(self):
        from review_pipeline import save
        h,path,row,request=self.fixture();before=path.read_bytes()
        request['observations']={'dimension_review':{'identity':{'status':'FAIL','evidence':'SYNTHETIC new identity issue'}}}
        with self.assertRaisesRegex(ValueError,'QA_DECISION|QA_FIELD'):save(path,digest(path),request)
        self.assertEqual(path.read_bytes(),before)

    def test_first_save_uses_the_exact_prepared_template_without_fake_approval(self):
        from review_pipeline import save
        h,path,row,request=self.fixture();state=read_json(path);target=state['panels'][0]
        template=target.pop('qa_report');target['status']='GENERATED'
        target.pop('adoption');target.pop('production_decisions');path.write_text(json.dumps(state))
        request.update(base_qa=None,qa_template=template)
        result=save(path,digest(path),request);updated=read_json(path)['panels'][0]
        self.assertEqual(updated['status'],'VISUAL_FAIL')
        self.assertEqual(updated['qa_revisions'][0]['qa_report'],None)
        self.assertNotIn('adoption',updated);self.assertEqual(result['user_approval'],'NOT_GRANTED')

    def test_peer_write_during_review_is_kept(self):
        import review_pipeline
        h,path,row,request=self.fixture();original=review_pipeline.state_write_lock
        @contextmanager
        def conflict(*a,**k):
            state=read_json(path);state['peer_note']='preserve';path.write_text(json.dumps(state))
            with original(*a,**k):yield
        with patch.object(review_pipeline,'state_write_lock',conflict):
            with self.assertRaisesRegex(ValueError,'CHANGED'):review_pipeline.save(path,digest(path),request)
        updated=read_json(path)
        self.assertEqual(updated['peer_note'],'preserve');self.assertEqual(updated['panels'][0]['qa_report'],row['qa_report'])

class OptimisticReserveTests(unittest.TestCase):
    def setUp(self):
        from dispatch_fixture import DispatchFixture
        self.f=DispatchFixture();self.addCleanup(self.f.close)
        state=read_json(self.f.state_path);state['runtime_pipeline_policy']=POLICY
        self.f.state_path.write_text(json.dumps(state))

    def test_actual_preflight_and_packet_stage_are_outside_locks(self):
        import episode_dispatch_queue as queue
        held=[];actual=queue._timed_locks;prepare=queue._prepare;commit=queue._commit
        @contextmanager
        def locks(*a,**k):
            with actual(*a,**k):
                held.append(True)
                try:yield
                finally:held.pop()
        def preflight(*a,**k):self.assertFalse(held);return prepare(*a,**k)
        def stage(*a,**k):self.assertFalse(held);self.assertTrue(k['_stage_only']);return commit(*a,**k)
        with patch.object(queue,'_timed_locks',locks),patch.object(queue,'_prepare',preflight),patch.object(queue,'_commit',stage):
            result=queue.reserve_ready(self.f.state_path,digest(self.f.state_path),digest(self.f.control_path),1)
        self.assertEqual(result['status'],'RESERVED');self.assertEqual(len(read_json(self.f.state_path)['dispatch_ledger']),1)

    def test_pause_after_packet_stage_does_not_reserve(self):
        import episode_dispatch_queue as queue
        actual=queue._commit;before=self.f.state_path.read_bytes()
        def pause(*a,**k):
            result=actual(*a,**k);control=read_json(self.f.control_path);control['paused']=True
            self.f.control_path.write_text(json.dumps(control));return result
        with patch.object(queue,'_commit',pause):
            with self.assertRaisesRegex(ValueError,'CHANGED'):
                queue.reserve_ready(self.f.state_path,digest(self.f.state_path),digest(self.f.control_path),1)
        self.assertEqual(self.f.state_path.read_bytes(),before)

class WorkflowSessionTests(unittest.TestCase):
    def test_jsonl_input_and_output_use_utf8_with_a_legacy_codepage(self):
        import os,subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'00_输入审计/state.json';path.parent.mkdir();path.write_text('{}',encoding='utf8')
            request={'request_id':'SYNTHETIC_中文','state':str(path),'action':'unsupported'}
            data=(json.dumps(request,ensure_ascii=False)+'\n')*2
            child_env={**os.environ,'PYTHONIOENCODING':'cp1252'}
            p=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve().parents[1]/'scripts/workflow_session.py'),'--serve'],
                input=data.encode('utf8'),capture_output=True,env=child_env,timeout=20)
            self.assertEqual(p.returncode,0,p.stderr.decode('utf8'))
            rows=[json.loads(line) for line in p.stdout.decode('utf8').splitlines()]
            self.assertEqual(len(rows),2)
            self.assertTrue(all(r['request_id']==request['request_id'] and r['result']['status']=='HOLD' for r in rows))

    def test_real_compile_reuses_facts_but_final_gate_has_no_shared_pool(self):
        import test_direct_handoff as fixtures
        from workflow_session import WorkflowSession
        f=fixtures.DirectHandoffTests();f.setUp();self.addCleanup(f.doCleanups)
        worker=WorkflowSession();path=f.template/'00_输入审计/生产流程.json'
        request={'action':'compile','state':str(path),'input_audit':True,'record_timing':False}
        first=worker.execute(request);second=worker.execute(request)
        self.assertEqual(first['jobs'],second['jobs']);self.assertGreater(worker.pool.statistics['hits'],0)
        hits=worker.pool.statistics['hits']
        result=worker.execute({'action':'final-check','state':str(path),'record_timing':False})
        self.assertEqual(worker.pool.statistics['hits'],hits)
        self.assertNotEqual(result.get('status'),'PASS')  # Unproduced fixture cannot be delivered.

    def test_pilot_does_not_claim_real_repair_from_first_round_evidence(self):
        from workflow_session import pilot
        f=review_fixtures.FirstBatchTests();self.addCleanup(f.doCleanups)
        h,state,row,item,decision=f.fixture()
        result=pilot(state,h.root,{'panels':[row['panel_id']],'repair_panel':row['panel_id']})
        self.assertEqual(result['status'],'PILOT_INCOMPLETE')
        self.assertIn('REAL_REPAIR_NOT_OBSERVED',';'.join(result['errors']))

class AuditBudgetTests(unittest.TestCase):
    def test_task_remaining_budget_caps_child_timeout(self):
        import audit_process,io,subprocess,time
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);started=time.monotonic()
            with patch('runtime_clock.require_running',return_value={'state':'RUNNING','remaining_seconds':.1}):
                with self.assertRaises(subprocess.TimeoutExpired) as caught:
                    audit_process.run([sys.executable,'-u','-c',"import time;print('saved',flush=True);time.sleep(20)"],
                        cwd=root,timeout=20,stdout_path=root/'out',stderr_path=root/'err',progress_stream=io.StringIO())
            self.assertLess(time.monotonic()-started,3)
            self.assertEqual(caught.exception.timeout,.1)
            self.assertEqual((root/'out').read_text(),'saved\n')

    def test_uncertain_clock_stops_before_launch_not_reset(self):
        import audit_process
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('runtime_clock.require_running',side_effect=ValueError('CLOCK_TIME_UNCERTAIN')),patch.object(audit_process.subprocess,'Popen') as spawn:
                with self.assertRaisesRegex(ValueError,'CLOCK_TIME_UNCERTAIN'):
                    audit_process.run(['unused'],cwd=root,timeout=1200,stdout_path=root/'out',stderr_path=root/'err')
                spawn.assert_not_called()

    def test_long_lived_operation_polls_original_budget_during_validation(self):
        from runtime_pipeline import budget,_BUDGET
        with patch('runtime_clock.require_running',side_effect=[{'state':'RUNNING'},ValueError('CLOCK_LIMIT_REACHED')]):
            with budget('synthetic'):
                _BUDGET.get()['next_check']=0
                with self.assertRaisesRegex(ValueError,'CLOCK_LIMIT_REACHED'):
                    derived('approval_proof','budget',lambda:True)

if __name__=='__main__':unittest.main()
