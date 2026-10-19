#!/usr/bin/env python3
"""Reference-purpose preflight and dimension-review checks; never image approval."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


POLICY = "reference_continuity_v1"
DIMENSIONS = ("identity", "costume", "action_interaction", "background_space", "framing")
TRANSFERS = {
    "identity": {"face", "hair", "fixed_marks", "body_proportions"},
    "costume_state": {"clothing", "accessories", "injury_state"},
    "pose_interaction": {"pose", "contact", "gaze"},
    "scene_view": {"geometry", "materials", "lighting"},
    "framing": {"composition", "crop"},
    "spatial_layout": {"screen_region", "depth", "occlusion"},
    "prop_state": {"prop_shape", "prop_state"},
    "style": {"linework", "palette", "shading"},
}
ROLE_NAMES = {
    "identity": "身份", "costume_state": "服装/身体状态", "pose_interaction": "姿态/互动",
    "scene_view": "场景视图", "framing": "构图", "spatial_layout": "空间示意",
    "prop_state": "道具状态", "style": "风格",
}
SCENE_MODES = {"same_scene_same_view", "same_scene_new_view", "new_scene", "scene_state_change"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strings(value: Any, nonempty: bool = False) -> bool:
    return isinstance(value, list) and (bool(value) or not nonempty) and all(isinstance(x, str) and x.strip() for x in value)


def text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def visible_ids(panel: dict[str, Any]) -> list[str] | None:
    people = panel.get("characters_visible")
    if not isinstance(people, list):
        return None
    ids = []
    for person in people:
        if isinstance(person, str):
            subject = person
        elif isinstance(person, dict):
            subject = person.get("character_id") or person.get("subject_id") or person.get("id") or person.get("asset_id")
        else:
            return None
        if not text(subject):
            return None
        ids.append(subject)
    return ids


def reference_usage_block(bindings: list[dict[str, Any]], references: list[dict[str, Any]] | None = None) -> str:
    """Compile already-checked bindings into literal, per-alias B instructions."""
    lines = ["参考用途绑定"]
    order = {r.get("alias"): index + 1 for index, r in enumerate(references or []) if isinstance(r, dict)}
    for binding in bindings:
        prefix = f"参考图{order[binding['alias']]} " if references is not None and binding['alias'] in order else ""
        lines.append(
            f"{prefix}{binding['alias']}：{ROLE_NAMES[binding['purpose']]}；对象{'、'.join(binding['subject_ids'])}；"
            f"仅迁移{'、'.join(binding['allowed_transfer'])}；不迁移{'、'.join(binding['forbidden_transfer'])}。"
        )
    return "\n".join(lines)


def validate_panel(panel: dict[str, Any], previous: dict[str, dict[str, Any]], *, prompt: bool, indexed: bool = False) -> list[str]:
    """Check declared contracts; source truth and visual quality still need review."""
    errors = []
    pid = panel.get("panel_id", "?")

    def fail(message: str) -> None:
        errors.append(f"{pid}: {message}")

    contract = panel.get("continuity_contract")
    if not isinstance(contract, dict):
        return [f"{pid}: 缺少continuity_contract"]
    subjects = contract.get("subjects")
    if not isinstance(subjects, dict):
        fail("continuity_contract.subjects必须按角色ID登记")
        subjects = {}
    people = visible_ids(panel)
    if people is None or len(people) != len(set(people)) or set(people) != set(subjects):
        fail("subjects必须与characters_visible的唯一角色ID完全一致")
    for subject, state in subjects.items():
        if not text(subject) or not isinstance(state, dict):
            fail("角色状态必须为ID对应对象")
            continue
        for key in ("identity_state", "costume_state", "screen_region"):
            if not text(state.get(key)):
                fail(f"{subject}缺少{key}")
        for key in ("identity_visible", "costume_visible"):
            if not isinstance(state.get(key), bool):
                fail(f"{subject}.{key}须根据批准裁切填写布尔值")
        exemption = state.get("asset_exemption")
        if exemption is not None and not (
            isinstance(exemption, dict) and exemption.get("status") == "ONE_OFF_ASSET_EXEMPT"
            and exemption.get("appearance_count") == 1 and text(exemption.get("basis"))
        ):
            fail(f"{subject}一次出镜豁免缺少出镜统计或源脚本描述依据")

    required = contract.get("required_visible")
    framing = obj(panel.get("framing"))
    if not strings(required, True) or required != framing.get("required_visible"):
        fail("required_visible必须逐项保留批准framing.required_visible")
    offscreen = contract.get("offscreen_entities")
    if not strings(offscreen) or len(offscreen) != len(set(offscreen)):
        fail("offscreen_entities须为不重复的ID数组")
        offscreen = []
    if set(offscreen) & set(subjects):
        fail("画外角色不能同时出现在subjects中")
    if strings(required) and any(any(item.startswith(entity + "：") or item == entity for item in required) for entity in offscreen):
        fail("必显实体不能同时登记为画外")

    fixed, changes = contract.get("invariants"), contract.get("allowed_changes")
    for name, value in (("invariants", fixed), ("allowed_changes", changes)):
        if not isinstance(value, dict) or any(not text(k) or "." not in k or not text(v) for k, v in value.items()):
            fail(f"{name}须使用对象ID.属性键和值/脚本依据")
    fixed = fixed if isinstance(fixed, dict) else {}
    changes = changes if isinstance(changes, dict) else {}
    if set(fixed) & set(changes):
        fail("同一属性不能既锁定又允许改变")

    scene = contract.get("scene")
    scene = scene if isinstance(scene, dict) else {}
    mode, prior_id = scene.get("mode"), scene.get("previous_panel_id")
    if not isinstance(mode, str) or mode not in SCENE_MODES or not text(scene.get("basis")) or not text(scene.get("scene_id")):
        fail("scene须明确scene_id、连续性模式和批准空间/脚本依据")
    if scene.get("scene_id") != panel.get("scene_id"):
        fail("合同scene_id与本格不一致")
    prior = previous.get(prior_id) if isinstance(prior_id, str) else None
    last = next(reversed(previous.values()), None) if previous else None
    if mode == "new_scene" and last and obj(obj(last.get("continuity_contract")).get("scene")).get("scene_id") == scene.get("scene_id"):
        fail("连续同场景不能以new_scene且不填前序格来绕过连续性")
    if mode != "new_scene" and prior is None:
        fail("连续场景模式须指向已存在的前序格")
    if prior:
        old_scene = obj(obj(prior.get("continuity_contract")).get("scene"))
        if mode != "new_scene" and old_scene.get("scene_id") != scene.get("scene_id"):
            fail("不同场景不能使用同场景连续性模式")
        if mode == "new_scene" and old_scene.get("scene_id") == scene.get("scene_id"):
            fail("同一场景不能以new_scene绕过连续性检查")
        same_view = prior.get("camera_view_id") == panel.get("camera_view_id")
        if mode == "same_scene_same_view" and not same_view:
            fail("同场景同视图模式与camera_view_id不符")
        if mode == "same_scene_new_view" and same_view:
            fail("换机位模式必须有不同camera_view_id")
    if mode == "scene_state_change" and f"{scene.get('scene_id')}.background_space" not in changes:
        fail("场景状态变化须登记background_space的脚本支持变化")
    # Reappearing characters remain linked even across a scene cut.
    for subject, state in subjects.items():
        if not isinstance(state, dict):
            continue
        earlier = next((p for p in reversed(list(previous.values())) if subject in obj(obj(p.get("continuity_contract")).get("subjects"))), None)
        if earlier:
            old = obj(earlier["continuity_contract"]["subjects"][subject])
            for dimension, key in (("identity", "identity_state"), ("costume", "costume_state")):
                if old.get(key) != state.get(key) and f"{subject}.{dimension}" not in changes:
                    fail(f"{subject}.{key}改变但没有脚本支持的allowed_changes")

    requirements = contract.get("qa_requirements")
    if not isinstance(requirements, dict) or set(requirements) != set(DIMENSIONS):
        fail("qa_requirements须明确五个维度，不可遗漏或增加替代项")
        requirements = requirements if isinstance(requirements, dict) else {}
    for dimension in DIMENSIONS:
        requirement = requirements.get(dimension, {})
        if not isinstance(requirement, dict):
            fail(f"{dimension}验收要求须为对象")
            continue
        applicability = requirement.get("applicability")
        if not isinstance(applicability, str) or applicability not in ("REQUIRED", "NOT_VISIBLE", "NOT_APPLICABLE") or not text(requirement.get("criterion")):
            fail(f"{dimension}须在生图前明确适用状态与判据/理由")
        targets = requirement.get("subject_ids")
        if not strings(targets) or len(targets) != len(set(targets)) or (applicability == "REQUIRED" and not targets):
            fail(f"{dimension}.subject_ids无效")
            targets = []
        if set(targets) & set(offscreen):
            fail(f"{dimension}不能要求画外角色入画验收")
        if dimension in ("identity", "costume"):
            visible = {s for s, state in subjects.items() if isinstance(state, dict) and state.get(f"{dimension}_visible") is True}
            if visible and (applicability != "REQUIRED" or set(targets) != visible):
                fail(f"{dimension}必须覆盖所有实际可见的角色特征")
            if not visible and applicability == "REQUIRED":
                fail(f"{dimension}不可要求裁切外特征")
            if applicability != "REQUIRED" and targets:
                fail(f"{dimension}不适用时subject_ids须为空")
            if subjects and not visible and applicability != "NOT_VISIBLE":
                fail(f"{dimension}特征被裁切时用NOT_VISIBLE，不能伪称无此验收维度")
            if not subjects and applicability != "NOT_APPLICABLE":
                fail(f"{dimension}无人物时用NOT_APPLICABLE")
        if dimension == "framing" and (applicability != "REQUIRED" or targets != [pid]):
            fail("framing必须验收本格批准构图及全部必显信息")
        if dimension == "background_space":
            if framing.get("background_level") != "minimal" and applicability != "REQUIRED":
                fail("批准构图含背景空间，不能豁免背景验收")
            if applicability == "REQUIRED" and targets != [scene.get("scene_id")]:
                fail("background_space须核对当前scene_id")

    bindings = panel.get("reference_bindings")
    if not isinstance(bindings, list):
        fail("缺少reference_bindings数组")
        bindings = []
    seen = set()
    valid_bindings = []
    for binding in bindings:
        if not isinstance(binding, dict):
            fail("reference_bindings条目须为对象")
            continue
        alias, purpose, targets = binding.get("alias"), binding.get("purpose"), binding.get("subject_ids")
        valid = text(alias) and isinstance(purpose, str) and purpose in TRANSFERS and strings(targets, True)
        if not valid:
            fail("绑定须明确alias、合法purpose和subject_ids")
            continue
        key = (alias, purpose, tuple(targets))
        if key in seen:
            fail(f"重复参考绑定{alias}/{purpose}")
        seen.add(key)
        allowed, forbidden = binding.get("allowed_transfer"), binding.get("forbidden_transfer")
        if not strings(allowed, True) or not strings(forbidden, True):
            fail(f"{alias}须明确可迁移与不可迁移内容")
            continue
        if not set(allowed) <= TRANSFERS[purpose] or set(allowed) & set(forbidden):
            fail(f"{alias}/{purpose}存在跨用途迁移或互斥指令")
        if set(targets) & set(offscreen):
            fail(f"{alias}用途绑定不能把画外实体当作本格生成对象")
        if purpose in ("identity", "costume_state", "pose_interaction") and not set(targets) <= set(subjects):
            fail(f"{alias}人物参考须绑定实际可见角色ID")
        if purpose == "scene_view" and targets != [scene.get("scene_id")]:
            fail(f"{alias}场景参考须绑定本格scene_id")
        if purpose in ("framing", "spatial_layout") and targets != [pid]:
            fail(f"{alias}构图/空间参考须绑定本格panel_id")
        valid_bindings.append(binding)

    for subject, state in subjects.items():
        if not isinstance(state, dict) or state.get("asset_exemption"):
            continue
        for dimension, purpose in (("identity", "identity"), ("costume", "costume_state")):
            if state.get(f"{dimension}_visible") and not any(b["purpose"] == purpose and subject in b["subject_ids"] for b in valid_bindings):
                fail(f"{subject}缺少可见{dimension}的参考绑定或一次出镜豁免")
            key = f"{subject}.{dimension}"
            if key not in changes and fixed.get(key) != state.get(f"{dimension}_state"):
                fail(f"{key}须在invariants中锁定本格真实状态")
    if any(b["purpose"] == "pose_interaction" for b in valid_bindings):
        if obj(requirements.get("action_interaction")).get("applicability") != "REQUIRED":
            fail("使用互动参考仍须实际验收动作/接触")

    if prompt:
        refs = panel.get("reference_images")
        refs = refs if isinstance(refs, list) else []
        by_alias = {r.get("alias"): r for r in refs if isinstance(r, dict) and text(r.get("alias"))}
        aliases = {b.get("alias") for b in valid_bindings}
        if aliases != set(by_alias):
            fail("每张实际参考图须有用途绑定，绑定不可引用不存在的别名")
        for binding in valid_bindings:
            if binding["purpose"] in ("identity", "costume_state"):
                ref = by_alias.get(binding["alias"], {})
                owners = ref.get("subject_ids")
                if not strings(owners, True) or not set(binding["subject_ids"]) <= set(owners):
                    fail(f"{binding['alias']}角色归属与绑定对象不一致或缺少subject_ids")
                dimension = "identity" if binding["purpose"] == "identity" else "costume"
                for subject in binding["subject_ids"]:
                    declared = obj(obj(ref.get("subject_states")).get(subject)).get(dimension)
                    if declared != obj(subjects.get(subject)).get(f"{dimension}_state") or not text(declared):
                        fail(f"{binding['alias']}/{subject}:参考{dimension}状态与本格合同不一致")
        if len(valid_bindings) == len(bindings):
            block = reference_usage_block(valid_bindings, refs if indexed else None)
            if panel.get("reference_usage_block") != block or block not in str(panel.get("prompt", "")):
                fail("参考用途绑定须编译进reference_usage_block与实际prompt正文")
    return errors


def validate_manifest(manifest: dict[str, Any], *, prompt: bool = True, root: Path | None = None) -> tuple[list[str], list[str]]:
    if manifest.get("continuity_policy") != POLICY:
        if manifest.get("continuity_policy") is not None:
            return ["不支持的continuity_policy，不能降级跳过门禁"], []
        panels = manifest.get("panels") or manifest.get("shot_design") or []
        if isinstance(panels, list) and any(isinstance(p, dict) and ("continuity_contract" in p or "reference_bindings" in p) for p in panels):
            return ["已有连续性扩展但缺少策略声明，不能删除策略绕过门禁"], []
        return [], ["旧包未声明reference_continuity_v1；新增门禁未执行，须人工迁移，不能称新规则已通过"]
    panels = manifest.get("panels") or manifest.get("shot_design")
    if not isinstance(panels, list) or not panels:
        return ["连续性合同panels不能为空"], []
    from continuity_context import load_context
    previous, errors = load_context(manifest,root)
    for panel in panels:
        if not isinstance(panel, dict):
            errors.append("逐格合同须为对象")
            continue
        errors.extend(validate_panel(panel, previous, prompt=prompt, indexed=manifest.get("reference_input_policy") == "codex_reference_v1"))
        previous[panel.get("panel_id")] = panel
    return errors, []


def dimension_template(panel: dict[str, Any]) -> dict[str, Any]:
    requirements = obj(obj(panel.get("continuity_contract")).get("qa_requirements"))
    result = {}
    for dimension in DIMENSIONS:
        expected = requirements.get(dimension)
        planned = expected.get("applicability") if isinstance(expected, dict) else None
        result[dimension] = {
            "expected": expected,
            "status": planned if isinstance(planned, str) and planned in ("NOT_VISIBLE", "NOT_APPLICABLE") else "UNREVIEWED",
            "reviewer": None, "evidence": None,
        }
    return result


def check_dimension_report(manifest: dict[str, Any], report: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    """Verify recorded reviews against the frozen contract and actual image bytes."""
    errors, warnings = validate_manifest(manifest,root=manifest_path.parent)
    if manifest.get("continuity_policy") != POLICY:
        errors.append("旧包没有可执行的连续性合同；不能完成分项验收")
    if report.get("source_manifest_sha256") != sha256(manifest_path):
        errors.append("QA对应的源manifest已变更或缺少哈希")
    errors.extend(str(e) for e in report.get("errors", []))
    source_panels = manifest.get("panels", [])
    items = report.get("panels", [])
    if not isinstance(items, list) or [p.get("panel_id") for p in items if isinstance(p, dict)] != [p.get("panel_id") for p in source_panels]:
        errors.append("QA格号/顺序与源manifest不一致")
        items = []
    for panel, item in zip(source_panels, items):
        pid = panel.get("panel_id")
        if manifest.get("style_policy") == "approved_style_v1" or panel.get("style_policy") is not None:
            from style_contract import validate_style, review_errors
            errors.extend(f"{pid}: {e}" for e in validate_style(panel, manifest_path.parent))
            errors.extend(f"{pid}: {e}" for e in review_errors(panel, item))
        image = Path(item.get("image") or "")
        if not image.is_file() or sha256(image) != item.get("image_sha256"):
            errors.append(f"{pid}:待审图片缺失、已改变或未登记哈希")
        if item.get("ratio_check") != "PASS":
            errors.append(f"{pid}:实际比例未通过")
        from visual_evidence import review_errors as visual_review_errors
        actual_size = None
        if panel.get("visual_evidence_policy"):
            try:
                from PIL import Image
                with Image.open(image) as opened: actual_size = opened.size
            except (OSError, ValueError): errors.append(f"{pid}:原图无法读取，不能进行原尺寸审查")
        errors.extend(f"{pid}: {e}" for e in visual_review_errors(panel, item, image_size=actual_size))
        expected = dimension_template(panel)
        actual = item.get("dimension_review")
        if not isinstance(actual, dict) or set(actual) != set(DIMENSIONS):
            errors.append(f"{pid}:五维度验收记录不完整")
            continue
        for dimension, template in expected.items():
            review = actual.get(dimension)
            if not isinstance(review, dict) or review.get("expected") != template["expected"]:
                errors.append(f"{pid}/{dimension}:验收判据被修改或缺失")
                continue
            applicability = template["expected"].get("applicability") if isinstance(template["expected"], dict) else None
            if applicability == "REQUIRED":
                if review.get("status") != "PASS" or not text(review.get("reviewer")) or not text(review.get("evidence")):
                    errors.append(f"{pid}/{dimension}:未通过实际图片复核或缺少复核者/具体证据")
            elif review.get("status") != applicability:
                errors.append(f"{pid}/{dimension}:不能在生图后改写适用范围")
    return {"status": "HOLD" if errors else "DIMENSION_REVIEW_RECORDED", "scope": "dimension_review_only", "layout_release": False, "errors": errors, "warnings": warnings}


def main() -> int:
    parser = argparse.ArgumentParser(description="参考用途/连续性合同检查；可检查分项QA记录，不授权底图或排版")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--qa-report", help="检查已人工填写的生成图QA报告")
    args = parser.parse_args()
    path = Path(args.manifest).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    if args.qa_report:
        report = json.loads(Path(args.qa_report).read_text(encoding="utf-8-sig"))
        result = check_dimension_report(manifest, report, path)
    else:
        errors, warnings = validate_manifest(manifest,root=path.parent)
        result = {"status": "HOLD" if errors else ("LEGACY_REVIEW_REQUIRED" if warnings else "PASS"), "scope": "declared_contract_only", "layout_release": False, "errors": errors, "warnings": warnings}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] in ("HOLD", "LEGACY_REVIEW_REQUIRED") else 0


if __name__ == "__main__":
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
