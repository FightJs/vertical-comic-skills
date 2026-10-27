"""The four requested changes: real local artifacts/QA, no image-service calls."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
from input_dependencies import fingerprint,file_hash
from panel_source import expand
from panel_derivation import derive,receipt_pointer
import test_light_review as light_fixture
from light_review import REPAIR_FIELD,REPAIR_POLICY,template
from codex_reference_contract import read_json,digest
from review_pipeline import save

class IncrementalTests(unittest.TestCase):
    def fixture(self,count=3):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        ids=[f'P{i:03d}' for i in range(1,count+1)];locked={pid:'SYNTHETIC '+pid for pid in ids}
        snap=root/'snapshot.json';snap.write_text(json.dumps({'panel_ids':ids,'locked_scripts':locked}))
        rows=[]
        for pid in ids:
            shot={'panel_id':pid,'locked_script':locked[pid],'visual_focus':'original'}
            execution={'prompt':'synthetic preserved input'}
            rows.append({'panel_id':pid,'shot':shot,'execution':execution,'packet_header':{'book_id':'SYNTHETIC','episode_id':'E001'},
                'render_mode':'preserved_import','import_panel_key':fingerprint({**shot,**execution})})
        source={'policy':'panel_authoring_source_v1','status':'WORKING_DRAFT','book_id':'SYNTHETIC','episode_id':'E001',
            'run_root':str(root),'source_snapshot':{'path':str(snap),'sha256':file_hash(snap)},'panel_ids':ids,'panels':rows,
            'shared':{},'shot_header':{'book_id':'SYNTHETIC','episode_id':'E001'}}
        path=root/'source.json';path.write_text(json.dumps(source));return root,path,source

    def test_unchanged_35_and_165_reuse_without_previous_argument(self):
        for count in (35,165):
            with self.subTest(count=count):
                root,path,source=self.fixture(count)
                first=derive(path,root/'drafts/first');second=derive(path,root/'drafts/second')
                self.assertEqual(first['metrics']['compiled_panels'],count)
                self.assertEqual(second['metrics']['compiled_panels'],0)
                self.assertEqual(second['metrics']['reused_panels'],count)
                self.assertEqual(second['previous_derivation']['mode'],'automatic')
                self.assertEqual(second['panels'][0]['artifacts'],first['panels'][0]['artifacts'])

    def test_local_edit_recompiles_only_changed_panel(self):
        root,path,source=self.fixture();derive(path,root/'drafts/first')
        row=source['panels'][1];row['shot']['visual_focus']='actual changed action'
        row['execution']['prompt']='synthetic newly compiled prose'
        row['import_panel_key']=fingerprint({**row['shot'],**row['execution']})
        path.write_text(json.dumps(source));result=derive(path,root/'drafts/second')
        self.assertEqual(result['impact']['affected_panel_ids'],['P002'])
        self.assertEqual(result['metrics']['compiled_panels'],1);self.assertEqual(result['metrics']['reused_panels'],2)

    def test_real_dependents_recompile_but_unrelated_panels_reuse(self):
        root,path,source=self.fixture(4)
        source['panels'][2]['dependencies']=['P002'];path.write_text(json.dumps(source))
        derive(path,root/'drafts/first')
        row=source['panels'][1];row['shot']['visual_focus']='changed action';row['execution']['prompt']='recompiled changed action'
        row['import_panel_key']=fingerprint({**row['shot'],**row['execution']});path.write_text(json.dumps(source))
        result=derive(path,root/'drafts/second')
        self.assertEqual(result['impact']['affected_panel_ids'],['P002','P003'])
        self.assertEqual(result['metrics']['compiled_panels'],2);self.assertEqual(result['metrics']['reused_panels'],2)

    def test_missing_index_recovers_old_receipt_without_full_rebuild(self):
        root,path,source=self.fixture();derive(path,root/'04_B提示词包_CANDIDATE/first')
        receipt_pointer(path).unlink()
        result=derive(path,root/'04_B提示词包_CANDIDATE/second')
        self.assertEqual(result['metrics']['compiled_panels'],0)

    def test_corrupt_artifact_rebuilds_only_that_panel(self):
        root,path,source=self.fixture();first=derive(path,root/'drafts/first')
        Path(first['panels'][1]['artifacts'][1]['path']).write_text('changed')
        result=derive(path,root/'drafts/second')
        self.assertEqual(result['metrics']['compiled_panels'],1);self.assertEqual(result['metrics']['reused_panels'],2)

    def test_other_source_same_book_and_episode_not_implicitly_reused(self):
        root,path,source=self.fixture();derive(path,root/'drafts/first')
        second=root/'another-source.json';second.write_text(path.read_text())
        result=derive(second,root/'drafts/second')
        self.assertEqual(result['previous_derivation']['mode'],'first_derivation')
        self.assertEqual(result['metrics']['compiled_panels'],3)

    def test_minimal_template_replaces_actors_without_mutating_shared(self):
        library={'ordinary':{'characters':['old'],'shot_scale':'medium','camera_position':'approved-position'}}
        value=expand({'$shared':'ordinary','$overrides':{'characters':['current'],'shot_scale':'close'}},library)
        self.assertEqual(value,{'characters':['current'],'shot_scale':'close','camera_position':'approved-position'})
        self.assertEqual(library['ordinary']['characters'],['old'])


class EssentialRepairTests(unittest.TestCase):
    def fixture(self):
        f=light_fixture.LightReviewTests();self.addCleanup(f.doCleanups)
        h,path,row,proposal=f.fixture();state=read_json(path);state[REPAIR_FIELD]=REPAIR_POLICY;path.write_text(json.dumps(state))
        report={'source_manifest_sha256':row['package_manifest']['sha256'],'image_review_profile':'light_story_review_v1',
            'panels':[template(row,state)]}
        proposal['qa_template']=h.h.f.write('essential-template.json',report)
        proposal['light_observations']={'single_observation':'SYNTHETIC actual character and story observation','issues':[]}
        return h,path,row,proposal

    def repair(self,p,impact):
        p['verdict']='FAIL';issue={'location':'action','problem':'observed problem','target':'actual target','story_critical':True,'story_impact':impact}
        p['light_observations']['issues']=[issue]
        p['decision']={'action':'local_edit','reason':'SYNTHETIC actual reason','issues':[{**issue,'id':'I1','category':1,
            'kind':'story','certainty':'confirmed','basis':'actual observation','handling':'repair',
            'observations':['/light_review/issues/0']}], 'fix_now':['I1'],'manual':[],'opportunistic':[],
            'method_key':'local-action','cause_key':'action-target','preserve_constraints':['keep identity']}
        p['adopt']=False

    def test_new_template_is_single_look_from_start(self):
        h,path,row,p=self.fixture();qa=read_json(h.root/p['qa_template']['path'])['panels'][0]['light_review']
        self.assertNotIn('checks',qa);self.assertEqual(qa['single_observation'],'')
        save(path,digest(path),p)
        state=read_json(path);self.assertTrue(state['panels'][0].get('adoption'))
        from panel_delivery import build
        self.assertEqual(build(state,h.root)['panels'][0]['outcome'],'DELIVERABLE')

    def test_readable_major_issue_is_adopted_without_new_attempt(self):
        h,path,row,p=self.fixture();self.repair(p,'readable');save(path,digest(path),p)
        state=read_json(path);current=state['panels'][0]
        from production_decisions import selected
        self.assertEqual(selected(h.root,current)[1]['action'],'defer_manual')
        self.assertEqual(current['status'],'VISUAL_FAIL');self.assertEqual(current['round_id'],1)
        self.assertEqual(current['output'],row['output'])
        from panel_delivery import build
        self.assertEqual(build(state,h.root)['panels'][0]['outcome'],'MANUAL_PRIORITY')

    def test_essential_story_error_still_allows_one_repair(self):
        h,path,row,p=self.fixture();self.repair(p,'story_reversed');save(path,digest(path),p)
        state=read_json(path);current=state['panels'][0]
        from production_decisions import load_decision
        from repair_routes import plan
        decision=load_decision(h.root,current,current['attempt_id'])[1]
        self.assertTrue(plan(decision,current)['image_call_allowed'])
        self.assertFalse(current.get('adoption'))

    def test_policy_cannot_be_removed_from_template(self):
        h,path,row,p=self.fixture();report=read_json(h.root/p['qa_template']['path']);report['panels'][0]['light_review'].pop(REPAIR_FIELD)
        p['qa_template']=h.h.f.write('downgraded-template.json',report)
        with self.assertRaisesRegex(ValueError,'threshold mismatch'):save(path,digest(path),p)

if __name__=='__main__':unittest.main()
