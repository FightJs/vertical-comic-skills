from asset_format_fixture import reviewed
"""Source scope and durable recovery regressions, isolated from real assets."""
import copy, hashlib, json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from openpyxl import Workbook
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import script_catalog as sc
import costume_requirements as cr
import asset_catalog as ac
import handoff_continuity as hc

class SourceScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        w=Workbook();a=w.active;a.title='第60话';a.append(['格号','出现角色','画面内容','当前时间','台词']);a.append([1,'甲','衬衫','当晚','我去换衣服'])
        b=w.create_sheet('第61话');b.append(['格号','出现角色','画面内容']);b.append([1,'甲','同场延续']);b.append([2,'甲','同场延续'])
        w.save(self.root/'script.xlsx')
        catalog=sc.discover(self.root,'B',['E060']);self.catalog=sc.select(catalog,{e:{'path':'script.xlsx','version':'v1','source_evidence':'actual sheet'} for e in ('E060','E061')},evidence='test selection')
        self.req={'requirement_id':'R','character_id':'C','costume_id':'S','source_basis':'E060/P001','panel_ids':['P001'],'episode_id':'E060'}
    def observations(self,ids):
        return [{'episode_id':'E061','panel_id':p,'character_id':'C','costume_id':'S','visible':True,'match':'CONFIRMED','source_sha256':sc.digest(self.root/'script.xlsx'),'evidence':'actual source observation'} for p in ids]
    def plan(self,ids):return cr.plan('B',['E060'],[self.req],self.observations(ids),coverage='UNKNOWN',source_catalog=self.catalog)
    def test_nonexistent_source_panels_rejected(self):
        with self.assertRaisesRegex(ValueError,'panel|源格'):self.plan(['P998','P999'])
    def test_noncanonical_alias_does_not_count_twice(self):
        with self.assertRaisesRegex(ValueError,'panel|源格'):self.plan(['P1','P001'])
    def test_observation_must_be_selected_as_future(self):
        self.catalog['future_reference_episode_ids']=[]
        with self.assertRaisesRegex(ValueError,'future|后续'):self.plan(['P001','P002'])
    def test_current_requirement_must_exist_in_production_source(self):
        self.req['panel_ids']=['P999']
        with self.assertRaisesRegex(ValueError,'panel|源格'):self.plan(['P001','P002'])
    def test_asset_task_cannot_borrow_other_episode_requirement(self):
        import asset_tasks
        plan=self.plan(['P001','P002'])
        task={'asset_id':'A','requirement_id':'R','character_id':'C','costume_id':'S','episode_id':'E059','panel_ids':['P001'],'visible_occurrences':1,'source_basis':'source'}
        result=asset_tasks.audit(self.root,[task],reuse_plan=plan)['asset_tasks'][0]
        self.assertEqual(result['reuse_decision'],'REUSE_HOLD');self.assertFalse(result['publication_required'])
    def test_change_cues_in_dialogue_and_time_are_preserved(self):
        row=sc.workbook_hints(self.root/'script.xlsx')[0]['panel_evidence'][0]
        self.assertEqual(row['当前时间'],'当晚');self.assertEqual(row['台词'],'我去换衣服')
    def test_source_scene_is_available_to_semantic_review(self):
        catalog=sc.discover(self.root,'B',['E060'])
        evidence=catalog['files'][0]['workbook_evidence'][1]['panel_evidence'][0]
        self.assertIn('source_panel',evidence)

class DurableAssetTests(SourceScopeTests):
    def record(self):
        self.image=self.root/'image.png';self.image.write_bytes(b'test image');digest=sc.digest(self.image)
        self.reuse=self.plan(['P001','P002']);occ=self.reuse['requirements'][0]['future_occurrences']
        return {'policy':ac.POLICY,'book_id':'B','asset_id':'A','character_id':'C','costume_id':'S','production_episode_ids':['E060'],
            'source_basis':'actual source','future_occurrences':occ,'sha256':digest,'relative_path':'states/a.png',
            'authorization':{'source_kind':'user_message','source_locator':'test-only','quote':'test-only','book_id':'B','asset_ids':['A'],'episode_ids':['E060'],'operations':['publish']},
            'format_review':reviewed(digest),'review':{'status':'PASS','asset_id':'A','image_sha256':digest,'reviewer':'test-only','evidence':'not real QA'}}
    def test_saved_asset_registration_replays_without_original_source(self):
        record=self.record();assets=self.root/'assets';assets.mkdir();original=ac.atomic_json
        def interrupted(path,value):
            if Path(path).name=='衣装增量索引.json':raise OSError('interrupted index')
            return original(path,value)
        with patch.object(ac,'atomic_json',side_effect=interrupted):
            with self.assertRaises(OSError):ac.publish(assets,record,self.image,reuse_plan=self.reuse)
        self.image.unlink();(self.root/'script.xlsx').unlink()
        self.assertEqual(ac.publish(assets,record,self.image,reuse_plan=self.reuse)['status'],'PUBLISHED')
    def test_already_published_replay_does_not_require_original_script(self):
        record=self.record();assets=self.root/'assets';assets.mkdir();ac.publish(assets,record,self.image,reuse_plan=self.reuse)
        self.image.unlink();(self.root/'script.xlsx').unlink()
        self.assertEqual(ac.publish(assets,record,self.image,reuse_plan=self.reuse)['status'],'ALREADY_PUBLISHED')

if __name__=='__main__':unittest.main()

class ProfileCompatibilityTests(unittest.TestCase):
    def test_explicit_folder_replaces_book_source_with_recoverable_profile(self):
        import comic_start
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source=root/'old.xlsx';source.write_bytes(b'existing single input');assets=root/'assets';assets.mkdir()
            folder=root/'scripts';folder.mkdir();w=Workbook();w.active.title='第60话';w.active.append(['格号']);w.active.append([1]);w.save(folder/'new.xlsx')
            with patch.dict('os.environ',{'CODEX_HOME':str(root/'codex')}):
                first=comic_start.prepare(root,'B',['E060'],script=source,assets=assets,runtime_limit_seconds=None)
                profile=Path(first['profile']);data=json.loads(profile.read_text());data['user_preference']='keep';profile.write_text(json.dumps(data));before=profile.read_bytes()
                second=comic_start.prepare(root,'B',['E060'],script=folder,runtime_limit_seconds=None)
            self.assertEqual(json.loads(profile.read_text())['script_root'],str(folder.resolve()))
            self.assertNotIn('script_path',json.loads(profile.read_text()));self.assertEqual(json.loads(profile.read_text())['user_preference'],'keep')
            backups=list((profile.parent/'backups').glob('*.json'));self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),before)
            self.assertTrue(Path(second['script_catalog']).is_file())

class BoundaryIdempotencyTests(unittest.TestCase):
    def test_staging_replays_lost_acknowledgement(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);package=root/'candidate';package.mkdir();(package/'image.png').write_bytes(b'img')
            index=package/'交接验收索引.json';index.write_text(json.dumps({'book_id':'B','package_id':'K'}))
            record={'policy':hc.POLICY,'book_id':'B','next_episode_id':'E061','source_package_id':'K','characters':[{
                'character_id':'C','costume_id':'S','appearance_state_id':'AS','verification_status':'CONFIRMED','identity_basis':'test',
                'last_confirmed_source_panel':'E060-P001','applicability':'E061 P001','reference':{'path':'image.png','sha256':hc.sha(package/'image.png')}}]}
            old=hc.sha(index);first=hc.stage_boundary(package,record,expected_index_sha256=old)
            replay=hc.stage_boundary(package,record,expected_index_sha256=old)
            self.assertEqual(first['boundary'],replay['boundary']);self.assertEqual(replay['status'],'ALREADY_STAGED_NOT_APPROVED')
            data=json.loads(index.read_text());data['book_id']='OTHER';index.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'book|package'):hc.stage_boundary(package,record,expected_index_sha256=old)
    def test_inherit_conflicting_state_is_local_hold(self):
        boundary={'policy':hc.POLICY,'book_id':'B','next_episode_id':'E061','characters':[{'character_id':'C','costume_id':'S1','appearance_state_id':'AS1','verification_status':'CONFIRMED'}, {'character_id':'D','costume_id':'T','appearance_state_id':'AT','verification_status':'CONFIRMED'}]}
        result=hc.reconcile(boundary,'E061',['P001'],[
            {'panel_id':'P001','character_id':'C','decision':'INHERIT','costume_id':'S2','source_evidence':'changed source'},
            {'panel_id':'P001','character_id':'D','decision':'INHERIT','source_evidence':'unchanged source'}])
        self.assertEqual(result['bindings'][0]['state']['verification_status'],'UNRESOLVED')
        self.assertEqual(result['bindings'][1]['state']['verification_status'],'CONFIRMED')

class AutomationReceiptTests(unittest.TestCase):
    def test_batch_partial_hold_sets_exit_code_and_keeps_receipt(self):
        import subprocess
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);batch=root/'batch.json';batch.write_text('[{}]')
            script=Path(ac.__file__)
            result=subprocess.run([sys.executable,str(script),'--asset-root',str(root),'--batch',str(batch)],capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            self.assertEqual(json.loads(result.stdout)['status'],'PARTIAL_HOLD')
    def test_source_cli_failure_is_structured(self):
        import subprocess
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            result=subprocess.run([sys.executable,str(Path(sc.__file__)),'select','--catalog',str(root/'missing.json'),'--selections',str(root/'missing2.json'),'--evidence','test','--output',str(root/'out.json')],capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            self.assertEqual(json.loads(result.stdout)['status'],'SCRIPT_CATALOG_HOLD')

class PartialIdentityTests(unittest.TestCase):
    def test_unresolved_costume_still_carries_known_identity_image(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source=root/'source';source.mkdir();(source/'identity.png').write_bytes(b'identity')
            package=root/'candidate';package.mkdir();index=package/'交接验收索引.json';index.write_text(json.dumps({'book_id':'B','package_id':'K'}))
            record={'policy':hc.POLICY,'book_id':'B','next_episode_id':'E061','source_package_id':'K','characters':[{
                'character_id':'C','verification_status':'UNRESOLVED','reason':'next costume unknown',
                'identity_reference':{'path':'identity.png','sha256':hc.sha(source/'identity.png')}}]}
            hc.stage_boundary(package,record,expected_index_sha256=hc.sha(index),source_root=source)
            self.assertEqual((package/'identity.png').read_bytes(),b'identity')
