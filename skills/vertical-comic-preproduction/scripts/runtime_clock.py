#!/usr/bin/env python3
"""Task wall-time budget excluding explicit pauses. Never an image-call ledger."""
from pathlib import Path
import argparse, hashlib, json, os, platform, subprocess, time, uuid
from functools import lru_cache
from platform_io import atomic_json, file_lock, configure_stdio

POLICY = 'active_runtime_clock_v1'

@lru_cache(maxsize=1)
def boot_id():
    try:
        p = Path('/proc/sys/kernel/random/boot_id')
        if p.is_file(): return p.read_text().strip()
        if platform.system() == 'Darwin':
            return subprocess.check_output(['sysctl', '-n', 'kern.boottime'], timeout=.3, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.SubprocessError): pass
    return None  # No guessed boot identity on unsupported hosts.

def instant():
    return {'wall': time.time(), 'mono': time.monotonic(),
            'host': platform.node(), 'boot': boot_id()}

def elapsed(a, b):
    if a['host'] != b['host'] or (a['boot'] and b['boot'] and a['boot'] != b['boot']):
        raise ValueError('CLOCK_TIME_UNCERTAIN: host/boot identity unavailable or changed')
    delta = b['mono'] - a['mono']
    if delta < 0 or abs((b['wall']-a['wall'])-delta) > 2:
        raise ValueError('CLOCK_TIME_UNCERTAIN: system clock changed')
    return delta

def initialize(directory, role, limit=14400, *, at=None):
    directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=True)
    if role not in {'preparation', 'production'} or type(limit) is not int or limit < 1:
        raise ValueError('invalid role/limit')
    with file_lock(directory/'clock.lock'):
        path = directory/'runtime-clock.json'
        if path.exists():
            old = json.loads(path.read_text(encoding='utf-8'))
            if old['role'] != role or old['limit_seconds'] != limit: raise ValueError('CLOCK_SCOPE_CONFLICT')
        else:
            atomic_json(path, {'policy': POLICY, 'role': role, 'limit_seconds': limit,
                              'created': at or instant(), 'events': []})
    return status(directory, at=at)

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
    same_boot = len({(e['at']['host'], e['at']['boot']) for e in events}) <= 1
    events.sort(key=lambda e: (e['at']['mono'] if same_boot else e['at']['wall'], e['event_id']))
    value['events'] = events
    atomic_json(directory/'runtime-clock.json', value)
    return value

def status(directory, *, at=None):
    directory = Path(directory).resolve()
    with file_lock(directory/'clock.lock'):
        value = _read(directory)
    now = at or instant()
    state = 'NOT_STARTED'; opened = None; total = 0.; uncertain = None
    last_interrupt = None; hook_seen = False
    try:
        for e in value['events']:
            action = e['action']; stamp = e['at']
            if e['source'].startswith('hook:'):
                hook_seen = True
                if action == 'pause': last_interrupt = stamp['wall']
            if action == 'hook_probe': continue
            if action == 'uncertain': raise ValueError('CLOCK_TIME_UNCERTAIN: unclean lifecycle')
            if state == 'FINISHED':
                if action == 'pause' and e['source']=='hook:Interrupt':continue
                raise ValueError('CLOCK_EVENT_AFTER_FINISH')
            if action in {'start','resume'}:
                if opened is None: opened = stamp
                state = 'RUNNING'
            elif action in {'pause','wait_user','finish'}:
                if opened is not None: total += elapsed(opened, stamp); opened = None
                state = {'pause':'PAUSED','wait_user':'WAIT_USER','finish':'FINISHED'}[action]
        if opened is not None: total += elapsed(opened, now)
    except ValueError as exc:
        uncertain = str(exc); state = 'TIME_UNCERTAIN'
    try: wall = elapsed(value['created'], now)
    except ValueError: wall = None
    from runtime_clock_context import binding_status
    binding=binding_status(directory)
    return {'binding':binding,'policy': POLICY, 'role': value['role'], 'state': state,
            'active_seconds': None if uncertain else round(total, 3),
            'confirmed_closed_seconds': round(total, 3) if opened is None else None,
            'wall_seconds': round(wall, 3) if wall is not None else None,
            'excluded_seconds': round(max(0,wall-total), 3) if wall is not None and not uncertain else None,
            'remaining_seconds': round(max(0,value['limit_seconds']-total),3) if not uncertain else None,
            'limit_seconds': value['limit_seconds'], 'time_error': uncertain,
            'hook_event_observed': hook_seen, 'last_interrupt_wall': last_interrupt,
            'automatic_pause_verified': False,
            'note': 'hook_event_observed is receipt evidence, not proof of all lifecycle events; trust and real UI test required'}

def locate(path):
    path = Path(path).resolve()
    for parent in [path if path.is_dir() else path.parent, *path.parents]:
        candidate = parent/'00_任务协调'
        if (candidate/'runtime-clock.json').is_file(): return candidate
    return None

def require_running(path):
    directory = locate(path)
    if directory is None: return None  # Legacy RVs remain unchanged.
    value = status(directory)
    if value['state'] != 'RUNNING': raise ValueError('RUNTIME_CLOCK_'+value['state'])
    if (directory/'clock-session.json').exists():
        from runtime_clock_context import require_bound
        require_bound(directory)
    if value['remaining_seconds'] <= 0: raise ValueError('RUNTIME_CLOCK_LIMIT_REACHED: save returns and report; no new calls')
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
    p.add_argument('action', choices=['init','start','pause','resume','wait_user','finish','uncertain','status','bind','attach','unbind','check-submit'])
    p.add_argument('--directory', required=True); p.add_argument('--role', choices=['preparation','production'])
    p.add_argument('--limit-seconds',type=int,default=14400); p.add_argument('--event-id'); p.add_argument('--session-id'); p.add_argument('--codex-home')
    a=p.parse_args(); directory=Path(a.directory).resolve()
    if a.action=='init': result=initialize(directory,a.role,a.limit_seconds)
    elif a.action in {'bind','attach'}: result=attach_current(directory,home=a.codex_home,explicit_session=a.session_id)
    elif a.action=='unbind':
        release(directory,a.session_id,a.codex_home)
        result={'status':'UNBOUND'}
    elif a.action=='check-submit':
        result=status(directory)
        if (directory/'clock-session.json').exists():
            from runtime_clock_context import require_bound
            require_bound(directory,a.codex_home)
        if result['state']!='RUNNING' or not result['remaining_seconds']: raise ValueError('RUNTIME_CLOCK_NOT_ADMITTED')
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
