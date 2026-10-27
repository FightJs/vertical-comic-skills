"""Synthetic returned images through real registration/delivery gates; no image service."""
import copy,json,sys,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
from light_review import POLICY, FIELD, template, prepare_observations, review_errors
from codex_reference_contract import read_json,digest
import test_first_batch_production as full_fixture
from review_pipeline import save

class LightReviewTests(unittest.TestCase):
    def fixture(self):
        fixture=full_fixture.FirstBatchTests();self.addCleanup(fixture.doCleanups)
        h,state,row,_,_=fixture.fixture()
        state[FIELD]=POLICY;state['runtime_pipeline_policy']='observed_incremental_pipeline_v1'
        state.pop('batch_reviews',None)
        row['status']='GENERATED'
        for k in ('qa_report','adoption','production_decisions','failure_diagnosis'):row.pop(k,None)
        qa={'source_manifest_sha256':row['package_manifest']['sha256'],FIELD:POLICY,'panels':[template(row)]}
        ref=h.h.f.write('light-template.json',qa)
        path=h.root/'00_输入审计/生产流程.json';path.write_text(json.dumps(state))
        proposal={'panel_id':row['panel_id'],'attempt_id':row['attempt_id'],'base_qa':None,'qa_template':ref,
            'reviewer':'SYNTHETIC','reason':'synthetic one-look observation','verdict':'PASS','adopt':True,
            'light_observations':{'checks':{k:{'status':'PASS','observed':'SYNTHETIC actual image observation'} for k in ('identity','story_readability')},'issues':[]}}
        return h,path,row,proposal

    def test_single_observation_saves_and_delivers_without_full_qa_or_episode_review(self):
        h,path,row,proposal=self.fixture();result=save(path,digest(path),proposal)
        self.assertEqual(result['pending_comparisons'],[])
        state=read_json(path);new=state['panels'][0]
        self.assertEqual(new['status'],'VISUAL_PASS');self.assertEqual(new['output'],row['output'])
        qa=read_json(h.root/new['qa_report']['path'])
        self.assertNotIn('dimension_review',qa['panels'][0])
        from panel_delivery import build
        report=build(state,h.root)
        self.assertEqual(report['panels'][0]['outcome'],'DELIVERABLE')
        self.assertFalse(report['handoff_complete'])  # other source panels are genuinely missing
        self.assertEqual(report[FIELD],POLICY)

    def test_minor_issue_delivers_with_scoped_pass_and_no_repair(self):
        h,path,row,p=self.fixture()
        p['light_observations']['issues']=[{'location':'earring','problem':'minor detail','target':'manual retouch','story_critical':False}]
        save(path,digest(path),p);state=read_json(path);new=state['panels'][0]
        self.assertEqual(new['status'],'VISUAL_PASS');self.assertEqual(new['round_id'],1)
        from production_decisions import selected
        self.assertEqual(selected(h.root,new)[1]['action'],'defer_manual')
        from panel_delivery import build
        report=build(state,h.root)
        self.assertEqual(report['panels'][0]['outcome'],'MANUAL_RETOUCH')
        self.assertEqual(report['panels'][0]['incomplete_reasons'],[])

    def test_unobserved_check_rejected_without_state_write(self):
        h,path,row,p=self.fixture();before=path.read_bytes()
        p['light_observations']['checks']['identity']['observed']=''
        with self.assertRaisesRegex(ValueError,'observation'):save(path,digest(path),p)
        self.assertEqual(before,path.read_bytes())

    def test_critical_issue_cannot_be_reported_as_pass(self):
        h,path,row,p=self.fixture();p['light_observations']['issues']=[{'location':'earring','problem':'wrong actor','target':'correct actor','story_critical':True}]
        with self.assertRaisesRegex(ValueError,'verdict'):save(path,digest(path),p)

    def test_serious_issue_requires_real_repair_plan(self):
        h,path,row,p=self.fixture();p['verdict']='FAIL'
        p['light_observations']['checks']['story_readability']['status']='FAIL'
        p['light_observations']['issues']=[{'location':'action','problem':'wrong target','target':'correct story','story_critical':True}]
        with self.assertRaisesRegex(ValueError,'repair plan'):save(path,digest(path),p)

    def test_old_run_cannot_accept_light_qa(self):
        h,path,row,p=self.fixture();s=read_json(path);s.pop(FIELD);path.write_text(json.dumps(s))
        with self.assertRaisesRegex(ValueError,'cannot be downgraded'):save(path,digest(path),p)

    def test_unknown_result_cannot_be_adopted(self):
        h,path,row,p=self.fixture();s=read_json(path);s['panels'][0]['status']='RESULT_UNKNOWN';path.write_text(json.dumps(s))
        with self.assertRaisesRegex(ValueError,'ATTEMPT_CHANGED'):save(path,digest(path),p)

    def test_image_mutation_rejected(self):
        h,path,row,p=self.fixture();image=h.root/row['output']['path'];image.write_bytes(image.read_bytes()+b'changed')
        with self.assertRaises(ValueError):save(path,digest(path),p)

    def test_revision_preserves_old_qa_and_automatic_decision(self):
        h,path,row,p=self.fixture();save(path,digest(path),p);state=read_json(path);old=state['panels'][0]['qa_report'];before=(h.root/old['path']).read_bytes()
        p.update(base_qa=old,reason='revised actual observation');p['light_observations']['checks']['identity']['observed']='SYNTHETIC revised'
        save(path,digest(path),p);new=read_json(path)['panels'][0]
        self.assertEqual((h.root/old['path']).read_bytes(),before);self.assertNotEqual(old,new['qa_report'])
        self.assertEqual(new['qa_revisions'][-1]['qa_report'],old)

    def test_serious_first_round_repair_decision_registers(self):
        h,path,row,p=self.fixture();p['verdict']='FAIL'
        issue={'location':'action','problem':'wrong action target','target':'correct story action','story_critical':True}
        p['light_observations']['checks']['story_readability']['status']='FAIL'
        p['light_observations']['issues']=[issue]
        d={**issue,'id':'I1','category':1,'kind':'story','certainty':'confirmed',
           'basis':'SYNTHETIC observed story','handling':'one local edit','observations':['/light_review/issues/0']}
        p['decision']={'action':'local_edit','reason':'SYNTHETIC serious story error','issues':[d],
            'fix_now':['I1'],'manual':[],'opportunistic':[],'method_key':'local-action',
            'cause_key':'action-target','preserve_constraints':['keep identity and scene']}
        p['adopt']=False
        save(path,digest(path),p)
        state=read_json(path);new=state['panels'][0]
        from production_decisions import load_decision
        decision=load_decision(h.root,new,new['attempt_id'])[1]
        from repair_routes import plan
        self.assertTrue(plan(decision,new)['image_call_allowed'])
        self.assertEqual(new['round_id'],1)

    def test_prepared_queue_uses_light_template_and_no_detail_fields(self):
        h,path,row,p=self.fixture()
        from production_runtime import prepare_review
        queue={'items':[{'panel_id':row['panel_id'],'action':'REVIEW_STORY_ONCE'}]}
        value=prepare_review(read_json(path),h.root,queue)
        qa=read_json(h.root/value['items'][0]['qa_template']['path'])
        self.assertEqual(qa[FIELD],POLICY)
        self.assertEqual(qa['panels'][0]['light_review']['status'],'UNREVIEWED')
        self.assertNotIn('dimension_review',qa['panels'][0])

    def test_cosmetic_repair_and_second_round_repair_rejected(self):
        from light_review import decision_errors
        for critical,round_id in ((False,1),(True,2)):
            item={'light_review':{'policy':POLICY,'reviewer':'SYNTHETIC','status':'FAIL','checks':{k:{'status':'PASS','observed':'SYNTHETIC'} for k in ('identity','story_readability')},'issues':[{'location':'x','problem':'x','target':'x','story_critical':critical}]}}
            d={'action':'local_edit','fix_now':['I1'],'opportunistic':[],'issues':[{'id':'I1',**item['light_review']['issues'][0],'observations':['/light_review/issues/0']}]}
            self.assertTrue(decision_errors(d,{'round_id':round_id},item))

if __name__=='__main__':unittest.main()
