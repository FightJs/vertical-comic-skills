"""Priority-contract checks use synthetic records, never production approvals."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from input_priority import EXECUTION_BLOCK, resolution_block, resolution_errors
from repair_prompt_package import content_block
from validate_preproduction import Gate


class InputPriorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.gate = Gate(Path(self.temp.name))

    def test_compiler_carries_policy_and_approved_solution(self):
        resolution = {
            "issue": "原镜头要求穿过床沿看全身",
            "scene_evidence": "SYNTHETIC scene record",
            "approved_visual_solution": "镜头稍抬高，保留床沿遮挡与原动作",
            "approval_evidence": "SYNTHETIC approval only",
            "status": "APPROVED",
        }
        panel = {"panel_id": "P001", "input_priority_policy": "physical_scene_priority_v1"}
        shot = {"visual_resolution": resolution, "framing": {"body_crop": "waist_up"}}
        prompt = content_block(panel, shot)
        self.assertIn(EXECUTION_BLOCK, prompt)
        self.assertIn(resolution_block(resolution), prompt)
        self.gate.check_input_priority({"prompt": prompt, "visual_resolution": resolution}, "P001", True, prompt=True)
        self.assertEqual(self.gate.errors, [])

    def test_unapproved_resolution_blocks_even_when_prompt_is_generic(self):
        unresolved = {"status": "HOLD", "issue": "missing table"}
        self.assertTrue(resolution_errors(unresolved))
        self.assertEqual(resolution_block(unresolved), "")
        self.gate.check_input_priority({"prompt": EXECUTION_BLOCK, "visual_resolution": unresolved}, "P001", True, prompt=True)
        self.assertTrue(any("VISUAL_CONFLICT_HOLD" in error for error in self.gate.errors))

    def test_missing_executable_policy_blocks_new_package(self):
        self.gate.check_input_priority({"prompt": "只画漂亮人物"}, "P001", True, prompt=True)
        self.assertTrue(any("实际提示词缺少物理与场景" in error for error in self.gate.errors))

    def test_legacy_package_does_not_require_new_policy(self):
        self.gate.check_input_priority({"prompt": "legacy"}, "P001", False, prompt=True)
        self.assertEqual(self.gate.errors, [])


if __name__ == "__main__":
    unittest.main()
