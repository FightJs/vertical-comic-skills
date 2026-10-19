"""Executable framing extension; synthetic data, no paid image calls."""
import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from visual_evidence import framing_errors, framing_execution_block, execution_block, packet_errors
from test_visual_evidence import fixture


def framed():
    basis, panel = fixture()
    panel['framing'].update(background_treatment='clear_limited', body_crop='waist_up',
        focus='人物表情及握杯动作', required_visible=['表情', '右手与杯柄接触'])
    panel['visible_region'] = '上缘略高于头顶，下缘在腰；人物画面右侧，背后仅露舞台一角'
    panel['visual_execution_block'] = execution_block(panel)
    panel['prompt'] = panel['visual_execution_block']
    return basis, panel


class PromptFramingTests(unittest.TestCase):
    def test_legacy_without_extension_is_unchanged(self):
        basis, panel = fixture()
        self.assertEqual(framing_execution_block(panel), '')
        self.assertEqual(framing_errors(panel, prompt=True), [])
        self.assertEqual(packet_errors(basis, panel, panel, basis), [])

    def test_actual_input_carries_crop_background_and_existing_contacts_details(self):
        basis, panel = framed()
        block = framing_execution_block(panel)
        self.assertIn(panel['visible_region'], block)
        self.assertIn('右手与杯柄接触', block)
        self.assertIn('不加入背景虚化', block)
        self.assertIn('单层水滴', panel['prompt'])
        self.assertEqual(packet_errors(basis, panel, panel, basis), [])
        missing = copy.deepcopy(panel)
        missing['prompt'] = missing['prompt'].replace(block, '')
        self.assertTrue(packet_errors(basis, panel, missing, basis))

    def test_invalid_values_and_missing_region_do_not_compile(self):
        _, panel = framed()
        for value in ('blur', {}, None):
            bad = copy.deepcopy(panel)
            bad['framing']['background_treatment'] = value
            self.assertTrue(framing_errors(bad))
            with self.assertRaises(ValueError):
                framing_execution_block(bad)
        panel.pop('visible_region')
        self.assertTrue(framing_errors(panel))

    def test_special_depth_requires_specific_design_basis(self):
        _, panel = framed()
        panel['framing']['background_treatment'] = 'approved_depth_of_field'
        self.assertTrue(framing_errors(panel))
        panel['framing']['background_treatment_basis'] = '测试批准设计：脸与手清楚，远景按指定景深处理'
        self.assertEqual(framing_errors(panel), [])
        block = framing_execution_block(panel)
        self.assertIn('测试批准设计', block)
        self.assertNotIn('不加入背景虚化', block)

    def test_prompt_rebuild_keeps_frozen_specific_visual_block(self):
        from repair_prompt_package_v2 import build_prompt
        _, panel = framed()
        panel['locked_script'] = '测试人物握杯'
        prompt, _, _ = build_prompt(panel, 'eye_level', 'medium_close', '3:4',
            '舞台前', '朝舞台', '眼平', panel['visible_region'], ['@人物'],
            None, None, 'test-camera', '人物在画面右侧握杯')
        self.assertIn(panel['visual_execution_block'], prompt)
        self.assertEqual(prompt.count('本格构图与背景处理'), 1)
        self.assertIn('拇指与掌部连接自然', prompt)
        self.assertIn('单层水滴', prompt)

    def test_validator_accepts_negative_blur_instruction_but_rejects_missing_block(self):
        from validate_preproduction import Gate
        _, panel = framed()
        panel['view_check'] = 'PASS'
        gate = Gate(Path('.'))
        gate.check_prompt_conflicts(panel, 'TEST')
        self.assertEqual(gate.errors, [])
        panel['prompt'] = '画面右侧人物，背景虚化'
        gate.check_prompt_conflicts(panel, 'TEST')
        self.assertTrue(gate.errors)

    def test_real_qa_command_preserves_unreviewed_original_dimensions(self):
        from test_codex_reference_contract import ReferenceTests
        from codex_reference_contract import digest
        fx = ReferenceTests('test_valid_reference_route')
        fx.setUp()
        self.addCleanup(fx.doCleanups)
        fx.use_no_composition_reference()
        panel = fx.panel
        panel['framing'].update(background_treatment='clear_limited', focus='握杯表情')
        panel['visible_region'] = '画面左侧胸以上人物，下缘保留手势，后方仅露固定窗框'
        panel['prompt'] += '\n' + framing_execution_block(panel)
        (fx.root / 'P001/prompt.txt').write_text(panel['prompt'])
        fx.write('manifest.json', fx.manifest)
        image = fx.root / fx.refs[2]['path']
        output = fx.root / 'qa'
        script = Path(__file__).resolve().parents[1] / 'scripts/make_generation_qa.py'
        subprocess.run([sys.executable, '-B', str(script), '--package', str(fx.root),
            '--manifest', 'manifest.json', '--images', str(fx.root), '--image-path', str(image),
            '--output', str(output), '--skip-contact-sheet'], check=True, capture_output=True)
        report = json.loads((output / '生成图QA报告.json').read_text())
        self.assertEqual(report['errors'], [])
        row = report['panels'][0]
        self.assertEqual(row['image_sha256'], digest(image))
        self.assertIn(framing_execution_block(panel), row['framing_review_focus']['expected'])
        self.assertEqual(row['inspection_plan']['status'], 'UNREVIEWED')
        self.assertEqual(row['dimension_review']['framing']['status'], 'UNREVIEWED')
        self.assertEqual(row['dimension_review']['background_space']['status'], 'UNREVIEWED')


if __name__ == '__main__':
    unittest.main()
