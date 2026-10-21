"""Approved style inputs and recorded review consistency; never visual approval."""
from __future__ import annotations
from codex_reference_contract import read_json

import json
from pathlib import Path

POLICY = "approved_style_v1"
TRAITS = ("linework", "face_proportions", "hair", "coloring", "shading")


def output_spec_errors(panel, size=None, image_format=None):
    spec = panel.get("output_spec")
    if not isinstance(spec, dict):
        return ["OUTPUT_SPEC_HOLD:缺少已确定的output_spec"]
    formats = spec.get("formats")
    if not isinstance(formats, list) or not formats or any(x not in ("PNG", "JPEG", "WEBP") for x in formats):
        return ["OUTPUT_SPEC_HOLD:格式须明确为PNG/JPEG/WEBP列表"]
    if any(type(spec.get(k)) is not int or spec[k] <= 0 for k in ("min_width", "min_height")):
        return ["OUTPUT_SPEC_HOLD:最小宽高须为正整数"]
    exact = spec.get("exact_size")
    if exact is not None and (not isinstance(exact, list) or len(exact) != 2 or any(type(x) is not int or x <= 0 for x in exact)):
        return ["OUTPUT_SPEC_HOLD:精确尺寸无效"]
    errors = []
    if exact is not None and (exact[0] < spec["min_width"] or exact[1] < spec["min_height"]):
        errors.append("OUTPUT_SPEC_HOLD:精确尺寸小于最小规格")
    if size is not None:
        if size[0] < spec["min_width"] or size[1] < spec["min_height"] or (exact is not None and list(size) != exact):
            errors.append("OUTPUT_SPEC_HOLD:实际像素尺寸不符合规格")
        if image_format not in formats:
            errors.append("OUTPUT_SPEC_HOLD:实际图片格式不符合规格")
    return errors


def style_block(contract):
    traits = contract.get("traits", {})
    labels = dict(zip(TRAITS, ("线稿", "五官比例", "发束", "上色", "阴影")))
    lines = ["画风锁定", "批准样例：" + "、".join(contract.get("reference_aliases", []))]
    lines.extend(f"{labels[key]}：{traits.get(key, '')}" for key in TRAITS)
    lines.append("构图、场景、道具和旧候选只迁移其获准用途，不覆盖上述画风。")
    return "\n".join(lines)


def validate_style(panel, root):
    from codex_reference_contract import checked_file
    errors = []
    if panel.get("style_policy") != POLICY:
        return ["缺少approved_style_v1；旧输入须明确迁移"]
    contract = panel.get("style_contract")
    if not isinstance(contract, dict):
        return ["缺少style_contract"]
    aliases = contract.get("reference_aliases")
    if not isinstance(aliases, list) or not aliases or any(not isinstance(x, str) for x in aliases) or len(set(aliases)) != len(aliases):
        return ["画风样例别名为空、重复或无效"]
    refs = {r.get("alias"): r for r in panel.get("reference_images", []) if isinstance(r, dict)}
    bindings = panel.get("reference_bindings", [])
    for alias in aliases:
        ref = refs.get(alias)
        if not ref:
            errors.append(f"{alias}:画风样例未进入实际reference_images")
            continue
        if not any(isinstance(b, dict) and b.get("alias") == alias and b.get("purpose") == "style" for b in bindings):
            errors.append(f"{alias}:缺少style用途绑定")
        if ref.get("reference_kind") not in ("approved_comic_sample", "approved_character_board"):
            errors.append(f"{alias}:风格依据必须是批准样张或人物板，不能是失败候选/构图图")
        try:
            checked_file(root, ref)
            approval = read_json(checked_file(root, ref.get('approval_evidence')))
            if approval.get("status") != "APPROVED" or approval.get("source_kind") != "user_message" or not approval.get("source_locator") or not approval.get("quote"):
                errors.append(f"{alias}:缺少真实用户批准来源")
            if ref.get("sha256") not in approval.get("approved_sha256", []) or approval.get("book_id") != contract.get("book_id"):
                errors.append(f"{alias}:样例批准未覆盖当前文件或本书")
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            errors.append(f"{alias}:画风批准证据无效: {exc}")
    if not contract.get("book_id"):
        errors.append("画风合同缺少book_id")
    traits = contract.get("traits")
    if not isinstance(traits, dict) or any(not isinstance(traits.get(k), str) or not traits[k].strip() for k in TRAITS):
        errors.append("须登记线稿、五官比例、发束、上色和阴影的具体特征")
    else:
        block = style_block(contract)
        if panel.get("style_execution_block") != block or block not in str(panel.get("prompt", "")):
            errors.append("实际prompt缺少与批准记录一致的画风执行块")
    return errors


def review_template(panel):
    contract = panel.get("style_contract") or {}
    aliases = contract.get("reference_aliases", [])
    refs = [dict(alias=r["alias"], path=r["path"], sha256=r["sha256"])
            for r in panel.get("reference_images", []) if r.get("alias") in aliases]
    return {"status": "UNREVIEWED", "reference_files": refs,
            "traits": contract.get("traits", {}), "reviewer": None, "evidence": None}


def review_errors(panel, item):
    review = item.get("style_review")
    if not isinstance(review, dict):
        return ["IMAGE_STYLE_HOLD:缺少独立画风验收"]
    expected = review_template(panel)
    if review.get("reference_files") != expected["reference_files"] or review.get("traits") != expected["traits"]:
        return ["IMAGE_STYLE_HOLD:验收样例或判据与生成输入不一致"]
    if review.get("status") != "PASS" or not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip() or not isinstance(review.get("evidence"), str) or not review["evidence"].strip():
        return ["IMAGE_STYLE_HOLD:画风未审/失败或缺少实际观察依据"]
    return []
