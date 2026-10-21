"""CAS coordinator stop/resume controls; no owner, capacity or budget changes."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import copy
import json
from pathlib import Path

from codex_reference_contract import digest, read_json, file_session
from dispatch_publication import require_legacy
from platform_io import atomic_json, file_lock, portable_relative

POLICY = 'locked_control_v1'


def errors(control):
    if not any(k in control for k in ('control_update_policy', 'control_revision')): return []
    if (control.get('control_update_policy') != POLICY or type(control.get('control_revision')) is not int or
            control['control_revision'] < 1):
        return ['CONTROL_UPDATE_HOLD: unknown or incomplete control policy']
    return []


def update(control_path, expected_control_sha256, expected_states, changes, *, reason):
    """All initialized episode lease owners are locked in reservation order.

    expected_states is job_id -> exact current state SHA256. Membership, owners,
    leases, references, capacities and permits cannot change through this API.
    Cancellation is not silently undone. Resuming a technical dispatch pause
    does not grant approval; normal gates still run.
    """
    from authority_updates import state_errors
    from execution_contract import state_errors as execution_errors
    from codex_reference_contract import _FILE_SESSION
    if _FILE_SESSION.get() is not None: raise ValueError('CONTROL_UPDATE_REQUIRES_OWN_TRANSACTION')
    if (not isinstance(changes, dict) or not changes or not set(changes) <= {'cancelled', 'holds', 'jobs'} or
            not isinstance(reason, str) or not reason.strip() or not isinstance(expected_states, dict)):
        raise ValueError('CONTROL_UPDATE_HOLD: explicit allowed changes, states and reason required')
    path = Path(control_path).resolve(); initial = read_json(path); require_legacy(initial)
    if errors(initial): raise ValueError(';'.join(errors(initial)))
    if initial.get('dispatch_policy') != 'episode_slot_lease_v1':
        raise ValueError('CONTROL_UPDATE_HOLD: only initialized episode lease runs; legacy coordinator stays unchanged')
    jobs = initial.get('jobs', [])
    if set(expected_states) != {j['job_id'] for j in jobs}: raise ValueError('CONTROL_UPDATE_HOLD: exact job coverage required')
    states = []
    for job in jobs:
        root = Path(job['root']).resolve(); name = job.get('state_file', '00_输入审计/生产流程.json')
        portable_relative(name); state_path = (root/name).resolve()
        if not state_path.is_relative_to(root) or not state_path.is_file():
            raise ValueError('CONTROL_UPDATE_HOLD: owner state missing or outside root')
        states.append((job, state_path))
    locks = sorted({path.with_suffix('.dispatch.lock'), *(p.with_suffix('.runtime.lock') for _, p in states)})
    with ExitStack() as stack:
        for lock in locks: stack.enter_context(file_lock(lock))
        if digest(path) != expected_control_sha256: raise ValueError('CONTROL_CHANGED: no update committed')
        with file_session():
            control = read_json(path); require_legacy(control)
            for job, state_path in states:
                if digest(state_path) != expected_states[job['job_id']]: raise ValueError('STATE_CHANGED: '+job['job_id'])
                state = read_json(state_path); require_legacy(state)
                context = state.get('parallel_context', {})
                if (state.get('execution_mode') != 'episode_async_v1' or
                        state.get('runtime', {}).get('dispatch_policy') != 'episode_slot_lease_v1' or
                        state.get('book_id') != control.get('book_id') or state.get('episode_id') != job['episode_id'] or
                        Path(context.get('control_file', '')).resolve() != path or any(
                            context.get(k) != v for k, v in {'job_id': job['job_id'], 'worker_id': job['worker_id'], 'epoch': control['epoch']}.items())):
                    raise ValueError('CONTROL_UPDATE_HOLD: owner/scope mismatch')
                issues = state_errors(state)+execution_errors(state, state_path.parent.parent)
                if issues: raise ValueError(';'.join(issues))
            new = copy.deepcopy(control)
            if 'cancelled' in changes:
                if type(changes['cancelled']) is not bool or control.get('cancelled') is True and changes['cancelled'] is False:
                    raise ValueError('CONTROL_UPDATE_HOLD: cancellation cannot be silently resumed')
                new['cancelled'] = changes['cancelled']
            if 'holds' in changes:
                if not isinstance(changes['holds'], list): raise ValueError('CONTROL_UPDATE_HOLD: holds must be a list')
                new['holds'] = copy.deepcopy(changes['holds'])
            updates = changes.get('jobs', {})
            if not isinstance(updates, dict) or not set(updates) <= set(expected_states):
                raise ValueError('CONTROL_UPDATE_HOLD: unknown job')
            for job in new['jobs']:
                fields = updates.get(job['job_id'], {})
                if not isinstance(fields, dict) or not set(fields) <= {'dispatch_pause', 'holds'}:
                    raise ValueError('CONTROL_UPDATE_HOLD: owner/capacity/permit/input changes require their own protocol')
                if 'dispatch_pause' in fields and type(fields['dispatch_pause']) is not bool:
                    raise ValueError('CONTROL_UPDATE_HOLD: dispatch_pause must be boolean')
                if 'holds' in fields and not isinstance(fields['holds'], list): raise ValueError('CONTROL_UPDATE_HOLD: holds must be a list')
                job.update(copy.deepcopy(fields))
        new.update(control_update_policy=POLICY, control_revision=control.get('control_revision', 0)+1,
                   last_control_reason=reason)
        atomic_json(path, new)
    return {'status': 'CONTROL_UPDATED', 'control_sha256': digest(path), 'control_revision': new['control_revision'],
            'image_calls': 0, 'user_approval': 'NOT_GRANTED', 'short_lock_enabled': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control', required=True); parser.add_argument('--expected-control-sha256', required=True)
    parser.add_argument('--expected-states', required=True); parser.add_argument('--changes', required=True); parser.add_argument('--reason', required=True)
    args = parser.parse_args()
    print(json.dumps(update(args.control, args.expected_control_sha256, read_json(Path(args.expected_states)),
                            read_json(Path(args.changes)), reason=args.reason), ensure_ascii=False))


if __name__ == '__main__':
    from platform_io import configure_stdio
    configure_stdio()
    try: main()
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({'status': 'HOLD', 'errors': [str(exc)], 'image_calls': 0}, ensure_ascii=False)); raise SystemExit(1)
