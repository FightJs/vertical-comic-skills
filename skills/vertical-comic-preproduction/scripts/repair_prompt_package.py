#!/usr/bin/env python3
"""Repair an existing B-stage prompt package without overwriting it.

The repair is deliberately conservative: it copies the source package to a new
version, injects an executable camera block into every prompt, carries frame
ratio and adjacent-shot guards into the manifest, and preserves a HOLD when
the source camera was not physically proven.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from legacy_spatial_cleanup import copy_panel_inputs, migrate_manifest
from continuity_contract import reference_usage_block
from codex_reference_contract import POLICY as CODEX_POLICY, final_prompt, invalidate_execution, copy_contract_evidence
from check_control_inputs import validate_manifest as validate_inputs
from validate_preproduction import Gate
from identity_confirmation import execution_block as identity_block, repair_preflight, validate_manifest as validate_identity


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline='\n')


def records(data: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("shot_design", "panels"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def panel_key(value: Any) -> str:
    """Normalize episode-prefixed IDs (E011-P001) to package IDs (P001)."""
    text = str(value or "").strip()
    match = re.search(r"(?:^|[-_])P(\d{3})$", text, flags=re.IGNORECASE)
    return f"P{match.group(1)}" if match else text


def unproven(record: dict[str, Any]) -> bool:
    text = " ".join(
        str(record.get(key, ""))
        for key in ("view_check", "downstream_status", "camera_exception_reason", "asset_dependency_status")
    )
    needles = ("HOLD", "UNKNOWN", "未验证", "未证明", "绝对坐标", "空间复核", "物理可见性")
    return any(needle in text for needle in needles)


def signature_parts(record: dict[str, Any]) -> tuple[str, str]:
    signature = str(record.get("camera_view_signature", ""))
    parts = [part.strip() for part in signature.split("/")]
    angle = str(record.get("camera_angle_family") or (parts[0] if parts else ""))
    scale = str(record.get("shot_scale") or (parts[1] if len(parts) > 1 else ""))
    return angle, scale


def compact(value: Any, limit: int = 900) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        text = "；".join(compact(item, 260) for item in value)
    elif isinstance(value, dict):
        text = "；".join(f"{key}={compact(item, 220)}" for key, item in value.items())
    else:
        text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def content_block(panel: dict[str, Any], shot: dict[str, Any]) -> str:
    """Write the executable visible-content contract into prompt.txt.

    Existing packages often had these facts only in JSON or in a vague
    reference sentence.  The repair makes the actual image request carry the
    same spatial facts while keeping script text locked verbatim.
    """
    from appearance_lock import single, frame_errors, SINGLE_TEXT
    if single(panel):
        issues=frame_errors(panel)
        if issues:raise ValueError(';'.join(issues))
    scene = shot.get("scene_id") or panel.get("scene_id") or panel.get("scene_reference_status", "")
    visible = shot.get("visible_region") or panel.get("visible_region") or ""
    characters = shot.get("characters_visible", panel.get("characters_visible", []))
    if isinstance(characters, list):
        characters = [item for item in characters if not isinstance(item, dict) or (item.get("in_frame") is not False and item.get("visibility") != "offscreen")]
    anchors = shot.get("background_anchors_visible", panel.get("background_anchors_visible", []))
    visible_props = shot.get("fixed_props_visible", panel.get("fixed_props_visible", []))
    if visible_props:
        anchors = [*anchors, *visible_props] if isinstance(anchors, list) else visible_props
    occlusion = shot.get("occlusion_relations") or panel.get("occlusion_relations") or []
    locked = panel.get("locked_script") or {}
    event_text = locked.get("event_text") if isinstance(locked, dict) else ""
    lines = [
        f"【画面内容锁定｜{panel.get('panel_id', 'P???')}】",
        f"场景：{compact(scene) or '严格按已绑定的场景参考图与站位图。'}。",
        f"本格必须可见：{compact(visible) or '按本格已批准镜头、裁切和逐人物空间记录执行。'}。",
    ]
    framing = shot.get("framing", panel.get("framing"))
    if isinstance(framing, dict):
        crops = {"waist_up": "腰以上", "chest_up": "胸以上", "shoulders_up": "肩以上", "face_detail": "面部局部", "hands_detail": "手部局部", "object_detail": "物件局部", "full_body": "全身", "environment": "必要环境范围", "mixed": "逐人物指定的裁切"}
        lines.append(f"身体裁切：{crops.get(str(framing.get('body_crop')), '')}；画面重点：{compact(framing.get('focus'))}；必显信息：{compact(framing.get('required_visible'))}；背景层级：{framing.get('background_level', '')}。只画已选可见范围，不补出画外人物或腿脚。")
    if characters:
        lines.append("人物与关系：")
        for item in characters if isinstance(characters, list) else [characters]:
            if isinstance(item, dict):
                name = item.get("name") or item.get("character") or item.get("asset_id") or "角色"
                details = []
                for key in (
                    "asset_id", "asset_alias", "screen_position", "depth_order", "depth",
                    "body_orientation", "head_orientation", "gaze", "expression", "action",
                    "body_pose", "head_gaze", "contact_occlusion", "body_crop",
                ):
                    if item.get(key) not in (None, "", []):
                        details.append(f"{key}={compact(item[key], 420)}")
                lines.append(f"- {name}：" + "；".join(details))
            else:
                lines.append(f"- {compact(item)}")
    if anchors:
        lines.append(f"背景锚点与固定道具：{compact(anchors)}。位置、大小、遮挡按场景资产和站位图固定，不为露出物品破坏遮挡。")
    if occlusion:
        lines.append(f"遮挡关系：{compact(occlusion)}。必须遵守前中后景真实遮挡。")
    lighting = shot.get("lighting", panel.get("lighting"))
    if lighting:
        lines.append(f"光线：{compact(lighting)}。")
    style = shot.get("style_constraints", panel.get("style_constraints"))
    if style:
        lines.append(f"既定画风约束：{compact(style)}。")
    if panel.get("input_priority_policy") == "physical_scene_priority_v1":
        from input_priority import EXECUTION_BLOCK, resolution_block
        lines.append(EXECUTION_BLOCK)
        adapted = resolution_block(shot.get("visual_resolution", panel.get("visual_resolution")))
        if adapted:
            lines.append(adapted)
    if single(panel):
        lines.extend([SINGLE_TEXT,"本格仅选画面："+panel["frame_plan"]["selected_scene"]])
    if event_text and not isinstance(framing, dict) and not single(panel):
        lines.append(f"本格事件画面只呈现脚本锁定事件：{compact(event_text, 1200)}。不得新增、删减或改写事件。")
    lines.append("人物身体朝向、头部朝向、视线、微表情和标志性特征按本格批准依据执行；参考资产不要求扩大本格裁切。")
    return "\n".join(lines)


def normalize_package_path(root: Path, value: Any) -> Any:
    """Make copied package references self-contained when old manifests used
    the package directory name as an extra relative prefix."""
    if not isinstance(value, str) or not value.strip():
        return value
    candidate = root / value
    if candidate.exists():
        return value
    parts = Path(value).parts
    if len(parts) > 1:
        stripped = Path(*parts[1:])
        if (root / stripped).exists():
            return stripped.as_posix()
    return value


def strip_repair_blocks(prompt: str) -> str:
    """Allow a later repair pass without stacking duplicate generated blocks."""
    text = prompt.strip()
    if text.startswith("【机位强制执行｜"):
        parts = text.split("\n\n", 1)
        text = parts[1] if len(parts) == 2 else ""
    if text.startswith("【画面内容锁定｜"):
        parts = text.split("\n\n", 1)
        text = parts[1] if len(parts) == 2 else ""
    return text.strip()


def ratio_text(record: dict[str, Any], panel: dict[str, Any]) -> str:
    raw = str(record.get("frame_ratio") or panel.get("frame_ratio") or "")
    for text in (raw, str(panel.get("prompt", "")), str(panel.get("visible_region", ""))):
        match = re.search(r"(\d+)\s*[:：]\s*(\d+)", text)
        if match:
            return f"{match.group(1)}:{match.group(2)}"
    return raw or "UNSPECIFIED_RATIO_HOLD"


def camera_block(panel: dict[str, Any], shot: dict[str, Any], previous: dict[str, Any] | None, following: dict[str, Any] | None) -> str:
    panel_id = panel.get("panel_id", "P???")
    angle, scale = signature_parts(shot)
    ratio = ratio_text(shot, panel)
    signature = shot.get("camera_view_signature", "")
    position = shot.get("camera_position", {})
    if isinstance(position, dict):
        position_text = position.get("reference", "")
        if not position_text and all(position.get(axis) is not None for axis in ("x", "y", "z")):
            position_text = "；".join(f"{axis}={position[axis]}" for axis in ("x", "y", "z"))
        position_text = position_text or "摄影机位置缺少批准依据，保持CAMERA_HOLD"
    else:
        position_text = str(position)
    height = shot.get("camera_height", "")
    facing = shot.get("facing_direction", "")
    horizontal = shot.get("horizontal_angle", "")
    vertical = shot.get("vertical_angle", "")
    visible = shot.get("visible_region", "") or panel.get("visible_region", "")
    lines = [
        f"【机位强制执行｜{panel_id}】",
        f"机位角度：{angle}。",
        f"景别：{scale}。",
        f"画幅比例：{ratio}；严格按该比例输出，不得默认生成3:2横版。",
        f"摄影机位置/朝向：{position_text}；{facing}。",
        f"摄影机高度与俯仰：{height}；水平角度：{horizontal}；垂直角度：{vertical}。",
        f"摄影机镜头签名：{signature}。",
        f"本机位实际可见区域：{visible}。",
        "从上述摄影机位置执行本格已批准构图；参考图的全身或宽景不要求扩大本格取景。",
    ]
    if previous:
        previous_angle, previous_scale = signature_parts(previous)
        lines.append(
            f"上一格{previous.get('panel_id')}使用“{previous_angle} / {previous_scale}”；本格按自身已批准焦点与可见范围执行，不因景别相同拉远。"
        )
    if following:
        following_angle, following_scale = signature_parts(following)
        lines.append(
            f"下一格{following.get('panel_id')}使用“{following_angle} / {following_scale}”；保持本格自己的批准取景。"
        )
    return "\n".join(lines)


def camera_negative(panel: dict[str, Any], shot: dict[str, Any]) -> str:
    ratio = ratio_text(shot, panel)
    return (
        f"禁止意外复制默认场景视图；禁止擅自扩大已批准身体裁切或补入画外人物；禁止输出非{ratio}画幅；"
        "禁止为了露出人物或道具而破坏真实遮挡关系。"
    )


def package_records(data: dict[str, Any]) -> list[dict[str, Any]]:
    value = data.get("panels")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair a B-stage prompt package into a new version")
    parser.add_argument("--source", required=True, help="existing package root")
    parser.add_argument("--shot-manifest", default=None, help="detailed shot manifest; if omitted, use the package panel records")
    parser.add_argument("--output", required=True, help="new package root; must not already exist")
    parser.add_argument("--gate-manifest", default=None, help="optional accepted/locked gate manifest")
    parser.add_argument("--identity-root", default=None, help="episode root containing scoped identity confirmation evidence")
    args = parser.parse_args()

    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    shot_path = Path(args.shot_manifest).resolve() if args.shot_manifest else None
    gate_path = Path(args.gate_manifest).resolve() if args.gate_manifest else None
    manifest_path = source / "全话提示词索引.json"
    if not source.is_dir():
        raise SystemExit(f"source package does not exist: {source}")
    if not manifest_path.is_file():
        raise SystemExit(f"manifest does not exist: {manifest_path}")
    if shot_path is not None and not shot_path.is_file():
        raise SystemExit(f"shot manifest does not exist: {shot_path}")
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing output: {output}")

    original_manifest = load_json(manifest_path)
    prompt_manifest, migrations = migrate_manifest(original_manifest)
    identity_root = Path(args.identity_root).resolve() if args.identity_root else source.parent
    identity_errors = repair_preflight(prompt_manifest, identity_root, source)
    if identity_errors:
        print(json.dumps({"status": "HOLD", "errors": identity_errors, "output_created": False}, ensure_ascii=False, indent=2))
        return 1
    panels = prompt_manifest.get("panels")
    if not isinstance(panels, list) or not panels:
        raise SystemExit("prompt manifest has no panels")
    shot_by_id: dict[str, dict[str, Any]] = {}
    for item in package_records(prompt_manifest):
        if item.get("panel_id"):
            shot_by_id[panel_key(item["panel_id"])] = dict(item)
    if shot_path is not None:
        shot_data, shot_migrations = migrate_manifest(load_json(shot_path))
        migrations.extend(shot_migrations)
        if shot_data.get("input_priority_policy") != prompt_manifest.get("input_priority_policy"):
            raise SystemExit("input_priority_policy differs between source package and approved shots")
        identity_errors = repair_preflight(prompt_manifest, identity_root, source, shot_data)
        if identity_errors:
            print(json.dumps({"status": "HOLD", "errors": identity_errors, "output_created": False}, ensure_ascii=False, indent=2))
            return 1
        for item in records(shot_data):
            if item.get("panel_id"):
                key = panel_key(item["panel_id"])
                shot_by_id[key] = {**shot_by_id.get(key, {}), **item}
    if gate_path and gate_path.is_file():
        gate_data, gate_migrations = migrate_manifest(load_json(gate_path))
        migrations.extend(gate_migrations)
        for item in records(gate_data):
            if item.get("panel_id"):
                panel_id_key = panel_key(item["panel_id"])
                base = shot_by_id.get(panel_id_key, {})
                nonempty = {field: value for field, value in item.items() if value not in (None, "")}
                shot_by_id[panel_id_key] = {**base, **nonempty}

    identity_fields = ("scene_id", "script_character_labels", "character_bindings", "scene_binding", "characters_visible")
    merged_panels = [{**p, **{k: shot_by_id.get(panel_key(p.get("panel_id")), {})[k] for k in identity_fields if k in shot_by_id.get(panel_key(p.get("panel_id")), {})}} for p in panels]
    identity_errors = repair_preflight({**prompt_manifest, "panels": merged_panels}, identity_root, source)
    if identity_errors:
        print(json.dumps({"status": "HOLD", "errors": identity_errors, "output_created": False}, ensure_ascii=False, indent=2))
        return 1
    output.mkdir(parents=True)
    contract_copy_errors = copy_contract_evidence(source, output, prompt_manifest)
    missing_inputs = {}
    for panel in panels:
        missing_inputs[panel.get("panel_id")] = copy_panel_inputs(source, output, panel)
    normalized = []
    for index, panel in enumerate(panels):
        if not isinstance(panel, dict):
            raise SystemExit(f"panel {index} is not an object")
        pid = panel.get("panel_id")
        shot = shot_by_id.get(panel_key(pid))
        if not shot:
            raise SystemExit(f"missing shot record for {pid}")
        panel = dict(panel)
        if prompt_manifest.get("input_priority_policy"):
            panel["input_priority_policy"] = prompt_manifest["input_priority_policy"]
        for field in ("continuity_contract", "reference_bindings", "composition_reference"):
            if field in shot:
                panel[field] = shot[field]
        previous = shot_by_id.get(f"P{int(pid[1:]) - 1:03d}") if isinstance(pid, str) and pid[1:].isdigit() and int(pid[1:]) > 1 else None
        following = shot_by_id.get(f"P{int(pid[1:]) + 1:03d}") if isinstance(pid, str) and pid[1:].isdigit() else None
        block = camera_block(panel, shot, previous, following)
        visible_content = content_block(panel, shot)
        old_prompt = strip_repair_blocks(str(panel.get("prompt", "")))
        explicit_framing = isinstance(shot.get("framing"), dict)
        if explicit_framing:
            # An old wide-view paragraph can contradict the approved crop.
            # Preserve it for audit, rather than leaving it executable.
            aliases = [str(ref.get("alias")) for ref in panel.get("reference_images", []) if isinstance(ref, dict) and ref.get("alias")]
            tail = "参考图引用：" + " ".join(aliases) + "。参考图用于身份、风格和空间依据，不要求复制完整参考画幅。"
        else:
            tail = old_prompt.strip()
        locked_identity = identity_block(panel, prompt_manifest["identity_registry"])
        old_identity = panel.get("identity_execution_block")
        if isinstance(old_identity, str) and old_identity:
            tail = tail.replace(old_identity, "").strip()
        usage = reference_usage_block(panel["reference_bindings"], panel.get("reference_images", []) if prompt_manifest.get("reference_input_policy") == CODEX_POLICY else None) if isinstance(panel.get("reference_bindings"), list) else ""
        old_usage = panel.get("reference_usage_block")
        if old_usage:
            tail = tail.replace(old_usage, "").strip()
        repaired_prompt = "\n\n".join(x for x in (block, visible_content, usage, locked_identity, tail) if x)
        if panel.get("style_policy") == "approved_style_v1" and isinstance(panel.get("style_contract"), dict):
            from style_contract import style_block
            panel["style_execution_block"] = style_block(panel["style_contract"])
            repaired_prompt += "\n\n" + panel["style_execution_block"]
        # The detailed shot record can say PASS while the package itself still
        # carries a HOLD (for example, station/visible-region proof was not
        # promoted into the package).  The repair must preserve the stricter
        # source state instead of silently promoting it.
        source_unproven = unproven(shot) or unproven(panel)
        execution_status = "EXPLICIT_UNPROVEN_HOLD" if source_unproven else "EXPLICIT_AND_PROVEN"
        repaired_view_check = "CAMERA_HOLD" if source_unproven else ("CAMERA_EXCEPTION" if shot.get("view_check") == "CAMERA_EXCEPTION" else "PASS")
        angle, scale = signature_parts(shot)
        ratio = ratio_text(shot, panel)
        repaired = dict(panel)
        if explicit_framing:
            repaired["source_prompt"] = panel.get("source_prompt", panel.get("prompt", ""))
            repaired["source_negative_prompt"] = panel.get("source_negative_prompt", panel.get("negative_prompt", ""))
            holds = repaired.get("hold_reasons") or []
            holds = [holds] if isinstance(holds, str) else list(holds)
            if old_prompt:
                reason = "LEGACY_PROMPT_REVIEW_HOLD：旧正文已移入source_prompt；须核对非构图风格约束和必显信息完整转入新正文"
                if reason not in holds:
                    holds.append(reason)
            repaired["hold_reasons"] = holds
        for field in ("framing", "characters_visible", "background_anchors_visible", "fixed_props_visible", "adjacent_change_reason", "camera_exception_approval", "continuity_contract", "reference_bindings", "composition_reference", "composition_required", "ratio_tolerance", "transparent_background", "visual_resolution"):
            if field in shot:
                repaired[field] = shot[field]
        references = repaired.get("reference_images")
        if isinstance(references, list):
            repaired["reference_images"] = [
                {**ref, "path": normalize_package_path(output, ref.get("path"))}
                if isinstance(ref, dict) else ref
                for ref in references
            ]
        for path_field in ("prompt_file", "negative_prompt_file"):
            if path_field in repaired:
                repaired[path_field] = normalize_package_path(output, repaired[path_field])
        repaired.update(
            {
                "camera_angle_family": angle,
                "shot_scale": scale,
                "frame_ratio": ratio,
                "camera_view_signature": shot.get("camera_view_signature", ""),
                "camera_execution_status": execution_status,
                "camera_execution_block": block,
                "content_execution_block": visible_content,
                "identity_execution_block": locked_identity,
                "source_view_check": shot.get("view_check"),
                "source_downstream_status": shot.get("downstream_status"),
                "source_camera_exception_reason": shot.get("camera_exception_reason", ""),
                "view_check": repaired_view_check,
                "status": "PROMPT_REPAIRED_CAMERA_HOLD" if source_unproven else "PROMPT_REPAIRED",
                "prompt": repaired_prompt,
                "negative_prompt": (("" if explicit_framing else str(panel.get("negative_prompt", "")).rstrip()) + "\n" + camera_negative(panel, shot)).strip(),
                "repair_note": "镜头、比例及批准裁切写入实际正文；有framing时旧正文移入审计字段并保留复核HOLD，避免旧宽景指令冲突；脚本文字和参考绑定保留。",
            }
        )
        if usage:
            repaired["reference_usage_block"] = usage
        invalidate_execution(repaired)
        if prompt_manifest.get("reference_input_policy") == CODEX_POLICY:
            repaired_prompt = final_prompt(repaired_prompt, repaired["negative_prompt"])
            repaired["prompt"] = repaired_prompt
        if missing_inputs.get(pid):
            repaired.setdefault("hold_reasons", []).append("REFERENCE_INPUT_HOLD：实际参考或审计文件缺失，未生成替代图片")
        normalized.append(repaired)
        panel_dir = output / pid
        panel_dir.mkdir(parents=True, exist_ok=True)
        (panel_dir / "prompt.txt").write_text(repaired_prompt + "\n", encoding="utf-8", newline='\n')
        (panel_dir / "negative_prompt.txt").write_text(repaired["negative_prompt"] + "\n", encoding="utf-8", newline='\n')
        write_json(
            panel_dir / "camera_execution.json",
            {
                "panel_id": pid,
                "camera_angle_family": repaired["camera_angle_family"],
                "shot_scale": repaired["shot_scale"],
                "frame_ratio": repaired["frame_ratio"],
                "camera_view_signature": repaired["camera_view_signature"],
                "camera_execution_status": execution_status,
                "view_check": repaired_view_check,
                "camera_execution_block": block,
                "content_execution_block": visible_content,
                "framing": repaired.get("framing"),
            },
        )

    prompt_manifest["panels"] = normalized
    prompt_manifest["framing_policy"] = "information_first_v1"
    identity_errors = validate_identity(prompt_manifest, identity_root, prompt=True, reference_root=output)
    input_errors = validate_inputs(prompt_manifest, output)["errors"]
    for index, item in enumerate(normalized):
        gate = Gate(source)
        gate.check_framing(item, str(item.get("panel_id")), True)
        gate.check_prompt_conflicts(item, str(item.get("panel_id")))
        if index:
            gate.check_adjacent(normalized[index - 1], item)
        elif item.get("view_check") == "CAMERA_EXCEPTION":
            gate.error("首格没有可适用的上一格重复例外")
        holds = item.get("hold_reasons") or []
        if isinstance(holds, str):
            holds = [holds]
        item["hold_reasons"] = [*holds, *identity_errors, *(f"REFERENCE_INPUT_HOLD：{x}" for x in [*contract_copy_errors, *input_errors]), *(f"EXECUTION_REVIEW_HOLD：{x}" for x in gate.errors)]
        if item["hold_reasons"]:
            item["status"] = "PROMPT_REPAIRED_WITH_OPEN_HOLD"
        panel_dir = output / item["panel_id"]
        execution_path = panel_dir / "camera_execution.json"
        execution = load_json(execution_path)
        execution["hold_reasons"] = item["hold_reasons"]
        write_json(execution_path, execution)
        per_panel_path = panel_dir / "提示词.json"
        per_panel = load_json(per_panel_path) if per_panel_path.is_file() else {}
        per_panel.update(item)
        write_json(per_panel_path, per_panel)
    prompt_manifest["package_version"] = "RV_v002_CAMERA_EXECUTION_REPAIRED"
    prompt_manifest["status"] = (
        "REPAIRED_CANDIDATE_CAMERA_HOLD"
        if any(item.get("hold_reasons") or item.get("camera_execution_status") == "EXPLICIT_UNPROVEN_HOLD" for item in normalized)
        else "REPAIRED_READY_FOR_GENERATION_PENDING_IMAGE_QA"
    )
    prompt_manifest["repair_timestamp"] = datetime.now().astimezone().isoformat(timespec="seconds")
    prompt_manifest["repair_basis"] = {
        "source_package": str(source),
        "shot_manifest": str(shot_path),
        "gate_manifest": str(gate_path) if gate_path else None,
        "source_preserved": True,
        "camera_fields_written_into_prompt_text": True,
        "frame_ratio_written_into_prompt_text": True,
        "image_qa_required_before_layout": True,
    }
    source_dir = output / "sources"
    source_dir.mkdir(exist_ok=True)
    shutil.copy2(manifest_path, source_dir / "original_source_manifest.json")
    if shot_path:
        shutil.copy2(shot_path, source_dir / "original_shot_manifest.json")
    if gate_path:
        shutil.copy2(gate_path, source_dir / "original_gate_manifest.json")
    write_json(source_dir / "shot_manifest.json", {**prompt_manifest, "panels": list(shot_by_id.values())})
    prompt_manifest["sources"] = {"source_manifest": "sources/original_source_manifest.json", "shot_manifest": "sources/shot_manifest.json"}
    write_json(output / "旧空间输入迁移.json", {"source_preserved": True, "changes": migrations})
    write_json(output / "全话提示词索引.json", prompt_manifest)
    write_json(
        output / "修复门禁报告.json",
        {
            "status": prompt_manifest["status"],
            "source_preserved": True,
            "panel_count": len(normalized),
            "camera_hold_panels": [p["panel_id"] for p in normalized if p.get("camera_execution_status") == "EXPLICIT_UNPROVEN_HOLD"],
            "framing_hold_panels": [p["panel_id"] for p in normalized if any("FRAMING_REVIEW_HOLD" in str(x) for x in p.get("hold_reasons", []))],
            "legacy_prompt_review_panels": [p["panel_id"] for p in normalized if any("LEGACY_PROMPT_REVIEW_HOLD" in str(x) for x in p.get("hold_reasons", []))],
            "next_required_step": "先复核CAMERA_HOLD、FRAMING_REVIEW_HOLD及旧正文迁移HOLD；B出图后做实际裁切与相邻信息审查。",
        },
    )
    (output / "修复说明.md").write_text(
        "# 生图包镜头执行修复\n\n"
        f"来源包：`{source}`\n\n"
        "来源包保留。镜头、比例及身体裁切写入实际 `prompt.txt`；新构图不与旧宽景正文混用，旧正文保留在审计字段中。保留空间证明和构图/旧正文迁移的复核HOLD。\n\n"
        "使用本包前，先处理 `修复门禁报告.json` 中的所有HOLD。B返回底图后运行 `make_generation_qa.py`，核对实际裁切与必显信息，并通过P001–P003相邻三格审查后才能进入排版。\n",
        encoding="utf-8",
    newline='\n')
    print(json.dumps({"status": "CREATED", "output": str(output), "panel_count": len(normalized)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
