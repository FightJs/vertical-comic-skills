#!/usr/bin/env python3
"""Check declared generation capabilities, control inputs and execution evidence.

This verifies a local contract, not provider internals, spatial truth or image
quality. It never invokes a generator or upgrades an image to accepted status.
"""
from __future__ import annotations
from codex_reference_contract import is_file, read_json, resolve_path, digest

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any
from codex_reference_contract import BACKEND as CODEX_BACKEND, POLICY as CODEX_POLICY, validate_panel as validate_codex_panel, execution_errors as codex_execution_errors
from continuity_contract import validate_manifest as validate_continuity

POLICY = "structural_guidance_v1"
MODES = {"text_only", "reference_guided", "structural_control"}
TYPES = {"pose", "edges", "depth", "segmentation"}
SOURCES = {"camera_view_render", "pose_extraction", "edge_extraction", "depth_estimation", "segmentation"}


def sha(path: Path) -> str:
    return digest(path)


def positive(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        return False


def ratio(value: Any) -> float | None:
    if positive(value):
        return float(value)
    match = re.fullmatch(r"\s*([1-9]\d*)\s*[:：]\s*([1-9]\d*)\s*", value) if isinstance(value, str) else None
    if match:
        try:
            result = int(match[1]) / int(match[2])
            return result if positive(result) else None
        except (ValueError, OverflowError):
            pass
    return None


def validate_manifest(data: Any, root: Path, phase: str = "preflight") -> dict[str, Any]:
    root = resolve_path(root)
    errors: list[str] = []
    warnings: list[str] = []
    panels_out: list[dict[str, Any]] = []

    def error(label: str, message: str) -> None:
        errors.append(f"{label}: {message}")

    def evidence(item: Any, label: str) -> Path | None:
        if not isinstance(item, dict):
            error(label, "缺少文件与哈希证据")
            return None
        rel, expected = item.get("path"), item.get("sha256")
        if not isinstance(rel, str) or not rel.strip() or Path(rel).is_absolute():
            error(label, "证据必须使用包内相对路径")
            return None
        path = resolve_path(root / rel)
        if not path.is_relative_to(root) or not is_file(path):
            error(label, "文件缺失或越出包目录")
            return None
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected) or sha(path).lower() != expected.lower():
            error(label, "SHA256缺失或不匹配")
            return None
        return path

    def model(value: Any) -> bool:
        return isinstance(value, dict) and all(isinstance(value.get(k), str) and value[k].strip() for k in ("id", "revision"))

    if not isinstance(data, dict):
        return {"status": "HOLD", "errors": ["manifest必须是对象"], "warnings": [], "panels": [], "structural_control_executed": False, "image_acceptance": "NOT_ASSESSED"}
    panels = data.get("panels", [])
    staged = data.get("workflow_policy") == "staged_comic_v1"
    if staged and data.get("style_policy") != "approved_style_v1":
        error("manifest", "阶段化生图不能删除approved_style_v1")
    policy = data.get("control_policy")
    declared = staged or data.get("style_policy") is not None or "generation_backend" in data or (isinstance(panels, list) and any(isinstance(p, dict) and any(k in p for k in ("control_inputs", "generation_execution", "structural_control_executed")) for p in panels))
    if policy is None and not declared:
        if phase == "execution":
            return {"status": "HOLD", "errors": ["旧包无能力登记或执行证据，不能通过执行核验"], "warnings": [], "panels": [], "structural_control_executed": False, "image_acceptance": "NOT_ASSESSED"}
        return {"status": "LEGACY_NOT_ASSESSED", "errors": [], "warnings": ["旧包未登记结构控制能力；未授予新增门禁或控制已执行状态"], "panels": [], "structural_control_executed": False, "image_acceptance": "NOT_ASSESSED"}
    if policy != POLICY:
        error("manifest", f"control_policy必须为{POLICY}；不能删策略来绕过声明")
    backend = data.get("generation_backend")
    if not isinstance(backend, dict):
        backend = {}
        error("generation_backend", "缺少能力登记")
    backend_id, mode = backend.get("backend_id"), backend.get("mode")
    codex = backend_id == CODEX_BACKEND
    if codex and (mode != "reference_guided" or data.get("reference_input_policy") != CODEX_POLICY):
        error("generation_backend", "Codex须使用reference_guided及codex_reference_v1")
    if codex:
        if data.get("continuity_policy") != "reference_continuity_v1":
            error("manifest", "Codex参考分支须保留reference_continuity_v1")
        continuity_errors, continuity_warnings = validate_continuity(data,root=root)
        errors.extend(continuity_errors)
        warnings.extend(continuity_warnings)
    if not isinstance(backend_id, str) or not backend_id.strip():
        error("generation_backend", "backend_id缺失")
    if not isinstance(mode, str) or mode not in MODES:
        error("generation_backend", "能力未知或mode非法，不能猜测可用接口")
    evidence(backend.get("evidence"), "generation_backend.evidence")
    capabilities = backend.get("structural_controls")
    if not isinstance(capabilities, list):
        capabilities = []
        error("generation_backend", "structural_controls必须为数组；普通上传填空数组")
    if mode != "structural_control" and capabilities:
        error("generation_backend", "普通参考/文本路线不能声明结构控制接口")
    if mode == "structural_control" and (not capabilities or not isinstance(backend.get("base_model"), str) or not backend["base_model"].strip()):
        error("generation_backend", "结构控制路线须登记base_model和实际控制接口")
    for index, capability in enumerate(capabilities):
        if not isinstance(capability, dict) or not isinstance(capability.get("type"), str) or capability["type"] not in TYPES or not isinstance(capability.get("input_slot"), str) or not capability["input_slot"].strip() or not model(capability.get("control_model")):
            error(f"capability[{index}]", "控制类型、输入槽或模型/版本无效")
    if not isinstance(panels, list) or not panels:
        error("manifest", "panels不能为空")
        panels = []
    seen: set[str] = set()
    for index, panel in enumerate(panels):
        label = f"panels[{index}]"
        if not isinstance(panel, dict):
            error(label, "必须是对象")
            continue
        pid = panel.get("panel_id")
        if not isinstance(pid, str) or not re.fullmatch(r"P\d{3}", pid) or pid in seen:
            error(label, "panel_id缺失、非法或重复")
        else:
            label = pid
            seen.add(pid)
        start_errors = len(errors)
        submission = None
        if staged or data.get("style_policy") == "approved_style_v1":
            from style_contract import validate_style, output_spec_errors
            for message in validate_style(panel, root):
                error(label, message)
            if staged:
                for message in output_spec_errors(panel):
                    error(label, message)
        if codex:
            ref_errors, submission = validate_codex_panel(panel, root, enforce_input_budget=phase != "execution")
            for message in ref_errors:
                error(label, message)
        controls = panel.get("control_inputs")
        if not isinstance(controls, list):
            controls = []
            error(label, "control_inputs必须显式为数组；不用控制时填[]")
        if controls and mode != "structural_control":
            error(label, "生图端未登记结构控制能力，上传卡片不等于ControlNet")
        size = panel.get("generation_size")
        size_valid = isinstance(size, list) and len(size) == 2 and all(type(v) is int and v > 0 for v in size)
        if controls:
            target_ratio = ratio(panel.get("frame_ratio"))
            if not size_valid or target_ratio is None or abs(size[0] / size[1] - target_ratio) / target_ratio > 0.001:
                error(label, "generation_size缺失或与批准frame_ratio不一致")
        control_ids: set[str] = set()
        request_controls: list[dict[str, Any]] = []
        audit_paths = {resolve_path(root / x['path']) for x in panel.get("supporting_documents", []) if isinstance(x, dict) and isinstance(x.get("path"), str)} if isinstance(panel.get("supporting_documents", []), list) else set()
        for ci, control in enumerate(controls):
            c_label = f"{label}.control_inputs[{ci}]"
            if not isinstance(control, dict):
                error(c_label, "必须是对象")
                continue
            cid = control.get("control_id")
            if not isinstance(cid, str) or not cid.strip() or cid in control_ids:
                error(c_label, "control_id缺失或重复")
            else:
                control_ids.add(cid)
            path = evidence(control, c_label)
            if (path is not None and path in audit_paths) or not isinstance(control.get("source_kind"), str) or control["source_kind"] not in SOURCES or control.get("contains_annotations") is not False:
                error(c_label, "审阅文件/标注卡不能直接充当模型控制图")
            camera_id = panel.get("camera_view_id")
            if not isinstance(camera_id, str) or not camera_id.strip() or control.get("source_camera_view_id") != camera_id:
                error(c_label, "控制图未绑定本格批准摄影机")
            preprocessor = control.get("preprocessor")
            if not model(preprocessor) or not isinstance(preprocessor.get("parameters"), dict):
                error(c_label, "缺少预处理器/版本/参数；手工结构图也需登记manual及编码格式")
            evidence(control.get("view_review_evidence"), c_label + ".view_review_evidence")
            if control.get("view_check") != "PASS":
                error(c_label, "控制图尚未对照批准视角审查")
            if not positive(control.get("strength")):
                error(c_label, "strength必须为正有限数值；不设置跨模型万能强度")
            if not any(isinstance(c, dict) and all(control.get(k) == c.get(k) for k in ("type", "input_slot", "control_model")) for c in capabilities):
                error(c_label, "控制类型、模型/版本或输入槽不匹配能力登记")
            if path:
                try:
                    from PIL import Image
                    from codex_reference_contract import physical_file
                    with Image.open(physical_file(path)) as image:
                        actual_size = list(image.size)
                        image.verify()
                    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or actual_size != control.get("target_size") or not size_valid or actual_size != size:
                        error(c_label, "可解码位图尺寸须同时匹配target_size和generation_size")
                except Exception as exc:
                    error(c_label, f"控制图读取失败: {exc}")
            request_controls.append({k: control.get(k) for k in ("control_id", "path", "sha256", "type", "input_slot", "control_model", "strength")})
        execution = panel.get("generation_execution", {"status": "NOT_RUN"})
        applied = False
        execution_status = "NOT_RUN"
        if not isinstance(execution, dict) or not isinstance(execution.get("status"), str) or execution["status"] not in {"NOT_RUN", "COMPLETED"}:
            error(label, "generation_execution.status非法")
        elif execution.get("status") == "COMPLETED":
            execution_status = "UNVERIFIED"
            if codex:
                if submission is None:
                    error(label, "参考输入无效，不能核验完成记录")
                else:
                    for message in codex_execution_errors(execution, submission, root, pid):
                        error(label, message)
                if len(errors) == start_errors:
                    execution_status = "RECORDED_COMPLETED"
            request = evidence(execution.get("request_evidence"), label + ".request_evidence") if not codex else None
            response = evidence(execution.get("response_evidence"), label + ".response_evidence") if not codex else None
            if request and response:
                try:
                    req = read_json(request)
                    res = read_json(response)
                    request_id = execution.get("request_id")
                    if not isinstance(req, dict) or not isinstance(res, dict) or not isinstance(request_id, str) or not request_id.strip() or req.get("request_id") != request_id or res.get("request_id") != request_id or req.get("backend_id") != backend_id or req.get("panel_id") != pid or req.get("controls") != request_controls or res.get("status") != "COMPLETED":
                        error(label, "执行请求/响应与本格实际控制参数不一致")
                    outputs = res.get("outputs") if isinstance(res, dict) else None
                    if not isinstance(outputs, list) or not outputs:
                        error(label, "执行响应缺少输出文件证据")
                    else:
                        for oi, output in enumerate(outputs):
                            evidence(output, f"{label}.outputs[{oi}]")
                except (OSError, ValueError, TypeError) as exc:
                    error(label, f"执行证据不可读取: {exc}")
                if len(errors) == start_errors:
                    execution_status = "RECORDED_COMPLETED"
                    applied = bool(controls)
        elif phase == "execution":
            error(label, "尚未执行，不能通过执行核验")
        if "structural_control_executed" in panel and type(panel["structural_control_executed"]) is not bool:
            error(label, "structural_control_executed声明须为布尔值，不能用文字冒充")
        if panel.get("structural_control_executed") is True and not applied:
            error(label, "没有匹配执行证据，禁止声明结构控制已执行")
        panels_out.append({"panel_id": pid, "control_count": len(controls), "reference_count": len(panel.get("reference_images", [])) if isinstance(panel.get("reference_images"), list) else 0, "input_status": "INVALID" if len(errors) > start_errors else ("REFERENCE_INPUTS_VALID" if codex and submission else ("INPUTS_VALID" if controls else "NOT_USED")), "execution_status": execution_status, "structural_control_executed": applied})
    if errors:
        for item in panels_out:
            item["structural_control_executed"] = False
    return {"status": "HOLD" if errors else "PASS", "policy": policy, "mode": mode, "errors": errors, "warnings": warnings, "panels": panels_out, "structural_control_executed": not errors and any(p["structural_control_executed"] for p in panels_out), "image_acceptance": "NOT_ASSESSED"}


def main() -> int:
    parser = argparse.ArgumentParser(description="核对生图能力、结构控制输入和执行证据；不生成图片")
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--manifest", default="全话提示词索引.json", help="包内相对路径")
    parser.add_argument("--phase", choices=("preflight", "execution"), default="preflight")
    parser.add_argument("--report", help="新报告路径；已有文件不覆盖")
    args = parser.parse_args()
    root = resolve_path(Path(args.package_root))
    manifest = resolve_path(root / args.manifest)
    try:
        if Path(args.manifest).is_absolute() or not manifest.is_relative_to(root):
            raise ValueError("manifest须为包内相对路径")
        result = validate_manifest(read_json(manifest), root, args.phase)
    except (OSError, ValueError, TypeError) as exc:
        result = {"status": "HOLD", "errors": [str(exc)], "warnings": [], "structural_control_executed": False, "image_acceptance": "NOT_ASSESSED"}
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline='\n') as handle:
            handle.write(output)
    print(output, end="")
    return 1 if result["status"] == "HOLD" else 0


if __name__ == "__main__":
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
