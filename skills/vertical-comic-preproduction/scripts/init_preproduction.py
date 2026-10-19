#!/usr/bin/env python3
"""Create a non-destructive episode workspace for preproduction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from identity_confirmation import POLICY as IDENTITY_POLICY


DIRS = (
    "00_输入审计",
    "01_镜头改编_CANDIDATE",
    "02_场景资产_CANDIDATE",
    "03_站位_CANDIDATE",
    "04_B提示词包_CANDIDATE",
    "05_逐格图片",
    "06_图片验收",
    "98_记忆更新",
)


def write_if_missing(path: Path, value: object) -> None:
    if path.exists():
        return
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化条漫前期制作话目录")
    parser.add_argument("--output", required=True, help="本话新RV输出目录")
    parser.add_argument("--book", required=True)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--panel-count", type=int, default=None)
    parser.add_argument("--config", help="可选使用配置JSON；读取第三来源及请求并发，不修改全局agent配置")
    parser.add_argument("--runtime-snapshot", help="本批一次创建、各话共用的manifest.json绝对路径")
    parser.add_argument("--memory-root", help="通用规则记忆库绝对路径")
    parser.add_argument("--memory-loading-policy", choices=("stage_baseline_loading_v1",), help="无配置的新库须显式绑定读取合同；旧库省略")
    parser.add_argument("--batch-size", type=int, choices=range(1, 6), default=None)
    parser.add_argument("--execution-mode", choices=("episode_async_v1", "half_episode_async_v1", "batch5_v1", "sequential_v1"), default=None, help="新任务默认整话异步；旧任务不自动迁移")
    parser.add_argument("--preparation-policy", choices=("episode_preparation_v1", "half_scoped_v1"), help="新整话模式使用全话准备一次；half_scoped_v1仅供旧半话兼容")
    parser.add_argument("--backend", choices=("codex_builtin_imagegen",), default=None, help="预选Codex入口；能力证据仍需实际核实")
    args = parser.parse_args()

    snapshot_ref = None
    frozen_runtime = None
    if args.runtime_snapshot:
        from runtime_snapshot import verify, sha
        snapshot_ref = {'path':str(Path(args.runtime_snapshot).resolve()),'sha256':sha(args.runtime_snapshot)}
        frozen_runtime = verify(snapshot_ref)
    config = None
    memory_source = None
    if args.config:
        from usage_config import read_config, memory_source as config_memory_source
        config = read_config(args.config,frozen_memory_source=frozen_runtime['memory_source'] if frozen_runtime else None)
        if args.book != config["production"]["book"] or args.episode not in config["production"]["episodes"]:
            parser.error("本书/本话不属于指定使用配置范围")
        memory_source = config_memory_source(config)
    if args.memory_root:
        if config and Path(args.memory_root).resolve() != Path(memory_source["root"]).resolve():
            parser.error("memory-root与使用配置冲突；请先明确修改配置")
        from rule_memory import POLICY as MEMORY_POLICY, source_index
        if not config:
            memory_source = {"policy": MEMORY_POLICY, "root": str(Path(args.memory_root).resolve()), "index": "记忆索引.json"}
            if args.memory_loading_policy:
                memory_source["loading_policy"] = args.memory_loading_policy
        source_index(memory_source)
    if args.memory_loading_policy:
        if memory_source is None or memory_source.get("loading_policy") != args.memory_loading_policy:
            parser.error("memory-loading-policy须与指定规则库/使用配置一致")
    if frozen_runtime:
        if memory_source and frozen_runtime['data'].get('origin_memory_root') != memory_source['root']:
            parser.error('本批快照的原规则来源与配置不一致')
        memory_source = frozen_runtime['memory_source']
    if config and config.get('runtime',{}).get('snapshot_policy')=='batch_snapshot_v1' and not snapshot_ref:
        parser.error('本配置要求--runtime-snapshot；先为本批创建一次快照，所有话共用')
    mode = args.execution_mode or (config["generation"].get("execution_mode", "batch5_v1") if config else "episode_async_v1")
    if snapshot_ref and mode!='episode_async_v1':parser.error('运行快照只用于新整话RV，旧RV不得静默迁移')
    if mode in {"episode_async_v1", "half_episode_async_v1"}:
        if args.batch_size is not None: parser.error("整话/半话模式不设置固定batch-size")
        extra = {"batch_strategy": "full_episode" if mode=="episode_async_v1" else "half_episode", "review_policy": config.get("review", {}) if config else {"systemic_failure_count_gt": 5, "max_auto_correction_rounds": 1}}
        from batch_round import settings as validate_review
        validate_review(extra)
    else:
        batch_size = args.batch_size or (config["generation"].get("batch_size", 5) if config else 5)
        extra = {"batch_size": batch_size}
    optimization=(config.get("optimization",{}).get("policy") if config else ("scoped_episode_review_v1" if mode=="episode_async_v1" else "scoped_half_review_v1")) if mode in {"episode_async_v1","half_episode_async_v1"} else None
    if optimization:
        preparation=args.preparation_policy or (config.get('preparation',{}).get('policy','half_scoped_v1') if config else 'episode_preparation_v1')
        if mode=='episode_async_v1' and preparation!='episode_preparation_v1':parser.error('整话生产须全话准备一次')
        if args.preparation_policy and config and args.preparation_policy!=config.get('preparation',{}).get('policy','half_scoped_v1'):
            parser.error('preparation-policy与使用配置冲突')
        extra.update(optimization_policy=optimization)
        if config and config.get('optimization',{}).get('state_dispatch_policy'):
            extra['state_dispatch_policy']=config['optimization']['state_dispatch_policy']
        if preparation=='episode_preparation_v1':
            extra.update(preparation_policy=preparation,semantic_audit=None)
            from panel_readiness import POLICY as READINESS
            readiness=config.get('readiness',{}).get('policy') if config else READINESS
            if readiness:extra.update(readiness_policy=readiness)
        else:
            extra.update(half_inputs={},half_gates={})
    execution=config.get('execution',{}).get('contract') if config else ('comic_execution_v2' if optimization else None)
    from frame_ratio_plan import POLICY as RATIO_POLICY
    ratio_policy=config.get('framing',{}).get('policy') if config else RATIO_POLICY
    if ratio_policy:extra.update(frame_ratio_policy=ratio_policy,frame_ratio_plan=None,requested_framing={'policy':ratio_policy})
    if execution and optimization:
        from execution_contract import toolchain
        extra.update(execution_contract=execution,toolchain=toolchain(frozen_runtime['scripts'] if frozen_runtime else None),continuity_sources=[],episode_order=config['production']['episodes'] if config else [args.episode])
        if snapshot_ref:extra['runtime_snapshot']=snapshot_ref
        from production_runtime import DEFAULTS, EPISODE_DEFAULTS, settings as runtime_settings
        default_runtime=EPISODE_DEFAULTS if mode=='episode_async_v1' else DEFAULTS
        runtime = dict(config.get('runtime', default_runtime)) if config else dict(default_runtime)
        extra.update(runtime=runtime_settings(runtime), generation_packages={})
    if mode == "episode_async_v1":
        from visual_evidence import POLICY as VISUAL_POLICY
        extra["visual_evidence_policy"] = (config or {}).get("quality", {}).get("policy", VISUAL_POLICY)
    if mode == 'episode_async_v1':
        from visual_evidence import BACKGROUND_POLICY
        bg = config.get('background') if config else {
            'policy': BACKGROUND_POLICY, 'selection': 'content_driven', 'closeup_preference': 'scene_flat'}
        if bg:
            extra.update(background_policy=BACKGROUND_POLICY, requested_background=bg)
    if mode == 'episode_async_v1':
        extra['input_quality_policy'] = 'execution_quality_v1'
        from appearance_lock import APPEARANCE,FRAME
        extra.update(appearance_policy=APPEARANCE,frame_policy=FRAME)
    if memory_source is not None:
        extra["memory_source"] = memory_source
    if config:
        extra["usage_config_path"] = str(Path(args.config).resolve())
        extra["requested_generation"] = config["generation"]

    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for name in DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)

    if extra.get("runtime", {}).get("watchdog", {}).get("policy") == "worker_watchdog_v1":
        write_if_missing(root / "00_输入审计" / "worker_watchdog.json",
                         {"policy": "worker_watchdog_v1", "events": [], "emitted": []})

    if optimization:
        index_path=root/"00_输入审计"/"批准索引.json"
        write_if_missing(index_path,{"policy":"approval_index_v1","book_id":args.book,"entries":[]})
        from codex_reference_contract import digest
        extra["approval_index"]={"path":str(index_path.relative_to(root)),"sha256":digest(index_path)}

    identity = {
        "identity_policy": IDENTITY_POLICY,
        "book_id": args.book,
        "episode_id": args.episode,
        "identity_registry": {
            "book_id": args.book, "characters": {}, "appearance_states": {},
            "scene_states": {}, "assets": {}, "issues": [],
        },
    }
    metadata = {
        **identity,
        "schema": "vertical-comic-preproduction-episode-v1",
        "book": args.book,
        "episode": args.episode,
        "status": "INPUT",
        "panel_count": args.panel_count,
        "source_script": None,
        "source_asset_index": None,
        "approval_basis": None,
    }
    backend_fields = {} if args.backend is None else {
        "control_policy": "structural_guidance_v1", "reference_input_policy": "codex_reference_v1",
        "generation_backend": {"backend_id": args.backend, "mode": "reference_guided", "structural_controls": [], "evidence": None},
    }
    metadata.update(backend_fields)
    metadata.update(extra)
    metadata.update({"workflow_policy": "staged_comic_v1", "execution_mode": mode, "style_policy": "approved_style_v1", "input_priority_policy": "physical_scene_priority_v1", "deliverable": "per_panel_image_package"})
    write_if_missing(root / "00_输入审计" / "生产流程.json", {
        "policy": "staged_comic_v1", "book_id": args.book, "episode_id": args.episode,
        "input_priority_policy": "physical_scene_priority_v1",
        **extra,
        "execution_mode": mode,
        **({"batch_plan": None, "batch_reviews": {}} if mode in {"batch5_v1", "half_episode_async_v1", "episode_async_v1"} else {}),
        **({"round_reviews": {}, "calibration_reviews": {}} if mode == "half_episode_async_v1" else {}),
        **({"repair_authorizations": {}, "episode_failure_diagnosis": {}} if mode == "episode_async_v1" else {}),
        "source_script": None, "source_snapshot": None, "visual_basis": None,
        "shot_manifest": None, "gates": {}, "production_authorization": None,
        "panels": [], "state_reviews": {}, "holds": [], "cancelled": False,
    })
    write_if_missing(root / "00_输入审计" / "本话配置.json", metadata)
    write_if_missing(root / "00_输入审计" / "人物身份与状态绑定.json", {
        **identity, "status": "IDENTITY_HOLD", "panels": [],
    })
    write_if_missing(root / "01_镜头改编_CANDIDATE" / "镜头改编表.json", {
        **identity,
        "schema": "vertical-comic-shot-design-v1",
        "framing_policy": "information_first_v1",
        "input_priority_policy": "physical_scene_priority_v1",
        "continuity_policy": "reference_continuity_v1",
        "workflow_policy": "staged_comic_v1",
        **extra,
        "execution_mode": mode,
        "style_policy": "approved_style_v1",
        **({"reference_input_policy": "codex_reference_v1"} if args.backend else {}),
        "book": args.book,
        "episode": args.episode,
        "status": "CAMERA_CANDIDATE",
        "panels": [],
    })
    write_if_missing(root / "02_场景资产_CANDIDATE" / "场景空间底账.json", {
        "schema": "vertical-comic-scene-ledger-v1",
        "book": args.book,
        "episode": args.episode,
        "status": "ASSET_CANDIDATE",
        "scenes": [],
    })
    write_if_missing(root / "03_站位_CANDIDATE" / "空间图索引.json", {
        "schema": "vertical-comic-spatial-board-v2",
        "book": args.book,
        "episode": args.episode,
        "status": "STATION_CANDIDATE",
        "states": [],
    })
    write_if_missing(root / "04_B提示词包_CANDIDATE" / "全话提示词索引.json", {
        **identity,
        **backend_fields,
        "schema": "vertical-comic-prompt-package-v1",
        "framing_policy": "information_first_v1",
        "input_priority_policy": "physical_scene_priority_v1",
        "continuity_policy": "reference_continuity_v1",
        "workflow_policy": "staged_comic_v1",
        **extra,
        "execution_mode": mode,
        "style_policy": "approved_style_v1",
        "book": args.book,
        "episode": args.episode,
        "status": "PROMPT_PACKAGE_HOLD",
        "sources": {},
        "panels": [],
    })
    print(json.dumps({"status": "SCAFFOLD_CREATED", "production_status": "IDENTITY_HOLD", "root": str(root), "created_dirs": list(DIRS)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
