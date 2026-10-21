"""Episode gate: one source-contiguous production scope with rolling repairs."""
from codex_reference_contract import resolve_path
from authority_updates import authority_scoped
import time
from pathlib import Path
from codex_reference_contract import checked_file
from staged_workflow import POLICY, DONE, read, approval_errors
from rule_memory import binding_errors
from batch_round import settings, TERMINAL
from scoped_inputs import EPISODE_MODE as MODE, EPISODE_POLICY as OPT, STATE_DISPATCH, build_plan, half_view, approval_for, blocked_panels, validate_shots, global_hold, full_preparation


@authority_scoped
def evaluate_episode(state, root, check='status', requested=None):
    """reservation_batch reuses status gates and checks only enough unreserved inputs.

    It grants no dispatch authority: receipts, final compile and submission checks
    remain separate. Other batch modes always check their complete requested set.
    """
    from codex_reference_contract import _READ_VIEW
    view = _READ_VIEW.get()
    if view is not None: view.authorize_check(check, requested)
    from batch_workflow import completed_errors, input_errors, batch_review_errors, cross_episode_errors
    started = time.perf_counter()
    root=resolve_path(Path(root)); original=state
    def result(action, errors=(), batch=None, eligible=(), round_id=1, blocked_ids=()):
        return {'policy':POLICY,'execution_mode':MODE,'optimization_policy':OPT,
                'status':'PASS' if not errors and action in {'READY_FOR_EPISODE_PANEL','READY_TO_PACKAGE','READY_FOR_CROSS_REVIEW'} else 'HOLD',
                'next_action':action,'batch_id':(batch or {}).get('batch_id'),'batch_panel_ids':(batch or {}).get('panel_ids',[]),
                'round_id':round_id,'eligible_panel_ids':list(eligible),'blocked_panel_ids':sorted(blocked_ids),
                'cursor':requested,'errors':list(errors),'user_acceptance':'NOT_GRANTED_BY_SCRIPT'}
    try:
        reserving = check == 'reservation_batch'
        if reserving:
            if (not isinstance(requested, dict) or type(requested.get('limit')) is not int
                    or requested['limit'] < 1 or not isinstance(requested.get('excluded'), list)
                    or any(not isinstance(pid, str) for pid in requested['excluded'])):
                return result('SOURCE_EPISODE_HOLD', ['领取选集须有正整数limit和excluded格号清单'])
        from execution_contract import state_errors
        errors=state_errors(state,root)
        if errors:return result('EXECUTION_CONTRACT_HOLD',errors)
        from production_decisions import enabled as first_batch, priority as production_priority
        if first_batch(state) and check == 'deliver':
            if state.get('cancelled'): return result('CANCELLED', ['用户取消；不能自动恢复'])
            from panel_delivery import gate
            return gate(state, root)
        book,episode=state.get('book_id'),state.get('episode_id')
        if state.get('policy')!=POLICY or state.get('execution_mode')!=MODE or state.get('optimization_policy')!=OPT or not book or not episode:
            return result('COMPLETE_INPUT_AUDIT',['流程/书话/优化策略缺失'])
        settings(state)
        if state.get('cancelled'):return result('CANCELLED',['用户取消；不能自动恢复'])
        if global_hold(state.get('holds')):return result('RESOLVE_HOLD',state['holds'])
        checked_file(root,state['source_script']);source=read(checked_file(root,state['source_snapshot']));order=source.get('panel_ids')
        if not isinstance(order,list) or not order or len(set(order))!=len(order) or source.get('source_sha256')!=state['source_script']['sha256'] or set(source.get('locked_scripts',{}))!=set(order):
            return result('COMPLETE_INPUT_AUDIT',['源格序/锁定原文/源文件版本无效'])
        plan=read(checked_file(root,state['batch_plan']))
        if plan!=build_plan(state,source):return result('REBUILD_BATCH_PLAN',['整话计划与原稿不一致'])
        records=state.get('panels',[])
        if [r.get('panel_id') for r in records]!=order:return result('COMPLETE_INPUT_AUDIT',['完整逐格进度与源序不一致'])
        whole=full_preparation(original)
        from panel_readiness import enabled as scoped_preparation,report as readiness_report
        readiness=readiness_report(original,root) if scoped_preparation(original) else None
        if readiness and readiness['global_errors']:return result('GLOBAL_PREPARATION_HOLD',readiness['global_errors'])
        by_id={r['panel_id']:r for r in records};shot_by_id={};checked_ids=set();previous=[];seen=set();all_refs=[]
        for bidx, window in enumerate(plan['batches']):
            bid=window['batch_id'];ids=window['panel_ids'];current=[by_id[p] for p in ids]
            try:
                from scoped_inputs import resolve_context
                context=resolve_context(original,root,bid)
                state=context['state']
            except ValueError as exc:return result('WAIT_EPISODE_INPUT' if whole else 'WAIT_HALF_INPUT',[str(exc)],window)
            basis=read(checked_file(root,state['visual_basis']));shots=read(checked_file(root,state['shot_manifest']))
            if basis.get('book_id')!=book or basis.get('episode_id')!=episode or not basis.get('reference_files'):
                return result('COMPLETE_EPISODE_INPUT' if whole else 'COMPLETE_HALF_INPUT',['视觉基准归属/参考缺失'],window)
            for ref in basis['reference_files']:checked_file(root,ref)
            errors=binding_errors(state,shots=shots)
            if errors:return result('MEMORY_HOLD',errors,window)
            from scoped_inputs import generation_holds, comparison_holds
            raw=shots.get('panels',[]);blocked,hold_reasons=blocked_panels(generation_holds(original),order,window,raw)
            if readiness:
                blocked.update(set(readiness['blocked_panel_ids'])&set(ids))
                for pid in ids:hold_reasons.extend(readiness['blockers'].get(pid,[]))
            panels=validate_shots(state,source,window,shots,blocked)
            from image_risk_guards import shot_errors as risk_shot_errors
            # Readiness-enabled runs classify local risk errors and propagate
            # their actual design/image dependencies before this fallback.
            risk_errors=[] if readiness else [f"{p['panel_id']}:{e}" for p in panels if p['panel_id'] not in blocked for e in risk_shot_errors(p)]
            if risk_errors:return result('SHOT_RISK_HOLD',risk_errors,window)
            from frame_ratio_plan import panel_errors
            errors=panel_errors(state,root,panels)
            if errors:return result('RATIO_PLAN_HOLD',errors,window)
            from execution_contract import semantic_errors,extra_basis_refs
            errors=semantic_errors(state,root,window,set(readiness['blocked_panel_ids']) if readiness else blocked)
            if errors:return result('SEMANTIC_AUDIT_HOLD',errors,window,blocked_ids=blocked)
            ready_ids=[p for p in ids if p not in blocked]
            if not ready_ids:return result('SCOPED_HOLD',hold_reasons or ['本话全部待解决'],window,blocked_ids=blocked)
            gates=original.get('gates',{}) if whole else original.get('half_gates',{}).get(bid,{})
            extra_refs=extra_basis_refs(state)
            if readiness:
                for pid in ready_ids:
                    errors=approval_for(state,root,'visual_basis',[state['source_script'],state['source_snapshot'],state['visual_basis']],[pid],gates.get('visual_basis'))
                    phase='visual_basis'
                    if not errors and check!='candidate_batch':
                        phase='shot_design'
                        errors=approval_for(state,root,phase,[state['visual_basis'],state['shot_manifest'],*extra_refs],[pid],gates.get(phase))
                    if errors:
                        blocked.add(pid);hold_reasons.append({'panel_id':pid,'reason':'WAIT_REAL_APPROVAL','phase':phase,'errors':errors})
            else:
                approval_ids=order if whole else ready_ids
                errors=approval_for(state,root,'visual_basis',[state['source_script'],state['source_snapshot'],state['visual_basis']],approval_ids,gates.get('visual_basis'))
                if errors:return result('WAIT_EPISODE_VISUAL_APPROVAL' if whole else 'WAIT_HALF_VISUAL_APPROVAL',errors,window,blocked_ids=blocked)
                errors=approval_for(state,root,'shot_design',[state['visual_basis'],state['shot_manifest'],*extra_refs],approval_ids,gates.get('shot_design'))
                if errors and check != 'candidate_batch':return result('WAIT_EPISODE_SHOT_APPROVAL' if whole else 'WAIT_HALF_SHOT_APPROVAL',errors,window,blocked_ids=blocked)
            all_refs.extend([state['visual_basis'],state['shot_manifest'],*extra_refs]);shot_by_id.update({p['panel_id']:p for p in panels})
            barriers=[]
            for p in panels:
                if p['panel_id'] in blocked:continue
                new=set(p['visual_state_keys'])-seen
                if p['requires_state_review'] or p.get('calibration_anchor') or (p['panel_id']!=order[0] and new):barriers.append((p['panel_id'],new or set(p['visual_state_keys'])))
                seen.update(p['visual_state_keys'])
            batch={**window,'state_barriers':[p for p,_ in barriers]}
            parallel_ordinary=original.get('state_dispatch_policy')==STATE_DISPATCH
            hard_barrier_ids={pid for pid,_ in barriers if not parallel_ordinary or
                shot_by_id[pid].get('requires_state_review') or shot_by_id[pid].get('calibration_anchor') or
                shot_by_id[pid].get('state_review_policy','user_required')=='user_required'}
            for r in current:
                if r['panel_id'] in blocked:continue
                if r.get('status') in DONE:
                    if r.get('round_id') not in (1,2) or not r.get('attempt_id'):return result('ROUND_HOLD',['合格图缺准确尝试/轮次'],batch)
                    errors=completed_errors(state,root,r,shot_by_id[r['panel_id']],basis,by_id)
                    if errors:
                        if not original.get('runtime'):
                            return result('REVIEW_EPISODE_PANEL',errors,batch,round_id=r['round_id'])
                        blocked.add(r['panel_id'])
                        hold_reasons.append({'panel_id':r['panel_id'],'reason':'RECORDED_QA_INVALID','errors':errors})
                        continue
                    checked_ids.add(r['panel_id'])
            for pid,keys in barriers:
                r=by_id[pid]
                if pid not in hard_barrier_ids:
                    # Ordinary first-state images remain QA/calibration anchors, but
                    # their approved followers may be submitted before their return.
                    continue
                approved=False
                if pid in checked_ids:
                    merge=shot_by_id[pid].get('state_review_policy','user_required')
                    if merge in {'merge_into_C','merge_into_D'}:approved=True
                    else:
                        errors=approval_for(state,root,'state_review',[state['visual_basis'],state['shot_manifest'],r['output']],[pid],original.get('state_reviews',{}).get(pid))
                        approved=not errors
                if approved:continue
                if pid in checked_ids:
                    blocked.add(pid);hold_reasons.append({'panel_id':pid,'state_keys':sorted(keys),'reason':'WAIT_NEW_STATE_APPROVAL','review_policy':'user_required'})
                # Only subsequent users of this state (plus real dependencies) wait.
                for later in panels[ids.index(pid)+1:]:
                    if keys.intersection(later.get('visual_state_keys',[])):blocked.add(later['panel_id'])
                if r.get('status') in {'VISUAL_FAIL','CALL_FAILED','RESULT_UNKNOWN','CANCELLED'}:
                    blocked.add(pid);hold_reasons.append({'panel_id':pid,'reason':'STATE_FAILURE_HOLD'})
            changed=True
            while changed:
                changed=False
                for p in panels:
                    if p['panel_id'] not in blocked and set(p.get('generation_dependencies',[])).intersection(blocked):blocked.add(p['panel_id']);changed=True
            if (state.get('runtime',{}).get('dispatch_policy')=='episode_slot_lease_v1'
                    and 'parallel_context' not in state and check not in {'candidate_batch','input_audit_batch'}):
                return result('WAIT_CAPACITY_ASSIGNMENT',['租约模式尚未绑定真实调度上下文'],batch)
            if 'parallel_context' in state:
                from parallel_dispatch import context_errors
                errors=context_errors(state['parallel_context'],root,book,episode)
                if errors:return result('PARALLEL_HOLD',errors,batch)
            from episode_repair import repair_errors, systemic_errors
            systemic = systemic_errors(original, current, root)
            # Full-scope round/history checks protect the call budget, including
            # blocked/excluded rows beyond the requested reservation count.
            for r in current:
                if r.get('round_id') == 2:
                    errors = repair_errors(original, root, r)
                    if errors:return result('ROLLING_REPAIR_HOLD', errors, batch)
                elif r.get('attempt_history') or r.get('status') == 'REPAIR_AUTHORIZED':
                    return result('ROUND_HOLD', ['返修不得伪装成首轮'], batch)
            if any(type(r.get('round_id', 1)) is not int or r.get('round_id', 1) not in (1, 2) for r in current):
                return result('STOP_DIAGNOSE', ['不允许第三轮自动调用'], batch)
            complete = all(r.get('status') in DONE for r in current)
            if first_batch(original) and check == 'status' and all(r.get('status') in TERMINAL for r in current):
                from production_decisions import selected
                undecided = []
                for row in current:
                    if row.get('status') in {'CALL_FAILED','RESULT_UNKNOWN','CANCELLED'}: continue
                    try:
                        _, d, _, _ = selected(root, row)
                        if d['action'] not in {'complete','defer_manual','stop_diagnose'}:
                            undecided.append(row['panel_id'])
                    except (ValueError, KeyError, TypeError, OSError):
                        undecided.append(row['panel_id'])
                if not undecided:
                    if original.get('delivery_review'):
                        from panel_delivery import gate
                        return gate(original, root)
                    return result('PREPARE_FIRST_BATCH_HANDOFF', batch=batch)
                if complete:
                    return result('PREPARE_PRODUCTION_DECISIONS', ['已审图须登记采用版本和问题去向'], batch=batch)

            if complete and blocked:
                if any(isinstance(h,dict) and h.get('reason')=='WAIT_NEW_STATE_APPROVAL' for h in hold_reasons):
                    return result('WAIT_NEW_STATE_APPROVAL',hold_reasons,batch,blocked_ids=blocked)
                return result('SCOPED_HOLD', hold_reasons, batch, blocked_ids=blocked)
            if complete:
                errors = batch_review_errors(state, root, batch, current, previous)
                if errors: return result('REVIEW_EPISODE_CONTINUITY', errors, batch)
                previous = current; continue
            if check == 'deliver': return result('EPISODE_INCOMPLETE', ['整话仍有未验收格'], batch)
            if any(r.get('status') not in TERMINAL | {'PENDING', 'REPAIR_AUTHORIZED', 'IN_FLIGHT', 'GENERATED'} for r in current):
                return result('RESOLVE_EPISODE_HOLD', ['未知/暂停状态'], batch)
            eligible = [r['panel_id'] for r in current if r['panel_id'] not in blocked and r.get('status') in {'PENDING', 'REPAIR_AUTHORIZED'}
                        and all(d in checked_ids for d in shot_by_id[r['panel_id']]['generation_dependencies'])
                        and (r.get('status') == 'PENDING' and r.get('round_id', 1) == 1 or r.get('status') == 'REPAIR_AUTHORIZED' and r.get('round_id') == 2 and not systemic)]
            active = any(r.get('status') == 'IN_FLIGHT' for r in current)
            round_id = 1
            if reserving:
                excluded = set(requested['excluded'])
                eligible = [pid for pid in eligible if pid not in excluded]
            if first_batch(original):
                eligible.sort(key=lambda pid: production_priority(original, by_id[pid], panels, root))
            if check == 'status' or reserving:
                if eligible and original.get('runtime'):
                    from production_runtime import package_review_errors
                    approved = [p for p in eligible if not package_review_errors(original,root,batch,by_id[p])]
                    if not approved:
                        return result('WAIT_GENERATION_PACKAGE_APPROVAL', ['当前就绪格须有准确生图包批准'], batch, eligible=eligible, round_id=round_id, blocked_ids=blocked)
                    eligible=approved
                if eligible and not reserving:
                    value=result('SUBMIT_READY_EPISODE_REQUESTS', batch=batch, eligible=eligible, blocked_ids=blocked)
                    value['pending_state_review_panel_ids']=[h['panel_id'] for h in hold_reasons if isinstance(h,dict) and h.get('reason')=='WAIT_NEW_STATE_APPROVAL']
                    return value
                if not eligible:
                    if active: return result('COLLECT_INFLIGHT_RESULTS', batch=batch, round_id=round_id, blocked_ids=blocked)
                    if systemic: return result('DIAGNOSE_COMMON_CAUSE', systemic, batch, blocked_ids=blocked)
                    if blocked:
                        action='WAIT_NEW_STATE_APPROVAL' if any(isinstance(h,dict) and h.get('reason')=='WAIT_NEW_STATE_APPROVAL' for h in hold_reasons) else 'SCOPED_HOLD'
                        return result(action, hold_reasons or ['本话局部状态待确认'], batch, blocked_ids=blocked)
                    if any(by_id[p].get('status') in {'VISUAL_FAIL', 'CALL_FAILED', 'RESULT_UNKNOWN', 'CANCELLED'} for p in hard_barrier_ids) and any(r.get('status') == 'PENDING' for r in current):
                        return result('STATE_FAILURE_HOLD', ['新状态校准图失败使后格未提交；先诊断校准状态，不要求虚假的完整整话汇总'], batch, round_id=round_id)
                    if any(r.get('status') == 'PENDING' and any(by_id[d].get('status') in {'VISUAL_FAIL', 'CALL_FAILED', 'RESULT_UNKNOWN', 'CANCELLED'} for d in shot_by_id[r['panel_id']]['generation_dependencies']) for r in current):
                        return result('DEPENDENCY_FAILURE_HOLD', ['前置实图失败导致后格未提交；先诊断依赖链，不虚构完整批次或失败数'], batch, round_id=round_id)
                    if first_batch(original):
                        from production_decisions import selected
                        settled = []
                        for row in current:
                            try:
                                _, decision, _, _ = selected(root, row)
                                if decision['action'] in {'complete', 'defer_manual', 'stop_diagnose'}:
                                    settled.append(row['panel_id'])
                            except (ValueError, KeyError, TypeError, OSError):
                                pass
                        if len(settled) == len(current):
                            return result('PREPARE_FIRST_BATCH_HANDOFF', batch=batch)
                        pending = [r for r in current if r['panel_id'] not in settled]
                    else:
                        pending = current
                    if any(r.get('status') == 'VISUAL_FAIL' and r.get('round_id') == 1 for r in pending):
                        return result('PREPARE_ROLLING_REPAIR', batch=batch)
                    if any(r.get('round_id') == 2 and r.get('status') in {'VISUAL_FAIL','CALL_FAILED','RESULT_UNKNOWN','CANCELLED'} for r in current):
                        return result('STOP_DIAGNOSE', ['第二轮仍失败或结果未知；保留原尝试'], batch)
                    return result('REVIEW_PENDING_IMAGES', batch=batch)
            def check_one(pid):
                try:
                    if pid not in ids: return result('SOURCE_EPISODE_HOLD', ['只允许当前整话'], batch, eligible, round_id)
                    if pid in blocked: return result('SCOPED_HOLD', hold_reasons or ['本格状态尚未确认'], batch, round_id=round_id, blocked_ids=blocked)
                    if pid not in eligible: return result('DEPENDENCY_OR_RESULT_HOLD', ['依赖未满足、在途、未审或修正尚未授权'], batch, eligible, round_id)
                    record = by_id[pid]
                    local_round=record.get('round_id')
                    if not record.get('attempt_id') or type(local_round) is not int or local_round not in (1,2):
                        return result('ROUND_HOLD', ['新请求须有准确轮次与唯一attempt_id'], batch, eligible, round_id)
                    from panel_readiness import review_context
                    # Candidate input checks still traverse the complete real
                    # context and image dependencies; only other candidates
                    # may be deferred after enough ready inputs are found.
                    def validate_inputs():
                        with review_context(state,root,check=='candidate_batch' or reserving):
                            issues=input_errors(state,root,record,shot_by_id[pid],basis,by_id,
                                                candidate=check=='candidate_batch' or reserving,dispatch_audit=check=='input_audit_batch')
                        if check!='candidate_batch' and not reserving:
                            from production_runtime import package_review_errors
                            issues.extend(package_review_errors(original,root,batch,record))
                        return issues
                    if check=='input_audit_batch':
                        from audit_cache import derived,content_key
                        import hashlib
                        key=hashlib.sha256(content_key([str(root),state,original,batch,record,shot_by_id[pid],basis,by_id]).encode()).hexdigest()
                        errors=list(derived('receiver_panel_inputs',key,validate_inputs,accept=lambda issues:not issues))
                    else:errors=validate_inputs()
                    packet = read(checked_file(root, record['package_manifest']))
                    if type(packet.get('round_context', {}).get('round_id')) is not int or packet.get('round_context') != {'batch_id': batch['batch_id'], 'round_id': local_round, 'attempt_id': record['attempt_id']}:
                        errors.append('执行包轮次/尝试/整话归属不一致')
                    if local_round == 1 and packet['panels'][0].get('operation') == 'repair':
                        errors.append('首轮不能提交返修包绕过二轮门禁')
                    if local_round == 2:
                        panel = packet['panels'][0]
                        from codex_reference_contract import read_json
                        auth=read_json(checked_file(root, original['repair_authorizations'][pid]))
                        if record.get('status') != 'REPAIR_AUTHORIZED' or panel.get('operation') != 'repair' or any(line not in panel.get('prompt', '') for line in auth['repair_constraints']):
                            errors.append('第二轮须授权定向修正、声明repair并将诊断约束写进实际prompt')
                    return result('INPUT_HOLD' if errors else 'READY_FOR_EPISODE_PANEL', errors, batch, eligible, local_round)
                except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
                    return result('INPUT_EVIDENCE_HOLD', [str(exc)], batch, round_id=round_id)
            if check in {'generate_batch', 'candidate_batch', 'input_audit_batch'} or reserving:
                selection = eligible if requested is None or reserving else requested
                if not isinstance(selection, list) or any(not isinstance(p, str) for p in selection) or len(selection) != len(set(selection)):
                    return result('SOURCE_EPISODE_HOLD', ['批量格号须为不重复清单'], batch)
                from audit_progress import mark
                inputs_started = time.perf_counter()
                reports=[]; ready=[]; ready_observed={}
                for index,pid in enumerate(selection):
                    mark(panel_id=pid,completed=index,total=len(selection))
                    reports.append({'panel_id':pid,**check_one(pid)})
                    mark(panel_id=pid,completed=index+1,total=len(selection))
                    if reports[-1]['status'] == 'PASS':
                        ready.append(pid)
                        if reserving: ready_observed[pid] = time.perf_counter()
                    if reserving and len(ready) >= requested['limit']: break
                value = result('READY_FOR_EPISODE_PANEL' if ready else 'INPUT_HOLD', batch=batch, eligible=ready, blocked_ids=blocked)
                if check=='input_audit_batch':
                    value.update(dispatch_authorized=False,input_audit_only=True,audit_policy='receiver_input_audit_v1')
                if check == 'candidate_batch' or reserving:
                    value['dispatch_authorized'] = False
                    value['candidate_only'] = True
                if reserving:
                    value.update(reservation_preflight_only=True, candidate_count=len(selection),
                                 _ready_observed_monotonic=ready_observed,
                                 checked_panel_count=len(reports), deferred_panel_ids=selection[len(reports):],
                                 common_check_seconds=round(inputs_started-started,6),
                                 panel_check_seconds=round(time.perf_counter()-inputs_started,6))
                value.update(status='READY' if reports and len(ready) == len(reports) else 'PARTIAL_READY' if ready else 'HOLD',
                             ready_panel_ids=ready, reports=reports)
                return value
            return check_one(requested)
        state=original
        from scoped_inputs import comparison_holds
        pending_comparison=comparison_holds(state)
        if pending_comparison:return result('WAIT_EPISODE_CONTINUITY',pending_comparison)
        from frame_ratio_plan import actual_errors
        errors=actual_errors(state,root,records)
        if errors:return result('IMAGE_RATIO_HOLD',errors)
        if check=='generate':return result('EPISODE_COMPLETE',['本话无待生成格'])
        if check=='scope_complete':return result('READY_FOR_CROSS_REVIEW')
        if 'parallel_context' in state:
            errors=cross_episode_errors(state['parallel_context'])
            if errors:return result('WAIT_CROSS_EPISODE_REVIEW',errors)
        errors=approval_for(state,root,'final',[state['source_script'],state['source_snapshot'],*all_refs,*[r['output'] for r in records]],order,state.get('gates',{}).get('final'))
        return result('WAIT_FINAL_APPROVAL' if errors else 'READY_TO_PACKAGE',errors)
    except (OSError,ValueError,TypeError,KeyError,AttributeError,IndexError) as exc:
        return result('INPUT_EVIDENCE_HOLD',[str(exc)])
