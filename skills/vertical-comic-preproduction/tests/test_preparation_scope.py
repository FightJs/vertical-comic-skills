"""Bounded equivalence never turns metadata reuse into a new observation."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import preparation_gate_policy as gate
from input_dependencies import file_hash
try:
    import preparation_scope as scope
except ImportError:
    scope=None

class ScopeProofTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def inputs(self,targets=()):
        return {gate.FIELD:gate.EXCEPTION,'input_semantics_policy':'final_input_semantics_v2','panel_id':'P001',
            'prompt':'exact prompt','transparent_background':False,'references':[], 'preparation_requirements':list(targets)}
    def snapshot(self,inputs=None,**kw):
        self.assertIsNotNone(scope,'scope implementation missing')
        return scope.snapshot(inputs or self.inputs(),self.root,consumed_facts={'camera':'side','mirror':'frosted'},**kw)
    def test_ordinary_ready_has_no_observer_or_fake_approval_and_receipt_is_replayable(self):
        value=self.snapshot();result=scope.finalize_scope({'P001':value},operation_id='a',receipt_root=self.root)
        record=result['records']['P001'];self.assertEqual(record['status'],'TECHNICALLY_READY');self.assertFalse(record['review_performed']);self.assertNotIn('reviewer',record);self.assertFalse(result['dispatch_authorized'])
        self.assertEqual(scope.finalize_scope({'P001':value},operation_id='a',receipt_root=self.root),result)
        changed=copy.deepcopy(value);changed['prompt']='different'
        with self.assertRaises(ValueError):scope.finalize_scope({'P001':changed},operation_id='a',receipt_root=self.root)
    def test_targeted_requires_actual_evidence_then_rebind_preserves_original_observer_time(self):
        value=self.snapshot(self.inputs([{'id':'contact:0','expected':{'kind':'contact'}}]));blocked=scope.finalize_scope({'P001':value})
        self.assertEqual(blocked['targeted_panel_ids'],['P001']);self.assertNotIn('P001',blocked['records'])
        result=scope.finalize_scope({'P001':value},{'P001':{'evidence':'actual hand contact check','issues':[]}},'original observer')
        review=result['records']['P001'];self.assertIn('observed_at',review)
        current=copy.deepcopy(value);current['_preparation_scope']['assembly']={'container':'new-root'}
        rebound=scope.rebind(review,value,current)
        self.assertEqual(rebound['reviewer'],'original observer');self.assertEqual(rebound['observed_at'],review['observed_at']);self.assertEqual(rebound['reused_from']['review'],review)
        self.assertEqual(gate.review_errors(rebound,current),[])
    def test_prompt_parameters_reference_order_purpose_physics_rules_targets_unknown_change_fail(self):
        original=self.snapshot()
        changes=[('prompt','new'),('transparent_background',True),('references',[{'sha256':'invented','purpose':'identity'}]),('preparation_requirements',[{'id':'new'}]),('new_unknown','fact')]
        for key,value in changes:
            current=copy.deepcopy(original);current[key]=value;self.assertFalse(scope.equivalence(original,current)['equivalent'],key)
        for key in ['camera','mirror','rule']:
            current=copy.deepcopy(original);current['_preparation_scope']['consumed_facts'][key]='changed';self.assertFalse(scope.equivalence(original,current)['equivalent'],key)
    def test_real_file_same_bytes_path_move_allowed_and_tampering_rejected(self):
        file=self.root/'a.png';file.write_bytes(b'actual reference bytes');ref={'path':'a.png','sha256':file_hash(file)}
        old=self.snapshot(file_refs=[ref]);(self.root/'b.png').write_bytes(file.read_bytes());new=self.snapshot(file_refs=[{**ref,'path':'b.png'}])
        self.assertTrue(scope.equivalence(old,new)['equivalent'])
        (self.root/'b.png').write_bytes(b'changed')
        self.assertFalse(scope.equivalence(old,new)['equivalent'])
    def test_only_unconsumed_shared_additions_allowed(self):
        old=self.snapshot(shared={'a':{'fact':1}});new=self.snapshot(shared={'a':{'fact':1},'b':{'fact':2}})
        self.assertTrue(scope.equivalence(old,new)['equivalent'])
        new['_preparation_scope']['shared']['a']['fact']=2;self.assertFalse(scope.equivalence(old,new)['equivalent'])
    def test_negative_observation_and_wrong_input_digest_cannot_be_rebound(self):
        value=self.snapshot();result=scope.finalize_scope({'P001':value},{'P001':{'key_event_readable':False}})
        self.assertEqual(result['status'],'HOLD');self.assertNotIn('P001',result['records'])
        with self.assertRaises(ValueError):scope.rebind({'input_digest':'forged'},value,value)

class TechnicalInputTests(unittest.TestCase):
    def setUp(self):
        from test_exception_preparation import Flow
        self.fixture=Flow('test_finalize_ordinary_then_compile_without_observations');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
    def test_aggregate_basis_and_registry_addition_preserves_only_exact_consumed_review(self):
        self.assertIsNotNone(scope,'scope implementation missing')
        from codex_reference_contract import read_json,checked_file,digest
        from input_semantics import actual_input
        f=self.fixture.f;s=f.state;root=f.template;shot=read_json(checked_file(root,s['shot_manifest']))['panels'][0];path=checked_file(root,s['panels'][0]['package_manifest']);packet=read_json(path)
        packet['visual_basis']=copy.deepcopy(s['visual_basis'])
        packet['shot_manifest']=copy.deepcopy(s['shot_manifest'])
        old=scope.technical_inputs(s,root,shot,packet,path.parent)
        review=scope.finalize_scope({shot['panel_id']:old})['records'][shot['panel_id']]
        basis=read_json(checked_file(root,s['visual_basis']));basis.setdefault('appearance_details',{})['UNUSED_NEW']={'detail':'unconsumed'}
        basis_path=root/'basis-additive.json';basis_path.write_text(json.dumps(basis));changed=copy.deepcopy(s);changed['visual_basis']={'path':basis_path.name,'sha256':digest(basis_path)}
        new_packet=copy.deepcopy(packet);new_packet['visual_basis']=copy.deepcopy(changed['visual_basis']);new_packet['identity_registry']['characters']['UNUSED_NEW']={'canonical_name':'unused'}
        current=scope.technical_inputs(changed,root,shot,new_packet,path.parent)
        self.assertTrue(scope.equivalence(old,current)['equivalent'],scope.equivalence(old,current))
        plain=actual_input(changed,root,shot,new_packet,path.parent)
        rebound=scope.rebind(review,old,current,target_inputs=plain)
        self.assertEqual(gate.review_errors(rebound,plain),[]);self.assertFalse(rebound['review_performed'])
        invalid=copy.deepcopy(current);invalid['_preparation_scope']['basis']['document']['unknown_field']='invented'
        self.assertFalse(scope.equivalence(old,invalid)['equivalent'])

    def test_planned_real_image_dependency_waits_without_fabricated_image(self):
        self.assertIsNotNone(scope,'scope implementation missing')
        from codex_reference_contract import read_json,checked_file,digest
        f=self.fixture.f;s=copy.deepcopy(f.state);root=f.template
        shots=read_json(checked_file(root,s['shot_manifest']));shot=shots['panels'][1]
        shot['generation_dependencies']=['P001'];shot['continuity_contract']['generation_dependency_reasons']={'P001':'carry actual prior composition'}
        shot_path=root/'planned-shots.json';shot_path.write_text(json.dumps(shots));s['shot_manifest']={'path':shot_path.name,'sha256':digest(shot_path)}
        path=checked_file(root,s['panels'][1]['package_manifest']);packet=read_json(path);panel=packet['panels'][0]
        refs=[]
        for r in panel['reference_images']:
            actual=checked_file(path.parent,r);refs.append({**r,'path':str(actual.relative_to(root.resolve()))})
        refs.append({'path':'@DEPENDENCY:P001'})
        row={'panel_id':shot['panel_id'],'reference_path_basis':'run_root','arguments':{'prompt':panel['prompt'],'transparent_background':False,'referenced_image_paths':[r['path'] for r in refs]},'reference_files':refs,'reference_bindings':[*panel['reference_bindings'],{'alias':'@PREV','purpose':'continuity'}],'output_spec':panel.get('output_spec')}
        plan={'policy':'dependency_completion_plan_v1','scope':'episode',**{k:s[k] for k in ('book_id','episode_id','visual_basis','shot_manifest')},'inputs':[row]}
        plan_path=root/'dep-plan.json';plan_path.write_text(json.dumps(plan));ref={'path':plan_path.name,'sha256':digest(plan_path)}
        value=scope.technical_inputs(s,root,shot,packet,path.parent,dependency_plan=ref)
        self.assertTrue(value['dependency_plan']);self.assertEqual(value['references'][-1],{'dependency':'P001'})
        result=scope.finalize_scope({shot['panel_id']:value});self.assertEqual(result['status'],'WAIT_DEPENDENCY');self.assertEqual(result['waiting_dependency_panel_ids'],[shot['panel_id']]);self.assertFalse(result['dispatch_authorized'])
        self.assertEqual(value['_preparation_scope']['dependency_plan'],ref)
        with self.assertRaises(ValueError):scope.technical_inputs(s,root,shot,packet,path.parent)

    def test_real_compiler_semantics_and_reference_bytes_are_consumed(self):
        self.assertIsNotNone(scope,'scope implementation missing')
        from codex_reference_contract import read_json,checked_file
        f=self.fixture.f;s=f.state;root=f.template;shot=read_json(checked_file(root,s['shot_manifest']))['panels'][0];path=checked_file(root,s['panels'][0]['package_manifest']);packet=read_json(path)
        value=scope.technical_inputs(s,root,shot,packet,path.parent)
        self.assertIn('_preparation_scope',value);self.assertTrue(value['_preparation_scope']['files']);self.assertFalse(scope.finalize_scope({shot['panel_id']:value})['records'][shot['panel_id']]['review_performed'])
        invalid=copy.deepcopy(packet);invalid['identity_registry']['issues']=[{'status':'UNRESOLVED'}]
        with self.assertRaises(ValueError):scope.technical_inputs(s,root,shot,invalid,path.parent)
        changed=copy.deepcopy(packet);changed['panels'][0]['prompt']='uncompiled prompt'
        with self.assertRaises(ValueError):scope.technical_inputs(s,root,shot,changed,path.parent)

if __name__=='__main__':unittest.main()
