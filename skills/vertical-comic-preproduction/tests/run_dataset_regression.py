#!/usr/bin/env python3
"""Read-only historical dataset regression; writes only a new output directory."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from legacy_spatial_cleanup import migrate_panel, retired_inputs
from validate_preproduction import Gate


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root, output = Path(args.dataset).resolve(), Path(args.output).resolve()
    if output.exists() or output.is_relative_to(root):
        raise SystemExit("输出必须是数据集外的新目录")
    output.mkdir(parents=True)
    checks, cases, repairs = [], [], []
    def check(name, passed, detail=None):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
    entries = read(root / "文件校验清单.json")
    before = {}
    integrity_errors, metadata_mismatches = [], []
    for entry in entries:
        path = (root / entry["path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            integrity_errors.append(entry["path"])
            continue
        before[entry["path"]] = sha(path)
        if before[entry["path"]] != entry["sha256"]:
            (metadata_mismatches if path.name == ".DS_Store" else integrity_errors).append(entry["path"])
    check("业务数据文件与原校验清单一致", not integrity_errors, integrity_errors)
    cross = read(root / "跨阶段索引.json")
    check("七阶段case_id对齐", all(len(read(root / stage / "index.json")) == len(cross) for stage in cross[0]["stages"]))
    verified_images = {}
    for entry in cross:
        case_id = entry["case_id"]
        # Only stage inputs feed the migration under test. Historical outputs
        # below are observations for comparison, never approval/gold answers.
        input_data = read(root / entry["stages"]["06_提示词"]["input"])["data"]
        shot = copy.deepcopy(input_data["shot"])
        shot["reference_images"] = copy.deepcopy(input_data["reference_images"])
        if "camera_card" in input_data:
            shot["camera_card"] = copy.deepcopy(input_data["camera_card"])
        source_locked = copy.deepcopy(shot.get("locked_script"))
        cleaned, migration = migrate_panel(shot)
        live_retired = retired_inputs(cleaned)
        check(case_id + ":移除退役卡", not live_retired, live_retired)
        check(case_id + ":锁定剧本逐字保留", source_locked == cleaned.get("locked_script"))
        for field in ("camera_view_id", "camera_view_signature", "camera_position", "frame_ratio", "characters_visible"):
            check(case_id + ":保留" + field, shot.get(field) == cleaned.get(field))
        old_holds = shot.get("hold_reasons", [])
        old_holds = [old_holds] if isinstance(old_holds, str) else old_holds
        spatial = [h for h in old_holds if any(s in str(h) for s in ("HOLD_NOT_YET_SPATIALLY_PROVEN", "CAMERA_HOLD", "空间资产HOLD", "IDENTITY_HOLD"))]
        check(case_id + ":未证明空间或身份继续HOLD", all(h in cleaned.get("hold_reasons", []) for h in spatial))
        refs_ok = True
        for ref in input_data["reference_images"]:
            path = (root / ref.get("dataset_path", "")).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                refs_ok = False; continue
            if str(path) not in verified_images:
                verified_images[str(path)] = sha(path)
            refs_ok &= verified_images[str(path)] == ref.get("sha256")
        check(case_id + ":真实参考文件与哈希", refs_ok)
        generation = read(root / entry["stages"]["07_生成图片"]["output"])["data"]
        check(case_id + ":缺底图不能视为验收通过", generation.get("status") == "MISSING_RETURNED_PANEL_IMAGE" and not generation.get("image_files"))
        destination = output / "迁移候选" / (case_id + ".json")
        destination.parent.mkdir(exist_ok=True)
        destination.write_text(json.dumps({"status": "TEST_MIGRATION_ONLY_NOT_READY_OR_APPROVED", "case_id": case_id, "input": entry["stages"]["06_提示词"]["input"], "panel": cleaned, "migration": migration}, ensure_ascii=False, indent=2))
        cases.append({"case_id": case_id, "removed_aliases": migration["removed_aliases"], "script_preserved": source_locked == cleaned.get("locked_script"), "historical_label": "OBSERVED_HISTORICAL_OUTPUT_NOT_GOLD", "image_acceptance": "NOT_ASSESSED"})
    for episode in sorted({item["case_id"].split("-")[0] for item in cross}):
        package = root / "00_共享证据/原始包证据" / episode
        source = read(package / "全话提示词索引.json")
        shots = read(package / "sources/镜头改编表.json")
        gate = Gate(root)
        gate.prompt_root = package
        shot_panels = gate.check_shots(shots)
        gate.check_prompt(source, shot_panels)
        (output / (episode + "_旧包门禁.json")).write_text(json.dumps({"status": "HOLD" if gate.errors else "PASS", "errors": gate.errors, "warnings": gate.warnings}, ensure_ascii=False, indent=2))
        check(episode + ":历史候选不自动批准", bool(gate.errors))
        if episode == "E012":
            check("E012-P008:已知机位签名差异被门禁捕获", any("提示词索引[7]" in e and "camera_view_signature与镜头改编表不一致" in e for e in gate.errors))
        for script in ("repair_prompt_package.py", "repair_prompt_package_v2.py"):
            destination = output / (episode + "_" + Path(script).stem)
            run = subprocess.run([sys.executable, str(SCRIPTS / script), "--source", str(package), "--output", str(destination)], capture_output=True, text=True)
            try:
                result = json.loads(run.stdout)
            except ValueError:
                result = {"status": "ERROR", "stderr": run.stderr, "stdout": run.stdout}
            expected_hold = result.get("status") == "HOLD" and not destination.exists() and result.get("output_created") is False
            check(episode + ":" + script + ":缺身份依据不创建修复包", expected_hold)
            repairs.append({"episode": episode, "script": script, "returncode": run.returncode, "result": result})
    changed = [rel for rel, digest in before.items() if sha(root / rel) != digest]
    check("测试后原数据集字节未改", not changed, changed)
    report = {"status": "PASS" if all(c["passed"] for c in checks) else "FAIL", "dataset": str(root), "case_count": len(cases), "unique_reference_files_verified": len(verified_images), "integrity_file_count": len(before), "metadata_mismatches": metadata_mismatches, "checks_passed": sum(c["passed"] for c in checks), "checks_total": len(checks), "actual_generation_calls": 0, "returned_panel_images": 0, "visual_quality_assessed": False, "checks": checks, "cases": cases, "repair_cli_checks": repairs}
    (output / "数据集回归报告.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k not in {"checks", "cases", "repair_cli_checks"}}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
