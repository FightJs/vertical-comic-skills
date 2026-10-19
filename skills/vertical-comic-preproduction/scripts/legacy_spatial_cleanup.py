#!/usr/bin/env python3
"""Remove retired legacy diagram inputs without changing script or shot facts.

This module only migrates metadata and executable references. It renders no
images, invents no positions and does not grant spatial or identity approval.
"""

from __future__ import annotations

import copy
import re
import shutil
from pathlib import Path
from typing import Any

from continuity_contract import reference_usage_block


RETIRED_KEYS = {
    "camera_cards", "camera_card", "camera_card_path", "camera_card_file",
    "visible_cards", "visible_card", "visible_scene_cards", "visible_scene_card",
    "visible_scene_card_path", "camera_visible_card", "camera_visible_scene_card",
    "camera_view_card", "view_card",
}
RETIRED_TEXT = re.compile(
    r"可见(?:画面|视图|view)(?:[^；。\n]{0,8})?(?:卡|示意图)|"
    r"(?:站位|视角|构图)投影卡|画面事实参考|"
    r"camera[ _-]?(?:(?:visible|view|frame)[ _-]?)?(?:scene[ _-]?)?cards?|view[ _-]?cards?|"
    r"visible[ _-]?(?:scene|frame)[ _-]?(?:cards?|diagram)|script_visible_content_card",
    re.I,
)
LEGACY_ALIAS = re.compile(r"^@VIEW_(?:E\d{3}_)?P\d{3}$", re.I)
EXECUTION_FIELDS = ("prompt", "negative_prompt", "camera_execution_block", "content_execution_block")


def is_retired_reference(value: Any) -> bool:
    if isinstance(value, str):
        return bool(RETIRED_TEXT.search(value) or LEGACY_ALIAS.fullmatch(value))
    if not isinstance(value, dict):
        return False
    # A real scene reference may mention an old dependency after a semicolon.
    # Classify the reference itself, not that incidental instruction.
    role = str(value.get("role") or "").split("；", 1)[0].split(";", 1)[0]
    if role.lower() in {"camera_visible", "visible_scene", "visible_frame", "camera_view_card", "visible_card", "script_visible_content_card"}:
        return True
    labels = [value.get(k, "") for k in ("alias", "path", "source_path", "kind", "type")]
    labels.append(role)
    return any(is_retired_reference(str(x)) for x in labels)


def execution_text(text: str, aliases: set[str]) -> str:
    for alias in sorted(aliases, key=len, reverse=True):
        text = re.sub(re.escape(alias) + r"(?![A-Za-z0-9_\-\u4e00-\u9fff])", "", text)
    text = RETIRED_TEXT.sub("已批准镜头与逐人物空间记录", text)
    text = re.sub(r"[、,，][ \t]*[、,，]+", "、", text)
    return text.strip()


def migrate_panel(panel: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    result = copy.deepcopy(panel)
    report: dict[str, Any] = {"panel_id": panel.get("panel_id"), "removed_fields": [], "removed_references": [], "resolved_dependencies": []}
    aliases: set[str] = set()
    for field in RETIRED_KEYS:
        if field in result:
            result.pop(field)
            report["removed_fields"].append(field)
    camera = result.get("camera")
    if isinstance(camera, dict):
        for field in RETIRED_KEYS:
            if field in camera:
                camera.pop(field)
                report["removed_fields"].append("camera." + field)
    for field in ("reference_images", "supporting_documents", "planned_identity_assets"):
        entries = result.get(field)
        if not isinstance(entries, list):
            continue
        kept = []
        for entry in entries:
            if is_retired_reference(entry):
                report["removed_references"].append({"field": field, "entry": entry})
                if isinstance(entry, dict) and isinstance(entry.get("alias"), str):
                    aliases.add(entry["alias"])
                continue
            if isinstance(entry, dict) and isinstance(entry.get("role"), str):
                entry["role"] = execution_text(entry["role"], set())
            kept.append(entry)
        result[field] = kept
    for field in ("asset_mentions", "reference_bindings"):
        entries = result.get(field)
        if isinstance(entries, list):
            result[field] = [x for x in entries if (x.get("alias") if isinstance(x, dict) else x) not in aliases and not is_retired_reference(x)]
    if ("reference_usage_block" in result and isinstance(result.get("reference_bindings"), list)
            and result["reference_bindings"] != panel.get("reference_bindings")):
        old_block = result["reference_usage_block"]
        indexed = isinstance(old_block, str) and bool(re.search(r"^参考图\d+ ", old_block, re.M))
        new_block = reference_usage_block(result["reference_bindings"], result.get("reference_images", []) if indexed else None)
        result["reference_usage_block"] = new_block
        if isinstance(old_block, str) and isinstance(result.get("prompt"), str):
            result["prompt"] = result["prompt"].replace(old_block, new_block)
    for field in EXECUTION_FIELDS:
        if isinstance(result.get(field), str):
            result[field] = execution_text(result[field], aliases)
    holds = result.get("hold_reasons")
    if isinstance(holds, str):
        holds = [holds]
    if isinstance(holds, list):
        kept = []
        for hold in holds:
            text = str(hold)
            # Resolve only an isolated missing-output dependency. Camera,
            # identity and mixed spatial conflicts remain open.
            card_only = bool(re.fullmatch(r"(?:缺少|缺失|未生成|待生成|待制作)\s*(?:逐格|本格)?\s*(?:可见画面卡|相机可见画面卡)[。.!！]?", text))
            if card_only:
                report["resolved_dependencies"].append(text)
            else:
                kept.append(hold)
        result["hold_reasons"] = kept
    if result.get("panel_id") and (aliases or report["removed_fields"] or report["removed_references"]):
        visible = result.get("visible_region")
        insufficient = not isinstance(visible, str) or not visible.strip() or bool(RETIRED_TEXT.search(visible))
        contract = result.get("continuity_contract")
        subjects = contract.get("subjects") if isinstance(contract, dict) else {}
        subjects = subjects if isinstance(subjects, dict) else {}
        for person in result.get("characters_visible") or []:
            if not isinstance(person, dict):
                continue
            cid = person.get("character_id") or person.get("id")
            position = person.get("screen_position") or subjects.get(cid, {}).get("screen_region")
            if not isinstance(position, str) or not position.strip() or RETIRED_TEXT.search(position):
                insufficient = True
        if insufficient:
            result.setdefault("hold_reasons", []).append("CAMERA_HOLD：移除旧示意引用后，可见范围或逐人物位置缺少明确依据")
    report["removed_aliases"] = sorted(aliases)
    return result, report


def migrate_manifest(data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    result, root_report = migrate_panel(data)
    reports = []
    if any(root_report[k] for k in ("removed_fields", "removed_references", "resolved_dependencies", "removed_aliases")):
        reports.append(root_report)
    for field in ("panels", "shot_design"):
        if isinstance(result.get(field), list):
            items = []
            for item in result[field]:
                if isinstance(item, dict):
                    cleaned, report = migrate_panel(item)
                    items.append(cleaned)
                    if report != {"panel_id": item.get("panel_id"), "removed_fields": [], "removed_references": [], "resolved_dependencies": [], "removed_aliases": []}:
                        reports.append(report)
                else:
                    items.append(item)
            result[field] = items
    return result, reports


def retired_inputs(record: dict[str, Any]) -> list[str]:
    issues = [key for key in RETIRED_KEYS if key in record]
    if isinstance(record.get("camera"), dict):
        issues += ["camera." + key for key in RETIRED_KEYS if key in record["camera"]]
    for field in ("reference_images", "supporting_documents", "asset_mentions", "reference_bindings"):
        for entry in record.get(field) or []:
            if is_retired_reference(entry):
                issues.append(field + ": " + str(entry))
    for field in (*EXECUTION_FIELDS, "reference_usage_block"):
        if isinstance(record.get(field), str) and RETIRED_TEXT.search(record[field]):
            issues.append(field)
    return issues


def copy_panel_inputs(source: Path, output: Path, panel: dict[str, Any]) -> list[str]:
    """Copy declared live inputs only; never copy old executable trees."""
    missing = []
    for field in ("reference_images", "supporting_documents"):
        for index, entry in enumerate(panel.get(field) or []):
            value = entry.get("path") if isinstance(entry, dict) else entry
            if not isinstance(value, str) or not value:
                continue
            relative = Path(value)
            if relative.is_absolute():
                missing.append(value)
                continue
            candidates = [relative]
            if len(relative.parts) > 1 and relative.parts[0] == source.name:
                candidates.append(Path(*relative.parts[1:]))
            chosen = next((p for p in candidates if (source / p).resolve().is_relative_to(source.resolve()) and (source / p).is_file()), None)
            if chosen is None:
                missing.append(value)
                continue
            target = (output / chosen).resolve()
            if not target.is_relative_to(output.resolve()):
                missing.append(value)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / chosen, target)
            if isinstance(entry, dict):
                entry["path"] = chosen.as_posix()
            else:
                panel[field][index] = chosen.as_posix()
    return missing
