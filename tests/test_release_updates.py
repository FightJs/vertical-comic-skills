"""Isolated update/download/restore scenarios; fake HTTP, real ZIP and installer."""
from pathlib import Path
import copy,importlib.util,json,os,shutil,subprocess,sys,tempfile,unittest,zipfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import sync_skills as sync
import build_release
sys.path.insert(0,str(ROOT/'skills/vertical-comic-preproduction/scripts'))
import update_skills as u
import installation_state as state

class ReleaseUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.home=self.root/'自定义安装'
    def remote(self,version='v2099.01.01.1'):
        name='vertical-comic-skills-'+version+'.zip';base='https://github.com/FightJs/vertical-comic-skills/releases/download/'+version+'/'
        return {'tag_name':version,'draft':False,'prerelease':False,'html_url':base,'assets':[{'name':x,'browser_download_url':base+x} for x in (name,name+'.sha256')]}
    def distribution(self,version='v2099.01.01.1'):
        target=self.root/('source-'+str(len(list(self.root.glob('source-*')))))
        shutil.copytree(ROOT,target,ignore=shutil.ignore_patterns('.git','__pycache__','*.pyc','.venv','dist'))
        p=target/'skills/vertical-comic-preproduction/SKILL.md';p.write_bytes(p.read_bytes()+b'\n<!-- Synthetic update -->\n')
        data=json.loads((target/'bundle.json').read_text(encoding='utf-8'))
        row=next(x for x in data['files'] if x['path']==p.relative_to(target).as_posix());row.update(sha256=sync.digest(p),bytes=p.stat().st_size)
        (target/'bundle.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        (target/'VERSION').write_text(version+'\n',encoding='utf-8');return target
    def archive(self,source):
        out=self.root/(source.name+'.zip')
        with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for p in source.rglob('*'):
                if p.is_file():z.write(p,'distribution/'+p.relative_to(source).as_posix())
        return out
    def add_user_rule(self):
        base=self.home/'skills/vertical-comic-preproduction/assets/rule-memory';user=base/'用户增补';body=user/'规则/USR-NEW.md';body.parent.mkdir(exist_ok=True)
        body.write_text('# Portable user method added after upgrade',encoding='utf-8')
        rule=copy.deepcopy(state.read(base/'内置规则/记忆索引.json')['rules'][0]);rule.update(id='USR-NEW',version='1',file={'path':'规则/USR-NEW.md','sha256':sync.digest(body)})
        state.write(user/'记忆索引.json',{'policy':'triggered_rules_v1','loading_policy':'stage_baseline_loading_v1','rules':[rule]});return body
    def test_stable_check_does_not_install_or_require_account(self):
        with patch.object(u,'json_request',return_value=self.remote()):result=u.check(self.home)
        self.assertEqual(result['status'],'UPDATE_AVAILABLE');self.assertFalse(self.home.exists())
    def test_no_silent_downgrade_or_preview_fallback(self):
        sync.install(self.home)
        with patch.object(u,'json_request',return_value=self.remote('v2000.01.01.1')),patch.object(u,'download',side_effect=AssertionError('must not download')):
            self.assertEqual(u.update(self.home)['status'],'AHEAD_OF_STABLE')
        release=self.remote();release['assets']=[]
        with patch.object(u,'json_request',return_value=release):
            with self.assertRaisesRegex(ValueError,'尚无统一更新包'):u.check(self.home)
    def test_preview_uses_exact_commit(self):
        with patch.object(u,'json_request',return_value={'sha':'a'*40}) as call:
            result=u.remote_version('preview')
        self.assertTrue(call.call_args.args[0].endswith('/commits/main'));self.assertIn('a'*40,result['url'])
    def test_network_failure_preserves_install(self):
        sync.install(self.home);before=state.inventory(self.home)
        with patch.object(u,'json_request',side_effect=OSError('offline')):
            with self.assertRaises(OSError):u.update(self.home)
        self.assertEqual(before,state.inventory(self.home))
    def test_bad_download_checksum_never_installs(self):
        sync.install(self.home);before=state.inventory(self.home)
        def download(url,dest,limit=None):Path(dest).write_bytes(b'wrong checksum' if str(dest).endswith('.txt') else b'not a ZIP')
        with patch.object(u,'json_request',return_value=self.remote()),patch.object(u,'download',side_effect=download):
            with self.assertRaisesRegex(ValueError,'校验失败'):u.update(self.home)
        self.assertEqual(before,state.inventory(self.home))
    def test_real_offline_update_restore_keeps_new_user_rules_and_project(self):
        sync.install(self.home);original=(self.home/'skills/vertical-comic-preproduction/SKILL.md').read_bytes()
        project=self.root/'project/.comic/books/book.json';project.parent.mkdir(parents=True);project.write_bytes(b'unchanged book config and RV evidence')
        contribution=self.home/'comic/rule-contributions/sync.json';contribution.parent.mkdir(parents=True);contribution.write_bytes(b'local consent')
        archive=self.archive(self.distribution())
        with patch.object(u,'json_request',side_effect=AssertionError('offline')),patch.object(u,'download',side_effect=AssertionError('offline')):
            result=u.update(self.home,archive=archive)
        self.assertEqual(result['status'],'INSTALLED');self.assertEqual(state.read(self.home/'skill-bundles/vertical-comic-skills/installed.json')['version'],'v2099.01.01.1')
        body=self.add_user_rule();restored=state.restore(self.home)
        self.assertEqual(restored['status'],'RESTORED');self.assertEqual((self.home/'skills/vertical-comic-preproduction/SKILL.md').read_bytes(),original)
        self.assertIn('after upgrade',body.read_text(encoding='utf-8'));self.assertEqual(contribution.read_bytes(),b'local consent');self.assertEqual(project.read_bytes(),b'unchanged book config and RV evidence')
        self.assertTrue(state.available_backups(self.home))
    def test_actual_remote_flow_uses_real_installer_without_git_or_gh(self):
        archive=self.archive(self.distribution())
        def download(url,dest,limit=None):
            if url.endswith('.sha256'):Path(dest).write_text(sync.digest(archive)+'  '+self.remote()['assets'][0]['name']+'\n',encoding='utf-8')
            else:shutil.copyfile(archive,dest)
        env=os.environ.copy();env['PATH']=str(self.root/'no-git-or-gh')
        with patch.object(u,'json_request',return_value=self.remote()),patch.object(u,'download',side_effect=download),patch.dict(os.environ,env,clear=True):result=u.update(self.home)
        self.assertEqual(result['status'],'INSTALLED');marker=state.read(self.home/'skill-bundles/vertical-comic-skills/installed.json');self.assertIsNone(marker['commit']);self.assertEqual(marker['source']['channel'],'stable')
    def test_local_edits_stop_update_and_restore(self):
        sync.install(self.home);u.update(self.home,archive=self.archive(self.distribution()))
        file=self.home/'skills/vertical-comic-preproduction/SKILL.md';file.write_text('LOCAL CUSTOM CHANGE',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'LOCAL_CHANGES'):state.restore(self.home)
        self.assertEqual(file.read_text(encoding='utf-8'),'LOCAL CUSTOM CHANGE')
        with patch.object(u,'json_request',return_value=self.remote('v2099.01.01.2')):
            with self.assertRaisesRegex(ValueError,'LOCAL_CHANGES'):u.update(self.home)
    def test_incompatible_personal_rules_prevent_restore_without_loss(self):
        sync.install(self.home);u.update(self.home,archive=self.archive(self.distribution()))
        state.write(self.home/state.USER/'记忆索引.json',{'rules':[{'id':'broken'}]});before=state.inventory(self.home)
        with self.assertRaises(subprocess.CalledProcessError):state.restore(self.home)
        self.assertEqual(before,state.inventory(self.home))
    def test_competing_install_is_rejected_by_same_lock(self):
        with state.installation_lock(self.home):
            process=subprocess.run([sys.executable,'-X','utf8','-B',str(ROOT/'tools/sync_skills.py'),'--codex-home',str(self.home)],capture_output=True,text=True,encoding='utf-8')
        self.assertNotEqual(process.returncode,0);self.assertIn('LOCK_TIMEOUT',process.stderr);self.assertFalse((self.home/'skills').exists())
    def test_rule_maintenance_obeys_install_lock(self):
        sync.install(self.home)
        import rule_contributions
        with state.installation_lock(self.home):
            with self.assertRaises(TimeoutError):
                rule_contributions.update('not-read','not-read','not-read',library_root=(self.home/state.USER).parent)

    def test_corrupt_backup_stops_restore(self):
        sync.install(self.home);u.update(self.home,archive=self.archive(self.distribution()))
        backup=state.available_backups(self.home)[0];file=Path(backup['path'])/'skills/vertical-comic-preproduction/SKILL.md';file.write_bytes(b'corrupt')
        before=state.inventory(self.home)
        with self.assertRaisesRegex(ValueError,'完整性'):state.restore(self.home,backup['id'])
        self.assertEqual(before,state.inventory(self.home))
    def test_partial_restore_failure_rolls_back_current_install(self):
        sync.install(self.home);u.update(self.home,archive=self.archive(self.distribution()));before=state.inventory(self.home);real=state.os.replace
        def fail(src,dst):
            if '.restore-' in str(src) and str(dst).endswith('vertical-comic-shot-design'):raise PermissionError('synthetic sharing violation')
            return real(src,dst)
        with patch.object(state.os,'replace',side_effect=fail):
            with self.assertRaises(PermissionError):state.restore(self.home)
        self.assertEqual(before,state.inventory(self.home))
    def test_broken_payload_rejected_before_installer_executes(self):
        source=self.distribution();(source/'skills/vertical-comic-preproduction/SKILL.md').write_bytes(b'damaged')
        archive=self.archive(source)
        with patch.object(u.subprocess,'run',side_effect=AssertionError('must validate before executing installer')):
            with self.assertRaisesRegex(ValueError,'哈希失配'):u.update(self.home,archive=archive)
        self.assertFalse(self.home.exists())

    def test_release_version_mismatch_cannot_install(self):
        source=self.distribution();archive=self.archive(source)
        with tempfile.TemporaryDirectory() as work:
            with self.assertRaisesRegex(ValueError,'版本不一致'):
                u.apply_archive(self.home,archive,work,source={'version':'v2099.01.01.2'})
        self.assertFalse(self.home.exists())

    def test_archive_traversal_duplicate_and_symlink_rejected(self):
        for names in [('root/../escape',),('root/A','root/a')]:
            with self.subTest(names=names):
                archive=self.root/'malicious.zip'
                with zipfile.ZipFile(archive,'w') as z:
                    for n in names:z.writestr(n,'x')
                with self.assertRaises(ValueError):u.unpack(archive,self.root/'never-created')
                self.assertFalse((self.root/'never-created').exists())
    def test_custom_installed_entry_detects_home_without_environment(self):
        sync.install(self.home);script=self.home/'skills/vertical-comic-preproduction/scripts/update_skills.py'
        code='import sys;sys.path.insert(0,sys.argv[1]);import update_skills as u;print(u.home_path())'
        env=os.environ.copy();env.pop('CODEX_HOME',None)
        result=subprocess.run([sys.executable,'-X','utf8','-B','-c',code,str(script.parent)],capture_output=True,text=True,encoding='utf-8',env=env)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(Path(result.stdout.strip()),self.home.resolve())
    def test_release_builder_roundtrip_and_refuses_overwrite(self):
        result=build_release.build(self.root/'release');archive=Path(result['zip'])
        self.assertTrue(Path(result['checksum']).read_text(encoding='utf-8').startswith(sync.digest(archive)))
        unpacked=u.unpack(archive,self.root/'built-extracted');self.assertTrue((unpacked/'tools/sync_skills.py').is_file())
        with self.assertRaisesRegex(ValueError,'already exist'):build_release.build(self.root/'release')

if __name__=='__main__':unittest.main()
