"""Updater behavior in disposable Codex homes; never touches a real installation."""
import importlib.util,json,os,shutil,subprocess,sys,tempfile,unittest
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
        sync.install(self.home);file=self.home/'skills/vertical-comic-preproduction/SKILL.md';file.write_text('LOCAL EDIT')
        with self.assertRaises(ValueError):sync.install(self.home)
        self.assertEqual(file.read_text(),'LOCAL EDIT')
        result=sync.install(self.home,replace_existing=True)
        self.assertEqual((Path(result['backup'])/'skills/vertical-comic-preproduction/SKILL.md').read_text(),'LOCAL EDIT')
        self.assertNotEqual(file.read_text(),'LOCAL EDIT')
    def test_untracked_custom_rule_is_preserved(self):
        sync.install(self.home);file=self.home/'skill-bundles/vertical-comic-skills/memory/custom.md';file.write_text('CUSTOM')
        self.assertEqual(sync.install(self.home,check=True)['status'],'LOCAL_CHANGES')
        with self.assertRaises(ValueError):sync.install(self.home)
        self.assertEqual(file.read_text(),'CUSTOM')
    def test_unmanaged_existing_skill_requires_explicit_replacement(self):
        file=self.home/'skills/vertical-comic-preproduction/SKILL.md';file.parent.mkdir(parents=True);file.write_text('OLD')
        with self.assertRaises(ValueError):sync.install(self.home)
        self.assertEqual(file.read_text(),'OLD')
    def test_builtin_user_additions_survive_replacement_without_becoming_managed(self):
        sync.install(self.home)
        directory=self.home/sync.USER_ADDITIONS
        directory.mkdir(parents=True,exist_ok=True)
        (directory/'custom.md').write_text('USER RULE')
        (directory/'记忆索引.json').write_text('{"user":true}')
        self.assertEqual(sync.install(self.home,check=True)['status'],'UP_TO_DATE')
        core=self.home/'skills/vertical-comic-preproduction/SKILL.md';core.write_text('LOCAL EDIT')
        sync.install(self.home,replace_existing=True)
        self.assertEqual((directory/'custom.md').read_text(),'USER RULE')
        self.assertEqual((directory/'记忆索引.json').read_text(),'{"user":true}')

    def test_fresh_install_can_auto_configure_and_reuse_book_profile(self):
        sync.install(self.home)
        project=Path(self.tmp.name)/'project';project.mkdir();script=project/'source.xlsx';script.write_bytes(b'SYNTHETIC configuration-only fixture, not production input');assets=project/'assets';assets.mkdir()
        start=self.home/'skills/vertical-comic-preproduction/scripts/comic_start.py'
        command=[sys.executable,'-B',str(start),'prepare','--project',str(project),'--book','SYNTHETIC','--episodes','E001-E002','--script',str(script),'--assets',str(assets)]
        process=subprocess.run(command,capture_output=True,text=True);self.assertEqual(process.returncode,0,process.stdout+process.stderr)
        first=json.loads(process.stdout);self.assertEqual(first['image_calls'],0);self.assertTrue(Path(first['profile']).is_file())
        state=json.loads((Path(first['run_root'])/'E001/00_输入审计/生产流程.json').read_text());self.assertEqual(state['gates'],{})
        second=subprocess.run([sys.executable,'-B',str(start),'prepare','--project',str(project),'--book','SYNTHETIC','--episodes','E003'],capture_output=True,text=True)
        self.assertEqual(second.returncode,0,second.stdout+second.stderr);reused=json.loads(second.stdout);self.assertEqual(reused['profile'],first['profile']);self.assertEqual(reused['episode_ids'],['E003'])

    def test_path_traversal_is_rejected(self):
        for name in ('../outside','/outside','skills/../../outside'):
            with self.assertRaises(ValueError):sync.safe(self.home,name)

    def copy_distribution(self,name='ZIP 解压目录'):
        target=Path(self.tmp.name)/name
        shutil.copytree(ROOT,target,ignore=shutil.ignore_patterns('.git','.venv','__pycache__','*.pyc'))
        return target

    def change_release(self,source):
        name='skills/vertical-comic-preproduction/SKILL.md'
        file=source/name;file.write_text(file.read_text()+'\n<!-- SYNTHETIC upgrade fixture -->\n')
        data=json.loads((source/'bundle.json').read_text())
        row=next(row for row in data['files'] if row['path']==name)
        row.update(sha256=sync.digest(file),bytes=file.stat().st_size)
        (source/'bundle.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
        (source/'VERSION').write_text('synthetic-upgrade\n')
        return file

    def test_zip_install_and_manual_upgrade_without_git(self):
        source=self.copy_distribution();env=os.environ.copy();env['PATH']=str(Path(self.tmp.name)/'no-git')
        command=[sys.executable,'-B',str(source/'tools/sync_skills.py'),'--codex-home',str(self.home)]
        first=subprocess.run(command,env=env,capture_output=True,text=True)
        self.assertEqual(first.returncode,0,first.stderr)
        marker=self.home/'skill-bundles/vertical-comic-skills/installed.json'
        self.assertIsNone(json.loads(marker.read_text())['commit'])
        additions=self.home/sync.USER_ADDITIONS/'custom.md';additions.write_text('USER ADDITION')
        updated=self.change_release(source)
        second=subprocess.run(command,env=env,capture_output=True,text=True)
        self.assertEqual(second.returncode,0,second.stderr)
        result=json.loads(second.stdout)
        self.assertEqual(additions.read_text(),'USER ADDITION')
        saved=Path(result['backup'])/'skills/vertical-comic-preproduction/SKILL.md'
        self.assertNotEqual(sync.digest(saved),sync.digest(updated))
        self.assertEqual(sync.digest(self.home/'skills/vertical-comic-preproduction/SKILL.md'),sync.digest(updated))
        record=json.loads(marker.read_text())
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
            return subprocess.run(['git',*args],cwd=cwd,capture_output=True,text=True,check=True)
        git('init','-b','main');git('config','user.email','synthetic@example.invalid');git('config','user.name','Synthetic Test')
        git('add','.');git('commit','-m','Synthetic initial distribution')
        checkout=Path(self.tmp.name)/'checkout';git('clone',str(upstream),str(checkout))
        command=[sys.executable,'-B',str(checkout/'tools/sync_skills.py'),'--codex-home',str(self.home)]
        first=subprocess.run(command,capture_output=True,text=True);self.assertEqual(first.returncode,0,first.stderr)
        updated=self.change_release(upstream);git('add','.');git('commit','-m','Synthetic new distribution')
        upgraded=subprocess.run([*command,'--update'],capture_output=True,text=True)
        self.assertEqual(upgraded.returncode,0,upgraded.stderr)
        self.assertEqual(sync.digest(self.home/'skills/vertical-comic-preproduction/SKILL.md'),sync.digest(updated))
        (checkout/'README.md').write_text('LOCAL CHANGE')
        blocked=subprocess.run([*command,'--update'],capture_output=True,text=True)
        self.assertNotEqual(blocked.returncode,0);self.assertIn('local changes',blocked.stderr)
        self.assertEqual((checkout/'README.md').read_text(),'LOCAL CHANGE')

    def test_custom_installation_keeps_runtime_cache_and_contribution_state_inside_home(self):
        sync.install(self.home)
        scripts=self.home/'skills/vertical-comic-preproduction/scripts'
        env=os.environ.copy();env.pop('CODEX_HOME',None)
        code='import sys,json;sys.path.insert(0,sys.argv[1]);import builtin_memory as b,rule_contributions as c;print(json.dumps([b.resolve()["root"],str(c.STATE)]))'
        process=subprocess.run([sys.executable,'-B','-c',code,str(scripts)],env=env,capture_output=True,text=True)
        self.assertEqual(process.returncode,0,process.stderr)
        cache,state=map(Path,json.loads(process.stdout))
        self.assertTrue(cache.is_relative_to(self.home.resolve()/'comic/cache/rules'))
        self.assertEqual(state,self.home.resolve()/'comic/rule-contributions')
if __name__=='__main__':unittest.main()
