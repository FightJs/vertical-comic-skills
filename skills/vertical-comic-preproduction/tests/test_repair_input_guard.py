"""Repair preflight catches contradictions before spending an image request."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from repair_input_guard import repair_errors


class RepairInputGuardTests(unittest.TestCase):
    def panel(self):
        contact = {
            'actor': '桑榆', 'target': '温霜', 'actor_limb': '桑榆空着的蓝袖前臂',
            'target_part': '温霜靠近她的米白袖前臂',
            'visible_path': '桑榆的手从自己肩肘连续弯起并搭绕温霜前臂',
            'forbidden_reverse': '温霜不能抓桑榆蓝袖',
        }
        return {
            'operation': 'repair',
            'reference_images': [{'alias': '@REPAIR_TARGET', 'role': 'framing'}],
            'reference_bindings': [{
                'alias': '@REPAIR_TARGET', 'purpose': 'framing', 'subject_ids': ['P015'],
                'allowed_transfer': ['composition'],
                'forbidden_transfer': ['crop', 'pose', 'contact'],
            }],
            'repair_focus': {'failed_transfers': ['crop', 'pose', 'contact'], 'action_contact': contact},
            'prompt': '；'.join(contact.values()),
        }

    def test_rejects_actual_conflicting_failed_crop(self):
        panel = self.panel()
        panel['reference_bindings'][0]['allowed_transfer'].append('crop')
        panel['reference_bindings'][0]['forbidden_transfer'].remove('crop')
        errors = repair_errors(panel)
        self.assertTrue(any('允许继承本次待修正要素:crop' in error for error in errors))

    def test_rejects_missing_repair_focus_and_stale_round_text(self):
        panel = self.panel()
        panel.pop('repair_focus')
        panel['prompt'] += ' 待人工批准的额外一次定向补救（当前禁止调用）'
        errors = repair_errors(panel)
        self.assertTrue(any('须声明repair_focus' in error for error in errors))
        self.assertTrue(any('流程状态' in error for error in errors))

    def test_contact_geometry_must_reach_real_prompt(self):
        panel = self.panel()
        panel['prompt'] = '桑榆挽着温霜'
        self.assertTrue(any('action_contact.visible_path' in error for error in repair_errors(panel)))

    def test_valid_scoped_repair_passes(self):
        self.assertEqual(repair_errors(self.panel()), [])

    def test_ordinary_panels_are_untouched(self):
        self.assertEqual(repair_errors({'operation': 'generate', 'prompt': '普通格'}), [])

    def test_frozen_legacy_repair_without_focus_remains_compatible(self):
        panel = self.panel()
        panel.pop('repair_focus')
        self.assertEqual(repair_errors(panel, require_focus=False), [])

    def test_actual_prompt_must_match_packet_and_has_no_stale_status(self):
        panel = self.panel()
        errors = repair_errors(panel, actual_prompt=panel['prompt'] + ' 当前禁止调用')
        self.assertTrue(any('实际提交提示词与逐格JSON不一致' in error for error in errors))
        self.assertTrue(any('流程状态' in error for error in errors))


if __name__ == '__main__':
    unittest.main()
