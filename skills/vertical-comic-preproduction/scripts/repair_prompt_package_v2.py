#!/usr/bin/env python3
"""Evidence-preserving comprehensive repair for legacy B-stage packages.

This is intentionally stricter than the first repair helper.  It does not
pretend that longer prose proves a camera.  It rebuilds one authoritative
prompt per panel, copies actual references and station SVGs, derives
positive ratios, preserves information-first framing without cycling scales, and writes an
issue ledger including one-off asset exemptions.  The source package is never
overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


from legacy_spatial_cleanup import is_retired_reference, migrate_manifest
from continuity_contract import reference_usage_block
from codex_reference_contract import POLICY as CODEX_POLICY, final_prompt, invalidate_execution, copy_contract_evidence
from check_control_inputs import validate_manifest as validate_inputs
from validate_preproduction import Gate
from identity_confirmation import execution_block as identity_block, repair_preflight, validate_manifest as validate_identity
from input_priority import POLICY as INPUT_PRIORITY_POLICY, EXECUTION_BLOCK, resolution_block

try:
    import cairosvg
except Exception:  # pragma: no cover - optional only for SVG station maps
    cairosvg = None


RASTER = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
POSITIVE_RATIO = re.compile(r"^\s*[1-9]\d*\s*:\s*[1-9]\d*\s*$")
PANEL_RE = re.compile(r"(?:^|[-_])P(\d{3})$", re.I)
ANGLE_MAP = {
    "frontal": "frontal_eye",
    "frontal_eye": "frontal_eye",
    "profile": "profile_left",
    "profile_left": "profile_left",
    "profile_right": "profile_right",
    "three_quarter": "three_quarter_left",
    "three_quarter_left": "three_quarter_left",
    "three_quarter_right": "three_quarter_right",
    "ots": "over_shoulder",
    "over_shoulder": "over_shoulder",
    "pov": "subjective_oblique",
    "low_angle": "low_angle",
    "high_angle": "high_oblique",
    "top_down": "top_down",
    "reflection": "reflection_oblique",
    "insert": "insert_oblique",
    "insert_oblique": "insert_oblique",
    "ecu": "insert_oblique",
    "ground_level": "ground_level",
}
def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline='\n')


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def pid(value: Any) -> str:
    text = str(value or "")
    match = PANEL_RE.search(text)
    return f"P{match.group(1)}" if match else text


def compact(value: Any, limit: int | None = None) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, dict):
        value = "；".join(f"{k}={compact(v, limit)}" for k, v in value.items())
    elif isinstance(value, list):
        value = "；".join(compact(v, limit) for v in value)
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text if limit is None or len(text) <= limit else text[: limit - 1] + "…"


def executable_text(value: Any, fallback: str) -> str:
    """Keep stale HOLD/unmapped markers out of executable B-facing prose."""
    # A legacy camera dict often contains x/y/z=null plus a status marker.
    # Never leak that bookkeeping into the B-facing sentence.  The caller
    # separately keeps the unresolved state in the audit ledger and HOLD.
    if isinstance(value, dict) and value.get("reference"):
        value = value.get("reference")
    text = compact(value)
    if not text:
        return fallback
    text = re.sub(r"SCENE_HOLD_UNMAPPED", fallback, text, flags=re.I)
    text = re.sub(r"\s*[；;，,]?\s*(?:待|未)(?:场景底账|空间底账|站位图|空间图)[^；;，,。]*", "", text)
    text = re.sub(r"\b(?:HOLD|UNMAPPED|UNSPECIFIED_RATIO_HOLD)\b", "", text, flags=re.I)
    if any(marker in text for marker in ("按源画面内容", "按锁定脚本视觉内容", "按源内容", "未明示处")):
        return fallback
    text = re.sub(r"[；;，,]\s*[；;，,]", "；", text).strip("；;，, ")
    return text or fallback


SPATIAL_HOLD_MARKERS = (
    "UNKNOWN_ABSOLUTE_COORDINATES",
    "ID_RESERVED_ONLY_NOT_A_STATION_MAP",
    "HOLD_NOT_YET_SPATIALLY_PROVEN",
    "CAMERA_HOLD",
    "ASSET_HOLD",
    "待空间图验证",
    "待场景定版",
    "绝对坐标UNKNOWN",
)


def spatial_proof_is_missing(raw_panel: dict[str, Any], shot: dict[str, Any] | None) -> bool:
    """Return True unless the source actually proves the camera and blocking.

    A scoped user approval of an asset or relative design is not spatial proof.
    Legacy packages frequently carried null x/y/z, a reserved station ID and a
    downstream CAMERA_HOLD while a later repair script promoted them to PASS.
    Those states must remain a B-stage HOLD until scene evidence, blocking and
    the approved camera/crop establish the actual view.
    """
    records = [raw_panel, shot or {}]
    text = json.dumps(records, ensure_ascii=False)
    if any(marker in text for marker in SPATIAL_HOLD_MARKERS):
        return True
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("view_check") not in (None, "", "PASS", "CAMERA_EXCEPTION"):
            return True
        if record.get("downstream_status") not in (None, "", "PASS", "READY"):
            return True
        camera = record.get("camera_position") or record.get("camera")
        if isinstance(camera, dict) and any(camera.get(axis) is None for axis in ("x", "y", "z")):
            # A relative reference can be valid, but it is not sufficient by
            # itself if the actual camera and blocking are not established.
            return True
    return False


def merge_shot(panel: dict[str, Any], source: dict[str, Any] | None) -> dict[str, Any]:
    result = dict(panel)
    if source:
        result.update(source)
        nested = source.get("camera")
        if isinstance(nested, dict):
            result.update(nested)
        # Keep panel's locked script/content if the candidate shot is only a
        # camera shell and has no real source text.
        for key in ("locked_script", "visual_analysis", "reference_images", "asset_mentions"):
            if panel.get(key) not in (None, "", [], {}):
                result[key] = panel[key]
    return result


def ratio_for(record: dict[str, Any], event: str, original_prompt: str) -> str:
    # Several legacy packages stored 3:2 as a generic fallback even while the
    # shot plan explicitly said that the positive ratio was still to be
    # designed.  Treat that value as missing when the evidence carries those
    # markers; do not let a negative prompt or a stale fallback become the
    # repaired output ratio.
    record_text = json.dumps(record, ensure_ascii=False).lower()
    legacy_ratio_is_unproven = any(
        marker in record_text
        for marker in ("vertical_candidate", "exact ratio hold", "exact ratio", "不得默认生成3:2")
    )
    for value in (record.get("frame_ratio"), record.get("ratio"), record.get("frame")):
        text = str(value or "")
        match = re.search(r"(?<!\d)(\d+)\s*[:：]\s*(\d+)(?!\d)", text)
        if match and int(match.group(1)) > 0 and int(match.group(2)) > 0:
            a, b = int(match.group(1)), int(match.group(2))
            # Reject the legacy default when it is only present in a negative
            # sentence or was copied as the old fallback.
            if (not legacy_ratio_is_unproven or f"{a}:{b}" != "3:2") and f"不要默认生成{a}:{b}" not in original_prompt and not str(value).endswith("candidate"):
                return f"{a}:{b}"
    lower = event.lower()
    if any(x in event for x in ("手机", "手指", "手机屏幕", "伤口", "脸", "眼睛", "符纸", "婚书", "钥匙")):
        return "4:5"
    if any(x in event for x in ("三人", "群像", "全身", "房间", "通道", "客厅", "停机坪", "仓库")):
        return "3:4"
    return "9:16"


def choose_angle(original: str, event: str, previous: str | None) -> tuple[str, str]:
    raw = str(original or "").lower().replace("-", "_").replace(" ", "_")
    # Preserve the provided camera. A repair cannot move it to satisfy a
    # neighboring label; absent authority remains a candidate for review.
    if raw in ANGLE_MAP:
        base = ANGLE_MAP[raw]
    elif raw in ANGLE_MAP.values():
        base = raw
    else:
        base = next((ANGLE_MAP[k] for k in sorted(ANGLE_MAP, key=len, reverse=True) if k in raw), "three_quarter_left")
    return base, raw


def choose_scale(original: str, event: str, previous: str | None) -> tuple[str, str]:
    raw = str(original or "").lower().replace("-", "_").replace(" ", "_")
    lookup = {
        "ecu": "extreme_close", "extreme_close_up": "extreme_close", "close_up": "close",
        "cu": "close", "mcu": "medium_close", "medium_close_up": "medium_close", "medium_close": "medium_close",
        "ms": "medium", "medium": "medium", "ws": "wide", "wide": "wide",
        "long": "long", "extreme_long": "extreme_long", "extreme_close": "extreme_close", "close": "close", "medium_wide": "medium_wide", "full": "medium_wide",
        "中近景": "medium_close", "近景": "medium_close", "特写": "close", "大特写": "extreme_close", "中景": "medium", "半身": "medium", "全身": "medium_wide", "全景": "wide", "远景": "long",
    }
    # Same-scale dialogue is valid. Location words in the event and the
    # previous scale cannot force a wider frame. Missing scale is a proposal.
    base = lookup.get(raw) or next((lookup[k] for k in sorted(lookup, key=len, reverse=True) if k in raw), "medium_close")
    return base, raw


def face_logic(angle: str) -> str:
    return {
        "frontal_eye": "主体面对观众，双眼和大部分正脸可见",
        "profile_left": "主体面向画面左，画面中只见一侧完整侧脸，不补出另一侧正脸",
        "profile_right": "主体面向画面右，画面中只见一侧完整侧脸，不补出另一侧正脸",
        "three_quarter_left": "主体向画面左前方，露出大部分正脸与一侧面部",
        "three_quarter_right": "主体向画面右前方，露出大部分正脸与一侧面部",
        "over_shoulder": "前景人物背对观众，露出大部分后脑勺和少量靠镜头一侧面部",
        "subjective_oblique": "按主观视点展示目标实际可见面，不把被遮挡人物补成正脸",
        "low_angle": "低机位看到人物下方仰视关系，脸部按身体朝向露出，不强行正脸",
        "high_oblique": "高机位斜俯，头顶和肩线可见，脸部因俯角自然减少",
        "top_down": "俯视为主，人物脸部不强行完整呈现，地面关系和遮挡优先",
        "insert_oblique": "局部斜侧特写，只呈现脚本指定接触点和局部可见面",
        "ground_level": "贴地机位，前景实体自然遮挡下半身，不为露全人物移除遮挡",
        "reflection_oblique": "以镜面真实反射展示可见面，镜外人物和镜中人物不互换位置",
    }.get(angle, "按本格摄影机位置呈现人物实际可见面，不强行补全正脸")


def source_file(root: Path, relative: Any, panel_dir: Path) -> Path | None:
    if isinstance(relative, str) and relative:
        candidate = (root / relative).resolve()
        if candidate.is_file():
            return candidate
        candidate = (panel_dir / relative).resolve()
        if candidate.is_file():
            return candidate
        name = Path(relative).name
        hits = list(root.rglob(name))
        if hits:
            return hits[0]
    return None


def event_text(panel: dict[str, Any]) -> str:
    locked = panel.get("locked_script")
    if isinstance(locked, dict):
        return str(locked.get("event_text") or locked.get("source_cells", {}).get("画面内容") or "")
    return str(panel.get("event_text") or "")


def character_records(panel: dict[str, Any]) -> list[dict[str, Any]]:
    # An explicit empty visible list is meaningful (e.g. object-only detail).
    values = panel.get("characters_visible") if "characters_visible" in panel else panel.get("characters") or panel.get("people") or []
    return [item for item in values if isinstance(item, dict) and item.get("in_frame") is not False and item.get("visibility") != "offscreen"] if isinstance(values, list) else []


def derived_visible_region(panel: dict[str, Any], event: str, angle: str) -> str:
    records = character_records(panel)
    names = [str(item.get("name") or item.get("asset_alias") or item.get("asset_id") or "主体") for item in records]
    if not names:
        return f"画面中央承载脚本动作主体；画面左前景保留真实遮挡，画面右后景保留场景锚点。脚本可见内容：{event}"
    if angle == "over_shoulder":
        positions = ["画面左前景（背对观众，仅露后脑/肩线作为遮挡）", "画面中央偏右（目标主体）"]
        positions += ["画面右后景（被前景关系遮挡的次要主体）"] * max(0, len(names) - 2)
    elif angle in {"high_oblique", "top_down"}:
        positions = ["画面中央偏左上（主体）", "画面中央偏右下（关系主体）"]
        positions += ["画面右后景"] * max(0, len(names) - 2)
    elif angle in {"insert_oblique", "extreme_close"}:
        positions = ["画面中央局部（脚本指定接触点或关键表情）"]
        positions += ["不入画，仅保留其与关键接触点的真实遮挡关系"] * max(0, len(names) - 1)
    elif angle in {"profile_left", "profile_right"}:
        positions = ["画面中央偏左（完整侧脸/身体关系）", "画面右中（互动对象）"]
        positions += ["画面右后景"] * max(0, len(names) - 2)
    else:
        positions = ["画面中央偏左（主要动作主体）", "画面中央偏右（关系主体）"]
        positions += ["画面后中景"] * max(0, len(names) - 2)
    # If the locked shot explicitly says “A肩后看B”, bind foreground and
    # target by name instead of assuming character-list order.
    shot_text = json.dumps(panel.get("source_cells") or panel.get("camera") or {}, ensure_ascii=False)
    match = re.search(r"([\u4e00-\u9fff]{2,5})肩后看([\u4e00-\u9fff]{2,5})", shot_text)
    if match and angle == "over_shoulder":
        foreground, target = match.groups()
        by_name = {name: positions[index] for index, name in enumerate(names)}
        def resolve_name(token: str) -> str | None:
            if token in by_name:
                return token
            return next((name for name in names if token in name or name in token), None)
        foreground_name = resolve_name(foreground)
        target_name = resolve_name(target)
        if foreground_name:
            by_name[foreground_name] = "画面左前景（背对观众，仅露后脑/肩线作为遮挡）"
        if target_name:
            by_name[target_name] = "画面中央偏右（目标主体）"
        positions = [by_name[name] for name in names]
    pairs = [f"{name}={positions[index]}" for index, name in enumerate(names)]
    anchors = panel.get("background_anchors_visible") if "background_anchors_visible" in panel else panel.get("background_anchors") or []
    anchor_text = "；背景锚点=" + "、".join(str(x) for x in anchors[:5]) if isinstance(anchors, list) and anchors else ""
    return "人物屏幕位置：" + "；".join(pairs) + anchor_text + f"。脚本可见内容：{event}"


def character_details(panel: dict[str, Any], event: str, angle: str, visible: str) -> str:
    records = character_records(panel)
    if not records:
        return "仅画本格已指定的可见局部或物件，不从画外人物与全场角色清单补人。"
    # Reuse the same deterministic position logic used in visible_region so
    # the prompt cannot describe a different screen arrangement.
    names = [str(item.get("name") or item.get("asset_alias") or item.get("asset_id") or "主体") for item in records]
    position_text = visible.split("脚本可见内容：", 1)[0].replace("人物屏幕位置：", "")
    position_map = {}
    for part in position_text.split("；"):
        if "=" in part:
            key, value = part.split("=", 1)
            position_map[key.strip()] = value.strip()
    lines: list[str] = []
    for item, name in zip(records, names):
        visibility = panel.get('subject_visibility', {})
        subject_scope = visibility.get(item.get('character_id') or item.get('subject_id'), {}) or next(
            (v for v in visibility.values() if v.get('subject_name') == name), {})
        hidden_face = subject_scope.get('face_visible') is False
        action = executable_text(item.get("action") or item.get("body_pose"), event)
        gaze = executable_text(item.get("head_gaze") or item.get("gaze"),
                               "仅表现批准的头部朝向" if hidden_face else "头部和视线朝向本格互动对象")
        expression = executable_text(item.get("expression"),
                                    "" if hidden_face else f"表情/状态以锁定事件为准：{event}")
        relation = executable_text(item.get("orientation_relative_to") or item.get("relative_position"), "按场景锚点保持相对位置")
        face_visibility = executable_text(
            item.get("visible_face") or item.get("face_visibility") or item.get("head_orientation"),
            "只显示本格实际可见的面；未明确露出正脸时不得擅自补正脸",
        )
        position = executable_text(item.get("screen_position"), position_map.get(name, "屏幕位置未明确，保持CAMERA_HOLD"))
        from spatial_contract import enabled as spatial_enabled
        if spatial_enabled(panel):
            ev = panel['visual_evidence']
            owner = item.get('character_id') or item.get('subject_id')
            blocking = ev.get('blocking', {}).get(owner)
            projection = ev.get('visibility', {}).get(owner)
            if not blocking or not projection:
                raise ValueError(f'SPATIAL_HOLD:{name}:缺当前人物站位与可见性，不能继承旧屏幕位置')
            position = projection['expected']
            relation = f"世界位置={blocking['position']}，朝向={blocking['facing']}"
        from visual_evidence import BODY_CROP_LABELS
        crop = item.get('body_crop') or (panel.get('framing') or {}).get('body_crop', '')
        if crop in ('mixed', 'environment'):
            raise ValueError(f"INPUT_CONFLICT:{name}:须在编译前明确逐人物body_crop，不能继承mixed/environment")
        crop_label = BODY_CROP_LABELS.get(str(crop), crop)
        lines.append(
            f"- {name}：屏幕位置={position}；动作/身体={action}；头部/视线={gaze}；微表情={expression}；可见面={face_visibility}；朝向关系={relation}；身体裁切={crop_label}。"
        )
    result = "逐人物执行：\n" + "\n".join(lines)
    from input_semantics import conflict_errors
    issues = conflict_errors(panel, result)
    if issues: raise ValueError(';'.join(issues))
    return result


def visible_text(panel: dict[str, Any], event: str, angle: str) -> str:
    value = compact(panel.get("visible_region"))
    placeholder = any(x in value for x in ("待", "按脚本", "按源", "HOLD", "绝对屏幕坐标", "画面左/右与前后层级按"))
    if value and not placeholder:
        return value
    return derived_visible_region(panel, event, angle)


def build_prompt(panel: dict[str, Any], angle: str, scale: str, ratio: str,
                 camera_position: str, facing: str, height: str,
                 visible: str, refs: list[str], previous: dict[str, Any] | None,
                 following: dict[str, Any] | None, signature: str,
                 characters: str) -> tuple[str, str, str]:
    panel_id = pid(panel.get("panel_id"))
    event = event_text(panel)
    scene = executable_text(
        panel.get("scene_source_label") or panel.get("scene_id") or panel.get("scene_reference_status"),
        "本格脚本场景",
    )
    framing = panel.get("framing")
    from visual_evidence import BODY_CROP_LABELS as crops
    crop_line = ""
    if isinstance(framing, dict):
        crop_line = f"身体裁切：{crops.get(str(framing.get('body_crop')), '')}；视觉重点：{compact(framing.get('focus'))}；必显信息：{compact(framing.get('required_visible'))}；背景层级：{framing.get('background_level', '')}。"
    from visual_evidence import framing_execution_block, execution_block as visual_block, POLICY as VISUAL_POLICY
    execution_panel = {**panel, 'visible_region': visible}
    from spatial_contract import enabled as spatial_enabled, selection_errors, projection_errors
    if spatial_enabled(panel):
        execution_panel.update(camera_angle_family=angle, shot_scale=scale, frame_ratio=ratio,
                               camera_position=camera_position, facing_direction=facing,
                               camera_height=height, camera_view_signature=signature)
        problems = selection_errors(execution_panel) + projection_errors(execution_panel)
        if problems: raise ValueError(';'.join(problems))
    framing_block = framing_execution_block(execution_panel)
    if framing_block:
        crop_line = ''  # The compiled block already carries crop/focus/required information.
    concrete_block = visual_block(execution_panel) if panel.get('visual_evidence_policy') == VISUAL_POLICY else framing_block
    visible_beat = compact(framing.get("required_visible")) if isinstance(framing, dict) else event
    body = [
        f"【机位强制执行｜{panel_id}】",
        "机位角度：" + f"{angle}；面部可见范围以本格可见区域和逐人物执行为准，不得因机位标签强行露出正脸。",
        f"景别：{scale}；主体在画面中的占比必须与该景别一致。",
        f"画幅比例：{ratio}；按此正整数比例输出，不得默认改成横版或3:2。",
        f"镜头签名：{signature}；必须执行此签名对应的机位、景别、位置和朝向。",
        f"摄影机位置/朝向：相对于{scene}的固定锚点，{camera_position}；{facing}。",
        f"摄影机高度与俯仰：{height}；机位只改变观察位置，不移动场景结构、人物站位或固定道具。",
        f"本机位实际可见区域：{visible}。",
        crop_line,
        "【画面内容锁定】",
        concrete_block,
        f"场景：{scene}。场景结构、门窗、墙体、地形和光源方向保持稳定。",
        f"画面分区：{visible}；前景保留真实遮挡，中景承载动作，后景保留脚本要求的背景锚点。",
        characters,
        f"人物面部与身体：{visible_beat}。身体朝向、头部朝向、视线、微表情、可见面和接触动作以本格已批准镜头、裁切和逐人物记录为准；未写出的心理和动作不新增。",
        "连续性：人物自身左右侧的发饰、伤势、衣服标志和固定道具不得换边；角色面对观众时，角色自身左侧标志落在画面右侧，反之亦然。",
        "遮挡：门框、桌沿、床沿、前景人物、车座或道具按现实关系遮挡，不为了露出完整人物或物品而删掉实体；反打机位只显示真实能看到的后脑勺、侧脸或正脸比例。",
        "光线：沿用场景固定主光源方向、色温和阴影逻辑，不为本格添加情绪光。场景/道具本体文字按脚本精确要求随图生成；对白、旁白、心声和画外SFX不写进底图。",
        f"本格执行已批准的必显信息：{visible_beat}。原事件逐字保留在locked_script；裁切不得遗漏必要动作、道具、文字或同时反应。",
        "参考图：" + "、".join(refs) + "。参考图只辅助角色外观、场景结构和连续性，最终必须服从本格机位和画面锁定内容。",
    ]
    if panel.get('input_quality_policy') == 'execution_quality_v1':
        # Executable visual facts once. Signature, budget and neighboring labels
        # remain structured metadata, never extra drawing instructions.
        body = [
            f"【本格镜头｜{panel_id}】",
            f"机位角度：{angle}；景别：{scale}；画幅比例：{ratio}。摄影机位置：{camera_position}；朝向：{facing}；高度与俯仰：{height}。",
            "【画面内容锁定】", concrete_block, characters,
            "对白、旁白、心声和后期SFX不绘入底图；画内文字按本格准确要求。",
            "参考图：" + "、".join(refs) + "。按各自身份/衣装、场景、画风或编辑用途使用，不迁移相反的装饰、姿态与空间。",
        ]
    from coordinate_repair import execution_block as coordinate_block
    coordinate_text = coordinate_block(panel)
    if coordinate_text: body.append(coordinate_text)
    from rule_memory import execution_constraints
    constraints = execution_constraints(panel)
    existing = '\n'.join(x for x in body if x)
    missing = [line for line in constraints if line not in existing]
    if missing: body.extend(['【本格适用规则】', *missing])
    prompt = "\n".join(x for x in body if x)
    negative = (
        f"禁止擅自扩大已批准身体裁切；禁止补入画外人物或未要求的背景物件；禁止默认3:2；禁止移动门窗家具和固定道具；"
        "禁止把反打画成错误正脸；禁止解除真实遮挡；禁止发饰、伤势或标志物换边；禁止违背脚本或批准方案机械复制表情和身体状态；"
        "禁止新增剧情、对白、心声、旁白和未锁定的画内文字。"
    )
    content_start = body.index("【画面内容锁定】")
    camera_block = "\n".join(x for x in body[:content_start] if x)
    content_block = "\n".join(x for x in body[content_start:] if x)
    from input_semantics import conflict_errors
    issues = conflict_errors(panel, final_prompt(prompt, negative))
    if issues: raise ValueError(';'.join(issues))
    return prompt, negative, camera_block + "\n\n" + content_block


def occurrences(panels: list[dict[str, Any]]) -> Counter[str]:
    # This is deliberately conservative: only names/objects explicitly
    # present in the locked event text are counted.  It is used for exemptions,
    # not as proof that an unknown identity is safe to invent.
    counter: Counter[str] = Counter()
    for panel in panels:
        text = event_text(panel)
        names = set(re.findall(r"[\u4e00-\u9fff]{2,8}", text))
        for name in names:
            counter[name] += 1
    return counter


HOLD_GENERIC_TOKENS = {
    "资产", "场景", "角色", "道具", "人物", "物品", "缺失", "缺口", "需要", "补制",
    "参考", "图", "空间", "站位", "坐标", "镜头", "画面", "视觉", "连续性", "未登记",
}


def prepare_refs(source_root: Path, output_root: Path, panel: dict[str, Any], event: str) -> tuple[list[dict[str, Any]], list[str], list[Any]]:
    panel_id = pid(panel.get("panel_id"))
    src_panel_dir = source_root / panel_id
    out_panel_dir = output_root / panel_id
    ref_dir = out_panel_dir / "参考图"
    ref_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    aliases: list[str] = []
    supporting: list[Any] = []
    original = panel.get("reference_images") if isinstance(panel.get("reference_images"), list) else []
    documents = list(panel.get("supporting_documents") or [])
    for index, ref in enumerate(original):
        if not isinstance(ref, dict) or is_retired_reference(ref):
            continue
        source = source_file(source_root, ref.get("path"), src_panel_dir)
        if source is None:
            continue
        alias = str(ref.get("alias") or f"@{panel_id}_ref_{index+1}")
        if source.suffix.lower() in RASTER:
            target = ref_dir / source.name
            shutil.copy2(source, target)
        elif source.suffix.lower() == ".svg":
            if cairosvg is None:
                raise ValueError('SVG_RENDERER_HOLD: 实际参考需要SVG转PNG；当前解释器缺CairoSVG或原生Cairo。运行runtime_environment.py --require-svg检查，不得静默丢弃参考。')
            target = ref_dir / f"{source.stem}_raster.png"
            try:
                cairosvg.svg2png(url=str(source), write_to=str(target), output_width=1400)
            except Exception as exc:
                target.unlink(missing_ok=True)
                raise ValueError('SVG_RENDERER_HOLD: 必需参考转换失败: '+str(source)) from exc
            documents.append(ref)
        else:
            documents.append(ref)
            continue
        entries.append({**ref, "alias": alias, "path": target.relative_to(output_root).as_posix(),
                        "role": str(ref.get("role") or "reference"),
                        "version": str(ref.get("version") or "REPAIRED_V2"), "sha256": sha256(target)})
        aliases.append(alias)
    for doc in documents:
        if is_retired_reference(doc):
            continue
        value = doc.get("path") if isinstance(doc, dict) else doc
        source = source_file(source_root, value, src_panel_dir)
        if source is None:
            continue
        target = out_panel_dir / "supporting_documents" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        relative = target.relative_to(output_root).as_posix()
        entry = {**doc, "path": relative} if isinstance(doc, dict) else relative
        if entry not in supporting:
            supporting.append(entry)
    return entries, aliases, supporting


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--shot-manifest", default=None)
    ap.add_argument("--output", required=True)
    ap.add_argument("--book", default="")
    ap.add_argument("--episode", default="")
    ap.add_argument("--accepted-basis", action="store_true", help="use scoped user-accepted relative spatial basis")
    ap.add_argument("--identity-root", default=None, help="episode root containing scoped identity confirmation evidence")
    args = ap.parse_args()
    source_root = Path(args.source).resolve()
    output_root = Path(args.output).resolve()
    if output_root.exists():
        raise SystemExit(f"refusing to overwrite: {output_root}")
    manifest_path = source_root / "全话提示词索引.json"
    if not manifest_path.is_file():
        raise SystemExit(f"missing manifest: {manifest_path}")
    original_manifest = read_json(manifest_path)
    data, migrations = migrate_manifest(original_manifest)
    identity_root = Path(args.identity_root).resolve() if args.identity_root else source_root.parent
    identity_shot = None
    if args.shot_manifest:
        identity_shot, shot_migrations = migrate_manifest(read_json(Path(args.shot_manifest).resolve()))
        migrations.extend(shot_migrations)
        if identity_shot.get("input_priority_policy") != data.get("input_priority_policy"):
            raise SystemExit("input_priority_policy differs between source package and approved shots")
    identity_errors = repair_preflight(data, identity_root, source_root, identity_shot)
    if args.book and args.book != data.get("book_id") or args.episode and args.episode != data.get("episode_id"):
        identity_errors.append("IDENTITY_HOLD: 修复命令的本书/本话与身份审计不一致")
    if identity_errors:
        print(json.dumps({"status": "HOLD", "errors": identity_errors, "output_created": False}, ensure_ascii=False, indent=2))
        return 1
    panels = data.get("panels")
    if not isinstance(panels, list) or not panels:
        raise SystemExit("manifest has no panels")
    shot_items = (identity_shot or {}).get("panels") or (identity_shot or {}).get("shot_design") or (identity_shot or {}).get("items") or []
    if isinstance(shot_items, dict):
        shot_items = list(shot_items.values())
    shots = {pid(p.get("panel_id")): p for p in shot_items if isinstance(p, dict)}
    merged_panels = [merge_shot(p, shots.get(pid(p.get("panel_id")))) for p in panels]
    identity_errors = repair_preflight({**data, "panels": merged_panels}, identity_root, source_root)
    if identity_errors:
        print(json.dumps({"status": "HOLD", "errors": identity_errors, "output_created": False}, ensure_ascii=False, indent=2))
        return 1
    output_root.mkdir(parents=True)
    counter = occurrences([p for p in panels if isinstance(p, dict)])
    all_old_holds: list[str] = []
    for item in panels:
        if not isinstance(item, dict):
            continue
        values = item.get("hold_reasons") or []
        if isinstance(values, str):
            values = [values]
        all_old_holds.extend(str(value) for value in values)
    hold_counter = Counter(all_old_holds)
    asset_hold_counter: Counter[str] = Counter()
    for hold in all_old_holds:
        for asset_id in re.findall(r"PR-[A-Za-z0-9_-]+", hold):
            asset_hold_counter[asset_id] += 1
    prepared: list[dict[str, Any]] = []
    issue_ledger: list[dict[str, Any]] = []
    prev_new: dict[str, Any] | None = None
    for index, raw_panel in enumerate(panels):
        if not isinstance(raw_panel, dict):
            continue
        panel_id = pid(raw_panel.get("panel_id"))
        source_shot = shots.get(panel_id)
        panel = merge_shot(raw_panel, source_shot)
        spatial_hold = spatial_proof_is_missing(raw_panel, source_shot)
        event = event_text(panel)
        old_angle = panel.get("camera_angle_family") or panel.get("camera", {}).get("camera_angle_family")
        old_scale = panel.get("shot_scale") or panel.get("camera", {}).get("shot_scale")
        angle, old_angle_raw = choose_angle(str(old_angle or ""), event, prev_new.get("_new_angle") if prev_new else None)
        scale, old_scale_raw = choose_scale(str(old_scale or ""), event, prev_new.get("_new_scale") if prev_new else None)
        ratio = ratio_for(panel, event, str(raw_panel.get("prompt", "")))
        camera_position = executable_text(
            panel.get("camera_position") or panel.get("relative_anchor") or panel.get("camera", {}).get("camera_position"),
            "位于脚本主体与场景固定锚点之间的相对位置",
        )
        facing = executable_text(
            panel.get("facing_direction") or panel.get("camera", {}).get("facing_direction"),
            "朝向本格动作主体，保持场景固定锚点在真实背景位置",
        )
        height = executable_text(
            panel.get("camera_height") or panel.get("camera", {}).get("camera_height"),
            "低于人物胸口" if angle in {"low_angle", "ground_level"} else "接近人物视线高度",
        )
        visible_event = compact(panel["framing"].get("required_visible")) if isinstance(panel.get("framing"), dict) else event
        visible = visible_text(panel, visible_event, angle)
        character_detail = character_details(panel, visible_event, angle, visible)
        # Attach newly selected values to neighbors before building prompts.
        panel["_new_angle"], panel["_new_scale"] = angle, scale
        following = None
        if index + 1 < len(panels) and isinstance(panels[index + 1], dict):
            next_raw = panels[index + 1]
            next_panel = merge_shot(next_raw, shots.get(pid(next_raw.get("panel_id"))))
            next_event = event_text(next_panel)
            next_old_angle = next_panel.get("camera_angle_family") or next_panel.get("camera", {}).get("camera_angle_family")
            next_old_scale = next_panel.get("shot_scale") or next_panel.get("camera", {}).get("shot_scale")
            next_angle, _ = choose_angle(str(next_old_angle or ""), next_event, angle)
            next_scale, _ = choose_scale(str(next_old_scale or ""), next_event, scale)
            following = {"panel_id": next_panel.get("panel_id"), "_new_angle": next_angle, "_new_scale": next_scale}
        refs, aliases, support_paths = prepare_refs(source_root, output_root, raw_panel, event)
        previous_for_prompt = prev_new
        signature = str(panel.get("camera_view_signature") or f"{angle} / {scale} / {camera_position} / {facing}")
        prompt, negative, blocks = build_prompt(panel, angle, scale, ratio, camera_position, facing, height, visible, aliases, previous_for_prompt, following, signature, character_detail)
        if data.get("input_priority_policy") == INPUT_PRIORITY_POLICY:
            priority_text = "\n".join(x for x in (EXECUTION_BLOCK, resolution_block(panel.get("visual_resolution"))) if x)
            prompt += "\n" + priority_text
            blocks += "\n" + priority_text
        locked_identity = identity_block(panel, data["identity_registry"])
        usage = reference_usage_block(panel["reference_bindings"], refs if data.get("reference_input_policy") == CODEX_POLICY else None) if isinstance(panel.get("reference_bindings"), list) else ""
        prompt += "\n\n" + locked_identity
        if usage:
            prompt += "\n\n" + usage
        if raw_panel.get("style_policy") == "approved_style_v1" and isinstance(raw_panel.get("style_contract"), dict):
            from style_contract import style_block
            raw_panel = dict(raw_panel)
            raw_panel["style_execution_block"] = style_block(raw_panel["style_contract"])
            prompt += "\n\n" + raw_panel["style_execution_block"]
        if data.get("reference_input_policy") == CODEX_POLICY:
            prompt = final_prompt(prompt, negative)
        panel_dir = output_root / panel_id
        (panel_dir / "prompt.txt").write_text(prompt + "\n", encoding="utf-8", newline='\n')
        (panel_dir / "negative_prompt.txt").write_text(negative + "\n", encoding="utf-8", newline='\n')
        write_json(panel_dir / "提示词.json", {"panel_id": panel_id, "prompt": prompt, "negative_prompt": negative, "references": refs, "camera_angle_family": angle, "shot_scale": scale, "frame_ratio": ratio})
        write_json(panel_dir / "camera_execution.json", {"panel_id": panel_id, "camera_angle_family": angle, "shot_scale": scale, "frame_ratio": ratio, "camera_position": camera_position, "facing_direction": facing, "camera_height": height, "visible_region": visible})

        repaired = dict(raw_panel)
        repaired.update({
            "panel_id": panel_id,
            "camera_angle_family": angle,
            "shot_scale": scale,
            "frame_ratio": ratio,
            "camera_view_signature": signature,
            "camera_position": camera_position,
            "facing_direction": facing,
            "visible_region": visible,
            "camera_execution_status": "EXPLICIT_UNPROVEN_HOLD" if spatial_hold else ("EXPLICIT_USER_ACCEPTED_SPATIAL_BASIS" if args.accepted_basis else "EXPLICIT_AND_PROVEN"),
            "camera_execution_block": blocks.split("\n\n", 1)[0],
            "content_execution_block": blocks.split("\n\n", 1)[1] if "\n\n" in blocks else blocks,
            "identity_execution_block": locked_identity,
            "prompt": prompt,
            "negative_prompt": negative,
            "prompt_file": f"{panel_id}/prompt.txt",
            "negative_prompt_file": f"{panel_id}/negative_prompt.txt",
            "reference_images": refs,
            "asset_mentions": aliases,
            "supporting_documents": support_paths,
            "view_check": "HOLD_NOT_YET_SPATIALLY_PROVEN" if spatial_hold else ("CAMERA_EXCEPTION" if panel.get("view_check") == "CAMERA_EXCEPTION" else "PASS"),
            "source_view_check": raw_panel.get("view_check") or raw_panel.get("source_view_check"),
            "source_downstream_status": (source_shot or {}).get("downstream_status") or raw_panel.get("downstream_status"),
            "status": "PROMPT_REPAIRED_V2",
            "repair_note": "综合修复v2：保留已有镜头与信息优先构图，不机械轮换景别；比例来自正向设计；实际提示词、参考图和索引已重建。",
        })
        for field in ("framing", "characters_visible", "background_anchors_visible", "fixed_props_visible", "adjacent_change_reason", "camera_exception_approval", "continuity_contract", "reference_bindings", "composition_reference", "composition_required", "ratio_tolerance", "transparent_background", "visual_resolution", "visual_evidence_policy", "visual_evidence", "visual_evidence_context", "semantic_facts", "subject_visibility", "adjacent_face_comparison", "generation_dependencies", "memory_applications", "memory_tags", "appearance_policy", "frame_policy", "frame_plan", "appearance_repair", "input_quality_policy", "background_policy"):
            if field in panel:
                repaired[field] = panel[field]
        if usage:
            repaired["reference_usage_block"] = usage
        if repaired.get('visual_evidence_policy') == 'visual_evidence_v1':
            from visual_evidence import execution_block as visual_block
            repaired['visual_execution_block'] = visual_block(repaired)
        invalidate_execution(repaired)
        old_holds = raw_panel.get("hold_reasons") or []
        if isinstance(old_holds, str):
            old_holds = [old_holds]
        remaining: list[str] = []
        resolved: list[dict[str, Any]] = []
        for hold in old_holds:
            text = str(hold)
            if is_retired_reference(text) or "CAMERA_HOLD" in text:
                remaining.append(text)
                continue
            asset_ids = re.findall(r"PR-[A-Za-z0-9_-]+", text)
            if asset_ids:
                repeated_assets = [asset_id for asset_id in asset_ids if asset_hold_counter[asset_id] > 1]
                single_assets = [asset_id for asset_id in asset_ids if asset_hold_counter[asset_id] <= 1]
                if single_assets:
                    resolved.append({
                        "issue": "、".join(single_assets),
                        "resolution": "ONE_OFF_ASSET_EXEMPT",
                        "evidence": f"资产缺口只在本话单格出现：{single_assets}",
                    })
                if repeated_assets:
                    prefix = text.split("PR-", 1)[0].rstrip("：:，, ")
                    remaining.append(f"{prefix}：{'、'.join(repeated_assets)}")
                continue
            # A non-asset hold may still describe a one-off visible person or
            # scene.  Use exact hold repetition across the episode; if it is
            # repeated, it remains a continuity gate.
            if hold_counter[text] == 1 and any(key in text for key in ("角色", "道具", "资产", "场景", "人物", "空间")):
                resolved.append({
                    "issue": text,
                    "resolution": "ONE_OFF_ASSET_EXEMPT",
                    "evidence": "同一缺口在本话HOLD台账中只出现一次；按用户规则不要求独立资产",
                })
                continue
            # Candidate/status holds are stale when a scoped accepted basis is
            # present.  Identity/continuity holds are kept unless genuinely
            # one-off; this prevents the new rule becoming a loophole.
            tokens = re.findall(r"[\u4e00-\u9fff]{2,8}", text)
            relevant_counts = [
                counter[t] for t in tokens
                if t in counter and t not in HOLD_GENERIC_TOKENS
            ]
            one_off = bool(relevant_counts) and max(relevant_counts) <= 1 and any(
                key in text for key in ("角色", "道具", "资产", "scene", "场景")
            )
            if one_off:
                resolved.append({"issue": text, "resolution": "ONE_OFF_ASSET_EXEMPT", "evidence": f"{panel_id}脚本可见文本统计为一次出镜"})
            elif (not spatial_hold) and args.accepted_basis and any(key in text for key in ("空间", "场景", "坐标", "站位", "CAMERA", "SCENE_ASSET", "ASSET_HOLD")):
                resolved.append({"issue": text, "resolution": "RESOLVED_WITH_ACCEPTED_RELATIVE_BASIS", "evidence": "本话用户确认候选/相对坐标依据；不要求绝对XYZ"})
            else:
                remaining.append(text)
        live_aliases = {r.get("alias") for r in raw_panel.get("reference_images", []) if isinstance(r, dict)}
        if live_aliases - set(aliases):
            remaining.append("REFERENCE_INPUT_HOLD：实际参考缺失或格式不支持，未生成替代图片")
        repaired["hold_reasons"] = remaining
        if not isinstance(panel.get("framing"), dict) or not old_angle or not old_scale:
            remaining.append("FRAMING_REVIEW_HOLD：缺少批准构图记录或原机位/景别；修复器的默认提案不构成批准")
        if spatial_hold:
            spatial_reason = "空间证明未完成：站位、摄影机或实际裁切记录仍为候选，不能交B生图"
            if spatial_reason not in remaining:
                remaining.append(spatial_reason)
            repaired["hold_reasons"] = remaining
        if remaining:
            repaired["status"] = "PROMPT_REPAIRED_WITH_OPEN_HOLD"
        for item in resolved:
            issue_ledger.append({"panel_id": panel_id, **item})
        if remaining:
            for hold in remaining:
                issue_ledger.append({"panel_id": panel_id, "issue": hold, "resolution": "OPEN"})
        prepared.append(repaired)
        prev_new = panel

    data["panels"] = prepared
    contract_copy_errors = copy_contract_evidence(source_root, output_root, data)
    input_errors = validate_inputs(data, output_root)["errors"]
    identity_errors = validate_identity(data, identity_root, prompt=True, reference_root=output_root)
    for index, item in enumerate(prepared):
        gate = Gate(source_root)
        gate.check_framing(item, str(item.get("panel_id")), True)
        gate.check_prompt_conflicts(item, str(item.get("panel_id")))
        if index:
            gate.check_adjacent(prepared[index - 1], item)
        elif item.get("view_check") == "CAMERA_EXCEPTION":
            gate.error("首格没有可适用的上一格重复例外")
        for error in [*identity_errors, *(f"REFERENCE_INPUT_HOLD：{x}" for x in [*contract_copy_errors, *input_errors]), *(f"EXECUTION_REVIEW_HOLD：{x}" for x in gate.errors)]:
            reason = error
            if reason not in item["hold_reasons"]:
                item["hold_reasons"].append(reason)
                issue_ledger.append({"panel_id": item["panel_id"], "issue": reason, "resolution": "OPEN"})
        if item["hold_reasons"]:
            item["status"] = "PROMPT_REPAIRED_WITH_OPEN_HOLD"
        panel_dir = output_root / item["panel_id"]
        for filename in ("提示词.json", "camera_execution.json"):
            details = read_json(panel_dir / filename)
            if filename == "提示词.json":
                details.update(item)
            details.update({key: item.get(key) for key in ("framing", "characters_visible", "background_anchors_visible", "fixed_props_visible", "adjacent_change_reason", "hold_reasons", "status", "view_check")})
            write_json(panel_dir / filename, details)
    data["schema"] = "vertical-comic-prompt-package-v1"
    data["framing_policy"] = "information_first_v1"
    data["package_version"] = "RV_v001_COMPREHENSIVE_REPAIR_20260929"
    data["status"] = (
        "READY_FOR_B_GENERATION_PENDING_IMAGE_QA"
        if not any(p.get("hold_reasons") or p.get("camera_execution_status") == "EXPLICIT_UNPROVEN_HOLD" for p in prepared)
        else "REPAIRED_WITH_OPEN_HOLD"
    )
    data["repair_timestamp"] = datetime.now().astimezone().isoformat(timespec="seconds")
    data["repair_scope"] = {"book": args.book, "episode": args.episode, "source_preserved": True, "accepted_relative_basis": args.accepted_basis, "one_off_asset_rule": True}
    source_dir = output_root / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(manifest_path, source_dir / "original_source_manifest.json")
    write_json(source_dir / "source_manifest.json", {**data, "panels": panels})
    if args.shot_manifest:
        shot_path = Path(args.shot_manifest).resolve()
        if shot_path.is_file():
            shutil.copy2(shot_path, source_dir / "original_shot_manifest.json")
            write_json(source_dir / "shot_manifest.json", identity_shot)
    data["sources"] = {
        "source_manifest": "sources/source_manifest.json",
        "shot_manifest": "sources/shot_manifest.json" if (source_dir / "shot_manifest.json").is_file() else "sources/source_manifest.json",
    }
    write_json(output_root / "旧空间输入迁移.json", {"source_preserved": True, "changes": migrations})
    write_json(output_root / "全话提示词索引.json", data)
    write_json(output_root / "修复覆盖台账.json", {"book": args.book, "episode": args.episode, "panel_count": len(prepared), "issues": issue_ledger, "one_off_asset_exemptions": [x for x in issue_ledger if x["resolution"] == "ONE_OFF_ASSET_EXEMPT"], "open_hold_count": sum(1 for x in issue_ledger if x["resolution"] == "OPEN")})
    (output_root / "未决项.md").write_text("# 未决项\n\n" + ("\n".join(f"- {x['panel_id']}：{x['issue']}" for x in issue_ledger if x["resolution"] == "OPEN") or "- 无结构化未决项；B返回底图后仍必须做相邻视觉QA。") + "\n", encoding="utf-8", newline='\n')
    (output_root / "修复说明.md").write_text("# 综合修复v2\n\n原包只读保留。已有镜头按信息优先取景保留，允许有依据的同景别对话；缺少批准构图的默认提案保持HOLD。单次出镜对象不强制独立资产。实际提示词、逐格JSON、参考图和全话索引已重建。结构通过不等于底图通过；B返回后必须做比例、P001–P003及全话相邻镜头视觉QA。\n", encoding="utf-8", newline='\n')
    print(json.dumps({"status": data["status"], "output": str(output_root), "panel_count": len(prepared), "open_holds": sum(1 for x in issue_ledger if x["resolution"] == "OPEN")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
