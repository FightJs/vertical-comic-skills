"""Isolated protocol fixtures, never production approvals or generation logs."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from codex_reference_contract import (BACKEND, POLICY, copy_contract_evidence, digest,
    final_prompt, invalidate_execution, validate_panel)
from check_control_inputs import validate_manifest
from continuity_contract import reference_usage_block
from legacy_spatial_cleanup import migrate_panel, is_retired_reference
from identity_confirmation import execution_block as identity_block
from validate_preproduction import Gate


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.refs = []
        for alias, name in (("@COMP_P001", "composition"), ("@SCENE", "scene"), ("@A", "character")):
            path = self.root / "P001" / "参考图" / f"{name}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (90, 160), {"composition": "grey", "scene": "white", "character": "blue"}[name]).save(path)
            self.refs.append({"alias": alias, "path": str(path.relative_to(self.root)), "sha256": digest(path), "role": "camera_composition" if name == "composition" else name, "version": "UNIT_FIXTURE_ONLY", "subject_ids": ["A"] if name == "character" else [], "subject_states": {"A": {"identity": "ID_A", "costume": "D_A"}} if name == "character" else {}})
        def binding(alias, purpose, targets, allowed):
            return {"alias": alias, "purpose": purpose, "subject_ids": targets, "allowed_transfer": allowed, "forbidden_transfer": ["unrelated_content"]}
        bindings = [binding("@COMP_P001", "framing", ["P001"], ["composition", "crop"]), binding("@SCENE", "scene_view", ["S"], ["geometry", "materials", "lighting"]), binding("@A", "identity", ["A"], ["face", "hair"]), binding("@A", "costume_state", ["A"], ["clothing"])]
        required = ["A上半身", "必要手势"]
        qa = {key: {"applicability": "REQUIRED", "criterion": "UNIT_FIXTURE: inspect actual output", "subject_ids": targets} for key, targets in (("identity", ["A"]), ("costume", ["A"]), ("action_interaction", ["A"]), ("background_space", ["S"]), ("framing", ["P001"]))}
        self.panel = {"panel_id": "P001", "scene_id": "S", "camera_view_id": "CAM1", "camera_view_signature": "TEST left camera chest-up", "frame_ratio": "9:16", "framing": {"body_crop": "chest_up", "required_visible": required, "background_level": "anchor_only"}, "characters_visible": [{"character_id": "A"}], "continuity_contract": {"subjects": {"A": {"identity_state": "ID_A", "costume_state": "D_A", "screen_region": "画面左", "identity_visible": True, "costume_visible": True}}, "required_visible": required, "offscreen_entities": [], "invariants": {"A.identity": "ID_A", "A.costume": "D_A"}, "allowed_changes": {}, "scene": {"scene_id": "S", "mode": "new_scene", "basis": "UNIT_FIXTURE_ONLY"}, "qa_requirements": qa}, "reference_images": self.refs, "reference_bindings": bindings, "control_inputs": [], "ratio_tolerance": 0, "transparent_background": False, "negative_prompt": "禁止多余人物", "generation_execution": {"status": "NOT_RUN"}}
        review = {k: self.panel[k] for k in ("panel_id", "camera_view_id", "camera_view_signature", "frame_ratio", "framing")}
        review.update({"status": "REVIEWED", "reviewer": "UNIT_FIXTURE_NOT_USER_APPROVAL", "evidence": "synthetic schema fixture only", "clean_camera_view": True, "reference_sha256": self.refs[0]["sha256"]})
        self.panel["composition_reference"] = {"mode": "REUSE", "reason": "synthetic protocol fixture", "alias": "@COMP_P001", "review_evidence": self.write("P001/review.json", review)}
        self.panel["reference_usage_block"] = reference_usage_block(bindings, self.refs)
        self.panel["prompt"] = final_prompt("测试构图\n" + self.panel["reference_usage_block"], self.panel["negative_prompt"])
        (self.root / "P001/prompt.txt").write_text(self.panel["prompt"])
        self.manifest = {"control_policy": "structural_guidance_v1", "continuity_policy": "reference_continuity_v1", "reference_input_policy": POLICY, "generation_backend": {"backend_id": BACKEND, "mode": "reference_guided", "structural_controls": [], "evidence": self.write("capability.json", {"source": "SYNTHETIC_PROTOCOL_FIXTURE_ONLY"})}, "panels": [self.panel]}

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        return {"path": name, "sha256": digest(path)}

    def report(self):
        return validate_manifest(self.manifest, self.root)

    def hold(self, substring):
        report = self.report()
        self.assertEqual(report["status"], "HOLD")
        self.assertIn(substring, "\n".join(report["errors"]))

    def test_valid_reference_route(self):
        report = self.report()
        self.assertEqual(report["status"], "PASS", report["errors"])
        self.assertFalse(report["structural_control_executed"])
        self.assertEqual(report["image_acceptance"], "NOT_ASSESSED")

    def add_detail_reference(self, index, *, same_path=False):
        ref=copy.deepcopy(self.refs[2]);ref['alias']=f'@DETAIL_{index}'
        if not same_path:
            target=self.root/'P001/参考图'/f'detail-{index}.png'
            target.write_bytes((self.root/ref['path']).read_bytes())
            ref['path']=str(target.relative_to(self.root));ref['sha256']=digest(target)
        self.refs.append(ref)
        self.panel['reference_bindings'].append({'alias':ref['alias'],'purpose':'pose_interaction','subject_ids':['A'],'allowed_transfer':['pose'],'forbidden_transfer':['identity','clothing']})
        self.panel['reference_usage_block']=reference_usage_block(self.panel['reference_bindings'],self.refs)
        self.panel['prompt']=final_prompt(self.panel['reference_usage_block'],self.panel['negative_prompt'])
        (self.root/'P001/prompt.txt').write_text(self.panel['prompt'])

    def test_exactly_five_paths_can_be_exported(self):
        self.add_detail_reference(1);self.add_detail_reference(2)
        errors,plan=validate_panel(self.panel,self.root)
        self.assertEqual(errors,[]);self.assertEqual(len(plan['arguments']['referenced_image_paths']),5)

    def test_six_paths_hold_before_tool_plan_is_exported(self):
        for i in (1,2,3):self.add_detail_reference(i)
        errors,plan=validate_panel(self.panel,self.root)
        self.assertIsNone(plan);self.assertIn('REFERENCE_LIMIT_HOLD','\n'.join(errors))

    def test_same_file_multiple_aliases_require_compilation_merge(self):
        self.add_detail_reference(1,same_path=True)
        self.hold('REFERENCE_DUPLICATE_HOLD')

    def test_same_alias_multiple_purposes_use_only_one_path(self):
        errors,plan=validate_panel(self.panel,self.root)
        self.assertEqual(errors,[]);self.assertEqual(len(plan['arguments']['referenced_image_paths']),3)
        self.assertEqual(len([b for b in self.panel['reference_bindings'] if b['alias']=='@A']),2)

    def test_historical_six_path_execution_is_audited_but_cannot_be_resubmitted(self):
        for i in (1,2,3):self.add_detail_reference(i)
        errors,plan=validate_panel(self.panel,self.root,enforce_input_budget=False)
        self.assertEqual(errors,[])
        request={'attempt_id':'HISTORICAL_TEST','backend_id':BACKEND,'panel_id':'P001',**plan,'source_kind':'observed_tool_call','source_locator':'synthetic://historical'}
        response={'attempt_id':'HISTORICAL_TEST','status':'COMPLETED','outputs':[self.refs[0]],'source_kind':'observed_tool_result','source_locator':'synthetic://historical'}
        self.panel['generation_execution']={'status':'COMPLETED','attempt_id':'HISTORICAL_TEST','request_evidence':self.write('old-request.json',request),'response_evidence':self.write('old-response.json',response)}
        report=validate_manifest(self.manifest,self.root,phase='execution')
        self.assertEqual(report['status'],'PASS',report['errors'])
        self.hold('REFERENCE_LIMIT_HOLD')

    def test_missing_real_image_is_hold(self):
        (self.root / self.refs[0]["path"]).unlink()
        self.hold("文件缺失")

    def test_alias_only_is_not_image_input(self):
        self.panel["reference_images"] = []
        self.hold("没有实际图片")

    def test_changed_image_hash_is_hold(self):
        Image.new("RGB", (90, 160), "red").save(self.root / self.refs[0]["path"])
        self.hold("SHA256")

    def test_wrong_character_owner_is_hold(self):
        self.refs[2]["subject_ids"] = ["B"]
        self.hold("角色归属")

    def test_wrong_costume_state_is_hold(self):
        self.refs[2]["subject_states"]["A"]["costume"] = "wrong"
        self.hold("状态与本格合同不一致")

    def test_wrong_camera_review_is_hold(self):
        evidence = self.panel["composition_reference"]["review_evidence"]
        review = json.loads((self.root / evidence["path"]).read_text())
        review["camera_view_id"] = "CAM_WRONG"
        self.panel["composition_reference"]["review_evidence"] = self.write(evidence["path"], review)
        self.hold("批准机位/裁切/比例")

    def test_wrong_crop_review_is_hold(self):
        self.panel["framing"]["body_crop"] = "full_body"
        self.hold("批准机位/裁切/比例")

    def test_wrong_composition_pixel_ratio_is_hold(self):
        path = self.root / self.refs[0]["path"]
        Image.new("RGB", (90, 150), "grey").save(path)
        self.refs[0]["sha256"] = digest(path)
        evidence = self.panel["composition_reference"]["review_evidence"]
        review = json.loads((self.root / evidence["path"]).read_text())
        review["reference_sha256"] = digest(path)
        self.panel["composition_reference"]["review_evidence"] = self.write(evidence["path"], review)
        self.hold("实际比例")

    def test_annotated_station_is_not_camera_reference(self):
        self.refs[0]["contains_annotations"] = True
        self.hold("supporting_documents")

    def test_text_screenshot_review_cannot_claim_clean_view(self):
        evidence = self.panel["composition_reference"]["review_evidence"]
        review = json.loads((self.root / evidence["path"]).read_text())
        review["clean_camera_view"] = False
        self.panel["composition_reference"]["review_evidence"] = self.write(evidence["path"], review)
        self.hold("干净的摄影机视角")

    def use_no_composition_reference(self):
        self.panel["composition_reference"] = {"mode": "NOT_REQUIRED", "reason": "simple shot covered by existing approved basis in unit fixture"}
        self.panel["reference_images"] = self.refs[1:]
        self.panel["reference_bindings"] = [b for b in self.panel["reference_bindings"] if b["alias"] != "@COMP_P001"]
        self.panel["reference_usage_block"] = reference_usage_block(self.panel["reference_bindings"], self.panel["reference_images"])
        self.panel["prompt"] = final_prompt(self.panel["reference_usage_block"], self.panel["negative_prompt"])
        (self.root / "P001/prompt.txt").write_text(self.panel["prompt"])

    def test_optional_composition_can_reuse_sufficient_basis(self):
        self.use_no_composition_reference()
        self.assertEqual(self.report()["status"], "PASS")

    def qa_report(self):
        self.write("全话提示词索引.json", self.manifest)
        images = self.root / "returned_unit_fixture"
        images.mkdir()
        Image.new("RGB", (90, 160), "white").save(images / "P001.png")
        output = self.root / "qa_unit_fixture"
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "make_generation_qa.py"),
             "--package", str(self.root), "--images", str(images), "--output", str(output)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads((output / "生成图QA报告.json").read_text()), output

    def test_no_optional_images_needs_no_review_files_or_qa_comparison(self):
        self.use_no_composition_reference()
        (self.root / self.refs[0]["path"]).unlink()
        (self.root / "P001/review.json").unlink()
        self.assertEqual(self.report()["status"], "PASS")
        report, output = self.qa_report()
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["status"], "HOLD_UNREVIEWED")
        panel = report["panels"][0]
        self.assertEqual(panel["composition_match"], "NOT_APPLICABLE")
        self.assertEqual(panel["composition_review_basis"], "APPROVED_SHOT_SPATIAL_RECORDS_AND_ASSETS")
        self.assertNotIn("composition_comparison", panel)
        self.assertFalse(list(output.glob("*构图与返回图对照.jpg")))
        self.assertEqual(panel["dimension_review"]["framing"]["status"], "UNREVIEWED")
        self.assertIsNone(panel["camera_match"])
        self.assertIsNone(panel["body_crop_match"])

    def test_optional_images_do_not_resolve_real_spatial_hold(self):
        self.use_no_composition_reference()
        self.panel["view_check"] = "CAMERA_HOLD"
        self.panel["hold_reasons"] = ["HOLD_NOT_YET_SPATIALLY_PROVEN"]
        gate = Gate(self.root)
        gate.check_prompt_conflicts(self.panel, "P001")
        self.assertTrue(any("hold_reasons" in error for error in gate.errors))
        self.assertTrue(any("空间视角未通过" in error for error in gate.errors))

    def test_reused_composition_still_gets_qa_comparison(self):
        before = {ref["path"]: digest(self.root / ref["path"]) for ref in self.refs}
        report, output = self.qa_report()
        self.assertEqual(report["errors"], [])
        panel = report["panels"][0]
        self.assertIsNone(panel["composition_match"])
        self.assertEqual(panel["composition_review_basis"], "COMPOSITION_REFERENCE")
        self.assertTrue((output / panel["composition_comparison"]).is_file())
        self.assertEqual(before, {ref["path"]: digest(self.root / ref["path"]) for ref in self.refs})

    def test_required_composition_cannot_be_skipped_in_qa(self):
        self.panel["composition_required"] = True
        self.panel["composition_reference"] = {"mode": "NOT_REQUIRED", "reason": "unsupported exemption"}
        report, _ = self.qa_report()
        self.assertTrue(any("不能豁免" in error for error in report["errors"]))
        self.assertIsNone(report["panels"][0]["composition_match"])

    def test_legacy_package_is_not_assessed_as_new_route(self):
        report = validate_manifest({"panels": [{"panel_id": "P001"}]}, self.root)
        self.assertEqual(report["status"], "LEGACY_NOT_ASSESSED")

    def test_external_reference_route_remains_compatible(self):
        manifest = {"control_policy": "structural_guidance_v1", "generation_backend": {"backend_id": "other_backend", "mode": "reference_guided", "structural_controls": [], "evidence": self.manifest["generation_backend"]["evidence"]}, "panels": [{"panel_id": "P001", "control_inputs": []}]}
        self.assertEqual(validate_manifest(manifest, self.root)["status"], "PASS")

    def test_policy_cannot_be_deleted_to_bypass_backend(self):
        self.manifest.pop("control_policy")
        self.hold("不能删策略")

    def test_required_composition_cannot_be_exempted(self):
        self.panel["composition_required"] = True
        self.panel["composition_reference"] = {"mode": "NOT_REQUIRED", "reason": "unsupported exemption"}
        self.hold("不能豁免")

    def test_no_unsupported_structural_capability(self):
        self.manifest["generation_backend"]["mode"] = "structural_control"
        self.hold("Codex须使用reference_guided")

    def test_negative_constraints_must_reach_prompt(self):
        self.panel["prompt"] = "missing avoid block"
        (self.root / "P001/prompt.txt").write_text(self.panel["prompt"])
        self.hold("负向约束")

    def test_numbered_reference_roles_match_input_order(self):
        self.assertIn("参考图3 @A：身份", self.panel["prompt"])
        self.assertIn("参考图3 @A：服装", self.panel["prompt"])
        self.panel["reference_images"] = list(reversed(self.refs))
        self.hold("须编译进")

    def test_missing_execution_logs_cannot_claim_completed(self):
        self.panel["generation_execution"] = {"status": "COMPLETED"}
        self.hold("执行证据")

    def execution_fixture(self):
        _, plan = validate_panel(self.panel, self.root)
        request = {"attempt_id": "LOCAL_UNIT_FIXTURE", "backend_id": BACKEND, "panel_id": "P001", **plan, "source_kind": "observed_tool_call", "source_locator": "synthetic-unittest://not-a-real-call"}
        response = {"attempt_id": "LOCAL_UNIT_FIXTURE", "status": "COMPLETED", "outputs": [self.refs[0]], "source_kind": "observed_tool_result", "source_locator": "synthetic-unittest://not-a-real-result"}
        self.panel["generation_execution"] = {"status": "COMPLETED", "attempt_id": "LOCAL_UNIT_FIXTURE", "request_evidence": self.write("request.json", request), "response_evidence": self.write("response.json", response)}
        return request

    def test_local_attempt_links_records_without_service_request_id(self):
        self.execution_fixture()
        self.assertEqual(self.report()["status"], "PASS")
        self.assertFalse(self.report()["structural_control_executed"])

    def test_execution_cannot_omit_actual_reference_paths(self):
        request = self.execution_fixture()
        request["arguments"].pop("referenced_image_paths")
        self.panel["generation_execution"]["request_evidence"] = self.write("request.json", request)
        self.hold("实际工具调用")

    def test_execution_rejects_unsupported_weight_argument(self):
        request = self.execution_fixture()
        request["arguments"]["reference_weight"] = 1
        self.panel["generation_execution"]["request_evidence"] = self.write("request.json", request)
        self.hold("实际工具调用")

    def test_changed_reference_bytes_invalidate_old_execution_even_at_same_path(self):
        self.execution_fixture()
        path = self.root / self.refs[2]["path"]
        Image.new("RGB", (90, 160), "green").save(path)
        self.refs[2]["sha256"] = digest(path)
        self.hold("实际工具调用")

    def test_plan_is_not_observed_execution(self):
        request = self.execution_fixture()
        request["source_kind"] = "planned_submission"
        self.panel["generation_execution"]["request_evidence"] = self.write("request.json", request)
        self.hold("计划不能充当执行证据")

    def test_repair_invalidates_old_execution(self):
        self.execution_fixture()
        old = copy.deepcopy(self.panel["generation_execution"])
        invalidate_execution(self.panel)
        self.assertEqual(self.panel["generation_execution"]["status"], "NOT_RUN")
        self.assertEqual(self.panel["generation_execution_history"], [old])

    def test_new_composition_survives_legacy_cleanup(self):
        self.assertFalse(is_retired_reference(self.refs[0]))
        new, _ = migrate_panel(self.panel)
        self.assertEqual(new["composition_reference"], self.panel["composition_reference"])
        self.assertEqual(new["reference_images"], self.refs)
        self.assertEqual(new["reference_usage_block"], self.panel["reference_usage_block"])
        self.assertEqual(new["prompt"], self.panel["prompt"])

    def test_legacy_card_is_still_retired(self):
        old = {"alias": "@VIEW_E011_P001", "role": "camera_visible", "path": "old.png"}
        migrated, _ = migrate_panel({"reference_images": [old, self.refs[0]], "locked_script": {"dialogue": "unchanged"}})
        self.assertEqual(migrated["reference_images"], [self.refs[0]])
        self.assertEqual(migrated["locked_script"]["dialogue"], "unchanged")

    def test_cleanup_renumbers_roles_when_a_legacy_input_is_removed(self):
        panel = copy.deepcopy(self.panel)
        old = {"alias": "@VIEW_E011_P001", "role": "camera_visible", "path": "old.png"}
        old_binding = {"alias": old["alias"], "purpose": "framing", "subject_ids": ["P001"], "allowed_transfer": ["composition"], "forbidden_transfer": ["identity"]}
        panel["reference_images"].insert(0, old)
        panel["reference_bindings"].insert(0, old_binding)
        panel["reference_usage_block"] = reference_usage_block(panel["reference_bindings"], panel["reference_images"])
        panel["prompt"] = final_prompt(panel["reference_usage_block"], panel["negative_prompt"])
        cleaned, _ = migrate_panel(panel)
        expected = reference_usage_block(cleaned["reference_bindings"], cleaned["reference_images"])
        self.assertEqual(cleaned["reference_usage_block"], expected)
        self.assertIn(expected, cleaned["prompt"])
        self.assertNotIn(old["alias"], cleaned["prompt"])

    def test_repair_copies_review_and_capability_evidence(self):
        output = self.root / "repair"
        self.assertEqual(copy_contract_evidence(self.root, output, self.manifest), [])
        for evidence in (self.manifest["generation_backend"]["evidence"], self.panel["composition_reference"]["review_evidence"]):
            self.assertEqual(digest(output / evidence["path"]), evidence["sha256"])

    def test_export_cli_emits_only_plan_and_supported_arguments(self):
        self.write("全话提示词索引.json", self.manifest)
        output = self.root / "plan.json"
        result = subprocess.run([sys.executable, str(SCRIPTS / "codex_reference_contract.py"), "--package-root", str(self.root), "--output", str(output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(output.read_text())["plans"][0]
        self.assertEqual(plan["status"], "NOT_RUN")
        self.assertEqual(set(plan["arguments"]), {"prompt", "referenced_image_paths", "transparent_background"})
        self.assertTrue(all(Path(p).is_absolute() for p in plan["arguments"]["referenced_image_paths"]))

    def test_initializer_keeps_unverified_backend_on_hold(self):
        output = self.root / "initialized"
        result = subprocess.run([sys.executable, str(SCRIPTS / "init_preproduction.py"), "--output", str(output), "--book", "UNIT_ONLY", "--episode", "E000", "--backend", BACKEND], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((output / "04_B提示词包_CANDIDATE/全话提示词索引.json").read_text())
        self.assertEqual(manifest["status"], "PROMPT_PACKAGE_HOLD")
        self.assertEqual(validate_manifest(manifest, output)["status"], "HOLD")

    def test_qa_exact_ratio_and_unreviewed_dimensions(self):
        self.write("全话提示词索引.json", self.manifest)
        images = self.root / "returned"; images.mkdir()
        # Synthetic unit image is not a returned generation or acceptance.
        Image.new("RGB", (90, 159), "white").save(images / "P001.png")
        output = self.root / "qa"
        result = subprocess.run([sys.executable, str(SCRIPTS / "make_generation_qa.py"), "--package", str(self.root), "--images", str(images), "--output", str(output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((output / "生成图QA报告.json").read_text())
        item = report["panels"][0]
        self.assertEqual(item["ratio_check"], "FAIL")
        self.assertEqual(report["status"], "HOLD_UNREVIEWED")
        self.assertTrue(all(d["status"] == "UNREVIEWED" for d in item["dimension_review"].values()))
        self.assertTrue((output / item["composition_comparison"]).is_file())
        baseline = os.environ.get("COMIC_SKILL_BASELINE")
        if baseline:
            before = self.root / "qa_before"
            result = subprocess.run([sys.executable, str(Path(baseline) / "scripts/make_generation_qa.py"), "--package", str(self.root), "--images", str(images), "--output", str(before)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            previous = json.loads((before / "生成图QA报告.json").read_text())
            self.assertEqual(previous["panels"][0]["ratio_check"], "PASS")
            destination = os.environ.get("COMIC_VERIFICATION_OUTPUT")
            if destination:
                Path(destination, "比例验收前后对比.json").write_text(json.dumps({"fixture_kind": "SYNTHETIC_NOT_GENERATED_IMAGE", "expected_ratio": "9:16", "actual_pixels": [90, 159], "before_fixed_tolerance": 0.05, "before_ratio_check": "PASS", "after_requested_tolerance": 0, "after_ratio_check": item["ratio_check"], "both_image_acceptance": "UNREVIEWED"}, ensure_ascii=False, indent=2))

    def test_both_repair_clis_keep_new_reference_and_reset_execution(self):
        # Confirmed fields here are synthetic protocol fixtures, never actual
        # user approval of a character, camera, scene or production panel.
        proof = self.write("fixture_confirmation.json", {"purpose": "SYNTHETIC_UNIT_TEST_NOT_USER_APPROVAL"})
        book, episode = "UNIT_TEST_ONLY", "E000"
        def confirmation(subject, facets, state=None):
            scope = {"book_id": book, "subject_id": subject, "episode_ids": [episode], "panel_ids": ["P001"]}
            if state:
                scope["state_id"] = state
            return {"status": "CONFIRMED", "scope": scope, "facets": facets, "evidence": [proof]}
        exemption = {"status": "ONE_OFF_ASSET_EXEMPT", "appearance_count": 1, "book_id": book, "episode_id": episode, "panel_ids": ["P001"], "basis": "synthetic one-panel fixture"}
        registry = {"book_id": book, "characters": {"A": {"canonical_name": "测试甲", "name_kind": "approved_role_name", "relationships": [], "confirmation": confirmation("A", ["identity"])}}, "appearance_states": {"AP": {"character_id": "A", "description": "蓝衣测试人物", "confirmation": confirmation("A", ["appearance"], "AP")}}, "scene_states": {"SS": {"scene_id": "S", "canonical_name": "测试房间", "ownership_context": "synthetic test", "description": "固定窗与桌", "confirmation": confirmation("S", ["scene_identity", "scene_state"], "SS")}}, "assets": {}, "issues": []}
        self.manifest.update({"identity_policy": "identity_confirmation_v1", "book_id": book, "episode_id": episode, "identity_registry": registry, "schema": "vertical-comic-prompt-package-v1", "framing_policy": "information_first_v1"})
        self.panel.update({"script_character_labels": ["测试甲"], "character_bindings": [{"source_label": "测试甲", "canonical_name": "测试甲", "character_id": "A", "on_screen": True, "appearance_state_id": "AP", "asset_exemption": exemption}], "scene_binding": {"scene_id": "S", "scene_state_id": "SS", "background_visible": True, "asset_exemption": exemption}, "script_shot_id": "E000-S001", "station_id": "ST001", "station_state_id": "ST001", "camera_position": {"x": 1, "y": 2, "z": 1.6}, "facing_direction": "朝向桌边人物", "camera_height": "eye_level", "camera_angle_family": "three_quarter_left", "shot_scale": "medium_close", "visible_region": "画面左测试甲胸以上，手在桌边，背景窗", "view_check": "PASS", "camera_execution_status": "EXPLICIT_AND_PROVEN", "script_lock_check": "PASS", "locked_script": {"dialogue": "", "inner_voice": "", "narration": "", "sfx_text": "", "event_text": "测试甲在桌边抬手。"}, "visual_analysis": {}, "characters_visible": [{"character_id": "A", "name": "测试甲", "screen_position": "画面左", "depth_order": "中景", "body_orientation_and_visible_face": "面向桌右，露左侧脸", "head_orientation_and_gaze": "看向手", "expression": "平静", "action": "抬手", "contact_occlusion": "桌沿遮下身"}], "occlusion_relations": "桌沿遮下身", "background_anchors_visible": ["后方窗"], "hold_reasons": []})
        self.panel["framing"].update({"focus": "抬手", "focus_subjects": ["A"], "crop_reason": "手势与胸以上即可"})
        evidence = self.panel["composition_reference"]["review_evidence"]
        review = json.loads((self.root / evidence["path"]).read_text())
        review["framing"] = self.panel["framing"]
        self.panel["composition_reference"]["review_evidence"] = self.write(evidence["path"], review)
        self.panel["identity_execution_block"] = identity_block(self.panel, registry)
        self.panel["prompt"] += "\n\n" + self.panel["identity_execution_block"]
        (self.root / "P001/prompt.txt").write_text(self.panel["prompt"])
        self.execution_fixture()
        self.write("全话提示词索引.json", self.manifest)
        self.write("P001/提示词.json", self.panel)
        for script in ("repair_prompt_package.py", "repair_prompt_package_v2.py"):
            with self.subTest(script=script):
                output = self.root / script.removesuffix(".py")
                result = subprocess.run([sys.executable, str(SCRIPTS / script), "--source", str(self.root), "--identity-root", str(self.root), "--output", str(output)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                repaired = json.loads((output / "全话提示词索引.json").read_text())
                panel = repaired["panels"][0]
                self.assertEqual(panel["generation_execution"]["status"], "NOT_RUN")
                self.assertTrue(panel["generation_execution_history"])
                self.assertEqual(panel["composition_reference"], self.panel["composition_reference"])
                self.assertEqual(panel["locked_script"], self.panel["locked_script"])
                self.assertEqual(len(panel["reference_images"]), 3)
                report = validate_manifest(repaired, output)
                self.assertEqual(report["status"], "PASS", report["errors"])
                shot_path = output / repaired["sources"]["shot_manifest"]
                gate = Gate(self.root)
                full_report = gate.run(shot_path, output / "全话提示词索引.json")
                if script == "repair_prompt_package.py":
                    # The v1 repair rebuilds legacy prose and deliberately
                    # requires review of migrated style/content constraints.
                    self.assertTrue(any("LEGACY_PROMPT_REVIEW_HOLD" in h for h in panel["hold_reasons"]))
                    self.assertTrue(full_report["errors"])
                    self.assertTrue(all("未解除的hold_reasons" in e for e in full_report["errors"]), full_report["errors"])
                else:
                    self.assertFalse(full_report["errors"], full_report["errors"])
        baseline = os.environ.get("COMIC_SKILL_BASELINE")
        if baseline:
            before_records = []
            for script in ("repair_prompt_package.py", "repair_prompt_package_v2.py"):
                output = self.root / ("before_" + script.removesuffix(".py"))
                result = subprocess.run([sys.executable, str(Path(baseline) / "scripts" / script), "--source", str(self.root), "--identity-root", str(self.root), "--output", str(output)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                before = json.loads((output / "全话提示词索引.json").read_text())["panels"][0]
                self.assertEqual(before["generation_execution"]["status"], "COMPLETED")
                before_records.append({"script": script, "before_execution_status": "COMPLETED", "after_execution_status": "NOT_RUN", "before_review_evidence_copied": (output / before["composition_reference"]["review_evidence"]["path"]).exists(), "after_review_evidence_copied": True})
            destination = os.environ.get("COMIC_VERIFICATION_OUTPUT")
            if destination:
                Path(destination, "修复流程前后对比.json").write_text(json.dumps({"fixture_kind": "SYNTHETIC_NOT_REAL_APPROVAL_OR_EXECUTION", "records": before_records}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
