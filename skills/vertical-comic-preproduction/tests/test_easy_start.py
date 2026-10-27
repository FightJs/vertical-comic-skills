"""First use, generic user rules, no-account export and isolated GitHub submission."""
import copy,json,shutil,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import builtin_memory as b
import rule_contributions as c
import comic_start as start
import test_rule_memory as fixture
from usage_config import read_config,memory_source

class EasyStartTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.library=self.root/'library';shutil.copytree(b.ROOT,self.library);self.state=self.root/'state'
    def put(self,name,value):
        p=self.root/name;p.write_text(json.dumps(value,ensure_ascii=False), encoding='utf-8', newline='\n');return p
    def rule(self):
        source=fixture.library(self.root/'synthetic');rule=json.loads((Path(source['root'])/'记忆索引.json').read_text(encoding='utf-8-sig'))['rules'][0]
        rule.update(id='USR-SUPPORT',version='1',load_policy='on_match');body=self.root/'generic.md';body.write_text('# 通用承托判据\n明确身体承托物与接触点。', encoding='utf-8', newline='\n')
        return self.put('rule.json',rule),body,self.put('review.json',{'source_kind':'user_message','source_locator':'synthetic://test-only','authorization':'SYNTHETIC maintenance authorization','portable':True,'contains_story_facts':False})
    def test_builtins_resolve_without_third_path_and_reuse_content_cache(self):
        a=b.resolve(library_root=self.library,cache_root=self.root/'cache');other=b.resolve(library_root=self.library,cache_root=self.root/'cache')
        self.assertEqual(a,other);self.assertEqual(len(b.read(Path(a['root'])/'记忆索引.json')['rules']),11)
        self.assertTrue((Path(a['root'])/'内置规则/规则记忆输入与增添规范.md').is_file())
    def test_custom_codex_home_controls_default_cache(self):
        home=self.root/'custom-home'
        with patch.dict(b.os.environ,{'CODEX_HOME':str(home)}):
            result=b.resolve(library_root=self.library)
        self.assertTrue(Path(result['root']).is_relative_to(home.resolve()/'comic/cache/rules'))
    def test_explicit_cache_takes_precedence_over_codex_home(self):
        cache=self.root/'explicit-cache'
        with patch.dict(b.os.environ,{'CODEX_HOME':str(self.root/'other-home')}):
            result=b.resolve(library_root=self.library,cache_root=cache)
        self.assertTrue(Path(result['root']).is_relative_to(cache.resolve()))
    def test_prepared_config_uses_frozen_rules_without_resolving_live_cache(self):
        script=self.root/'source.xlsx';script.write_bytes(b'SYNTHETIC');assets=self.root/'assets';assets.mkdir()
        with patch.dict(b.os.environ,{'CODEX_HOME':str(self.root/'custom-home')}):
            result=start.prepare(self.root,'SYNTHETIC',['E001'],runtime_limit_seconds=None,script=script,assets=assets)
        config=b.read(result['config']);origin=config['inputs']['memory_root']
        state=b.read(Path(result['run_root'])/'E001/00_输入审计/生产流程.json')
        with patch.object(b,'resolve',side_effect=AssertionError('must not resolve live rules from a frozen run')):
            loaded=read_config(result['config'],frozen_memory_source=state['memory_source'])
        self.assertEqual(loaded['inputs']['memory_root'],origin)
    def test_user_update_does_not_need_account_and_export_excludes_authorization(self):
        args=self.rule()
        with patch.object(c,'api',side_effect=AssertionError('must not call GitHub')):
            result=c.update(*args,library_root=self.library,state_root=self.state)
        self.assertEqual(result['sync']['status'],'LOCAL_ONLY_EXPORT_AVAILABLE')
        src=b.resolve(library_root=self.library,cache_root=self.root/'merged');self.assertEqual(len(b.read(Path(src['root'])/'记忆索引.json')['rules']),12)
        event=result['outbox'];self.assertEqual(c.enqueue(self.library,self.state)['snapshot_id'],event['snapshot_id'])
        out=self.root/'contribution.zip';c.export(event['event_dir'],out)
        with zipfile.ZipFile(out) as z:
            self.assertFalse(any('review' in x or 'sync.json' in x for x in z.namelist()))
            self.assertFalse(any(b'synthetic://test-only' in z.read(n) for n in z.namelist()))
    def test_offline_zip_import_is_review_only_and_tamper_is_rejected(self):
        event=c.update(*self.rule(),library_root=self.library,state_root=self.state)['outbox'];archive=self.root/'offline.zip';c.export(event['event_dir'],archive)
        owner=self.root/'owner-state';result=c.import_package(archive,owner)
        self.assertFalse(result['activated']);self.assertEqual(result['status'],'IMPORTED_PENDING_REVIEW')
        self.assertEqual(c.import_package(archive,owner)['event_dir'],result['event_dir'])
        broken=self.root/'bad.zip'
        with zipfile.ZipFile(archive) as src,zipfile.ZipFile(broken,'w') as dst:
            for name in src.namelist():dst.writestr(name,b'changed' if name.endswith('USR-SUPPORT.md') else src.read(name))
        with self.assertRaises(ValueError):c.import_package(broken,self.root/'owner2')

    def test_story_specific_update_rejected_and_original_bytes_preserved(self):
        args=self.rule();before=b.digest(self.library/'用户增补/记忆索引.json');args[1].write_text('E026-P015 的傅家卧室具体位置', encoding='utf-8', newline='\n')
        with self.assertRaises(ValueError):c.update(*args,library_root=self.library,state_root=self.state)
        self.assertEqual(b.digest(self.library/'用户增补/记忆索引.json'),before)
    def test_duplicate_ids_cannot_override_builtin(self):
        index=b.read(self.library/'用户增补/记忆索引.json');rule=copy.deepcopy(b.read(self.library/'内置规则/记忆索引.json')['rules'][0]);rule['file']['path']='rule.md'
        shutil.copyfile(next((self.library/'内置规则/规则/生图').glob('MEM-001*')),self.library/'用户增补/rule.md');index['rules']=[rule];c.write(self.library/'用户增补/记忆索引.json',index)
        with self.assertRaisesRegex(ValueError,'冲突'):b.resolve(library_root=self.library,cache_root=self.root/'cache')
    def test_config_without_memory_path_uses_internal_rules(self):
        script=self.root/'source.xlsx';script.write_bytes(b'SYNTHETIC');assets=self.root/'assets';assets.mkdir()
        config=b.read(start.BASE/'assets/templates/默认使用配置.json');config.update(production={'book':'SYNTHETIC','episodes':['E001']},inputs={'script_path':str(script),'asset_root':str(assets)})
        loaded=read_config(self.put('config.json',config));self.assertTrue(memory_source(loaded)['index_sha256'])
    def test_explicit_broken_external_source_does_not_fall_back(self):
        script=self.root/'source.xlsx';script.write_bytes(b'SYNTHETIC');assets=self.root/'assets';assets.mkdir()
        config=b.read(start.BASE/'assets/templates/默认使用配置.json');config['memory'].pop('source');config.update(production={'book':'SYNTHETIC','episodes':['E001']},inputs={'script_path':str(script),'asset_root':str(assets),'memory_root':str(self.root/'missing')})
        with self.assertRaises(ValueError):read_config(self.put('config.json',config))
    def test_prepare_creates_one_book_profile_and_batch_snapshot_no_approval(self):
        script=self.root/'source.xlsx';script.write_bytes(b'SYNTHETIC');assets=self.root/'assets';assets.mkdir()
        result=start.prepare(self.root,'SYNTHETIC',['E001-E002'],runtime_limit_seconds=None,script=script,assets=assets)
        self.assertEqual(result['image_calls'],0);root=Path(result['run_root']);state=b.read(root/'E001/00_输入审计/生产流程.json')
        self.assertEqual(state['gates'],{});self.assertTrue(state['memory_source']['index_sha256']);self.assertTrue((Path(state['memory_source']['root'])/'内置规则/规则记忆输入与增添规范.md').is_file())
        self.assertEqual(state['image_review_profile'],'light_story_review_v1')
        self.assertEqual(state['speed_policy'],'bounded_stage_fallback_v1')
        self.assertEqual(state['task_context'],result['task_context'])
        self.assertEqual(b.read(root/'E002/00_输入审计/生产流程.json')['task_context'],state['task_context'])
        self.assertEqual(state['task_context']['origin'],'fresh')
        self.assertEqual(state['task_context']['imports'],[])
        self.assertEqual(state['task_context']['request_source']['source_kind'],'tool_invocation')
        newer=start.prepare(self.root,'SYNTHETIC',['E003'],runtime_limit_seconds=None);self.assertNotEqual(result['run_root'],newer['run_root'])
        self.assertEqual(b.read(newer['config'])['production']['episodes'],['E003'])
        self.assertNotEqual(newer['task_context']['task_id'],result['task_context']['task_id'])
        # Even the same book/episode is a separate task when explicitly prepared afresh.
        (self.root/'old-production-with-missing-ledger').mkdir()
        remake=start.prepare(self.root,'SYNTHETIC',['E001'],runtime_limit_seconds=None)
        self.assertNotEqual(remake['task_context']['task_id'],result['task_context']['task_id'])
        self.assertEqual(b.read(Path(remake['run_root'])/'E001/00_输入审计/生产流程.json')['panels'],[])

    def test_reinitializing_existing_episode_cannot_reset_task_identity(self):
        import subprocess
        script=self.root/'source.xlsx';script.write_bytes(b'SYNTHETIC');assets=self.root/'assets';assets.mkdir()
        result=start.prepare(self.root,'SYNTHETIC',['E001'],runtime_limit_seconds=None,script=script,assets=assets)
        root=Path(result['run_root']);state=root/'E001/00_输入审计/生产流程.json';before=state.read_bytes()
        cmd=[sys.executable, '-X', 'utf8','-B',str(root/'00_总控/运行版本/skills/vertical-comic-preproduction/scripts/init_preproduction.py'),
             '--book','SYNTHETIC','--episode','E001','--config',result['config'],
             '--runtime-snapshot',str(root/'00_总控/运行版本/manifest.json'),'--output',str(root/'E001')]
        proc=subprocess.run(cmd,capture_output=True,text=True, encoding='utf-8')
        self.assertEqual(proc.returncode,0);self.assertEqual(state.read_bytes(),before)
        self.assertEqual(json.loads(proc.stdout)['status'],'EXISTING_STATE_PRESERVED')
        from task_context import fresh
        foreign=self.put('foreign-task.json',fresh('SYNTHETIC',['E001']))
        changed=subprocess.run([*cmd,'--task-context',str(foreign)],capture_output=True,text=True, encoding='utf-8')
        self.assertNotEqual(changed.returncode,0);self.assertEqual(state.read_bytes(),before)
    def test_receive_missing_archive_does_not_create_run(self):
        with self.assertRaises(ValueError):start.receive(self.root/'package.zip',output=self.root/'receive')
        self.assertFalse((self.root/'receive').exists())
    def test_no_login_when_enabled_is_pending_and_does_not_lose_update(self):
        args=self.rule();c.configure(enabled=True,state_root=self.state,authorization='SYNTHETIC explicit opt-in')
        with patch.object(c,'api',side_effect=ValueError('no GitHub login')):result=c.update(*args,library_root=self.library,state_root=self.state)
        self.assertEqual(result['sync']['status'],'PENDING_SYNC');self.assertTrue((self.library/'用户增补/规则/USR-SUPPORT.md').exists())
    def test_github_push_only_targets_own_branch_and_immutable_contribution_path(self):
        event=c.update(*self.rule(),library_root=self.library,state_root=self.state)['outbox'];c.configure(enabled=True,state_root=self.state,authorization='SYNTHETIC opt-in');calls=[]
        def api(path,method='GET',data=None):
            calls.append((path,method,data))
            if path=='user':return {'login':'TestUser'}
            if path=='repos/FightJs/vertical-comic-skills':return {'permissions':{'push':True},'default_branch':'main'}
            if '/git/ref/heads/' in path:return {'object':{'sha':'old'}}
            if '/git/commits/' in path:return {'tree':{'sha':'tree'}}
            if '?recursive=1' in path:return {'tree':[]}
            return {'sha':'new'}
        with patch.object(c,'api',side_effect=api):result=c.publish(event['event_dir'],state_root=self.state)
        self.assertEqual(result['status'],'SYNCED')
        updates=[x for x in calls if x[1]=='PATCH'];self.assertEqual(len(updates),1);self.assertIn('users%2FTestUser%2Frule-memory',updates[0][0]);self.assertIs(updates[0][2]['force'],False)
        tree=next(x[2]['tree'] for x in calls if x[1]=='POST' and x[0].endswith('/git/trees'))
        self.assertTrue(all(x['path'].startswith('contributions/TestUser/rule-memory/'+event['snapshot_id']+'/') for x in tree))

if __name__=='__main__':unittest.main()
