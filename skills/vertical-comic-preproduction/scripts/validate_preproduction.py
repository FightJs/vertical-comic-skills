#!/usr/bin/env python3
"""Deterministic structural and continuity gate for the preproduction skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from codex_reference_contract import composition_errors
from typing import Any

from continuity_contract import POLICY as CONTINUITY_POLICY, validate_manifest as validate_continuity
from check_control_inputs import validate_manifest as validate_controls
from legacy_spatial_cleanup import retired_inputs
from identity_confirmation import POLICY as IDENTITY_POLICY, validate_manifest as validate_identity
from input_priority import POLICY as INPUT_PRIORITY_POLICY, EXECUTION_BLOCK, resolution_block, resolution_errors


PANEL_RE = re.compile(r"^P(\d{3})$", re.IGNORECASE)
ALIAS_RE = re.compile(r"^@[A-Za-z0-9_\-\u4e00-\u9fff]+$")
ALIAS_IN_TEXT_RE = re.compile(r"@[A-Za-z0-9_\-\u4e00-\u9fff]+")
SCREEN_WORDS = ("画面左", "画面中央", "画面右", "画左", "画右")
FORBIDDEN = ("自由机位", "任意角度", "自行发挥", "随意机位", "随便角度")
FRAMING_POLICY = "information_first_v1"
BODY_CROPS = {"waist_up", "chest_up", "shoulders_up", "face_detail", "hands_detail", "object_detail", "full_body", "mixed", "environment"}
BACKGROUND_LEVELS = {"establishing", "anchor_only", "minimal"}
WIDE_SCALES = {"wide", "wide_shot", "long", "long_shot", "extreme_long", "extreme_long_shot", "medium_wide", "full", "full_shot", "full_body", "全景", "远景", "大全景", "全身", "中全景"}
SPATIAL_HOLD_MARKERS = (
    "UNKNOWN_ABSOLUTE_COORDINATES",
    "ID_RESERVED_ONLY_NOT_A_STATION_MAP",
    "HOLD_NOT_YET_SPATIALLY_PROVEN",
    "CAMERA_HOLD",
    "待空间图验证",
    "待场景定版",
    "按上述人物屏幕位置",
    "x=；y=；z=",
)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe(root: Path, rel: str) -> Path | None:
    if not isinstance(rel, str) or not rel.strip():
        return None
    p = (root / rel).resolve()
    try:
        p.relative_to(root.resolve())
    except ValueError:
        return None
    return p


class Gate:
    def __init__(self, root: Path, expected_panel_ids: list[str] | None = None) -> None:
        self.root = root.resolve()
        self.expected_panel_ids = expected_panel_ids
        self.prompt_root = self.root / "04_B提示词包_CANDIDATE"
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def panel_order(self, panels: list[Any], label: str) -> list[int]:
        nums: list[int] = []
        seen: set[str] = set()
        for index, panel in enumerate(panels):
            if not isinstance(panel, dict):
                self.error(f"{label}[{index}]必须是对象")
                continue
            pid = panel.get("panel_id")
            if not isinstance(pid, str) or not PANEL_RE.fullmatch(pid):
                self.error(f"{label}[{index}] panel_id无效: {pid!r}")
                continue
            if pid in seen:
                self.error(f"{label} panel_id重复: {pid}")
            seen.add(pid)
            nums.append(int(pid[1:]))
        if self.expected_panel_ids is not None:
            actual = [p.get("panel_id") for p in panels if isinstance(p, dict)]
            if actual != self.expected_panel_ids:
                self.error(f"{label}与已核对源格序选集不一致")
        elif nums and nums != list(range(1, len(nums) + 1)):
            self.error(f"{label}必须从P001连续编号，当前为{nums}")
        return nums

    def check_script_lock(self, panel: dict[str, Any], label: str) -> None:
        if panel.get("script_lock_check") != "PASS":
            self.error(f"{label}: script_lock_check不是PASS")
        locked = panel.get("locked_script")
        if not isinstance(locked, dict):
            self.error(f"{label}:缺少locked_script，不能证明脚本文字被锁定")
            return
        for key in ("dialogue", "inner_voice", "narration", "sfx_text", "event_text"):
            if key not in locked:
                self.error(f"{label}:locked_script缺少{key}")
        visual = panel.get("visual_analysis")
        if not isinstance(visual, dict):
            self.error(f"{label}:缺少visual_analysis")
        for text in (str(locked.get("event_text", "")), str(panel.get("prompt", ""))):
            if any(term in text for term in FORBIDDEN):
                self.error(f"{label}:出现禁止的模糊机位表达")

    def check_input_priority(self, panel: dict[str, Any], label: str, enabled: bool, prompt: bool = False) -> None:
        if not enabled:
            return
        resolution = panel.get("visual_resolution")
        for issue in resolution_errors(resolution):
            self.error(f"{label}:{issue}")
        if prompt:
            actual = str(panel.get("prompt", ""))
            if EXECUTION_BLOCK not in actual:
                self.error(f"{label}:实际提示词缺少物理与场景优先级执行约束")
            if resolution is not None and resolution_block(resolution) not in actual:
                self.error(f"{label}:实际提示词缺少已批准的本格画面适配")

    def check_framing(self, panel: dict[str, Any], label: str, required: bool) -> None:
        from visual_evidence import framing_errors
        for issue in framing_errors(panel):
            self.error(f"{label}:{issue}")
        framing = panel.get("framing")
        if framing is None and not required:
            return
        if not isinstance(framing, dict):
            self.error(f"{label}:缺少framing构图记录")
            return
        for key in ("focus", "crop_reason"):
            if not isinstance(framing.get(key), str) or not framing[key].strip():
                self.error(f"{label}:framing缺少{key}")
        for key in ("focus_subjects", "required_visible"):
            value = framing.get(key)
            if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
                self.error(f"{label}:framing.{key}必须为非空文字数组")
        crop = framing.get("body_crop")
        if not isinstance(crop, str) or crop not in BODY_CROPS:
            self.error(f"{label}:body_crop必须明确身体裁切范围")
        if not isinstance(framing.get("background_level"), str) or framing["background_level"] not in BACKGROUND_LEVELS:
            self.error(f"{label}:background_level无效")
        scale = str(panel.get("shot_scale", "")).strip().lower().replace("-", "_").replace(" ", "_")
        if crop in ("full_body", "environment") or scale in WIDE_SCALES:
            reason = framing.get("wide_or_full_reason")
            if not isinstance(reason, str) or not reason.strip():
                self.error(f"{label}:全身或宽景缺少wide_or_full_reason")
        if crop == "mixed":
            people = panel.get("characters_visible")
            if not isinstance(people, list) or not people or any(not isinstance(x, dict) or not isinstance(x.get("body_crop"), str) or x["body_crop"] not in BODY_CROPS - {"mixed", "environment"} for x in people):
                self.error(f"{label}:mixed裁切必须逐人物写明body_crop")
            elif any(x["body_crop"] == "full_body" for x in people) and not str(framing.get("wide_or_full_reason") or "").strip():
                self.error(f"{label}:mixed包含全身人物，须填写wide_or_full_reason")

    def repeat_is_approved(self, previous: dict[str, Any], current: dict[str, Any]) -> bool:
        approval = current.get("camera_exception_approval")
        if not isinstance(approval, dict) or approval.get("status") != "USER_ACCEPTED":
            return False
        if approval.get("panel_ids") != [previous.get("panel_id"), current.get("panel_id")]:
            return False
        event = safe(self.root, approval.get("event_path"))
        expected = approval.get("sha256")
        return bool(event and event.is_file() and isinstance(expected, str) and re.fullmatch(r"[0-9a-fA-F]{64}", expected) and digest(event).lower() == expected.lower())

    def check_adjacent(self, previous: dict[str, Any], current: dict[str, Any]) -> None:
        pair = f"{previous.get('panel_id')}→{current.get('panel_id')}"
        same_angle = previous.get("camera_angle_family") == current.get("camera_angle_family")
        same_scale = previous.get("shot_scale") == current.get("shot_scale")
        if current.get("view_check") == "CAMERA_EXCEPTION" and not self.repeat_is_approved(previous, current):
            self.error(f"相邻镜头{pair}:CAMERA_EXCEPTION缺少该格对实际批准事件与哈希")
        if not (same_angle and same_scale):
            return
        reason = current.get("adjacent_change_reason")
        if not isinstance(reason, str) or not reason.strip():
            self.error(f"相邻镜头{pair}:相同角度与景别须说明实际叙事变化或持镜理由")
        fields = ("camera_position", "facing_direction", "visible_region", "characters_visible")
        changed = any(previous.get(k) not in (None, "", [], {}) and current.get(k) not in (None, "", [], {}) and previous[k] != current[k] for k in fields)
        before = previous.get("framing") or {}
        after = current.get("framing") or {}
        if isinstance(before, dict) and isinstance(after, dict):
            changed = changed or any(before.get(k) not in (None, "", []) and after.get(k) not in (None, "", []) and before[k] != after[k] for k in ("focus_subjects", "body_crop"))
        if not changed and not self.repeat_is_approved(previous, current):
            self.error(f"相邻镜头{pair}:构图无可观察变化；只改签名或理由不能代替格对批准")

    def check_shots(self, shot_data: Any) -> list[dict[str, Any]]:
        if not isinstance(shot_data, dict):
            self.error("镜头改编表根节点必须是对象")
            return []
        for issue in retired_inputs(shot_data):
            self.error(f"镜头改编表:停用的逐格示意输入须先迁移: {issue}")
        # Older locked shot manifests use `shot_design`; newer manifests use
        # `panels`.  Both must be read, otherwise the gate can report a false
        # empty shot table and never compare the prompt package to its source.
        panels = shot_data.get("panels") or shot_data.get("shot_design")
        if not isinstance(panels, list) or not panels:
            self.error("镜头改编表panels不能为空")
            return []
        self.panel_order(panels, "镜头改编表")
        from visual_evidence import background_binding_errors
        from input_quality import bindings as input_bindings
        self.errors.extend(background_binding_errors(shot_data, *[p for p in panels if isinstance(p, dict)]))
        self.errors.extend(input_bindings(shot_data, *[p for p in panels if isinstance(p,dict)]))
        self.shot_background_policy = shot_data.get('background_policy')
        from frame_ratio_plan import plan_errors,panel_errors
        self.errors.extend(plan_errors(shot_data,self.root))
        self.errors.extend(panel_errors(shot_data,self.root,panels))
        errors, warnings = validate_continuity(shot_data, prompt=False,root=getattr(self,'shot_root',self.root))
        self.errors.extend(errors)
        self.warnings.extend(warnings)
        from continuity_context import load_context
        prior,context_errors=load_context(shot_data,getattr(self,'shot_root',self.root),readonly=True)
        self.errors.extend(context_errors)
        context_previous=next(reversed(prior.values()),None) if prior else None
        framing_required = shot_data.get("framing_policy") == FRAMING_POLICY
        if shot_data.get("input_priority_policy") not in (None, INPUT_PRIORITY_POLICY):
            self.error("镜头表input_priority_policy未知，不能跳过新规则")
        priority_required = shot_data.get("input_priority_policy") == INPUT_PRIORITY_POLICY
        if not framing_required:
            self.warn("镜头表未声明information_first_v1；旧构图须按新取景规则人工复核，不能伪填framing")
        for i, panel in enumerate(panels):
            label = f"镜头改编表[{i}]"
            if not isinstance(panel, dict):
                continue
            if shot_data.get("reference_input_policy") == "codex_reference_v1":
                self.errors.extend(f"{label}:{message}" for message in composition_errors(panel))
            required = ("panel_id", "script_shot_id", "station_state_id", "camera_view_id", "camera_angle_family", "shot_scale", "visible_region", "camera_view_signature", "view_check", "script_lock_check")
            for key in required:
                if panel.get(key) in (None, ""):
                    self.error(f"{label}:缺少{key}")
            self.check_script_lock(panel, label)
            self.check_input_priority(panel, label, priority_required)
            self.check_framing(panel, label, framing_required)
            for issue in retired_inputs(panel):
                self.error(f"{label}:停用的逐格示意输入须先迁移: {issue}")
            if panel.get("view_check") not in ("PASS", "CAMERA_EXCEPTION"):
                self.error(f"{label}: view_check必须是PASS或CAMERA_EXCEPTION")
            if panel.get("view_check") == "CAMERA_EXCEPTION" and not str(panel.get("camera_exception_reason", "")).strip():
                self.error(f"{label}: CAMERA_EXCEPTION必须给出camera_exception_reason")
            if i == 0 and context_previous is None and panel.get("view_check") == "CAMERA_EXCEPTION":
                self.error(f"{label}:首格没有可适用的上一格重复例外")
            if panel.get("status") not in (None, "CANDIDATE", "CAMERA_CANDIDATE", "CAMERA_LOCKED", "USER_ACCEPTED"):
                self.warn(f"{label}:未知状态{panel.get('status')!r}")
        adjacent=[(context_previous,panels[0])] if context_previous else []
        for prev, cur in [*adjacent,*zip(panels, panels[1:])]:
            if not isinstance(prev, dict) or not isinstance(cur, dict):
                continue
            self.check_adjacent(prev, cur)
            signature = str(cur.get("camera_view_signature", ""))
            if not signature.strip():
                self.error(f"{cur.get('panel_id')}: camera_view_signature为空")
        return [p for p in panels if isinstance(p, dict)]

    def check_refs(self, panel: dict[str, Any], label: str, reference_root: Path | None = None, allow_empty: bool = False) -> None:
        refs = panel.get("reference_images")
        if not isinstance(refs, list) or (not refs and not allow_empty):
            self.error(f"{label}: reference_images不能为空")
            return
        aliases: set[str] = set()
        for i, ref in enumerate(refs):
            if not isinstance(ref, dict):
                self.error(f"{label}:参考图{i}不是对象")
                continue
            alias = ref.get("alias")
            if not isinstance(alias, str) or not ALIAS_RE.fullmatch(alias):
                self.error(f"{label}:参考图{i} alias无效")
            elif alias in aliases:
                self.error(f"{label}:参考图别名重复{alias}")
            else:
                aliases.add(alias)
            path = safe(reference_root or self.root, ref.get("path"))
            if path is None or not path.is_file():
                self.error(f"{label}:{alias or i}参考图不存在或越出本话目录")
            else:
                expected = ref.get("sha256")
                if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
                    self.error(f"{label}:{alias or i}缺少真实SHA256")
                elif digest(path).lower() != expected.lower():
                    self.error(f"{label}:{alias or i} SHA256不匹配")
            for key in ("role", "version"):
                if not str(ref.get(key, "")).strip():
                    self.error(f"{label}:{alias or i}缺少{key}")
        prompt = str(panel.get("prompt", ""))
        mentioned = set(ALIAS_IN_TEXT_RE.findall(prompt))
        if aliases - mentioned:
            self.error(f"{label}提示词漏引参考别名: {sorted(aliases-mentioned)}")
        if mentioned - aliases:
            self.error(f"{label}提示词引用不存在的参考别名: {sorted(mentioned-aliases)}")
        if not any(word in prompt for word in SCREEN_WORDS):
            self.warn(f"{label}提示词没有画面左/右/中央坐标词")
        if any(word in prompt for word in FORBIDDEN):
            self.error(f"{label}提示词含模糊机位表达")

    def check_prompt_conflicts(self, panel: dict[str, Any], label: str) -> None:
        from visual_evidence import framing_errors
        for issue in framing_errors(panel, prompt=True):
            self.error(f"{label}:{issue}")
        prompt = str(panel.get("prompt", ""))
        for issue in retired_inputs(panel):
            self.error(f"{label}:停用的逐格示意输入须先迁移: {issue}")
        if panel.get("hold_reasons"):
            self.error(f"{label}仍有未解除的hold_reasons，不能进入B生图")
        for marker in SPATIAL_HOLD_MARKERS:
            if marker in prompt:
                self.error(f"{label}提示词含未解决的空间/执行占位：{marker}")
        if "只露双手" in prompt and any(term in prompt for term in ("露出大部分正脸", "露出正脸", "完整正脸")):
            self.error(f"{label}同时要求只露双手和露出正脸")
        if "脸在画外" in prompt and any(term in prompt for term in ("露出大部分正脸", "露出正脸", "完整正脸")):
            self.error(f"{label}同时要求脸在画外和露出正脸")
        if "按上述人物屏幕位置" in prompt:
            self.error(f"{label}人物屏幕位置未逐人写实")
        if panel.get("view_check") not in ("PASS", "CAMERA_EXCEPTION"):
            self.error(f"{label}空间视角未通过，不能进入B生图")
        if panel.get("camera_execution_status") == "EXPLICIT_UNPROVEN_HOLD":
            self.error(f"{label}camera_execution_status仍为未证明HOLD")

    def check_prompt(self, prompt_data: Any, shot_panels: list[dict[str, Any]]) -> None:
        if not isinstance(prompt_data, dict):
            self.error("提示词索引根节点必须是对象")
            return
        if prompt_data.get("schema") != "vertical-comic-prompt-package-v1":
            self.error("提示词索引schema不匹配")
        panels = prompt_data.get("panels")
        if not isinstance(panels, list) or not panels:
            self.error("提示词索引panels不能为空")
            return
        numbers = self.panel_order(panels, "提示词索引")
        from visual_evidence import background_binding_errors
        from input_quality import bindings as input_bindings
        self.errors.extend(background_binding_errors(prompt_data, *[p for p in panels if isinstance(p, dict)]))
        self.errors.extend(input_bindings(prompt_data, *[p for p in panels if isinstance(p,dict)]))
        if prompt_data.get('background_policy') != getattr(self, 'shot_background_policy', None):
            self.error('BACKGROUND_HOLD:镜头表与提示词索引的背景策略不同')
        from frame_ratio_plan import plan_errors,panel_errors
        self.errors.extend(plan_errors(prompt_data,self.root))
        self.errors.extend(panel_errors(prompt_data,self.root,panels,prompt=True))
        control_report = validate_controls(prompt_data, self.prompt_root)
        self.errors.extend(control_report["errors"])
        self.warnings.extend(control_report["warnings"])
        try:
            self.errors.extend(validate_identity(prompt_data, self.root, prompt=True, reference_root=self.prompt_root))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.error(f"IDENTITY_HOLD: 身份依据或绑定无法核验: {exc}")
        errors, warnings = validate_continuity(prompt_data,root=self.prompt_root)
        self.errors.extend(errors)
        self.warnings.extend(warnings)
        full_preparation = (prompt_data.get("preparation_policy") == "episode_preparation_v1"
                            and getattr(self, "shot_preparation_policy", None) == "episode_preparation_v1"
                            and self.expected_panel_ids is not None and len(self.expected_panel_ids) == len(panels))
        if len(panels) > 32 and not full_preparation and prompt_data.get("approved_first_version_exception") is not True:
            self.error("提示词包超过32格且没有approved_first_version_exception")
        for issue in retired_inputs(prompt_data):
            self.error(f"提示词索引:停用的逐格示意输入须先迁移: {issue}")
        shot_by_id = {p.get("panel_id"): p for p in shot_panels}
        framing_required = prompt_data.get("framing_policy") == FRAMING_POLICY
        if prompt_data.get("input_priority_policy") not in (None, INPUT_PRIORITY_POLICY):
            self.error("提示词索引input_priority_policy未知，不能跳过新规则")
        priority_required = prompt_data.get("input_priority_policy") == INPUT_PRIORITY_POLICY
        if not framing_required:
            self.warn("提示词索引未声明information_first_v1；需核对批准的身体裁切与背景层级")
        for i, panel in enumerate(panels):
            label = f"提示词索引[{i}]"
            if not isinstance(panel, dict):
                continue
            for key in ("panel_id", "script_shot_id", "station_id", "camera_view_id", "camera_view_signature", "visible_region", "view_check", "prompt", "negative_prompt", "script_lock_check", "locked_script", "visual_analysis"):
                if panel.get(key) in (None, ""):
                    self.error(f"{label}:缺少{key}")
            self.check_script_lock(panel, label)
            self.check_input_priority(panel, label, priority_required, prompt=True)
            self.check_framing(panel, label, framing_required)
            identity_required = prompt_data.get("identity_policy") == IDENTITY_POLICY
            self.check_refs(panel, label, self.prompt_root if identity_required else None, allow_empty=identity_required)
            self.check_prompt_conflicts(panel, label)
            if (prompt_data.get("continuity_policy") == CONTINUITY_POLICY
                    or prompt_data.get("identity_policy") == IDENTITY_POLICY
                    or 'background_treatment' in (panel.get('framing') or {})):
                actual = safe(self.prompt_root, panel.get("prompt_file", f"{panel.get('panel_id')}/prompt.txt"))
                if not actual or not actual.is_file():
                    self.error(f"{label}:实际prompt.txt缺失或路径越界")
                elif actual.read_text(encoding="utf-8-sig").strip() != str(panel.get("prompt", "")).strip():
                    self.error(f"{label}:实际prompt.txt与manifest不一致，参考用途不可只存在于索引")
                details = safe(self.prompt_root, panel.get("panel_json_file", f"{panel.get('panel_id')}/提示词.json"))
                if not details or not details.is_file():
                    self.error(f"{label}:逐格提示词.json缺失或路径越界")
                else:
                    try:
                        detail = load(details)
                    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                        self.error(f"{label}:逐格JSON无法读取: {exc}")
                        detail = None
                    detail_keys = ["prompt", "continuity_contract", "reference_bindings", "reference_usage_block"]
                    if panel.get('input_quality_policy'):detail_keys.append('input_quality_policy')
                    if panel.get('background_policy'):
                        detail_keys.append('background_policy')
                    if 'background_treatment' in (panel.get('framing') or {}):
                        detail_keys.extend(('framing', 'visible_region'))
                    if prompt_data.get('frame_ratio_policy')=='content_balanced_ratios_v1':detail_keys.extend(('frame_ratio','frame_ratio_reason','frame_ratio_execution_block'))
                    if panel.get("visual_evidence_policy"):
                        detail_keys.extend(("visual_evidence_policy", "visual_evidence", "visual_evidence_context", "visual_execution_block", "repair_source"))
                    if priority_required:
                        detail_keys.append("visual_resolution")
                    if prompt_data.get("reference_input_policy") == "codex_reference_v1":
                        detail_keys.extend(("composition_reference", "reference_images", "ratio_tolerance", "transparent_background"))
                    if prompt_data.get("identity_policy") == IDENTITY_POLICY:
                        detail_keys.extend(("script_character_labels", "character_bindings", "scene_binding", "identity_execution_block"))
                    for key in detail_keys:
                        if not isinstance(detail, dict) or detail.get(key) != panel.get(key):
                            self.error(f"{label}:逐格JSON的{key}与manifest不一致")
            shot = shot_by_id.get(panel.get("panel_id"))
            if shot:
                for issue in input_bindings(shot, panel):
                    self.error(f'{label}:{issue}')
                for issue in background_binding_errors(shot, panel):
                    self.error(f'{label}:{issue}')
                for key in ("script_shot_id", "station_state_id", "camera_view_id", "camera_view_signature"):
                    prompt_key = "station_id" if key == "station_state_id" else key
                    if panel.get(prompt_key) != shot.get(key):
                        self.error(f"{label}:{prompt_key}与镜头改编表不一致")
                if shot.get("framing") is not None and panel.get("framing") != shot["framing"]:
                    self.error(f"{label}:framing与镜头改编表不一致，不能擅自扩大或改变批准构图")
                if priority_required and panel.get("visual_resolution") != shot.get("visual_resolution"):
                    self.error(f"{label}:visual_resolution与批准镜头表不一致")
                for key in ("continuity_contract", "reference_bindings"):
                    if shot.get(key) is not None and panel.get(key) != shot[key]:
                        from calibration_repair import binding_extension_valid
                        from visual_evidence import repair_binding_extension_valid
                        if key!='reference_bindings' or not (binding_extension_valid(prompt_data,panel,shot,self.prompt_root) or repair_binding_extension_valid(panel,shot)):
                            self.error(f"{label}:{key}与镜头改编表不一致，须保留批准合同与用途")
                if prompt_data.get("reference_input_policy") == "codex_reference_v1" and panel.get("composition_reference") != shot.get("composition_reference"):
                    self.error(f"{label}:composition_reference与批准镜头表不一致")
                if prompt_data.get("identity_policy") == IDENTITY_POLICY:
                    for key in ("script_character_labels", "character_bindings", "scene_binding"):
                        if panel.get(key) != shot.get(key):
                            self.error(f"IDENTITY_HOLD: {label}:{key}与镜头改编表不一致，须重新确认并同步")
        if numbers and len(shot_panels) != len(panels):
            self.error("镜头改编表与提示词格数不一致")

    def run(self, shot_path: Path, prompt_path: Path) -> dict[str, Any]:
        self.prompt_root = prompt_path.parent.resolve()
        self.shot_root = shot_path.parent.resolve()
        if not shot_path.is_file():
            self.error(f"镜头改编表不存在: {shot_path}")
            shot_panels: list[dict[str, Any]] = []
        else:
            shot_data = load(shot_path)
            self.shot_preparation_policy = shot_data.get("preparation_policy") if isinstance(shot_data, dict) else None
            shot_panels = self.check_shots(shot_data)
            try:
                self.errors.extend(validate_identity(shot_data, self.root))
            except (OSError, ValueError, TypeError, KeyError) as exc:
                self.error(f"IDENTITY_HOLD: 镜头表身份依据或绑定无法核验: {exc}")
        if not prompt_path.is_file():
            self.error(f"提示词索引不存在: {prompt_path}")
        else:
            prompt_data = load(prompt_path)
            if shot_path.is_file() and isinstance(shot_data, dict) and isinstance(prompt_data, dict):
                if shot_data.get("input_priority_policy") != prompt_data.get("input_priority_policy"):
                    self.error("镜头表与提示词包input_priority_policy不一致")
                if shot_data.get("continuity_policy") != prompt_data.get("continuity_policy"):
                    self.error("镜头表与提示词包continuity_policy不一致，不能只迁移其中一份或降级")
                if shot_data.get("reference_input_policy") != prompt_data.get("reference_input_policy"):
                    self.error("镜头表与提示词包reference_input_policy不一致")
                for key in ("identity_policy", "book_id", "episode_id", "identity_registry"):
                    if shot_data.get(key) != prompt_data.get(key):
                        self.error(f"IDENTITY_HOLD: 镜头表与提示词包{key}不一致，不能只迁移其中一份")
            self.check_prompt(prompt_data, shot_panels)
        status = "HOLD" if self.errors else ("PASS_WITH_WARNINGS" if self.warnings else "PASS")
        return {"status": status, "errors": self.errors, "warnings": self.warnings, "shot_manifest": str(shot_path), "prompt_manifest": str(prompt_path),
                "scope": "STRUCTURAL_AND_INPUT_CONSISTENCY_ONLY", "user_approval": "NOT_GRANTED",
                "visual_rule_acceptance": "REQUIRES_APPLICABLE_RULES_AND_ACTUAL_IMAGE_QA"}


def main() -> int:
    parser = argparse.ArgumentParser(description="条漫前期镜头、空间与提示词包门禁")
    parser.add_argument("--root", required=True, help="本话前期制作根目录")
    parser.add_argument("--shot-manifest", default=None)
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--report", default=None)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    shot = Path(args.shot_manifest).resolve() if args.shot_manifest else root / "01_镜头改编_CANDIDATE" / "镜头改编表.json"
    prompt = Path(args.manifest).resolve() if args.manifest else root / "04_B提示词包_CANDIDATE" / "全话提示词索引.json"
    result = Gate(root).run(shot, prompt)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    print(output, end="")
    if args.report:
        Path(args.report).write_text(output, encoding="utf-8", newline='\n')
    return 1 if result["status"] == "HOLD" else 0


if __name__ == "__main__":
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
