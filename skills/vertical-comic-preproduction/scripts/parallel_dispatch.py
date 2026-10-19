#!/usr/bin/env python3
"""Read-only parallel episode dispatch contract; never spawns agents or generates images.

episode_slot_lease_v1 uses coordinator-assigned capacity and owner-local receipts;
slot_leases.effective_control presents that ledger to the original validators.
The coordinator/worker handshake below applies only to legacy permit mode.

The coordinator alone atomically replaces the control JSON and reserves permits
before dispatch. A worker checks immediately before a tool call, then asks the
coordinator to mark its permit IN_FLIGHT. This checker cannot make that handoff
atomic, authenticate user approval, or prove backend concurrency capacity. Never
use a passed check as permission to reuse a permit. Returned images carry their
job/worker/epoch/permit identifiers; old-epoch returns remain candidates until
explicit carry-forward re-review is recorded without rewriting the old receipt.

context: {control_file: absolute path, job_id, worker_id, epoch}.
All shared_files paths are relative to control_file.parent. At least one
style_basis JSON (book_id and style object) and state_registry are frozen there;
actual style image bytes are also listed. State registries are existing approved
ledgers, not a second set of identity definitions. Jobs bind the four episode
state input references via frozen_inputs and have exclusive episode roots and
worker owners. A generation check needs exactly one RESERVED permit. Control
writes and actual agent/tool orchestration remain coordinator responsibilities.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from codex_reference_contract import read_json, digest

POLICY = "parallel_episodes_v1"
INPUTS = ("source_script", "source_snapshot", "visual_basis", "shot_manifest")
ACTIVE_JOBS = {"ASSIGNED", "RUNNING", "WAIT_REVIEW", "HOLD"}
TERMINAL_JOBS = {"COMPLETED", "CANCELLED"}
QUEUED_JOBS = {"QUEUED"}
ACTIVE_PERMITS = {"RESERVED", "IN_FLIGHT", "RESULT_UNKNOWN"}
TERMINAL_PERMITS = {"COMPLETED", "RELEASED", "CANCELLED"}


def _read(path):
    return read_json(path)


def _file(root, ref):
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise ValueError("文件引用必须包含path/sha256")
    name = Path(ref["path"])
    path = (root / name).resolve()
    if name.is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError("冻结引用必须为根目录内相对路径")
    if not path.is_file():
        raise ValueError(f"冻结文件不存在: {name}")
    if digest(path) != ref.get("sha256"):
        raise ValueError(f"冻结文件哈希不符: {name}")
    return path


def _positive(value):
    return type(value) is int and value > 0


def context_errors(context, episode_root, book_id, episode_id, panel_id=None):
    """Validate a coordinator snapshot and optional one-use generation reservation.

    Read episode state from job.state_file (default 00_输入审计/生产流程.json).
    None is not a valid parallel context: callers explicitly choose serial mode
    by not invoking this function. Returns errors; never edits any state.
    """
    errors = []
    try:
        if not isinstance(context, dict):
            return ["缺少并行调度上下文"]
        control_path = Path(context.get("control_file", ""))
        if not control_path.is_absolute():
            return ["control_file必须是绝对路径"]
        control_path = control_path.resolve()
        control = _read(control_path)
        if control.get("policy") != POLICY or (type(control.get("version")) is not int or control.get("version") != 1):
            errors.append("并行调度合同版本错误")
        if control.get("book_id") != book_id:
            errors.append("并行批次书名不一致")
        epoch = control.get("epoch")
        if not _positive(epoch) or not _positive(context.get("epoch")) or context.get("epoch") != epoch:
            errors.append("并行epoch已过期或无效；旧返回不得采用")
        if control.get("cancelled") is not False:
            errors.append("批次取消或取消状态缺失；不得发出新请求")
        if not isinstance(control.get("holds"), list) or control["holds"]:
            errors.append("全局HOLD或缺少holds；先处理共用问题")
        for key in ("max_workers", "max_inflight"):
            if not _positive(control.get(key)):
                errors.append(f"{key}必须是正整数，由总控按实际容量设置")

        shared = control.get("shared_files")
        if not isinstance(shared, list) or not shared:
            return errors + ["缺少共用冻结文件"]
        shared_paths = [_file(control_path.parent, ref) for ref in shared]
        if len(set(shared_paths)) != len(shared_paths):
            errors.append("共用冻结文件路径重复")
        style_refs = [path for ref, path in zip(shared, shared_paths) if ref.get("role") == "style_basis"]
        if len(style_refs) != 1:
            return errors + ["共用style_basis须唯一"]
        if not any(ref.get("role") == "state_registry" for ref in shared):
            errors.append("缺少冻结的共用状态账本state_registry")
        shared_basis = _read(style_refs[0])
        shared_style = shared_basis.get("style", {})
        hashes = shared_style.get("reference_sha256")
        traits = shared_style.get("traits")
        if shared_basis.get("book_id") != book_id or not isinstance(hashes, list) or not hashes or not isinstance(traits, dict) or not traits:
            errors.append("共用画风基准的书名、样例或特征缺失")
        elif not set(hashes).issubset({ref.get("sha256") for ref in shared}):
            errors.append("共用样例实际文件未全部纳入冻结校验")

        jobs = control.get("jobs")
        permits = control.get("permits")
        if not isinstance(jobs, list) or not jobs or not isinstance(permits, list):
            return errors + ["jobs/permits须为清单且jobs非空"]
        for key in ("job_id", "episode_id", "root"):
            values = [job.get(key) for job in jobs]
            if any(not isinstance(v, str) or not v for v in values) or len(set(values)) != len(values):
                errors.append(f"任务{key}为空或重复")
        roots = []
        for job in jobs:
            job_root = Path(job.get("root", ""))
            if not job_root.is_absolute():
                errors.append("每话任务root必须为绝对路径")
            roots.append(job_root.resolve())
            if job.get("status") not in ACTIVE_JOBS | TERMINAL_JOBS | QUEUED_JOBS:
                errors.append("未知任务状态")
        if len(set(roots)) != len(roots) or any(a != b and (a.is_relative_to(b) or b.is_relative_to(a)) for a in roots for b in roots):
            errors.append("任务根目录重复或嵌套；不能隔离写入")
        active_jobs = [job for job in jobs if job.get("status") in ACTIVE_JOBS]
        owners = [job.get("worker_id") for job in active_jobs]
        if any(not isinstance(owner, str) or not owner for owner in owners) or len(set(owners)) != len(owners):
            errors.append("活动任务owner为空或同一worker接管多话")
        if _positive(control.get("max_workers")) and len(active_jobs) > control["max_workers"]:
            errors.append("活动工作任务超过max_workers")
        matches = [job for job in jobs if job.get("job_id") == context.get("job_id")]
        if len(matches) != 1:
            return errors + ["上下文job_id不存在或重复"]
        job = matches[0]
        root = Path(episode_root).resolve()
        if Path(job.get("root", "")).resolve() != root or job.get("episode_id") != episode_id:
            errors.append("任务话号或根目录不一致")
        if job.get("worker_id") != context.get("worker_id") or not context.get("worker_id"):
            errors.append("当前worker不是任务唯一owner")
        if job.get("status") not in ACTIVE_JOBS and not (job.get("status") == "COMPLETED" and panel_id is None):
            errors.append("任务未被接管或已取消/结束，不能继续采用返回或生成")
        if job.get("status") == "HOLD" or job.get("holds"):
            errors.append("本话HOLD")
        if panel_id is not None and job.get("status") not in {"ASSIGNED", "RUNNING"}:
            errors.append("本话尚待审查，不能发出新请求")
        if job.get("dispatch_pause") not in (None, False, True):
            errors.append("dispatch_pause须为布尔值")
        if panel_id is not None and job.get("dispatch_pause") is True:
            errors.append("本话已暂停新请求；在途返回及QA仍须收尾")
        state_name = Path(job.get("state_file", "00_输入审计/生产流程.json"))
        state_path = (root / state_name).resolve()
        if state_name.is_absolute() or not state_path.is_relative_to(root):
            return errors + ["state_file必须为话根目录内相对路径"]
        state = _read(state_path)
        from slot_leases import effective_control, enabled as leased
        if state.get('runtime',{}).get('dispatch_policy')=='episode_slot_lease_v1' and not leased(control):
            errors.append('LEASE_HOLD: 当前话要求总控先分配租约')
        control = effective_control(control,state,context)
        permits = control['permits']
        if state.get("book_id") != book_id or state.get("episode_id") != episode_id or state.get("parallel_context") != context:
            errors.append("本话生产状态与调度上下文不一致")
        scoped = state.get("optimization_policy") in {"scoped_half_review_v1", "scoped_episode_review_v1"}
        from scoped_inputs import full_preparation
        whole = scoped and full_preparation(state)
        if scoped:
            from scoped_inputs import global_hold, blocked_panels, half_view, generation_holds
            has_hold = global_hold(state.get("holds"))
            if panel_id is not None:
                plan = _read(_file(root, state.get("batch_plan")))
                windows = [b for b in plan.get("batches",[]) if panel_id in b.get("panel_ids",[])]
                if len(windows)!=1: errors.append("请求不属于准确半话计划")
                else:
                    local=half_view(state, windows[0]["batch_id"])
                    shots=_read(_file(root,local["shot_manifest"]))
                    source=_read(_file(root,state["source_snapshot"]))
                    blocked,_=blocked_panels(generation_holds(state),source["panel_ids"],windows[0],shots.get("panels",[]))
                    has_hold = has_hold or panel_id in blocked
        else: has_hold = bool(state.get("holds"))
        if state.get("cancelled") is True or has_hold:
            errors.append("本话状态已取消或本请求范围HOLD")
        frozen = job.get("frozen_inputs", {})
        for key in (INPUTS[:2] if scoped and not whole else INPUTS):
            if not isinstance(frozen.get(key), dict) or frozen[key] != state.get(key):
                errors.append(f"本话{key}与任务冻结版本不一致")
            else:
                _file(root, frozen[key])
        if scoped and not whole:
            bid=job.get("active_batch_id")
            local=half_view(state,bid)
            frozen_halves=job.get("frozen_halves",{})
            if frozen_halves.get(bid)!=state.get("half_inputs",{}).get(bid): errors.append("当前半话输入与调度冻结范围不一致")
            for frozen_bid,refs in frozen_halves.items():
                if state.get("half_inputs",{}).get(frozen_bid)!=refs: errors.append("已有冻结半话被改写")
                for ref in refs.values(): _file(root,ref)
            basis = _read(_file(root,local["visual_basis"]))
        elif whole:
            if job.get("frozen_halves"):
                errors.append("全话准备不使用半话冻结资产/镜头")
            basis = _read(_file(root,state.get("visual_basis")))
        else:
            basis = _read(_file(root, state.get("visual_basis")))
        if basis.get("book_id") != book_id or basis.get("episode_id") != episode_id or basis.get("style") != shared_style:
            errors.append("本话视觉基准未绑定共用书名/话号/画风样例与特征")
        if panel_id is not None and panel_id not in [p.get("panel_id") for p in state.get("panels", [])]:
            errors.append("请求格号不属于本话生产清单")
        if panel_id is not None:
            from panel_readiness import enabled as scoped_preparation,report as readiness_report
            if scoped_preparation(state):
                readiness=readiness_report(state,root)
                if readiness['global_errors'] or panel_id in readiness['blocked_panel_ids']:errors.append('本格准备/设计/跨话或实际依赖仍未就绪，不能领取许可')

        permit_ids = [p.get("permit_id") for p in permits]
        if any(not isinstance(p, str) or not p for p in permit_ids) or len(set(permit_ids)) != len(permit_ids):
            errors.append("permit_id为空或重复")
        active = [p for p in permits if p.get("status") in ACTIVE_PERMITS]
        if any(p.get("status") not in ACTIVE_PERMITS | TERMINAL_PERMITS for p in permits):
            errors.append("未知permit状态")
        if _positive(control.get("max_inflight")) and len(active) > control["max_inflight"]:
            errors.append("活动请求超过max_inflight")
        # Half windows use a separate per-episode ceiling and immutable round receipts.
        for owner_job in jobs:
            if owner_job.get("status") not in ACTIVE_JOBS: continue
            if owner_job.get("job_id") != context.get("job_id"): continue
            owner_root = Path(owner_job["root"]).resolve()
            owner_name = Path(owner_job.get("state_file", "00_输入审计/生产流程.json"))
            owner_path = (owner_root / owner_name).resolve()
            if owner_name.is_absolute() or not owner_path.is_relative_to(owner_root):
                errors.append("任务state_file越界"); continue
            if not owner_path.is_file():
                if owner_job.get("status") in ACTIVE_JOBS: errors.append("活动话缺少磁盘状态")
                continue
            owner_state = _read(owner_path)
            if owner_state.get("execution_mode") not in {"half_episode_async_v1", "episode_async_v1"}: continue
            limit = owner_job.get("max_inflight")
            batch_id = owner_job.get("active_batch_id")
            plan = _read(_file(owner_root, owner_state.get("batch_plan")))
            windows = [b for b in plan.get("batches", []) if b.get("batch_id") == batch_id]
            if not _positive(limit) or len(windows) != 1 or limit > len(windows[0]["panel_ids"]):
                if owner_state.get("execution_mode") == "half_episode_async_v1":
                    errors.append("半话任务须有准确active_batch_id及不超过本半话格数的max_inflight")
                else:errors.append("整话任务须有active_batch_id=EPISODE及不超过整话格数的max_inflight")
                continue
            used = [p for p in permits if p.get("job_id") == owner_job["job_id"] and p.get("epoch") == epoch and p.get("status") in {"RESERVED", "IN_FLIGHT", "RESULT_UNKNOWN", "COMPLETED"}]
            phases = {}
            for p in used:
                key = (p.get("panel_id"), p.get("batch_id"), p.get("round_id"))
                phases.setdefault(key, []).append(p.get("permit_id"))
            if any(len(attempts) > 1 for attempts in phases.values()):
                errors.append("同一话同格同轮已有真实尝试，不得换attempt_id伪装首轮重试")
            own = [p for p in active if p.get("job_id") == owner_job["job_id"]]
            if len(own) > limit: errors.append("本话活动请求超过本话max_inflight")
            owner_records = {r["panel_id"]: r for r in owner_state.get("panels", [])}
            for permit in own:
                r = owner_records.get(permit.get("panel_id"), {})
                if permit.get("batch_id") != batch_id or permit.get("panel_id") not in windows[0]["panel_ids"] or type(permit.get("round_id")) is not int or permit["round_id"] not in (1, 2) or any(permit.get(k) != r.get(k) for k in ("attempt_id", "round_id")) or not permit.get("attempt_id"):
                    errors.append("半话活动permit批次/轮次/尝试与当前状态不一致")

        pairs = [(p.get("job_id"), p.get("panel_id")) for p in active]
        if len(set(pairs)) != len(pairs):
            errors.append("同话同格有重复活动permit")
        job_map = {j.get("job_id"): j for j in jobs}
        for permit in active:
            owner_job = job_map.get(permit.get("job_id"))
            if not owner_job or owner_job.get("status") not in ACTIVE_JOBS or permit.get("worker_id") != owner_job.get("worker_id") or not _positive(permit.get("epoch")) or permit.get("epoch") != epoch or not isinstance(permit.get("panel_id"), str) or not permit["panel_id"]:
                errors.append("活动permit的owner/job/epoch/格号无效")
        if panel_id is not None:
            current = [p for p in active if p.get("job_id") == context.get("job_id") and p.get("panel_id") == panel_id]
            if len(current) != 1 or current[0].get("status") != "RESERVED":
                errors.append("新生图须有唯一RESERVED permit；已IN_FLIGHT不得重复提交")
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        errors.append(f"并行合同读取失败: {exc}")
    return errors


def handoff_readiness(control, state, job_id, *, old_writer_stopped):
    """Advisory only: coordinator still rebinds unique owner and reruns full gates."""
    errors = []
    jobs = [j for j in control.get("jobs", []) if j.get("job_id") == job_id]
    if len(jobs) != 1:
        return ["交接任务须唯一"]
    if old_writer_stopped is not True:
        errors.append("旧执行者仍可能写入；须先停止并保存检查点")
    if jobs[0].get("status") not in ACTIVE_JOBS:
        errors.append("任务不是可交接的活动话")
    permits = [*control.get('permits',[]), *state.get('dispatch_ledger',[])]
    if any(p.get("job_id") == job_id and p.get("status") in ACTIVE_PERMITS for p in permits):
        errors.append("存在RESERVED或IN_FLIGHT许可；不得交接")
    if any(r.get("status") in {"IN_FLIGHT", "RESULT_UNKNOWN"} for r in state.get("panels", [])):
        errors.append("存在在途或结果未知格；先核对原请求")
    if state.get("cancelled") is True:
        errors.append("已取消话不得交接")
    return errors




def _carry_forward_errors(context, root, control, panel_id, receipt, permit, output_sha256):
    """Check explicit coordinator re-review; this never replaces visual/shot QA."""
    errors = []
    report = _read(_file(root, permit.get("carry_forward")))
    if report.get("policy") != "dispatch_reuse_v1" or report.get("status") != "PASS":
        errors.append("历史图复用报告未通过dispatch_reuse_v1")
    for key in ("reviewer", "evidence"):
        if not isinstance(report.get(key), str) or not report[key].strip():
            errors.append(f"历史图复用报告缺少实际复核{key}")
    if report.get("worker_id") != context.get("worker_id") or not _positive(report.get("epoch")) or report.get("epoch") != context.get("epoch"):
        errors.append("历史图复用报告的worker_id/epoch过期")
    if report.get("source_receipt") != receipt:
        errors.append("历史图复用报告未绑定原始dispatch_receipt")
    jobs = [job for job in control.get("jobs", []) if job.get("job_id") == context.get("job_id")]
    if len(jobs) != 1:
        return errors + ["历史图复用找不到当前唯一job"]
    job = jobs[0]
    if report.get("frozen_inputs") != job.get("frozen_inputs"):
        errors.append("历史图复用报告frozen_inputs不是当前冻结版本")
    state_name = Path(job.get("state_file", "00_输入审计/生产流程.json"))
    state_path = (root / state_name).resolve()
    if state_name.is_absolute() or not state_path.is_relative_to(root):
        return errors + ["历史图复用state_file越出话根目录"]
    state = _read(state_path)
    records = [record for record in state.get("panels", []) if record.get("panel_id") == panel_id]
    if len(records) != 1:
        return errors + ["历史图复用格记录不存在或重复"]
    record = records[0]
    paths = {}
    for key in ("package_manifest", "qa_report", "output"):
        if not isinstance(report.get(key), dict) or report[key] != record.get(key):
            errors.append(f"历史图复用报告{key}不是当前格记录版本")
        else:
            paths[key] = _file(root, report[key])
    if "package_manifest" in paths and _read(paths["package_manifest"]).get("dispatch_receipt") != receipt:
        errors.append("历史图复用包已更改原始dispatch_receipt")
    if "output" in paths and hashlib.sha256(paths["output"].read_bytes()).hexdigest() != output_sha256:
        errors.append("历史图复用报告实际图片与原调用输出不符")
    return errors


def receipt_errors(context, episode_root, book_id, episode_id, panel_id, receipt, output_sha256=None):
    """Bind one immutable packet receipt to its original dispatch and return bytes.

    No output hash means a new-call input check requiring RESERVED. A supplied
    hash means returned-image adoption and requires COMPLETED plus an exact
    output hash in the coordinator's permit record. Updating state context never
    upgrades an old packet receipt to the new epoch/owner. Old completed outputs
    require an explicit carry_forward report bound to current inputs and QA.
    """
    errors = context_errors(context, episode_root, book_id, episode_id,
                            panel_id if output_sha256 is None else None)
    try:
        if not isinstance(context, dict) or not isinstance(receipt, dict):
            return errors + ["缺少单格dispatch_receipt"]
        if receipt.get("job_id") != context.get("job_id") or not _positive(receipt.get("epoch")):
            errors.append("dispatch_receipt的job_id或epoch无效；不能跨任务复用")
        changed = [key for key in ("worker_id", "epoch") if receipt.get(key) != context.get(key)]
        if changed and output_sha256 is None:
            errors.append("新调用dispatch_receipt的worker_id/epoch须与当前上下文一致")
        permit_id = receipt.get("permit_id")
        if not isinstance(permit_id, str) or not permit_id:
            return errors + ["dispatch_receipt缺少permit_id"]
        control_path = Path(context.get("control_file", ""))
        if not control_path.is_absolute():
            return errors + ["dispatch_receipt控制文件必须为绝对路径"]
        control = _read(control_path)
        state_name = Path(next(j for j in control['jobs'] if j['job_id']==context['job_id']).get('state_file','00_输入审计/生产流程.json'))
        if state_name.is_absolute() or not (Path(episode_root).resolve()/state_name).resolve().is_relative_to(Path(episode_root).resolve()):
            raise ValueError('state_file越界')
        state = _read(Path(episode_root).resolve()/state_name)
        from slot_leases import effective_control, enabled as leased
        control = effective_control(control,state,context)
        permits = [p for p in control.get("permits", []) if p.get("permit_id") == permit_id]
        if len(permits) != 1:
            return errors + ["dispatch_receipt对应permit不存在或重复"]
        permit = permits[0]
        if leased(control) and (not receipt.get('lease_id') or receipt.get('lease_id')!=permit.get('lease_id')):
            errors.append('dispatch_receipt租约不符')
        for key in ("job_id", "worker_id", "epoch"):
            if permit.get(key) != receipt.get(key):
                errors.append(f"原调用permit的{key}与dispatch_receipt不符")
        if permit.get("panel_id") != panel_id:
            errors.append("dispatch_receipt对应permit属于其他格")
        state_name = Path(next(j for j in control["jobs"] if j["job_id"] == context["job_id"]).get("state_file", "00_输入审计/生产流程.json"))
        state = _read(Path(episode_root).resolve() / state_name)
        if state.get("execution_mode") in {"half_episode_async_v1", "episode_async_v1"}:
            for key in ("batch_id", "round_id", "attempt_id"):
                if receipt.get(key) != permit.get(key) or receipt.get(key) is None:
                    errors.append(f"dispatch_receipt的{key}与原调用permit不一致")

        expected = "RESERVED" if output_sha256 is None else "COMPLETED"
        if permit.get("status") != expected:
            errors.append(f"dispatch_receipt对应permit须为{expected}")
        if output_sha256 is not None:
            if not isinstance(output_sha256, str) or len(output_sha256) != 64 or any(c not in "0123456789abcdef" for c in output_sha256):
                errors.append("实际output_sha256缺失或无效")
            if permit.get("output_sha256") != output_sha256:
                errors.append("实际输出哈希与原调用permit记录不符或缺失")
            if changed:
                if not isinstance(permit.get("carry_forward"), dict):
                    errors.append("旧worker_id/epoch返回缺少carry_forward实际复核报告")
                else:
                    errors.extend(_carry_forward_errors(context, Path(episode_root).resolve(), control,
                                                        panel_id, receipt, permit, output_sha256))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        errors.append(f"dispatch_receipt读取失败: {exc}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--root", help="默认state父目录的父目录")
    parser.add_argument("--panel", help="指定源格号时检查新请求的RESERVED许可")
    parser.add_argument("--handoff-check", action="store_true", help="仅核对本话owner交接前的活动请求和旧执行者停止条件")
    parser.add_argument("--old-writer-stopped", action="store_true", help="总控已实际停止旧执行者并保存检查点")
    args = parser.parse_args()
    path = Path(args.state).resolve()
    root = Path(args.root).resolve() if args.root else path.parent.parent
    try:
        state = _read(path)
        if args.handoff_check:
            context = state.get("parallel_context", {})
            control = _read(Path(context["control_file"]))
            errors = handoff_readiness(control, state, context["job_id"], old_writer_stopped=args.old_writer_stopped)
        else:
            errors = context_errors(state.get("parallel_context"), root, state.get("book_id"), state.get("episode_id"), args.panel)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors = [str(exc)]
    print(json.dumps({"policy": POLICY, "status": "HOLD" if errors else "PASS", "errors": errors,
                      "handoff_check_only": args.handoff_check,
                      "read_only": True, "user_acceptance": "NOT_GRANTED_BY_SCRIPT"}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
