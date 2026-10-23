#!/usr/bin/env python3
"""Host identity receipts and fast Interrupt events; no production or network calls."""
import json, sys, uuid
from runtime_clock import binding_path, event
from runtime_clock_context import observe

def handle(payload, home=None):
    session=payload.get('session_id')
    if not isinstance(session,str) or not session:return {'status':'UNBOUND'}
    path=binding_path(session,home)
    name=payload.get('hook_event_name')
    if name=='PreToolUse':
        tool_input=json.dumps(payload.get('tool_input',{}),ensure_ascii=False)
        relevant=path.is_file() or any(x in tool_input for x in (
            'comic_start','runtime_clock','task_coordination','comic-clock-context'))
        if relevant:observe(payload,home)
        return {'status':'CONTEXT_RECORDED' if relevant else 'UNRELATED'}
    if name=='SessionStart':
        observe(payload,home);return {'status':'SESSION_OBSERVED'}
    if name!='Interrupt' or not path.is_file():return {'status':'UNBOUND'}
    bound=json.loads(path.read_text(encoding='utf-8'))
    if bound['session_id']!=session:raise ValueError('session mismatch')
    # Receipt time, not an invented exact button-click timestamp. Never wait on clock.lock.
    event(bound['directory'],'pause',f"interrupt:{payload.get('turn_id') or uuid.uuid4().hex}",source='hook:Interrupt')
    return {'status':'RECORDED'}

if __name__=='__main__':
    try:handle(json.load(sys.stdin))
    except Exception as exc:
        print(json.dumps({'systemMessage':'Comic clock hook failed: '+str(exc)+'; automatic pause is not confirmed.'}))
        raise SystemExit(1)
