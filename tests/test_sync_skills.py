"""Updater behavior in disposable Codex homes; never touches a real installation."""
import importlib.util,tempfile,unittest,json,copy,hashlib
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
    def test_user_additions_survive_update_without_becoming_install_conflicts(self):
        sync.install(self.home);base=self.home/'skills/vertical-comic-preproduction/assets/rule-memory';user=base/'用户增补'
        rule=copy.deepcopy(json.loads((base/'内置规则/记忆索引.json').read_text())['rules'][0]);body=user/'规则/USR-CUSTOM.md';body.parent.mkdir();body.write_text('# Universal user method')
        rule.update(id='USR-CUSTOM',version='1',file={'path':'规则/USR-CUSTOM.md','sha256':hashlib.sha256(body.read_bytes()).hexdigest()})
        index=json.loads((user/'记忆索引.json').read_text());index['rules']=[rule];(user/'记忆索引.json').write_text(json.dumps(index,ensure_ascii=False))
        self.assertEqual(sync.install(self.home,check=True)['status'],'UP_TO_DATE')
        (self.home/'skills/vertical-comic-preproduction/SKILL.md').write_text('LOCAL EDIT triggers explicit replacement')
        sync.install(self.home,replace_existing=True)
        self.assertEqual(body.read_text(),'# Universal user method');self.assertEqual(json.loads((user/'记忆索引.json').read_text())['rules'][0]['id'],'USR-CUSTOM')

    def test_unmanaged_existing_skill_requires_explicit_replacement(self):
        file=self.home/'skills/vertical-comic-preproduction/SKILL.md';file.parent.mkdir(parents=True);file.write_text('OLD')
        with self.assertRaises(ValueError):sync.install(self.home)
        self.assertEqual(file.read_text(),'OLD')
    def test_zip_install_does_not_require_git_or_github(self):
        with patch.object(sync.shutil,'which',return_value=None):result=sync.install(self.home)
        self.assertEqual(result['status'],'INSTALLED')

    def test_path_traversal_is_rejected(self):
        for name in ('../outside','/outside','skills/../../outside'):
            with self.assertRaises(ValueError):sync.safe(self.home,name)
if __name__=='__main__':unittest.main()
