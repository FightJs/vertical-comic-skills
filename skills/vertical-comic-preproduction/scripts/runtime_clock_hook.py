#!/usr/bin/env python3
"""Trusted host Interrupt adapter. No production locks, approvals or tool calls."""
import json, sys, uuid
from runtime_clock import binding_path, event

def handle(payload, home=None):
    session=payload.get('session_id')
    if not session: return {'status':'UNBOUND'}
    path=binding_path(session,home)
    if not path.is_file(): return {'status':'UNBOUND'}
    bound=json.loads(path.read_text(encoding='utf-8'))
    if bound['session_id']!=session: raise ValueError('session mismatch')
    name=payload.get('hook_event_name')
    if name=='Interrupt':
        # Timestamp is receipt time, not an invented exact UI click timestamp.
        event(bound['directory'],'pause',f"interrupt:{payload.get('turn_id') or uuid.uuid4().hex}",source='hook:Interrupt')
    elif name=='SessionEnd':
        event(bound['directory'],'uncertain',f"session-end:{uuid.uuid4().hex}",source='hook:SessionEnd')
    return {'status':'RECORDED'}

if __name__=='__main__':
    try: handle(json.load(sys.stdin))
    except Exception:
        print(json.dumps({'systemMessage':'Comic runtime clock hook failed; pause time needs reconciliation.'}))
        raise SystemExit(1)
