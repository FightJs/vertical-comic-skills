#!/usr/bin/env python3
"""Task wall-time budget excluding explicit pauses. Never an image-call ledger."""
from pathlib import Path
import argparse, hashlib, json, os, platform, subprocess, time, uuid
from functools import lru_cache
from platform_io import atomic_json, file_lock, configure_stdio

POLICY = 'active_runtime_clock_v1'
CONTEXT_POLICY = 'local_execution_context_v1'
LEGACY_DEADLINE_POLICY = 'three_hour_target_four_hour_active_v1'
DEADLINE_POLICY = 'four_hour_target_seven_hour_active_v2'
DEADLINE_POLICIES = {LEGACY_DEADLINE_POLICY, DEADLINE_POLICY}
TARGET_SECONDS = 14400
HARD_LIMIT_SECONDS = 25200
DELIVERY_SCHEDULE = 'four_hour_wall_delivery_v1'

def initialize_context(run, role, limit, *, hard_deadline=False):
    """Local receiver/owner metadata, never portable creative approval evidence."""
    run = Path(run).resolve(); directory = run/'00_任务协调'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory/'execution-context.json'
    value = {'policy': CONTEXT_POLICY, 'run_id': uuid.uuid4().hex,
             'run_root': str(run), 'role': role, 'clock_required': limit is not None,
             'clock_directory': str(directory), 'limit_seconds': limit,
             **({'deadline_policy':DEADLINE_POLICY} if hard_deadline else {})}
    if hard_deadline:
        ledger=json.loads((directory/'runtime-clock.json').read_text(encoding='utf-8'))
        if ledger.get('deadline_policy') not in DEADLINE_POLICIES or ledger['limit_seconds']!=limit:raise ValueError('CLOCK_CONTEXT_CONFLICT')
        value['deadline_policy']=ledger['deadline_policy']
        value['clock_origin']=ledger['created']
        if ledger.get('delivery_schedule'):
            value['delivery_schedule']=ledger['delivery_schedule']
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        if any(old.get(k) != value.get(k) for k in ('policy','run_root','role','clock_required','clock_directory','limit_seconds','deadline_policy','clock_origin','delivery_schedule')):
            raise ValueError('CLOCK_CONTEXT_CONFLICT: preserve original owner policy')
    else: atomic_json(path, value)
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

def execution_context(path, *, state=None):
    path = Path(path).resolve()
    if state is None and path.is_file() and path.suffix == '.json':
        state = json.loads(path.read_text(encoding='utf-8-sig'))
    ref = (state or {}).get('runtime_execution_context')
    if ref is None:
        for parent in [path if path.is_dir() else path.parent, *path.parents]:
            candidate = parent/'00_任务协调/execution-context.json'
            if candidate.is_file():
                ref = {'path': str(candidate), 'sha256': hashlib.sha256(candidate.read_bytes()).hexdigest()}
                break
    if ref is None: return None
    target = Path(ref['path'])
    if not target.is_absolute() or target.is_symlink() or not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != ref.get('sha256'):
        raise ValueError('CLOCK_CONTEXT_MISSING_OR_CHANGED')
    data = json.loads(target.read_text(encoding='utf-8'))
    root = Path(data['run_root']).resolve(); directory = root/'00_任务协调'
    if (data.get('policy') != CONTEXT_POLICY or type(data.get('clock_required')) is not bool or
            not data.get('run_id') or data.get('role') not in {'preparation','production'} or
            not path.is_relative_to(root) or target.resolve() != directory/'execution-context.json' or
            data.get('clock_directory') != str(directory)):
        raise ValueError('CLOCK_CONTEXT_SCOPE_MISMATCH')
    return {**data, 'reference': ref}

@lru_cache(maxsize=1)
def boot_id():
    try:
        p = Path('/proc/sys/kernel/random/boot_id')
        if p.is_file(): return p.read_text().strip()
        if platform.system() == 'Windows':
            import ctypes
            data=ctypes.create_string_buffer(32)
            query=ctypes.WinDLL('ntdll').NtQuerySystemInformation
            query.argtypes=[ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_void_p]
            query.restype=ctypes.c_long
            if query(90,data,len(data),None)==0 and any(data.raw[:16]):
                return 'windows:'+data.raw[:16].hex()
        if platform.system() == 'Darwin':
            return subprocess.check_output(['sysctl', '-n', 'kern.boottime'], timeout=.3, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, AttributeError, subprocess.SubprocessError): pass
    return None  # No guessed boot identity on unsupported hosts.

@lru_cache(maxsize=1)
def boot_session_id():
    # Extra identity is understood by new clocks; legacy boot wire format stays
    # readable by already-frozen executors receiving events from installed hooks.
    if platform.system()!='Darwin':return None
    try:
        return subprocess.check_output(['sysctl','-n','kern.bootsessionuuid'],timeout=.3,
            text=True,stderr=subprocess.DEVNULL).strip() or None
    except (OSError,subprocess.SubprocessError):return None

def instant():
    return {'wall': time.time(), 'mono': time.monotonic(),
            'host': platform.node(), 'boot': boot_id(), 'boot_session':boot_session_id()}

def same_boot(a, b):
    """Identity compatibility only; callers must also verify monotonic continuity."""
    if a == b:return True
    if not a or not b:return False
    import re
    def parts(value):
        if value.startswith('darwin-session:'):
            _, session, seconds = value.split(':', 2)
            return session, seconds
        match = re.search(r'sec\s*=\s*(\d+)', value)
        if match:return None, match.group(1)
        match = re.fullmatch(r'darwin:(\d+)(?::\d+)?', value)
        return (None, match.group(1)) if match else (None, None)
    sa, ta = parts(a); sb, tb = parts(b)
    return bool(ta and ta == tb and (not sa or not sb or sa == sb))

def elapsed(a, b):
    if a.get('boot_session') and b.get('boot_session') and a['boot_session']!=b['boot_session']:
        raise ValueError('CLOCK_TIME_UNCERTAIN: boot session changed')
    if a['host'] != b['host'] or (a['boot'] and b['boot'] and not same_boot(a['boot'], b['boot'])):
        raise ValueError('CLOCK_TIME_UNCERTAIN: host/boot identity unavailable or changed')
    delta = b['mono'] - a['mono']
    if delta < 0 or abs((b['wall']-a['wall'])-delta) > 2:
        raise ValueError('CLOCK_TIME_UNCERTAIN: system clock changed')
    return delta

def initialize(directory, role, limit=None, *, at=None, hard_deadline=False, delivery_deadline=False):
    directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=True)
    if limit is None:limit=HARD_LIMIT_SECONDS if hard_deadline and not delivery_deadline else 14400
    deadline_policy=LEGACY_DEADLINE_POLICY if delivery_deadline else DEADLINE_POLICY
    maximum=14400 if delivery_deadline else HARD_LIMIT_SECONDS
    if role not in {'preparation', 'production'} or type(limit) is not int or limit < 1:
        raise ValueError('invalid role/limit')
    if delivery_deadline and not hard_deadline:raise ValueError('delivery deadline requires hard deadline')
    if hard_deadline and limit>maximum:raise ValueError(f'HARD_LIMIT_MAX_{maximum}: requested limit exceeds this clock policy')
    with file_lock(directory/'clock.lock'):
        path = directory/'runtime-clock.json'
        if path.exists():
            old = json.loads(path.read_text(encoding='utf-8'))
            if (old['role'] != role or old['limit_seconds'] != limit or
                old.get('deadline_policy') != (deadline_policy if hard_deadline else None) or
                old.get('delivery_schedule') != (DELIVERY_SCHEDULE if delivery_deadline else None)):
                raise ValueError('CLOCK_SCOPE_CONFLICT')
        else:
            atomic_json(path, {'policy': POLICY, 'role': role, 'limit_seconds': limit,
                              'created': at or instant(), 'events': [],
                              **({'delivery_schedule':DELIVERY_SCHEDULE} if delivery_deadline else {}),
                              **({'deadline_policy':deadline_policy,'target_seconds':min(10800 if delivery_deadline else TARGET_SECONDS,limit),
                                  'converge_seconds':min(9000,int(limit*.625))} if hard_deadline else {})})
    return status(directory, at=at)

def amendment_identity(directory, value):
    context=Path(directory)/'execution-context.json'
    return {'role':value['role'],'created':value['created'],
            'deadline_policy':value.get('deadline_policy'),'limit_seconds':value['limit_seconds'],
            'context_sha256':hashlib.sha256(context.read_bytes()).hexdigest() if context.exists() else None}


def amend_policy(directory, *, reason, source_ref):
    """Explicit scheduling revision; preserve original ledger, context refs and events."""
    if not isinstance(reason,str) or not reason.strip() or not isinstance(source_ref,str) or not source_ref.strip():
        raise ValueError('CLOCK_POLICY_AUTHORIZATION_REFERENCE_REQUIRED')
    directory=Path(directory).resolve()
    before=status(directory)
    if before['state'] in {'FINISHED','TIME_UNCERTAIN'}:raise ValueError('CLOCK_POLICY_REQUIRES_RECOVERABLE_RUN')
    with file_lock(directory/'clock.lock'):
        value=json.loads((directory/'runtime-clock.json').read_text(encoding='utf-8'))
        if value.get('delivery_schedule') or value.get('deadline_policy') not in DEADLINE_POLICIES:
            raise ValueError('CLOCK_POLICY_ACTIVE_ONLY')
        amendment={'policy':DEADLINE_POLICY,'origin':amendment_identity(directory,value),
                   'limit_seconds':HARD_LIMIT_SECONDS,'target_seconds':TARGET_SECONDS,
                   'reason':reason,'source_ref':source_ref}
        path=directory/'clock-policy-amendment.json'
        if path.exists():
            if json.loads(path.read_text(encoding='utf-8'))!=amendment:raise ValueError('CLOCK_POLICY_AMENDMENT_CONFLICT')
        else:atomic_json(path,amendment)
    return {'status':'POLICY_UPDATED','clock':status(directory),'history_reset':False,'image_calls':0}


def event(directory, action, event_id, *, source='explicit', at=None):
    """Immutable spool avoids waiting on coordinator/production locks in Interrupt."""
    directory = Path(directory).resolve()
    if action not in {'start','pause','resume','wait_user','finish','uncertain','hook_probe'}:
        raise ValueError('invalid clock action')
    if not event_id: raise ValueError('event_id required')
    if not (directory/'runtime-clock.json').is_file(): raise ValueError('clock not initialized')
    value = {'event_id': event_id, 'action': action, 'source': source, 'at': at or instant()}
    # Unique filenames preserve conflicting replays for diagnosis instead of overwriting.
    spool = directory/'clock-events'; spool.mkdir(exist_ok=True)
    atomic_json(spool/(uuid.uuid4().hex+'.json'), value)
    return value

def _read(directory):
    value = json.loads((directory/'runtime-clock.json').read_text(encoding='utf-8'))
    if value['policy'] != POLICY: raise ValueError('unknown clock policy')
    known = {e['event_id']: e for e in value['events']}
    for p in sorted((directory/'clock-events').glob('*.json')):
        e = json.loads(p.read_text(encoding='utf-8'))
        old = known.get(e['event_id'])
        if old is not None:
            if (old['action'],old['source']) != (e['action'],e['source']): raise ValueError('CLOCK_EVENT_ID_CONFLICT')
            if old['at']['wall'] <= e['at']['wall']: continue
        known[e['event_id']] = e
    events = list(known.values())
    same_boot = (all(e['at'].get('boot') for e in events) and
                 len({(e['at']['host'], e['at']['boot']) for e in events}) <= 1)
    events.sort(key=lambda e: (e['at']['mono'] if same_boot else e['at']['wall'], e['event_id']))
    if value['events'] != events:
        value['events'] = events
        atomic_json(directory/'runtime-clock.json', value)
    return value

def status(directory, *, at=None):
    directory = Path(directory).resolve()
    with file_lock(directory/'clock.lock'):
        value = _read(directory)
    now = at or instant()
    state = 'NOT_STARTED'; opened = None; total = 0.; uncertain = None
    last_interrupt = next((e['at']['wall'] for e in reversed(value['events'])
                           if e['source'].startswith('hook:') and e['action']=='pause'), None)
    hook_seen = any(e['source'].startswith('hook:') for e in value['events'])
    previous = None; closed = 0.
    try:
        for e in value['events']:
            action = e['action']; stamp = e['at']
            # Unknown boot IDs are not proof of one monotonic epoch. Validate
            # adjacent receipts, including gaps between closed active intervals.
            if previous is not None:
                if (state in {'PAUSED','WAIT_USER'} and action in {'resume','start'}
                        and previous.get('boot') and stamp.get('boot')):
                    # An explicit closed pause spans no charged execution. A
                    # reboot starts a new monotonic epoch; never subtract them.
                    if previous['host']!=stamp['host']:
                        raise ValueError('CLOCK_TIME_UNCERTAIN: host changed during pause')
                else:
                    elapsed(previous, stamp)
            previous = stamp
            if action == 'hook_probe': continue
            if action == 'uncertain': raise ValueError('CLOCK_TIME_UNCERTAIN: unclean lifecycle')
            if state == 'FINISHED':
                if action == 'pause' and e['source']=='hook:Interrupt':continue
                raise ValueError('CLOCK_EVENT_AFTER_FINISH')
            if action in {'start','resume'}:
                if opened is None: opened = stamp
                state = 'RUNNING'
            elif action in {'pause','wait_user','finish'}:
                if opened is not None:
                    total += elapsed(opened, stamp); opened = None; closed = total
                state = {'pause':'PAUSED','wait_user':'WAIT_USER','finish':'FINISHED'}[action]
        if opened is not None: total += elapsed(opened, now)
    except ValueError as exc:
        uncertain = str(exc); state = 'TIME_UNCERTAIN'
    try: wall = elapsed(value['created'], previous if state=='FINISHED' and value.get('deadline_policy') in DEADLINE_POLICIES else now)
    except ValueError: wall = None
    hard=value.get('deadline_policy') in DEADLINE_POLICIES
    if value.get('deadline_policy') not in (None,*DEADLINE_POLICIES):raise ValueError('UNKNOWN_DEADLINE_POLICY')
    maximum=14400 if value.get('deadline_policy')==LEGACY_DEADLINE_POLICY else HARD_LIMIT_SECONDS
    target=10800 if value.get('deadline_policy')==LEGACY_DEADLINE_POLICY else TARGET_SECONDS
    if hard and (value['limit_seconds']>maximum or value.get('target_seconds')!=min(target,value['limit_seconds'])):
        raise ValueError('DEADLINE_CONTRACT_CHANGED')
    original_limit=value['limit_seconds'];original_policy=value.get('deadline_policy')
    amendment_path=directory/'clock-policy-amendment.json'
    if amendment_path.exists():
        amendment=json.loads(amendment_path.read_text(encoding='utf-8'))
        expected=amendment_identity(directory,value)
        if (original_policy not in DEADLINE_POLICIES or amendment.get('origin')!=expected or amendment.get('policy')!=DEADLINE_POLICY
                or amendment.get('limit_seconds')!=HARD_LIMIT_SECONDS or amendment.get('target_seconds')!=TARGET_SECONDS
                or not amendment.get('reason') or not amendment.get('source_ref') or value.get('delivery_schedule')):
            raise ValueError('CLOCK_POLICY_AMENDMENT_CHANGED')
        value={**value,'deadline_policy':DEADLINE_POLICY,'limit_seconds':HARD_LIMIT_SECONDS,'target_seconds':TARGET_SECONDS}
        hard=True
    delivery=value.get('delivery_schedule')==DELIVERY_SCHEDULE
    if value.get('delivery_schedule') not in (None,DELIVERY_SCHEDULE):raise ValueError('UNKNOWN_DELIVERY_SCHEDULE')
    if delivery and wall is None:
        uncertain=uncertain or 'CLOCK_TIME_UNCERTAIN: wall deadline unavailable';state='TIME_UNCERTAIN'
    charged=wall if delivery else total
    remaining=None if uncertain else round(max(0,value['limit_seconds']-charged),3)
    stage=('HARD_STOP' if remaining==0 else 'TARGET_OVERRUN' if hard and not uncertain and total>=value['target_seconds']
           else 'CONVERGE' if hard and not uncertain and total>=value['converge_seconds'] else 'PRODUCE')
    if delivery and remaining is not None:
        reserve=min(1800,value['limit_seconds']*.125)
        stage=('HARD_STOP' if remaining==0 else 'PACKAGE' if remaining<=reserve/2
               else 'DRAIN' if remaining<=reserve else 'CONVERGE' if charged>=value['limit_seconds']*.625 else 'PRODUCE')
    from runtime_clock_context import binding_status
    binding=binding_status(directory)
    return {'binding':binding,'policy': POLICY, 'role': value['role'], 'state': state,
            'active_seconds': None if uncertain else round(total, 3),
            'confirmed_closed_seconds': round(closed, 3),
            'active_segment':opened,
            'wall_seconds': round(wall, 3) if wall is not None else None,
            'excluded_seconds': round(max(0,wall-total), 3) if wall is not None and not uncertain else None,
            'remaining_seconds': remaining,
            'deadline_policy':value.get('deadline_policy'),'target_seconds':value.get('target_seconds'),
            'original_deadline_policy':original_policy,'original_limit_seconds':original_limit,
            'clock_origin':value['created'] if hard else None,
            'schedule_stage':stage,'optional_work_allowed':stage=='PRODUCE',
            'deadline_includes_pauses':delivery,
            'delivery_schedule':value.get('delivery_schedule'),
            'delivery_due_wall':value['created']['wall']+value['limit_seconds'] if delivery else None,
            'delivery_reserve_seconds':min(1800,value['limit_seconds']*.125) if delivery else 0,
            'schedule_actions':({'PRODUCE':['reuse_verified_inputs','generate_ready_panels','incremental_review_and_delivery'],
              'CONVERGE':['stop_optional_work','repair_common_causes_once','clear_returned_image_review_queue','prepare_delivery_index'],
              'TARGET_OVERRUN':['continue_required_generation_and_review','diagnose_repeated_work','reuse_verified_inputs','incremental_delivery'],
              'DRAIN':['no_new_calls','save_returns','finish_available_review','publish_current_package'],
              'PACKAGE':['no_new_calls','publish_current_package','list_missing_and_unknown'],
              'HARD_STOP':['no_new_steps','preserve_inflight_identity','save_late_returns_only','preserve_existing_delivery','report_incomplete_scope']}[stage]),
            'new_calls_allowed':state=='RUNNING' and remaining is not None and remaining>0 and stage not in {'DRAIN','PACKAGE','HARD_STOP'},
            'target_remaining_seconds':max(0,round(value['target_seconds']-total,3)) if hard and not uncertain else None,
            'limit_seconds': value['limit_seconds'], 'time_error': uncertain,
            'hook_event_observed': hook_seen, 'last_interrupt_wall': last_interrupt,
            'automatic_pause_verified': False,
            'note': 'hook_event_observed is receipt evidence, not proof of all lifecycle events; trust and real UI test required'}

def locate(path):
    path = Path(path).resolve()
    for parent in [path if path.is_dir() else path.parent, *path.parents]:
        candidate = parent/'00_任务协调'
        if (candidate/'runtime-clock.json').is_file() or (candidate/'execution-context.json').is_file(): return candidate
    return None

def require_running(path):
    context = execution_context(path)
    if context and not context['clock_required']:
        if (Path(context['clock_directory'])/'runtime-clock.json').exists():
            raise ValueError('CLOCK_CONTEXT_CONFLICT: disabled context has a clock ledger')
        return {'state': 'DISABLED', 'run_id': context['run_id']}
    directory = Path(context['clock_directory']) if context else locate(path)
    if directory is None: return None  # Legacy RVs remain unchanged.
    if not (directory/'runtime-clock.json').is_file(): raise ValueError('CLOCK_REQUIRED_LEDGER_MISSING')
    value = status(directory)
    if context:
        if (value['role'] != context['role'] or value['original_limit_seconds'] != context['limit_seconds'] or
            value.get('original_deadline_policy')!=context.get('deadline_policy') or
            value.get('delivery_schedule')!=context.get('delivery_schedule')):
            raise ValueError('CLOCK_CONTEXT_SCOPE_MISMATCH')
        if context.get('deadline_policy') in DEADLINE_POLICIES and (
            context.get('clock_origin')!=value['clock_origin']):
            raise ValueError('DEADLINE_ORIGIN_CHANGED')
        from runtime_clock_context import require_bound
        if context.get('delivery_schedule')!=DELIVERY_SCHEDULE:require_bound(directory)
    if value['state'] != 'RUNNING': raise ValueError('RUNTIME_CLOCK_'+value['state'])
    if (directory/'clock-session.json').exists():
        from runtime_clock_context import require_bound
        require_bound(directory)
    if value['remaining_seconds'] <= 0: raise ValueError('RUNTIME_CLOCK_LIMIT_REACHED: save returns and report; no new calls')
    return value

def require_step(path, action=None, *, optional=False):
    """New hard-deadline runs only; preserve legacy return/review behavior."""
    context=execution_context(path)
    directory=Path(context['clock_directory']) if context else locate(path)
    if directory is None or not (directory/'runtime-clock.json').is_file():
        if context and context.get('deadline_policy') in DEADLINE_POLICIES:raise ValueError('CLOCK_REQUIRED_LEDGER_MISSING')
        return None
    if context:
        if context.get('deadline_policy') not in DEADLINE_POLICIES:return None
    else:
        marker=json.loads((directory/'runtime-clock.json').read_text(encoding='utf-8')).get('deadline_policy')
        if marker is None:return None
        if marker not in DEADLINE_POLICIES:raise ValueError('UNKNOWN_DEADLINE_POLICY')
    try:value=require_running(path)
    except ValueError as exc:
        if action!='preserve-delivery' or 'RUNTIME_CLOCK_LIMIT_REACHED' not in str(exc):raise
        value=status(directory)
        if value['state'] not in {'RUNNING','FINISHED'}:raise
    if optional and value['schedule_stage']!='PRODUCE':
        raise ValueError('RUNTIME_CONVERGE: optional work stopped; finish required review and delivery')
    return value


def require_dispatch(path):
    value=require_running(path)
    if value and not value.get('new_calls_allowed',True):
        raise ValueError('RUNTIME_DELIVERY_DRAIN: reserve time for returned images and package; no new calls')
    return value


def registry(home=None):
    return Path(home or os.environ.get('CODEX_HOME', Path.home()/'.codex'))/'skill-bundles/vertical-comic-skills/clock-bindings'

def binding_path(session, home=None):
    if not session: raise ValueError('explicit host session/thread id required')
    return registry(home)/(hashlib.sha256(session.encode()).hexdigest()+'.json')

def bind(directory, session, home=None, *, identity_source='explicit'):
    directory=Path(directory).resolve()
    if not (directory/'runtime-clock.json').is_file():raise ValueError('clock not initialized')
    path=binding_path(session,home);path.parent.mkdir(parents=True,exist_ok=True)
    with file_lock(path.parent/'bindings.lock'):
        pointer=directory/'clock-session.json'
        if pointer.exists():
            existing=json.loads(pointer.read_text(encoding='utf-8'))
            if existing.get('active') and existing['session_id']!=session:
                raise ValueError('CLOCK_RUN_ALREADY_BOUND: explicit handoff required')
        if path.exists():
            old=json.loads(path.read_text(encoding='utf-8'))
            if old['directory']!=str(directory):
                if status(old['directory'])['state']!='FINISHED':
                    raise ValueError('CLOCK_SESSION_ALREADY_BOUND: explicitly unbind old task')
                _release_locked(Path(old['directory']),session,home)
        value={'policy':POLICY,'session_id':session,'directory':str(directory),
               'identity_source':identity_source,'active':True,'bound_at':time.time(),
               'codex_home':str(registry(home).parents[2])}
        atomic_json(pointer,value)
        atomic_json(path,value)
    return {'binding':str(path),'session_bound':True,'identity_source':identity_source,
            'automatic_pause_verified':False}

def _release_locked(directory, session, home=None):
    path=binding_path(session,home)
    if path.exists():
        old=json.loads(path.read_text(encoding='utf-8'))
        if old['directory']!=str(directory.resolve()):raise ValueError('CLOCK_BINDING_SCOPE_CONFLICT')
        archive=path.parent/'history';archive.mkdir(exist_ok=True)
        atomic_json(archive/(uuid.uuid4().hex+'.json'),{**old,'released_at':time.time()})
        path.unlink()
    pointer=directory/'clock-session.json'
    if pointer.exists():
        old=json.loads(pointer.read_text(encoding='utf-8'))
        if old['session_id']==session:atomic_json(pointer,{**old,'active':False,'released_at':time.time()})

def release(directory, session=None, home=None):
    directory=Path(directory).resolve();pointer=directory/'clock-session.json'
    if session is None:
        if not pointer.is_file():return
        session=json.loads(pointer.read_text(encoding='utf-8'))['session_id']
    if home is None and pointer.is_file():home=json.loads(pointer.read_text(encoding='utf-8')).get('codex_home')
    root=registry(home);root.mkdir(parents=True,exist_ok=True)
    with file_lock(root/'bindings.lock'):_release_locked(directory,session,home)

def attach_current(directory, *, home=None, explicit_session=None):
    from runtime_clock_context import resolve
    context=resolve(home,explicit_session=explicit_session)
    result=bind(directory,context['session_id'],home,identity_source='host:PreToolUse+CODEX_THREAD_ID')
    return {**result,'effective_from':time.time(),'history_recalculated':False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['init','start','pause','resume','wait_user','finish','uncertain','status','bind','attach','unbind','check-submit','amend-policy'])
    p.add_argument('--directory', required=True); p.add_argument('--role', choices=['preparation','production'])
    p.add_argument('--limit-seconds',type=int,default=HARD_LIMIT_SECONDS); p.add_argument('--event-id'); p.add_argument('--session-id'); p.add_argument('--codex-home')
    p.add_argument('--reason');p.add_argument('--source-ref')
    a=p.parse_args(); directory=Path(a.directory).resolve()
    if a.action=='init': result=initialize(directory,a.role,a.limit_seconds,hard_deadline=True)
    elif a.action=='amend-policy':result=amend_policy(directory,reason=a.reason,source_ref=a.source_ref)
    elif a.action in {'bind','attach'}: result=attach_current(directory,home=a.codex_home,explicit_session=a.session_id)
    elif a.action=='unbind':
        release(directory,a.session_id,a.codex_home)
        result={'status':'UNBOUND'}
    elif a.action=='check-submit':
        result=status(directory)
        if (directory/'clock-session.json').exists():
            from runtime_clock_context import require_bound
            require_bound(directory,a.codex_home)
        if result['state']!='RUNNING' or not result['remaining_seconds'] or not result['new_calls_allowed']: raise ValueError('RUNTIME_CLOCK_NOT_ADMITTED')
    else:
        if a.action=='resume' and (directory/'clock-session.json').exists():
            attach_current(directory,home=a.codex_home,explicit_session=a.session_id)
        if a.action!='status': event(directory,a.action,a.event_id or uuid.uuid4().hex)
        if a.action=='finish':release(directory,home=a.codex_home)
        result=status(directory)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    configure_stdio()
    try: main()
    except (OSError,ValueError,KeyError) as exc:
        print(json.dumps({'status':'CLOCK_ERROR','error':str(exc)},ensure_ascii=False)); raise SystemExit(1)
