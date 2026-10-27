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
    clock = require_running(path)
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
    if phase == 'repair' and clock['remaining_seconds'] <= 1800: expired = True
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
