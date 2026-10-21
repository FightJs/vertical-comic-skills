#!/usr/bin/env python3
"""Codex local-reference contract. Never generates images or grants approval."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
from contextlib import contextmanager
from contextvars import ContextVar
import copy
from typing import Any

BACKEND = "codex_builtin_imagegen"
POLICY = "codex_reference_v1"
RASTER = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
# Observed local-tool rejection on 2026-10-12, not an Image API limit.
MAX_REFERENCE_PATHS = 5
_FILE_SESSION = ContextVar("comic_read_transaction", default=None)
_READ_VIEW = ContextVar("comic_immutable_read_view", default=None)
READ_POLICY = 'read_dependencies_v2'


def physical_file(path):
    """I/O location only; logical paths remain the identity used by validators."""
    view = _READ_VIEW.get()
    return Path(path) if view is None else view.physical(path)


def _changed(reason):
    memo = _FILE_SESSION.get()
    message = 'CHECK_SNAPSHOT_CHANGED: ' + str(reason)
    if memo is not None:
        if memo['invalidated'] is None:
            memo['invalidated'] = message
            memo['dependency_invalidations'] += 1
        message = memo['invalidated']
    raise ValueError(message)


def _valid():
    view = _READ_VIEW.get()
    if view is not None: view.check()
    memo = _FILE_SESSION.get()
    if memo is not None and memo['invalidated'] is not None:
        raise ValueError(memo['invalidated'])
    return memo


def _depend(token):
    memo = _valid()
    if memo is not None and memo['dependency_stack']:
        memo['dependency_stack'][-1].add(token)


def _observe(kind, path, value, options=()):
    memo = _valid()
    if memo is not None:
        token = (kind, os.path.abspath(path), options)
        _depend(token)
        if token in memo['observations'] and memo['observations'][token] != value:
            _changed(f'{kind}: {path}')
        if token not in memo['observations'] and value is False:
            memo['negative_observations'] += 1
        memo['observations'][token] = value
    return value


def resolve_path(path, *, strict=False):
    """Retain the logical reference before a caller canonicalizes its target."""
    _valid()
    view = _READ_VIEW.get()
    target = Path(path).resolve(strict=strict) if view is None else Path(view.query('resolve', path, (strict,)))
    _observe('resolve', path, str(target), (strict,))
    return target


def path_exists(path):
    resolve_path(path)
    view = _READ_VIEW.get()
    return _observe('exists', path, Path(path).exists() if view is None else view.query('exists', path))


def is_file(path):
    resolve_path(path)
    view = _READ_VIEW.get()
    return _observe('is_file', path, Path(path).is_file() if view is None else view.query('is_file', path))


def is_dir(path):
    resolve_path(path)
    view = _READ_VIEW.get()
    return _observe('is_dir', path, Path(path).is_dir() if view is None else view.query('is_dir', path))


def is_symlink(path):
    resolve_path(path)
    view = _READ_VIEW.get()
    return _observe('is_symlink', path, Path(path).is_symlink() if view is None else view.query('is_symlink', path))


def scan_directory(path, *, recursive=False, suffixes=(), excluded_parts=(), excluded_names=(), excluded_suffixes=(), excluded_paths=()):
    """Observe the complete matching name/type/target set, including empty sets.

    Filters are part of the dependency key. Bytecode and OS metadata exclusions
    are chosen explicitly by each caller, never inferred from a previous scan.
    """
    base = Path(path)
    resolve_path(base)
    present = is_dir(base)
    options = (recursive, tuple(suffixes), tuple(excluded_parts), tuple(excluded_names), tuple(excluded_suffixes), tuple(excluded_paths))
    view = _READ_VIEW.get()
    if view is not None:
        signature = view.query('directory', base, options)
        memo = _valid()
        if memo is not None: memo['directory_scans'] += 1
        _observe('directory', base, signature, options)
        return [base/row[0] for row in signature]
    result = []
    signature = []
    try:
        entries = base.rglob('*') if recursive else base.iterdir()
        for item in entries:
            relative = item.relative_to(base)
            if (set(relative.parts) & set(excluded_parts) or item.name in excluded_names or relative.as_posix() in excluded_paths
                    or item.suffix in excluded_suffixes or suffixes and item.suffix not in suffixes):
                continue
            result.append(item)
            signature.append((relative.as_posix(), item.is_file(), item.is_dir(), item.is_symlink(), str(item.resolve())))
    except OSError:
        if present and _valid() is not None:
            _changed(f'{path}; directory enumeration failed')
        raise
    memo = _valid()
    if memo is not None:
        memo['directory_scans'] += 1
    _observe('directory', base, tuple(sorted(signature)), options)
    return result


def recheck_dependencies(dependencies):
    """Replay positive, negative, path-target and directory observations."""
    memo = _valid()
    for token in dependencies:
        if memo is not None:
            memo['dependency_checks'] += 1
        if isinstance(token, str):
            digest(Path(token))
            continue
        kind, name, options = token
        if kind == 'directory':
            recursive, suffixes, parts, names, excluded_suffixes, excluded_paths = options
            scan_directory(name, recursive=recursive, suffixes=suffixes, excluded_parts=parts,
                           excluded_names=names, excluded_suffixes=excluded_suffixes, excluded_paths=excluded_paths)
        elif kind == 'resolve':
            resolve_path(name, strict=options[0])
        else:
            {'exists': path_exists, 'is_file': is_file, 'is_dir': is_dir, 'is_symlink': is_symlink}[kind](name)


def read_bytes(path):
    if _valid() is None:
        return physical_file(path).read_bytes()
    digest(Path(path))
    try:
        data = physical_file(path).read_bytes()
        digest(Path(path))  # Recheck the same file stamp after this physical read.
    except OSError:
        _changed(f'{path}; file read failed after validation')
    _FILE_SESSION.get()['content_read_bytes'] += len(data)
    return data


def read_text(path, encoding=None, errors=None):
    if _valid() is None:
        return physical_file(path).read_text(encoding=encoding, errors=errors)
    digest(Path(path))
    try:
        value = physical_file(path).read_text(encoding=encoding, errors=errors)
        digest(Path(path))
        _FILE_SESSION.get()['content_read_bytes'] += physical_file(path).stat().st_size
    except OSError:
        _changed(f'{path}; text read failed after validation')
    return value


@contextmanager
def file_session():
    """Read-only transaction cache; changes during a check fail closed."""
    active = _FILE_SESSION.get()
    if active is not None:
        _valid()
        yield active
        return
    memo = {"files": {}, "json": {}, "hash_reads": 0, "hash_hits": 0,"validations":{},"validation_runs":0,"validation_hits":0,
            "readonly_json": {}, "derived": {}, "dependency_stack": [], "audit_statistics": {}, "paths": {},
            "validation_dependencies": {}, "hash_bytes": 0, "json_parses": 0, "json_hits": 0,
            "policy": READ_POLICY, "observations": {}, "invalidated": None,
            "dependency_checks": 0, "dependency_invalidations": 0, "negative_observations": 0,
            "directory_scans": 0, "content_read_bytes": 0}
    token = _FILE_SESSION.set(memo)
    try:
        yield memo
        _valid()
        recheck_dependencies(tuple(memo['observations']))
        # A cached result may not reread every file before the caller returns.
        # Recheck the complete read set at the outer transaction boundary.
        for name, target in memo['paths'].items():
            if str(resolve_path(name)) != target:
                _changed(f'{name}; reference target changed')
        for name, (stamp, _) in memo['files'].items():
            try:
                current = physical_file(name).stat()
            except OSError as exc:
                _changed(name)
            if stamp != (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns):
                _changed(name)
    finally:
        _FILE_SESSION.reset(token)


def digest(path: Path) -> str:
    logical = os.path.abspath(path)
    path = resolve_path(path)
    memo = _valid()
    if memo is None:
        return hashlib.sha256(physical_file(path).read_bytes()).hexdigest()
    if memo['paths'].setdefault(logical, str(path)) != str(path):
        _changed(f'{logical}; reference target changed')
    try:
        stat = physical_file(path).stat()
    except OSError:
        is_file(logical)
        if str(path) in memo['files']:
            _changed(logical)
        raise
    _depend(logical)
    stamp = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    saved = memo["files"].get(str(path))
    if saved:
        if saved[0] != stamp:
            _changed(path.name)
        memo["hash_hits"] += 1
        return saved[1]
    try:
        data = physical_file(path).read_bytes()
        value = hashlib.sha256(data).hexdigest()
        after = physical_file(path).stat()
    except OSError:
        _changed(f'{logical}; file changed during hashing')
    if stamp != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        _changed(path.name)
    memo["files"][str(path)] = (stamp, value)
    memo["hash_reads"] += 1
    memo["hash_bytes"] += len(data)
    return value


def read_json(path: Path):
    memo = _FILE_SESSION.get()
    if memo is None:
        return json.loads(read_text(path, encoding="utf-8-sig"))
    key = (str(resolve_path(path)), digest(path))
    if key not in memo["json"]:
        memo["json"][key] = json.loads(read_text(path, encoding="utf-8-sig"))
        memo['json_parses'] += 1
    else:
        memo['json_hits'] += 1
    return copy.deepcopy(memo["json"][key])


def read_json_readonly(path: Path):
    """Opt-in shared immutable JSON; read_json retains its mutable-copy API."""
    from audit_cache import freeze
    memo = _FILE_SESSION.get()
    if memo is None:
        return freeze(read_json(path))
    key = (str(resolve_path(path)), digest(path))
    if key not in memo['readonly_json']:
        if key not in memo['json']:
            memo['json'][key] = json.loads(read_text(path, encoding='utf-8-sig'))
            memo['json_parses'] += 1
        else:
            memo['json_hits'] += 1
        memo['readonly_json'][key] = freeze(memo['json'][key])
    else:
        memo['json_hits'] += 1
    return memo['readonly_json'][key]

def memoized_validation(namespace,key,compute,*,options=None):
    """Successful deterministic checks only, within an unchanged read transaction."""
    memo=_valid()
    if memo is None:return compute()
    from audit_cache import content_key
    token=content_key([READ_POLICY,namespace,key,options])
    if token in memo['validations']:
        recheck_dependencies(memo['validation_dependencies'][token])
        memo['validation_hits']+=1;return copy.deepcopy(memo['validations'][token])
    memo['validation_runs']+=1
    dependencies=set();memo['dependency_stack'].append(dependencies)
    try:
        result=compute()
        if result==[]:
            memo['validations'][token]=copy.deepcopy(result)
            memo['validation_dependencies'][token]=tuple(sorted(dependencies, key=repr))
        return result
    finally:
        memo['dependency_stack'].pop()
        if memo['dependency_stack']:memo['dependency_stack'][-1].update(dependencies)


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def ratio(value: Any) -> float | None:
    if type(value) in (int, float):
        return float(value) if math.isfinite(value) and value > 0 else None
    match = re.fullmatch(r"\s*([1-9]\d*)\s*[:：]\s*([1-9]\d*)\s*", value) if isinstance(value, str) else None
    return int(match[1]) / int(match[2]) if match else None


def final_prompt(prompt: str, negative: str) -> str:
    """Merge relevant avoid constraints; no separate negative tool argument."""
    prompt, negative = prompt.strip(), negative.strip()
    return prompt if not negative or negative in prompt else prompt + "\n\n避免：\n" + negative


def checked_file(root: Path, item: Any) -> Path:
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        raise ValueError("缺少文件路径/哈希")
    rel = Path(item["path"])
    path = resolve_path(root / rel)
    if rel.is_absolute() or not path.is_relative_to(resolve_path(root)) or not is_file(path):
        raise ValueError("文件缺失或不是包内相对路径")
    if digest(root / rel) != str(item.get("sha256", "")).lower():
        raise ValueError("文件SHA256缺失或不匹配")
    return path


def composition_errors(panel: dict[str, Any]) -> list[str]:
    value = panel.get("composition_reference")
    if not isinstance(value, dict):
        return ["缺少composition_reference方案"]
    errors = []
    mode = value.get("mode")
    if not isinstance(mode, str) or mode not in {"CREATE", "REUSE", "NOT_REQUIRED"}:
        errors.append("构图参考mode须为CREATE/REUSE/NOT_REQUIRED")
    if not isinstance(value.get("reason"), str) or not value["reason"].strip():
        errors.append("构图参考须说明制作/复用/豁免理由")
    if mode == "NOT_REQUIRED":
        if value.get("alias"):
            errors.append("NOT_REQUIRED不能同时指定构图图片")
        if panel.get("composition_required") is True:
            errors.append("已登记需要构图参考的格不能豁免")
    elif isinstance(mode, str) and mode in {"CREATE", "REUSE"}:
        if not isinstance(value.get("alias"), str) or not value["alias"].startswith("@"):
            errors.append("构图参考缺少实际图片别名")
        if not isinstance(value.get("review_evidence"), dict):
            errors.append("构图参考缺少空间/视角核对证据")
    return errors


def validate_panel(panel: dict[str, Any], root: Path, *, enforce_input_budget: bool = True) -> tuple[list[str], dict[str, Any] | None]:
    """Verify package files and review-record consistency, not visual truth."""
    root = resolve_path(root)
    errors = composition_errors(panel)
    from visual_evidence import panel_errors as visual_panel_errors
    errors.extend(visual_panel_errors(panel, prompt=True))
    from input_quality import scene_reference_errors
    errors.extend(scene_reference_errors(panel, root))
    refs = panel.get("reference_images")
    refs = refs if isinstance(refs, list) else []
    if enforce_input_budget and len(refs) > MAX_REFERENCE_PATHS:
        errors.append(f"REFERENCE_LIMIT_HOLD: 当前Codex入口最多{MAX_REFERENCE_PATHS}个参考路径，实际{len(refs)}条；先合并同图用途，不能截断必需参考")
    paths, aliases = [], []
    bindings = panel.get("reference_bindings")
    bindings = bindings if isinstance(bindings, list) else []
    bound = {b.get("alias") for b in bindings if isinstance(b, dict) and isinstance(b.get("alias"), str)}
    if not refs:
        errors.append("参考图路线没有实际图片输入")
    for index, ref in enumerate(refs):
        if not isinstance(ref, dict):
            errors.append(f"参考图{index + 1}不是对象")
            continue
        alias = ref.get("alias")
        if not isinstance(alias, str) or not alias.startswith("@") or alias in aliases:
            errors.append("参考图片别名缺失或重复")
            continue
        aliases.append(alias)
        if alias not in bound:
            errors.append(f"{alias}缺少参考用途绑定")
        if ref.get('derivation_policy')=='faithful_atlas_v1':
            uses=[b for b in bindings if b.get('alias')==alias]
            owners={s for b in uses for s in b.get('subject_ids',[])}
            if any(b.get('purpose') not in {'identity','costume_state'} for b in uses) or owners!=set(ref.get('subject_ids',[])):
                errors.append(f'{alias}:忠实图集须只绑定准确入画人物的身份/衣装，不能替代画风或其他用途')
        # A rasterized annotated top-down map remains a review document.
        role = str(ref.get("role", ""))
        if ref.get("contains_annotations") is True or ref.get("reference_kind") == "station_map" or "站位图" in role:
            errors.append(f"{alias}标注站位图须移至supporting_documents")
        try:
            path = checked_file(root, ref)
            if path.suffix.lower() not in RASTER:
                raise ValueError("不是当前本地参考路线的栅格图片")
            from PIL import Image
            with Image.open(physical_file(path)) as opened:
                opened.verify()
            if enforce_input_budget and str(path) in paths:
                errors.append(f"REFERENCE_DUPLICATE_HOLD:{alias}:同一文件重复占输入槽；只登记一个别名，保留所有用途绑定并重编译prompt")
            paths.append(str(path))
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"{alias}: {exc}")
    if bound != set(aliases):
        errors.append("用途绑定和实际图片别名不一致")
    preserved=(panel.get('repair_source') or {}).get('preservation_regions')
    if preserved:
        try:
            base=next(r for r in refs if r.get('sha256')==panel['repair_source'].get('image_sha256'))
            from reference_atlas import rect
            from PIL import Image
            with Image.open(physical_file(checked_file(root,base))) as original:
                for box in preserved.values():rect(box,original.size)
        except (StopIteration,OSError,ValueError,TypeError,AttributeError) as exc:
            errors.append('REPAIR_INPUT_HOLD:保留区域无法绑定真实底图有效像素:'+str(exc))
    prompt = panel.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        errors.append("最终prompt缺失")
        prompt = ""
    elif final_prompt(prompt, str(panel.get("negative_prompt") or "")) != prompt.strip():
        errors.append("Codex必要负向约束尚未编入最终prompt")
    prompt_file = panel.get("prompt_file", f"{panel.get('panel_id')}/prompt.txt")
    if 'semantic_facts' in panel or 'subject_visibility' in panel:
        from input_semantics import conflict_errors
        errors.extend(conflict_errors(panel, prompt))
    try:
        file = resolve_path(root / str(prompt_file))
        if Path(str(prompt_file)).is_absolute() or not file.is_relative_to(root) or read_text(file, encoding='utf-8-sig').strip() != prompt.strip():
            raise ValueError("实际prompt.txt与索引不一致或路径越界")
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    value = panel.get("composition_reference") or {}
    if isinstance(value, dict) and isinstance(value.get("mode"), str) and value.get("mode") in {"CREATE", "REUSE"}:
        alias = value.get("alias")
        ref = next((r for r in refs if isinstance(r, dict) and r.get("alias") == alias), None)
        if ref is None:
            errors.append("构图别名没有对应实际图片")
        if not any(isinstance(b, dict) and b.get("alias") == alias and b.get("purpose") == "framing" and b.get("subject_ids") == [panel.get("panel_id")] for b in bindings):
            errors.append("构图图片须绑定本格framing用途")
        try:
            review = read_json(checked_file(root, value.get('review_evidence')))
            expected = {k: panel.get(k) for k in ("panel_id", "camera_view_id", "camera_view_signature", "framing", "frame_ratio")}
            numeric_ratio = ratio(panel.get("frame_ratio"))
            reviewed_ratio = ratio(review.get("frame_ratio"))
            same_ratio = numeric_ratio is not None and reviewed_ratio is not None and abs(numeric_ratio - reviewed_ratio) <= 1e-12
            if any(v is None for v in expected.values()) or not same_ratio or any(review.get(k) != v for k, v in expected.items() if k != "frame_ratio"):
                errors.append("构图核对记录与本格批准机位/裁切/比例不一致")
            if review.get("status") != "REVIEWED" or not review.get("reviewer") or not review.get("evidence") or review.get("reference_sha256") != (ref or {}).get("sha256"):
                errors.append("构图核对未完成或未绑定当前图片")
            if review.get("clean_camera_view") is not True:
                errors.append("构图图片未记录为干净的摄影机视角")
            if ref is not None:
                from PIL import Image
                with Image.open(physical_file(checked_file(root, ref))) as opened:
                    actual = opened.width / opened.height
                target = ratio(panel.get("frame_ratio"))
                if target is None or abs(actual - target) / target > 0.001:
                    errors.append("构图图片实际比例与目标画幅不一致")
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            errors.append(f"构图核对证据无效: {exc}")
    if "ratio_tolerance" not in panel or type(panel["ratio_tolerance"]) not in (int, float) or not math.isfinite(panel["ratio_tolerance"]) or not 0 <= panel["ratio_tolerance"] < 1:
        errors.append("须登记0<=ratio_tolerance<1；0表示精确比例")
    if type(panel.get("transparent_background")) is not bool:
        errors.append("须显式登记transparent_background")
    if panel.get("style_policy") is not None:
        from style_contract import validate_style
        errors.extend(validate_style(panel, root))
    if errors:
        return errors, None
    return [], {"tool": "image_gen.imagegen", "arguments": {"prompt": prompt.strip(), "referenced_image_paths": paths, "transparent_background": panel["transparent_background"]}, "reference_order": aliases, "reference_files": [{"alias": r["alias"], "path": r["path"], "sha256": r["sha256"]} for r in refs]}


def execution_errors(execution: dict[str, Any], submission: dict[str, Any], root: Path, panel_id: str) -> list[str]:
    errors = []
    try:
        req = read_json(checked_file(root, execution.get('request_evidence')))
        res = read_json(checked_file(root, execution.get('response_evidence')))
        attempt = execution.get("attempt_id")
        if not isinstance(attempt, str) or not attempt.strip() or req.get("attempt_id") != attempt or res.get("attempt_id") != attempt:
            errors.append("本地attempt_id缺失或调用/返回无法对应")
        if req.get("backend_id") != BACKEND or req.get("panel_id") != panel_id or req.get("tool") != submission["tool"] or req.get("arguments") != submission["arguments"] or req.get("reference_order") != submission["reference_order"] or req.get("reference_files") != submission["reference_files"]:
            errors.append("实际工具调用的提示词/图片顺序/参数与本格输入不一致")
        if req.get("source_kind") != "observed_tool_call" or not req.get("source_locator"):
            errors.append("缺少真实工具调用来源；计划不能充当执行证据")
        if res.get("source_kind") != "observed_tool_result" or not res.get("source_locator") or res.get("status") != "COMPLETED":
            errors.append("缺少真实工具返回来源或未完成")
        if not isinstance(res.get("outputs"), list) or not res["outputs"]:
            errors.append("缺少实际返回图片证据")
        for item in res.get("outputs", []):
            from PIL import Image
            with Image.open(physical_file(checked_file(root, item))) as opened:
                opened.verify()
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        errors.append(f"执行证据无效: {exc}")
    return errors


def invalidate_execution(panel: dict[str, Any]) -> None:
    """Repair changes prompts/paths: retain historical evidence only for audit."""
    old = panel.get("generation_execution")
    if isinstance(old, dict) and old.get("status") != "NOT_RUN":
        panel.setdefault("generation_execution_history", []).append(old)
    if old is not None:
        panel["generation_execution"] = {"status": "NOT_RUN", "reason": "INPUTS_REBUILT_REQUIRES_NEW_EXECUTION_EVIDENCE"}
    if "structural_control_executed" in panel:
        panel["structural_control_executed"] = False


def copy_contract_evidence(source: Path, output: Path, manifest: dict[str, Any]) -> list[str]:
    """Preserve actual capability/composition evidence, without inventing reviews."""
    items = [((manifest.get("generation_backend") or {}).get("evidence"), "backend")]
    items += [((p.get("composition_reference") or {}).get("review_evidence"), p.get("panel_id")) for p in manifest.get("panels", []) if isinstance(p, dict)]
    items += [(r.get("approval_evidence"), p.get("panel_id"))
              for p in manifest.get("panels", []) if isinstance(p, dict)
              for r in p.get("reference_images", []) if isinstance(r, dict) and r.get("approval_evidence")]
    errors = []
    for item, label in items:
        if item is None:
            continue
        try:
            path = checked_file(resolve_path(source), item)
            target = output / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"{label}: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="核对并导出Codex逐格参考调用计划；不执行生图")
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--output", required=True, help="新的调用计划JSON文件")
    args = parser.parse_args()
    root, output = resolve_path(Path(args.package_root)), resolve_path(Path(args.output))
    if path_exists(output):
        raise SystemExit("拒绝覆盖已有输出")
    data = read_json(root / '全话提示词索引.json')
    from check_control_inputs import validate_manifest
    report = validate_manifest(data, root)
    plans = []
    if (data.get("generation_backend") or {}).get("backend_id") != BACKEND:
        report["errors"].append("该导出器仅适用于codex_builtin_imagegen")
    if report["errors"]:
        report["status"] = "HOLD"
    else:
        for panel in data["panels"]:
            _, plan = validate_panel(panel, root)
            plans.append({"panel_id": panel["panel_id"], "status": "NOT_RUN", **plan})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"status": report["status"], "errors": report["errors"], "image_acceptance": "NOT_ASSESSED", "plans": plans}, ensure_ascii=False, indent=2) + "\n", encoding='utf-8', newline='\n')
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
