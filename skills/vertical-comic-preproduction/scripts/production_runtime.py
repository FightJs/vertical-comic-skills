#!/usr/bin/env python3
"""One entry for actual preflight, tool-input compilation, review queues and checkpoints.

No image calls, agent creation, user approval synthesis or shared-state writes.
Single-panel prompts remain the authoritative inputs; this compiles those real
inputs into jobs instead of recreating camera/identity/style contracts.
"""
from __future__ import annotations
import argparse
import json
import copy
import os
import tempfile
from platform_io import file_lock, atomic_json
from dispatch_publication import require_legacy
from authority_updates import state_write_lock, authority_scoped
import io
import uuid
from contextlib import redirect_stdout
from pathlib import Path
from codex_reference_contract import checked_file, digest, file_session, read_json, validate_panel

POLICY = "incremental_runtime_v1"
DEFAULTS = {
    "policy": POLICY, "audit_scope": "requested_episodes",
    "checkpoint_presentation": "grouped", "half_review_dispatch": "as_ready",
    "review_group_size": 4, "review_max_wait_seconds": 30,
    "watchdog": {
        "policy": "worker_watchdog_v1", "preparation_warning_seconds": 300,
        "preparation_escalation_seconds": 720, "review_warning_seconds": 300,
        "review_escalation_seconds": 720, "request_warning_seconds": 900,
        "request_escalation_seconds": 1800,
    },
}
EPISODE_DEFAULTS = {**DEFAULTS, "policy": "incremental_runtime_v2",
                    "episode_review_dispatch": "as_ready"}
EPISODE_DEFAULTS.pop("half_review_dispatch")


def settings(value):
    if not isinstance(value, dict):raise ValueError("runtime须为对象")
    for key, policy in (('snapshot_policy','batch_snapshot_v1'),('question_policy','grouped_review_v1'),('dispatch_policy','episode_slot_lease_v1')):
        if key in value and value[key]!=policy:raise ValueError('未知runtime策略:'+key)
        if key in value and value.get('policy')!='incremental_runtime_v2':raise ValueError('新运行策略只适用于整话新RV')
    spec=EPISODE_DEFAULTS if value.get('policy')=='incremental_runtime_v2' else DEFAULTS
    dispatch='episode_review_dispatch' if spec is EPISODE_DEFAULTS else 'half_review_dispatch'
    if any(value.get(k) != spec[k] for k in ("policy", "audit_scope", "checkpoint_presentation", dispatch)):
        raise ValueError("runtime须明确本批审计、合并展示及准确生产模式")
    if type(value.get("review_group_size")) is not int or not 3 <= value["review_group_size"] <= 5:
        raise ValueError("review_group_size须为3至5；依赖/校准格仍即时通知")
    if type(value.get("review_max_wait_seconds")) is not int or not 1 <= value["review_max_wait_seconds"] <= 30:
        raise ValueError("review_max_wait_seconds须为1至30")
    if "watchdog" in value:
        from worker_watchdog import settings as watchdog_settings
        watchdog_settings(value["watchdog"])
    return value


@authority_scoped
def compile_jobs(state, root, panel_ids=None, *, candidate=False, input_audit=False):
    """Full bulk gates once; export actual paths/prompt, never execute planned jobs."""
    from staged_workflow import preflight_many
    if input_audit and (candidate or state.get('parallel_context')):
        raise ValueError('接包输入审计不得使用candidate或线上调度上下文')
    import time
    started=time.monotonic()
    with file_session() as memo:
        report = preflight_many(state, root, panel_ids, candidate=candidate, input_audit=input_audit)
        records = {r["panel_id"]: r for r in state.get("panels", [])}
        from scoped_inputs import STATE_DISPATCH,state_leads
        shots=_shots(state,root,report['batch_id']) if report.get('batch_id') else []
        priority_leads=state_leads(shots) if state.get('state_dispatch_policy')==STATE_DISPATCH else set()
        actual_dependencies={d for row in shots for d in row.get('generation_dependencies',[])}
        jobs = []
        for pid in report.get("ready_panel_ids", []):
            record = records[pid]
            path = checked_file(Path(root), record["package_manifest"])
            packet = read_json(path)
            panel = packet["panels"][0]
            errors, submission = validate_panel(panel, path.parent)
            if errors or submission is None:
                raise ValueError(f"{pid}: " + ";".join(errors))
            arguments = submission["arguments"]
            prepared = {}
            from input_semantics import PREPARED_POLICY, actual_input, fingerprint
            if state.get('input_semantics_policy') == PREPARED_POLICY:
                shot = next(p for p in shots if p['panel_id'] == pid)
                prepared = {'prepared_input_digest': fingerprint(actual_input(state, root, shot, packet, path.parent))}
            jobs.append({**prepared,
                "kind": "repair" if panel.get("operation") == "repair" else "panel",
                "book_id": state['book_id'], "episode_id": state['episode_id'],
                "job_id": state.get("parallel_context", {}).get("job_id", state["episode_id"]),
                "panel_id": pid, "source_panel_id": record.get("source_panel_id"),
                "batch_id": report["batch_id"], "round_id": record["round_id"],
                "attempt_id": record["attempt_id"],
                "ready_at": record.get('ready_at'),
                "package_manifest": record["package_manifest"],
                "arguments": arguments,
                "candidate_only": candidate,
                "input_audit_only": input_audit, "dispatch_authorized": False if input_audit or candidate else None,
                "review_priority": bool(panel.get("calibration_anchor") or panel.get("requires_state_review")
                    or pid in priority_leads or pid in actual_dependencies),
                "status": "INPUT_AUDITED_NOT_DISPATCHABLE" if input_audit else "CANDIDATE_NOT_DISPATCHABLE" if candidate else "NOT_RUN",
            })
        return {"policy": state.get('runtime',{}).get('policy',POLICY), "book_id": state.get("book_id"), "episode_id": state.get("episode_id"),
                "candidate_only": candidate, "input_audit_only": input_audit,
                "dispatch_authorized": False if input_audit or candidate else None,
                "audit_policy": 'receiver_input_audit_v1' if input_audit else None,
                "jobs": jobs, "preflight": report,
                "file_reuse_statistics": {k: memo[k] for k in ("hash_reads", "hash_hits","validation_runs","validation_hits")},
                "audit_reuse_statistics": copy.deepcopy(memo['audit_statistics']),
                "preflight_elapsed_seconds":round(time.monotonic()-started,4),
                "user_approval": "NOT_GRANTED", "image_calls": 0}


def preparation_report(state, root):
    from panel_readiness import enabled, report
    from execution_contract import state_errors
    errors=state_errors(state,root)
    if errors or not enabled(state):raise ValueError(';'.join(errors) or '本RV未声明逐格准备策略；不自动迁移')
    value=report(state,root)
    value['dispatch_authorized']=False
    return value


def receiver_audit(state, root, h001_ids, all_ids):
    """Run three original scopes in one read transaction; never derive H001 by slicing."""
    import time
    from audit_progress import mark
    if state.get('execution_mode')!='episode_async_v1' or state.get('parallel_context'):
        raise ValueError('合并接包审计只适用于未领线上许可的整话运行')
    started,cpu_started=time.monotonic(),time.process_time()
    with file_session() as memo:
        source=read_json(checked_file(Path(root),state['source_snapshot']))
        order=source['panel_ids']
        if all_ids!=order or not h001_ids or h001_ids!=order[:len(h001_ids)]:
            raise ValueError('接包审计须保留全话源序及准确H001前缀范围')
        mark('H001',completed=0,total=len(h001_ids),force=True)
        first=compile_jobs(state,root,h001_ids,input_audit=True)
        mark('preparation',completed=0,total=len(order),force=True)
        prepared=preparation_report(state,root)
        mark('all_inputs',completed=0,total=len(order),force=True)
        full=compile_jobs(state,root,all_ids,input_audit=True)
        value={'policy':'receiver_audit_bundle_v1','book_id':state.get('book_id'),
               'episode_id':state.get('episode_id'),'h001_panel_ids':h001_ids,'panel_ids':all_ids,
               'h001':first,'preparation':prepared,'all_inputs':full,
               'audit_reuse_statistics':copy.deepcopy(memo['audit_statistics']),
               'dispatch_authorized':False,'image_calls':0,'user_approval':'NOT_GRANTED'}
        from input_semantics import enabled as semantics_enabled, coverage as semantic_coverage
        if semantics_enabled(state):
            value['final_input_semantics'] = semantic_coverage(state, root)
        mark('snapshot_verification',completed=len(order),total=len(order),force=True)
    value.update(elapsed_seconds=round(time.monotonic()-started,4),cpu_seconds=round(time.process_time()-cpu_started,4))
    return value


def _shots(state, root, batch_id):
    from scoped_inputs import resolve_context
    return resolve_context(state, root, batch_id)['shots']


def checkpoint(state, root):
    """One episode at a time; other episodes cannot delay its C checkpoint."""
    from staged_workflow import evaluate
    report = evaluate(state, root)
    action = report.get("next_action")
    phase = {
        "WAIT_HALF_VISUAL_APPROVAL": "A",
        "WAIT_EPISODE_VISUAL_APPROVAL": "A",
        "WAIT_HALF_SHOT_APPROVAL": "B_AND_PACKAGE",
        "WAIT_EPISODE_SHOT_APPROVAL": "B_AND_PACKAGE",
        "WAIT_GENERATION_PACKAGE_APPROVAL": "B_AND_PACKAGE",
        "WAIT_FIRST_HALF_APPROVAL": "C",
        "WAIT_NEW_STATE_APPROVAL": "STATE_REVIEW",
        "WAIT_FINAL_APPROVAL": "D",
    }.get(action)
    lifecycle = "WAIT_HUMAN" if phase else "LOCAL_WORK"
    pending_state_reviews=report.get('pending_state_review_panel_ids',[])
    if action in {"WAIT_CROSS_EPISODE_REVIEW", "WAIT_CROSS_EPISODE", "WAIT_OTHER_EPISODES"}:
        lifecycle = "LOCAL_DONE_HANDOFF_TO_COORDINATOR"
    return {"policy": POLICY, "episode_id": state["episode_id"], "phase": phase,
            "ready_for_user_review": phase is not None or bool(pending_state_reviews),
            "pending_state_review_panel_ids": pending_state_reviews,
            "review_notifications": [{"phase":"STATE_REVIEW","panel_id":pid} for pid in pending_state_reviews],
            "dispatch_review": "IMMEDIATE_THIS_EPISODE" if phase or pending_state_reviews else "NOT_READY",
            "wait_for_other_episodes": False, "worker_lifecycle": lifecycle, "gate": report,
            "user_approval": "NOT_GRANTED"}


def package_signature(packet, package_root):
    """Input-only signature: attaching real execution evidence does not change it."""
    panel = packet["panels"][0]
    _, submission = validate_panel(panel, Path(package_root), enforce_input_budget=True)
    if submission is None:
        raise ValueError("缺少可核对的实际输入")
    if packet.get('portability_policy') not in (None,'approved_relative_inputs_v1'):raise ValueError('未知参考路径批准合同')
    portable=packet.get('portability_policy')=='approved_relative_inputs_v1'
    return {**({'portability_policy':'approved_relative_inputs_v1','reference_path_basis':'package_root'} if portable else {}),**({"visual_evidence_policy":panel["visual_evidence_policy"],
                "visual_evidence":panel.get("visual_evidence"),
                "visual_evidence_context":panel.get("visual_evidence_context"),
                "repair_source":panel.get("repair_source"), "repair_method":panel.get("repair_method"),
                 "production_policy":panel.get("production_policy")} if panel.get("visual_evidence_policy") else {}),
            **({'background_policy': panel['background_policy'], 'framing': copy.deepcopy(panel.get('framing'))}
               if panel.get('background_policy') else {}),
            **({'input_quality_policy': panel['input_quality_policy']} if panel.get('input_quality_policy') else {}),
            "panel_id": panel["panel_id"], "prompt": submission["arguments"]["prompt"],
            "transparent_background": submission["arguments"]["transparent_background"],
            "output_spec": panel.get("output_spec"),
            "references": [{"path": Path(os.path.relpath(Path(p).resolve(),Path(package_root).resolve())).as_posix() if portable else p, "sha256": digest(Path(p))}
                           for p in submission["arguments"]["referenced_image_paths"]]}


def package_review_errors(state, root, batch, record):
    """New runtime checks the exact frozen package proof before first-round calls."""
    if state.get("runtime", {}).get("policy") not in {POLICY, "incremental_runtime_v2"} or record.get("round_id") != 1:
        return []
    from scoped_inputs import approval_for, half_view, full_preparation
    from panel_readiness import enabled as scoped_preparation
    try:
        from input_semantics import enabled as semantics_enabled, panel_errors as final_input_errors
        if semantics_enabled(state):
            shot = next(p for p in _shots(state, root, batch["batch_id"]) if p["panel_id"] == record["panel_id"])
            path = checked_file(Path(root), record["package_manifest"])
            issues = final_input_errors(state, root, shot, read_json(path), path.parent)
            if issues: return issues
        view = half_view(state, batch["batch_id"])
        whole=full_preparation(state)
        source=read_json(checked_file(Path(root),state['source_snapshot'])) if whole else None
        refs = state.get("generation_packages", {}).get('EPISODE' if whole else batch["batch_id"], [])
        for ref in refs:
            bundle = read_json(checked_file(Path(root), ref))
            if bundle.get("policy") != "generation_review_package_v1" or bundle.get("book_id") != state["book_id"] or bundle.get("episode_id") != state["episode_id"]:
                continue
            if whole:
                if bundle.get('scope')!='episode' or bundle.get('panel_ids')!=source['panel_ids']:continue
                if scoped_preparation(state) and (bundle.get('readiness_policy')!=state['readiness_policy'] or record['panel_id'] not in bundle.get('approval_panel_ids',[])):continue
            elif bundle.get('batch_id') != batch['batch_id']:continue
            row = next((r for r in bundle.get("inputs", []) if r["panel_id"] == record["panel_id"]), None)
            path = checked_file(Path(root), record["package_manifest"])
            if row != package_signature(read_json(path), path.parent) and not dependency_plan_matches(
                    bundle, state, root, batch, record, read_json(path), path.parent):
                continue
            errors = approval_for(view, root, "generation_package",
                [ref, view["visual_basis"], view["shot_manifest"]], [record['panel_id']] if scoped_preparation(state) else source['panel_ids'] if whole else [record["panel_id"]])
            if not errors:
                return []
        return ["缺少覆盖本格实际prompt/参考/版本的生图包用户批准"]
    except (OSError, ValueError, TypeError, KeyError, StopIteration) as exc:
        return [f"生图包批准核对失败:{exc}"]


def dependency_plan_matches(bundle, state, root, batch, record, packet, package_root):
    """Only exact preapproved substitutions of verified prior-image paths."""
    ref = bundle.get("dependency_completion_plan")
    if not ref:
        return False
    plan = read_json(checked_file(Path(root), ref))
    from scoped_inputs import full_preparation
    whole=full_preparation(state)
    if any(plan.get(k) != v for k, v in {
        "policy": "dependency_completion_plan_v1", "book_id": state["book_id"],
        "episode_id": state["episode_id"], **({'scope':'episode','visual_basis':state['visual_basis'],'shot_manifest':state['shot_manifest']} if whole else {'batch_id':batch['batch_id']})}.items()):
        return False
    row = next((r for r in plan.get("inputs", []) if r.get("panel_id") == record["panel_id"]), None)
    if not row:
        return False
    shot = next(p for p in _shots(state, root, batch["batch_id"]) if p["panel_id"] == record["panel_id"])
    deps = shot.get("generation_dependencies", [])
    if set(row.get("dependency_panel_ids", [])) != set(deps) or not deps:
        return False
    source = read_json(checked_file(Path(root), state["source_snapshot"]))
    order = source["panel_ids"]
    if record["panel_id"] not in order or not set(deps)<=set(order[:order.index(record["panel_id"])]):
        return False
    if row.get("output_spec") != packet["panels"][0].get("output_spec"):
        return False
    errors, actual = validate_panel(packet["panels"][0], Path(package_root))
    if errors or actual is None:
        return False
    expected = copy.deepcopy(row["arguments"])
    refs = row.get("reference_files", [])
    if len(refs) != len(expected.get("referenced_image_paths", [])):
        return False
    observed = set()
    records = {r["panel_id"]: r for r in state["panels"]}
    for i, ref in enumerate(refs):
        token = expected["referenced_image_paths"][i]
        if token.startswith("@DEPENDENCY:"):
            dep = token.split(":", 1)[1]
            if dep not in deps or records[dep].get("status") not in {"VISUAL_PASS", "USER_ACCEPTED"}:
                return False
            source = checked_file(Path(root), records[dep]["output"])
            path = Path(actual["arguments"]["referenced_image_paths"][i])
            if digest(source) != digest(path):
                return False
            expected["referenced_image_paths"][i] = str(path)
            observed.add(dep)
        else:
            if ref.get('path') != token: return False
            if row.get('reference_path_basis') == 'run_root':
                try: path = checked_file(Path(root), ref)
                except (OSError, ValueError): return False
                expected['referenced_image_paths'][i] = str(path)
            elif row.get('reference_path_basis') is not None or not Path(token).is_absolute() or digest(Path(token)) != ref.get('sha256'):
                return False
    return observed == set(deps) and expected == actual["arguments"]


def review_bundle(state, root, compiled, dependency_plan=None):
    """Freeze only real ready inputs; dependency additions require exact proof."""
    bid = compiled["preflight"].get("batch_id")
    if not bid or not compiled["jobs"]:
        raise ValueError("没有完整技术预检通过的当前输入，不能将空候选包提交批准")
    records = {r["panel_id"]: r for r in state["panels"]}
    inputs = []
    for job in compiled["jobs"]:
        path = checked_file(Path(root), records[job["panel_id"]]["package_manifest"])
        inputs.append(package_signature(read_json(path), path.parent))
    value = {"policy": "generation_review_package_v1", "book_id": state["book_id"],
            "episode_id": state["episode_id"], "batch_id": bid,
            "panel_ids": [r["panel_id"] for r in inputs], "inputs": inputs,
            "status": "CANDIDATE", "user_approval": "NOT_GRANTED",
            "pending_or_blocked_panel_ids": compiled["preflight"].get("blocked_panel_ids", [])}
    if dependency_plan:
        plan = read_json(checked_file(Path(root), dependency_plan))
        if any(plan.get(k) != v for k, v in {"policy":"dependency_completion_plan_v1",
                "book_id":state["book_id"],"episode_id":state["episode_id"],"batch_id":bid}.items()):
            raise ValueError("依赖补齐方案归属或版本不一致")
        deferred = [r["panel_id"] for r in plan.get("inputs", [])]
        valid = {p["panel_id"] for p in _shots(state,root,bid)}
        if not deferred or len(set(deferred)) != len(deferred) or not set(deferred) <= valid:
            raise ValueError("依赖补齐方案缺格、重复或超出本半话")
        value["dependency_completion_plan"] = dependency_plan
        value["panel_ids"] = list(dict.fromkeys(value["panel_ids"] + deferred))
    return value


def episode_bundle(state, root, dependency_plan=None):
    from panel_readiness import review_context
    with file_session(), review_context(state, root, True):
        return _episode_bundle(state, root, dependency_plan)


def _episode_bundle(state, root, dependency_plan=None):
    """Freeze one complete episode candidate before either production half starts."""
    from scoped_inputs import full_preparation, validate_shots, approval_for
    from execution_contract import state_errors, semantic_errors
    from rule_memory import binding_errors as memory_binding_errors
    from frame_ratio_plan import panel_errors as ratio_panel_errors
    from staged_workflow import basis_errors
    from batch_workflow import SHOT_FIELDS
    from style_contract import validate_style, output_spec_errors
    from panel_readiness import enabled as scoped_preparation,report as readiness_report,review_context
    import time
    started=time.monotonic()
    if not full_preparation(state):
        raise ValueError('旧半话准备须使用原半话bundle入口')
    errors=state_errors(state,root)
    if errors:raise ValueError(';'.join(errors))
    source=read_json(checked_file(Path(root),state['source_snapshot']));order=source['panel_ids']
    if [r.get('panel_id') for r in state.get('panels',[])]!=order:
        raise ValueError('全话进度须准确覆盖源格序')
    basis=read_json(checked_file(Path(root),state['visual_basis']))
    if basis.get('book_id')!=state['book_id'] or basis.get('episode_id')!=state['episode_id'] or not basis.get('reference_files'):
        raise ValueError('全话视觉基准归属/参考缺失')
    for ref in basis['reference_files']:checked_file(Path(root),ref)
    approved_hashes={r['sha256'] for r in basis['reference_files']}
    style_hashes=set(basis.get('style',{}).get('reference_sha256',[]))
    shots=read_json(checked_file(Path(root),state['shot_manifest']))
    readiness=readiness_report(state,root) if scoped_preparation(state) else None
    if readiness and readiness['global_errors']:raise ValueError(';'.join(readiness['global_errors']))
    blocked=set(readiness['blocked_panel_ids']) if readiness else set()
    reviewable=set(readiness['ready_for_review_ids']) if readiness else set(order)
    selected=[p for p in order if p not in blocked or p in reviewable and next(s for s in shots['panels'] if s['panel_id']==p).get('generation_dependencies')]
    errors=memory_binding_errors(state,shots=shots)
    if errors:raise ValueError(';'.join(errors))
    validate_shots(state,source,{'batch_id':'EPISODE','panel_ids':order},shots,blocked)
    errors=ratio_panel_errors(state,root,shots['panels'])
    errors.extend(semantic_errors(state,root,{'batch_id':'EPISODE','panel_ids':order},blocked))
    errors.extend(approval_for(state,root,'visual_basis',[state['source_script'],state['source_snapshot'],state['visual_basis']],selected,state.get('gates',{}).get('visual_basis')))
    if errors:raise ValueError(';'.join(errors))
    by_shot={p['panel_id']:p for p in shots['panels']}
    by_record={r['panel_id']:r for r in state['panels']}
    dependency_ids={pid for pid in selected if by_shot[pid].get('generation_dependencies')}
    deferred=set();plan_ref=None;technical_errors={}
    def validate_dependency(row):
        pid=row['panel_id'];deps=by_shot[pid]['generation_dependencies'];args=row.get('arguments',{})
        refs=row.get('reference_files',[]);paths=args.get('referenced_image_paths',[])
        if row.get('dependency_panel_ids')!=deps or set(args)!={'prompt','transparent_background','referenced_image_paths'} or not isinstance(args.get('prompt'),str) or not args['prompt'].strip() or type(args.get('transparent_background')) is not bool or not isinstance(paths,list) or not 1<=len(paths)<=5 or len(refs)!=len(paths) or not isinstance(row.get('output_spec'),dict):
            raise ValueError(f'{pid}:全话依赖输入缺失、顺序错误或超过五图参考预算')
        found=[];fixed_hashes=[]
        for token,ref in zip(paths,refs):
            if not isinstance(token,str) or not isinstance(ref,dict) or ref.get('path')!=token:raise ValueError(f'{pid}:参考路径记录与实际参数不一致')
            if token.startswith('@DEPENDENCY:'):found.append(token.split(':',1)[1])
            else:
                if row.get('reference_path_basis') == 'run_root':
                    fixed_path = checked_file(Path(root), ref)
                elif row.get('reference_path_basis') is None and Path(token).is_absolute():
                    fixed_path = Path(token)
                else: raise ValueError(f'{pid}:固定参考缺明确路径基准')
                if digest(fixed_path)!=ref.get('sha256') or ref['sha256'] not in approved_hashes:
                    raise ValueError(f'{pid}:固定参考路径/哈希不是全话已批准依据')
                fixed_hashes.append(ref['sha256'])
        if sorted(found)!=sorted(deps) or len(found)!=len(deps):raise ValueError(f'{pid}:真实前格替换槽必须逐一对应依赖')
        if not style_hashes or not style_hashes<=set(fixed_hashes):raise ValueError(f'{pid}:依赖方案未实际携带批准画风样例')
    if dependency_ids:
        try:
            if dependency_plan is None:raise ValueError('实图依赖格须提供准确补齐方案')
            plan=read_json(checked_file(Path(root),dependency_plan))
            expected={'policy':'dependency_completion_plan_v1','scope':'episode','book_id':state['book_id'],
                      'episode_id':state['episode_id'],'visual_basis':state['visual_basis'],'shot_manifest':state['shot_manifest']}
            if any(plan.get(k)!=v for k,v in expected.items()):raise ValueError('全话实图依赖方案归属/版本不一致')
            rows=plan.get('inputs',[]);plan_ids=[r.get('panel_id') for r in rows] if isinstance(rows,list) else []
            relevant=[pid for pid in plan_ids if pid in dependency_ids]
            valid_partial=isinstance(rows,list) and len(set(plan_ids))==len(plan_ids) and all(pid in by_shot and by_shot[pid].get('generation_dependencies') for pid in plan_ids) and relevant==[p for p in order if p in set(relevant)]
            if not (valid_partial if readiness else isinstance(rows,list) and plan_ids==[p for p in order if p in dependency_ids]):
                raise ValueError('全话实图依赖方案缺格/乱序或混入无依赖格')
            row_by_id={r['panel_id']:r for r in rows}
            for pid in order:
                if pid not in dependency_ids:continue
                try:
                    if pid not in row_by_id:raise ValueError(f'{pid}:尚未准备实图依赖补齐方案')
                    validate_dependency(row_by_id[pid])
                    from input_semantics import panel_errors as final_input_errors
                    semantic_issues = final_input_errors(state, root, by_shot[pid], plan_row=row_by_id[pid])
                    if semantic_issues: raise ValueError(';'.join(semantic_issues))
                    deferred.add(pid)
                except (OSError,ValueError,TypeError,KeyError,AttributeError) as exc:
                    if not readiness:raise
                    technical_errors[pid]=[str(exc)]
            if deferred:plan_ref=dependency_plan
        except (OSError,ValueError,TypeError,KeyError,AttributeError) as exc:
            if not readiness:raise
            for pid in dependency_ids:technical_errors[pid]=[str(exc)]
    elif dependency_plan is not None and not readiness:
        raise ValueError('本话没有实图依赖，不登记多余补齐方案')
    inputs=[]
    for pid in selected:
        if pid in dependency_ids:continue
        try:
            record=by_record[pid];path=checked_file(Path(root),record.get('package_manifest'));packet=read_json(path)
            packet_panels=packet.get('panels',[]);panel=packet_panels[0] if len(packet_panels)==1 else None
            if packet.get('preparation_policy')!=state['preparation_policy'] or packet.get('execution_mode')!=state['execution_mode'] or packet.get('optimization_policy')!=state['optimization_policy'] or packet.get('book_id')!=state['book_id'] or packet.get('episode_id')!=state['episode_id'] or not isinstance(panel,dict) or panel.get('panel_id')!=pid:
                raise ValueError(f'{pid}:全话候选执行包归属/范围不一致')
            if any(panel.get(k)!=by_shot[pid].get(k) for k in SHOT_FIELDS):raise ValueError(f'{pid}:候选执行输入偏离全话镜头')
            errors=basis_errors(panel,basis);errors.extend(ratio_panel_errors(state,root,[panel],prompt=True))
            errors.extend(validate_style(panel,path.parent));errors.extend(output_spec_errors(panel))
            if readiness:
                from batch_workflow import input_errors
                with review_context(state,root,True):errors.extend(input_errors(state,root,record,by_shot[pid],basis,by_record,candidate=True,preparation_only=True))
            if errors:raise ValueError(';'.join(errors))
            inputs.append(package_signature(packet,path.parent))
        except (OSError,ValueError,TypeError,KeyError,AttributeError,IndexError) as exc:
            if not readiness:raise
            technical_errors[pid]=[str(exc)]
    value={'policy':'generation_review_package_v1','scope':'episode','book_id':state['book_id'],
           'episode_id':state['episode_id'],'visual_basis':state['visual_basis'],'shot_manifest':state['shot_manifest'],
           'panel_ids':order,'inputs':inputs,'status':'CANDIDATE','user_approval':'NOT_GRANTED'}
    if plan_ref:value['dependency_completion_plan']=plan_ref
    from input_semantics import enabled as semantics_enabled, coverage as semantic_coverage
    if semantics_enabled(state):
        value['input_semantics_policy'] = state['input_semantics_policy']
        value['final_input_semantics'] = semantic_coverage(state, root, dependency_plan)
        value['semantic_audit'] = state['semantic_audit']
    if readiness:
        approved_ids={r['panel_id'] for r in inputs}|deferred
        value.update(readiness_policy=state['readiness_policy'],coverage='complete' if len(approved_ids)==len(order) else 'partial',
                     approval_panel_ids=[p for p in order if p in approved_ids],pending_panel_ids=[p for p in order if p not in approved_ids],
                     design_review_panel_ids=readiness['ready_for_review_ids'],blockers=readiness['blockers'],candidate_technical_errors=technical_errors)
    value['preparation_check_elapsed_seconds']=round(time.monotonic()-started,4)
    return value


def commit_updates(state_path, expected_sha256, updates, *, resolution_ref=None):
    """Single-writer CAS: real receipts/QA only; never changes frozen inputs/gates."""
    from staged_workflow import qa_errors
    from batch_round import attempt_errors
    from codex_reference_contract import execution_errors
    state_path = Path(state_path).resolve(); root = state_path.parent.parent
    allowed = {"status", "output", "qa_report", "call_evidence", "failure_diagnosis",
               "package_manifest", "ready_at", "submitted_at", "returned_at", "save_started_at", "saved_at", "qa_completed_at"}
    transitions = {
        "PENDING": {"IN_FLIGHT"}, "REPAIR_AUTHORIZED": {"IN_FLIGHT"},
        "IN_FLIGHT": {"GENERATED", "CALL_FAILED", "RESULT_UNKNOWN", "CANCELLED"},
        "GENERATED": {"VISUAL_PASS", "VISUAL_FAIL"},
    }
    if not isinstance(updates,list) or not updates or len({u.get("panel_id") for u in updates}) != len(updates):
        raise ValueError("updates须明确不重复格号")
    with state_write_lock(state_path):
        state = read_json(state_path); require_legacy(state)
        operation = None
        if 'dispatch_consistency' in state:
            from dispatch_publication import _bytes, _sha
            operation = _sha(_bytes([updates, resolution_ref]))
            old = state.get('runtime_operations', {}).get(operation)
            if old is not None:
                return {'status': 'UPDATES_ALREADY_SAVED', 'panel_ids': old['panel_ids'],
                        'state_sha256': digest(state_path), 'watchdog_progress': [], 'user_approval': 'NOT_GRANTED'}
        if digest(state_path) != expected_sha256:
            raise ValueError("STATE_CHANGED: 读取最新状态后合并，不覆盖其他返回")
        new = copy.deepcopy(state)
        records = {r["panel_id"]:r for r in new["panels"]}
        if resolution_ref is not None:
            from slot_leases import resolution_errors
            if len(updates)!=1:raise ValueError('每次只解析一个原未知请求')
            resolution=read_json(checked_file(root,resolution_ref))
            original=records[updates[0]['panel_id']]
            errors=resolution_errors(state,root,original,updates[0],resolution)
            if errors:raise ValueError(';'.join(errors))
            transitions['RESULT_UNKNOWN']={'GENERATED','CALL_FAILED'}
            new.setdefault('unknown_resolutions',{})[original['attempt_id']]=resolution_ref
        with file_session():
            for update in updates:
                pid = update["panel_id"]; row = records[pid]
                if update.get("attempt_id") != row.get("attempt_id") or update.get("round_id") != row.get("round_id"):
                    raise ValueError("更新尝试/轮次不一致；旧返回不得覆盖新尝试")
                fields = {k:v for k,v in update.items() if k not in {"panel_id","attempt_id","round_id"}}
                if not set(fields) <= allowed or fields.get("status") not in transitions.get(row.get("status"),set()):
                    raise ValueError("更新超出返回/QA范围或状态转换无效")
                row.update(fields)
                if row["status"] == "GENERATED":
                    path = checked_file(root,row["package_manifest"]); packet=read_json(path); panel=packet["panels"][0]
                    original=next(r for r in state["panels"] if r["panel_id"]==pid)
                    before=checked_file(root,original["package_manifest"])
                    before_packet=read_json(before)
                    if state.get('runtime',{}).get('dispatch_policy')=='episode_slot_lease_v1' and any(
                            packet.get(k)!=before_packet.get(k) for k in ('dispatch_receipt','round_context','dispatch_source_package')):
                        raise ValueError('返回登记不得修改原租约回执或轮次')
                    if package_signature(read_json(before),before.parent)!=package_signature(packet,path.parent):
                        raise ValueError("返回登记不能改变已提交的实际prompt或参考输入")
                    errors, submission = validate_panel(panel,path.parent)
                    if errors or submission is None:raise ValueError(";".join(errors))
                    errors=execution_errors(panel["generation_execution"],submission,path.parent,pid)
                    response=read_json(checked_file(path.parent,panel["generation_execution"]["response_evidence"]))
                    checked_file(root,row["output"])
                    if row["output"]["sha256"] not in {r["sha256"] for r in response["outputs"]}:errors.append("输出不属于本次真实返回")
                    if errors:raise ValueError(";".join(errors))
                elif row["status"] == "VISUAL_PASS":
                    errors=qa_errors(root,row)
                    if state.get("visual_evidence_policy"):
                        from visual_evidence import comparison_errors
                        packet=read_json(checked_file(root,row["package_manifest"]))
                        qa=read_json(checked_file(root,row["qa_report"]))
                        item=next((q for q in qa.get("panels",[]) if q.get("panel_id")==pid),{})
                        errors.extend(comparison_errors(packet["panels"][0],item,records,root))
                    if errors:raise ValueError(";".join(errors))
                elif row["status"] in {"VISUAL_FAIL","CALL_FAILED","RESULT_UNKNOWN","CANCELLED"}:
                    errors=attempt_errors(new,root,row)
                    if errors:raise ValueError(";".join(errors))
                elif row["status"] == "IN_FLIGHT":
                    from staged_workflow import preflight_many
                    report=preflight_many(state,root,[pid])
                    if pid not in report.get("ready_panel_ids",[]):raise ValueError("提交前完整门禁未通过")
                if new.get('runtime',{}).get('dispatch_policy')=='episode_slot_lease_v1':
                    from slot_leases import advance
                    advance(new,pid,row['status'],row.get('output'))
        # Only small state snapshots are retained; no image/reference copies.
        history=state_path.parent/"runtime_history";history.mkdir(exist_ok=True)
        previous=history/(expected_sha256+".json")
        if not previous.exists():previous.write_bytes(state_path.read_bytes())
        if digest(state_path) != expected_sha256:raise ValueError("STATE_CHANGED")
        if operation is not None:
            new.setdefault('runtime_operations', {})[operation] = {'panel_ids': [u['panel_id'] for u in updates]}
        atomic_json(state_path, new)
        monitored=[]
        if new.get("runtime",{}).get("watchdog",{}).get("policy") == "worker_watchdog_v1":
            from worker_watchdog import record_progress
            ledger=root/"00_输入审计"/"worker_watchdog.json"
            for update in updates:
                row=records[update["panel_id"]]; status=row["status"]
                stage="repair" if row.get("round_id")==2 else ("image_review" if status in {"VISUAL_PASS","VISUAL_FAIL"} else "generation")
                kind={"IN_FLIGHT":"request_submitted","GENERATED":"image_saved",
                      "VISUAL_PASS":"qa_saved","VISUAL_FAIL":"qa_saved",
                      "CALL_FAILED":"request_returned","RESULT_UNKNOWN":"request_returned",
                      "CANCELLED":"request_returned"}.get(status)
                if kind is None: continue
                ref=(row.get("output") if kind=="image_saved" else row.get("qa_report") if kind=="qa_saved" else None)
                ref=ref or {"path":state_path.relative_to(root).as_posix(),"sha256":digest(state_path)}
                event={"stage":stage if kind!="qa_saved" else "image_review", "kind":kind,
                       "blocker_id":f"{row.get('batch_id','episode')}:{row['panel_id']}:{row.get('attempt_id','')}",
                       "evidence":ref}
                try:monitored.append(record_progress(ledger,root,event)["status"])
                except (OSError,ValueError,TypeError) as exc:monitored.append(f"PROGRESS_RECORD_ERROR:{exc}")
        return {"status":"UPDATES_SAVED","panel_ids":[u["panel_id"] for u in updates],
                "state_sha256":digest(state_path),"watchdog_progress":monitored,
                "user_approval":"NOT_GRANTED"}


def authorize_episode_repair(state_path, expected_sha256, authorization_ref):
    """Atomically open one second-round attempt without waiting for every panel."""
    from batch_round import snapshot, attempt_errors
    from episode_repair import systemic_errors
    state_path=Path(state_path).resolve();root=state_path.parent.parent
    with state_write_lock(state_path):
        if digest(state_path)!=expected_sha256:raise ValueError('STATE_CHANGED')
        state=read_json(state_path)
        require_legacy(state)
        if state.get('execution_mode')!='episode_async_v1':raise ValueError('滚动返修只用于整话模式')
        ref={'path':authorization_ref,'sha256':digest(root/authorization_ref)}
        auth=read_json(checked_file(root,ref));pid=auth.get('panel_id')
        row=next((r for r in state['panels'] if r['panel_id']==pid),None)
        if row is None or row.get('status')!='VISUAL_FAIL' or row.get('round_id')!=1 or row.get('attempt_history'):
            raise ValueError('仅真实首轮失败格可开启唯一自动返修')
        errors=attempt_errors(state,root,row)+systemic_errors(state,state['panels'],root)
        if auth.get('policy')!='episode_repair_v1' or auth.get('failed_attempt')!=snapshot(row) or auth.get('route')!='targeted_image_repair' or not auth.get('reviewer') or not auth.get('evidence'):
            errors.append('授权未绑定实际失败与执行层诊断')
        if state.get('input_quality_policy') == 'execution_quality_v1' or state.get('production_policy') == 'first_batch_production_v1':
            from input_quality import repair_decision_errors
            errors.extend(repair_decision_errors(auth.get('repair_decision'), row, require_image_call=True, state=state, root=root, new_package=auth.get('new_package_manifest')))
        constraints=auth.get('repair_constraints')
        if not isinstance(constraints,list) or not constraints or any(not isinstance(c,str) or not c.strip() for c in constraints):errors.append('修正约束缺失')
        packet_ref=auth.get('new_package_manifest');subset_ref=auth.get('new_shot_subset');attempt=auth.get('new_attempt_id')
        if not isinstance(packet_ref,dict) or not isinstance(subset_ref,dict) or not isinstance(attempt,str) or not attempt or attempt==row['attempt_id']:
            errors.append('新尝试/包/镜头选集无效')
        if errors:raise ValueError(';'.join(errors))
        packet=read_json(checked_file(root,packet_ref));checked_file(root,subset_ref)
        panel=packet.get('panels',[{}])[0]
        if packet.get('execution_mode')!='episode_async_v1' or packet.get('round_context')!={'batch_id':'EPISODE','round_id':2,'attempt_id':attempt} or panel.get('panel_id')!=pid or panel.get('operation')!='repair' or any(c not in panel.get('prompt','') for c in constraints):
            raise ValueError('第二轮执行包未准确使用返修诊断、格号和新attempt')
        from repair_input_guard import repair_errors as repair_input_errors
        from visual_evidence import repair_binding_errors
        repair_input_issues=repair_input_errors(panel) + repair_binding_errors(panel,row)
        if repair_input_issues:raise ValueError(';'.join(repair_input_issues))
        new=copy.deepcopy(state);target=next(r for r in new['panels'] if r['panel_id']==pid)
        old=copy.deepcopy(target)
        for key in ('output','qa_report','call_evidence','failure_diagnosis','submitted_at','returned_at','saved_at','qa_completed_at'):
            target.pop(key,None)
        target.update(status='REPAIR_AUTHORIZED',round_id=2,attempt_id=attempt,
                      package_manifest=packet_ref,shot_subset=subset_ref,attempt_history=[old])
        new.setdefault('repair_authorizations',{})[pid]=ref
        from episode_repair import repair_errors
        errors=repair_errors(new,root,target)
        if errors:raise ValueError(';'.join(errors))
        history=state_path.parent/'runtime_history';history.mkdir(exist_ok=True)
        previous=history/(expected_sha256+'.json')
        if not previous.exists():previous.write_bytes(state_path.read_bytes())
        atomic_json(state_path, new)
        return {'status':'REPAIR_AUTHORIZED','panel_id':pid,'attempt_id':attempt,'state_sha256':digest(state_path)}


def record_episode_diagnosis(state_path, expected_sha256, diagnosis_ref):
    """Atomically bind an actual common-cause review before >5 rolling repairs."""
    from episode_repair import failure_ids
    from batch_round import attempt_errors
    state_path=Path(state_path).resolve();root=state_path.parent.parent
    with state_write_lock(state_path):
        if digest(state_path)!=expected_sha256:raise ValueError('STATE_CHANGED')
        state=read_json(state_path)
        require_legacy(state)
        if state.get('execution_mode')!='episode_async_v1':raise ValueError('共因诊断只用于整话模式')
        ref={'path':diagnosis_ref,'sha256':digest(root/diagnosis_ref)}
        report=read_json(checked_file(root,ref))
        failures=failure_ids(state['panels'])
        if not failures or (len(failures)<=state['review_policy']['systemic_failure_count_gt'] and state.get('production_policy') != 'first_batch_production_v1'):
            raise ValueError('尚未超过真实视觉失败阈值，不登记共因诊断')
        for row in state['panels']:
            if row['panel_id'] not in failures:continue
            first=next((h for h in row.get('attempt_history',[]) if h.get('status')=='VISUAL_FAIL'), None)
            if first is None and row.get('status')=='VISUAL_FAIL':first=row
            errors=attempt_errors(state,root,first) if first else ['缺少真实首轮失败尝试']
            if errors:raise ValueError(f"{row['panel_id']}:"+';'.join(errors))
        if (report.get('policy')!='episode_failure_diagnosis_v1' or report.get('status')!='REVIEWED' or
                report.get('book_id')!=state['book_id'] or report.get('episode_id')!=state['episode_id'] or
                not isinstance(report.get('reviewer'),str) or not report['reviewer'].strip() or
                not isinstance(report.get('evidence'),str) or not report['evidence'].strip() or
                not set(failures)<=set(report.get('reviewed_failure_panel_ids',[])) or
                not isinstance(report.get('common_cause'),str) or not report['common_cause'].strip()):
            raise ValueError('共因诊断须覆盖当前全部真实失败格、具体原因和审查依据')
        for stopped in report.get('stopped_methods', []):
            if not isinstance(stopped, dict) or any(not isinstance(stopped.get(k), str) or not stopped[k].strip()
                    for k in ('method_key', 'cause_key', 'evidence')):
                raise ValueError('停止方法须有具体共因、方法与真实失败依据')
        new=copy.deepcopy(state)
        new['episode_failure_diagnosis']={**report,'source':ref}
        history=state_path.parent/'runtime_history';history.mkdir(exist_ok=True)
        previous=history/(expected_sha256+'.json')
        if not previous.exists():previous.write_bytes(state_path.read_bytes())
        _atomic_runtime_state(state_path,new)
        return {'status':'DIAGNOSIS_RECORDED','failure_panel_ids':failures,'state_sha256':digest(state_path)}


def _atomic_runtime_state(state_path, value):
    atomic_json(state_path, value)


def prepare_review(state, root, queue):
    """Create only missing real-image QA templates; one contact sheet per selected group."""
    from make_generation_qa import _main
    from batch_round import write_contact_sheet
    root=Path(root);records={r["panel_id"]:r for r in state["panels"]}
    for item in queue["items"]:
        row=records[item["panel_id"]]
        if item["action"] != "REVIEW_SIX_DIMENSIONS":
            continue
        if row.get("qa_report"):
            path=checked_file(root,row["qa_report"]);qa=read_json(path)
            if qa.get("source_manifest_sha256")==row["package_manifest"]["sha256"] and any(
                q.get("panel_id")==row["panel_id"] and q.get("image_sha256")==row["output"]["sha256"]
                for q in qa.get("panels",[])):
                item["qa_template"]=row["qa_report"];continue
        package=checked_file(root,row["package_manifest"]);image=checked_file(root,row["output"])
        parent=root/"06_图片验收";parent.mkdir(exist_ok=True)
        out=parent/(row["panel_id"]+"_"+uuid.uuid4().hex[:12])
        try:
            with redirect_stdout(io.StringIO()):
                _main(["--package",str(package.parent),"--manifest",package.name,"--images",str(image.parent),
                       "--image-path",str(image),"--output",str(out),"--episode-root",str(root),
                       "--panel-ids",row["panel_id"],"--skip-contact-sheet"])
        except SystemExit as exc:
            raise ValueError(f"{row['panel_id']}: QA材料创建失败:{exc}") from exc
        report=out/"生成图QA报告.json"
        item["qa_template"]={"path":report.relative_to(root).as_posix(),"sha256":digest(report)}
        item["template_status"]="UNREVIEWED"
    if queue["items"]:
        ids={i["panel_id"] for i in queue["items"]}
        order=[r["panel_id"] for r in state["panels"] if r["panel_id"] in ids]
        dest=root/"06_图片验收"/("增量组_"+uuid.uuid4().hex[:12]+".jpg")
        dest.parent.mkdir(exist_ok=True)
        queue["contact_sheet"]=write_contact_sheet(root,{"panel_ids":order},records,dest)
    return queue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--action", choices=("readiness", "preflight", "compile", "audit-inputs", "receiver-audit", "review", "checkpoint", "bundle", "commit", "repair-authorize", "diagnosis-record", "watch-progress", "watch-check", "watch-ack", "repair-plan", "decisions-register", "delivery-review", "production-questions"), required=True)
    parser.add_argument("--panels", nargs="*")
    parser.add_argument("--h001-panels", nargs="+", help="合并接包审计的准确首半话范围")
    parser.add_argument("--display-progress-dir", help="派生显示目录；仅保存现有检查结果，不新增门禁")
    parser.add_argument("--progress", action="store_true", help="stderr输出阶段/格号与定时进度；不改变判定")
    parser.add_argument("--batch")
    parser.add_argument("--candidate", action="store_true", help="待审B技术预检；不授予生产或包批准")
    parser.add_argument("--pending", help="复用原event_id待答记录，避免重复提问")
    parser.add_argument("--processed", help="仅去重观察通知的cursor JSON")
    parser.add_argument("--prepare-qa", action="store_true", help="仅新增/变化图生成未审模板及一次组联系表")
    parser.add_argument("--dependency-plan", help="已冻结依赖补齐方案的本话相对文件路径")
    parser.add_argument("--updates", help="真实返回或实际QA形成的updates JSON")
    parser.add_argument("--resolution", help="解析原未知请求的本话相对真实查证报告；不授予重发")
    parser.add_argument("--repair-authorization", help="整话滚动返修诊断文件的本话相对路径")
    parser.add_argument("--decisions", help="本话相对路径：已有QA上的生产决定/采用版本登记")
    parser.add_argument("--diagnosis", help="超过五张真实视觉失败的共因诊断文件本话相对路径")
    parser.add_argument("--expected-state-sha256", help="commit的CAS原状态哈希")
    parser.add_argument("--watch-event", help="watch-progress的实际事件JSON")
    parser.add_argument("--watch-alert-ids", help="watch-ack已送达事件ID数组JSON")
    parser.add_argument("--independent-work-pending", action="store_true", help="仍有可独立推进的实际工作")
    parser.add_argument("--write", help="可选新报告文件；不覆盖、不更改生产流程")
    args = parser.parse_args()
    try:
        path = Path(args.state).resolve(); root = path.parent.parent
        state = read_json(path)
        if "runtime" in state:
            settings(state["runtime"])
        if args.action == 'decisions-register':
            from production_decisions import register
            if not args.decisions or not args.expected_state_sha256: raise ValueError('缺决定文件或CAS哈希')
            ref = {'path': args.decisions, 'sha256': digest(root / args.decisions)}
            print(json.dumps(register(path, args.expected_state_sha256, ref), ensure_ascii=False)); return 0
        if args.action == 'production-questions':
            from review_policy import production_questions
            with file_session(): value = production_questions(state, root, read_json(Path(args.pending)) if args.pending else [])
            print(json.dumps(value, ensure_ascii=False, indent=2)); return 0
        if args.action == 'delivery-review':
            from panel_delivery import build
            with file_session(): value = build(state, root)
            if not args.write: raise ValueError('delivery-review须--write保存准确交审版本')
            dest = Path(args.write).resolve(); dest.relative_to(root)
            with dest.open('x', encoding='utf-8') as f: json.dump(value, f, ensure_ascii=False, indent=2)
            print(json.dumps({'status':'DELIVERY_REVIEW_SAVED','path':str(dest),'image_calls':0}, ensure_ascii=False)); return 0
        if args.action.startswith("watch-"):
            if state.get("runtime", {}).get("policy") not in {POLICY,'incremental_runtime_v2'}:
                raise ValueError("本RV未启用增量runtime；不得静默添加监控")
            from worker_watchdog import record_progress, check_ledger, acknowledge, DEFAULTS as WATCHDOG_DEFAULTS
            ledger = root / "00_输入审计" / "worker_watchdog.json"
            config = state["runtime"].get("watchdog", WATCHDOG_DEFAULTS)
            if args.action == "watch-progress":
                if not args.watch_event: raise ValueError("缺少--watch-event")
                value = record_progress(ledger, root, read_json(Path(args.watch_event)))
            elif args.action == "watch-check":
                value = check_ledger(ledger, state, config=config,
                                     independent_work_pending=args.independent_work_pending)
            else:
                if not args.watch_alert_ids: raise ValueError("缺少--watch-alert-ids")
                value = acknowledge(ledger, state, read_json(Path(args.watch_alert_ids)), config=config,
                                    independent_work_pending=args.independent_work_pending)
            print(json.dumps(value, ensure_ascii=False)); return 0
        if args.action == "commit":
            resolution_ref={"path":args.resolution,"sha256":digest(root/args.resolution)} if args.resolution else None
            value=commit_updates(path,args.expected_state_sha256,read_json(Path(args.updates)),resolution_ref=resolution_ref)
            print(json.dumps(value,ensure_ascii=False));return 0
        if args.action == 'repair-plan':
            if not args.diagnosis or not args.panels or len(args.panels)!=1:
                raise ValueError('repair-plan须一个格号及现有诊断文件')
            from repair_routes import plan
            diagnosis=read_json(checked_file(root, {'path':args.diagnosis,'sha256':digest(root/args.diagnosis)}))
            record=next(r for r in state['panels'] if r['panel_id']==args.panels[0])
            print(json.dumps(plan(diagnosis,record),ensure_ascii=False));return 0
        if args.action == "repair-authorize":
            if not args.repair_authorization or not args.expected_state_sha256:raise ValueError('缺少返修授权文件或CAS哈希')
            value=authorize_episode_repair(path,args.expected_state_sha256,args.repair_authorization)
            print(json.dumps(value,ensure_ascii=False));return 0
        if args.action == "diagnosis-record":
            if not args.diagnosis or not args.expected_state_sha256:raise ValueError('缺少共因诊断文件或CAS哈希')
            value=record_episode_diagnosis(path,args.expected_state_sha256,args.diagnosis)
            print(json.dumps(value,ensure_ascii=False));return 0
        from audit_progress import session as progress_session
        if args.candidate and args.action in {'audit-inputs','receiver-audit'}:
            raise ValueError('接包输入审计不得使用candidate')
        with progress_session(state.get('episode_id'),enabled=args.progress),file_session():
            if read_json(path)!=state:raise ValueError('CHECK_SNAPSHOT_CHANGED: 生产状态在审计开始前变化')
            if args.action=='readiness':
                value=preparation_report(state,root)
            elif args.action=='receiver-audit':
                value=receiver_audit(state,root,args.h001_panels,args.panels)
            elif args.action == 'bundle' and state.get('preparation_policy')=='episode_preparation_v1':
                dependency_plan = {"path":args.dependency_plan,"sha256":digest(root/args.dependency_plan)} if args.dependency_plan else None
                value=episode_bundle(state,root,dependency_plan)
            elif args.action in {"preflight", "compile", "audit-inputs", "bundle"}:
                # Bundle is for review, so missing B/package approval does not
                # become a fake dispatch permission.
                compiled = compile_jobs(state, root, args.panels, candidate=args.candidate or args.action == "bundle",input_audit=args.action=='audit-inputs')
                dependency_plan = {"path":args.dependency_plan,"sha256":digest(root/args.dependency_plan)} if args.dependency_plan else None
                value = review_bundle(state, root, compiled, dependency_plan) if args.action == "bundle" else compiled
            elif args.action == "checkpoint":
                value = checkpoint(state, root)
            else:
                from review_queue import build_queue
                plan = read_json(checked_file(root, state["batch_plan"]))
                batch = next(b for b in plan["batches"] if b["batch_id"] == args.batch)
                processed = read_json(Path(args.processed)) if args.processed else None
                value = build_queue(state, root, batch, incremental=True, processed=processed)
                if args.panels is not None:
                    if len(set(args.panels))!=len(args.panels) or not set(args.panels)<=set(batch["panel_ids"]):
                        raise ValueError("待审选集须准确属于本半话且不重复")
                    value["items"]=[i for i in value["items"] if i["panel_id"] in args.panels]
                else:
                    size=state.get("runtime",DEFAULTS)["review_group_size"]
                    value["remaining_pending_count"]=max(0,len(value["items"])-size)
                    value["items"]=value["items"][:size]
                if args.prepare_qa:
                    value=prepare_review(state,root,value)
        if args.write:
            dest = Path(args.write).resolve(); dest.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("x", encoding="utf-8", newline='\n') as f:
                json.dump(value, f, ensure_ascii=False, indent=2); f.write("\n")
        if args.display_progress_dir:
            from production_progress import observe_runtime
            try: observe_runtime(args.display_progress_dir,path,args.action,value,expected_state=state)
            except (OSError,ValueError,KeyError,TypeError) as exc:
                print("DISPLAY_PROGRESS_WARNING: "+str(exc),file=__import__("sys").stderr)
        print(json.dumps(value, ensure_ascii=False))
        if args.action=='receiver-audit':
            return 1 if (value['preparation'].get('global_errors') or value['preparation'].get('errors') or
                         any(value[k]['preflight'].get('status') not in {'READY','PARTIAL_READY'} for k in ('h001','all_inputs'))) else 0
        if value.get('global_errors'):return 1
        preflight = value.get("preflight", {})
        return 1 if preflight and preflight.get("status") not in {"READY", "PARTIAL_READY"} else 0
    except (OSError, ValueError, TypeError, KeyError, StopIteration) as exc:
        print(json.dumps({"status": "HOLD", "errors": [str(exc)]}, ensure_ascii=False)); return 1


if __name__ == "__main__":
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
