"""Real compiler and approval gates, synthetic artifacts and no image calls."""
import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import test_direct_handoff as fixture
from test_execution_lifecycle import write
from codex_reference_contract import read_json,checked_file,digest
import context_rebind as rebind

class ContextRebindTests(unittest.TestCase):
    def setUp(self):
        f=fixture.DirectHandoffTests();f.FINAL_SEMANTICS=True;f.setUp();self.addCleanup(f.doCleanups)
        self.root=f.template;self.state=f.state
        self.state.update(source_input_policy='formal_source_inputs_v1',runtime_pipeline_policy='observed_incremental_pipeline_v1')
        self.path=self.root/'00_输入审计/生产流程.json'
        self.row=self.state['panels'][1];self.old=copy.deepcopy(self.row['package_manifest'])
        packet=read_json(checked_file(self.root,self.old));context=read_json(checked_file(self.root,packet['continuity_context']))
        packet['continuity_context']=write(self.root,'candidate-context.json',context)
        ref=write(self.root,'candidate-packet.json',packet)
        self.replacements=[{'panel_id':'P002','package_manifest':ref}];self.save()
    def save(self):write(self.root,'00_输入审计/生产流程.json',self.state)
    def test_plan_readonly_apply_idempotent_preserves_originals(self):
        before={p:digest(p) for p in self.root.rglob('*') if p.is_file()}
        result=rebind.plan(self.path,self.replacements)
        self.assertEqual(result['status'],'EQUIVALENT_READY',result)
        self.assertEqual(before,{p:digest(p) for p in self.root.rglob('*') if p.is_file()})
        applied=rebind.apply(self.path,result['plan']);self.assertEqual(applied['status'],'APPLIED')
        state=read_json(self.path)
        for key,value in self.state.items():
            if key!='panels':self.assertEqual(state[key],value)
        self.assertEqual(state['panels'][0],self.state['panels'][0])
        self.assertEqual(checked_file(self.root,self.old).is_file(),True)
        self.assertEqual(rebind.apply(self.path,result['plan'])['status'],'APPLIED')
        self.assertEqual(len(read_json(self.path)['context_rebind_history']),1)
    def test_reject_history_reserved_or_unknown_result(self):
        for change in ({'status':'IN_FLIGHT'},{'status':'GENERATED'},{'ready_at':'observed'},{'attempt_history':[{}]}):
            original=copy.deepcopy(self.row);self.row.update(change);self.save()
            self.assertEqual(rebind.plan(self.path,self.replacements)['status'],'REVIEW_REQUIRED')
            self.row.clear();self.row.update(original)
    def test_prompt_change_and_missing_approval_rejected(self):
        self.state['gates']['shot_design']=None;self.save()
        self.assertEqual(rebind.plan(self.path,self.replacements)['status'],'REVIEW_REQUIRED')
    def test_plan_does_not_allow_state_changes_or_tampering(self):
        result=rebind.plan(self.path,self.replacements);self.assertEqual(result['status'],'EQUIVALENT_READY',result)
        self.state['holds']=['user hold'];self.save()
        with self.assertRaises(ValueError):rebind.apply(self.path,result['plan'])
        self.assertNotIn('context_rebind_history',read_json(self.path))
    def test_lock_race_never_overwrites_own_state(self):
        from contextlib import contextmanager
        result=rebind.plan(self.path,self.replacements);self.assertEqual(result['status'],'EQUIVALENT_READY',result)
        real=rebind.state_write_lock
        @contextmanager
        def race(path):
            self.state['holds']=['concurrent change'];self.save()
            with real(path):yield
        with patch.object(rebind,'state_write_lock',race),self.assertRaises(ValueError):rebind.apply(self.path,result['plan'])
        self.assertEqual(read_json(self.path)['holds'],['concurrent change'])
    def test_changed_context_design_rejected(self):
        packet=read_json(checked_file(self.root,self.replacements[0]['package_manifest']))
        context=read_json(checked_file(self.root,packet['continuity_context']))
        shots=read_json(checked_file(self.root,context['sources'][0]['shot_manifest']))
        shots['panels'][0]['locked_script']='changed creative input'
        context['sources'][0]['shot_manifest']=write(self.root,'changed-source-shots.json',shots)
        packet['continuity_context']=write(self.root,'changed-context.json',context)
        ref=write(self.root,'changed-context-packet.json',packet)
        result=rebind.plan(self.path,[{'panel_id':'P002','package_manifest':ref}])
        self.assertEqual(result['status'],'REVIEW_REQUIRED');self.assertIn('CONTEXT_NOT_EQUIVALENT',result['reason'])
    def test_changed_prompt_rejected_before_commit(self):
        packet=read_json(checked_file(self.root,self.replacements[0]['package_manifest']))
        packet['panels'][0]['prompt']+=' changed'
        ref=write(self.root,'changed-prompt-packet.json',packet)
        result=rebind.plan(self.path,[{'panel_id':'P002','package_manifest':ref}])
        self.assertEqual(result['status'],'REVIEW_REQUIRED');self.assertIn('PACKAGE_NOT_EQUIVALENT',result['reason'])
    def test_registration_blocks_even_if_row_claims_pending(self):
        from submission_contract import identity,fingerprint
        key=fingerprint([identity(self.state),self.state['episode_id'],'panel','P002',self.row['attempt_id'],1])
        self.state['submission_registrations']={key:{'observed_tool_call':False}};self.save()
        result=rebind.plan(self.path,self.replacements)
        self.assertEqual(result['status'],'REVIEW_REQUIRED');self.assertIn('ALREADY_REGISTERED',result['reason'])
    def test_legacy_run_not_migrated(self):
        self.state.pop('source_input_policy');self.save();before=digest(self.path)
        result=rebind.plan(self.path,self.replacements)
        self.assertEqual(result['status'],'REVIEW_REQUIRED');self.assertEqual(digest(self.path),before)
    def test_unrelated_context_shot_change_keeps_equivalence(self):
        packet=read_json(checked_file(self.root,self.replacements[0]['package_manifest']))
        context=read_json(checked_file(self.root,packet['continuity_context']))
        shots=read_json(checked_file(self.root,context['sources'][0]['shot_manifest']))
        shots['panels'][-1]['planning_notes']='new irrelevant observation'
        context['sources'][0]['shot_manifest']=write(self.root,'equivalent-source-shots.json',shots)
        packet['continuity_context']=write(self.root,'equivalent-context.json',context)
        ref=write(self.root,'equivalent-packet.json',packet)
        result=rebind.plan(self.path,[{'panel_id':'P002','package_manifest':ref,'shot_subset':ref}])
        self.assertEqual(result['status'],'EQUIVALENT_READY',result)
        self.assertEqual(rebind.apply(self.path,result['plan'])['status'],'APPLIED')
