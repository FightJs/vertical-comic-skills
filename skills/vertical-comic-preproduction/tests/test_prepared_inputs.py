"""Prepared inputs through real CLI, full gates and frozen handoff; synthetic only."""
import copy,json,subprocess,sys,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import input_semantics as sem
import test_input_semantics as legacy
import test_rule_memory as rules
from codex_reference_contract import checked_file,read_json
from production_runtime import episode_bundle
from _historical_fixture import compile_jobs


class PreparedInputs(unittest.TestCase):
    def setUp(self):
        h=legacy.RealInputBinding('test_real_final_input_binds_without_mutating_files');h.setUp()
        self.addCleanup(h.doCleanups);self.h=h
        h.state['input_semantics_policy']=sem.PREPARED_POLICY
        for row,shot,record in zip(h.audit['panels'],h.shots['panels'],h.state['panels']):
            path=checked_file(h.root,record['package_manifest'])
            row['execution_review']=legacy.reviewed(sem.actual_input(h.state,h.root,shot,read_json(path),path.parent))
        h.save_audit()

    def test_real_cli_and_compile_use_reviewed_prompt_without_new_authority(self):
        from test_direct_handoff import DirectHandoffTests
        from types import SimpleNamespace
        f=DirectHandoffTests('test_direct_bound_run_real_full_episode_gates_and_conditional_release')
        f.FINAL_SEMANTICS=True;f.SEMANTICS_VERSION=sem.PREPARED_POLICY;f.setUp();self.addCleanup(f.doCleanups)
        h=SimpleNamespace(state=f.state,root=f.template,audit=read_json(checked_file(f.template,f.state['semantic_audit'])))
        state=f.state_ref
        command=[sys.executable,'-B',str(Path(sem.__file__).with_name('production_runtime.py')),
                 '--state',str(h.root/state['path']),'--action','compile','--panels','P002']
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        value=json.loads(result.stdout);job=value['jobs'][0]
        packet=read_json(checked_file(h.root,h.state['panels'][1]['package_manifest']))
        self.assertEqual(job['arguments']['prompt'],packet['panels'][0]['prompt'])
        self.assertEqual(job['prepared_input_digest'],h.audit['panels'][1]['execution_review']['input_digest'])
        self.assertEqual(value['image_calls'],0)
        self.assertEqual(value['user_approval'],'NOT_GRANTED')

    def test_first_batch_policy_keeps_v2_preparation_checks(self):
        h=self.h;h.state['production_policy']='first_batch_production_v1'
        self.assertEqual(h.check(),[])
        h.audit['panels'][1]['execution_review']['checks']['appearance_anchors']['expected']={}
        h.save_audit();self.assertTrue(h.check(1))

    def test_missing_or_fabricated_preparation_targets_cannot_pass(self):
        h=self.h
        for key in sem.PREPARED_CHECKS:
            original=copy.deepcopy(h.audit['panels'][1]['execution_review'])
            h.audit['panels'][1]['execution_review']['checks'][key]['expected']={}
            h.save_audit();self.assertTrue(h.check(),key)
            h.audit['panels'][1]['execution_review']=original
        h.save_audit();self.assertEqual(h.check(),[])

    def test_unrelated_panel_keeps_review_after_one_input_changes(self):
        h=self.h;record=h.state['panels'][1];path=checked_file(h.root,record['package_manifest'])
        packet=read_json(path);p=packet['panels'][0];p['prompt']+='\nSYNTHETIC new local constraint'
        (h.root/p['prompt_file']).write_text(p['prompt'],encoding='utf-8')
        record['package_manifest']=legacy.fixture.fixtures.write(h.root,path.name,packet)
        self.assertTrue(h.check(1));self.assertEqual(h.check(2),[])

    def test_dependency_requires_reason_but_comparison_does_not_become_dependency(self):
        h=self.h;shot=copy.deepcopy(h.shots['panels'][1]);packet=read_json(checked_file(h.root,h.state['panels'][1]['package_manifest']));p=packet['panels'][0]
        base=sem.preparation_basis(h.state,h.root,shot,p,p['prompt'])
        self.assertEqual(base['preparation_targets']['continuity_and_dependencies']['generation_dependencies'],[])
        shot['generation_dependencies']=['P001'];p['generation_dependencies']=['P001']
        with self.assertRaisesRegex(ValueError,'依赖须逐项'):sem.preparation_basis(h.state,h.root,shot,p,p['prompt'])
        shot['continuity_contract']['generation_dependency_reasons']={'P001':'SYNTHETIC reference needed for exact contact state'}
        p['continuity_contract']=copy.deepcopy(shot['continuity_contract'])
        target=sem.preparation_basis(h.state,h.root,shot,p,p['prompt'])['preparation_targets']['continuity_and_dependencies']
        self.assertEqual(target['generation_dependencies'],['P001'])
        self.assertEqual(shot['generation_dependencies'],['P001'])

    def test_actual_rule_mapping_cannot_omit_prompt_or_forge_exclusion(self):
        h=self.h;h.state['memory_source']=rules.library(h.root/'rules')
        shot=copy.deepcopy(h.shots['panels'][1]);p=copy.deepcopy(shot);p['memory_tags']=['person_on_bed']
        app=rules.applied(h.state['memory_source'],'generation',p,h.root)
        p['memory_applications']={'generation':[app]}
        with self.assertRaisesRegex(ValueError,'未落实'):sem.preparation_basis(h.state,h.root,shot,p,'missing')
        plan=sem.preparation_basis(h.state,h.root,shot,p,app['prompt_constraints'][0])
        self.assertEqual(plan['preparation_targets']['rule_execution_coverage']['generation'][0]['prompt_constraints'],app['prompt_constraints'])
        app.update(decision='NOT_APPLICABLE',reason='SYNTHETIC skip tagged rule')
        with self.assertRaisesRegex(ValueError,'排除依据'):sem.preparation_basis(h.state,h.root,shot,p,app['prompt_constraints'][0])

    def test_template_cli_exposes_targets_and_keeps_original_design_checks(self):
        h=self.h;state=legacy.fixture.fixtures.write(h.root,'00_输入审计/生产流程.json',h.state);out=h.root/'new-review.json'
        result=subprocess.run([sys.executable,'-B',sem.__file__,'--state',str(h.root/state['path']),'--output',str(out),'--panels','P002'],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        data=json.loads(out.read_text(encoding='utf-8'));row=data['panels'][1]
        self.assertEqual(row['checks'],h.audit['panels'][1]['checks'])
        self.assertEqual(row['execution_review']['policy'],sem.PREPARED_POLICY)
        for key in sem.PREPARED_CHECKS:
            self.assertIn('expected',row['execution_review']['checks'][key])
            self.assertEqual(row['execution_review']['checks'][key]['status'],'UNREVIEWED')

    def test_cached_preparation_cannot_ignore_changed_manifest_reference(self):
        from codex_reference_contract import file_session
        h=self.h;shot=h.shots['panels'][1];path=checked_file(h.root,h.state['panels'][1]['package_manifest']);packet=read_json(path)
        with file_session():
            sem.actual_input(h.state,h.root,shot,packet,path.parent)
            other=copy.deepcopy(h.state);other['shot_manifest']={'path':'missing-new-manifest.json','sha256':'0'*64}
            with self.assertRaises((ValueError,OSError)):
                sem.actual_input(other,h.root,shot,packet,path.parent)

    def test_full_prepared_handoff_keeps_version_after_real_extract_bind(self):
        from test_direct_handoff import DirectHandoffTests
        f=DirectHandoffTests('test_direct_bound_run_real_full_episode_gates_and_conditional_release')
        f.FINAL_SEMANTICS=True;f.SEMANTICS_VERSION=sem.PREPARED_POLICY
        f.setUp();self.addCleanup(f.doCleanups)
        f.test_direct_bound_run_real_full_episode_gates_and_conditional_release()
        state=json.loads((f.base/'local-run/E000/00_输入审计/生产流程.json').read_text(encoding='utf-8'))
        self.assertEqual(state['input_semantics_policy'],sem.PREPARED_POLICY)

if __name__=='__main__':unittest.main()
