"""Synthetic isolated protocol tests. No production images or user approvals."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import test_codex_reference_contract as fixtures
from codex_reference_contract import validate_panel, digest, invalidate_execution
from continuity_contract import reference_usage_block, check_dimension_report
from style_contract import style_block, validate_style, review_errors, output_spec_errors
from staged_workflow import evaluate, approval_errors, basis_errors
from validate_preproduction import Gate
from check_control_inputs import validate_manifest as input_gate


class StagedTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ReferenceTests("test_valid_reference_route")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.root, self.panel, self.manifest = self.f.root, self.f.panel, self.f.manifest
        self.f.use_no_composition_reference()
        self.panel.update({"style_policy": "approved_style_v1", "visual_state_keys": ["style:UNIT:v1"],
                           "locked_script": {"event_text": "SYNTHETIC ONLY"},
                           "output_spec": {"formats": ["PNG"], "min_width": 90, "min_height": 160, "exact_size": None}})
        self.manifest.update({"style_policy": "approved_style_v1", "workflow_policy": "staged_comic_v1"})
        ref = self.panel["reference_images"][-1]
        ref["reference_kind"] = "approved_character_board"
        ref["approval_evidence"] = self.f.write("style_approval.json", {
            "status": "APPROVED", "source_kind": "user_message", "source_locator": "SYNTHETIC_UNIT_FIXTURE",
            "quote": "SYNTHETIC NOT REAL APPROVAL", "book_id": "UNIT", "approved_sha256": [ref["sha256"]]})
        self.panel["reference_bindings"].append({"alias": ref["alias"], "purpose": "style", "subject_ids": ["P001"],
            "allowed_transfer": ["linework", "palette", "shading"], "forbidden_transfer": ["composition"]})
        self.panel["style_contract"] = {"book_id": "UNIT", "reference_aliases": [ref["alias"]],
            "traits": {key: "SYNTHETIC observed trait" for key in ("linework", "face_proportions", "hair", "coloring", "shading")}}
        self.panel["style_execution_block"] = style_block(self.panel["style_contract"])
        self.panel["reference_usage_block"] = reference_usage_block(self.panel["reference_bindings"], self.panel["reference_images"])
        self.panel["prompt"] = self.panel["reference_usage_block"] + "\n" + self.panel["style_execution_block"] + "\n" + self.panel["negative_prompt"]
        (self.root / "P001/prompt.txt").write_text(self.panel["prompt"], encoding='utf-8', newline='\n')

    def test_actual_style_input_is_exported(self):
        errors, submission = validate_panel(self.panel, self.root)
        self.assertEqual(errors, [])
        self.assertIn(str((self.root / self.panel["reference_images"][-1]["path"]).resolve()), submission["arguments"]["referenced_image_paths"])

    def test_style_only_alias_without_actual_input_is_blocked(self):
        self.panel["style_contract"]["reference_aliases"] = ["@MISSING"]
        self.assertTrue(validate_style(self.panel, self.root))

    def test_unapproved_or_wrong_book_style_is_blocked(self):
        self.panel["style_contract"]["book_id"] = "OTHER_BOOK"
        self.assertTrue(validate_style(self.panel, self.root))

    def test_style_evidence_hash_change_blocks(self):
        (self.root / "style_approval.json").write_text("{}", encoding='utf-8', newline='\n')
        self.assertTrue(validate_style(self.panel, self.root))

    def test_failed_candidate_cannot_be_style_authority(self):
        self.panel["reference_images"][-1]["reference_kind"] = "failed_candidate"
        self.assertTrue(validate_style(self.panel, self.root))

    def test_style_block_must_reach_actual_prompt(self):
        self.panel["prompt"] = "generic style"
        self.assertTrue(validate_style(self.panel, self.root))

    def test_cannot_remove_style_policy_to_bypass_stage(self):
        self.panel.pop("style_policy")
        self.assertEqual(input_gate(self.manifest, self.root)["status"], "HOLD")
        self.manifest.pop("style_policy")
        self.assertEqual(input_gate(self.manifest, self.root)["status"], "HOLD")

    def test_qa_generates_style_comparison_but_never_pass(self):
        report, output = self.f.qa_report()
        item = report["panels"][0]
        self.assertEqual(report["errors"], [])
        self.assertEqual(item["style_review"]["status"], "UNREVIEWED")
        self.assertTrue((output / item["style_comparisons"][0]).is_file())
        self.assertEqual(item["output_spec_check"], "PASS")

    def test_five_passes_cannot_override_failed_style(self):
        report, output = self.f.qa_report()
        item = report["panels"][0]
        for review in item["dimension_review"].values():
            review.update(status="PASS", reviewer="SYNTHETIC", evidence="UNIT TEST ONLY")
        item["style_review"].update(status="FAIL", reviewer="SYNTHETIC", evidence="UNIT TEST drift")
        result = check_dimension_report(self.manifest, report, self.root / "全话提示词索引.json")
        self.assertTrue(any("IMAGE_STYLE_HOLD" in e for e in result["errors"]))

    def test_output_dimensions_and_format_are_checked(self):
        self.assertTrue(output_spec_errors(self.panel, [89, 160], "PNG"))
        self.assertTrue(output_spec_errors(self.panel, [90, 160], "JPEG"))
        self.assertEqual(output_spec_errors(self.panel, [90, 160], "PNG"), [])

    def state(self, count=4):
        source = self.f.write("source.json", {"unit": "SYNTHETIC SCRIPT"})
        ids = [f"P{i+1:03d}" for i in range(count)]
        snapshot = self.f.write("snapshot.json", {"source_sha256": source["sha256"], "panel_ids": ids,
            "locked_scripts": {p: self.panel["locked_script"] for p in ids}})
        basis = self.f.write("basis.json", {"book_id": "UNIT", "episode_id": "E000", "reference_files": self.panel["reference_images"], "style": {
            "reference_sha256": [self.panel["reference_images"][-1]["sha256"]], "traits": self.panel["style_contract"]["traits"]}})
        shots = [dict(self.panel, panel_id=pid) for pid in ids]
        shot = self.f.write("shots.json", {"panels": shots})
        self.shots = shots
        data = {"policy": "staged_comic_v1", "book_id": "UNIT", "episode_id": "E000",
            "source_script": source, "source_snapshot": snapshot, "visual_basis": basis, "shot_manifest": shot,
            "gates": {}, "panels": [{"panel_id": pid, "status": "PENDING"} for pid in ids], "state_reviews": {}}
        data["gates"]["visual_basis"] = self.approve([source, snapshot, basis])
        data["gates"]["shot_design"] = self.approve([basis, shot])
        data["production_authorization"] = dict(self.approve([source]), panel_ids=ids)
        return data

    def approve(self, artifacts):
        return {"status": "APPROVED", "source_kind": "user_message", "source_locator": "SYNTHETIC_UNIT_FIXTURE",
                "quote": "SYNTHETIC NOT REAL APPROVAL", "book_id": "UNIT", "episode_id": "E000", "artifacts": artifacts}

    def fake_completed_for_routing(self, state, index):
        record = state["panels"][index]
        record["status"] = "VISUAL_PASS"
        record["output"] = self.f.write(f"routing_output{index}.json", {"SYNTHETIC": index})
        record["package_manifest"] = self.f.write(f"routing_package{index}.json", {"book_id": "UNIT", "episode_id": "E000", "panels": [self.shots[index]]})
        # Only routing tests mock qa_errors; real QA is exercised in other tests.

    def test_jump_ahead_is_blocked(self):
        result = evaluate(self.state(), self.root, "generate", "P003")
        self.assertEqual(result["next_action"], "SOURCE_ORDER_HOLD")

    def test_missing_visual_approval_stops_before_shots(self):
        state = self.state()
        state["gates"]["visual_basis"] = None
        self.assertEqual(evaluate(state, self.root)["next_action"], "WAIT_VISUAL_BASIS_APPROVAL")

    def test_changed_approved_artifact_is_not_reused(self):
        state = self.state()
        (self.root / "shots.json").write_text("{}", encoding='utf-8', newline='\n')
        self.assertEqual(evaluate(state, self.root)["status"], "HOLD")

    def test_new_style_basis_invalidates_old_execution_copy(self):
        state = self.state()
        basis = json.loads((self.root / state["visual_basis"]["path"]).read_text(encoding='utf-8-sig'))
        self.assertEqual(basis_errors(self.panel, basis), [])
        basis["style"]["traits"]["shading"] = "CHANGED"
        self.assertTrue(basis_errors(self.panel, basis))

    def test_missing_pilot_approval_blocks_fourth_panel(self):
        state = self.state()
        for i in range(3):
            self.fake_completed_for_routing(state, i)
        with patch("staged_workflow.qa_errors", return_value=[]):
            result = evaluate(state, self.root, "generate", "P004")
        self.assertEqual(result["next_action"], "WAIT_PILOT_APPROVAL")

    def test_new_state_requires_its_first_image_review(self):
        state = self.state(5)
        self.shots[3]["visual_state_keys"] = ["costume:NEW:v1"]
        state["shot_manifest"] = self.f.write("shots.json", {"panels": self.shots})
        state["gates"]["shot_design"] = self.approve([state["visual_basis"], state["shot_manifest"]])
        for i in range(4):
            self.fake_completed_for_routing(state, i)
        state["gates"]["pilot"] = self.approve([state["visual_basis"], state["shot_manifest"], *[r["output"] for r in state["panels"][:3]]])
        with patch("staged_workflow.qa_errors", return_value=[]):
            result = evaluate(state, self.root, "generate", "P005")
        self.assertEqual(result["next_action"], "WAIT_NEW_STATE_APPROVAL")

    def test_fake_visual_pass_without_qa_is_blocked(self):
        state = self.state()
        state["panels"][0]["status"] = "VISUAL_PASS"
        self.assertEqual(evaluate(state, self.root, "generate", "P002")["status"], "HOLD")

    def test_cancelled_repair_does_not_restart(self):
        state = self.state()
        state["panels"][0]["status"] = "CANCELLED"
        self.assertEqual(evaluate(state, self.root, "generate", "P001")["next_action"], "REVIEW_OR_RESOLVE_CURRENT_PANEL")

    def test_final_approval_is_separate_from_visual_pass(self):
        state = self.state(1)
        self.fake_completed_for_routing(state, 0)
        artifacts = [state["visual_basis"], state["shot_manifest"], state["panels"][0]["output"]]
        state["gates"]["pilot"] = self.approve(artifacts)
        with patch("staged_workflow.qa_errors", return_value=[]):
            self.assertEqual(evaluate(state, self.root, "deliver")["next_action"], "WAIT_FINAL_APPROVAL")
            state["gates"]["final"] = self.approve(artifacts)
            result = evaluate(state, self.root, "deliver")
        self.assertEqual(result["next_action"], "READY_TO_PACKAGE")
        self.assertEqual(result["user_acceptance"], "NOT_GRANTED_BY_SCRIPT")

    def test_source_snapshot_mismatch_blocks(self):
        state = self.state()
        data = json.loads((self.root / "snapshot.json").read_text(encoding='utf-8-sig'))
        data["locked_scripts"]["P001"] = {"event_text": "rewritten"}
        state["source_snapshot"] = self.f.write("snapshot.json", data)
        state["gates"]["visual_basis"] = self.approve([state["source_script"], state["source_snapshot"], state["visual_basis"]])
        self.assertIn("原文", " ".join(evaluate(state, self.root)["errors"]))

    def test_scoped_order_does_not_renumber_panel(self):
        gate = Gate(self.root, expected_panel_ids=["P014"])
        gate.panel_order([{"panel_id": "P014"}], "fixture")
        self.assertEqual(gate.errors, [])
        gate.panel_order([{"panel_id": "P001"}], "fixture")
        self.assertTrue(gate.errors)

    def real_input(self):
        # All artifacts below are synthetic in a TemporaryDirectory; no real
        # image generation or production acceptance takes place in this test.
        from PIL import Image
        from identity_confirmation import execution_block
        from repair_prompt_package import camera_block, content_block
        proof = self.f.write("identity-proof.json", {"SYNTHETIC": True})
        def confirmation(subject, facets, state=None):
            scope = {"book_id": "UNIT", "subject_id": subject, "episode_ids": ["E000"], "panel_ids": ["P001"]}
            if state:
                scope["state_id"] = state
            return {"status": "CONFIRMED", "scope": scope, "facets": facets, "evidence": [proof]}
        exemption = {"status": "ONE_OFF_ASSET_EXEMPT", "appearance_count": 1, "book_id": "UNIT", "episode_id": "E000", "panel_ids": ["P001"], "basis": "SYNTHETIC one panel"}
        registry = {"book_id": "UNIT", "characters": {"A": {"canonical_name": "测试甲", "name_kind": "approved_role_name", "relationships": [], "confirmation": confirmation("A", ["identity"])}},
            "appearance_states": {"AP": {"character_id": "A", "description": "蓝衣", "confirmation": confirmation("A", ["appearance"], "AP")}},
            "scene_states": {"SS": {"scene_id": "S", "canonical_name": "测试房间", "ownership_context": "SYNTHETIC", "description": "窗与桌", "confirmation": confirmation("S", ["scene_identity", "scene_state"], "SS")}},
            "assets": {}, "issues": []}
        self.manifest.update(identity_policy="identity_confirmation_v1", book_id="UNIT", episode_id="E000", identity_registry=registry, framing_policy="information_first_v1", schema="vertical-comic-prompt-package-v1")
        self.panel.update(script_character_labels=["测试甲"], character_bindings=[{"source_label": "测试甲", "canonical_name": "测试甲", "character_id": "A", "on_screen": True, "appearance_state_id": "AP", "asset_exemption": exemption}],
            scene_binding={"scene_id": "S", "scene_state_id": "SS", "background_visible": True, "asset_exemption": exemption},
            script_shot_id="E000-S001", station_id="ST001", station_state_id="ST001", camera_position={"x": 1, "y": 2, "z": 1.6}, facing_direction="朝向桌边人物", camera_height="eye_level",
            camera_angle_family="three_quarter_left", shot_scale="medium_close", visible_region="画面左胸以上与手势，背景窗", view_check="PASS", camera_execution_status="EXPLICIT_AND_PROVEN",
            script_lock_check="PASS", locked_script={"dialogue": "", "inner_voice": "", "narration": "", "sfx_text": "", "event_text": "测试甲在桌边抬手。"}, visual_analysis={},
            characters_visible=[{"character_id": "A", "name": "测试甲", "screen_position": "画面左", "depth_order": "中景", "body_orientation_and_visible_face": "朝右露左侧脸", "head_orientation_and_gaze": "看向手", "expression": "平静", "action": "抬手", "contact_occlusion": "桌沿遮下身"}],
            occlusion_relations="桌沿遮下身", background_anchors_visible=["后方窗"], hold_reasons=[])
        self.panel["framing"].update(focus="抬手", focus_subjects=["A"], crop_reason="胸以上和手势足够")
        self.panel["camera_execution_block"] = camera_block(self.panel, self.panel, None, None)
        self.panel["content_execution_block"] = content_block(self.panel, self.panel)
        self.panel["identity_execution_block"] = execution_block(self.panel, registry)
        self.panel["prompt"] = "\n\n".join(self.panel[k] for k in ("camera_execution_block", "content_execution_block", "identity_execution_block", "reference_usage_block", "style_execution_block", "negative_prompt"))
        (self.root / "P001/prompt.txt").write_text(self.panel["prompt"], encoding='utf-8', newline='\n')
        self.f.write("P001/提示词.json", self.panel)
        state = self.state(1)
        # The canonical shot includes the registry, while per-panel design is
        # exactly the same in the selected execution snapshot.
        shot_data = {**self.manifest, "panels": self.shots}
        state["shot_manifest"] = self.f.write("shots.json", shot_data)
        state["gates"]["shot_design"] = self.approve([state["visual_basis"], state["shot_manifest"]])
        record = state["panels"][0]
        record["package_manifest"] = self.f.write("全话提示词索引.json", self.manifest)
        record["shot_subset"] = self.f.write("shot-subset.json", shot_data)
        return state

    def test_real_gates_from_preflight_through_final_record(self):
        from PIL import Image
        state = self.real_input()
        record = state["panels"][0]
        result = evaluate(state, self.root, "generate", "P001")
        self.assertEqual(result["next_action"], "READY_FOR_CURRENT_PANEL", result)
        _, plan = validate_panel(self.panel, self.root)
        output = self.root / "synthetic-output.png"
        Image.new("RGB", (90, 160), "white").save(output)
        req = {"attempt_id": "UNIT_ONLY", "backend_id": "codex_builtin_imagegen", "panel_id": "P001", **plan, "source_kind": "observed_tool_call", "source_locator": "synthetic-unittest://not-real"}
        res = {"attempt_id": "UNIT_ONLY", "status": "COMPLETED", "outputs": [{"path": output.name, "sha256": digest(output)}], "source_kind": "observed_tool_result", "source_locator": "synthetic-unittest://not-real"}
        self.panel["generation_execution"] = {"status": "COMPLETED", "attempt_id": "UNIT_ONLY", "request_evidence": self.f.write("request.json", req), "response_evidence": self.f.write("response.json", res)}
        report, qa_dir = self.f.qa_report()
        self.assertEqual(report["errors"], [])
        item = report["panels"][0]
        for r in [*item["dimension_review"].values(), item["style_review"]]:
            r.update(status="PASS", reviewer="UNIT_ONLY", evidence="SYNTHETIC review fixture, not real acceptance")
        for field in ("camera_match", "shot_scale_match", "background_view_match", "body_crop_match", "required_visible_information_preserved", "no_extra_offscreen_characters"):
            item[field] = True
        record.update(status="VISUAL_PASS", package_manifest={"path": "全话提示词索引.json", "sha256": digest(self.root / "全话提示词索引.json")},
            qa_report=self.f.write("reviewed-qa.json", report), output={"path": output.name, "sha256": digest(output)})
        artifacts = [state["visual_basis"], state["shot_manifest"], record["output"]]
        state["gates"]["pilot"] = self.approve(artifacts)
        state["gates"]["final"] = self.approve(artifacts)
        result = evaluate(state, self.root, "deliver")
        self.assertEqual(result["next_action"], "READY_TO_PACKAGE", result)
        Image.new("RGB", (90, 160), "red").save(output)
        self.assertEqual(evaluate(state, self.root, "deliver")["status"], "HOLD")


if __name__ == "__main__":
    unittest.main()
