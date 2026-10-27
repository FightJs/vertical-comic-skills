"""Synthetic gate/readiness/handoff behavior; no external image calls."""
import copy
import json
import sys
import unittest
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import preparation_gate_policy as gate
import input_semantics as sem
import preparation_review as entry
from codex_reference_contract import checked_file, read_json
import test_input_semantics as legacy

OBS = {'evidence':'SYNTHETIC characters and event readable, references usable',
       'characters_correct':True,'key_event_readable':True,'input_usable':True,'issues':[]}

class QuickObservation(unittest.TestCase):
    def inputs(self):
        return {gate.FIELD:gate.POLICY,'input_semantics_policy':sem.PREPARED_POLICY,'prompt':'SYNTHETIC'}
    def test_one_observation_and_cosmetic_warning_pass_without_nine_checks(self):
        inputs=self.inputs();obs=copy.deepcopy(OBS)
        obs['issues']=[{'code':'ACCESSORY_DETAIL','detail':'SYNTHETIC small ornament','affects_story':False}]
        review=gate.reviewed(inputs,obs,'SYNTHETIC',sem.fingerprint(inputs))
        self.assertEqual(sem.review_errors(review,inputs),[])
        self.assertNotIn('checks',review)
        self.assertEqual(len(gate.warnings({'execution_review':review})),1)
    def test_story_issue_blocks_even_with_positive_booleans(self):
        inputs=self.inputs()
        for issue in ({'code':'STORY_REVERSED','detail':'SYNTHETIC reversed event','affects_story':True},
                      {'code':'ACCESSORY_DETAIL','detail':'SYNTHETIC plot-critical ring','affects_story':True}):
            obs={**OBS,'issues':[issue]};review=gate.reviewed(inputs,obs,'SYNTHETIC',sem.fingerprint(inputs))
            self.assertTrue(sem.review_errors(review,inputs))
    def test_stale_digest_and_bad_fields_rejected(self):
        with self.assertRaises(ValueError):gate.reviewed(self.inputs(),OBS,'SYNTHETIC','stale')
        with self.assertRaises(ValueError):gate.reviewed(self.inputs(),{**OBS,'input_usable':'yes'},'SYNTHETIC',sem.fingerprint(self.inputs()))
    def test_unknown_policy_rejected_and_legacy_unchanged(self):
        with self.assertRaises(ValueError):gate.enabled({gate.FIELD:'unknown'})
        self.assertFalse(gate.enabled({}))
        inputs={'prompt':'SYNTHETIC'}
        review=sem.review_template(inputs)
        self.assertEqual(len(review['checks']),6)
        self.assertTrue(sem.review_errors(review,inputs))
    def test_policy_removal_and_unreviewed_template_cannot_pass(self):
        inputs=self.inputs();review=sem.review_template(inputs)
        self.assertTrue(sem.review_errors(review,inputs))
        review=gate.reviewed(inputs,OBS,'SYNTHETIC',sem.fingerprint(inputs));review.pop(gate.FIELD)
        self.assertTrue(sem.review_errors(review,inputs))

class RuleObservation(unittest.TestCase):
    def test_rule_explanation_and_checks_not_repeated_but_actual_constraints_required(self):
        import tempfile
        import test_rule_memory as rules
        from rule_memory import application_errors
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=rules.library(root/'rules')
            panel={'memory_tags':['person_on_bed'],'prompt':'SYNTHETIC support constraint'}
            app=rules.applied(source,'generation',panel,root)
            app.pop('evidence');app.pop('reviewer');app.pop('checks')
            panel['memory_applications']={'generation':[app]}
            state={gate.FIELD:gate.POLICY,'input_semantics_policy':sem.PREPARED_POLICY,'execution_mode':'episode_async_v1'}
            self.assertEqual(application_errors(source,'generation',panel,root,scope=state),[])
            self.assertTrue(application_errors(source,'generation',panel,root))
            panel['prompt']='missing constraint'
            self.assertTrue(application_errors(source,'generation',panel,root,scope=state))

class SavedObservations(unittest.TestCase):
    def setUp(self):
        h=legacy.RealInputBinding('test_real_final_input_binds_without_mutating_files');h.setUp();self.addCleanup(h.doCleanups);self.h=h
        h.state.update(execution_mode='episode_async_v1', input_semantics_policy=sem.PREPARED_POLICY)
        h.state[gate.FIELD]=gate.POLICY
        self.path=h.root/'00_输入审计/生产流程.json';self.path.parent.mkdir(exist_ok=True)
        self.path.write_text(json.dumps(h.state))
    def observations(self, ids=None):
        value=entry.prepare(self.path,ids)
        for row in value['panels']:row['observation']=copy.deepcopy(OBS)
        return value
    def test_save_replaces_only_selected_row_and_preserves_old_audit_and_attempts(self):
        h=self.h;old=checked_file(h.root,h.state['semantic_audit']);raw=old.read_bytes();panels=copy.deepcopy(h.state['panels'])
        value=self.observations(['P002']);value['panels'][0]['observation']['issues']=[{'code':'COMPOSITION_DETAIL','detail':'SYNTHETIC acceptable crop','affects_story':False}]
        result=entry.save(self.path,value,'SYNTHETIC');self.assertEqual(result['status'],'SAVED',result)
        after=read_json(self.path);audit=read_json(checked_file(h.root,after['semantic_audit']))
        self.assertEqual(old.read_bytes(),raw);self.assertEqual(after['panels'],panels)
        for i in (0,2,3):self.assertEqual(audit['panels'][i],h.audit['panels'][i])
        self.assertEqual(result['review']['warnings']['P002'][0]['code'],'COMPOSITION_DETAIL')
        self.assertEqual(result['decision_phases'],[])
    def test_negative_observation_saves_truth_but_cannot_pass(self):
        value=self.observations(['P002']);value['panels'][0]['observation']['key_event_readable']=False
        result=entry.save(self.path,value,'SYNTHETIC');self.assertEqual(result['status'],'SAVED_WITH_HOLDS')
        self.assertEqual(list(result['review']['errors']),['P002'])
    def test_changed_actual_prompt_rejects_stale_observation(self):
        h=self.h;value=self.observations(['P002']);record=h.state['panels'][1];p=checked_file(h.root,record['package_manifest']);data=read_json(p)
        data['panels'][0]['prompt']+='\nSYNTHETIC changed action'
        (h.root/data['panels'][0]['prompt_file']).write_text(data['panels'][0]['prompt'])
        record['package_manifest']=legacy.fixture.fixtures.write(h.root,p.name,data)
        self.path.write_text(json.dumps(h.state));before=self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'输入已改变'):entry.save(self.path,value,'SYNTHETIC')
        self.assertEqual(self.path.read_bytes(),before)
    def test_explicit_dependency_plan_without_previous_package(self):
        h=self.h;shot=h.shots['panels'][1];shot['generation_dependencies']=['P001']
        shot['continuity_contract']['generation_dependency_reasons']={'P001':'SYNTHETIC preceding image reference'}
        h.state['shot_manifest']=legacy.fixture.fixtures.write(h.root,'new-shots.json',h.shots)
        h.audit['shot_manifest']=h.state['shot_manifest'];h.save_audit()
        path=checked_file(h.root,h.state['panels'][1]['package_manifest']);panel=read_json(path)['panels'][0]
        refs=[copy.deepcopy(r) for r in panel['reference_images']]+[{'path':'@DEPENDENCY:P001'}]
        row={'panel_id':'P002','reference_path_basis':'run_root',
             'arguments':{'prompt':panel['prompt'],'transparent_background':False,'referenced_image_paths':[r['path'] for r in refs]},
             'reference_files':refs,'reference_bindings':[*panel['reference_bindings'],{'alias':'@PREV','purpose':'continuity'}],
             'output_spec':panel.get('output_spec')}
        plan={'policy':'dependency_completion_plan_v1','scope':'episode',
              **{k:h.state[k] for k in ('book_id','episode_id','visual_basis','shot_manifest')},'inputs':[row]}
        ref=legacy.fixture.fixtures.write(h.root,'dependency-plan.json',plan)
        self.path.write_text(json.dumps(h.state))
        value=entry.prepare(self.path,['P002'],dependency_plan=ref)
        self.assertEqual(value['panels'][0]['inputs']['references'][-1],{'dependency':'P001'})
        value['panels'][0]['observation']=copy.deepcopy(OBS)
        result=entry.save(self.path,value,'SYNTHETIC');self.assertEqual(result['status'],'SAVED',result)
        self.assertEqual(result['review']['pending_real_reference_review_ids'],['P002'])

    def test_broken_prompt_or_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):entry.prepare(self.path,['P002','P002'])
        h=self.h;p=checked_file(h.root,h.state['panels'][1]['package_manifest']);packet=read_json(p)
        (h.root/packet['panels'][0]['prompt_file']).write_text('broken')
        with self.assertRaises(ValueError):entry.prepare(self.path,['P002'])

class FullGate(unittest.TestCase):
    def fixture(self):
        from test_direct_handoff import DirectHandoffTests
        f=DirectHandoffTests('test_direct_bound_run_real_full_episode_gates_and_conditional_release')
        f.FINAL_SEMANTICS=True;f.SEMANTICS_VERSION=sem.PREPARED_POLICY;f.LIGHT_PREPARATION=True
        f.setUp();self.addCleanup(f.doCleanups);return f
    def test_one_observation_runs_full_gates_and_frozen_handoff(self):
        f=self.fixture()
        from panel_readiness import report
        from execution_contract import semantic_errors
        self.assertEqual(report(f.state,f.template)['prepared_panel_ids'],['P001','P002','P003','P004'])
        self.assertEqual(semantic_errors(f.state,f.template,{'batch_id':'EPISODE','panel_ids':['P001','P002','P003','P004']}),[])
        f.test_direct_bound_run_real_full_episode_gates_and_conditional_release()
    def test_save_and_automatic_scoped_decisions_require_real_delegation(self):
        f=self.fixture();path=f.template/f.state_ref['path']
        value=entry.prepare(path,['P002']);value['panels'][0]['observation']=copy.deepcopy(OBS)
        grant={'policy':'user_delegation_v1','status':'AUTHORIZED','source_kind':'user_message',
          'quote':'SYNTHETIC authorized preparation only','source_locator':'synthetic://not-user',
          'constraints':['SYNTHETIC isolated test'], 'book_id':f.state['book_id'],'episode_ids':['E000'],
          'panel_ids':{'E000':['P002']},'phases':['shot_design','generation_package']}
        ref=legacy.fixture.fixtures.write(f.template,'synthetic-grant.json',grant)
        result=entry.save(path,value,'SYNTHETIC',authority_ref=ref)
        self.assertEqual(result['decision_phases'],['shot_design','generation_package'])
        after=read_json(path);index=read_json(checked_file(f.template,after['approval_index']))
        self.assertEqual(index['entries'][-1]['panel_ids'],['P002'])
        grant['retained_user_phases']=['generation_package']
        ref=legacy.fixture.fixtures.write(f.template,'retained-grant.json',grant)
        before=path.read_bytes()
        with self.assertRaisesRegex(ValueError,'亲审'):entry.save(path,value,'SYNTHETIC',authority_ref=ref)
        self.assertEqual(path.read_bytes(),before)

if __name__=='__main__':unittest.main()
