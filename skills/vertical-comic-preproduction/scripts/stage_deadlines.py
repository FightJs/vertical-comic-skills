"""Durable active-time degradation. Never fabricates images, reviews or approvals."""
import copy, json, time
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar
from platform_io import atomic_json, file_lock

POLICY = 'bounded_stage_fallback_v1'
LIMITS = {'preparation':2700, 'intake':600, 'compile':90, 'review':30, 'repair':480, 'pack':30}
_SLICE = ContextVar('comic_compile_slice', default=None)


def enabled(state):
    policy = state.get('speed_policy')
    if policy not in (None, POLICY): raise ValueError('Unknown speed policy')
    if policy and state.get('image_review_profile') != 'light_story_review_v1':
        raise ValueError('Bounded stage policy requires lightweight image review')
    return policy == POLICY


def checkpoint(state_path, phase, panel_id=None, *, state=None):
    if phase not in LIMITS: raise ValueError('Unknown speed phase')
    path = Path(state_path).resolve()
    if state is None:
        from codex_reference_contract import read_json
        state = read_json(path)
    if not enabled(state): return None
    from runtime_clock import require_running, execution_context
    if phase in {'review','repair','pack'}:
        from runtime_clock import require_step
        clock = require_step(path,'preserve-delivery')
    else:clock = require_running(path)
    if not clock or clock.get('state') != 'RUNNING' or clock.get('active_seconds') is None:
        raise ValueError('SPEED_CLOCK_REQUIRED: no wall-time or unlimited fallback')
    context = execution_context(path)
    origin = context.get('run_id') if context else clock.get('clock_origin')
    if origin is None: raise ValueError('SPEED_CLOCK_ORIGIN_REQUIRED')
    active = clock['active_seconds']
    key = phase + ':' + (panel_id or 'episode')
    ledger_path = path.parent/'stage-runtime.json'
    # Operational scheduling metadata, not part of the creative-evidence read snapshot.
    with file_lock(path.parent/'stage-runtime.lock'):
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {
            'policy':POLICY, 'clock_origin':origin, 'starts':{}}
        if ledger.get('policy') != POLICY or ledger.get('clock_origin') != origin:
            raise ValueError('SPEED_CLOCK_ORIGIN_CHANGED')
        if key not in ledger['starts']:
            ledger['starts'][key] = 0 if phase in {'preparation','intake'} else active
            atomic_json(ledger_path, ledger)
        start = ledger['starts'][key]
    if active < start: raise ValueError('SPEED_ACTIVE_CLOCK_RESET')
    spent = active - start
    expired = spent >= LIMITS[phase]
    if phase == 'repair' and clock['remaining_seconds'] <= 900: expired = True
    return {'policy':POLICY, 'phase':phase, 'panel_id':panel_id,
            'active_elapsed_seconds':round(spent,3), 'limit_seconds':LIMITS[phase],
            'degraded':expired, 'remaining_task_seconds':clock['remaining_seconds'],
            'fallback':{'preparation':'skip_optional_polish', 'intake':'skip_optional_reorganization',
                'compile':'incremental_five_panels', 'review':'single_observed_summary',
                'repair':'adopt_existing_with_issues', 'pack':'store_remaining_files'}[phase]}


class CompileSliceExpired(RuntimeError): pass
class RepairPlanningExpired(RuntimeError): pass


@contextmanager
def compile_slice(path, state):
    mark = checkpoint(path, 'compile', state=state)
    token = _SLICE.set({'path':path, 'state':state, 'next':time.monotonic()+.5} if mark else None)
    try: yield
    finally: _SLICE.reset(token)


def poll_compile():
    scope = _SLICE.get()
    if scope and time.monotonic() >= scope['next']:
        if checkpoint(scope['path'], 'compile', state=scope['state'])['degraded']:
            raise CompileSliceExpired('SPEED_COMPILE_SLICE_EXPIRED')
        scope['next'] = time.monotonic()+.5


def manual_decision(decision):
    value = copy.deepcopy(decision)
    value.update(action='defer_manual', fix_now=[], opportunistic=[],
                 manual=[i['id'] for i in value['issues']],
                 reason='环节预算耗尽：采用已有真实图片，保留问题供人工后修')
    for issue in value['issues']: issue['handling'] = '限时降级：保留原图，人工后修'
    return value


def defer_repair(path, expected_state, panel_id):
    """Revise handling/adoption through the original CAS pipeline, retain old QA/attempts."""
    from codex_reference_contract import read_json, checked_file, digest
    from production_decisions import load_decision
    from review_pipeline import save
    path = Path(path).resolve(); root = path.parent.parent
    if digest(path) != expected_state: raise ValueError('STATE_CHANGED')
    state = read_json(path); row = next(r for r in state['panels'] if r['panel_id']==panel_id)
    if row.get('round_id') != 1 or row.get('status') != 'VISUAL_FAIL':
        raise ValueError('SPEED_DEFER_REQUIRES_UNSUBMITTED_REPAIR')
    _, decision, item, _ = load_decision(root, row, row['attempt_id'])
    review = item['light_review']
    observed = ({'single_observation':review['single_observation'], 'issues':review['issues']}
                if 'single_observation' in review else {'checks':review['checks'],'issues':review['issues']})
    proposal = {'panel_id':panel_id, 'attempt_id':row['attempt_id'], 'base_qa':row['qa_report'],
        'reviewer':review['reviewer'], 'reason':'限时改为采用已有图；复用未变化图片的原观察，未重新看图',
        'verdict':review['status'], 'light_observations':observed,
        'decision':{k:v for k,v in manual_decision(decision).items()
                    if k not in {'policy','panel_id','attempt_id','image','qa_report','reviewer'}}, 'adopt':True}
    result = save(path, expected_state, proposal)
    result.update(status='REPAIR_DEFERRED_TO_DELIVERY', image_calls=0, new_attempt_created=False)
    return result


def forecast(state_paths, clock):
    """Observed unique returned panels per ACTIVE second; not service promises.

    Sampling is shared by the task, excludes imported output as newly generated
    work and does not restart the original clock. Missing timing stays unknown.
    """
    from codex_reference_contract import read_json
    paths=[Path(p).resolve() for p in state_paths]
    if not paths:raise ValueError('FORECAST_REQUIRES_STATES')
    from runtime_clock import execution_context
    contexts=[execution_context(p) for p in paths]
    if any(c is None for c in contexts) or len({c['run_id'] for c in contexts})!=1:
        raise ValueError('FORECAST_REQUIRES_ONE_TASK_CLOCK')
    active=clock.get('active_seconds');remaining=clock.get('remaining_seconds')
    target_remaining=clock.get('target_remaining_seconds')
    if target_remaining is None:target_remaining=remaining
    states=[read_json(p) for p in paths]
    keys={(s['episode_id'],r['panel_id']) for s in states for r in s['panels']}
    returned={(s['episode_id'],r['panel_id']) for s in states for r in s['panels'] if r.get('output')}
    folder=Path(contexts[0]['clock_directory']);path=folder/'throughput.json'
    if active is None or remaining is None:
        return {'status':'TIME_UNCERTAIN','missing_panels':len(keys-returned),'expected_remaining_seconds':None}
    with file_lock(folder/'throughput.lock'):
        data=read_json(path) if path.exists() else {'run_id':contexts[0]['run_id'],'samples':[],'source_keys':sorted(keys)}
        if data['run_id']!=contexts[0]['run_id'] or data['source_keys']!=[list(k) for k in sorted(keys)]:
            # JSON list/tuple normalization also covers the first local value.
            if data['run_id']!=contexts[0]['run_id'] or [list(k) for k in data['source_keys']]!=[list(k) for k in sorted(keys)]:
                raise ValueError('FORECAST_SCOPE_CHANGED')
        samples=data['samples']
        if samples and active<samples[-1]['active_seconds']:raise ValueError('FORECAST_CLOCK_RESET')
        sample={'active_seconds':active,'returned':len(returned)}
        if not samples or sample!=samples[-1]:samples.append(sample)
        data['samples']=samples[-120:];atomic_json(path,data)
    first=samples[0];count=len(returned)-first['returned'];elapsed=active-first['active_seconds']
    missing=len(keys-returned)
    seconds=missing*elapsed/count if count>=5 and elapsed>0 else None
    reserve=900
    late=missing>0 and (target_remaining<=0 or (seconds is not None and seconds+reserve>target_remaining))
    return {'status':'AT_RISK' if late else 'OBSERVING' if seconds is None else 'ON_TRACK',
            'source_panels':len(keys),'returned_panels':len(returned),'missing_panels':missing,
            'active_seconds':active,'remaining_seconds':remaining,'target_remaining_seconds':target_remaining,
            'hard_stop_at_risk':seconds is not None and seconds+reserve>remaining,
            'expected_remaining_seconds':round(seconds,3) if seconds is not None else None,
            'delivery_reserve_seconds':reserve,'stop_first_round':False,
            'actions':['prioritize_missing','skip_optional_polish','inspect_idle_slots_and_local_queue'] if late else ['continue_required_production'],
            'real_image_service_guarantee':False}


def repair_schedule(state,root):
    """Missing originals have priority; only their actual dependency repairs bypass it."""
    if not enabled(state):return None
    from codex_reference_contract import read_json,checked_file
    from runtime_clock import require_running
    clock=require_running(Path(root)/'00_输入审计/生产流程.json')
    states=[(state,Path(root))]
    if state.get('parallel_context'):
        control=read_json(Path(state['parallel_context']['control_file']))
        states=[(read_json(Path(j['root'])/j.get('state_file','00_输入审计/生产流程.json')),Path(j['root'])) for j in control['jobs']]
    missing=[];blocking=set()
    for other,other_root in states:
        absent={r['panel_id'] for r in other['panels'] if not r.get('output') and not any(h.get('output') for h in r.get('attempt_history',[]))}
        missing.extend((other['episode_id'],pid) for pid in sorted(absent))
        if absent and other['episode_id']==state['episode_id']:
            shots=read_json(checked_file(other_root,other['shot_manifest']))
            deps={r['panel_id']:r.get('generation_dependencies',[]) for r in shots['panels']}
            pending=list(absent);seen=set()
            while pending:
                pid=pending.pop()
                if pid in seen:continue
                seen.add(pid)
                for dep in deps.get(pid,[]):blocking.add(dep);pending.append(dep)
    return {'missing':missing,'required_dependency_repairs':sorted(blocking),
            'repair_budget_available':clock['remaining_seconds']>900,
            'delivery_reserve_seconds':900}
