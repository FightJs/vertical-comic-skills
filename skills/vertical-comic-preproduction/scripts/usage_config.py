#!/usr/bin/env python3
"""Validate comic usage configuration; resolve runtime ceilings without spawning agents."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from rule_memory import POLICY as MEMORY_POLICY, LOADING_POLICY, source_index

POLICY = "comic_usage_v1"


def read_config(path, *, frozen_memory_source=None):
    config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    from dispatch_publication import require_legacy
    require_legacy(config)
    if config.get("policy") != POLICY:
        raise ValueError("配置policy必须是comic_usage_v1")
    inputs = config.get("inputs", {})
    # A prepared run already records its resolved origin. From its snapshot,
    # validate the frozen rules instead of resolving a different cache location.
    pinned_origin=(frozen_memory_source is not None and inputs.get('memory_root')
                   and config.get('memory',{}).get('index_sha256')
                   and config['memory']['index_sha256']==frozen_memory_source.get('index_sha256'))
    if not pinned_origin and (config.get('memory',{}).get('source')=='builtin' or not inputs.get('memory_root')):
        from builtin_memory import resolve
        resolved=resolve()
        config.setdefault('inputs',{})['memory_root']=resolved['root']
        config.setdefault('memory',{}).update(index=resolved['index'],loading_policy=resolved['loading_policy'],index_sha256=resolved['index_sha256'])
        inputs=config['inputs']
    for key, directory in (("script_path", False), ("asset_root", True), ("memory_root", True)):
        p = Path(inputs.get(key, ""))
        if not p.is_absolute() or not (p.is_dir() if directory else p.is_file()):
            raise ValueError(f"{key}必须是存在的绝对{'目录' if directory else '文件'}路径")
    scope = config.get("production", {})
    if not isinstance(scope.get("book"), str) or not scope["book"].strip():
        raise ValueError("production.book缺失")
    episodes = scope.get("episodes")
    if not isinstance(episodes, list) or not episodes or any(not isinstance(e, str) or not e for e in episodes) or len(set(episodes)) != len(episodes):
        raise ValueError("production.episodes须明确列出不重复话号")
    settings = config.get("generation", {})
    if type(settings.get("episode_workers")) is not int or settings["episode_workers"] < 1:
        raise ValueError("generation.episode_workers须为正整数")
    half = settings.get("execution_mode") == "half_episode_async_v1"
    episode_mode = settings.get("execution_mode") == "episode_async_v1"
    if half or episode_mode:
        strategy="half_episode" if half else "full_episode"
        if settings.get("batch_strategy") != strategy or "batch_size" in settings:
            raise ValueError(f"{strategy}模式不设置固定batch_size")
        for key, automatic in (("max_inflight_images", "auto"), ("max_inflight_per_episode", "half_episode" if half else "episode")):
            value = settings.get(key)
            if value != automatic and (type(value) is not int or value < 1):
                raise ValueError(f"{key}须为{automatic}或正整数")
        from batch_round import settings as review_settings
        review_settings({"review_policy": config.get("review", {})})
    else:
        if settings.get("execution_mode") not in (None, "batch5_v1", "sequential_v1"):
            raise ValueError("未知执行模式")
        for key in ("max_inflight_images", "batch_size"):
            if type(settings.get(key)) is not int or not 1 <= settings[key]:
                raise ValueError(f"generation.{key}须为正整数")
        if settings["batch_size"] > 5:
            raise ValueError("旧batch5_v1的batch_size上限5")
    preparation=config.get('preparation')
    if preparation is not None and not isinstance(preparation,dict):
        raise ValueError('preparation须为对象')
    optimization=config.get("optimization")
    readiness=config.get('readiness')
    if readiness is not None:
        from panel_readiness import POLICY as READINESS_POLICY
        if not isinstance(readiness,dict) or readiness.get('policy')!=READINESS_POLICY or config.get('preparation',{}).get('policy')!='episode_preparation_v1':raise ValueError('readiness须为panel_readiness_v1并配套全话准备')
    if optimization is not None:
        preparation_policy=(preparation or {}).get('policy','half_scoped_v1')
        approval_scope='generation_half_only' if preparation_policy=='episode_preparation_v1' else 'half_episode'
        if episode_mode:approval_scope='generation_episode_only'
        expected_policy='scoped_episode_review_v1' if episode_mode else 'scoped_half_review_v1'
        if not (half or episode_mode) or not isinstance(optimization,dict) or optimization.get("policy")!=expected_policy or optimization.get("approval_scope")!=approval_scope or optimization.get("review_strategy")!="on_return" or optimization.get("unchanged_qa")!="reuse_recorded":
            raise ValueError("审查优化范围须与前期准备模式一致，并保留返回即审与内容绑定复用")
        from scoped_inputs import STATE_DISPATCH
        if optimization.get('state_dispatch_policy') not in (None,STATE_DISPATCH):
            raise ValueError('未知新状态提交策略')
        if optimization.get('state_dispatch_policy')==STATE_DISPATCH and (preparation_policy!='episode_preparation_v1' or not readiness or not config.get('execution')):
            raise ValueError('普通新状态并发须配套全话准备、逐格就绪和完整执行合同')
    if preparation is not None:
        if not (half or episode_mode) or not optimization or not isinstance(preparation,dict) or preparation.get('policy') not in ({'episode_preparation_v1'} if episode_mode else {'episode_preparation_v1','half_scoped_v1'}):
            raise ValueError('前期准备须与整话或旧版半话执行模式一致')
    if config.get("runtime") is not None:
        from production_runtime import settings as runtime_settings
        if not (half or episode_mode) or not optimization:raise ValueError("runtime须配套审查优化")
        runtime_settings(config["runtime"])
        expected_runtime='incremental_runtime_v2' if episode_mode else 'incremental_runtime_v1'
        if config['runtime'].get('policy')!=expected_runtime:raise ValueError('runtime版本与生产范围不一致')
    if 'execution_quality' in config and (not episode_mode or config['execution_quality'] != {'policy':'execution_quality_v1'}):
        raise ValueError('execution_quality须为整话execution_quality_v1')
    if "quality" in config:
        from visual_evidence import POLICY as VISUAL_POLICY
        if not episode_mode or config["quality"] != {"policy": VISUAL_POLICY}:
            raise ValueError("quality须为整话visual_evidence_v1；旧RV不自动升级")
    if 'background' in config:
        from visual_evidence import background_config_errors
        issues = background_config_errors(config['background'])
        if not episode_mode or issues:
            raise ValueError('背景策略仅用于新整话RV；' + ';'.join(issues))
    memory = config.get("memory", {})
    framing=config.get('framing')
    if framing is not None:
        from frame_ratio_plan import POLICY as RATIO_POLICY
        if not isinstance(framing,dict) or framing.get('policy')!=RATIO_POLICY:raise ValueError('framing.policy须为content_balanced_ratios_v1')
    execution=config.get('execution')
    if execution is not None:
        if not isinstance(execution,dict) or not (half or episode_mode) or not optimization or execution.get('contract')!='comic_execution_v2' or execution.get('request_log')!='structured' or execution.get('semantic_audit')!='before_freeze' or execution.get('id_mapping')!='source_preserving':raise ValueError('完整执行合同须配套生产优化、结构化调用记录、冻结前语义核对及源编号映射')
    if preparation is not None and preparation.get('policy')=='episode_preparation_v1' and execution is None:
        raise ValueError('全话准备须启用comic_execution_v2以逐格核对全话语义')
    if memory.get("cache") != "run_worker_version" or memory.get("admission") != "cross_work_only":
        raise ValueError("记忆配置须使用run_worker_version缓存及cross_work_only入库限制")
    if "loading_policy" in memory and memory["loading_policy"] != LOADING_POLICY:
        raise ValueError("memory.loading_policy须为stage_baseline_loading_v1；旧库省略")
    source_index(frozen_memory_source if frozen_memory_source is not None else memory_source(config))
    return config


def memory_source(config):
    memory = config.get("memory", {})
    source = {"policy": MEMORY_POLICY, "root": config["inputs"]["memory_root"],
              "index": memory.get("index", "记忆索引.json")}
    if "loading_policy" in memory:
        source["loading_policy"] = memory["loading_policy"]
    if memory.get('index_sha256'):source['index_sha256']=memory['index_sha256']
    return source


def runtime_limits(config, agent_slots, backend_limit=None, episode_panel_counts=None, active_episodes=None, current_half_counts=None):
    if type(agent_slots) is not int or agent_slots < 1:
        raise ValueError("实际agent总槽位须为正整数（包含总控）")
    if backend_limit is not None and (type(backend_limit) is not int or backend_limit < 1):
        raise ValueError("已确认的后端并发上限须为正整数")
    settings = config["generation"]
    workers = min(settings["episode_workers"], len(config["production"]["episodes"]), max(0, agent_slots - 1))
    if settings.get("execution_mode") in {"half_episode_async_v1", "episode_async_v1"}:
        half=settings['execution_mode']=="half_episode_async_v1"
        if not half and current_half_counts is not None:
            raise ValueError('整话模式只接受episode_panel_counts，不接受旧半话长度')
        episodes = active_episodes if active_episodes is not None else config["production"]["episodes"][:max(1, workers)]
        if not isinstance(episodes, list) or not episodes or len(set(episodes)) != len(episodes) or len(episodes) > max(1, workers) or any(e not in config["production"]["episodes"] for e in episodes):
            raise ValueError("活动话须属于配置范围、不重复且不超过有效worker数")
        if episode_panel_counts is None and current_half_counts is None:
            return {"worker_agents": workers, "coordinator_runs_episode_if_no_worker": workers == 0,
                    "max_inflight": None, "batch_strategy": "half_episode" if half else "full_episode", "backend_capacity_verified": backend_limit is not None,
                    "note": "先审计真实格数并选择实际活动话；未核定后端容量时不虚报有效额度。"}
        counts = current_half_counts if current_half_counts is not None else episode_panel_counts
        if any(type(counts.get(e)) is not int or counts[e] < 1 for e in episodes):
            raise ValueError("活动话须有经脚本/当前计划审计的真实正整数格数")
        per_episode = {e: counts[e] if not half or current_half_counts is not None else (counts[e] + 1)//2 for e in episodes}
        per_cap = settings["max_inflight_per_episode"]
        if type(per_cap) is int: per_episode = {e: min(n, per_cap) for e, n in per_episode.items()}
        target = sum(per_episode.values())
        if type(settings["max_inflight_images"]) is int: target = min(target, settings["max_inflight_images"])
        return {"worker_agents": workers, "coordinator_runs_episode_if_no_worker": workers == 0,
                "target_per_episode": per_episode, "target_max_inflight": target,
                "max_inflight": min(target, backend_limit) if backend_limit is not None else None,
                "batch_strategy": "half_episode" if half else "full_episode", "backend_capacity_verified": backend_limit is not None,
                "note": "按实际活动话与源格数计算待提交池；实际在途请求服从有效许可和已核定工具容量。"}
    calls = min(settings["max_inflight_images"], max(1, workers) * settings["batch_size"], backend_limit if backend_limit is not None else 1)
    return {"worker_agents": workers, "coordinator_runs_episode_if_no_worker": workers == 0,
            "max_inflight": calls, "batch_size": settings["batch_size"],
            "backend_capacity_verified": backend_limit is not None,
            "note": "旧模式容量未知从1请求开始；不降模型或规格。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--agent-slots", type=int)
    parser.add_argument("--backend-limit", type=int)
    parser.add_argument("--active-episodes", nargs="+", help="当前实际活动话，不填仅演算配置前几话")
    parser.add_argument("--current-half-counts", help="当前半话实际长度JSON对象，第二半话/恢复时使用")
    parser.add_argument("--episode-panel-counts", help="经源脚本审计的话号到格数JSON对象；仅额度演算")
    args = parser.parse_args()
    try:
        config = read_config(args.config)
        result = {"status": "PASS", "memory_source": memory_source(config), "requested": config["generation"],
                  "preparation": config.get('preparation', {'policy':'half_scoped_v1'} if config.get('optimization') else None),
                  "optimization": config.get("optimization"), "execution":config.get('execution'), "framing":config.get('framing'), "background":config.get("background"), "readiness":config.get('readiness'),
                  "runtime":config.get('runtime'), "production_authorized": False, "read_only": True}
        if args.agent_slots is not None:
            result["effective"] = runtime_limits(config, args.agent_slots, args.backend_limit, json.loads(args.episode_panel_counts) if args.episode_panel_counts else None, args.active_episodes, json.loads(args.current_half_counts) if args.current_half_counts else None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(json.dumps({"status": "HOLD", "errors": [str(exc)]}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
