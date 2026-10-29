"""Synthetic conflict regressions; no production evidence or image calls."""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts'), str(Path(__file__).parent)]
import input_semantics as sem
import test_panel_readiness as fixture
from codex_reference_contract import checked_file, read_json, file_session
from production_runtime import episode_bundle
from _historical_fixture import compile_jobs


def reviewed(inputs):
    value = sem.review_template(inputs)
    value.update(status='REVIEWED', reviewer='SYNTHETIC', evidence='Isolated fixture review, never user approval')
    for check in value['checks'].values():
        check.update(status='PASS', evidence='Synthetic exact inputs and references inspected')
    return value


class ConflictCases(unittest.TestCase):
    def shot(self, attribute, value, quote, name='甲'):
        return {'panel_id': 'P001', 'locked_script': {'event': name + quote},
                'semantic_facts': [{'subject_id': 'A', 'subject_name': name, 'instant': 'current',
                                    'attribute': attribute, 'value': value, 'source_quote': quote}]}

    def test_six_reported_conflicts_and_resolutions(self):
        cases = [
            ('E027-P002', 'eyes', 'wide', '骤然睁大的眼睛', '甲：上眼睑略收以表达当前专注', '甲：双眼睁大'),
            ('E028-P009', 'eyes', 'wide', '睁大眼睛', '甲：上眼睑略收以表达当前专注', '甲：眼睑抬起，双眼睁大'),
            ('E029-P001', 'mouth', 'parted', '嘴唇微张', '甲：双唇收拢自然闭合', '甲：嘴唇微张，保持沉默'),
            ('E029-P005', 'focus', 'unfocused', '视线无法聚焦', '甲：瞳孔朝向作用对象，表现专注', '甲：眼皮沉，视线失焦'),
        ]
        for pid, attr, value, quote, bad, good in cases:
            with self.subTest(panel=pid):
                s = self.shot(attr, value, quote)
                self.assertTrue(sem.conflict_errors(s, bad))
                self.assertEqual(sem.conflict_errors(s, good), [])
        hidden = {'panel_id': 'P016', 'subject_visibility': {'A': {
            'subject_name': '甲', 'face_visible': False, 'identity_observable': True,
            'evidence': '只见左前肩与后脑'}},
            'adjacent_face_comparison': {'A': {'face_comparable': True}}}
        self.assertTrue(sem.conflict_errors(hidden, '甲：瞳孔看向对方，嘴唇微张'))
        hidden['adjacent_face_comparison']['A']['face_comparable'] = False
        self.assertEqual(sem.conflict_errors(hidden, '甲：后脑与肩线入画'), [])
        self.assertTrue(hidden['subject_visibility']['A']['identity_observable'])
        crop = {'panel_id': 'P002', 'framing': {'body_crop': 'chest_up',
            'required_visible': ['两人腰部以上', '右手自然垂在身侧的完整手势']}}
        self.assertTrue(sem.conflict_errors(crop, ''))
        crop['framing']['body_crop'] = 'mixed'
        crop['visible_region'] = '下沿上腿，完整自然垂手，不到膝部'
        self.assertEqual(sem.conflict_errors(crop, ''), [])

    def test_negations_different_people_and_instants_not_positive_conflicts(self):
        s = self.shot('mouth', 'parted', '嘴唇微张')
        for prompt in ('甲：嘴唇微张；不得自然闭合。', '乙：双唇自然闭合。\n甲：嘴唇微张。',
                       '甲上一格双唇自然闭合。\n甲当前嘴唇微张。'):
            self.assertEqual(sem.conflict_errors(s, prompt), [])

    def test_facts_must_be_grounded_and_no_conflicting_fact_values(self):
        s = self.shot('eyes', 'wide', '睁大眼睛')
        s['semantic_facts'][0]['source_quote'] = '编造源句'
        self.assertTrue(sem.conflict_errors(s, ''))
        s = self.shot('eyes', 'wide', '睁大眼睛')
        s['semantic_facts'].append({**s['semantic_facts'][0], 'value': 'narrow'})
        self.assertTrue(sem.conflict_errors(s, ''))

    def test_checker_never_creates_review_or_approval(self):
        s = self.shot('eyes', 'wide', '睁大眼睛')
        inputs = {'prompt': '甲：睁大眼睛'}
        self.assertEqual(sem.conflict_errors(s, inputs['prompt']), [])
        review = sem.review_template(inputs)
        self.assertEqual(review['status'], 'UNREVIEWED')
        self.assertTrue(sem.review_errors(review, inputs))
        self.assertNotIn('approval', review)


class RealInputBinding(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'episode'
        self.state, self.shots = fixture.fixture(self.root)
        self.state['input_semantics_policy'] = sem.POLICY
        # New explicit facts are empty when the synthetic script has none.
        for shot in self.shots['panels']:
            shot['semantic_facts'] = []
            shot['subject_visibility'] = {c['character_id']: {
                'subject_name': c['character_id'], 'face_visible': True,
                'identity_observable': True, 'evidence': 'Synthetic visible face'}
                for c in shot.get('character_bindings', [])}
        self.state['shot_manifest'] = fixture.fixtures.write(self.root, 'semantic-shots.json', self.shots)
        audit = read_json(checked_file(self.root, self.state['semantic_audit']))
        audit['shot_manifest'] = self.state['shot_manifest']
        for row, shot, record in zip(audit['panels'], self.shots['panels'], self.state['panels']):
            path = checked_file(self.root, record['package_manifest']); packet = read_json(path)
            packet['panels'][0].update(semantic_facts=shot['semantic_facts'], subject_visibility=shot['subject_visibility'])
            record['package_manifest'] = fixture.fixtures.write(self.root, record['package_manifest']['path'], packet)
            subset = read_json(checked_file(self.root, record['shot_subset']))
            subset['panels'][0].update(semantic_facts=shot['semantic_facts'], subject_visibility=shot['subject_visibility'])
            record['shot_subset'] = fixture.fixtures.write(self.root, record['shot_subset']['path'], subset)
            inputs = sem.actual_input(self.state, self.root, shot, packet, path.parent)
            row['execution_review'] = reviewed(inputs)
        self.audit = audit
        self.save_audit()

    def save_audit(self):
        self.state['semantic_audit'] = fixture.fixtures.write(self.root, 'semantic-audit.json', self.audit)

    def check(self, index=1):
        shot = self.shots['panels'][index]; record = self.state['panels'][index]
        path = checked_file(self.root, record['package_manifest'])
        return sem.panel_errors(self.state, self.root, shot, read_json(path), path.parent)

    def test_real_final_input_binds_without_mutating_files(self):
        before = copy.deepcopy(self.state)
        self.assertEqual(self.check(), [])
        report = sem.coverage(self.state, self.root)
        self.assertEqual(report['reviewed_panel_ids'], ['P001', 'P002', 'P003', 'P004'])
        self.assertFalse(report['dispatch_authorized'])
        self.assertEqual(self.state, before)

    def test_changed_prompt_with_synchronized_json_invalidates_only_its_review(self):
        record = self.state['panels'][1]; path = checked_file(self.root, record['package_manifest'])
        packet = read_json(path); panel = packet['panels'][0]
        panel['prompt'] += '\nSYNTHETIC new expression requirement'
        (self.root / panel['prompt_file']).write_text(panel['prompt'], encoding='utf-8', newline='\n')
        record['package_manifest'] = fixture.fixtures.write(self.root, path.name, packet)
        self.assertTrue(any('已变化' in e for e in self.check()))
        self.assertEqual(self.check(2), [])

    def test_unsynchronized_prompt_and_manifest_block_before_review(self):
        record = self.state['panels'][1]; path = checked_file(self.root, record['package_manifest'])
        packet = read_json(path)
        (self.root / packet['panels'][0]['prompt_file']).write_text('SYNTHETIC changed only txt', encoding='utf-8', newline='\n')
        self.assertTrue(any('prompt.txt' in e for e in self.check()))

    def test_criteria_change_invalidates_review_even_with_same_prompt(self):
        record = self.state['panels'][1]; path = checked_file(self.root, record['package_manifest'])
        packet = read_json(path); packet['panels'][0]['memory_applications'] = [{'checks': {'face': 'SYNTHETIC changed expected'}}]
        record['package_manifest'] = fixture.fixtures.write(self.root, path.name, packet)
        self.assertTrue(self.check())

    def test_path_only_relocation_reuses_review(self):
        new = self.root.parent / 'receiver'; shutil.copytree(self.root, new)
        record = self.state['panels'][1]; path = checked_file(new, record['package_manifest'])
        self.assertEqual(sem.panel_errors(self.state, new, self.shots['panels'][1], read_json(path), path.parent), [])

    def test_missing_checks_and_unresolved_issue_block(self):
        self.audit['panels'][1]['execution_review']['checks'].pop('actual_references'); self.save_audit()
        self.assertTrue(self.check())
        report = sem.coverage(self.state, self.root)
        self.assertEqual(list(report['errors']), ['P002'])

    def test_legacy_policy_is_not_silently_upgraded(self):
        old = copy.deepcopy(self.state); old.pop('input_semantics_policy')
        self.assertEqual(sem.panel_errors(old, self.root, {}, None, None), [])
        old['input_semantics_policy'] = 'unrecognized'
        self.assertTrue(sem.panel_errors(old, self.root, {}, None, None))

    def test_current_tool_or_rule_change_invalidates_review(self):
        self.state['toolchain']['files'][0]['sha256'] = 'different'
        self.assertTrue(self.check())

    def test_structural_success_cannot_reuse_unreviewed_template(self):
        self.audit['panels'][1]['execution_review']['status'] = 'UNREVIEWED'; self.save_audit()
        self.assertTrue(self.check())

    def test_cached_review_detects_mid_transaction_prompt_edit(self):
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                self.assertEqual(self.check(), [])
                self.assertEqual(self.check(), [])
                path = self.root / 'P002/prompt.txt'
                path.write_text(path.read_text(encoding='utf-8') + '\nSYNTHETIC mutation', encoding='utf-8', newline='\n')
                self.assertTrue(self.check())

    def test_template_cli_preserves_design_and_never_overwrites(self):
        import subprocess
        state_ref = fixture.fixtures.write(self.root, '00_输入审计/生产流程.json', self.state)
        dest = self.root / 'candidate-audit.json'
        script = Path(sem.__file__)
        command = [sys.executable, '-B', str(script), '--state', str(self.root / state_ref['path']),
                   '--output', str(dest), '--panels', 'P002']
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        value = json.loads(dest.read_text(encoding='utf-8'))
        self.assertEqual(value['panels'][1]['execution_review']['status'], 'UNREVIEWED')
        self.assertEqual(value['panels'][0], self.audit['panels'][0])
        self.assertEqual(value['panels'][1]['checks'], self.audit['panels'][1]['checks'])
        original = dest.read_bytes()
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(dest.read_bytes(), original)

    def test_dependency_plan_is_reviewed_without_placeholder_images(self):
        shot = copy.deepcopy(self.shots['panels'][1]); shot['generation_dependencies'] = ['P001']
        record = self.state['panels'][1]; path = checked_file(self.root, record['package_manifest'])
        packet = read_json(path); panel = packet['panels'][0]
        refs = [copy.deepcopy(r) for r in panel['reference_images']]
        refs.append({'path': '@DEPENDENCY:P001'})
        row = {'panel_id': 'P002', 'reference_path_basis': 'run_root', 'arguments': {'prompt': panel['prompt'], 'transparent_background': False,
                'referenced_image_paths': [r['path'] for r in refs]}, 'reference_files': refs,
                'reference_bindings': [*panel['reference_bindings'], {'alias': '@PREV', 'purpose': 'continuity'}],
                'output_spec': panel.get('output_spec')}
        inputs = sem.planned_input(self.state, self.root, shot, row)
        self.assertTrue(inputs['dependency_plan'])
        self.assertEqual(inputs['references'][-1], {'dependency': 'P001'})
        self.assertTrue(sem.review_errors(sem.review_template(inputs), inputs))
        self.assertEqual(sem.review_errors(reviewed(inputs), inputs), [])


class FrozenHandoff(unittest.TestCase):
    def fixture(self):
        from test_direct_handoff import DirectHandoffTests
        f = DirectHandoffTests('test_direct_bound_run_real_full_episode_gates_and_conditional_release')
        f.FINAL_SEMANTICS = True
        f.setUp(); self.addCleanup(f.doCleanups)
        return f

    def test_real_pack_extract_bind_frozen_gates_and_release(self):
        f = self.fixture()
        f.test_direct_bound_run_real_full_episode_gates_and_conditional_release()

    def test_missing_semantic_receipt_cannot_pass_formal_closure(self):
        import handoff_delivery as delivery
        f = self.fixture()
        audit = fixture.fixtures.read(f.template, f.state['semantic_audit'])
        audit['panels'][2]['execution_review']['status'] = 'UNREVIEWED'
        f.state['semantic_audit'] = fixture.fixtures.write(f.template, 'bad-final-audit.json', audit)
        f.index['episodes'][0]['semantic_audit'] = f.ref('template/E000/bad-final-audit.json')
        f.refresh_template()
        errors = delivery.closure(f.package, f.index)
        self.assertTrue(any('语义审查未闭合' in e for e in errors), errors)

    def test_receiver_reuses_review_and_never_grants_dispatch(self):
        from production_runtime import receiver_audit
        f = self.fixture()
        result = receiver_audit(f.state, f.template, ['P001', 'P002'], ['P001', 'P002', 'P003', 'P004'])
        self.assertEqual(result['final_input_semantics']['status'], 'PREPRODUCTION_INPUTS_REVIEWED')
        self.assertFalse(result['dispatch_authorized'])
        self.assertEqual(result['image_calls'], 0)


if __name__ == '__main__':
    unittest.main()
