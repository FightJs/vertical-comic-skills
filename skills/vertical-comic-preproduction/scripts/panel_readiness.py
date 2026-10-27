"""Scoped preparation and literal approval reuse; never writes or grants approval."""
from codex_reference_contract import resolve_path
from pathlib import Path
import hashlib,json,copy
from contextvars import ContextVar
from contextlib import contextmanager
from codex_reference_contract import checked_file,read_json,read_json_readonly,digest
from audit_cache import derived,content_key
from authority_updates import authority_scoped, revocation_errors, revocation_token

POLICY='panel_readiness_v1'
_REVIEW=ContextVar('comic_design_review',default=None)

@contextmanager
def review_context(state,root,candidate=False):
    token=_REVIEW.set((state, resolve_path(Path(root))) if candidate and enabled(state) else None)
    try:yield
    finally:_REVIEW.reset(token)

def review_scope():
    active = _REVIEW.get()
    if active is None:return None
    state, root = active
    return [str(root), {k:state.get(k) for k in (
        'episode_id','source_script','source_snapshot','visual_basis','shot_manifest',
        'task_context','continuity_sources','episode_order','preparation_authorization','parallel_context')}]


def candidate_source(source):
    active=_REVIEW.get()
    if active is None:return False
    state,root=active
    if resolve_path(Path(source.get('root', '')))==root and source.get('episode_id')==state['episode_id']:
        return all(source.get(k)==state.get(k) for k in ('source_script','source_snapshot','visual_basis','shot_manifest'))
    # Only B may be pending, and only inside offline review of the same task.
    # Source hashes, A, source order and continuity checks still run normally.
    from continuity_context import runtime_source_state, registered_source
    from task_context import state_errors, preparation_errors
    normalized = {k:v for k,v in source.items() if k != 'root_mode'}
    registered = registered_source(state, root, normalized, root)
    if not registered or source.get('approval_resolution') != 'source_runtime_gates_v1':
        return False
    if state.get('parallel_context') or not state.get('task_context') or state_errors(state, root):
        return False
    other_root = Path(source['root'])
    other = runtime_source_state(source, other_root, state['book_id'])
    if (other.get('parallel_context') or not enabled(other) or
            other.get('task_context') != state['task_context'] or state_errors(other, other_root)):
        return False
    order = state.get('episode_order', [])
    if (other.get('episode_order') != order or source['episode_id'] not in order or
            state['episode_id'] not in order or order.index(source['episode_id']) >= order.index(state['episode_id'])):
        return False
    for owner, base in ((state, root), (other, other_root)):
        ids = read_json_readonly(checked_file(base, owner['source_snapshot']))['panel_ids']
        if preparation_errors(owner, base, ids):return False
    return True

def enabled(state):return state.get('readiness_policy')==POLICY

def binding_errors(state,manifest):
    if enabled(state) and manifest.get('readiness_policy')!=POLICY:return ['READINESS_HOLD:执行依据缺少相同逐格放行策略']
    return []

def design_signature(panel):
    # These are observations, holds or call receipts, not creative authority.
    ignored={'generation_execution','memory_applications','status','hold_reasons','boundary_comparison','inspection_plan','planning_notes'}
    value={k:v for k,v in panel.items() if k not in ignored}
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def collection_summary(root,ref):
    path=checked_file(Path(root),ref)
    def compute():
        value=read_json_readonly(path)
        panels=value.get('panels')
        if not isinstance(panels,list):return None
        by_id={p['panel_id']:design_signature(p) for p in panels}
        if len(by_id)!=len(panels):return None
        ignored={'panels','continuity_context','status','hold_reasons'}
        return {'header':{k:v for k,v in value.items() if k not in ignored},
                'book_id':value.get('book_id'),'episode_id':value.get('episode_id'),'signatures':by_id}
    return derived('collection_summary',(str(path),digest(path)),compute)

def compatible_collection(root,old_ref,new_ref,ids,book,episode):
    """Compare original frozen rows and all shared design headers; no re-signing."""
    if old_ref==new_ref:return True
    try:
        def compare():
            old=collection_summary(root,old_ref);new=collection_summary(root,new_ref)
            if old is None or new is None:return None
            if new['book_id'] not in (None,book) or new['episode_id'] not in (None,episode):return None
            if old['header']!=new['header']:return None
            a=old['signatures'];b=new['signatures']
            return {pid:a[pid]==b[pid] for pid in a if pid in b}
        matches=derived('collection_pair', content_key([str(resolve_path(Path(root))), old_ref, new_ref, book, episode]), compare)
        return matches is not None and all(matches.get(pid,False) for pid in ids)
    except (OSError,ValueError,TypeError,KeyError):return False

def artifacts_covered(state,root,proof,artifacts,ids,phase=None):
    if revocation_errors(proof, state['book_id'], state['episode_id']): return False
    key=content_key([str(resolve_path(Path(root))), state['book_id'], state['episode_id'], state.get('shot_manifest'), proof, artifacts, ids, phase, revocation_token()])
    return derived('approval_coverage',key,
                   lambda:_artifacts_covered(state,root,proof,artifacts,ids,phase),accept=lambda value:True)

def _artifacts_covered(state,root,proof,artifacts,ids,phase=None):
    """Narrow technical reuse of exact approved rows from preserved source files."""
    from staged_workflow import approval_errors
    bound=proof.get('artifacts',[])
    if approval_errors(proof,root,bound,state['book_id'],state['episode_id'],phase=phase,panel_ids=ids):return False
    def covered(ref):
        if ref in bound:return True
        value=read_json_readonly(checked_file(Path(root),ref))
        if value.get('policy')=='semantic_audit_v1':
            return value.get('book_id')==state['book_id'] and value.get('episode_id')==state['episode_id'] and covered(value['visual_basis']) and covered(value['shot_manifest'])
        if ref==state.get('shot_manifest') or value.get('policy')=='content_balanced_ratios_v1':
            return any(compatible_collection(root,old,ref,ids,state['book_id'],state['episode_id']) for old in bound)
        # Keep source-ID adapter and exact original approvals supported.
        return not approval_errors(proof,root,[ref],state['book_id'],state['episode_id'],phase=phase,panel_ids=ids)
    try:return all(covered(ref) for ref in artifacts)
    except (OSError,ValueError,TypeError,KeyError,RecursionError):return False

def _approval_coverage_for(state,root,phase,artifacts,ids,direct=None,*,proofs=()):
    ids=tuple(ids)  # Preserve one-shot iterables for eligibility and missing-scope reporting.
    def indexed_candidates():
        candidates=[p for p in proofs if isinstance(p,dict)]
        if isinstance(direct,dict):candidates.append(direct)
        if state.get('approval_index'):
            index=read_json_readonly(checked_file(Path(root),state['approval_index']))
            if index.get('policy')!='approval_index_v1':return None
            for entry in index.get('entries',[]):
                if entry.get('phase')==phase and entry.get('book_id')==state['book_id'] and state['episode_id'] in entry.get('episode_ids',[]):
                    proof=read_json_readonly(checked_file(Path(root),entry['approval']))
                    candidates.append({**proof,'_lookup_panel_ids':entry.get('panel_ids',[])})
        scoped={};unscoped=[]
        for i,proof in enumerate(candidates):
            if (proof.get('review_event_id') or proof.get('source_kind')=='agent_decision') and proof.get('phase')!=phase:continue
            scope=proof.get('panel_ids')
            if phase=='visual_basis' and scope is None:
                names=proof.get('_lookup_panel_ids')
                if names is None:unscoped.append(i);continue
            elif isinstance(scope,list):names=scope
            else:continue
            for name in names:scoped.setdefault(name,[]).append(i)
        return {'proofs':candidates,'scoped':scoped,'unscoped':unscoped}
    key=content_key([str(resolve_path(Path(root))), state['book_id'], state['episode_id'], phase, state.get('approval_index'), direct, proofs])
    index=derived('approval_index',key,indexed_candidates)
    if index is None:return None
    # A proof usually covers many panels. Verify that proof's eligible scope
    # together instead of replaying the same file dependencies once per panel.
    # Both the original proof and the lookup entry still restrict the scope.
    eligible={}
    for pid in dict.fromkeys(ids):
        names={pid,state['episode_id']+'-'+pid}
        selected=set(index['unscoped'])
        for name in names:selected.update(index['scoped'].get(name,[]))
        for i in sorted(selected):
            proof=index['proofs'][i]
            if (proof.get('review_event_id') or proof.get('source_kind')=='agent_decision') and proof.get('phase')!=phase:continue
            scope=proof.get('panel_ids')
            if phase!='visual_basis' and (not isinstance(scope,list) or not names.intersection(scope)):continue
            if phase=='visual_basis' and scope is not None and not names.intersection(scope):continue
            if '_lookup_panel_ids' in proof and not names.intersection(proof['_lookup_panel_ids']):continue
            eligible.setdefault(i,[]).append(pid)
    covered=set()
    for i, scope in sorted(eligible.items()):
        pending=[pid for pid in scope if pid not in covered]
        if not pending:continue
        proof=index['proofs'][i]
        if artifacts_covered(state,root,proof,artifacts,pending,phase):
            covered.update(pending)
        elif len(pending)>1:
            # A revised collection can invalidate just one row, or different
            # preserved versions can cover different rows. Retain the original
            # per-panel fallback and never let one bad row block its siblings.
            for pid in pending:
                if artifacts_covered(state,root,proof,artifacts,[pid],phase):covered.add(pid)
    return tuple(covered)

def approval_errors_for(state,root,phase,artifacts,ids,direct=None,*,proofs=()):
    """Resolve one immutable coverage map, then query growing predecessor scopes.

    This is evidence coverage, never readiness or dispatch authorization. The
    existing grouped/per-row validator remains the sole producer of the map.
    """
    ids=tuple(ids)
    universe=ids
    ref=state.get('shot_manifest')
    if isinstance(ref,dict) and ref.get('path'):
        try:
            shots=read_json_readonly(checked_file(Path(root),ref))
            source_ids=[p['panel_id'] for p in shots.get('panels',[])]
            if source_ids and all(isinstance(pid,str) for pid in source_ids):
                # Preserve exact spellings: aliases are not additional authority.
                universe=tuple(dict.fromkeys(source_ids+list(ids)))
        except (OSError,ValueError,TypeError,KeyError):
            # The original validator still reports malformed/missing evidence.
            universe=ids
    key=content_key([str(resolve_path(Path(root))),state['book_id'],state['episode_id'],
                     ref,state.get('approval_index'),phase,artifacts,direct,proofs,
                     universe,revocation_token()])
    coverage=derived('approval_scope_map',key,
        lambda:_approval_coverage_for(state,root,phase,artifacts,universe,direct,proofs=proofs))
    if coverage is None:return ['批准索引版本错误']
    covered=set(coverage)
    missing=[pid for pid in ids if pid not in covered]
    return ['缺少原范围、原版本或未变条目适用的真实批准:'+','.join(missing)] if missing else []

def local_tags_manifest(manifest,panel):
    """An internal pair does not inherit the episode's preceding boundary pair."""
    if manifest.get('readiness_policy')!=POLICY:return manifest
    panels=manifest.get('panels',[])
    if panels and panel['panel_id']!=panels[0]['panel_id']:
        return {k:v for k,v in manifest.items() if k!='continuity_context'}
    return manifest

@authority_scoped
def report(state,root,*,include_execution=True):
    active=_REVIEW.get()
    scope=None if active is None else [active[0],str(active[1])]
    key=hashlib.sha256(content_key([str(resolve_path(Path(root))), state, scope, include_execution]).encode()).hexdigest()
    return copy.deepcopy(derived('preparation_report',key,lambda:_report(state,root,include_execution=include_execution),
                                 accept=lambda value:not value.get('global_errors')))

def _report(state,root,*,include_execution=True):
    """Return ready/reviewable/blocked rows; caller still runs full input gates."""
    source=read_json(checked_file(Path(root),state['source_snapshot']));order=source['panel_ids']
    path=checked_file(Path(root),state['shot_manifest']);shots=read_json(path)
    audit=read_json(checked_file(Path(root),state['semantic_audit']))
    expected={'book_id':state['book_id'],'episode_id':state['episode_id'],'source_snapshot':state['source_snapshot'],'visual_basis':state['visual_basis'],'shot_manifest':state['shot_manifest'],'panel_ids':order}
    errors=[]
    if any(shots.get(k)!=state.get(k) for k in ('book_id','episode_id','preparation_policy','readiness_policy')):errors.append('全话镜头归属或准备策略不一致')
    if audit.get('policy')!='semantic_audit_v1' or any(audit.get(k)!=v for k,v in expected.items()):errors.append('全话语义报告的书话、源稿或冻结版本错误')
    if [p.get('panel_id') for p in shots.get('panels',[])]!=order or [p.get('panel_id') for p in audit.get('panels',[])]!=order:errors.append('全话镜头/语义报告缺格、乱序或重复')
    if errors:
        from issue_disposition import summarize
        return {'issue_disposition':summarize(global_errors=errors),'global_errors':errors,'ready_for_review_ids':[],'prepared_panel_ids':[],'blocked_panel_ids':order,'blockers':{}}
    from scoped_inputs import blocked_panels, generation_holds, comparison_holds
    from execution_contract import semantic_checks
    from continuity_context import binding_errors as prior_binding,load_context
    raw=shots['panels'];by_id={p['panel_id']:p for p in raw};reviews={p['panel_id']:p for p in audit['panels']}
    planning_items=[]
    direct_holds={pid:[] for pid in order};blocked=set();clone=[{**p,'generation_dependencies':[],'visual_state_keys':p.get('visual_state_keys') if isinstance(p.get('visual_state_keys'),list) else []} for p in raw]
    split=(len(order)+1)//2
    windows=[('EPISODE',order)] if state.get('execution_mode')=='episode_async_v1' else [('H001',order[:split]),('H002',order[split:])]
    for bid,ids in windows:
        for hold in generation_holds(state):
            affected,_=blocked_panels([hold],order,{'batch_id':bid,'panel_ids':ids},clone)
            blocked.update(affected)
            for pid in affected:direct_holds[pid].append(hold)
    reasons={pid:[{'kind':'scoped_hold','evidence':str(direct_holds[pid])}] for pid in blocked}
    design_blocked=set(blocked)
    boundary=[*prior_binding(state,root,shots,path.parent),*load_context(shots,path.parent,readonly=True)[1]]
    for pid in order:
        p=by_id[pid];row=reviews[pid]
        issues=[]
        from issue_disposition import planning_notes
        notes=planning_notes(p.get('planning_notes',[]),pid)
        planning_items.extend(notes)
        issues.extend(n['detail'] for n in notes if n['blocks_input'])
        # Per-shot execution risks are local design evidence. Classify every
        # row before dependency propagation; a later malformed row must not
        # become an episode-wide HOLD or disappear behind a dispatch limit.
        if state.get('execution_mode')=='episode_async_v1':
            from image_risk_guards import shot_errors
            issues.extend(shot_errors(p))
        if p.get('locked_script')!=source['locked_scripts'][pid]:issues.append('锁定原文不一致')
        for field in ('generation_dependencies','design_dependencies'):
            deps=p.get(field,[] if field=='design_dependencies' else None)
            if not isinstance(deps,list) or any(not isinstance(d,str) or d not in order[:order.index(pid)] for d in deps) or len(set(deps))!=len(deps):issues.append(field+':缺失或不是准确前序格')
        keys=p.get('visual_state_keys')
        if not isinstance(keys,list) or not keys or any(not isinstance(k,str) or not k for k in keys) or type(p.get('requires_state_review')) is not bool:issues.append('视觉状态/审查条件尚未明确')
        policy=p.get('state_review_policy','user_required')
        if (policy not in ('user_required','merge_into_C','merge_into_D') or
            p.get('requires_state_review') and policy!='user_required' or
            state.get('execution_mode')=='episode_async_v1' and policy=='merge_into_C' or
            state.get('execution_mode')!='episode_async_v1' and (policy=='merge_into_C' and order.index(pid)>=split or policy=='merge_into_D' and order.index(pid)<split)):
            issues.append('新状态审查范围无效')
        if p.get('hold_reasons'):issues.extend(map(str,p['hold_reasons']))
        if row.get('status')!='REVIEWED' or not row.get('reviewer') or not row.get('evidence'):issues.append('本格尚未实际语义核对')
        for key in semantic_checks(state):
            check=row.get('checks',{}).get(key,{})
            if check.get('status')!='PASS' or not check.get('evidence'):issues.append(key+':尚未核对')
        if 'framing_feasibility' in semantic_checks(state):
            from visual_evidence import feasibility_errors
            issues.extend(feasibility_errors(p,row.get('checks',{}).get('framing_feasibility',{})))
        if pid!=order[0] or not boundary:
            try:
                from continuity_context import rule_tags
                from rule_memory import trigger_review_errors
                issues.extend(trigger_review_errors(state.get('memory_source'),'shot_design',p,row.get('checks',{}).get('rule_triggers',{}),rule_tags(shots,path.parent,p)))
            except (OSError,ValueError,TypeError,KeyError,AttributeError) as exc:issues.append('规则/相邻语义:'+str(exc))
        if pid==order[0] and not issues:
            own_holds=direct_holds[pid]
            if own_holds and all(isinstance(h,dict) and h.get('scope')=='panels' and h.get('dimension')=='boundary_comparison' for h in own_holds):design_blocked.discard(pid)
        if issues:blocked.add(pid);design_blocked.add(pid);reasons.setdefault(pid,[]).append({'kind':'design_or_audit','evidence':';'.join(issues)})
    # Missing/invalid preceding-episode comparison belongs to this boundary.
    if boundary:
        pid=order[0];blocked.add(pid);reasons.setdefault(pid,[]).append({'kind':'boundary_comparison','evidence':';'.join(boundary)})
    changed=True
    while changed:
        changed=False
        for pid in order:
            p=by_id[pid];deps=p.get('generation_dependencies');design=p.get('design_dependencies',[])
            deps=[d for d in deps if isinstance(d,str)] if isinstance(deps,list) else [];design=[d for d in design if isinstance(d,str)] if isinstance(design,list) else []
            prior=p.get('continuity_contract',{}).get('scene',{}).get('previous_panel_id')
            if prior in by_id:design.append(prior)
            inherited=set(deps)&blocked | set(design)&design_blocked
            if inherited and pid not in blocked:
                blocked.add(pid);reasons.setdefault(pid,[]).append({'kind':'dependency','panel_ids':sorted(inherited),'evidence':'实际图片/未确定设计依赖'})
                changed=True
            if set(design)&design_blocked and pid not in design_blocked:
                design_blocked.add(pid);changed=True
    from input_semantics import enabled as semantics_enabled, coverage as semantic_coverage
    execution_status = {}
    if include_execution and semantics_enabled(state):
        # Keep design readiness separate: final input review is downstream of
        # candidate construction and must not create a preparation cycle.
        execution_status['final_input_semantics'] = semantic_coverage(state, root)
    from issue_disposition import summarize
    disposition=summarize(local_errors=reasons,notes=planning_items,ready_ids=[pid for pid in order if pid not in blocked])
    return {**execution_status, 'issue_disposition':disposition, 'global_errors':[],'pending_comparison_panel_ids':sorted({p for h in comparison_holds(state) for p in h['panel_ids']}),
            'ready_for_review_ids':[pid for pid in order if pid not in design_blocked],
            'prepared_panel_ids':[pid for pid in order if pid not in blocked],
            'blocked_panel_ids':[pid for pid in order if pid in blocked],'blockers':reasons,'user_approval':'NOT_GRANTED'}
