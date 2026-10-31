"""Source progress isolation with real approved-context validators."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
from audit_fixtures import contexts,write
from codex_reference_contract import file_session,read_json,read_json_readonly,verify_read_snapshot
from continuity_context import load_context
from source_input_contract import read,strict_reads,POLICY
from validation_pool import ValidationPool,session

class SourceInputsTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.packet=contexts(self.root,4)[-1]
        ctx=read_json(self.root/self.packet['continuity_context']['path']);src=ctx['sources'][0]
        self.state={k:src[k] for k in ('episode_id','source_script','source_snapshot','visual_basis','shot_manifest')}
        self.state.update(book_id='BENCH',readiness_policy='panel_readiness_v1',execution_mode='episode_async_v1',
            runtime_pipeline_policy='observed_incremental_pipeline_v1',source_input_policy=POLICY,
            toolchain={'files':[{'path':'source_input_contract.py'}]},panels=[],
            gates={'visual_basis':src['visual_approval'],'shot_design':src['shot_approval']})
        self.path=self.root/'state.json';self.save()
        for key in ('visual_approval','shot_approval'):src.pop(key)
        src.update(approval_resolution='source_runtime_gates_v1',source_state_file='state.json')
        self.packet['continuity_context']=write(self.root,'runtime-context.json',ctx)
    def save(self):self.path.write_text(json.dumps(self.state),encoding='utf-8')
    def test_new_review_policies_keep_projected_progress_isolation(self):
        self.state.update(repair_window_policy='observed_repair_window_v2',review_followup_policy='observed_followup_v1')
        self.save()
        with file_session() as memo:
            value=read(self.path)
            from source_input_contract import SourceView
            self.assertIsInstance(value,SourceView)
            self.state['panels']=[{'panel_id':'P001','status':'VISUAL_PASS','review_submission':{'operation_id':'observed'}}];self.save()
        self.assertNotIn(str(self.path.resolve()),memo['files'])

    def test_real_context_survives_progress_at_transaction_boundary(self):
        with file_session() as memo:
            self.assertEqual(load_context(self.packet,self.root)[1],[])
            self.state['panels']=[{'status':'GENERATED'}];self.save()
        self.assertEqual(memo['source_progress_refreshes'],1)
        self.assertNotIn(str(self.path.resolve()),memo['files'])
    def test_prepared_proof_reuses_unchanged_source_projection(self):
        from prepared_job_store import PreparedStore,proof
        with file_session() as memo:read(self.path)
        saved=proof(memo,self.root/'unrelated-state.json')
        self.assertTrue(saved['reusable'])
        store=PreparedStore(self.root/'owner'/'state.json')
        store.verify_files(saved)
        self.state['panels']=[{'panel_id':'P001','status':'GENERATED','qa_report':'changed'}];self.save()
        store.verify_files(saved)
        self.state['gates']={};self.save()
        with self.assertRaises(ValueError):store.verify_files(saved)

    def test_input_and_authority_changes_fail_closed(self):
        for key,value in [('holds',['hold']),('gates',{}),('authority_revision',2),('approval_revocations',[]),('visual_basis',{})]:
            with self.subTest(key=key):
                original=copy.deepcopy(self.state)
                with self.assertRaisesRegex(ValueError,'CHECK_SNAPSHOT_CHANGED'):
                    with file_session():
                        read(self.path);self.state[key]=value;self.save()
                self.state=original;self.save()
    def test_pool_reuses_context_after_progress_but_revocation_rechecks(self):
        pool=ValidationPool()
        with session(pool):
            with file_session():self.assertEqual(load_context(self.packet,self.root)[1],[])
            self.state['panels']=[{'status':'GENERATED'}];self.save()
            with file_session() as memo:self.assertEqual(load_context(self.packet,self.root)[1],[])
            self.assertGreater(pool.statistics['hits'],0)
            self.state['gates']['shot_design']['status']='REVOKED';self.save()
            with file_session():self.assertTrue(load_context(self.packet,self.root)[1])
    def test_imported_panel_order_is_bound_without_progress_statuses(self):
        self.state['runtime_import']={'path':'import.json','sha256':'a'*64}
        self.state['panels']=[{'panel_id':'P001','status':'GENERATED'},{'panel_id':'P002','status':'PENDING'}];self.save()
        with file_session():
            self.assertEqual(read(self.path).panel_order,('P001','P002'))
            self.state['panels'][1]['status']='GENERATED';self.save()
        with self.assertRaisesRegex(ValueError,'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                read(self.path);self.state['panels'].reverse();self.save()

    def test_full_read_dominates_in_either_order(self):
        for first in (True,False):
            with self.assertRaisesRegex(ValueError,'CHECK_SNAPSHOT_CHANGED'):
                with file_session():
                    if first:read_json_readonly(self.path)
                    read(self.path)
                    if not first:read_json_readonly(self.path)
                    self.state['panels'].append({});self.save()
    def test_strict_and_unknown_schema_keep_full_state(self):
        with strict_reads(),file_session() as memo:read(self.path)
        self.assertIn(str(self.path.resolve()),memo['files'])
        self.state['new_unknown_field']=True;self.save()
        with file_session() as memo:read(self.path)
        self.assertIn(str(self.path.resolve()),memo['files'])
    def test_lock_verification_does_not_refresh_changed_json(self):
        with file_session() as memo:read(self.path)
        self.state['panels'].append({});self.save()
        with self.assertRaisesRegex(ValueError,'SOURCE_VIEW_VERSION_CHANGED'):
            verify_read_snapshot(memo,refresh_views=False)
        self.assertEqual(memo['source_input_reads'],1)
    def test_source_symlink_retarget_is_rejected(self):
        link=self.root/'link';link.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError,'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                read(link);other=self.root/'other';other.write_bytes(self.path.read_bytes())
                link.unlink();link.symlink_to(other)
    def test_undeclared_progress_access_is_rejected(self):
        with file_session():
            value=read(self.path)
            with self.assertRaisesRegex(ValueError,'FIELD_UNDECLARED'):value.get('panels')

    def test_progress_then_full_read_cannot_hide_formal_change(self):
        with self.assertRaisesRegex(ValueError,'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                read(self.path);self.state['holds']=['changed'];self.save();read_json(self.path)
    def test_original_qa_file_dependency_remains_strict(self):
        qa=self.root/'qa.json';qa.write_text('{}')
        with self.assertRaisesRegex(ValueError,'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                read(self.path);read_json(qa);qa.write_text('{"changed":true}')

    def test_strict_scope_promotes_existing_projection(self):
        with self.assertRaisesRegex(ValueError,'CHECK_SNAPSHOT_CHANGED'):
            with file_session() as memo:
                read(self.path)
                with strict_reads():
                    self.assertIn(str(self.path.resolve()),memo['files'])
                    self.state['panels'].append({});self.save()
