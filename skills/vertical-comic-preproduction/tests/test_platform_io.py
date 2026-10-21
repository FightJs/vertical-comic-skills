"""Real independent processes and immutable cross-platform provenance; no image calls."""
from pathlib import Path, PureWindowsPath
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import platform_io as io


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='中文 portability ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def spawn(self, code, *args):
        code = 'import sys;sys.path.insert(0,sys.argv[1]);' + code
        child = subprocess.Popen([sys.executable, '-X', 'utf8', '-B', '-c', code,
                                  str(SCRIPTS), *map(str, args)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def cleanup():
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)
        self.addCleanup(cleanup)
        return child

    def test_two_processes_cannot_lose_updates(self):
        state = self.root / '生产 状态.json'
        io.atomic_json(state, {'n': 0})
        code = """from pathlib import Path
import json
from platform_io import file_lock,atomic_json
p=Path(sys.argv[2])
for _ in range(30):
    with file_lock(p.with_suffix('.lock')):
        data=json.loads(p.read_text(encoding='utf-8'))
        data['n']+=1
        atomic_json(p,data)
"""
        children = [self.spawn(code, state) for _ in range(2)]
        for child in children:
            stdout, stderr = child.communicate(timeout=30)
            self.assertEqual(child.returncode, 0, stderr.decode('utf-8'))
        self.assertEqual(json.loads(state.read_bytes()), {'n': 60})

    def test_competing_dispatchers_cannot_reserve_same_attempt(self):
        import test_batch_runtime as fixtures
        from codex_reference_contract import digest
        case = fixtures.LeaseTests('test_local_reservation_never_writes_control_and_respects_slot')
        self.addCleanup(case.doCleanups)
        case.setUp()
        state, control = case.h.state_path, case.h.control_path
        code = """from pathlib import Path
import json
sys.path.insert(0,str(Path(sys.argv[1]).parent/'tests'))
from unittest.mock import patch
from test_batch_runtime import LeaseTests
from episode_dispatch_queue import reserve_ready
try:
    with patch('scoped_episode_workflow.evaluate_episode',side_effect=LeaseTests.gate):
        result=reserve_ready(sys.argv[2],sys.argv[3],sys.argv[4])
    print(json.dumps(result))
except ValueError as exc:
    print(json.dumps({'status':'STALE_STATE','reason':str(exc)}))
"""
        sha_state, sha_control = digest(state), digest(control)
        children = [self.spawn(code, state, sha_state, sha_control) for _ in range(2)]
        results = []
        for child in children:
            stdout, stderr = child.communicate(timeout=30)
            self.assertEqual(child.returncode, 0, stderr.decode('utf-8'))
            results.append(json.loads(stdout))
        self.assertEqual(sum(len(x.get('reserved', [])) for x in results), 1)
        self.assertEqual(sum(x['status'] == 'STALE_STATE' for x in results), 1)
        self.assertEqual(len(json.loads(state.read_bytes())['dispatch_ledger']), 1)
        self.assertEqual(digest(control), sha_control)

    def test_timeout_and_killed_owner_release_without_deleting_lock(self):
        lock = self.root / 'shared.lock'
        ready = self.root / 'ready'
        child = self.spawn("""from pathlib import Path
import time
from platform_io import file_lock
with file_lock(Path(sys.argv[2])):
    Path(sys.argv[3]).write_bytes(b'ready')
    time.sleep(30)
""", lock, ready)
        deadline = time.monotonic() + 10
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(ready.exists())
        with self.assertRaises(TimeoutError):
            with io.file_lock(lock, timeout=0.1):
                self.fail('second owner acquired active lock')
        child.kill()
        child.communicate(timeout=10)
        with io.file_lock(lock, timeout=1):
            self.assertTrue(lock.exists())

    def test_failed_replace_preserves_previous_json_and_cleans_temp(self):
        path = self.root / '状态.json'
        io.atomic_json(path, {'文本': '原文'})
        before = path.read_bytes()
        with patch.object(io, 'replace_file', side_effect=PermissionError('busy')):
            with self.assertRaises(PermissionError):
                io.atomic_json(path, {'文本': 'changed'})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [path])
        self.assertNotIn(b'\r\n', before)

    def test_portable_paths_reject_windows_aliases_on_every_os(self):
        for name in ('CON', 'NUL.txt', 'x/LPT1.json', 'x/COM¹.txt', 'x/a.', 'x/a ',
                     'x/a:b', 'x/a?b', 'C:/x', 'a\\b', '../x', '/x', 'a//b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                io.portable_relative(name)
        self.assertEqual(str(io.portable_relative('中文目录/参考 图.png')), '中文目录/参考 图.png')
        self.assertNotEqual(io.book_directory('a:b'), io.book_directory('a?b'))
        self.assertEqual(io.book_directory('中文书名'), '中文书名')

    def test_foreign_skill_paths_have_stable_identity(self):
        name = 'vertical-comic-preproduction'
        for value in (f'/source/skills/{name}/SKILL.md',
                      str(PureWindowsPath('D:/source/skills') / name / 'SKILL.md')):
            self.assertEqual(io.skill_entry_key(value), name)

    def test_non_utf8_parent_still_receives_utf8_json_and_custom_home(self):
        env = {**os.environ, 'PYTHONUTF8': '0', 'PYTHONIOENCODING': 'cp1252',
               'CODEX_HOME': str(self.root / '自定义 codex')}
        result = subprocess.run([sys.executable, '-X', 'utf8=0', '-B',
                                 str(SCRIPTS / 'runtime_environment.py'), '--probe-root', str(self.root)],
                                capture_output=True, env=env, timeout=30)
        data = json.loads(result.stdout.decode('utf-8'))
        self.assertEqual(result.returncode, 0, data)
        with patch.dict(os.environ, {'CODEX_HOME': str(self.root / '自定义 codex')}):
            self.assertEqual(io.codex_home(), (self.root / '自定义 codex').resolve())

    def test_semantic_cli_reports_chinese_hold_under_non_utf8_redirect(self):
        state = self.root / '中文 状态.json'
        io.atomic_json(state, {'input_semantics_policy': 'unknown'})
        before = state.read_bytes()
        env = {**os.environ, 'PYTHONUTF8': '0', 'PYTHONIOENCODING': 'cp1252'}
        result = subprocess.run([sys.executable, '-X', 'utf8=0', '-B',
                                 str(SCRIPTS / 'input_semantics.py'), '--state', str(state)],
                                capture_output=True, env=env, timeout=30)
        self.assertEqual(result.returncode, 1, result.stderr.decode('utf-8', errors='replace'))
        data = json.loads(result.stdout.decode('utf-8'))
        self.assertEqual(data['status'], 'HOLD')
        self.assertIn('未知最终输入审查策略', data['errors'][0])
        self.assertNotIn(b'UnicodeEncodeError', result.stderr)
        self.assertEqual(state.read_bytes(), before)

    def test_valid_xlsx_snapshot_preserves_text_formula_and_releases_file(self):
        from openpyxl import Workbook
        from source_workbook import snapshot
        path = self.root / '中文 源稿.xlsx'
        book = Workbook()
        sheet = book.active
        sheet.title = '第001话'
        sheet.append(['格号', '对白', '公式'])
        sheet.append(['E001-P001', '“原文，不能改！”\n第二行', '=1+2'])
        book.save(path)
        book.close()
        before = path.read_bytes()
        result = snapshot(path)
        self.assertEqual(result['sheets'][0]['rows'][1][1]['value'], '“原文，不能改！”\n第二行')
        self.assertEqual(result['sheets'][0]['rows'][1][2]['value'], '=1+2')
        self.assertEqual(result['source_sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(path.read_bytes(), before)
        path.rename(self.root / '可移动.xlsx')

    def test_snapshot_paths_are_posix_and_survive_relocation(self):
        from runtime_snapshot import create, verify, SKILLS
        import shutil
        installed = self.root / 'source'
        for name in SKILLS:
            folder = installed / name
            folder.mkdir(parents=True)
            (folder / 'SKILL.md').write_bytes(b'frozen\n')
        nested = installed / SKILLS[0] / 'scripts' / 'nested'
        nested.mkdir(parents=True)
        (nested / 'sample.py').write_bytes(b'pass\n')
        ref = create(self.root / 'frozen', skills_root=installed)
        original = Path(ref['path']).read_bytes()
        self.assertTrue(all('\\' not in row['path'] for row in json.loads(original)['files']))
        shutil.move(str(self.root / 'frozen'), str(self.root / '新位置'))
        relocated = {'path': str(self.root / '新位置/manifest.json'), 'sha256': ref['sha256']}
        verify(relocated)
        self.assertEqual(Path(relocated['path']).read_bytes(), original)

    def test_foreign_absolute_skill_paths_bind_without_rewriting_inputs(self):
        import test_direct_handoff as fixtures
        import handoff_delivery
        import handoff_zip
        case = fixtures.DirectHandoffTests('test_direct_bound_run_real_full_episode_gates_and_conditional_release')
        self.addCleanup(case.doCleanups)
        case.setUp()
        for row in case.state['toolchain']['skill_entries']:
            key = io.skill_entry_key(row['path'])
            row['path'] = str(PureWindowsPath('D:/foreign/skills') / key / 'SKILL.md')
        case.refresh_template()
        before = handoff_zip.files(case.package)
        result = handoff_delivery.bind(case.package, case.base / '跨机运行')
        self.assertEqual(result['status'], 'LOCAL_RUN_BOUND_NOT_IMAGE_AUTHORIZATION')
        self.assertEqual(handoff_zip.files(case.package), before)

    def test_missing_dependency_diagnosis_does_not_create_a_production_run(self):
        import runtime_environment
        real_import = runtime_environment.importlib.import_module
        def missing(name):
            if name == 'PIL':
                raise ImportError('synthetic missing dependency')
            return real_import(name)
        with patch.object(runtime_environment.importlib, 'import_module', side_effect=missing):
            result = runtime_environment.check(probe_root=self.root)
        self.assertEqual(result['status'], 'ENVIRONMENT_HOLD')
        self.assertIn('PIL', result['errors'][0])
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
