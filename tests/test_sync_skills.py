"""Updater behavior in disposable Codex homes; never touches a real installation."""
import importlib.util,tempfile,unittest,json,copy,hashlib,subprocess,sys,shutil,os
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('sync',ROOT/'tools/sync_skills.py');sync=importlib.util.module_from_spec(spec);spec.loader.exec_module(sync)
class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.home=Path(self.tmp.name)/'codex'
    def test_first_install_and_idempotent_check(self):
        self.assertEqual(sync.install(self.home,check=True)['status'],'UPDATE_AVAILABLE');self.assertFalse(self.home.exists())
        result=sync.install(self.home);self.assertEqual(result['status'],'INSTALLED');self.assertTrue(Path(result['memory_root']).is_dir())
        self.assertEqual(sync.install(self.home,check=True)['status'],'UP_TO_DATE')
        self.assertEqual(sync.install(self.home)['status'],'UP_TO_DATE')
    def test_local_edits_preserved_unless_explicit_replace_and_backed_up(self):
        sync.install(self.home);file=self.home/'skills/vertical-comic-preproduction/SKILL.md';file.write_text('LOCAL EDIT', encoding='utf-8', newline='\n')
        with self.assertRaises(ValueError):sync.install(self.home)
        self.assertEqual(file.read_text(encoding='utf-8-sig'),'LOCAL EDIT')
        result=sync.install(self.home,replace_existing=True)
        self.assertEqual((Path(result['backup'])/'skills/vertical-comic-preproduction/SKILL.md').read_text(encoding='utf-8-sig'),'LOCAL EDIT')
        self.assertNotEqual(file.read_text(encoding='utf-8-sig'),'LOCAL EDIT')
    def test_untracked_custom_rule_is_preserved(self):
        sync.install(self.home);file=self.home/'skill-bundles/vertical-comic-skills/memory/custom.md';file.write_text('CUSTOM', encoding='utf-8', newline='\n')
        self.assertEqual(sync.install(self.home,check=True)['status'],'LOCAL_CHANGES')
        with self.assertRaises(ValueError):sync.install(self.home)
        self.assertEqual(file.read_text(encoding='utf-8-sig'),'CUSTOM')
    def test_user_additions_survive_update_without_becoming_install_conflicts(self):
        sync.install(self.home);base=self.home/'skills/vertical-comic-preproduction/assets/rule-memory';user=base/'用户增补'
        rule=copy.deepcopy(json.loads((base/'内置规则/记忆索引.json').read_text(encoding='utf-8-sig'))['rules'][0]);body=user/'规则/USR-CUSTOM.md';body.parent.mkdir();body.write_text('# Universal user method', encoding='utf-8', newline='\n')
        rule.update(id='USR-CUSTOM',version='1',file={'path':'规则/USR-CUSTOM.md','sha256':hashlib.sha256(body.read_bytes()).hexdigest()})
        index=json.loads((user/'记忆索引.json').read_text(encoding='utf-8-sig'));index['rules']=[rule];(user/'记忆索引.json').write_text(json.dumps(index,ensure_ascii=False), encoding='utf-8', newline='\n')
        self.assertEqual(sync.install(self.home,check=True)['status'],'UP_TO_DATE')
        (self.home/'skills/vertical-comic-preproduction/SKILL.md').write_text('LOCAL EDIT triggers explicit replacement', encoding='utf-8', newline='\n')
        sync.install(self.home,replace_existing=True)
        self.assertEqual(body.read_text(encoding='utf-8-sig'),'# Universal user method');self.assertEqual(json.loads((user/'记忆索引.json').read_text(encoding='utf-8-sig'))['rules'][0]['id'],'USR-CUSTOM')

    def test_unmanaged_existing_skill_requires_explicit_replacement(self):
        file=self.home/'skills/vertical-comic-preproduction/SKILL.md';file.parent.mkdir(parents=True);file.write_text('OLD', encoding='utf-8', newline='\n')
        with self.assertRaises(ValueError):sync.install(self.home)
        self.assertEqual(file.read_text(encoding='utf-8-sig'),'OLD')
    def test_zip_install_does_not_require_git_or_github(self):
        with patch.object(sync.shutil,'which',return_value=None):result=sync.install(self.home)
        self.assertEqual(result['status'],'INSTALLED')

    def test_fresh_install_can_auto_configure_and_reuse_book_profile(self):
        sync.install(self.home)
        project=Path(self.tmp.name)/'project';project.mkdir();script=project/'source.xlsx';script.write_bytes(b'SYNTHETIC configuration-only fixture, not production input');assets=project/'assets';assets.mkdir()
        start=self.home/'skills/vertical-comic-preproduction/scripts/comic_start.py'
        command=[sys.executable, '-X', 'utf8','-B',str(start),'prepare','--project',str(project),'--book','SYNTHETIC','--episodes','E001-E002','--script',str(script),'--assets',str(assets)]
        process=subprocess.run(command,capture_output=True,text=True, encoding='utf-8');self.assertEqual(process.returncode,0,process.stdout+process.stderr)
        first=json.loads(process.stdout);self.assertEqual(first['image_calls'],0);self.assertTrue(Path(first['profile']).is_file())
        state=json.loads((Path(first['run_root'])/'E001/00_输入审计/生产流程.json').read_text(encoding='utf-8-sig'));self.assertEqual(state['gates'],{})
        second=subprocess.run([sys.executable, '-X', 'utf8','-B',str(start),'prepare','--project',str(project),'--book','SYNTHETIC','--episodes','E003'],capture_output=True,text=True, encoding='utf-8')
        self.assertEqual(second.returncode,0,second.stdout+second.stderr);reused=json.loads(second.stdout);self.assertEqual(reused['profile'],first['profile']);self.assertEqual(reused['episode_ids'],['E003'])

    def test_path_traversal_is_rejected(self):
        for name in ('../outside','/outside','skills/../../outside','C:drive','skills/NUL.json','skills/name.'):
            with self.assertRaises(ValueError):sync.safe(self.home,name)

    def test_runtime_failure_prevents_activation(self):
        real_run=sync.subprocess.run
        def fail_runtime(command,**kwargs):
            if any(str(x).endswith('runtime_environment.py') for x in command):
                return subprocess.CompletedProcess(command,1,'{"status":"ENVIRONMENT_HOLD"}','')
            return real_run(command,**kwargs)
        with patch.object(sync.subprocess,'run',side_effect=fail_runtime):
            with self.assertRaisesRegex(ValueError,'before activation'):sync.install(self.home)
        self.assertFalse((self.home/'skills').exists())

    def test_partial_upgrade_restores_all_original_files(self):
        sync.install(self.home)
        target=self.home/'skills/vertical-comic-preproduction/SKILL.md'
        target.write_bytes(b'LOCAL revision')
        before={p.relative_to(self.home).as_posix():p.read_bytes() for p in (self.home/'skills').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        marker=self.home/'skill-bundles/vertical-comic-skills/installed.json'
        old_marker=marker.read_bytes();real_replace=sync.os.replace
        def fail_activation(source,destination):
            if '.stage-' in str(source) and str(destination).endswith('vertical-comic-shot-design'):
                raise PermissionError('synthetic Windows sharing violation')
            return real_replace(source,destination)
        with patch.object(sync.os,'replace',side_effect=fail_activation):
            with self.assertRaises(PermissionError):sync.install(self.home,replace_existing=True)
        after={p.relative_to(self.home).as_posix():p.read_bytes() for p in (self.home/'skills').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        self.assertEqual(before,after);self.assertEqual(marker.read_bytes(),old_marker)

    @unittest.skipUnless(shutil.which('git'),'Git-specific checkout test; ZIP installation tested separately')
    def test_autocrlf_checkout_preserves_published_bytes(self):
        source=Path(self.tmp.name)/'git-source';source.mkdir()
        sample=ROOT/'skills/vertical-comic-preproduction/SKILL.md'
        shutil.copyfile(ROOT/'.gitattributes',source/'.gitattributes')
        shutil.copyfile(sample,source/'SKILL.md')
        def git(*args):
            p=subprocess.run(['git',*map(str,args)],capture_output=True)
            self.assertEqual(p.returncode,0,p.stderr)
        git('init',source)
        git('-C',source,'-c','core.autocrlf=false','add','.')
        git('-C',source,'-c','user.name=Synthetic test','-c','user.email=test@example.invalid','-c','commit.gpgsign=false','commit','-m','synthetic fixture')
        clone=Path(self.tmp.name)/'windows-checkout'
        git('clone','--no-hardlinks','-c','core.autocrlf=true',source,clone)
        self.assertEqual((clone/'SKILL.md').read_bytes(),sample.read_bytes())

    def copy_distribution(self,name='ZIP 解压目录'):
        target=Path(self.tmp.name)/name
        shutil.copytree(ROOT,target,ignore=shutil.ignore_patterns('.git','.venv','__pycache__','*.pyc'))
        return target

    def change_release(self,source):
        name='skills/vertical-comic-preproduction/SKILL.md'
        file=source/name;file.write_text(file.read_text(encoding='utf-8')+'\n<!-- SYNTHETIC upgrade fixture -->\n',encoding='utf-8',newline='\n')
        data=json.loads((source/'bundle.json').read_text(encoding='utf-8'))
        row=next(row for row in data['files'] if row['path']==name)
        row.update(sha256=sync.digest(file),bytes=file.stat().st_size)
        (source/'bundle.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        (source/'VERSION').write_text('synthetic-upgrade\n',encoding='utf-8',newline='\n')
        return file

    def test_zip_install_and_manual_upgrade_without_git(self):
        source=self.copy_distribution();env=os.environ.copy();env['PATH']=str(Path(self.tmp.name)/'no-git')
        command=[sys.executable,'-X','utf8','-B',str(source/'tools/sync_skills.py'),'--codex-home',str(self.home)]
        first=subprocess.run(command,env=env,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(first.returncode,0,first.stderr)
        marker=self.home/'skill-bundles/vertical-comic-skills/installed.json'
        self.assertIsNone(json.loads(marker.read_text(encoding='utf-8'))['commit'])
        additions=self.home/sync.USER_ADDITIONS/'custom.md';additions.write_text('USER ADDITION',encoding='utf-8',newline='\n')
        updated=self.change_release(source)
        second=subprocess.run(command,env=env,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(second.returncode,0,second.stderr)
        result=json.loads(second.stdout)
        self.assertEqual(additions.read_text(encoding='utf-8'),'USER ADDITION')
        saved=Path(result['backup'])/'skills/vertical-comic-preproduction/SKILL.md'
        self.assertNotEqual(sync.digest(saved),sync.digest(updated))
        self.assertEqual(sync.digest(self.home/'skills/vertical-comic-preproduction/SKILL.md'),sync.digest(updated))
        record=json.loads(marker.read_text(encoding='utf-8'))
        self.assertEqual(record['version'],'synthetic-upgrade')
        self.assertEqual(record['bundle_sha256'],sync.digest(source/'bundle.json'))

    def test_zip_update_explains_manual_upgrade_without_running_git(self):
        source=self.copy_distribution()
        with patch.object(sync,'ROOT',source),patch.object(sync.subprocess,'run',side_effect=AssertionError('must not run Git')):
            with self.assertRaisesRegex(ValueError,'ZIP.*--check'):sync.update_repository()
        self.assertFalse(self.home.exists())

    def test_git_update_missing_git_explains_dependency(self):
        source=self.copy_distribution();(source/'.git').mkdir()
        with patch.object(sync,'ROOT',source),patch.object(sync.shutil,'which',return_value=None):
            with self.assertRaisesRegex(ValueError,'需要Git'):sync.update_repository()

    @unittest.skipUnless(shutil.which('git'),'Git is optional for ZIP users')
    def test_real_git_fast_forward_upgrade_and_dirty_checkout_protection(self):
        upstream=self.copy_distribution('upstream')
        def git(*args,cwd=upstream):
            return subprocess.run(['git',*args],cwd=cwd,capture_output=True,text=True,check=True,encoding='utf-8')
        git('init','-b','main');git('config','user.email','synthetic@example.invalid');git('config','user.name','Synthetic Test')
        git('add','.');git('commit','-m','Synthetic initial distribution')
        checkout=Path(self.tmp.name)/'checkout';git('clone',str(upstream),str(checkout))
        command=[sys.executable,'-X','utf8','-B',str(checkout/'tools/sync_skills.py'),'--codex-home',str(self.home)]
        first=subprocess.run(command,capture_output=True,text=True,encoding='utf-8');self.assertEqual(first.returncode,0,first.stderr)
        updated=self.change_release(upstream);git('add','.');git('commit','-m','Synthetic new distribution')
        upgraded=subprocess.run([*command,'--update'],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(upgraded.returncode,0,upgraded.stderr)
        self.assertEqual(sync.digest(self.home/'skills/vertical-comic-preproduction/SKILL.md'),sync.digest(updated))
        (checkout/'README.md').write_text('LOCAL CHANGE',encoding='utf-8',newline='\n')
        blocked=subprocess.run([*command,'--update'],capture_output=True,text=True,encoding='utf-8')
        self.assertNotEqual(blocked.returncode,0);self.assertIn('local changes',blocked.stderr)
        self.assertEqual((checkout/'README.md').read_text(encoding='utf-8'),'LOCAL CHANGE')

    def test_custom_installation_keeps_runtime_cache_and_contribution_state_inside_home(self):
        sync.install(self.home)
        scripts=self.home/'skills/vertical-comic-preproduction/scripts'
        env=os.environ.copy();env.pop('CODEX_HOME',None)
        code='import sys,json;sys.path.insert(0,sys.argv[1]);import builtin_memory as b,rule_contributions as c;print(json.dumps([b.resolve()["root"],str(c.STATE)]))'
        process=subprocess.run([sys.executable,'-X','utf8','-B','-c',code,str(scripts)],env=env,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(process.returncode,0,process.stderr)
        cache,state=map(Path,json.loads(process.stdout))
        self.assertTrue(cache.is_relative_to(self.home.resolve()/'comic/cache/rules'))
        self.assertEqual(state,self.home.resolve()/'comic/rule-contributions')
if __name__=='__main__':unittest.main()
