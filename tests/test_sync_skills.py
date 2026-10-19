"""Updater behavior in disposable Codex homes; never touches a real installation."""
import importlib.util,json,subprocess,sys,tempfile,unittest
from pathlib import Path
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
if __name__=='__main__':unittest.main()
