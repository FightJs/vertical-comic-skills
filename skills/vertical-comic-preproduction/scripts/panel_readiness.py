"""Scoped preparation and literal approval reuse; never writes or grants approval."""
from pathlib import Path
import hashlib,json
from contextvars import ContextVar
from contextlib import contextmanager
from codex_reference_contract import checked_file,read_json

POLICY='panel_readiness_v1'
_REVIEW=ContextVar('comic_design_review',default=None)

@contextmanager
def review_context(state,root,candidate=False):
    token=_REVIEW.set((state,Path(root).resolve()) if candidate and enabled(state) else None)
    try:yield
    finally:_REVIEW.reset(token)

def candidate_source(source):
    active=_REVIEW.get()
    if active is None:return False
    state,root=active
    return Path(source.get('root','')).resolve()==root and source.get('episode_id')==state['episode_id'] and all(source.get(k)==state.get(k) for k in ('source_script','source_snapshot','visual_basis','shot_manifest'))

def enabled(state):return state.get('readiness_policy')==POLICY

def binding_errors(state,manifest):
    if enabled(state) and manifest.get('readiness_policy')!=POLICY:return ['READINESS_HOLD:执行依据缺少相同逐格放行策略']
    return []

def design_signature(panel):
    # These are observations, holds or call receipts, not creative authority.
    ignored={'generation_execution','memory_applications','status','hold_reasons','boundary_comparison','inspection_plan'}
    value={k:v for k,v in panel.items() if k not in ignored}
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def compatible_collection(root,old_ref,new_ref,ids,book,episode):
    """Compare original frozen rows and all shared design headers; no re-signing."""
    if old_ref==new_ref:return True
    try:
        old=read_json(checked_file(Path(root),old_ref));new=read_json(checked_file(Path(root),new_ref))
        if not isinstance(old.get('panels'),list) or not isinstance(new.get('panels'),list):return False
        if new.get('book_id') not in (None,book) or new.get('episode_id') not in (None,episode):return False
        ignored={'panels','continuity_context','status','hold_reasons'}
        if {k:v for k,v in old.items() if k not in ignored}!={k:v for k,v in new.items() if k not in ignored}:return False
        a={p['panel_id']:p for p in old['panels']};b={p['panel_id']:p for p in new['panels']}
        if len(a)!=len(old['panels']) or len(b)!=len(new['panels']):return False
        return all(pid in a and pid in b and design_signature(a[pid])==design_signature(b[pid]) for pid in ids)
    except (OSError,ValueError,TypeError,KeyError):return False

def artifacts_covered(state,root,proof,artifacts,ids,phase=None):
    """Narrow technical reuse of exact approved rows from preserved source files."""
    from staged_workflow import approval_errors
    bound=proof.get('artifacts',[])
    if approval_errors(proof,root,bound,state['book_id'],state['episode_id'],phase=phase,panel_ids=ids):return False
    def covered(ref):
        if ref in bound:return True
        value=read_json(checked_file(Path(root),ref))
        if value.get('policy')=='semantic_audit_v1':
            return value.get('book_id')==state['book_id'] and value.get('episode_id')==state['episode_id'] and covered(value['visual_basis']) and covered(value['shot_manifest'])
        if ref==state.get('shot_manifest') or value.get('policy')=='content_balanced_ratios_v1':
            return any(compatible_collection(root,old,ref,ids,state['book_id'],state['episode_id']) for old in bound)
        # Keep source-ID adapter and exact original approvals supported.
        return not approval_errors(proof,root,[ref],state['book_id'],state['episode_id'],phase=phase,panel_ids=ids)
    try:return all(covered(ref) for ref in artifacts)
    except (OSError,ValueError,TypeError,KeyError,RecursionError):return False

def approval_errors_for(state,root,phase,artifacts,ids,direct=None,*,proofs=()):
    from staged_workflow import approval_errors
    candidates=[p for p in proofs if isinstance(p,dict)]
    if isinstance(direct,dict):candidates.append(direct)
    if state.get('approval_index'):
        index=read_json(checked_file(Path(root),state['approval_index']))
        if index.get('policy')!='approval_index_v1':return ['批准索引版本错误']
        for entry in index.get('entries',[]):
            if entry.get('phase')==phase and entry.get('book_id')==state['book_id'] and state['episode_id'] in entry.get('episode_ids',[]):
                proof=read_json(checked_file(Path(root),entry['approval']))
                # Both the original proof and lookup scope must cover the row.
                candidates.append({**proof,'_lookup_panel_ids':entry.get('panel_ids',[])})
    missing=[]
    for pid in ids:
        names={pid,state['episode_id']+'-'+pid};found=False
        for proof in candidates:
            if (proof.get('review_event_id') or proof.get('source_kind')=='agent_decision') and proof.get('phase')!=phase:continue
            scope=proof.get('panel_ids')
            if phase!='visual_basis' and (not isinstance(scope,list) or not names.intersection(scope)):continue
            if phase=='visual_basis' and scope is not None and not names.intersection(scope):continue
            if '_lookup_panel_ids' in proof and not names.intersection(proof['_lookup_panel_ids']):continue
            if artifacts_covered(state,root,proof,artifacts,[pid],phase):found=True;break
        if not found:missing.append(pid)
    return ['缺少原范围、原版本或未变条目适用的真实批准:'+','.join(missing)] if missing else []

def local_tags_manifest(manifest,panel):
    """An internal pair does not inherit the episode's preceding boundary pair."""
    if manifest.get('readiness_policy')!=POLICY:return manifest
    panels=manifest.get('panels',[])
    if panels and panel['panel_id']!=panels[0]['panel_id']:
        return {k:v for k,v in manifest.items() if k!='continuity_context'}
    return manifest

def report(state,root):
    """Return ready/reviewable/blocked rows; caller still runs full input gates."""
    source=read_json(checked_file(Path(root),state['source_snapshot']));order=source['panel_ids']
    path=checked_file(Path(root),state['shot_manifest']);shots=read_json(path)
    audit=read_json(checked_file(Path(root),state['semantic_audit']))
    expected={'book_id':state['book_id'],'episode_id':state['episode_id'],'source_snapshot':state['source_snapshot'],'visual_basis':state['visual_basis'],'shot_manifest':state['shot_manifest'],'panel_ids':order}
    errors=[]
    if any(shots.get(k)!=state.get(k) for k in ('book_id','episode_id','preparation_policy','readiness_policy')):errors.append('全话镜头归属或准备策略不一致')
    if audit.get('policy')!='semantic_audit_v1' or any(audit.get(k)!=v for k,v in expected.items()):errors.append('全话语义报告的书话、源稿或冻结版本错误')
    if [p.get('panel_id') for p in shots.get('panels',[])]!=order or [p.get('panel_id') for p in audit.get('panels',[])]!=order:errors.append('全话镜头/语义报告缺格、乱序或重复')
    if errors:return {'global_errors':errors,'ready_for_review_ids':[],'prepared_panel_ids':[],'blocked_panel_ids':order,'blockers':{}}
    from scoped_inputs import blocked_panels, generation_holds, comparison_holds
    from execution_contract import semantic_checks
    from continuity_context import binding_errors as prior_binding,load_context
    raw=shots['panels'];by_id={p['panel_id']:p for p in raw};reviews={p['panel_id']:p for p in audit['panels']}
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
    boundary=[*prior_binding(state,root,shots,path.parent),*load_context(shots,path.parent)[1]]
    for pid in order:
        p=by_id[pid];row=reviews[pid]
        issues=[]
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
    return {'global_errors':[],'pending_comparison_panel_ids':sorted({p for h in comparison_holds(state) for p in h['panel_ids']}),
            'ready_for_review_ids':[pid for pid in order if pid not in design_blocked],
            'prepared_panel_ids':[pid for pid in order if pid not in blocked],
            'blocked_panel_ids':[pid for pid in order if pid in blocked],'blockers':reasons,'user_approval':'NOT_GRANTED'}
