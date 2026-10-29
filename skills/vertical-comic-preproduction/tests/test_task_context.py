"""Independent remake versus relocation/resume; no real image service or approvals."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts')]
import task_context as task
from asset_tasks import audit


class TaskContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.ctx=task.fresh('SYNTHETIC',['E001'])
        self.state={'book_id':'SYNTHETIC','episode_id':'E001','task_context':self.ctx,
                    'panels':[{'panel_id':'P001','attempt_id':'a1','round_id':1,'status':'PENDING'}]}
        marker=self.root/task.ORIGIN_FILE;marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({'task_context':self.ctx,'episode_id':'E001','initial_body_calls':0,'initial_asset_calls':0}), encoding='utf-8', newline='\n')
        self.episode={'episode_id':'E001','panels':[{'panel_id':'P001','history':{
            'task_id':self.ctx['task_id'],'status':'NEVER_SUBMITTED','attempts':[]}}]}
    def errors(self):return task.history_errors(self.ctx,self.episode,self.state,self.root,lambda r:None)
    def test_other_task_missing_history_is_not_a_dependency(self):
        old=self.root/'unrelated';old.mkdir();(old/'index.json').write_text('{"status":"UNKNOWN","missing":"old-qa.json"}', encoding='utf-8', newline='\n')
        # Neither validation nor handoff history searches the neighboring old run.
        self.assertEqual(self.errors(),[])
        self.assertNotEqual(self.ctx['task_id'],task.fresh('SYNTHETIC',['E001'])['task_id'])
    def test_empty_handoff_cannot_erase_actual_unknown_or_completed_call(self):
        for status in ('IN_FLIGHT','RESULT_UNKNOWN','GENERATED','VISUAL_PASS','CALL_FAILED','CANCELLED'):
            with self.subTest(status=status):
                self.state['panels'][0]['status']=status
                self.assertTrue(self.errors())
    def test_retained_attempt_survives_new_pending_correction(self):
        row=self.state['panels'][0];row.update(attempt_id='a2',status='REPAIR_AUTHORIZED',round_id=2,
            attempt_history=[{'attempt_id':'a1','status':'VISUAL_FAIL','output':{'sha256':'actual'}}])
        self.assertTrue(self.errors())
    def test_relocation_preserves_task_and_never_reinitializes_budget(self):
        other=self.root/'moved';shutil.copytree(self.root/'00_输入审计',other/'00_输入审计')
        self.assertEqual(task.state_errors(self.state,other),[])
        changed=copy.deepcopy(self.state);changed['task_context']=task.fresh('SYNTHETIC',['E001'])
        self.assertTrue(task.state_errors(changed,other))
    def test_marker_prevents_removing_new_contract_to_claim_legacy(self):
        self.state.pop('task_context');self.assertTrue(task.state_errors(self.state,self.root))
        self.assertEqual(task.state_errors({},self.root/'legacy'),[])
    def test_runtime_gate_rejects_wrong_task_before_generation(self):
        from _historical_fixture import evaluate
        self.state['task_context']=task.fresh('SYNTHETIC',['E001'])
        self.assertEqual(evaluate(self.state,self.root)['next_action'],'TASK_SCOPE_HOLD')
    def test_foreign_history_is_rejected_unless_explicitly_selected(self):
        row=self.state['panels'][0];row.update(status='RESULT_UNKNOWN',source_task_id='OLD')
        hist=self.episode['panels'][0]['history'];hist.update(status='UNRESOLVED',attempts=[{
            'attempt_id':'a1','status':'UNKNOWN','task_id':'OLD'}])
        self.assertTrue(self.errors())
        self.ctx.update(origin='reuse_selected',request_source={'source_kind':'user_message',
            'quote':'SYNTHETIC explicit reuse P001','source_locator':'synthetic://message'},
            imports=[{'source_task_id':'OLD','episode_id':'E001','panel_ids':['P001'],
                      'evidence':[{'path':'selected.json','sha256':'synthetic'}]}])
        (self.root/task.ORIGIN_FILE).write_text(json.dumps({'task_context':self.ctx,'episode_id':'E001','initial_body_calls':0}), encoding='utf-8', newline='\n')
        self.assertEqual(self.errors(),[])
        hist['attempts'][0]['status']='FAILED';self.assertTrue(self.errors())
    def test_fresh_cannot_smuggle_reuse_and_reuse_requires_user_scope(self):
        self.ctx['imports']=[{'source_task_id':'OLD'}]
        with self.assertRaises(ValueError):task.validate(self.ctx)
        self.ctx['origin']='reuse_selected'
        with self.assertRaises(ValueError):task.validate(self.ctx)
    def test_asset_ledger_does_not_claim_body_was_submitted(self):
        (self.root/'asset-call.json').write_text('{"kind":"asset","status":"COMPLETED"}', encoding='utf-8', newline='\n')
        self.assertEqual(self.errors(),[])
    def test_dispatch_receipt_cannot_be_hidden_by_pending_state(self):
        self.state['dispatch_ledger']=[{'panel_id':'P001','attempt_id':'a1','status':'IN_FLIGHT'}]
        self.assertTrue(self.errors())


class AssetScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.need={'asset_id':'SC-NEEDED','episode_id':'E001','panel_ids':['P001','P002'],
                   'visible_occurrences':2,'source_basis':'SYNTHETIC source rows 1 and 2'}
    def row(self,**fields):return {**self.need,**fields}
    def route(self,**fields):return audit(self.root,[self.row(**fields)])['asset_tasks'][0]['resolution']
    def test_unselected_old_index_missing_file_does_not_block_batch(self):
        (self.root/'old-index.json').write_text('{"missing":"obsolete.png"}', encoding='utf-8', newline='\n')
        image=self.root/'current.bin';image.write_bytes(b'SYNTHETIC actual reference bytes')
        result=audit(self.root,[self.row(reference={'path':image.name,'sha256':hashlib.sha256(image.read_bytes()).hexdigest()})])
        self.assertEqual(result['gap_panel_ids'],[]);self.assertEqual(result['asset_tasks'][0]['resolution'],'reuse')
        self.assertEqual(result['asset_tasks'][0]['approval'],'NOT_GRANTED_BY_FILE_AUDIT')
    def test_needed_recurring_asset_routes_to_canonical_candidate(self):
        self.assertEqual(self.route(publication_required=True),'canonical_candidate')
    def test_only_required_view_is_supplemented(self):
        self.assertEqual(self.route(existing_asset_requires_extension=True,publication_required=True),'supplement_view_or_state')
        base=self.root/'base.bin';base.write_bytes(b'SYNTHETIC partial base, no target view')
        result=audit(self.root,[self.row(existing_asset_requires_extension=True,
            reference={'path':base.name,'sha256':hashlib.sha256(base.read_bytes()).hexdigest()})])
        self.assertTrue(result['asset_tasks'][0]['base_reference_verified'])
        self.assertEqual(result['asset_tasks'][0]['resolution'],'supplement_view_or_state')
        self.assertEqual(result['gap_panel_ids'],['P001','P002'])
    def test_batch_reference_does_not_force_complete_board(self):
        self.assertEqual(self.route(),'temporary_reference')
    def test_actual_one_off_can_be_inline(self):
        self.assertEqual(self.route(visible_occurrences=1,panel_ids=['P001'],inline_sufficient=True),'inline_one_off')
        self.assertEqual(self.route(inline_sufficient=True),'temporary_reference')
        self.assertEqual(self.route(visible_occurrences=1,panel_ids=['P001'],inline_sufficient=True,publication_required=True),'canonical_candidate')
        with self.assertRaises(ValueError):self.route(visible_occurrences=1,inline_sufficient=True)
    def test_missing_needed_reference_blocks_only_its_panels(self):
        result=audit(self.root,[self.row(reference={'path':'missing.png','sha256':'not-present'},publication_required=True)])
        self.assertEqual(result['gap_panel_ids'],['P001','P002'])
        self.assertEqual(result['asset_tasks'][0]['resolution'],'canonical_candidate')
    def test_historical_absolute_path_not_treated_as_live_input(self):
        with self.assertRaises(ValueError):audit(self.root,[self.row(reference={'path':str(self.root/'old.png'),'sha256':'x'})])


if __name__=='__main__':unittest.main()
