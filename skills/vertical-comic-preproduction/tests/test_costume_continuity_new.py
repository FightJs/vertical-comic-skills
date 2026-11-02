from asset_format_fixture import reviewed
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from openpyxl import Workbook
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import script_catalog as sc, costume_requirements as cr, asset_catalog as ac, handoff_continuity as hc

def make_catalog(root):
    script=Path(root)/'future.txt'
    script.write_text(json.dumps({'book_id':'B','episodes':{'E001':{'panel_ids':['P001']},'E002':{'panel_ids':['P001','P002']}}}))
    digest=sc.digest(script)
    return {'policy':sc.POLICY,'status':'SELECTED_NOT_APPROVED','book_id':'B','production_episode_ids':['E001'],'root':str(root),'future_reference_episode_ids':['E002'],
            'selected_sources':{e:{'path':'future.txt','sha256':digest} for e in ('E001','E002')}}

def make_plan(root, record):
    catalog=make_catalog(root);digest=catalog['selected_sources']['E002']['sha256']
    for row in record['future_occurrences']:row['source_sha256']=digest
    req={'requirement_id':'R','character_id':'C','costume_id':'S','source_basis':'script','panel_ids':['P001']}
    return cr.plan('B',['E001'],[req],record['future_occurrences'],coverage='UNKNOWN',source_catalog=catalog)

class CostumeContinuityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def test_directory_inventory_and_version_conflict_require_selection(self):
        book=Workbook();sheet=book.active;sheet.title='第51话';sheet.append(['格号','画面内容']);sheet.append([1,'内容']);sheet.append([2,'内容'])
        book.save(self.root/'剧本_v001.xlsx');sheet.append([3,'其他版本']);book.save(self.root/'剧本_v002.xlsx')
        catalog=sc.discover(self.root,'书',['E051'])
        self.assertEqual(len(catalog['files']),2);self.assertEqual(catalog['files'][0]['workbook_evidence'][0]['panel_numbers'],[1,2]);self.assertEqual(catalog['episode_candidates']['E051']['status'],'VERSION_CONFLICT')
        with self.assertRaises(ValueError):sc.select(catalog,{},evidence='明确委托')
        sel={'E051':{'path':'剧本_v001.xlsx','version':'v001','source_evidence':'用户指定'}}
        result=sc.select(catalog,sel,evidence='用户消息')
        self.assertEqual(result['selected_sources']['E051']['path'],'剧本_v001.xlsx')
        (self.root/'剧本_v001.xlsx').write_bytes(b'changed')
        with self.assertRaises(ValueError):sc.select(catalog,sel,evidence='用户消息')
    def test_workbook_cache_is_content_bound_and_corruption_recovers(self):
        scripts=self.root/'scripts';scripts.mkdir();cache=self.root/'cache'
        workbook=Workbook();workbook.active.title='第51话';workbook.active.append(['格号']);workbook.active.append([1]);path=scripts/'book.xlsx';workbook.save(path)
        first=sc.discover(scripts,'B',['E051'],cache_root=cache);second=sc.discover(scripts,'B',['E051'],cache_root=cache)
        self.assertEqual(first['metrics']['workbook_parses'],1);self.assertEqual(second['metrics']['cache_reuses'],1)
        cachefile=next(cache.glob('*.json'));cachefile.write_text('{}')
        recovered=sc.discover(scripts,'B',['E051'],cache_root=cache)
        self.assertEqual(recovered['metrics']['workbook_parses'],1)
        self.assertEqual(sc.discover(scripts,'B',['E051'],cache_root=cache)['metrics']['cache_reuses'],1)
    def test_two_future_panels_not_current_or_duplicate(self):
        req={'requirement_id':'R','character_id':'C','costume_id':'S','source_basis':'脚本','panel_ids':['P001']}
        def obs(ep,p):return {'episode_id':ep,'panel_id':p,'character_id':'C','costume_id':'S','match':'CONFIRMED','visible':True,'source_sha256':'hash','evidence':'source'}
        catalog=make_catalog(self.root);source=self.root/'future.txt';digest=catalog['selected_sources']['E002']['sha256']
        a=obs('E002','P001');a['source_sha256']=digest;second=obs('E002','P002');second['source_sha256']=digest
        rows=[obs('E001','P001'),a,a]
        r=cr.plan('B',['E001'],[req],rows,coverage='UNKNOWN',source_catalog=catalog)['requirements'][0]
        self.assertEqual(r['future_count'],1);self.assertFalse(r['publication_required'])
        r=cr.plan('B',['E001'],[req],rows+[second],coverage='UNKNOWN',source_catalog=catalog)['requirements'][0]
        self.assertEqual(r['future_count'],2);self.assertTrue(r['publication_required'])
    def test_plan_routes_asset_and_rejects_stale_future_source(self):
        import asset_tasks
        catalog=make_catalog(self.root);source=self.root/'future.txt';digest=catalog['selected_sources']['E002']['sha256']
        requirement={'requirement_id':'R','character_id':'C','costume_id':'S','source_basis':'script','panel_ids':['P001']}
        def obs(p):return {'episode_id':'E002','panel_id':p,'character_id':'C','costume_id':'S','match':'CONFIRMED','visible':True,'source_sha256':digest,'evidence':'script'}
        plan=cr.plan('B',['E001'],[requirement],[obs('P001'),obs('P002')],coverage='UNKNOWN',source_catalog=catalog)
        row={'asset_id':'A','requirement_id':'R','character_id':'C','costume_id':'S','episode_id':'E001','panel_ids':['P001'],'visible_occurrences':1,'source_basis':'script'}
        result=asset_tasks.audit(self.root,[row],reuse_plan=plan)
        self.assertEqual(result['asset_tasks'][0]['resolution'],'canonical_candidate')
        source.write_text('changed')
        stale=asset_tasks.audit(self.root,[row],reuse_plan=plan)['asset_tasks'][0]
        self.assertEqual(stale['reuse_decision'],'REUSE_HOLD');self.assertEqual(stale['resolution'],'temporary_reference')
    def test_publication_is_replayable_and_prevents_overwrite(self):
        source=self.root/'image.png';source.write_bytes(b'actual image bytes');digest=hashlib.sha256(source.read_bytes()).hexdigest()
        def obs(p):return {'episode_id':'E002','panel_id':p,'character_id':'C','costume_id':'S','match':'CONFIRMED','visible':True,'source_sha256':'hash','evidence':'script'}
        record={'policy':ac.POLICY,'book_id':'B','asset_id':'A','character_id':'C','costume_id':'S','source_basis':'script','production_episode_ids':['E001'],
          'authorization':{'source_kind':'user_message','source_locator':'message','quote':'scope','book_id':'B','asset_ids':['A'],'episode_ids':['E001'],'operations':['publish']},
          'format_review':reviewed(digest),'review':{'status':'PASS','reviewer':'human','evidence':'observed','asset_id':'A','image_sha256':digest},'sha256':digest,'relative_path':'02_人物状态/asset.png','future_occurrences':[obs('P001'),obs('P002')]}
        plan=make_plan(self.root,record)
        self.assertEqual(ac.publish(self.root,record,source,reuse_plan=plan)['status'],'PUBLISHED')
        self.assertEqual(ac.publish(self.root,record,source,reuse_plan=plan)['status'],'ALREADY_PUBLISHED')
        batch=ac.publish_batch(self.root,[{}, {'record':record,'source':str(source),'reuse_plan':plan}])
        self.assertEqual([x['status'] for x in batch['results']],['ASSET_HOLD','ALREADY_PUBLISHED'])
        modified={**record,'costume_id':'changed'}
        with self.assertRaises(ValueError):ac.publish(self.root,modified,source,reuse_plan=plan)
        self.assertEqual((self.root/record['relative_path']).read_bytes(),source.read_bytes())
    def test_boundary_checks_missing_files_and_no_assumed_selection(self):
        img=self.root/'image.png';img.write_bytes(b'img');digest=hashlib.sha256(b'img').hexdigest()
        r={'policy':hc.POLICY,'book_id':'B','next_episode_id':'E002','source_package_id':'K','characters':[{'character_id':'C','verification_status':'CONFIRMED','costume_id':'S','appearance_state_id':'AS','identity_basis':'evidence','last_confirmed_source_panel':'E001-P002','applicability':'unknown','reference':{'path':'image.png','sha256':digest}}]}
        self.assertEqual(hc.validate(r,self.root)['status'],'BOUNDARY_EVIDENCE_VALID')
        img.unlink()
        with self.assertRaises(ValueError):hc.validate(r,self.root)
        self.assertEqual(hc.resolve(self.root,'B','E002')['status'],'NO_BOUNDARY')
if __name__=='__main__':unittest.main()

class TransitionTests(unittest.TestCase):
    def test_change_starts_on_selected_panel_and_conflict_is_local(self):
        boundary={'policy':hc.POLICY,'book_id':'B','next_episode_id':'E002','characters':[
          {'character_id':'C','verification_status':'CONFIRMED','costume_id':'S1','appearance_state_id':'AS1'},
          {'character_id':'D','verification_status':'CONFIRMED','costume_id':'T1','appearance_state_id':'AT1'}]}
        rows=[{'panel_id':'P001','character_id':'C','decision':'INHERIT','source_evidence':'script'},
              {'panel_id':'P002','character_id':'C','decision':'CHANGE','source_evidence':'script','costume_id':'S2','appearance_state_id':'AS2','reference':{'path':'x','sha256':'y'}},
              {'panel_id':'P003','character_id':'C','decision':'INHERIT','source_evidence':'script'},
              {'panel_id':'P003','character_id':'D','decision':'CONFLICT','source_evidence':'ambiguous'}]
        result=hc.reconcile(boundary,'E002',['P001','P002','P003'],rows)['bindings']
        self.assertEqual([r['state'].get('costume_id') for r in result],['S1','S2','S2','T1'])
        self.assertEqual(result[-1]['state']['verification_status'],'UNRESOLVED')

class ScopeAndRecoveryTests(unittest.TestCase):
    def test_script_folder_start_keeps_formal_scope(self):
        import comic_start
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);scripts=root/'scripts';scripts.mkdir();assets=root/'assets';assets.mkdir()
            wb=Workbook();ws=wb.active;ws.title='第51话';ws.append(['格号']);ws.append([1]);wb.create_sheet('第52话');wb.save(scripts/'book.xlsx')
            with patch.dict('os.environ',{'CODEX_HOME':str(root/'codex')}):
                result=comic_start.prepare(root,'B',['E051'],script=scripts,assets=assets,runtime_limit_seconds=None)
            run=Path(result['run_root']);catalog=json.loads((run/'脚本来源索引.json').read_text())
            self.assertEqual(catalog['production_episode_ids'],['E051']);self.assertTrue((run/'E051').is_dir());self.assertFalse((run/'E052').exists())
            self.assertEqual(result['incoming_continuity']['status'],'NO_BOUNDARY')
    def test_concurrent_same_asset_publishes_once(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.png';source.write_bytes(b'img');digest=hashlib.sha256(b'img').hexdigest();dest=root/'assets';dest.mkdir()
            def obs(p):return {'episode_id':'E002','panel_id':p,'character_id':'C','costume_id':'S','match':'CONFIRMED','visible':True,'source_sha256':'source','evidence':'script'}
            record={'policy':ac.POLICY,'book_id':'B','asset_id':'A','character_id':'C','costume_id':'S','source_basis':'script','production_episode_ids':['E001'],
                    'authorization':{'source_kind':'user_message','source_locator':'message','quote':'scope','book_id':'B','asset_ids':['A'],'episode_ids':['E001'],'operations':['publish']},
                    'format_review':reviewed(digest),'review':{'status':'PASS','reviewer':'agent','evidence':'seen','asset_id':'A','image_sha256':digest},'sha256':digest,'relative_path':'states/A.png','future_occurrences':[obs('P001'),obs('P002')]}
            plan=make_plan(root,record)
            with ThreadPoolExecutor(max_workers=2) as executor:
                results=list(executor.map(lambda _:ac.publish(dest,record,source,reuse_plan=plan),range(2)))
            self.assertEqual({x['status'] for x in results},{'PUBLISHED','ALREADY_PUBLISHED'})
            self.assertEqual(len(json.loads((dest/'07_元数据/衣装增量索引.json').read_text())['entries']),1)
    def test_saved_asset_replays_registration(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.png';source.write_bytes(b'img');h=hashlib.sha256(b'img').hexdigest();dest=root/'assets';dest.mkdir()
            def row(p):return {'episode_id':'E002','panel_id':p,'character_id':'C','costume_id':'S','match':'CONFIRMED','visible':True,'source_sha256':'source','evidence':'script'}
            record={'policy':ac.POLICY,'book_id':'B','asset_id':'A','character_id':'C','costume_id':'S','source_basis':'script','production_episode_ids':['E001'],
                    'authorization':{'source_kind':'user_message','source_locator':'message','quote':'scope','book_id':'B','asset_ids':['A'],'episode_ids':['E001'],'operations':['publish']},
                    'format_review':reviewed(h),'review':{'status':'PASS','reviewer':'agent','evidence':'seen','asset_id':'A','image_sha256':h},'sha256':h,'relative_path':'states/A.png','future_occurrences':[row('P001'),row('P002')]}
            from unittest.mock import patch
            plan=make_plan(root,record)
            original=ac.atomic_json
            def interrupt_index(path,value):
                if Path(path).name=='衣装增量索引.json':raise OSError('interrupted')
                return original(path,value)
            with patch.object(ac,'atomic_json',side_effect=interrupt_index):
                with self.assertRaises(OSError):ac.publish(dest,record,source,reuse_plan=plan)
            self.assertEqual((dest/'states/A.png').read_bytes(),b'img')
            self.assertEqual(ac.publish(dest,record,source,reuse_plan=plan)['status'],'PUBLISHED')
