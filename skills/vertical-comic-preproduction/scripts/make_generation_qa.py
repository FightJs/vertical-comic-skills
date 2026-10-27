#!/usr/bin/env python3
"""Create an auditable QA packet for images returned by the B computer.

It automatically checks file presence and aspect ratio, prepares an adjacent
panel checklist, and creates a P001-P003 contact sheet when those images exist.
Camera sameness is intentionally a human decision: the tool records the
expected signatures and refuses to claim image approval without review fields.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

from continuity_contract import dimension_template, sha256, validate_manifest
from codex_reference_contract import POLICY as CODEX_REFERENCE_POLICY, checked_file, composition_errors
from style_contract import POLICY as STYLE_POLICY, review_template as style_template, validate_style, output_spec_errors
from rule_memory import review_template as memory_template, inspection_plan, routing_session
from input_priority import POLICY as INPUT_PRIORITY_POLICY


RATIO_RE = re.compile(r"\s*(\d+(?:\.\d+)?)\s*[:：]\s*(\d+(?:\.\d+)?)\s*")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def parse_ratio(value: Any) -> tuple[float, float] | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        pair = (float(value), 1.0)
    elif isinstance(value, str):
        match = RATIO_RE.fullmatch(value)
        if not match:
            return None
        pair = (float(match.group(1)), float(match.group(2)))
    else:
        return None
    return pair if all(math.isfinite(x) and x > 0 for x in pair) else None


def expected_ratio(panel: dict[str, Any]) -> tuple[float, float] | None:
    # A negative instruction such as “不要3:2” is never ratio authority.
    value = panel.get("frame_ratio") if "frame_ratio" in panel else panel.get("ratio")
    return parse_ratio(value)


def find_image(images_root: Path, panel_id: str) -> Path | None:
    panel_dir = images_root / panel_id
    if panel_dir.is_dir():
        candidates = [p for p in panel_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
        if candidates:
            return sorted(candidates)[0]
    candidates = [p for p in images_root.glob(f"{panel_id}.*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    return sorted(candidates)[0] if candidates else None


def _main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Create returned-image QA report and contact sheet")
    parser.add_argument("--package", required=True, help="repaired or approved B package root")
    parser.add_argument("--images", required=True, help="returned image root; either Pxxx folders or Pxxx.ext files")
    parser.add_argument("--output", required=True, help="QA output directory")
    parser.add_argument('--episode-root',help='新画幅合同的本话根目录；不填沿用package根')
    parser.add_argument("--panel-ids", nargs="+", help="显式源格选集，保持原序；不填则使用包全部格")
    parser.add_argument("--manifest", default="全话提示词索引.json", help="实际不可变返回包相对文件名")
    parser.add_argument("--image-path", help="单格真实返回路径；不复制/重命名原图")
    parser.add_argument("--skip-contact-sheet", action="store_true", help="增量组审只制作一次组联系表")
    args = parser.parse_args(argv)

    package = Path(args.package).resolve()
    images_root = Path(args.images).resolve()
    output = Path(args.output).resolve()
    manifest_path = (package / args.manifest).resolve()
    if Path(args.manifest).is_absolute() or not manifest_path.is_relative_to(package):
        raise SystemExit("manifest须为实际包内相对文件名")
    if not manifest_path.is_file():
        raise SystemExit(f"manifest does not exist: {manifest_path}")
    if not images_root.is_dir():
        raise SystemExit(f"images root does not exist: {images_root}")
    output.mkdir(parents=True, exist_ok=False)
    manifest = load_json(manifest_path)
    from frame_ratio_plan import enabled as ratios_enabled,plan_errors as ratio_plan_errors,panel_errors as ratio_panel_errors,image_errors as ratio_image_errors,read_plan,statistics as ratio_statistics
    episode_root=Path(args.episode_root).resolve() if args.episode_root else package
    panels = manifest.get("panels")
    if not isinstance(panels, list) or not panels:
        raise SystemExit("manifest.panels is empty")

    if args.panel_ids:
        source_ids = [p.get("panel_id") for p in panels]
        if len(set(args.panel_ids)) != len(args.panel_ids) or [pid for pid in source_ids if pid in args.panel_ids] != args.panel_ids:
            raise SystemExit("panel-ids须为包中的准确源序选集")
        panels = [p for p in panels if p["panel_id"] in args.panel_ids]
    if args.image_path and (len(panels) != 1 or not Path(args.image_path).is_file()):
        raise SystemExit("image-path只用于单格真实存在的返回图")

    from light_review import at_root, template as light_template, FIELD, POLICY as LIGHT_POLICY
    if at_root(episode_root):
        items = []
        for panel in panels:
            image = Path(args.image_path) if args.image_path else find_image(images_root, panel['panel_id'])
            if image is None: raise SystemExit('LIGHT_QA: actual returned image missing')
            items.append(light_template({'panel_id': panel['panel_id'], 'output': {'sha256': sha256(image)}},
                load_json(episode_root/'00_输入审计/生产流程.json')))
        report = {FIELD: LIGHT_POLICY, 'status': 'HOLD_UNREVIEWED',
                  'source_manifest_sha256': sha256(manifest_path), 'panels': items}
        (output/'生成图QA报告.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({'status': report['status'], 'image_review_profile': LIGHT_POLICY}, ensure_ascii=False))
        return 0

    report: dict[str, Any] = {
        "status": "HOLD_UNREVIEWED",
        "package": str(package),
        "continuity_policy": manifest.get("continuity_policy"),
        "source_manifest_sha256": sha256(manifest_path),
        "images_root": str(images_root),
        "panel_count": len(panels),
        "errors": [],
        "warnings": [],
        "panels": [],
        "adjacent_review": [],
    }
    contract_errors, contract_warnings = validate_manifest(manifest,root=package)
    report["errors"].extend(contract_errors)
    report["warnings"].extend(contract_warnings)
    if ratios_enabled(manifest):
        ratio_errors=ratio_plan_errors(manifest,episode_root)
        report['errors'].extend(ratio_errors)
        report['errors'].extend(ratio_panel_errors(manifest,episode_root,panels,prompt=True))
        if not ratio_errors:report['planned_episode_ratio_distribution']=ratio_statistics(read_plan(manifest,episode_root)['panels'])
    image_items: list[tuple[str, Path]] = []
    for panel in panels:
        pid = str(panel.get("panel_id", ""))
        composition = panel.get("composition_reference") or {}
        composition_mode = composition.get("mode") if isinstance(composition, dict) and isinstance(composition.get("mode"), str) else None
        composition_used = composition_mode in {"CREATE", "REUSE"}
        composition_not_required = composition_mode == "NOT_REQUIRED" and panel.get("composition_required") is not True
        if manifest.get("reference_input_policy") == CODEX_REFERENCE_POLICY:
            report["errors"].extend(f"{pid}:{message}" for message in composition_errors(panel))
        image = Path(args.image_path).resolve() if args.image_path else find_image(images_root, pid)
        expected = expected_ratio(panel)
        item: dict[str, Any] = {
            "panel_id": pid,
            "expected_camera": {
                "angle": panel.get("camera_angle_family"),
                "scale": panel.get("shot_scale"),
                "ratio": panel.get("frame_ratio") or (f"{expected[0]}:{expected[1]}" if expected else None),
                "signature": panel.get("camera_view_signature"),
                "framing": panel.get("framing"),
            },
            "image": str(image) if image else None,
            "image_sha256": sha256(image) if image else None,
            "image_size": None,
            "ratio_check": "HOLD_MISSING",
            "camera_match": None,
            "shot_scale_match": None,
            "background_view_match": None,
            "body_crop_match": None,
            "required_visible_information_preserved": None,
            "no_extra_offscreen_characters": None,
            "dimension_review": dimension_template(panel),
            "composition_reference": panel.get("composition_reference"),
            # Only the extra image-to-image check is inapplicable. The
            # framing/spatial dimensions above remain unreviewed and required.
            "composition_match": "NOT_APPLICABLE" if composition_not_required else None,
            "composition_review_basis": (
                "COMPOSITION_REFERENCE" if composition_used else
                "APPROVED_SHOT_SPATIAL_RECORDS_AND_ASSETS" if composition_not_required else
                "UNRESOLVED_COMPOSITION_PLAN"
            ),
            "ratio_tolerance": panel.get("ratio_tolerance"),
            "notes": "一次观察并逐项写入原QA；相邻镜头按当前命中规则及真实格对例外核对，基础技术PASS不豁免专项规则。",
        }
        from visual_evidence import review_template as visual_review_template
        from visual_evidence import framing_execution_block, framing_errors
        framing_issues = framing_errors(panel, prompt=True)
        report['errors'].extend(f'{pid}:{issue}' for issue in framing_issues)
        if not framing_issues:
            framing_focus = framing_execution_block(panel)
            if framing_focus:
                item['framing_review_focus'] = {
                    'expected': framing_focus,
                    **({'background_policy': panel['background_policy'], 'background_plan': panel['framing']['background_plan']} if panel.get('background_policy') else {}),
                    'record_in': ['dimension_review.framing', 'dimension_review.background_space'],
                    'acceptance': 'ORIGINAL_QA_FIELDS_ONLY',
                }
        visual_review = visual_review_template(panel)
        if visual_review is not None:
            item["visual_evidence_review"] = visual_review
        if manifest.get("input_priority_policy") == INPUT_PRIORITY_POLICY:
            item["priority_review_focus"] = {
                "physical": "在现有action_interaction/framing与适用记忆中核对人体、支撑、接触、透视和遮挡",
                "scene": "在现有background_space/framing中核对批准场景的门窗、家具、固定物件及世界位置",
                "hard_requirements": "在现有身份、衣装、动作、表情和画风检查中核对原剧情与当前批准状态",
                "approved_visual_solution": (panel.get("visual_resolution") or {}).get("approved_visual_solution") if isinstance(panel.get("visual_resolution"), dict) else None,
            }
        if manifest.get("style_policy") == STYLE_POLICY or panel.get("style_policy") is not None:
            report["errors"].extend(f"{pid}:{e}" for e in validate_style(panel, package))
            item["style_review"] = style_template(panel)
        if manifest.get("memory_source") is not None:
            try:
                tags=[]
                if manifest.get('execution_contract')=='comic_execution_v2':
                    from continuity_context import rule_tags
                    tags=rule_tags(manifest,package,panel)
                item["memory_review"] = memory_template(manifest["memory_source"], panel, item["image_sha256"],context_tags=tags,artifact_root=package,scope=manifest)
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                report["errors"].append(f"{pid}:MEMORY_HOLD:{exc}")
        if image is None:
            report["errors"].append(f"{pid}:未找到返回底图")
        else:
            try:
                from PIL import Image

                with Image.open(image) as opened:
                    width, height = opened.size
                    actual_format = opened.format
                item["image_size"] = [width, height]
                variant_errors=ratio_image_errors(panel,[width,height]) if ratios_enabled(manifest) else []
                report['errors'].extend(f'{pid}:{e}' for e in variant_errors)
                item["image_format"] = actual_format
                if manifest.get("workflow_policy") == "staged_comic_v1":
                    spec_errors = output_spec_errors(panel, [width, height], actual_format)
                    item["output_spec_check"] = "FAIL" if spec_errors else "PASS"
                    report["errors"].extend(f"{pid}:{e}" for e in spec_errors)
                actual = width / height
                if expected is None:
                    item["ratio_check"] = "HOLD_NO_EXPECTED_RATIO"
                    report["warnings"].append(f"{pid}:结构化frame_ratio/ratio缺失或无效；不从正文/负面指令猜比例")
                else:
                    target = expected[0] / expected[1]
                    tolerance = panel.get("ratio_tolerance", 0.05)
                    item["ratio_relative_error"] = abs(actual - target) / target
                    if "ratio_tolerance" not in panel:
                        report["warnings"].append(f"{pid}:旧包沿用5%比例容差，未确认新的交付规格")
                    if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or not 0 <= tolerance < 1:
                        item["ratio_check"] = "HOLD_INVALID_TOLERANCE"
                        report["errors"].append(f"{pid}:比例容差非法")
                    else:
                        item["ratio_tolerance"] = tolerance
                        item["ratio_check"] = "PASS" if item["ratio_relative_error"] <= tolerance else "FAIL"
                        if variant_errors:item['ratio_check']='FAIL'
                    if item["ratio_check"] == "FAIL":
                        report["errors"].append(f"{pid}:实际比例{width}:{height}不符合预期{expected[0]}:{expected[1]}")
                image_items.append((pid, image))
                if "style_review" in item:
                    from PIL import ImageDraw
                    for index, ref in enumerate(item["style_review"]["reference_files"], 1):
                        try:
                            reference = checked_file(package, ref)
                            pair = Image.new("RGB", (760, 540), "white")
                            draw = ImageDraw.Draw(pair)
                            for col, (source, label) in enumerate(((reference, "APPROVED STYLE"), (image, "RETURNED"))):
                                with Image.open(source) as opened:
                                    thumb = opened.convert("RGB")
                                thumb.thumbnail((360, 480))
                                pair.paste(thumb, (col * 380 + (380 - thumb.width) // 2, 40))
                                draw.text((col * 380 + 10, 10), f"{pid} {label}", fill="black")
                            name = f"{pid}_画风对照_{index:02d}.jpg"
                            pair.save(output / name, quality=95)
                            item.setdefault("style_comparisons", []).append(name)
                        except (OSError, ValueError, TypeError) as exc:
                            report["errors"].append(f"{pid}:画风对照失败: {exc}")
                if composition_used:
                    ref = next((r for r in panel.get("reference_images", []) if isinstance(r, dict) and r.get("alias") == composition.get("alias")), None)
                    try:
                        reference = checked_file(package, ref)
                        from PIL import ImageDraw
                        pair = Image.new("RGB", (760, 540), "white")
                        draw = ImageDraw.Draw(pair)
                        for col, (source, label) in enumerate(((reference, "REFERENCE"), (image, "RETURNED"))):
                            with Image.open(source) as opened:
                                thumb = opened.convert("RGB")
                            thumb.thumbnail((360, 480))
                            pair.paste(thumb, (col * 380 + (380 - thumb.width) // 2, 40))
                            draw.text((col * 380 + 10, 10), f"{pid} {label}", fill="black")
                        name = f"{pid}_构图与返回图对照.jpg"
                        pair.save(output / name, quality=95)
                        item["composition_comparison"] = name
                        item["composition_reference_sha256"] = sha256(reference)
                    except (OSError, ValueError, TypeError) as exc:
                        report["errors"].append(f"{pid}:构图对照证据缺失或失效: {exc}")
            except Exception as exc:  # noqa: BLE001 - report the image read failure
                item["ratio_check"] = "HOLD_IMAGE_READ_ERROR"
                report["errors"].append(f"{pid}:无法读取图片: {exc}")
        item['inspection_plan']=inspection_plan(panel,item,report['source_manifest_sha256'])
        from coordinate_repair import spec as coordinate_spec
        coordinate = coordinate_spec(panel)
        if isinstance(coordinate, dict):
            item['inspection_plan']['coordinate_targets'] = coordinate.get('expected_observations', {})
        report["panels"].append(item)

    for previous, current in zip(report["panels"], report["panels"][1:]):
        report["adjacent_review"].append(
            {
                "pair": f"{previous['panel_id']}→{current['panel_id']}",
                "expected_previous": previous["expected_camera"],
                "expected_current": current["expected_camera"],
                "camera_angle_changed": None,
                "shot_scale_changed": None,
                "background_changed_physically": None,
                "same_default_view_risk": None,
                "focal_information_changed_as_planned": None,
                "decision": "按本批冻结MEM-010版本审查；v2按叙事与物理连续性允许同景别近景/正反打，v1保留原双变化要求；不把changed=false直接等同失败。",
            }
        )

    # Review every selected panel, including non-P001 half windows.
    try:
        from PIL import Image, ImageDraw
        thumbs = []
        for pid, path in image_items:
            with Image.open(path) as opened:
                thumb = opened.convert("RGB")
            thumb.thumbnail((360, 480))
            canvas = Image.new("RGB", (380, 520), "white")
            canvas.paste(thumb, ((380-thumb.width)//2, 30))
            ImageDraw.Draw(canvas).text((10, 8), pid, fill="black")
            thumbs.append(canvas)
        if thumbs and not args.skip_contact_sheet:
            columns = min(5, len(thumbs)); rows = math.ceil(len(thumbs)/columns)
            sheet = Image.new("RGB", (380*columns, 520*rows), "#dddddd")
            for index, thumb in enumerate(thumbs): sheet.paste(thumb, ((index%columns)*380, (index//columns)*520))
            name = f"{image_items[0][0]}-{image_items[-1][0]}_批次审查.jpg"
            sheet.save(output/name, quality=95); report["contact_sheet"] = name
    except Exception as exc:
        report["warnings"].append(f"未生成批次审查图:{exc}")

    (output / "生成图QA报告.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline='\n')
    (output / "相邻镜头审查说明.md").write_text(
        "# 返回底图审查\n\n"
        "逐对检查相邻格：机位角度族、真实摄影机位置、景别、地平线/消失点、背景裁切、人物可见范围和遮挡。\n\n"
        "相邻变化按本批冻结MEM-010版本和批准构图审查；v2允许有叙事依据的连续近景与同景别正反打，不强求角度/景别同时变化；旧v1保留其合同。意外复制默认视图、扩大身体裁切、补入画外人物、遗漏必显信息或比例不符时继续HOLD。\n\n"
        "先全图逐人物核对肢体数量、归属与承托，再看原尺寸眼/手/首饰局部，最后比较相关连续图。缩略总览只作导航。沿固定床侧/路沿等世界锚点判断，不把屏幕左右或看不见的部分当移位证据。\n\n"
        "D阶段选用CREATE/REUSE构图参考时，与返回图并排核对；NOT_REQUIRED时依据批准镜头、空间记录及相关资产审查，composition_match仅表示额外图片对照并标NOT_APPLICABLE。机位、裁切、接触、遮挡和framing维度仍须实际复核，不为验收补造灰阶稿或站位图。\n\n"
        "启用连续性合同时另逐项检查identity、costume、action_interaction、background_space、framing。必审项保持UNREVIEWED；实际看图后写PASS/FAIL、复核者和具体证据。计划的NOT_VISIBLE/NOT_APPLICABLE不能在生图后扩大。身份通过但接触失败仍HOLD；同场景换机位核对空间而非像素复制。分项记录校验不代替首三格、相邻审查和用户批准。\n",
        encoding="utf-8",
    newline='\n')
    print(json.dumps({"status": report["status"], "output": str(output), "errors": len(report["errors"])}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    with routing_session():return _main()


if __name__ == "__main__":
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
