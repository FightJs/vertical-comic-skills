"""Immutable half inputs, portable approval lookup and fail-closed scoped holds."""
from pathlib import Path
import json
from codex_reference_contract import read_json, checked_file

POLICY = 'scoped_half_review_v1'
EPISODE_POLICY = 'scoped_episode_review_v1'
EPISODE_MODE = 'episode_async_v1'
PREPARATION = 'episode_preparation_v1'
STATE_DISPATCH = 'ordinary_state_parallel_v1'


def enabled(state): return state.get('optimization_policy') in {POLICY, EPISODE_POLICY}

def full_preparation(state): return state.get('preparation_policy') == PREPARATION

def state_leads(panels):
    """First visible use of each approved state within the current half."""
    seen=set();leads=set()
    for panel in panels:
        keys=set(panel.get('visual_state_keys',[]))
        if keys-seen:leads.add(panel['panel_id'])
        seen.update(keys)
    return leads

def read(path): return read_json(path)


def build_plan(state, source):
    order = source.get('panel_ids')
    if not isinstance(order, list) or not order or any(not isinstance(p, str) or not p for p in order) or len(set(order)) != len(order):
        raise ValueError('源格序缺失或重复')
    if state.get('execution_mode') == EPISODE_MODE:
        return {'policy': EPISODE_MODE, 'optimization_policy': EPISODE_POLICY,
                'source_snapshot': state['source_snapshot'], 'batch_strategy': 'full_episode',
                'max_batch_size': len(order), 'batches': [{'batch_id': 'EPISODE', 'panel_ids': order}]}
    n = (len(order)+1)//2
    batches = [{'batch_id':'H001','panel_ids':order[:n]}]
    if order[n:]: batches.append({'batch_id':'H002','panel_ids':order[n:]})
    return {'policy':'half_episode_async_v1','optimization_policy':POLICY,'source_snapshot':state['source_snapshot'],
            'batch_strategy':'half_episode','max_batch_size':n,'pilot_panel_ids':order[:n],'batches':batches}


def half_view(state, batch_id):
    if full_preparation(state):
        if state.get('half_inputs') or state.get('half_gates'):
            raise ValueError('全话准备模式不能混用半话资产/镜头批准')
        if not state.get('visual_basis') or not state.get('shot_manifest'):
            raise ValueError('全话视觉基准/镜头尚未冻结')
        return {**state, 'active_input_scope':batch_id}
    inputs = state.get('half_inputs', {}).get(batch_id)
    if not isinstance(inputs, dict) or not inputs.get('visual_basis') or not inputs.get('shot_manifest'):
        raise ValueError(f'{batch_id}:半话视觉基准/镜头尚未冻结，不借其他半话批准放行')
    return {**state, 'visual_basis':inputs['visual_basis'],'shot_manifest':inputs['shot_manifest'],
            **({'semantic_audit':inputs['semantic_audit']} if inputs.get('semantic_audit') else {}),
            'active_input_scope':batch_id}


def resolve_context(state, root, batch_id):
    """One read-only view for dispatch, recovery and review; never selects new authority.

    Resolve only a declared source-contiguous scope. Historical attempts keep their
    own package/QA references; a current shot must never rewrite an old request.
    """
    root = Path(root).resolve()
    source = read(checked_file(root, state['source_snapshot']))
    plan = read(checked_file(root, state['batch_plan']))
    if plan != build_plan(state, source):
        raise ValueError('CONTEXT_HOLD:生产范围与冻结源序不一致')
    window = next((b for b in plan['batches'] if b['batch_id'] == batch_id), None)
    if window is None:
        raise ValueError('CONTEXT_HOLD:未声明的生产范围')
    view = half_view(state, batch_id)
    shot_document = read(checked_file(root, view['shot_manifest']))
    rows = shot_document.get('panels', [])
    expected = source['panel_ids'] if full_preparation(state) else window['panel_ids']
    if [p.get('panel_id') for p in rows] != expected:
        raise ValueError('CONTEXT_HOLD:镜头范围缺格、乱序或重复')
    records = state.get('panels', [])
    if [r.get('panel_id') for r in records] != source['panel_ids']:
        raise ValueError('CONTEXT_HOLD:当前进度与源序不同')
    return {'state': view, 'batch': window, 'source': source,
            'shots': rows, 'records': {r['panel_id']: r for r in records},
            'basis_ref': view['visual_basis'], 'shot_ref': view['shot_manifest']}


def approval_for(state, root, phase, artifacts, panel_ids, direct=None):
    """Reuse the original literal user proof; never expand scope or synthesize APPROVED."""
    from panel_readiness import enabled,approval_errors_for
    if enabled(state):return approval_errors_for(state,root,phase,artifacts,panel_ids,direct)
    from staged_workflow import approval_errors
    def check(approval):
        errors = approval_errors(approval, root, artifacts, state['book_id'], state['episode_id'],phase=phase,panel_ids=panel_ids)
        if isinstance(approval,dict) and (approval.get('review_event_id') or approval.get('source_kind')=='agent_decision') and approval.get('phase')!=phase:
            errors.append('批准阶段不符，不能从B推导包或最终批准')
        if isinstance(approval, dict) and approval.get('panel_ids') is not None and not all(p in approval['panel_ids'] or state['episode_id']+'-'+p in approval['panel_ids'] for p in panel_ids):
            errors.append('批准格号范围未覆盖本次请求')
        return errors
    if direct is not None: return check(direct)
    ref = state.get('approval_index')
    if not ref: return ['缺少本范围用户批准；无索引可复用']
    index = read(checked_file(root, ref))
    if index.get('policy') != 'approval_index_v1' or not isinstance(index.get('entries'), list): return ['批准索引版本无效']
    errors = []
    for entry in index['entries']:
        if entry.get('phase') != phase or entry.get('book_id') != state['book_id'] or state['episode_id'] not in entry.get('episode_ids', []) or not all(p in entry.get('panel_ids',[]) or state['episode_id']+'-'+p in entry.get('panel_ids',[]) for p in panel_ids):
            continue
        proof = read(checked_file(root, entry.get('approval')))
        found = check(proof)
        if not found: return []
        errors.extend(found)
    return errors or ['索引没有相同版本且实际授权范围适用的批准；需审查新增差异']


def blocked_panels(holds, order, batch, shots):
    """Unknown/unscoped holds block everything; explicit local scopes require evidence."""
    blocked, reasons = set(), []
    by_id = {p['panel_id']:p for p in shots}
    for h in holds or []:
        if not isinstance(h, dict) or h.get('scope') not in {'book','episode','half','panels','states'}:
            blocked.update(batch['panel_ids']); reasons.append(h); continue
        scope = h['scope']
        if scope in {'book','episode'}:
            blocked.update(batch['panel_ids']); reasons.append(h); continue
        if not isinstance(h.get('evidence'), str) or not h['evidence'].strip():
            blocked.update(batch['panel_ids']); reasons.append('局部HOLD缺少影响范围依据，按全局处理'); continue
        if scope == 'half' and batch['batch_id'] == 'EPISODE':
            # Legacy half-local holds must be converted explicitly during migration.
            blocked.update(batch['panel_ids']); reasons.append('旧半话HOLD尚未映射到准确格号'); continue
        if scope == 'half':
            ids = h.get('half_ids')
            valid = isinstance(ids,list) and bool(ids) and all(p in {'H001','H002'} for p in ids)
            affected = set(batch['panel_ids']) if not valid or batch['batch_id'] in ids else set()
        elif scope == 'panels':
            ids = h.get('panel_ids')
            valid = isinstance(ids,list) and bool(ids) and all(isinstance(p,str) and p in order for p in ids)
            affected = set(batch['panel_ids']) if not valid else set(ids).intersection(batch['panel_ids'])
        else:
            keys = h.get('state_keys')
            valid = isinstance(keys,list) and bool(keys) and all(isinstance(k,str) and k.strip() for k in keys)
            affected = set(batch['panel_ids']) if not valid else {p for p in batch['panel_ids'] if set(keys).intersection(by_id.get(p,{}).get('visual_state_keys',[]))}
        if affected: blocked.update(affected); reasons.append(h)
    # Real-image dependencies inherit the hold, never quietly consume a failed basis.
    changed = True
    while changed:
        changed = False
        for p in batch['panel_ids']:
            if p not in blocked and set(by_id.get(p,{}).get('generation_dependencies',[])).intersection(blocked):
                blocked.add(p); changed = True
    return blocked, reasons


def global_hold(holds):
    return any(not isinstance(h,dict) or h.get('scope') not in {'half','panels','states'} or not h.get('evidence') for h in holds or [])


def comparison_holds(state):
    """Only explicit final-comparison holds; never infer away uncertain design."""
    if state.get('execution_mode')!=EPISODE_MODE or state.get('runtime',{}).get('question_policy')!='grouped_review_v1':return []
    known={p['panel_id'] for p in state.get('panels',[])}
    return [h for h in state.get('holds',[]) if isinstance(h,dict) and h.get('scope')=='panels'
            and h.get('dimension')=='boundary_comparison' and h.get('comparison_only') is True
            and isinstance(h.get('panel_ids'),list) and h['panel_ids'] and set(h['panel_ids'])<=known
            and isinstance(h.get('evidence'),str) and h['evidence'].strip()]


def generation_holds(state):
    deferred=comparison_holds(state)
    return [h for h in state.get('holds',[]) if h not in deferred]


def validate_shots(state, source, batch, shots, blocked=()):
    from panel_readiness import binding_errors as readiness_binding
    issues=readiness_binding(state,shots)
    if issues:raise ValueError(';'.join(issues))
    from frame_ratio_plan import binding_errors
    errors=binding_errors(state,shots)
    if errors:raise ValueError(';'.join(errors))
    panels = shots.get('panels',[])
    expected = source['panel_ids'] if full_preparation(state) else batch['panel_ids']
    if shots.get('execution_mode') != state.get('execution_mode') or shots.get('optimization_policy') != state.get('optimization_policy') or [p.get('panel_id') for p in panels] != expected:
        raise ValueError('镜头须声明优化策略且准确覆盖当前准备范围源序')
    if full_preparation(state) and shots.get('preparation_policy') != PREPARATION:
        raise ValueError('全话镜头未绑定全话准备合同')
    order = source['panel_ids']; seen = set()
    for p in panels:
        pid = p['panel_id']; deps = p.get('generation_dependencies'); keys = p.get('visual_state_keys')
        if p.get('locked_script') != source['locked_scripts'][pid]: raise ValueError(f'{pid}:锁定原文不一致')
        if pid in blocked: continue
        if not isinstance(deps,list) or any(not isinstance(d,str) or d not in order[:order.index(pid)] for d in deps) or len(set(deps)) != len(deps): raise ValueError(f'{pid}:实图依赖无效')
        if not isinstance(keys,list) or not keys or any(not isinstance(k,str) or not k for k in keys) or type(p.get('requires_state_review')) is not bool: raise ValueError(f'{pid}:视觉状态/审查条件无效')
        if p['requires_state_review'] and p.get('state_review_policy','user_required')!='user_required':raise ValueError(f'{pid}:明确高风险实图停点不能合并到C/D')
        if p.get('state_review_policy','user_required') not in {'user_required','merge_into_C','merge_into_D'}: raise ValueError(f'{pid}:状态审查模式无效')
        in_first = pid in source['panel_ids'][:(len(source['panel_ids'])+1)//2]
        if state.get('execution_mode') == EPISODE_MODE:
            if p.get('state_review_policy') == 'merge_into_C':raise ValueError(f'{pid}:整话模式没有半话C停点')
        elif p.get('state_review_policy') == 'merge_into_C' and not in_first or p.get('state_review_policy') == 'merge_into_D' and in_first:
            raise ValueError(f'{pid}:状态合并审查范围不一致')
    return [p for p in panels if p['panel_id'] in batch['panel_ids']] if full_preparation(state) else panels
