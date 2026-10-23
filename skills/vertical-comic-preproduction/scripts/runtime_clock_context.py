#!/usr/bin/env python3
"""Use exact host hook identity, never recent-directory or title heuristics."""
from pathlib import Path
import hashlib, json, os, time
from platform_io import atomic_json

POLICY='comic_clock_context_v1'

def home_path(home=None):
    return Path(home or os.environ.get('CODEX_HOME',Path.home()/'.codex')).expanduser().resolve()

def context_path(session, home=None):
    return home_path(home)/'skill-bundles/vertical-comic-skills/clock-contexts'/(hashlib.sha256(session.encode()).hexdigest()+'.json')

def observe(payload, home=None):
    session=payload.get('session_id'); turn=payload.get('turn_id')
    if not isinstance(session,str) or not session: return None
    name=payload.get('hook_event_name')
    if name not in {'SessionStart','PreToolUse','Interrupt'}: return None
    path=context_path(session,home);path.parent.mkdir(parents=True,exist_ok=True)
    value={'policy':POLICY,'session_id':session,'turn_id':turn,'event':name,
           'observed_at':time.time(),'cwd':payload.get('cwd')}
    atomic_json(path,value)
    return value

def resolve(home=None, *, explicit_session=None, environ=None, now=None):
    env=os.environ if environ is None else environ
    thread=env.get('CODEX_THREAD_ID')
    if not thread: raise ValueError('CLOCK_CONTEXT_UNAVAILABLE: host thread identity unavailable; no guessed binding')
    if explicit_session is not None and explicit_session!=thread:
        raise ValueError('CLOCK_CONTEXT_MISMATCH: supplied session differs from host thread')
    path=context_path(thread,home)
    if not path.is_file():
        raise ValueError('CLOCK_CONTEXT_UNAVAILABLE: no trusted hook receipt for this thread; review clock hooks then retry')
    value=json.loads(path.read_text(encoding='utf-8'))
    if value.get('policy')!=POLICY or value.get('session_id')!=thread:
        raise ValueError('CLOCK_CONTEXT_MISMATCH')
    age=(time.time() if now is None else now)-value['observed_at']
    if not 0<=age<=600 or value.get('event')!='PreToolUse':
        raise ValueError('CLOCK_CONTEXT_STALE: require fresh PreToolUse identity receipt')
    return value

def bound(directory,home=None):
    from runtime_clock import binding_path
    pointer=Path(directory)/'clock-session.json'
    if not pointer.is_file():return None
    value=json.loads(pointer.read_text(encoding='utf-8'))
    if not value.get('active',True):return None
    path=binding_path(value['session_id'],home or value.get('codex_home'))
    if not path.is_file():return None
    current=json.loads(path.read_text(encoding='utf-8'))
    if current.get('directory')!=str(Path(directory).resolve()):return None
    return current

def require_bound(directory,home=None):
    if not bound(directory,home): raise ValueError('CLOCK_BINDING_MISSING: run has no active session binding')

def binding_status(directory,home=None):
    value=bound(directory,home)
    return {'session_bound':bool(value),'session_id':value.get('session_id') if value else None,
            'identity_source':value.get('identity_source') if value else None,
            'automatic_pause_verified':False}
