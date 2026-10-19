#!/usr/bin/env python3
"""Five-panel stage gates. Read evidence; never call image tools or grant approval."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from codex_reference_contract import read_json, checked_file
from style_contract import POLICY as STYLE_POLICY, validate_style, output_spec_errors
from staged_workflow import POLICY, DONE, read, approval_errors, basis_errors, qa_errors
from rule_memory import application_errors as memory_errors, binding_errors as memory_binding_errors

MODE = "batch5_v1"
SHOT_FIELDS = ("locked_script", "framing", "frame_ratio", "camera_view_signature",
               "character_bindings", "scene_binding", "continuity_contract", "visual_state_keys",
               "generation_dependencies", "design_dependencies", "requires_state_review", "memory_tags", "state_review_policy", "adjacent_face_comparison", "calibration_anchor", "rule_exceptions", "source_panel_id", "visual_resolution", "frame_ratio_reason", "visual_evidence_policy", "visual_evidence")


def build_plan(state, shots, source=None):
    """Deterministic source-contiguous batches; dependency edges remain per shot."""
    if state.get("execution_mode") in {"half_episode_async_v1", "episode_async_v1"}:
        from half_workflow import build_plan as half_plan
        return half_plan(state, shots, source)
    panels = shots.get("panels", shots.get("shot_design", []))
    if not panels:
        raise ValueError("镜头表为空")
    order = [p["panel_id"] for p in panels]
    if len(set(order)) != len(order):
        raise ValueError("源格重复")
    batch_size = state.get("batch_size", 5)
    if type(batch_size) is not int or not 1 <= batch_size <= 5:
        raise ValueError("batch_size必须为1到5的整数")
    batches, current, seen = [], [], set()
    pilot_count = min(5, len(order))
    def flush():
        if current:
            batches.append({"batch_id": f"B{len(batches)+1:03d}", "panel_ids": current.copy()})
            current.clear()
    for i, p in enumerate(panels):
        deps = p.get("generation_dependencies")
        if not isinstance(deps, list) or any(not isinstance(d, str) or d not in order[:i] for d in deps) or len(set(deps)) != len(deps):
            raise ValueError(f"{order[i]}:须明确generation_dependencies，只能引用本话前序源格")
        if type(p.get("requires_state_review")) is not bool:
            raise ValueError(f"{order[i]}:须明确requires_state_review布尔值")
        keys = p.get("visual_state_keys")
        if not isinstance(keys, list) or not keys or any(not isinstance(k, str) or not k.strip() for k in keys):
            raise ValueError(f"{order[i]}:视觉状态键缺失")
        anchor = p["requires_state_review"] or (i > 0 and bool(set(keys) - seen))
        if i == pilot_count or anchor:
            flush()
        current.append(order[i])
        if anchor or len(current) == batch_size:
            flush()
        seen.update(keys)
    flush()
    return {"policy": MODE, "source_snapshot": state["source_snapshot"],
            "visual_basis": state["visual_basis"], "shot_manifest": state["shot_manifest"],
            "max_batch_size": batch_size, "pilot_panel_ids": order[:pilot_count], "batches": batches}


def dependency_basis(root, package_path, packet, shot, basis, records, state=None):
    """Bind image-dependent shots to the exact checked predecessor image bytes."""
    deps = shot["generation_dependencies"]
    bound = packet.get("dependency_outputs", {})
    if not isinstance(bound, dict) or set(bound) != set(deps):
        raise ValueError("dependency_outputs须准确覆盖镜头的前格实图依赖")
    panel = packet["panels"][0]
    extra = []
    for pid in deps:
        record = records[pid]
        if record.get("status") not in DONE:
            raise ValueError(f"{pid}:前格实图尚未验收")
        checked_file(root, record.get("output"))
        checked_file(package_path.parent, bound[pid])
        if bound[pid]["sha256"] != record["output"]["sha256"]:
            raise ValueError(f"{pid}:前格图片换版，依赖调用及检查已失效")
        aliases = {r["alias"] for r in panel.get("reference_images", []) if r.get("sha256") == bound[pid]["sha256"]}
        bindings = [b for b in panel.get("reference_bindings", []) if b.get("alias") in aliases]
        if not aliases or not bindings or any(b.get("purpose") not in {"pose_interaction", "scene_view", "framing", "spatial_layout", "prop_state"} for b in bindings):
            raise ValueError(f"{pid}:前格实图须实际传入且只作动作/空间/构图/道具依据，不能替代身份衣装画风")
        extra.append(bound[pid])
    effective={**basis, "reference_files": [*basis["reference_files"], *extra]}
    if packet.get('calibration_repair'):
        if state is None:raise ValueError('校准编辑目标须有原生产状态，不可单独绕过来源核验')
        from calibration_repair import source_basis
        effective=source_basis(state,root,package_path,packet,effective)
    from visual_evidence import repair_basis
    return repair_basis(state,root,panel,effective,records)


def dispatch_errors(state, root, packet, pid, output_sha256=None):
    if "parallel_context" not in state:
        return ["并行执行回执不能删除上下文后按独立任务使用"] if "dispatch_receipt" in packet else []
    from parallel_dispatch import receipt_errors
    if state.get("execution_mode") in {"half_episode_async_v1", "episode_async_v1"}:
        receipt = packet.get("dispatch_receipt", {})
        context = packet.get("round_context", {})
        if any(receipt.get(k) != context.get(k) for k in ("batch_id", "round_id", "attempt_id")):
            return ["执行包round_context与实际调度回执不一致"]
    return receipt_errors(state["parallel_context"], root, state["book_id"], state["episode_id"],
                          pid, packet.get("dispatch_receipt"), output_sha256)


def cross_episode_errors(context):
    """Bind the coordinator's visual comparison to all current episode outputs."""
    control_path = Path(context["control_file"]).resolve()
    control = read(control_path)
    jobs = control["jobs"]
    if len(jobs) <= 1:
        return []
    ref = control.get("cross_episode_review")
    if not ref:
        return ["多话交付缺少跨话实际图片复核报告"]
    report = read(checked_file(control_path.parent, ref))
    errors = []
    if report.get("policy") != "cross_episode_review_v1" or report.get("book_id") != control["book_id"] or report.get("epoch") != control["epoch"] or report.get("shared_files") != control["shared_files"]:
        errors.append("跨话复核的本书/epoch/共用基准版本不一致")
    if report.get("status") != "PASS" or not isinstance(report.get("reviewer"), str) or not report["reviewer"].strip() or not isinstance(report.get("evidence"), str) or not report["evidence"].strip():
        errors.append("跨话比较尚未实际看图通过并记录审查者与依据")
    expected = []
    for job in jobs:
        episode_root = Path(job["root"]).resolve()
        name = Path(job.get("state_file", "00_输入审计/生产流程.json"))
        state_path = (episode_root / name).resolve()
        if name.is_absolute() or not state_path.is_relative_to(episode_root):
            raise ValueError("跨话状态路径越界")
        other = read(state_path)
        if other.get("book_id") != control["book_id"] or other.get("episode_id") != job["episode_id"] or other.get("execution_mode") not in {MODE, "half_episode_async_v1", "episode_async_v1"} or other.get("cancelled") or other.get("holds"):
            errors.append(f"{job['episode_id']}:本书/话/模式无效或已暂停取消")
        scoped = other.get("optimization_policy") in {"scoped_half_review_v1", "scoped_episode_review_v1"}
        from scoped_inputs import full_preparation
        whole = scoped and full_preparation(other)
        for key in (("source_script", "source_snapshot") if scoped and not whole else ("source_script", "source_snapshot", "visual_basis", "shot_manifest")):
            if other.get(key) != job["frozen_inputs"].get(key):
                errors.append(f"{job['episode_id']}:{key}已换版")
            checked_file(episode_root, other.get(key))
        if scoped:
            if not whole and job.get("frozen_halves") != other.get("half_inputs"):
                errors.append(f"{job['episode_id']}:最终半话冻结输入版本不一致")
            if whole and job.get('frozen_halves'):
                errors.append(f"{job['episode_id']}:全话准备不使用半话冻结资产/镜头")
            if other.get('execution_mode') == 'episode_async_v1':
                from scoped_episode_workflow import evaluate_episode as evaluate_scoped
            else:
                from scoped_half_workflow import evaluate_scoped
            verified = evaluate_scoped(other,episode_root,'scope_complete')
            if verified.get('next_action')!='READY_FOR_CROSS_REVIEW': errors.extend([f"{job['episode_id']}:半话放行不完整",*verified.get('errors',[])])
        source = read(checked_file(episode_root, other["source_snapshot"]))
        records = other.get("panels", [])
        if not records or [r.get("panel_id") for r in records] != source.get("panel_ids") or any(r.get("status") not in DONE for r in records):
            errors.append(f"{job['episode_id']}:尚非完整已检查源格清单")
        for r in records:
            checked_file(episode_root, r.get("output"))
            checked_file(episode_root, r.get("qa_report"))
            errors.extend(f"{job['episode_id']}:{r['panel_id']}:{e}" for e in qa_errors(episode_root, r))
        expected.append({"job_id": job["job_id"], "episode_id": job["episode_id"],
                         **({"half_inputs": other["half_inputs"]} if scoped and not whole else {"visual_basis": other["visual_basis"], "shot_manifest": other["shot_manifest"]}),
                         "outputs": [r["output"] for r in records], "qa_reports": [r["qa_report"] for r in records]})
    if report.get("episodes") != expected:
        errors.append("跨话复核未准确覆盖全部话及当前源序图片/QA版本")
    return errors


def completed_errors(state, root, record, shot, basis, records):
    errors = qa_errors(root, record)
    packet = read(checked_file(root, record.get("package_manifest")))
    from panel_readiness import binding_errors as readiness_binding
    errors.extend(readiness_binding(state,packet))
    if state.get('preparation_policy')=='episode_preparation_v1' and packet.get('preparation_policy')!=state['preparation_policy']:
        errors.append('验收包未绑定获批全话准备模式')
    from frame_ratio_plan import binding_errors as ratio_binding_errors
    errors.extend(ratio_binding_errors(state,packet))
    if state.get('execution_contract') and packet.get('execution_contract')!=state['execution_contract']:errors.append('执行包缺少本次完整执行合同；不能使用本话临时检查器降级')
    from continuity_context import binding_errors as prior_binding_errors
    errors.extend(prior_binding_errors(state,root,packet,checked_file(root,record['package_manifest']).parent))
    if state.get("optimization_policy") in {"scoped_half_review_v1", "scoped_episode_review_v1"} and packet.get("optimization_policy") != state["optimization_policy"]:
        errors.append("优化执行包缺少相同策略，不能退回旧输入合同")
    errors.extend(memory_binding_errors(state, packet=packet))
    tags=[]
    if state.get('execution_contract')=='comic_execution_v2':
        from continuity_context import rule_tags
        shot_path=checked_file(root,state['shot_manifest'])
        tags=rule_tags(read(shot_path),shot_path.parent,shot)
    errors.extend(memory_errors(state.get("memory_source"), "shot_design", shot, root,context_tags=tags,scope=state))
    if packet.get("book_id") != state["book_id"] or packet.get("episode_id") != state["episode_id"]:
        errors.append("验收包本书/本话不一致")
    if packet.get("execution_mode") != state.get("execution_mode", MODE) or len(packet.get("panels", [])) != 1:
        return errors + ["验收包执行模式不一致或非单格包"]
    panel = packet["panels"][0]
    from visual_evidence import binding_errors as visual_binding, packet_errors as visual_packet_errors
    errors.extend(visual_binding(state, packet))
    errors.extend(visual_packet_errors(state, shot, panel, basis))
    from visual_evidence import repair_binding_errors
    errors.extend(repair_binding_errors(panel, record))
    if state.get('execution_mode') == 'episode_async_v1':
        from image_risk_guards import packet_errors as risk_packet_errors
        errors.extend(risk_packet_errors(shot,panel))
    from repair_input_guard import repair_errors as repair_input_errors
    errors.extend(repair_input_errors(panel, require_focus=state.get('execution_mode') == 'episode_async_v1'))
    if state.get('execution_contract')=='comic_execution_v2' and panel.get('source_panel_id')!=record.get('source_panel_id'):errors.append('SOURCE_ID_HOLD:验收包原格号与准确源映射不一致')
    effective_basis = dependency_basis(root, checked_file(root, record["package_manifest"]), packet, shot, basis, records,state)
    errors.extend(basis_errors(panel, effective_basis))
    if state.get("visual_evidence_policy"):
        from visual_evidence import comparison_errors
        qa = read(checked_file(root, record["qa_report"]))
        item = next((q for q in qa.get("panels", []) if q.get("panel_id") == record["panel_id"]), {})
        errors.extend(comparison_errors(panel, item, records, root))
    errors.extend(dispatch_errors(state, root, packet, record["panel_id"], record["output"]["sha256"]))
    for key in SHOT_FIELDS:
        if panel.get(key) != shot.get(key):
            errors.append(f"{record['panel_id']}:{key}与获批镜头不一致")
    return errors


def input_errors(state, root, record, shot, basis, records, *, candidate=False):
    """Full existing single-panel preflight; batching does not weaken inputs."""
    book, episode, pid = state["book_id"], state["episode_id"], record["panel_id"]
    authorization = state.get("production_authorization")
    errors = approval_errors(authorization, root, [state["source_script"]], book, episode)
    if pid not in (authorization or {}).get("panel_ids", []) and episode+'-'+pid not in (authorization or {}).get('panel_ids',[]):
        errors.append("当前格不在已授权生产范围")
    manifest_path = checked_file(root, record.get("package_manifest"))
    packet = read(manifest_path)
    from panel_readiness import binding_errors as readiness_binding
    errors.extend(readiness_binding(state,packet))
    if state.get('preparation_policy')=='episode_preparation_v1' and packet.get('preparation_policy')!=state['preparation_policy']:
        errors.append('执行包未绑定获批全话准备模式')
    from frame_ratio_plan import binding_errors as ratio_binding_errors
    errors.extend(ratio_binding_errors(state,packet))
    if state.get("input_priority_policy") and packet.get("input_priority_policy") != state["input_priority_policy"]:
        errors.append("执行包input_priority_policy与本话冻结合同不一致")
    if state.get('execution_contract') and packet.get('execution_contract')!=state['execution_contract']:errors.append('执行包缺少本次完整执行合同；不能使用本话临时检查器降级')
    from continuity_context import binding_errors as prior_binding_errors
    errors.extend(prior_binding_errors(state,root,packet,manifest_path.parent))
    subset_path = checked_file(root, record.get("shot_subset"))
    subset = read(subset_path)
    if state.get("input_priority_policy") and subset.get("input_priority_policy") != state["input_priority_policy"]:
        errors.append("镜头选集input_priority_policy与本话冻结合同不一致")
    if state.get('execution_contract')=='comic_execution_v2':
        errors.extend(prior_binding_errors(state,root,subset,subset_path.parent))
        a=packet.get('continuity_context');b=subset.get('continuity_context')
        if bool(a)!=bool(b) or a and read(checked_file(manifest_path.parent,a))!=read(checked_file(subset_path.parent,b)):errors.append('镜头选集与执行包须携带相同真实前格上下文')
    if packet.get("book_id") != book or packet.get("episode_id") != episode:
        errors.append("执行包本书/本话不一致")
    if subset.get("panels") != [shot]:
        errors.append("单格镜头快照不是获批全话记录的准确选集")
    if packet.get("execution_mode") != state.get("execution_mode", MODE) or packet.get("style_policy") != STYLE_POLICY or packet.get("workflow_policy") != POLICY or len(packet.get("panels", [])) != 1:
        return errors + ["每次请求须为当前模式的单格执行包，保留阶段/画风合同"]
    panel = packet["panels"][0]
    from visual_evidence import binding_errors as visual_binding, packet_errors as visual_packet_errors
    errors.extend(visual_binding(state, packet))
    errors.extend(visual_packet_errors(state, shot, panel, basis))
    from visual_evidence import repair_binding_errors
    errors.extend(repair_binding_errors(panel, record))
    if state.get('execution_mode') == 'episode_async_v1':
        from image_risk_guards import packet_errors as risk_packet_errors
        errors.extend(risk_packet_errors(shot,panel))
    from repair_input_guard import repair_errors as repair_input_errors
    errors.extend(repair_input_errors(panel, require_focus=state.get('execution_mode') == 'episode_async_v1'))
    if state.get('execution_contract'):
        source=read(checked_file(root,state['source_snapshot']))
        original=next(p['source_panel_id'] for p in source['id_mapping']['pairs'] if p['panel_id']==pid)
        if record.get('source_panel_id')!=original or panel.get('source_panel_id')!=original:errors.append('源编号映射未原样传入进度/执行包')
    if state.get("optimization_policy") in {"scoped_half_review_v1", "scoped_episode_review_v1"} and packet.get("optimization_policy") != state["optimization_policy"]:
        errors.append("优化执行包缺少相同策略，不能退回旧输入合同")
    errors.extend(memory_binding_errors(state, packet=packet))
    tags=[];generation_tags=[]
    if state.get('execution_contract')=='comic_execution_v2':
        from continuity_context import rule_tags
        shot_path=checked_file(root,state['shot_manifest'])
        tags=rule_tags(read(shot_path),shot_path.parent,shot)
        generation_tags=rule_tags(packet,manifest_path.parent,panel)
        if tags!=generation_tags:errors.append('镜头与执行包的前格规则触发不一致')
    errors.extend(memory_errors(state.get("memory_source"), "shot_design", shot, root,context_tags=tags,scope=state))
    errors.extend(memory_errors(state.get("memory_source"), "generation", panel, manifest_path.parent,context_tags=generation_tags,scope=state))
    if state.get("memory_source") and record.get("status") == "REPAIR_AUTHORIZED" and panel.get("operation") != "repair":
        errors.append("MEMORY_HOLD:返修执行包必须声明operation=repair")
    if panel.get("panel_id") != pid or any(panel.get(k) != shot.get(k) for k in SHOT_FIELDS):
        errors.append("执行格号/画面/依赖与批准镜头不一致")
    effective_basis = dependency_basis(root, manifest_path, packet, shot, basis, records,state)
    errors.extend(basis_errors(panel, effective_basis))
    if not candidate:
        errors.extend(dispatch_errors(state, root, packet, pid))
    from validate_preproduction import Gate
    errors.extend(Gate(root, expected_panel_ids=[pid]).run(subset_path, manifest_path)["errors"])
    errors.extend(validate_style(panel, manifest_path.parent))
    errors.extend(output_spec_errors(panel))
    if panel.get("generation_execution", {}).get("status") != "NOT_RUN":
        errors.append("仅NOT_RUN的新尝试允许调用；已有结果先验收或另建返修版本")
    return errors


def batch_review_errors(state, root, batch, records, previous):
    ref = state.get("batch_reviews", {}).get(batch["batch_id"])
    if not ref:
        return ["缺少本批逐图对照及连续性审查报告"]
    report = read(checked_file(root, ref))
    expected = {"policy": "batch_review_v1", "book_id": state["book_id"],
                "episode_id": state["episode_id"], "batch_id": batch["batch_id"],
                "panel_ids": batch["panel_ids"], "visual_basis": state["visual_basis"],
                "shot_manifest": state["shot_manifest"],
                "outputs": [r["output"] for r in records],
                "previous_outputs": [r["output"] for r in previous]}
    errors = [f"批次审查版本或范围不一致:{k}" for k, v in expected.items() if report.get(k) != v]
    if report.get("status") != "PASS" or not isinstance(report.get("reviewer"), str) or not report["reviewer"].strip() or not isinstance(report.get("evidence"), str) or not report["evidence"].strip():
        errors.append("批次连续性尚未实际检查通过并记录审查者/观察依据")
    for item in [report.get("visual_basis"), report.get("shot_manifest"), *report.get("outputs", []), *report.get("previous_outputs", [])]:
        checked_file(root, item)
    return errors


def evaluate_batch(state, root, check="status", requested=None):
    root = Path(root).resolve()
    def result(action, errors=(), batch=None, eligible=()):
        return {"policy": POLICY, "execution_mode": MODE,
                "status": "PASS" if not errors and action in {"READY_FOR_BATCH_PANEL", "READY_TO_PACKAGE"} else "HOLD",
                "next_action": action, "batch_id": (batch or {}).get("batch_id"),
                "batch_panel_ids": (batch or {}).get("panel_ids", []),
                "eligible_panel_ids": list(eligible), "cursor": requested,
                "errors": list(errors), "user_acceptance": "NOT_GRANTED_BY_SCRIPT"}
    try:
        book, episode = state.get("book_id"), state.get("episode_id")
        if state.get("policy") != POLICY or state.get("execution_mode") != MODE or not book or not episode:
            return result("COMPLETE_INPUT_AUDIT", ["流程/模式/书话标识缺失"])
        if state.get("cancelled") is True:
            return result("CANCELLED", ["用户取消；不得自动恢复"])
        if state.get("holds"):
            return result("RESOLVE_HOLD", state["holds"])
        if "parallel_context" in state:
            from parallel_dispatch import context_errors
            errors = context_errors(state["parallel_context"], root, book, episode)
            if errors:
                return result("PARALLEL_HOLD", errors)
        checked_file(root, state.get("source_script"))
        source = read(checked_file(root, state.get("source_snapshot")))
        order = source.get("panel_ids")
        if not isinstance(order, list) or not order or any(not isinstance(p, str) for p in order) or len(set(order)) != len(order):
            return result("COMPLETE_INPUT_AUDIT", ["源格序为空/重复/无效"])
        if source.get("source_sha256") != state["source_script"]["sha256"] or set(source.get("locked_scripts", {})) != set(order):
            return result("COMPLETE_INPUT_AUDIT", ["源快照缺少原文或原稿版本不一致"])
        basis = read(checked_file(root, state.get("visual_basis")))
        if basis.get("book_id") != book or basis.get("episode_id") != episode or not basis.get("reference_files"):
            return result("COMPLETE_INPUT_AUDIT", ["视觉基准归属或实际参考缺失"])
        for ref in basis["reference_files"]:
            checked_file(root, ref)
        gates = state.get("gates", {})
        errors = approval_errors(gates.get("visual_basis"), root, [state["source_script"], state["source_snapshot"], state["visual_basis"]], book, episode)
        if errors:
            return result("WAIT_VISUAL_BASIS_APPROVAL", errors)
        shots = read(checked_file(root, state.get("shot_manifest")))
        memory_binding = memory_binding_errors(state, shots=shots)
        if memory_binding:
            return result("MEMORY_HOLD", memory_binding)
        panels = shots.get("panels", shots.get("shot_design", []))
        if shots.get("execution_mode") != MODE or [p.get("panel_id") for p in panels] != order:
            return result("REPAIR_SHOTS", ["获批镜头须声明batch5_v1且格序与源快照一致"])
        if any(p.get("locked_script") != source["locked_scripts"][p["panel_id"]] for p in panels):
            return result("REPAIR_SHOTS", ["镜头原文与源快照不一致"])
        errors = approval_errors(gates.get("shot_design"), root, [state["visual_basis"], state["shot_manifest"]], book, episode)
        if errors:
            return result("WAIT_SHOT_APPROVAL", errors)
        expected = build_plan(state, shots)
        plan = read(checked_file(root, state.get("batch_plan")))
        if plan != expected:
            return result("REBUILD_BATCH_PLAN", ["批次计划与源序/获批镜头/当前基准不一致"])
        records = state.get("panels", [])
        if [r.get("panel_id") for r in records] != order:
            return result("COMPLETE_INPUT_AUDIT", ["流程记录格序与源快照不一致"])
        by_id, shot_by_id = {r["panel_id"]: r for r in records}, {p["panel_id"]: p for p in panels}
        seen, anchors = set(), set()
        for i, p in enumerate(panels):
            if p["requires_state_review"] or (i > 0 and set(p["visual_state_keys"]) - seen):
                anchors.add(p["panel_id"])
            seen.update(p["visual_state_keys"])
        pilot = plan["pilot_panel_ids"]
        previous, checked_ids = [], set()
        for bidx, batch in enumerate(plan["batches"]):
            current = [by_id[p] for p in batch["panel_ids"]]
            # Later batches must stay untouched until every prior batch clears.
            # Once this batch is complete, they are evaluated in the next loop.
            for r in current:
                if r.get("status") in DONE:
                    errors = completed_errors(state, root, r, shot_by_id[r["panel_id"]], basis, by_id)
                    if errors:
                        return result("REVIEW_BATCH_PANEL", errors, batch)
                    checked_ids.add(r["panel_id"])
            complete = all(r.get("status") in DONE for r in current)
            if complete:
                errors = batch_review_errors(state, root, batch, current, previous)
                if errors:
                    return result("REVIEW_BATCH", errors, batch)
                for r in current:
                    if r["panel_id"] in anchors:
                        errors = approval_errors(state.get("state_reviews", {}).get(r["panel_id"]), root,
                                                 [state["visual_basis"], state["shot_manifest"], r["output"]], book, episode)
                        if errors:
                            return result("WAIT_NEW_STATE_APPROVAL", errors, batch)
                if pilot[-1] in batch["panel_ids"]:
                    errors = approval_errors(gates.get("pilot"), root,
                                             [state["visual_basis"], state["shot_manifest"], *[by_id[p]["output"] for p in pilot]], book, episode)
                    if errors:
                        return result("WAIT_PILOT_APPROVAL", errors, batch)
                previous = current
                continue
            later = [by_id[p] for b in plan["batches"][bidx+1:] for p in b["panel_ids"]]
            if any(r.get("status") != "PENDING" for r in later):
                return result("OUT_OF_BATCH_HOLD", ["后批已有执行/返修状态；须隔离越批结果后恢复原停点"], batch)
            if check == "deliver":
                return result("EPISODE_INCOMPLETE", ["本批尚未全部验收"], batch)
            blockers = [r["panel_id"] for r in current if r.get("status") not in DONE | {"PENDING", "REPAIR_AUTHORIZED", "IN_FLIGHT", "GENERATED"}]
            if blockers:
                return result("RESOLVE_BATCH_HOLD", ["本批失败/取消/未知状态:" + ",".join(blockers)], batch)
            eligible = [r["panel_id"] for r in current if r.get("status") in {"PENDING", "REPAIR_AUTHORIZED"}
                        and all(d in checked_ids for d in shot_by_id[r["panel_id"]]["generation_dependencies"])]
            if check == "status":
                return result("PREPARE_BATCH_INPUT" if eligible else "WAIT_OR_REVIEW_BATCH", batch=batch, eligible=eligible)
            if requested not in batch["panel_ids"]:
                return result("SOURCE_BATCH_HOLD", ["只允许当前连续源格批次，禁止跳批"], batch, eligible)
            if requested not in eligible:
                return result("DEPENDENCY_OR_RESULT_HOLD", ["该格已在途/有结果/取消，或前格实图依赖未验收"], batch, eligible)
            if "parallel_context" in state:
                from parallel_dispatch import context_errors
                errors = context_errors(state["parallel_context"], root, book, episode, requested)
                if errors:
                    return result("PARALLEL_HOLD", errors, batch, eligible)
            errors = input_errors(state, root, by_id[requested], shot_by_id[requested], basis, by_id)
            return result("INPUT_HOLD" if errors else "READY_FOR_BATCH_PANEL", errors, batch, eligible)
        if check == "generate":
            return result("EPISODE_COMPLETE", ["本话无待生成格"])
        if "parallel_context" in state:
            errors = cross_episode_errors(state["parallel_context"])
            if errors:
                return result("WAIT_CROSS_EPISODE_REVIEW", errors)
        errors = approval_errors(gates.get("final"), root,
                                 [state["visual_basis"], state["shot_manifest"], *[r["output"] for r in records]], book, episode)
        return result("WAIT_FINAL_APPROVAL" if errors else "READY_TO_PACKAGE", errors)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
        return result("INPUT_EVIDENCE_HOLD", [str(exc)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--root")
    parser.add_argument("--write-plan", required=True, help="新计划文件；不覆盖、不写批准或状态")
    args = parser.parse_args()
    state_path = Path(args.state).resolve()
    root = Path(args.root).resolve() if args.root else state_path.parent.parent
    try:
        state = read(state_path)
        if state.get("optimization_policy") == "scoped_half_review_v1":
            shots = {}
            source = read(checked_file(root, state.get("source_snapshot")))
        else:
            shots = read(checked_file(root, state.get("shot_manifest")))
            source = None
        plan = build_plan(state, shots, source)
        dest = Path(args.write_plan).resolve()
        dest.relative_to(root)
        with dest.open("x", encoding="utf-8") as output:
            json.dump(plan, output, ensure_ascii=False, indent=2)
            output.write("\n")
        print(json.dumps({"status": "PLAN_WRITTEN_NOT_APPROVED", "path": str(dest)}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"status": "HOLD", "errors": [str(exc)]}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
