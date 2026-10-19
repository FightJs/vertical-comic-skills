"""Only approved, applicable image-risk constraints reach the actual prompt."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from image_risk_guards import shot_errors, packet_errors


class ImageRiskGuardTests(unittest.TestCase):
    def test_empty_risks_add_no_generic_prompt_requirement(self):
        self.assertEqual(packet_errors({}, {'prompt': '具体画面'}), [])

    def test_real_risk_must_match_approved_shot_and_prompt(self):
        risks = [{'kind': 'support_contact', 'constraint': '双脚压在床垫上，身体由床承托'}]
        shot = {'production_risks': risks}
        self.assertEqual(packet_errors(shot, {'production_risks': risks,
            'prompt': '双脚压在床垫上，身体由床承托'}), [])
        self.assertTrue(packet_errors(shot, {'production_risks': risks, 'prompt': '人物在床边'}))
        self.assertTrue(packet_errors(shot, {'production_risks': [],
            'prompt': '双脚压在床垫上，身体由床承托'}))

    def test_vague_or_duplicate_constraints_are_rejected(self):
        self.assertTrue(shot_errors({'production_risks': [{'kind': 'prop_count', 'constraint': ''}]}))
        self.assertTrue(shot_errors({'production_risks': [
            {'kind': 'lower_edge', 'constraint': '保留下缘'},
            {'kind': 'lower_edge', 'constraint': '保留脚'}]}))


if __name__ == '__main__':
    unittest.main()
