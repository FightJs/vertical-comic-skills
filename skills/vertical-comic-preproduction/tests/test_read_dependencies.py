"""Complete read observations and immutable content keys; isolated files only."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts'), str(Path(__file__).parent)]
from codex_reference_contract import (file_session, digest, checked_file, read_json, read_text,
    path_exists, is_file, is_dir, resolve_path, scan_directory, memoized_validation)
from audit_cache import derived
from platform_io import atomic_json


class ReadDependencyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_absent_file_invalidates_cached_success_and_poison_is_sticky(self):
        path = self.root / 'optional.json'
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session() as memo:
                check = lambda: {'legacy': not path_exists(path)}
                self.assertTrue(derived('optional', 'key', check)['legacy'])
                atomic_json(path, {})
                with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
                    derived('optional', 'key', check)
                path.unlink()  # Restoring absence cannot rescue the transaction.
                with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
                    derived('unrelated', 'key', lambda: True)
                self.assertEqual(memo['dependency_invalidations'], 1)

    def test_missing_checked_file_is_observed_even_if_the_caller_recovers(self):
        path = self.root / 'missing.json'
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                with self.assertRaisesRegex(ValueError, '文件缺失'):
                    checked_file(self.root, {'path': path.name, 'sha256': '0' * 64})
                atomic_json(path, {})

    def test_direct_missing_digest_can_be_a_negative_dependency(self):
        path = self.root / 'missing.json'
        def check():
            try:
                digest(path)
            except FileNotFoundError:
                return {'absent': True}
            return {'absent': False}
        with file_session() as memo:
            self.assertTrue(derived('optional', 'key', check)['absent'])
            self.assertTrue(derived('optional', 'key', check)['absent'])
            self.assertEqual(memo['audit_statistics']['optional']['runs'], 1)

    def test_file_type_change_invalidates_a_negative_predicate(self):
        path = self.root / 'node'
        path.mkdir()
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                self.assertFalse(is_file(path))
                self.assertTrue(is_dir(path))
                path.rmdir()
                path.write_text('now a file')

    def test_empty_scan_is_a_dependency_of_a_cached_validator(self):
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                compute = lambda: [] if not scan_directory(self.root, suffixes=('.py',)) else ['new tool']
                self.assertEqual(memoized_validation('tools', 'key', compute), [])
                (self.root / 'added.py').write_text('# new tool')
                memoized_validation('tools', 'key', compute)

    def test_missing_recursive_directory_is_observed(self):
        path = self.root / 'missing'
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                self.assertEqual(scan_directory(path, recursive=True), [])
                path.mkdir()

    def test_recursive_scan_detects_nested_membership_change(self):
        directory = self.root / 'nested'
        directory.mkdir()
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                scan_directory(self.root, recursive=True)
                (directory / 'added.json').write_text('{}')

    def test_scan_filters_are_part_of_the_dependency_and_ignore_bytecode(self):
        (self.root / 'tool.py').write_text('# stable')
        with file_session():
            rows = scan_directory(self.root, recursive=True, suffixes=('.py',), excluded_parts=('__pycache__',))
            self.assertEqual([p.name for p in rows], ['tool.py'])
            cache = self.root / '__pycache__'
            cache.mkdir()
            (cache / 'generated.py').write_text('# ignored')
            (self.root / 'notes.txt').write_text('irrelevant')

    def test_retargeted_symlink_is_detected_before_first_content_read(self):
        a, b, link = self.root / 'a.json', self.root / 'b.json', self.root / 'link.json'
        atomic_json(a, {}); atomic_json(b, {})
        try:
            link.symlink_to(a)
        except OSError:
            self.skipTest('Symbolic links unavailable on this host')
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                canonical = resolve_path(link)
                link.unlink(); link.symlink_to(b)
                read_json(canonical)

    def test_parent_symlink_switch_is_detected_after_canonicalization(self):
        a, b, link = self.root / 'a', self.root / 'b', self.root / 'current'
        a.mkdir(); b.mkdir(); atomic_json(a / 'data.json', {}); atomic_json(b / 'data.json', {})
        try:
            link.symlink_to(a, target_is_directory=True)
        except OSError:
            self.skipTest('Directory symbolic links unavailable on this host')
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                read_json(resolve_path(link) / 'data.json')
                link.unlink(); link.symlink_to(b, target_is_directory=True)

    def test_raw_prompt_read_is_bound_even_if_a_parent_hits_the_cache(self):
        path = self.root / 'prompt.txt'; path.write_text('approved prompt')
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                self.assertEqual(derived('prompt', 'key', lambda: read_text(path)), 'approved prompt')
                path.write_text('changed prompt')
                derived('prompt', 'key', lambda: 'must not run')

    def test_negative_dependencies_transfer_through_both_cache_layers(self):
        path = self.root / 'optional'
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                compute = lambda: [] if not path_exists(path) else ['unexpected']
                self.assertEqual(memoized_validation('inner', 'key', compute), [])
                self.assertEqual(derived('outer', 'key', lambda: memoized_validation('inner', 'key', compute)), [])
                path.write_text('created')
                derived('outer', 'key', lambda: [])

    def test_options_are_content_bound_and_cached_results_are_immutable(self):
        options = {'mode': 'candidate', 'budget': False}
        with file_session() as memo:
            value = derived('mode', 'key', lambda: {'rows': [{'authorized': False}]}, options=options)
            with self.assertRaises(TypeError): value['rows'][0]['authorized'] = True
            with self.assertRaises(TypeError): value['rows'].append({})
            with self.assertRaises(TypeError): value.__init__({'authorized': True})
            with self.assertRaises(TypeError): value['rows'].__init__([{'authorized': True}])
            with self.assertRaises(TypeError): value._sealed = False
            copy.deepcopy(value)['rows'][0]['authorized'] = True
            self.assertIs(derived('mode', 'key', lambda: None, options=dict(options)), value)
            options['mode'] = 'formal'; options['budget'] = True
            self.assertFalse(derived('mode', 'key', lambda: {'authorized': False}, options=options)['authorized'])
            self.assertEqual(memo['audit_statistics']['mode'], {'runs': 2, 'hits': 1})

    def test_unserializable_identity_key_is_rejected(self):
        with file_session():
            with self.assertRaises(TypeError): derived('bad', object(), lambda: True)
            with self.assertRaises(TypeError): memoized_validation('bad', object(), lambda: [])
            with self.assertRaises(TypeError): derived('bad-result', 'key', lambda: {'mutable': set()})

    def test_prompt_crlf_behavior_is_preserved(self):
        path = self.root / 'prompt.txt'; path.write_bytes(b'line1\r\nline2\rline3\n')
        expected = path.read_text(encoding='utf-8')
        with file_session(): self.assertEqual(read_text(path, encoding='utf-8'), expected)

    def test_real_toolchain_scan_detects_new_checker(self):
        from execution_contract import toolchain, SKILLS
        skills = self.root / 'skills'
        for name in SKILLS:
            entry = skills / name / 'SKILL.md'; entry.parent.mkdir(parents=True)
            entry.write_text('SYNTHETIC tool entry')
        scripts = skills / SKILLS[0] / 'scripts'; scripts.mkdir()
        (scripts / 'old.py').write_text('# stable checker')
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                self.assertEqual(len(derived('toolchain', 'key', lambda: toolchain(scripts))['files']), 1)
                (scripts / 'new.js').write_text('// added checker')
                derived('toolchain', 'key', lambda: None)

    def test_runtime_snapshot_scan_tracks_nested_manifest_name(self):
        from runtime_snapshot import verify
        nested = self.root / 'nested'; nested.mkdir()
        checker = nested / 'tool.py'; checker.write_text('# frozen')
        manifest = self.root / 'manifest.json'
        atomic_json(manifest, {'policy': 'batch_snapshot_v1', 'files': [
            {'path': checker.relative_to(self.root).as_posix(), 'sha256': digest(checker)}]})
        ref = {'path': str(manifest), 'sha256': digest(manifest)}
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                verify(ref)
                atomic_json(nested / 'manifest.json', {'new': True})

    def test_changed_rule_body_invalidates_success_with_unchanged_index(self):
        from test_rule_memory import library
        from rule_memory import select, routing_session
        source = library(self.root / 'rules')
        def matched_body():
            rule = select(source, 'generation', {'memory_tags': ['person_on_bed']})[0]['rule']
            return read_text(checked_file(Path(source['root']), rule['file']), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session(), routing_session():
                derived('rule', 'key', matched_body)
                (Path(source['root']) / 'rule.md').write_text('# different rule')
                derived('rule', 'key', matched_body)

    def test_rule_no_match_is_invalidated_by_new_index_entry(self):
        from test_rule_memory import library
        from rule_memory import select, routing_session
        source = library(self.root / 'rules')
        panel = {'memory_tags': ['unmatched']}
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session(), routing_session():
                self.assertEqual(derived('rule', 'none', lambda: select(source, 'generation', panel)), [])
                path = Path(source['root']) / '记忆索引.json'
                index = read_json(path); index['rules'][0]['trigger']['any_tags'].append('unmatched')
                atomic_json(path, index)
                derived('rule', 'none', lambda: [])

    def test_validation_options_do_not_reuse_a_lenient_success(self):
        calls = []
        with file_session() as memo:
            self.assertEqual(memoized_validation('options', 'key', lambda: calls.append(False) or [],
                                                 options={'enforce_budget': False}), [])
            self.assertEqual(memoized_validation('options', 'key', lambda: calls.append(True) or ['budget hold'],
                                                 options={'enforce_budget': True}), ['budget hold'])
            self.assertEqual(calls, [False, True])
            self.assertEqual(memo['validation_hits'], 0)


class DispatchDependencyTests(unittest.TestCase):
    def setUp(self):
        from dispatch_fixture import DispatchFixture
        self.f = DispatchFixture()
        self.addCleanup(self.f.close)

    def test_absent_task_origin_created_after_real_preflight_cannot_commit(self):
        from episode_dispatch_queue import reserve_ready
        from staged_workflow import evaluate
        from task_context import ORIGIN_FILE
        before = self.f.state_path.read_bytes()
        def add_origin(*args, **kwargs):
            result = evaluate(*args, **kwargs)
            atomic_json(self.f.root / ORIGIN_FILE, {'unexpected': True})
            return result
        with patch('staged_workflow.evaluate', side_effect=add_origin):
            with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
                reserve_ready(self.f.state_path, digest(self.f.state_path), digest(self.f.control_path), 1)
        self.assertEqual(self.f.state_path.read_bytes(), before)
        self.assertEqual(list(self.f.root.glob('*.dispatch-*.json')), [])

    def test_no_matching_approval_is_bound_to_entire_index(self):
        from panel_readiness import approval_errors_for
        state = self.f.state
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                result = approval_errors_for(state, self.f.root, 'shot_design', [state['shot_manifest']], ['P999'])
                self.assertTrue(result)
                path = checked_file(self.f.root, state['approval_index'])
                index = read_json(path)
                index['entries'].append({'phase': 'shot_design', 'panel_ids': ['P999']})
                atomic_json(path, index)

    def test_real_cli_reports_discarded_preflight_without_writing_a_receipt(self):
        scripts = Path(__file__).resolve().parents[1] / 'scripts'
        before = self.f.state_path.read_bytes()
        code = '''import sys,runpy
from pathlib import Path
scripts=sys.argv.pop(1);sys.path.insert(0,scripts)
import staged_workflow as workflow
from platform_io import atomic_json
from task_context import ORIGIN_FILE
actual=workflow.evaluate
def switched(state,root,*args,**kwargs):
    result=actual(state,root,*args,**kwargs)
    atomic_json(Path(root)/ORIGIN_FILE,{'external_change':True})
    return result
workflow.evaluate=switched
sys.argv[0]=str(Path(scripts)/'episode_dispatch_queue.py')
runpy.run_path(sys.argv[0],run_name='__main__')
'''
        proc = subprocess.run([sys.executable, '-B', '-c', code, str(scripts), '--state', str(self.f.state_path),
                               '--expected-state-sha256', digest(self.f.state_path),
                               '--expected-control-sha256', digest(self.f.control_path), '--max-count', '1'],
                              capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result['status'], 'HOLD')
        self.assertIn('CHECK_SNAPSHOT_CHANGED', str(result['errors']))
        metrics = result['dispatch_metrics']
        self.assertFalse(metrics['read_dependencies_verified'])
        self.assertEqual(metrics['discarded_preflights'], 1)
        self.assertEqual(metrics['ready_wait']['panels'], [])
        self.assertEqual(metrics['file_reuse_statistics']['dependency_invalidations'], 1)
        self.assertEqual(len(metrics['locks']), 2)
        self.assertTrue(all('hold_seconds' in row for row in metrics['locks']))
        self.assertEqual(self.f.state_path.read_bytes(), before)
        self.assertEqual(list(self.f.root.glob('*.dispatch-*.json')), [])


if __name__ == '__main__':
    unittest.main()
