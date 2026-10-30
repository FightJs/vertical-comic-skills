"""Ordinary inputs are technically ready without fabricated observations."""
import copy,json,sys,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).parents[1]/'scripts'),str(Path(__file__).parent)]
import preparation_gate_policy as gate
import input_semantics as sem
import preparation_review as entry
from codex_reference_contract import read_json,checked_file,digest


class Records(unittest.TestCase):
    def inputs(self,targets=()):
        return {gate.FIELD:gate.EXCEPTION,'input_semantics_policy':sem.PREPARED_POLICY,
                'prompt':'SYNTHETIC','preparation_requirements':list(targets)}
    def test_ordinary_no_observation_or_reviewer(self):
        inputs=self.inputs();r=gate.exception_record(inputs)
        self.assertEqual(gate.review_errors(r,inputs),[])
        self.assertEqual(r['status'],'TECHNICALLY_READY')
        self.assertFalse(r['review_performed']);self.assertNotIn('reviewer',r);self.assertNotIn('observation',r)
    def test_targeted_requires_evidence_and_cannot_clear_negative_issue(self):
        inputs=self.inputs([{'id':'contact:0','expected':{'kind':'contact'}}])
        with self.assertRaises(ValueError):gate.exception_record(inputs)
        r=gate.exception_record(inputs,{'evidence':'SYNTHETIC contact','issues':[]},'SYNTHETIC')
        self.assertEqual(gate.review_errors(r,inputs),[])
        r['observation']['issues']=[{'code':'STORY_REVERSED','detail':'SYNTHETIC','affects_story':True}]
        self.assertTrue(gate.review_errors(r,inputs))
    def test_changed_input_and_old_review_are_not_relabelled(self):
        inputs=self.inputs();r=gate.exception_record(inputs)
        self.assertTrue(gate.review_errors(r,{**inputs,'prompt':'changed'}))
        old={'execution_review':{gate.FIELD:gate.POLICY,'status':'UNREVIEWED'}}
        self.assertTrue(gate.design_errors(old,{gate.FIELD:gate.EXCEPTION},{}))
    def test_ordinary_negative_observation_cannot_be_ignored(self):
        with self.assertRaises(ValueError):gate.exception_record(self.inputs(),{'key_event_readable':False})


class Flow(unittest.TestCase):
    def setUp(self):
        from test_direct_handoff import DirectHandoffTests
        f=DirectHandoffTests('test_direct_bound_run_real_full_episode_gates_and_conditional_release')
        f.FINAL_SEMANTICS=True;f.SEMANTICS_VERSION=sem.PREPARED_POLICY;f.setUp();self.addCleanup(f.doCleanups);self.f=f
        # A synthetic NEW policy fixture, never a production migration.
        s=f.state;s[gate.FIELD]=gate.EXCEPTION
        audit=read_json(checked_file(f.template,s['semantic_audit']))
        audit[gate.FIELD]=gate.EXCEPTION;audit['panels']=[{'panel_id':r['panel_id']} for r in audit['panels']]
        from test_panel_readiness import fixtures
        s['semantic_audit']=fixtures.write(f.template,'new-policy-audit.json',audit)
        self.path=f.template/f.state_ref['path'];self.path.write_text(json.dumps(s))
    def test_finalize_ordinary_then_compile_without_observations(self):
        r=entry.finalize(self.path);self.assertEqual(r['status'],'SAVED',r)
        s=read_json(self.path);c=sem.coverage(s,self.f.template)
        self.assertEqual(c['status'],'PREPRODUCTION_INPUTS_READY',c)
        self.assertEqual(c['reviewed_panel_ids'],[])
        audit=read_json(checked_file(self.f.template,s['semantic_audit']))
        self.assertTrue(all('observation' not in p['execution_review'] for p in audit['panels']))
        from production_runtime import episode_bundle
        bundle=episode_bundle(s,self.f.template)
        self.assertEqual(len(bundle['inputs']),4)

    def test_unchanged_finalize_is_read_only(self):
        entry.finalize(self.path);before=self.path.read_bytes()
        result=entry.finalize(self.path)
        self.assertEqual(result['status'],'REUSED')
        self.assertEqual(before,self.path.read_bytes())

    def test_valid_targeted_record_is_reused_without_new_observer(self):
        from unittest.mock import patch
        actual=entry.inputs_for
        def inputs(*args,**kwargs):
            result=copy.deepcopy(actual(*args,**kwargs))
            if 'P002' in result:result['P002']['preparation_requirements']=[{'id':'contact:0','expected':{'kind':'contact'}}]
            return result
        with patch.object(entry,'inputs_for',side_effect=inputs):
            observations=entry.prepare(self.path,['P002'])
            observations['panels'][0]['observation']={'evidence':'SYNTHETIC contact checked','issues':[]}
            # Save exercises the real record path; coverage below uses the real fixture's ordinary shot.
            entry.save(self.path,observations,'SYNTHETIC original observer')
            result=entry.finalize(self.path)
        self.assertEqual(result['targeted_panel_ids'],[])
        s=read_json(self.path);audit=read_json(checked_file(self.f.template,s['semantic_audit']))
        review=next(r for r in audit['panels'] if r['panel_id']=='P002')['execution_review']
        self.assertEqual(review['reviewer'],'SYNTHETIC original observer')
    def test_new_policy_real_directory_handoff(self):
        entry.finalize(self.path);f=self.f;f.state=read_json(self.path)
        from production_runtime import episode_bundle
        import test_panel_readiness as fixtures
        fixtures.approve_package(f.template,f.state,episode_bundle(f.state,f.template),f.index['episodes'][0]['panel_ids'])
        e=f.index['episodes'][0]
        e['semantic_audit']=f.ref('template/E000/'+f.state['semantic_audit']['path'])
        e['approval_evidence']=f.ref('template/E000/'+f.state['approval_index']['path'])
        e['generation_review_packages']=[f.ref('template/E000/'+r['path']) for r in f.state['generation_packages']['EPISODE']]
        f.refresh_template();f.test_direct_bound_run_real_full_episode_gates_and_conditional_release()

    def test_broken_input_not_ready_without_review(self):
        s=read_json(self.path);r=s['panels'][0];p=checked_file(self.f.template,r['package_manifest'])
        packet=read_json(p);(p.parent/packet['panels'][0]['prompt_file']).write_text('broken')
        result=entry.finalize(self.path)
        self.assertEqual(result['status'],'PARTIAL_READY')
        self.assertEqual(result['blocked_panel_ids'],['P001'])
        self.assertEqual(result['panel_ids'],['P002','P003','P004'])

    def test_targeted_panel_does_not_stop_ordinary_finalization(self):
        from unittest.mock import patch
        actual=entry.inputs_for
        def inputs(*args,**kwargs):
            result=copy.deepcopy(actual(*args,**kwargs))
            if 'P002' in result:result['P002']['preparation_requirements']=[{'id':'contact:0','expected':{'kind':'contact'}}]
            return result
        with patch.object(entry,'inputs_for',side_effect=inputs):result=entry.finalize(self.path)
        self.assertEqual(result['panel_ids'],['P001','P003','P004'])
        self.assertEqual(result['targeted_panel_ids'],['P002'])
        self.assertEqual(result['status'],'PARTIAL_READY')


if __name__=='__main__':unittest.main()
