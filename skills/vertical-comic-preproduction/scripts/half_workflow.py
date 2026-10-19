#!/usr/bin/env python3
"""Two source-contiguous half-episode windows with asynchronous eligible sets and scoped rounds."""
from pathlib import Path
from codex_reference_contract import checked_file
from staged_workflow import POLICY, DONE, read, approval_errors
from rule_memory import binding_errors
from batch_round import MODE, snapshot, settings, report_errors, PASS, TERMINAL


def build_plan(state, shots, source=None):
    if state.get('optimization_policy') == 'scoped_half_review_v1':
        from scoped_inputs import build_plan as stable_plan
        if source is None: raise ValueError('优化模式必须从真实源快照制定稳定半话计划')
        return stable_plan(state, source)
    panels = shots.get('panels', shots.get('shot_design', []))
    if not panels: raise ValueError('镜头表为空')
    order = [p['panel_id'] for p in panels]
    if len(set(order)) != len(order): raise ValueError('源格重复')
    split = (len(order) + 1) // 2
    seen, barriers = set(), []
    for i, p in enumerate(panels):
        deps = p.get('generation_dependencies')
        if not isinstance(deps, list) or len(set(deps)) != len(deps) or any(not isinstance(d, str) or d not in order[:i] for d in deps):
            raise ValueError(f'{order[i]}:实图依赖只能是本话前序格')
        keys = p.get('visual_state_keys')
        if not isinstance(keys, list) or not keys or any(not isinstance(k, str) or not k.strip() for k in keys) or type(p.get('requires_state_review')) is not bool:
            raise ValueError(f'{order[i]}:缺少准确视觉状态或审查条件')
        if p['requires_state_review'] or (i > 0 and set(keys) - seen): barriers.append(order[i])
        seen.update(keys)
    batches = [{'batch_id': 'H001', 'panel_ids': order[:split], 'state_barriers': [p for p in barriers if p in order[:split]]}]
    if order[split:]: batches.append({'batch_id': 'H002', 'panel_ids': order[split:], 'state_barriers': [p for p in barriers if p in order[split:]]})
    return {'policy': MODE, 'source_snapshot': state['source_snapshot'], 'visual_basis': state['visual_basis'],
            'shot_manifest': state['shot_manifest'], 'batch_strategy': 'half_episode', 'max_batch_size': split,
            'pilot_panel_ids': order[:split], 'batches': batches}


def evaluate_half(state, root, check='status', requested=None):
    if state.get('optimization_policy') == 'scoped_half_review_v1':
        from scoped_half_workflow import evaluate_scoped
        return evaluate_scoped(state, root, check, requested)
    from batch_workflow import completed_errors, input_errors, batch_review_errors, cross_episode_errors
    root = Path(root).resolve()
    def result(action, errors=(), batch=None, eligible=(), round_id=1):
        return {'policy': POLICY, 'execution_mode': MODE, 'status': 'PASS' if not errors and action in {'READY_FOR_HALF_PANEL', 'READY_TO_PACKAGE'} else 'HOLD',
                'next_action': action, 'batch_id': (batch or {}).get('batch_id'), 'batch_panel_ids': (batch or {}).get('panel_ids', []),
                'round_id': round_id, 'eligible_panel_ids': list(eligible), 'cursor': requested, 'errors': list(errors),
                'user_acceptance': 'NOT_GRANTED_BY_SCRIPT'}
    try:
        book, episode = state.get('book_id'), state.get('episode_id')
        if state.get('policy') != POLICY or state.get('execution_mode') != MODE or not book or not episode:
            return result('COMPLETE_INPUT_AUDIT', ['流程/书话/半话模式缺失'])
        settings(state)
        if state.get('cancelled'): return result('CANCELLED', ['取消的任务不能自动恢复'])
        if state.get('holds'): return result('RESOLVE_HOLD', state['holds'])
        if 'parallel_context' in state:
            from parallel_dispatch import context_errors
            errors = context_errors(state['parallel_context'], root, book, episode)
            if errors: return result('PARALLEL_HOLD', errors)
        checked_file(root, state['source_script'])
        source = read(checked_file(root, state['source_snapshot'])); order = source.get('panel_ids')
        if not isinstance(order, list) or not order or len(set(order)) != len(order) or any(not isinstance(p, str) for p in order) or source.get('source_sha256') != state['source_script']['sha256'] or set(source.get('locked_scripts', {})) != set(order):
            return result('COMPLETE_INPUT_AUDIT', ['源格序/原文/源文件版本不一致'])
        basis = read(checked_file(root, state['visual_basis']))
        if basis.get('book_id') != book or basis.get('episode_id') != episode or not basis.get('reference_files'):
            return result('COMPLETE_INPUT_AUDIT', ['视觉基准归属/实际参考缺失'])
        for ref in basis['reference_files']: checked_file(root, ref)
        gates = state.get('gates', {})
        errors = approval_errors(gates.get('visual_basis'), root, [state['source_script'], state['source_snapshot'], state['visual_basis']], book, episode)
        if errors: return result('WAIT_VISUAL_BASIS_APPROVAL', errors)
        shots = read(checked_file(root, state['shot_manifest'])); errors = binding_errors(state, shots=shots)
        if errors: return result('MEMORY_HOLD', errors)
        panels = shots.get('panels', shots.get('shot_design', []))
        if shots.get('execution_mode') != MODE or [p.get('panel_id') for p in panels] != order or any(p.get('locked_script') != source['locked_scripts'][p['panel_id']] for p in panels):
            return result('REPAIR_SHOTS', ['镜头模式/原文/格序不一致'])
        errors = approval_errors(gates.get('shot_design'), root, [state['visual_basis'], state['shot_manifest']], book, episode)
        if errors: return result('WAIT_SHOT_APPROVAL', errors)
        plan = read(checked_file(root, state['batch_plan']))
        if plan != build_plan(state, shots): return result('REBUILD_BATCH_PLAN', ['半话计划与获批源序、依赖、状态不一致'])
        records = state.get('panels', [])
        if [r.get('panel_id') for r in records] != order: return result('COMPLETE_INPUT_AUDIT', ['状态格序不一致'])
        by_id, shot_by_id = {r['panel_id']: r for r in records}, {p['panel_id']: p for p in panels}
        checked_ids, previous = set(), []
        for bidx, batch in enumerate(plan['batches']):
            ids = batch['panel_ids']; current = [by_id[p] for p in ids]
            for r in current:
                if r.get('status') in DONE:
                    if r.get('round_id') not in (1, 2) or not r.get('attempt_id'): return result('ROUND_HOLD', ['合格图缺少真实轮次/尝试'], batch)
                    errors = completed_errors(state, root, r, shot_by_id[r['panel_id']], basis, by_id)
                    if errors: return result('REVIEW_HALF_PANEL', errors, batch, round_id=r['round_id'])
                    checked_ids.add(r['panel_id'])
            # State barriers limit submission, but independent predecessors may still run.
            cutoff = len(ids)
            for pid in batch['state_barriers']:
                r = by_id[pid]
                if pid not in checked_ids:
                    cutoff = ids.index(pid) + 1; break
                errors = approval_errors(state.get('state_reviews', {}).get(pid), root, [state['visual_basis'], state['shot_manifest'], r['output']], book, episode)
                if errors: return result('WAIT_NEW_STATE_APPROVAL', errors, batch, round_id=r['round_id'])
            refs = state.get('round_reviews', {}).get(batch['batch_id'], {})
            report1 = read(checked_file(root, refs['1'])) if refs.get('1') else None
            repair_ids, constraints = [], {}
            if report1 is not None:
                errors = report_errors(state, root, batch, report1, 1, by_id)
                if errors: return result('ROUND_HOLD', errors, batch)
                if report1['strategy'] == 'CALL_HOLD': return result('RESOLVE_CALL_HOLD', ['调用异常/结果未知先查实际请求，不能重复抽图'], batch)
                repair_ids = report1['repair_panel_ids']; constraints = report1.get('diagnosis', {}).get('repair_constraints', {})
                old = {a['panel_id']: a for a in report1['attempts']}
                for r in current:
                    if r['panel_id'] not in repair_ids and snapshot(r) != old[r['panel_id']]:
                        return result('ROUND_HOLD', ['首轮合格图被替换/重生成，须恢复准确保留版本'], batch)
                    if r.get('round_id') == 2:
                        if r['panel_id'] not in repair_ids or r.get('attempt_id') == old[r['panel_id']]['attempt_id'] or old[r['panel_id']] not in [snapshot(h) for h in r.get('attempt_history', [])]:
                            return result('ROUND_HOLD', ['修正必须在失败范围并保留原始失败尝试'], batch, round_id=2)
            elif any(r.get('status') == 'REPAIR_AUTHORIZED' or r.get('attempt_history') for r in current):
                return result('ROUND_HOLD', ['返修须先完成首轮汇总并使用第二轮；不能伪装成首轮重试'], batch)
            elif any(r.get('round_id') == 2 for r in current):
                return result('ROUND_HOLD', ['第二轮缺首轮真实QA汇总与诊断'], batch, round_id=2)
            if any(type(r.get('round_id', 1)) is not int or r.get('round_id', 1) not in (1, 2) for r in current):
                return result('STOP_DIAGNOSE', ['不允许第三轮自动调用'], batch)
            complete = all(r.get('status') in DONE for r in current)
            if complete:
                if report1 is None: return result('REVIEW_HALF_BATCH', ['须先完成首轮汇总'], batch)
                if repair_ids:
                    if any(by_id[p].get('round_id') != 2 for p in repair_ids): return result('ROUND_HOLD', ['失败格未经过准确修正尝试'], batch, round_id=2)
                    if not refs.get('2'): return result('REVIEW_CORRECTION', ['修正后需全半话复验'], batch, round_id=2)
                    report2 = read(checked_file(root, refs['2'])); errors = report_errors(state, root, batch, report2, 2, by_id)
                    if errors or report2['strategy'] != 'ALL_PASS': return result('STOP_DIAGNOSE', errors or ['修正仍未通过'], batch, round_id=2)
                errors = batch_review_errors(state, root, batch, current, previous)
                if errors: return result('REVIEW_HALF_CONTINUITY', errors, batch, round_id=2 if repair_ids else 1)
                if bidx == 0:
                    errors = approval_errors(gates.get('pilot'), root, [state['visual_basis'], state['shot_manifest'], *[r['output'] for r in current]], book, episode)
                    if errors: return result('WAIT_FIRST_HALF_APPROVAL', errors, batch, round_id=2 if repair_ids else 1)
                previous = current; continue
            later = [by_id[p] for b in plan['batches'][bidx+1:] for p in b['panel_ids']]
            if any(r.get('status') != 'PENDING' for r in later): return result('OUT_OF_BATCH_HOLD', ['第二半话不能越过第一半话审查'], batch)
            if check == 'deliver': return result('EPISODE_INCOMPLETE', ['当前半话未全部验收'], batch)
            if any(r.get('status') not in TERMINAL | {'PENDING', 'REPAIR_AUTHORIZED', 'IN_FLIGHT', 'GENERATED'} for r in current):
                return result('RESOLVE_HALF_HOLD', ['未知/暂停状态'], batch)
            if report1 and any(r.get('round_id') == 2 and r.get('status') in {'VISUAL_FAIL', 'CALL_FAILED', 'RESULT_UNKNOWN', 'CANCELLED'} for r in current):
                return result('STOP_DIAGNOSE', ['第二轮仍失败/异常，暂停诊断，保存在途返回'], batch, round_id=2)
            eligible = [r['panel_id'] for r in current[:cutoff] if r.get('status') in {'PENDING', 'REPAIR_AUTHORIZED'}
                        and all(d in checked_ids for d in shot_by_id[r['panel_id']]['generation_dependencies'])
                        and (report1 is None and r.get('status') == 'PENDING' and r.get('round_id', 1) == 1 or report1 is not None and r['panel_id'] in repair_ids and r.get('round_id') == 2)]
            active = any(r.get('status') == 'IN_FLIGHT' for r in current)
            round_id = 2 if repair_ids else 1
            if check == 'status':
                if eligible: return result('SUBMIT_READY_HALF_REQUESTS', batch=batch, eligible=eligible, round_id=round_id)
                if active: return result('COLLECT_INFLIGHT_RESULTS', batch=batch, round_id=round_id)
                if any(by_id[p].get('status') in {'VISUAL_FAIL', 'CALL_FAILED', 'RESULT_UNKNOWN', 'CANCELLED'} for p in batch['state_barriers']) and any(r.get('status') == 'PENDING' for r in current):
                    return result('STATE_FAILURE_HOLD', ['新状态校准图失败使后格未提交；先诊断校准状态，不要求虚假的完整半话汇总'], batch, round_id=round_id)
                if any(r.get('status') == 'PENDING' and any(by_id[d].get('status') in {'VISUAL_FAIL', 'CALL_FAILED', 'RESULT_UNKNOWN', 'CANCELLED'} for d in shot_by_id[r['panel_id']]['generation_dependencies']) for r in current):
                    return result('DEPENDENCY_FAILURE_HOLD', ['前置实图失败导致后格未提交；先诊断依赖链，不虚构完整批次或失败数'], batch, round_id=round_id)
                if report1 is not None and repair_ids and any(by_id[p].get('round_id') == 1 for p in repair_ids):
                    return result('PREPARE_CORRECTION', batch=batch, eligible=repair_ids, round_id=2)
                return result('REVIEW_CORRECTION' if repair_ids else 'REVIEW_HALF_BATCH', batch=batch, round_id=round_id)
            if requested not in ids: return result('SOURCE_HALF_HOLD', ['只允许当前半话'], batch, eligible, round_id)
            if requested not in eligible: return result('DEPENDENCY_OR_RESULT_HOLD', ['依赖未满足、在途、未审或修正尚未授权'], batch, eligible, round_id)
            record = by_id[requested]
            if not record.get('attempt_id') or type(record.get('round_id')) is not int or record['round_id'] != round_id:
                return result('ROUND_HOLD', ['新请求须有准确轮次与唯一attempt_id'], batch, eligible, round_id)
            errors = input_errors(state, root, record, shot_by_id[requested], basis, by_id)
            packet = read(checked_file(root, record['package_manifest']))
            if type(packet.get('round_context', {}).get('round_id')) is not int or packet.get('round_context') != {'batch_id': batch['batch_id'], 'round_id': round_id, 'attempt_id': record['attempt_id']}:
                errors.append('执行包轮次/尝试/半话归属不一致')
            if round_id == 1 and packet['panels'][0].get('operation') == 'repair':
                errors.append('首轮不能提交返修包绕过二轮门禁')
            if round_id == 2:
                panel = packet['panels'][0]
                if record.get('status') != 'REPAIR_AUTHORIZED' or panel.get('operation') != 'repair' or any(line not in panel.get('prompt', '') for line in constraints[requested]):
                    errors.append('第二轮须授权定向修正、声明repair并将诊断约束写进实际prompt')
            return result('INPUT_HOLD' if errors else 'READY_FOR_HALF_PANEL', errors, batch, eligible, round_id)
        if check == 'generate': return result('EPISODE_COMPLETE', ['本话无待生成格'])
        if 'parallel_context' in state:
            errors = cross_episode_errors(state['parallel_context'])
            if errors: return result('WAIT_CROSS_EPISODE_REVIEW', errors)
        errors = approval_errors(gates.get('final'), root, [state['visual_basis'], state['shot_manifest'], *[r['output'] for r in records]], book, episode)
        return result('WAIT_FINAL_APPROVAL' if errors else 'READY_TO_PACKAGE', errors)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
        return result('INPUT_EVIDENCE_HOLD', [str(exc)])
