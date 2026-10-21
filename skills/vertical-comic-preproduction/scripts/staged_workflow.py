#!/usr/bin/env python3
"""Read-only staged workflow gate. Checks evidence consistency, never invents approval."""
from __future__ import annotations
from codex_reference_contract import resolve_path

import argparse
import json
from pathlib import Path

from codex_reference_contract import read_json, checked_file, digest, ratio, validate_panel, execution_errors
from continuity_contract import check_dimension_report
from style_contract import POLICY as STYLE_POLICY, validate_style, output_spec_errors
from rule_memory import application_errors as memory_errors, binding_errors as memory_binding_errors
from authority_updates import authority_scoped, revocation_errors, revocation_token
from codex_reference_contract import physical_file

POLICY = "staged_comic_v1"
DONE = {"VISUAL_PASS", "USER_ACCEPTED"}


def basis_errors(panel, basis):
    """Bind the execution copy to the approved episode reference/style index."""
    from visual_evidence import basis_errors as visual_basis_errors, packet_errors as visual_packet_errors
    errors = visual_basis_errors(basis)
    errors.extend(visual_packet_errors(basis, panel, panel, basis))
    approved = {r["sha256"] for r in basis.get("reference_files", [])}
    refs = panel.get("reference_images", [])
    for ref in refs:
        from reference_atlas import is_atlas
        derived = is_atlas(ref) and bool(ref.get('source_regions')) and all((r.get('source_file',{}).get('sha256') if isinstance(r.get('source_file'),dict) else r.get('source_sha256')) in approved for r in ref['source_regions'])
        if ref.get("sha256") not in approved and not derived:
            errors.append(f"{ref.get('alias')}:参考未纳入当前批准基准")
    style = basis.get("style", {})
    contract = panel.get("style_contract", {})
    hashes = {r.get("sha256") for r in refs if r.get("alias") in contract.get("reference_aliases", [])}
    if not style.get("reference_sha256") or hashes != set(style["reference_sha256"]) or contract.get("traits") != style.get("traits"):
        errors.append("样例或风格特征与当前批准视觉基准不一致")
    if contract.get("book_id") != basis.get("book_id"):
        errors.append("风格合同属于其他书")
    return errors


def read(path):
    return read_json(path)


def approval_errors(approval, root, artifacts, book, episode, *, phase=None, panel_ids=None):
    revoked = revocation_errors(approval, book, episode)
    if revoked: return revoked
    from audit_cache import derived, content_key
    key=content_key([str(resolve_path(Path(root))), approval, artifacts, book, episode, phase, panel_ids, revocation_token()])
    value=derived('approval_validation',key,
                  lambda:_approval_errors(approval,root,artifacts,book,episode,phase=phase,panel_ids=panel_ids),
                  accept=lambda errors:not errors)
    return list(value)


def _approval_errors(approval, root, artifacts, book, episode, *, phase=None, panel_ids=None):
    errors = []
    if not isinstance(approval, dict):
        return ["缺少用户批准记录"]
    if approval.get('source_kind') == 'agent_decision':
        from review_policy import decision_errors
        errors.extend(decision_errors(approval, root, book, episode))
        if errors:return errors
        if phase is None or approval.get('phase') != phase:
            errors.append('AUTHORITY_HOLD:执行者决定须从准确阶段入口核验')
        if panel_ids is not None and not set(panel_ids) <= set(approval.get('panel_ids', [])):
            errors.append('AUTHORITY_HOLD:决定未覆盖本次格号')
    elif approval.get("status") != "APPROVED" or approval.get("source_kind") != "user_message" or not approval.get("quote") or not approval.get("source_locator"):
        errors.append("须有实际用户批准原文和消息来源；技术PASS不能代替")
    if approval.get("book_id") != book or not (approval.get("episode_id") == episode or isinstance(approval.get("episode_ids"), list) and episode in approval["episode_ids"]):
        errors.append("批准的本书/本话范围不一致")
    bound = approval.get("artifacts")
    if not isinstance(bound, list):
        return errors + ["批准缺少文件版本范围"]
    for item in bound:
        try:
            checked_file(root, item)
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"批准依赖已失效: {exc}")
    def covered(item):
        if item in bound:return True
        try:
            file=checked_file(root,item)
            if file.suffix.lower()!='.json':return False
            value=read(file)
            if value.get('id_mapping',{}).get('policy')=='source_id_map_v1':
                from source_adapter import verify
                return not verify(value,root,episode) and value['id_mapping']['source_snapshot'] in bound
            if value.get('policy')=='semantic_audit_v1':
                return value.get('book_id')==book and value.get('episode_id')==episode and value.get('visual_basis') in bound and value.get('shot_manifest') in bound
        except (OSError,ValueError,TypeError,KeyError):pass
        return False
    if any(not covered(item) for item in artifacts):
        errors.append("批准未覆盖当前成果版本")
    return errors


def _qa_errors(root, record):
    errors = []
    manifest_path = checked_file(root, record.get("package_manifest"))
    manifest = read(manifest_path)
    report = read(checked_file(root, record.get("qa_report")))
    output = checked_file(root, record.get("output"))
    panels = manifest.get("panels", [])
    if len(panels) != 1 or panels[0].get("panel_id") != record.get("panel_id"):
        return ["每次执行/验收快照须只包含对应当前格，保持原格号"]
    if manifest.get("style_policy") != STYLE_POLICY:
        errors.append("当前执行快照未启用画风合同")
    panel = panels[0]
    from frame_ratio_plan import enabled as ratios_enabled,plan_errors as ratio_plan_errors,panel_errors as ratio_panel_errors,image_errors as ratio_image_errors
    errors.extend(ratio_plan_errors(manifest,root))
    errors.extend(ratio_panel_errors(manifest,root,panels,prompt=True))
    if manifest.get('execution_contract')=='comic_execution_v2':
        from identity_confirmation import validate_manifest as validate_identity
        errors.extend(validate_identity(manifest,root,prompt=True,reference_root=manifest_path.parent))
    tags=[]
    if manifest.get('execution_contract')=='comic_execution_v2':
        from continuity_context import rule_tags
        tags=rule_tags(manifest,manifest_path.parent,panel)
    errors.extend(memory_errors(manifest.get("memory_source"), "generation", panel, manifest_path.parent,context_tags=tags,scope=manifest))
    from PIL import Image
    with Image.open(physical_file(output)) as opened:
        if ratios_enabled(manifest):errors.extend(ratio_image_errors(panel,opened.size))
        errors.extend(output_spec_errors(panel, opened.size, opened.format))
        target, tolerance = ratio(panel.get("frame_ratio")), panel.get("ratio_tolerance")
        if target is None or type(tolerance) not in (int, float) or not 0 <= tolerance < 1 or abs(opened.width / opened.height - target) / target > tolerance:
            errors.append("实际输出比例未通过重新计算")
    errors.extend(validate_style(panel, manifest_path.parent))
    errors.extend(check_dimension_report(manifest, report, manifest_path)["errors"])
    items = report.get("panels", [])
    if len(items) != 1 or items[0].get("image_sha256") != digest(output):
        errors.append("当前图片与验收图片不一致")
    else:
        errors.extend(memory_errors(manifest.get("memory_source"), "image_review", panel, manifest_path.parent,
                                    applications=items[0].get("memory_review", []), image_sha256=digest(output),context_tags=tags,scope=manifest))
        for field in ("camera_match", "shot_scale_match", "background_view_match", "body_crop_match", "required_visible_information_preserved", "no_extra_offscreen_characters"):
            if items[0].get(field) is not True:
                errors.append(f"完整视觉检查未通过: {field}")
        if panel.get("composition_reference", {}).get("mode") in ("CREATE", "REUSE") and items[0].get("composition_match") is not True:
            errors.append("所需构图对照未通过")
    # Returned-image QA verifies its original observed request. Current submit
    # limits must not rewrite or invalidate a proven historical execution.
    preflight, submission = validate_panel(panel, manifest_path.parent, enforce_input_budget=False)
    errors.extend(preflight)
    execution = panel.get("generation_execution", {})
    if execution.get("status") != "COMPLETED":
        errors.append("缺少实际完成的生成证据")
    elif submission is not None:
        errors.extend(execution_errors(execution, submission, manifest_path.parent, panel["panel_id"]))
        response = read(checked_file(manifest_path.parent, execution.get("response_evidence")))
        if not any(item.get("sha256") == digest(output) for item in response.get("outputs", [])):
            errors.append("当前图片不属于本次实际返回")
    return errors


def qa_errors(root, record):
    from review_reuse import cached_qa
    return cached_qa(root,record,lambda:_qa_errors(root,record))


def _evaluate_impl(state, root, check="status", requested=None):
    if state.get("execution_mode") == "episode_async_v1":
        from scoped_episode_workflow import evaluate_episode
        return evaluate_episode(state, root, check, requested)
    """Return next action. Never edits state, advances cursor, or grants acceptance."""
    if state.get("execution_mode") == "half_episode_async_v1":
        from half_workflow import evaluate_half
        return evaluate_half(state, root, check, requested)
    if state.get("execution_mode") == "batch5_v1":
        from batch_workflow import evaluate_batch
        return evaluate_batch(state, root, check, requested)
    if state.get("execution_mode") not in (None, "sequential_v1"):
        return {"status": "HOLD", "next_action": "EXECUTION_MODE_HOLD", "errors": ["未知执行模式；不得降级为旧顺序流程"]}
    book, episode = state.get("book_id"), state.get("episode_id")
    def result(action, errors=(), cursor=None):
        ok = not errors and action in {"READY_FOR_CURRENT_PANEL", "READY_TO_PACKAGE"}
        return {"policy": POLICY, "status": "PASS" if ok else "HOLD", "next_action": action,
                "cursor": cursor, "errors": list(errors), "user_acceptance": "NOT_GRANTED_BY_SCRIPT"}
    if state.get("policy") != POLICY or not book or not episode:
        return result("COMPLETE_INPUT_AUDIT", ["流程版本或本书/本话标识缺失"])
    if state.get("cancelled") is True:
        return result("CANCELLED", ["用户取消；不得自动恢复"])
    if state.get("holds"):
        return result("RESOLVE_HOLD", state["holds"])
    try:
        checked_file(root, state.get("source_script"))
        source = read(checked_file(root, state.get("source_snapshot")))
        order = source.get("panel_ids")
        if not isinstance(order, list) or not order or any(not isinstance(x, str) for x in order) or len(set(order)) != len(order):
            return result("COMPLETE_INPUT_AUDIT", ["源格序为空或重复"])
        if source.get("source_sha256") != state["source_script"]["sha256"]:
            return result("COMPLETE_INPUT_AUDIT", ["源格序快照与剧本版本不一致"])
        if not isinstance(source.get("locked_scripts"), dict) or set(source["locked_scripts"]) != set(order):
            return result("COMPLETE_INPUT_AUDIT", ["源快照缺少逐格原文"])
        # Source extraction still needs actual comparison against the original script.
        basis = state.get("visual_basis")
        basis_data = read(checked_file(root, basis))
        if basis_data.get("book_id") != book or basis_data.get("episode_id") != episode:
            return result("COMPLETE_INPUT_AUDIT", ["视觉基准本书/本话不一致"])
        basis_refs = basis_data.get("reference_files", [])
        if not basis_refs:
            return result("COMPLETE_INPUT_AUDIT", ["视觉基准没有实际参考文件"])
        for ref in basis_refs:
            checked_file(root, ref)
        gates = state.get("gates", {})
        errors = approval_errors(gates.get("visual_basis"), root, [state["source_script"], state["source_snapshot"], basis], book, episode)
        if errors:
            return result("WAIT_VISUAL_BASIS_APPROVAL", errors)
        shot_ref = state.get("shot_manifest")
        shots = read(checked_file(root, shot_ref))
        memory_binding = memory_binding_errors(state, shots=shots)
        if memory_binding:
            return result("MEMORY_HOLD", memory_binding)
        if shots.get("execution_mode") in {"batch5_v1", "half_episode_async_v1"}:
            return result("EXECUTION_MODE_HOLD", ["批次镜头不能删除状态模式标识后走旧门禁"])
        shot_panels = shots.get("panels", shots.get("shot_design", []))
        if [p.get("panel_id") for p in shot_panels] != order:
            return result("REPAIR_SHOTS", ["全话镜头格序与源快照不一致"])
        errors = []
        for p in shot_panels:
            if p.get("locked_script") != source["locked_scripts"][p["panel_id"]]:
                errors.append(f"{p['panel_id']}:镜头原文与源快照不一致")
            keys = p.get("visual_state_keys")
            if not isinstance(keys, list) or not keys or any(not isinstance(k, str) or not k.strip() for k in keys):
                errors.append(f"{p['panel_id']}:缺少可追溯的视觉状态键")
        errors.extend(approval_errors(gates.get("shot_design"), root, [basis, shot_ref], book, episode))
        if errors:
            return result("WAIT_SHOT_APPROVAL", errors)
        records = state.get("panels", [])
        if [p.get("panel_id") for p in records] != order:
            return result("COMPLETE_INPUT_AUDIT", ["流程逐格清单与源格序不一致"])
        completed = 0
        for record in records:
            if record.get("status") not in DONE:
                break
            errors = qa_errors(root, record)
            if errors:
                return result("REVIEW_CURRENT_PANEL", errors, record["panel_id"])
            # Verify the generated package still came from the approved shot.
            packet = read(checked_file(root, record["package_manifest"]))
            original = shot_panels[completed]
            derived = packet["panels"][0]
            memory_binding = memory_binding_errors(state, packet=packet)
            memory_binding.extend(memory_errors(state.get("memory_source"), "shot_design", original, root))
            if memory_binding:
                return result("MEMORY_HOLD", memory_binding, record["panel_id"])
            if packet.get("book_id") != book or packet.get("episode_id") != episode:
                return result("INVALIDATE_DEPENDENT_OUTPUT", ["旧输出包本书/本话不一致"], record["panel_id"])
            errors = basis_errors(derived, basis_data)
            if errors:
                return result("INVALIDATE_DEPENDENT_OUTPUT", errors, record["panel_id"])
            for key in ("locked_script", "framing", "frame_ratio", "camera_view_signature", "character_bindings", "scene_binding", "continuity_contract", "visual_state_keys", "memory_tags"):
                if derived.get(key) != original.get(key):
                    return result("INVALIDATE_DEPENDENT_OUTPUT", [f"{record['panel_id']}:{key}与批准镜头不一致"], record["panel_id"])
            completed += 1
        pilot_count = min(3, len(order))
        if completed >= pilot_count:
            pilot_outputs = [p["output"] for p in records[:pilot_count]]
            errors = approval_errors(gates.get("pilot"), root, [basis, shot_ref, *pilot_outputs], book, episode)
            if errors:
                return result("WAIT_PILOT_APPROVAL", errors, order[completed] if completed < len(order) else None)
        seen = set()
        for i, shot in enumerate(shot_panels[:completed]):
            new_keys = set(shot["visual_state_keys"]) - seen
            seen.update(shot["visual_state_keys"])
            if i >= pilot_count and new_keys:
                # One scoped user message may approve every new state in this panel.
                approval = state.get("state_reviews", {}).get(shot["panel_id"])
                errors = approval_errors(approval, root, [basis, shot_ref, records[i]["output"]], book, episode)
                if errors:
                    return result("WAIT_NEW_STATE_APPROVAL", errors, shot["panel_id"])
        if completed == len(order):
            errors = approval_errors(gates.get("final"), root, [basis, shot_ref, *[p["output"] for p in records]], book, episode)
            if errors:
                return result("WAIT_FINAL_APPROVAL", errors)
            if check == "generate":
                return result("EPISODE_COMPLETE", ["本话无待生成格"])
            return result("READY_TO_PACKAGE")
        current = records[completed]
        pid = current["panel_id"]
        if check == "deliver":
            return result("EPISODE_INCOMPLETE", ["缺少已验收图片，不能交付成品包"], pid)
        if current.get("status") not in ("PENDING", "REPAIR_AUTHORIZED"):
            return result("REVIEW_OR_RESOLVE_CURRENT_PANEL", ["当前格待验收、失败、取消或状态无效；不能继续下一格"], pid)
        if check == "status":
            return result("PREPARE_CURRENT_PANEL_INPUT", cursor=pid)
        if requested != pid:
            return result("SOURCE_ORDER_HOLD", [f"只能生成当前格{pid}，不能跳到{requested}"], pid)
        authorization = state.get("production_authorization")
        if isinstance(authorization, dict) and (authorization.get('policy') == 'preparation_authorization_v1' or authorization.get('phase') == 'preparation'):
            return result('INPUT_HOLD', ['前期记录不能用作正文生产授权'])
        errors = approval_errors(authorization, root, [state["source_script"]], book, episode)
        if pid not in (authorization or {}).get("panel_ids", []):
            errors.append("当前格不在已授权生产范围")
        if errors:
            return result("WAIT_PRODUCTION_AUTHORIZATION", errors, pid)
        manifest_path = checked_file(root, current.get("package_manifest"))
        packet = read(manifest_path)
        if packet.get("book_id") != book or packet.get("episode_id") != episode:
            return result("INPUT_HOLD", ["执行包本书/本话不一致"], pid)
        subset_path = checked_file(root, current.get("shot_subset"))
        subset = read(subset_path)
        if state.get("input_priority_policy") and (subset.get("input_priority_policy") != state["input_priority_policy"] or packet.get("input_priority_policy") != state["input_priority_policy"]):
            return result("INPUT_HOLD", ["镜头选集与执行包input_priority_policy须与本话冻结合同一致"], pid)
        if subset.get("panels") != [shot_panels[completed]]:
            return result("INPUT_HOLD", ["单格镜头快照不是获批全话记录的准确选集"], pid)
        if packet.get("style_policy") != STYLE_POLICY or packet.get("workflow_policy") != POLICY or len(packet.get("panels", [])) != 1:
            return result("INPUT_HOLD", ["单格执行包须声明阶段/画风合同且只含当前格"], pid)
        panel = packet["panels"][0]
        errors = memory_binding_errors(state, packet=packet)
        errors.extend(memory_errors(state.get("memory_source"), "shot_design", shot_panels[completed], root))
        errors.extend(memory_errors(state.get("memory_source"), "generation", panel, manifest_path.parent))
        if state.get("memory_source") and current.get("status") == "REPAIR_AUTHORIZED" and panel.get("operation") != "repair":
            errors.append("MEMORY_HOLD:返修执行包必须声明operation=repair")
        if panel.get("memory_tags") != shot_panels[completed].get("memory_tags"):
            errors.append("MEMORY_HOLD:执行包标签与获批镜头不一致")
        if errors:
            return result("MEMORY_HOLD", errors, pid)
        if panel.get("panel_id") != pid or panel.get("visual_state_keys") != shot_panels[completed]["visual_state_keys"]:
            return result("INPUT_HOLD", ["执行格号或视觉状态与获批镜头不一致"], pid)
        errors = basis_errors(panel, basis_data)
        if errors:
            return result("INPUT_HOLD", errors, pid)
        from validate_preproduction import Gate
        errors = Gate(root, expected_panel_ids=[pid]).run(subset_path, manifest_path)["errors"]
        errors.extend(validate_style(panel, manifest_path.parent))
        errors.extend(output_spec_errors(panel))
        if panel.get("generation_execution", {}).get("status") != "NOT_RUN":
            errors.append("新调用计划须为NOT_RUN，已有结果应验收/复用或建立新返修版本")
        return result("INPUT_HOLD" if errors else "READY_FOR_CURRENT_PANEL", errors, pid)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
        return result("INPUT_EVIDENCE_HOLD", [str(exc)])


def _evaluate_with_session(state, root, check="status", requested=None):
    from review_reuse import session
    from execution_contract import state_errors
    # The episode router calls evaluate_episode, which checks the same contract
    # before reading any episode input. Keep its direct-call guard, without
    # introducing a second contract/toolchain walk through the standard entry.
    errors=state_errors(state,root) if state.get('execution_mode')!='episode_async_v1' else []
    if errors:return {'status':'HOLD','next_action':'EXECUTION_CONTRACT_HOLD','errors':errors,'user_acceptance':'NOT_GRANTED_BY_SCRIPT'}
    if state.get('optimization_policy') not in (None,'scoped_half_review_v1','scoped_episode_review_v1'):
        return {'status':'HOLD','next_action':'OPTIMIZATION_POLICY_HOLD','errors':['未知审查优化策略，不能静默降级'],'user_acceptance':'NOT_GRANTED_BY_SCRIPT'}
    with session(state.get('optimization_policy') in {'scoped_half_review_v1','scoped_episode_review_v1'}) as memo:
        result=_evaluate_impl(state,root,check,requested)
        result['optimization_status']='SCOPED_OPTIMIZATION_ENABLED' if state.get('optimization_policy') else 'LEGACY_UNCHANGED'
        if memo is not None:result['qa_reuse_statistics']={'hits':memo['hits'],'validated':memo['misses'],'persistent_cache_trusted':False}
        return result


@authority_scoped
def evaluate(state, root, check="status", requested=None):
    from codex_reference_contract import file_session
    from codex_reference_contract import _READ_VIEW
    view = _READ_VIEW.get()
    if view is not None: view.authorize_check(check, requested)
    if check=='input_audit_batch' and (state.get('execution_mode')!='episode_async_v1' or state.get('parallel_context')):
        raise ValueError('接包输入审计不能用于旧模式或线上调度上下文')
    from task_context import state_errors
    with file_session() as memo:
        scoped=state_errors(state,root)
        if scoped:
            return {'status':'HOLD','next_action':'TASK_SCOPE_HOLD','errors':scoped,
                    'ready_panel_ids':[],'reports':[],'failure_domain':'INPUT_OR_REVIEW_CONTEXT'}
        result = _evaluate_with_session(state, root, check, requested)
        action=result.get('next_action','')
        if 'SNAPSHOT' in str(result.get('errors',[])) or action=='EXECUTION_CONTRACT_HOLD':
            result['failure_domain']='RUNTIME_OR_FROZEN_INPUT'
        elif action in {'MEMORY_HOLD','SEMANTIC_AUDIT_HOLD','GLOBAL_PREPARATION_HOLD','INPUT_EVIDENCE_HOLD'}:
            result['failure_domain']='INPUT_OR_REVIEW_CONTEXT'
        else:
            # A gate's HOLD alone never proves the image is visually defective.
            result['failure_domain']='SEE_EXACT_GATE_AND_IMAGE_QA' if result.get('errors') else None
        result['file_reuse_statistics'] = {k: memo[k] for k in ('hash_reads', 'hash_hits')}
        return result


def preflight_many(state, root, panel_ids=None, candidate=False, input_audit=False):
    """Walk current scope gates once, then run every selected panel's original gates."""
    if state.get('optimization_policy') not in {'scoped_half_review_v1','scoped_episode_review_v1'}:
        return {'status': 'HOLD', 'next_action': 'RUNTIME_POLICY_HOLD',
                'errors': ['批量入口须使用对应整话或旧半话审查策略；旧流程不静默迁移'],
                'ready_panel_ids': [], 'reports': []}
    if input_audit and (candidate or state.get('execution_mode')!='episode_async_v1' or state.get('parallel_context')):
        raise ValueError('接包输入审计只适用于未领容量的整话新制，不授予生产许可')
    return evaluate(state, root, 'input_audit_batch' if input_audit else 'candidate_batch' if candidate else 'generate_batch', panel_ids)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, help="本话00_输入审计/生产流程.json")
    parser.add_argument("--root", help="默认生产流程文件父目录的父目录")
    parser.add_argument("--check", choices=("status", "generate", "deliver"), default="status")
    parser.add_argument("--panel", help="generate模式必填源格号")
    args = parser.parse_args()
    path = resolve_path(Path(args.state))
    root = resolve_path(Path(args.root)) if args.root else path.parent.parent
    try:
        report = evaluate(read(path), root, args.check, args.panel)
    except (OSError, ValueError) as exc:
        report = {"status": "HOLD", "next_action": "INPUT_EVIDENCE_HOLD", "errors": [str(exc)]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
