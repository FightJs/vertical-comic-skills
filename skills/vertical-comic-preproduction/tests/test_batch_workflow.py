"""Isolated batch-routing tests plus actual preflight/QA integration; no image calls."""
import copy
import json
from pathlib import Path
import sys
import shutil
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import test_staged_workflow as staged_fixtures
from batch_workflow import build_plan, dependency_basis, cross_episode_errors
from staged_workflow import evaluate
from codex_reference_contract import digest, validate_panel


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.h = staged_fixtures.StagedTests("test_actual_style_input_is_exported")
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.root, self.write = self.h.root, self.h.f.write

    def convert(self, state):
        state["execution_mode"] = "batch5_v1"
        state["batch_reviews"] = {}
        shots = json.loads((self.root / state["shot_manifest"]["path"]).read_text(encoding='utf-8-sig'))
        shots["execution_mode"] = "batch5_v1"
        for p in shots["panels"]:
            p.update(generation_dependencies=[], requires_state_review=False)
        self.h.shots = shots["panels"]
        state["shot_manifest"] = self.write("shots.json", shots)
        state["gates"]["shot_design"] = self.h.approve([state["visual_basis"], state["shot_manifest"]])
        state["batch_plan"] = self.write("batch-plan.json", build_plan(state, shots))
        return state

    def state(self, count=10):
        return self.convert(self.h.state(count))

    def replan(self, state):
        shots = {"execution_mode": "batch5_v1", "panels": self.h.shots}
        state["shot_manifest"] = self.write("shots.json", shots)
        state["gates"]["shot_design"] = self.h.approve([state["visual_basis"], state["shot_manifest"]])
        state["batch_plan"] = self.write("batch-plan.json", build_plan(state, shots))

    def completed(self, state, index):
        self.h.fake_completed_for_routing(state, index)
        record = state["panels"][index]
        record["package_manifest"] = self.write(f"routing_package{index}.json", {
            "execution_mode": "batch5_v1", "book_id": "UNIT", "episode_id": "E000", "panels": [self.h.shots[index]]})

    def reviewed(self, state, batch_index=0):
        plan = json.loads((self.root / "batch-plan.json").read_text(encoding='utf-8-sig'))
        batch = plan["batches"][batch_index]
        records = {r["panel_id"]: r for r in state["panels"]}
        prior = plan["batches"][batch_index-1]["panel_ids"] if batch_index else []
        report = {"policy": "batch_review_v1", "book_id": "UNIT", "episode_id": "E000", **batch,
                  "status": "PASS", "reviewer": "SYNTHETIC", "evidence": "SYNTHETIC ONLY",
                  "visual_basis": state["visual_basis"], "shot_manifest": state["shot_manifest"],
                  "outputs": [records[p]["output"] for p in batch["panel_ids"]],
                  "previous_outputs": [records[p]["output"] for p in prior]}
        state["batch_reviews"][batch["batch_id"]] = self.write(batch["batch_id"]+"-review.json", report)

    def pilot(self, state):
        state["gates"]["pilot"] = self.h.approve([state["visual_basis"], state["shot_manifest"], *[r["output"] for r in state["panels"][:5]]])

    def routed(self, state, check="status", pid=None):
        # These tests isolate scheduling. Full input and image QA run below.
        with patch("batch_workflow.input_errors", return_value=[]), patch("batch_workflow.qa_errors", return_value=[]):
            return evaluate(state, self.root, check, pid)

    def test_five_pending_panels_are_eligible_together(self):
        state = self.state()
        self.assertEqual(self.routed(state)["eligible_panel_ids"], [f"P{i:03d}" for i in range(1, 6)])
        self.assertEqual(self.routed(state, "generate", "P005")["status"], "PASS")

    def test_next_batch_cannot_launch_early(self):
        self.assertEqual(self.routed(self.state(), "generate", "P006")["next_action"], "SOURCE_BATCH_HOLD")

    def test_out_of_order_returns_do_not_change_source_batch(self):
        state = self.state()
        self.completed(state, 4)
        self.assertEqual(self.routed(state)["eligible_panel_ids"], ["P001", "P002", "P003", "P004"])

    def test_generated_and_inflight_panels_cannot_duplicate_calls(self):
        for status in ("GENERATED", "IN_FLIGHT"):
            state = self.state()
            state["panels"][0]["status"] = status
            self.assertEqual(self.routed(state, "generate", "P001")["next_action"], "DEPENDENCY_OR_RESULT_HOLD")
            self.assertEqual(self.routed(state, "generate", "P002")["status"], "PASS")

    def test_cancel_or_failure_blocks_new_siblings(self):
        for status in ("CANCELLED", "HOLD", "UNKNOWN"):
            state = self.state()
            state["panels"][0]["status"] = status
            self.assertEqual(self.routed(state, "generate", "P002")["next_action"], "RESOLVE_BATCH_HOLD")

    def test_single_repair_keeps_passed_siblings(self):
        state = self.state()
        for i in range(1, 5):
            self.completed(state, i)
        state["panels"][0]["status"] = "REPAIR_AUTHORIZED"
        self.assertEqual(self.routed(state)["eligible_panel_ids"], ["P001"])

    def test_all_individual_qa_does_not_replace_batch_review(self):
        state = self.state()
        for i in range(5):
            self.completed(state, i)
        self.assertEqual(self.routed(state, "generate", "P006")["next_action"], "REVIEW_BATCH")

    def test_first_five_require_actual_scoped_pilot_approval(self):
        state = self.state()
        for i in range(5):
            self.completed(state, i)
        self.reviewed(state)
        state["gates"]["pilot"] = self.h.approve([state["visual_basis"], state["shot_manifest"], *[r["output"] for r in state["panels"][:3]]])
        self.assertEqual(self.routed(state, "generate", "P006")["next_action"], "WAIT_PILOT_APPROVAL")
        self.pilot(state)
        self.assertEqual(self.routed(state, "generate", "P006")["status"], "PASS")

    def test_short_last_batch_and_no_unnecessary_human_batch_gate(self):
        state = self.state(12)
        plan = json.loads((self.root / "batch-plan.json").read_text(encoding='utf-8-sig'))
        self.assertEqual([len(b["panel_ids"]) for b in plan["batches"]], [5, 5, 2])
        for i in range(10):
            self.completed(state, i)
        self.reviewed(state, 0)
        self.reviewed(state, 1)
        self.pilot(state)
        self.assertEqual(self.routed(state, "generate", "P011")["status"], "PASS")

    def test_return_after_basis_change_is_blocked(self):
        state = self.state()
        (self.root / "basis.json").write_text("{}", encoding='utf-8', newline='\n')
        self.assertEqual(self.routed(state, "generate", "P001")["status"], "HOLD")

    def test_new_state_inside_pilot_gets_singleton_and_review(self):
        state = self.state()
        for p in self.h.shots[2:]:
            p["visual_state_keys"] += ["costume:NEW"]
        self.replan(state)
        plan = json.loads((self.root / "batch-plan.json").read_text(encoding='utf-8-sig'))
        self.assertEqual([b["panel_ids"] for b in plan["batches"][:3]], [["P001", "P002"], ["P003"], ["P004", "P005"]])
        for i in range(3):
            self.completed(state, i)
        self.reviewed(state, 0)
        self.reviewed(state, 1)
        self.assertEqual(self.routed(state, "generate", "P004")["next_action"], "WAIT_NEW_STATE_APPROVAL")
        state["state_reviews"]["P003"] = self.h.approve([state["visual_basis"], state["shot_manifest"], state["panels"][2]["output"]])
        self.assertEqual(self.routed(state, "generate", "P004")["status"], "PASS")

    def test_high_risk_anchor_splits_without_new_keys(self):
        state = self.state()
        self.h.shots[1]["requires_state_review"] = True
        self.replan(state)
        plan = json.loads((self.root / "batch-plan.json").read_text(encoding='utf-8-sig'))
        self.assertEqual(plan["batches"][1]["panel_ids"], ["P002"])

    def test_dependency_waits_for_real_predecessor_review(self):
        state = self.state()
        self.h.shots[1]["generation_dependencies"] = ["P001"]
        self.replan(state)
        self.assertEqual(self.routed(state, "generate", "P002")["next_action"], "DEPENDENCY_OR_RESULT_HOLD")
        self.completed(state, 0)
        self.assertEqual(self.routed(state, "generate", "P002")["status"], "PASS")

    def test_cycles_and_future_dependencies_are_rejected(self):
        state = self.state()
        self.h.shots[0]["generation_dependencies"] = ["P002"]
        with self.assertRaises(ValueError):
            self.replan(state)

    def test_edited_plan_cannot_pack_six_or_reorder(self):
        state = self.state()
        plan = json.loads((self.root / "batch-plan.json").read_text(encoding='utf-8-sig'))
        plan["batches"][0]["panel_ids"].append("P006")
        state["batch_plan"] = self.write("batch-plan.json", plan)
        self.assertEqual(self.routed(state)["next_action"], "REBUILD_BATCH_PLAN")

    def test_replacing_image_invalidates_batch_review(self):
        state = self.state()
        for i in range(5):
            self.completed(state, i)
        self.reviewed(state)
        state["panels"][2]["output"] = self.write("replacement.json", {"NEW": True})
        self.assertEqual(self.routed(state)["next_action"], "REVIEW_BATCH")

    def test_future_output_cannot_bypass_incomplete_batch(self):
        state = self.state()
        self.completed(state, 5)
        self.assertEqual(self.routed(state)["next_action"], "OUT_OF_BATCH_HOLD")

    def test_fake_pass_without_actual_qa_is_blocked(self):
        state = self.state()
        self.completed(state, 0)
        self.assertEqual(evaluate(state, self.root)["status"], "HOLD")

    def test_missing_mode_cannot_fall_back_to_legacy(self):
        state = self.state()
        del state["execution_mode"]
        self.assertEqual(evaluate(state, self.root)["next_action"], "EXECUTION_MODE_HOLD")

    def test_final_approval_still_required(self):
        state = self.state(2)
        for i in range(2):
            self.completed(state, i)
        self.reviewed(state)
        self.pilot(state)
        self.assertEqual(self.routed(state, "deliver")["next_action"], "WAIT_FINAL_APPROVAL")
        state["gates"]["final"] = self.h.approve([state["visual_basis"], state["shot_manifest"], *[r["output"] for r in state["panels"]]])
        self.assertEqual(self.routed(state, "deliver")["next_action"], "READY_TO_PACKAGE")

    def test_dependency_image_replacement_invalidates_bound_input(self):
        state = self.state(2)
        self.completed(state, 0)
        record = state["panels"][0]
        shot = {"generation_dependencies": ["P001"]}
        packet = {"dependency_outputs": {"P001": record["output"]}, "panels": [{
            "reference_images": [{"alias": "@PREV", **record["output"]}],
            "reference_bindings": [{"alias": "@PREV", "purpose": "pose_interaction"}]}]}
        basis = {"reference_files": []}
        dependency_basis(self.root, self.root / "package.json", packet, shot, basis, {"P001": record})
        packet["panels"][0]["reference_bindings"][0]["purpose"] = "style"
        with self.assertRaises(ValueError):
            dependency_basis(self.root, self.root / "package.json", packet, shot, basis, {"P001": record})
        packet["panels"][0]["reference_bindings"][0]["purpose"] = "pose_interaction"
        record["output"] = self.write("new-prev.json", {"NEW": True})
        with self.assertRaises(ValueError):
            dependency_basis(self.root, self.root / "package.json", packet, shot, basis, {"P001": record})

    def cross_fixture(self):
        # Report-binding fixture only; real image QA is separately tested below.
        state = self.state(1)
        self.completed(state, 0)
        state["panels"][0]["qa_report"] = self.write("qa.json", {"SYNTHETIC": True})
        state_name = "00_输入审计/生产流程.json"
        (self.root / "00_输入审计").mkdir(exist_ok=True)
        self.write(state_name, state)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        other_root = Path(temp.name) / "E001"
        shutil.copytree(self.root, other_root)
        other = copy.deepcopy(state)
        other["episode_id"] = "E001"
        (other_root / state_name).write_text(json.dumps(other), encoding='utf-8', newline='\n')
        jobs = [{"job_id": "J0", "episode_id": "E000", "root": str(self.root)},
                {"job_id": "J1", "episode_id": "E001", "root": str(other_root)}]
        for job in jobs:
            job["frozen_inputs"] = {k: state[k] for k in ("source_script", "source_snapshot", "visual_basis", "shot_manifest")}
        control = {"book_id": "UNIT", "epoch": 1, "shared_files": [], "jobs": jobs}
        report = {"policy": "cross_episode_review_v1", "book_id": "UNIT", "epoch": 1,
                  "shared_files": [], "status": "PASS", "reviewer": "SYNTHETIC", "evidence": "TEST ONLY", "episodes": []}
        for job in jobs:
            report["episodes"].append({"job_id": job["job_id"], "episode_id": job["episode_id"],
                "visual_basis": state["visual_basis"], "shot_manifest": state["shot_manifest"],
                "outputs": [state["panels"][0]["output"]], "qa_reports": [state["panels"][0]["qa_report"]]})
        control["cross_episode_review"] = self.write("cross-review.json", report)
        self.write("control.json", control)
        return {"control_file": str(self.root / "control.json")}, control, report, other_root

    def test_cross_episode_report_is_required_for_multi_episode_delivery(self):
        context, control, _, _ = self.cross_fixture()
        del control["cross_episode_review"]
        self.write("control.json", control)
        self.assertTrue(cross_episode_errors(context))

    def test_cross_episode_report_accepts_exact_current_images(self):
        context, _, _, _ = self.cross_fixture()
        with patch("batch_workflow.qa_errors", return_value=[]):
            self.assertEqual(cross_episode_errors(context), [])

    def test_cross_episode_failed_qa_is_not_overridden_by_report_pass(self):
        context, _, _, _ = self.cross_fixture()
        with patch("batch_workflow.qa_errors", return_value=["IMAGE_STYLE_HOLD"]):
            self.assertTrue(cross_episode_errors(context))

    def test_cross_episode_other_output_or_epoch_change_invalidates_report(self):
        context, control, _, other_root = self.cross_fixture()
        control["epoch"] = 2
        self.write("control.json", control)
        with patch("batch_workflow.qa_errors", return_value=[]):
            self.assertTrue(cross_episode_errors(context))
        control["epoch"] = 1
        self.write("control.json", control)
        state_path = other_root / "00_输入审计/生产流程.json"
        other = json.loads(state_path.read_text(encoding='utf-8-sig'))
        new_image = other_root / "changed-output.json"
        new_image.write_text('{"SYNTHETIC_CHANGED":true}', encoding='utf-8', newline='\n')
        other["panels"][0]["output"] = {"path": new_image.name, "sha256": digest(new_image)}
        state_path.write_text(json.dumps(other), encoding='utf-8', newline='\n')
        with patch("batch_workflow.qa_errors", return_value=[]):
            self.assertTrue(cross_episode_errors(context))
    def test_real_batch_preflight_through_qa_and_delivery(self):
        from PIL import Image
        state = self.convert(self.h.real_input())
        panel, manifest = self.h.panel, self.h.manifest
        panel.update(generation_dependencies=[], requires_state_review=False)
        manifest["execution_mode"] = "batch5_v1"
        self.write("P001/提示词.json", panel)
        record = state["panels"][0]
        shots = json.loads((self.root / "shots.json").read_text(encoding='utf-8-sig'))
        record["shot_subset"] = self.write("shot-subset.json", shots)
        context = {"control_file": str(self.root / "control.json"), "job_id": "UNIT-JOB", "worker_id": "UNIT-WORKER", "epoch": 1}
        state["parallel_context"] = context
        receipt = {"job_id": "UNIT-JOB", "worker_id": "UNIT-WORKER", "epoch": 1, "permit_id": "UNIT-PERMIT"}
        manifest["dispatch_receipt"] = receipt
        record["package_manifest"] = self.write("全话提示词索引.json", manifest)
        basis = json.loads((self.root / state["visual_basis"]["path"]).read_text(encoding='utf-8-sig'))
        style_ref = self.write("shared-style.json", {"book_id": "UNIT", "style": basis["style"]})
        registry_ref = self.write("shared-registry.json", manifest["identity_registry"])
        shared = [dict(style_ref, role="style_basis"), dict(registry_ref, role="state_registry"), panel["reference_images"][-1]]
        control = {"policy": "parallel_episodes_v1", "version": 1, "book_id": "UNIT", "epoch": 1,
                   "cancelled": False, "holds": [], "max_workers": 5, "max_inflight": 5, "shared_files": shared,
                   "jobs": [{"job_id": "UNIT-JOB", "episode_id": "E000", "worker_id": "UNIT-WORKER", "root": str(self.root),
                             "status": "RUNNING", "frozen_inputs": {k: state[k] for k in ("source_script", "source_snapshot", "visual_basis", "shot_manifest")}}],
                   "permits": [{**receipt, "panel_id": "P001", "status": "RESERVED"}]}
        (self.root / "00_输入审计").mkdir(exist_ok=True)
        self.write("00_输入审计/生产流程.json", state)
        self.write("control.json", control)
        self.assertEqual(evaluate(state, self.root, "generate", "P001")["next_action"], "READY_FOR_BATCH_PANEL")
        _, plan = validate_panel(panel, self.root)
        output = self.root / "synthetic-output.png"
        Image.new("RGB", (90, 160), "white").save(output)
        req = {"attempt_id": "UNIT_ONLY", "backend_id": "codex_builtin_imagegen", "panel_id": "P001", **plan,
               "source_kind": "observed_tool_call", "source_locator": "synthetic-unittest://not-real"}
        res = {"attempt_id": "UNIT_ONLY", "status": "COMPLETED", "outputs": [{"path": output.name, "sha256": digest(output)}],
               "source_kind": "observed_tool_result", "source_locator": "synthetic-unittest://not-real"}
        panel["generation_execution"] = {"status": "COMPLETED", "attempt_id": "UNIT_ONLY", "request_evidence": self.write("request.json", req), "response_evidence": self.write("response.json", res)}
        report, _ = self.h.f.qa_report()
        self.assertEqual(report["errors"], [])
        item = report["panels"][0]
        for r in [*item["dimension_review"].values(), item["style_review"]]:
            r.update(status="PASS", reviewer="SYNTHETIC", evidence="TEST ONLY")
        for key in ("camera_match", "shot_scale_match", "background_view_match", "body_crop_match", "required_visible_information_preserved", "no_extra_offscreen_characters"):
            item[key] = True
        record.update(status="VISUAL_PASS", package_manifest={"path": "全话提示词索引.json", "sha256": digest(self.root / "全话提示词索引.json")},
                      qa_report=self.write("qa-reviewed.json", report), output={"path": output.name, "sha256": digest(output)})
        control["permits"][0].update(status="COMPLETED", output_sha256=digest(output))
        self.write("control.json", control)
        self.write("00_输入审计/生产流程.json", state)
        self.assertEqual(evaluate(state, self.root)["next_action"], "REVIEW_BATCH")
        self.reviewed(state)
        self.pilot(state)
        state["gates"]["final"] = self.h.approve([state["visual_basis"], state["shot_manifest"], record["output"]])
        self.assertEqual(evaluate(state, self.root, "deliver")["next_action"], "READY_TO_PACKAGE")
        Image.new("RGB", (90, 160), "red").save(output)
        self.assertEqual(evaluate(state, self.root, "deliver")["status"], "HOLD")


if __name__ == "__main__":
    unittest.main()
