"""Scoped-half gate: freeze independent A/B artifacts, preserve real approvals and localize holds."""
from pathlib import Path
from codex_reference_contract import checked_file
from staged_workflow import POLICY, DONE, read, approval_errors
from rule_memory import binding_errors
from batch_round import MODE, snapshot, settings, report_errors, TERMINAL
from scoped_inputs import POLICY as OPT, STATE_DISPATCH, build_plan, half_view, approval_for, blocked_panels, validate_shots, global_hold, full_preparation


def evaluate_scoped(state, root, check='status', requested=None):
    from batch_workflow import completed_errors, input_errors, batch_review_errors, cross_episode_errors
    root=Path(root).resolve(); original=state
    def result(action, errors=(), batch=None, eligible=(), round_id=1, blocked_ids=()):
        return {'policy':POLICY,'execution_mode':MODE,'optimization_policy':OPT,
                'status':'PASS' if not errors and action in {'READY_FOR_HALF_PANEL','READY_TO_PACKAGE','READY_FOR_CROSS_REVIEW'} else 'HOLD',
                'next_action':action,'batch_id':(batch or {}).get('batch_id'),'batch_panel_ids':(batch or {}).get('panel_ids',[]),
                'round_id':round_id,'eligible_panel_ids':list(eligible),'blocked_panel_ids':sorted(blocked_ids),
                'cursor':requested,'errors':list(errors),'user_acceptance':'NOT_GRANTED_BY_SCRIPT'}
    try:
        from execution_contract import state_errors
        errors=state_errors(state,root)
        if errors:return result('EXECUTION_CONTRACT_HOLD',errors)
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
        if plan!=build_plan(state,source):return result('REBUILD_BATCH_PLAN',['稳定半话计划与原稿不一致'])
        records=state.get('panels',[])
        if [r.get('panel_id') for r in records]!=order:return result('COMPLETE_INPUT_AUDIT',['完整逐格进度与源序不一致'])
        whole=full_preparation(original)
        from panel_readiness import enabled as scoped_preparation,report as readiness_report
        readiness=readiness_report(original,root) if scoped_preparation(original) else None
        if readiness and readiness['global_errors']:return result('GLOBAL_PREPARATION_HOLD',readiness['global_errors'])
        by_id={r['panel_id']:r for r in records};shot_by_id={};checked_ids=set();previous=[];seen=set();all_refs=[]
        for bidx, window in enumerate(plan['batches']):
            bid=window['batch_id'];ids=window['panel_ids'];current=[by_id[p] for p in ids]
            try:state=half_view(original,bid)
            except ValueError as exc:return result('WAIT_EPISODE_INPUT' if whole else 'WAIT_HALF_INPUT',[str(exc)],window)
            basis=read(checked_file(root,state['visual_basis']));shots=read(checked_file(root,state['shot_manifest']))
            if basis.get('book_id')!=book or basis.get('episode_id')!=episode or not basis.get('reference_files'):
                return result('COMPLETE_EPISODE_INPUT' if whole else 'COMPLETE_HALF_INPUT',['视觉基准归属/参考缺失'],window)
            for ref in basis['reference_files']:checked_file(root,ref)
            errors=binding_errors(state,shots=shots)
            if errors:return result('MEMORY_HOLD',errors,window)
            raw=shots.get('panels',[]);blocked,hold_reasons=blocked_panels(original.get('holds'),order,window,raw)
            if readiness:
                blocked.update(set(readiness['blocked_panel_ids'])&set(ids))
                for pid in ids:hold_reasons.extend(readiness['blockers'].get(pid,[]))
            panels=validate_shots(state,source,window,shots,blocked)
            from frame_ratio_plan import panel_errors
            errors=panel_errors(state,root,panels)
            if errors:return result('RATIO_PLAN_HOLD',errors,window)
            from execution_contract import semantic_errors,extra_basis_refs
            errors=semantic_errors(state,root,window,set(readiness['blocked_panel_ids']) if readiness else blocked)
            if errors:return result('SEMANTIC_AUDIT_HOLD',errors,window,blocked_ids=blocked)
            ready_ids=[p for p in ids if p not in blocked]
            if not ready_ids:return result('SCOPED_HOLD',hold_reasons or ['本半话全部待解决'],window,blocked_ids=blocked)
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
            calibrations={}
            if state.get('execution_contract')=='comic_execution_v2':
                from calibration_repair import validate as validate_calibration
                for pid in ids:
                    if pid not in state.get('calibration_reviews',{}):continue
                    errors,data,old=validate_calibration(state,root,batch,shot_by_id,by_id,pid)
                    if errors:return result('CALIBRATION_REPAIR_HOLD',errors,batch,round_id=by_id[pid].get('round_id',1))
                    calibrations[pid]=(data,old)
            for r in current:
                if r['panel_id'] in blocked:continue
                if r.get('status') in DONE:
                    if r.get('round_id') not in (1,2) or not r.get('attempt_id'):return result('ROUND_HOLD',['合格图缺准确尝试/轮次'],batch)
                    errors=completed_errors(state,root,r,shot_by_id[r['panel_id']],basis,by_id)
                    if errors:
                        if not original.get('runtime'):
                            return result('REVIEW_HALF_PANEL',errors,batch,round_id=r['round_id'])
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
            if 'parallel_context' in state:
                from parallel_dispatch import context_errors
                errors=context_errors(state['parallel_context'],root,book,episode)
                if errors:return result('PARALLEL_HOLD',errors,batch)
            refs = state.get('round_reviews', {}).get(batch['batch_id'], {})
            report1 = read(checked_file(root, refs['1'])) if refs.get('1') else None
            repair_ids, constraints = [], {}
            if report1 is None and calibrations:
                if any(by_id[p].get('round_id')==2 and by_id[p].get('status') in {'VISUAL_FAIL','CALL_FAILED','RESULT_UNKNOWN','CANCELLED'} for p in calibrations):return result('STOP_DIAGNOSE',['校准第二轮失败/未知，保留原图与请求；不新增第三轮'],batch,round_id=2)
                pending=[p for p in calibrations if by_id[p].get('round_id')==2 and by_id[p].get('status')=='REPAIR_AUTHORIZED']
                if check=='generate' and requested in pending:
                    if any(d not in checked_ids for d in shot_by_id[requested]['generation_dependencies']):return result('DEPENDENCY_OR_RESULT_HOLD',['校准仍须真实前格实图依赖'],batch,round_id=2)
                    errors=input_errors(state,root,by_id[requested],shot_by_id[requested],basis,by_id)
                    return result('INPUT_HOLD' if errors else 'READY_FOR_HALF_PANEL',errors,batch,pending,2)
                if check=='status' and pending:return result('SUBMIT_CALIBRATION_CORRECTION',batch=batch,eligible=pending,round_id=2)
                initial=[p for p in calibrations if by_id[p].get('round_id')==1]
                if check=='status' and initial:return result('PREPARE_CALIBRATION_CORRECTION',batch=batch,eligible=initial,round_id=2)
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
            elif any((r.get('status') == 'REPAIR_AUTHORIZED' or r.get('attempt_history')) and r['panel_id'] not in calibrations for r in current):
                return result('ROUND_HOLD', ['返修须先完成首轮汇总并使用第二轮；不能伪装成首轮重试'], batch)
            elif any(r.get('round_id') == 2 and r['panel_id'] not in calibrations for r in current):
                return result('ROUND_HOLD', ['第二轮缺首轮真实QA汇总与诊断'], batch, round_id=2)
            if any(type(r.get('round_id', 1)) is not int or r.get('round_id', 1) not in (1, 2) for r in current):
                return result('STOP_DIAGNOSE', ['不允许第三轮自动调用'], batch)
            complete = all(r.get('status') in DONE for r in current)
            if complete and blocked:
                return result('SCOPED_HOLD', hold_reasons, batch, blocked_ids=blocked)
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
                    errors = approval_for(state, root, 'pilot', [state['visual_basis'], state['shot_manifest'], *extra_refs, *[r['output'] for r in current]], ids, original.get('gates', {}).get('pilot'))
                    if errors: return result('WAIT_FIRST_HALF_APPROVAL', errors, batch, round_id=2 if repair_ids else 1)
                previous = current; continue
            later = [by_id[p] for b in plan['batches'][bidx+1:] for p in b['panel_ids']]
            if any(r.get('status') != 'PENDING' for r in later): return result('OUT_OF_BATCH_HOLD', ['第二半话不能越过第一半话审查'], batch)
            if check == 'deliver': return result('EPISODE_INCOMPLETE', ['当前半话未全部验收'], batch)
            if any(r.get('status') not in TERMINAL | {'PENDING', 'REPAIR_AUTHORIZED', 'IN_FLIGHT', 'GENERATED'} for r in current):
                return result('RESOLVE_HALF_HOLD', ['未知/暂停状态'], batch)
            if report1 and any(r.get('round_id') == 2 and r.get('status') in {'VISUAL_FAIL', 'CALL_FAILED', 'RESULT_UNKNOWN', 'CANCELLED'} for r in current):
                return result('STOP_DIAGNOSE', ['第二轮仍失败/异常，暂停诊断，保存在途返回'], batch, round_id=2)
            eligible = [r['panel_id'] for r in current if r['panel_id'] not in blocked and r.get('status') in {'PENDING', 'REPAIR_AUTHORIZED'}
                        and all(d in checked_ids for d in shot_by_id[r['panel_id']]['generation_dependencies'])
                        and (report1 is None and r.get('status') == 'PENDING' and r.get('round_id', 1) == 1 or report1 is not None and r['panel_id'] in repair_ids and r.get('round_id') == 2)]
            active = any(r.get('status') == 'IN_FLIGHT' for r in current)
            round_id = 2 if repair_ids else 1
            if check == 'status':
                if eligible and original.get('runtime'):
                    from production_runtime import package_review_errors
                    approved = [p for p in eligible if not package_review_errors(original,root,batch,by_id[p])]
                    if not approved:
                        return result('WAIT_GENERATION_PACKAGE_APPROVAL', ['当前就绪格须有准确生图包批准'], batch, eligible=eligible, round_id=round_id, blocked_ids=blocked)
                    eligible=approved
                if eligible: return result('SUBMIT_READY_HALF_REQUESTS', batch=batch, eligible=eligible, round_id=round_id, blocked_ids=blocked)
                if active: return result('COLLECT_INFLIGHT_RESULTS', batch=batch, round_id=round_id, blocked_ids=blocked)
                if blocked: return result('SCOPED_HOLD', hold_reasons or ['本半话局部状态待确认'], batch, round_id=round_id, blocked_ids=blocked)
                if any(by_id[p].get('status') in {'VISUAL_FAIL', 'CALL_FAILED', 'RESULT_UNKNOWN', 'CANCELLED'} for p in hard_barrier_ids) and any(r.get('status') == 'PENDING' for r in current):
                    return result('STATE_FAILURE_HOLD', ['新状态校准图失败使后格未提交；先诊断校准状态，不要求虚假的完整半话汇总'], batch, round_id=round_id)
                if any(r.get('status') == 'PENDING' and any(by_id[d].get('status') in {'VISUAL_FAIL', 'CALL_FAILED', 'RESULT_UNKNOWN', 'CANCELLED'} for d in shot_by_id[r['panel_id']]['generation_dependencies']) for r in current):
                    return result('DEPENDENCY_FAILURE_HOLD', ['前置实图失败导致后格未提交；先诊断依赖链，不虚构完整批次或失败数'], batch, round_id=round_id)
                if report1 is not None and repair_ids and any(by_id[p].get('round_id') == 1 for p in repair_ids):
                    return result('PREPARE_CORRECTION', batch=batch, eligible=repair_ids, round_id=2)
                return result('REVIEW_CORRECTION' if repair_ids else 'REVIEW_HALF_BATCH', batch=batch, round_id=round_id)
            def check_one(pid):
                try:
                    if pid not in ids: return result('SOURCE_HALF_HOLD', ['只允许当前半话'], batch, eligible, round_id)
                    if pid in blocked: return result('SCOPED_HOLD', hold_reasons or ['本格状态尚未确认'], batch, round_id=round_id, blocked_ids=blocked)
                    if pid not in eligible: return result('DEPENDENCY_OR_RESULT_HOLD', ['依赖未满足、在途、未审或修正尚未授权'], batch, eligible, round_id)
                    record = by_id[pid]
                    if not record.get('attempt_id') or type(record.get('round_id')) is not int or record['round_id'] != round_id:
                        return result('ROUND_HOLD', ['新请求须有准确轮次与唯一attempt_id'], batch, eligible, round_id)
                    from panel_readiness import review_context
                    with review_context(state,root,check=='candidate_batch'):
                        errors = input_errors(state, root, record, shot_by_id[pid], basis, by_id, candidate=check=='candidate_batch')
                    if check != 'candidate_batch':
                        from production_runtime import package_review_errors
                        errors.extend(package_review_errors(original, root, batch, record))
                    packet = read(checked_file(root, record['package_manifest']))
                    if type(packet.get('round_context', {}).get('round_id')) is not int or packet.get('round_context') != {'batch_id': batch['batch_id'], 'round_id': round_id, 'attempt_id': record['attempt_id']}:
                        errors.append('执行包轮次/尝试/半话归属不一致')
                    if round_id == 1 and packet['panels'][0].get('operation') == 'repair':
                        errors.append('首轮不能提交返修包绕过二轮门禁')
                    if round_id == 2:
                        panel = packet['panels'][0]
                        if record.get('status') != 'REPAIR_AUTHORIZED' or panel.get('operation') != 'repair' or any(line not in panel.get('prompt', '') for line in constraints[pid]):
                            errors.append('第二轮须授权定向修正、声明repair并将诊断约束写进实际prompt')
                    return result('INPUT_HOLD' if errors else 'READY_FOR_HALF_PANEL', errors, batch, eligible, round_id)
                except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
                    return result('INPUT_EVIDENCE_HOLD', [str(exc)], batch, round_id=round_id)
            if check in {'generate_batch', 'candidate_batch'}:
                selection = eligible if requested is None else requested
                if not isinstance(selection, list) or any(not isinstance(p, str) for p in selection) or len(selection) != len(set(selection)):
                    return result('SOURCE_HALF_HOLD', ['批量格号须为不重复清单'], batch)
                reports = [{'panel_id': pid, **check_one(pid)} for pid in selection]
                ready = [r['panel_id'] for r in reports if r['status'] == 'PASS']
                value = result('READY_FOR_HALF_PANEL' if ready else 'INPUT_HOLD', batch=batch, eligible=ready, round_id=round_id, blocked_ids=blocked)
                if check == 'candidate_batch':
                    value['dispatch_authorized'] = False
                    value['candidate_only'] = True
                value.update(status='READY' if reports and len(ready) == len(reports) else 'PARTIAL_READY' if ready else 'HOLD',
                             ready_panel_ids=ready, reports=reports)
                return value
            return check_one(requested)
        state=original
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
