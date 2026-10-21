"""Locked, versioned approval registration/revocation, not a short-lock runtime.

These APIs preserve real proof bytes and publish a new index via one state CAS.
They neither interpret user messages nor enable dispatch_consistency capability.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
import copy
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import tempfile

from codex_reference_contract import checked_file, digest, file_session, read_bytes, read_json
from platform_io import atomic_json, file_lock
from dispatch_publication import require_legacy

POLICY = 'locked_authority_v1'
_AUTHORITY = ContextVar('comic_approval_authority', default=None)


def _encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode('utf-8')


def proof_signature(proof):
    # Lookup scope is internal index metadata, not part of the preserved proof.
    return hashlib.sha256(_encoded({k: v for k, v in proof.items() if k != '_lookup_panel_ids'})).hexdigest()


def state_errors(state):
    fields = ('authority_policy', 'authority_revision', 'approval_revocations')
    if not any(k in state for k in fields): return []
    if (state.get('authority_policy') != POLICY or type(state.get('authority_revision')) is not int or
            state['authority_revision'] < 1 or not isinstance(state.get('approval_revocations'), list) or
            state.get('execution_mode') != 'episode_async_v1'):
        return ['AUTHORITY_HOLD: unknown or incomplete authority protocol; do not downgrade']
    chain = state.get('toolchain')
    if (not isinstance(chain, dict) or not isinstance(chain.get('files'), list) or not any(
            isinstance(row, dict) and row.get('path') == 'authority_updates.py' for row in chain['files'])):
        return ['AUTHORITY_HOLD: frozen writers do not declare the authority implementation']
    return []


def _revocations(state, root):
    errors = state_errors(state)
    if errors: raise ValueError(';'.join(errors))
    revoked = set()
    for ref in state.get('approval_revocations', []):
        report = read_json(checked_file(Path(root), ref))
        proof = read_json(checked_file(Path(root), report['approval']))
        if (report.get('policy') != 'approval_revocation_v1' or report.get('status') != 'REVOKED' or
                report.get('book_id') != state['book_id'] or report.get('episode_id') != state['episode_id'] or
                report.get('source_kind') != 'user_message' or
                any(not isinstance(report.get(k), str) or not report[k].strip() for k in ('quote', 'source_locator')) or
                report.get('proof_signature') != proof_signature(proof)):
            raise ValueError('AUTHORITY_HOLD: revocation evidence or scope changed')
        revoked.add(report['proof_signature'])
    return revoked


@contextmanager
def authority_context(state, root, *, enforce=True):
    # No persistent trust: the report, original proof and negative state scope
    # remain part of the caller's normal read transaction.
    value = {'book_id': state.get('book_id'), 'episode_id': state.get('episode_id'),
             'revoked': _revocations(state, root), 'enforce': enforce}
    token = _AUTHORITY.set(value)
    try: yield value
    finally: _AUTHORITY.reset(token)


def authority_scoped(function):
    @wraps(function)
    def wrapped(state, root, *args, **kwargs):
        with file_session(), authority_context(state, root):
            return function(state, root, *args, **kwargs)
    return wrapped


def revocation_token():
    value = _AUTHORITY.get()
    return None if value is None else [value['book_id'], value['episode_id'], value['enforce'], sorted(value['revoked'])]


def revocation_errors(proof, book, episode):
    value = _AUTHORITY.get()
    if (value is None or not value['enforce'] or value['book_id'] != book or
            value['episode_id'] != episode or not isinstance(proof, dict)):
        return []
    return ['APPROVAL_REVOKED: original approval may not authorize a new request'] if proof_signature(proof) in value['revoked'] else []


def _control_path(state):
    context = state.get('parallel_context')
    if context is None: return None
    if not isinstance(context, dict) or not Path(context.get('control_file', '')).is_absolute():
        raise ValueError('AUTHORITY_HOLD: invalid parallel control reference')
    return Path(context['control_file']).resolve()


@contextmanager
def state_write_lock(state_path, *, force_shared=False):
    """Same lock order as reservations/lease changes; legacy remains unchanged.

    Once authority_policy is recorded, every existing owner write joins the
    shared authority lock. A concurrently installed policy cannot be missed by
    an old pre-lock read: reject and require a fresh CAS instead of upgrading
    locks in reverse order.
    """
    path = Path(state_path).resolve()
    initial = read_json(path)
    require_legacy(initial)
    errors = state_errors(initial)
    if errors: raise ValueError(';'.join(errors))
    control = _control_path(initial)
    shared = force_shared or initial.get('authority_policy') == POLICY
    paths = [path.with_suffix('.runtime.lock')]
    if shared and control is not None: paths.append(control.with_suffix('.dispatch.lock'))
    with ExitStack() as stack:
        for lock in sorted(set(paths)): stack.enter_context(file_lock(lock))
        actual = read_json(path)
        if (actual.get('parallel_context') != initial.get('parallel_context') or
                actual.get('authority_policy') != initial.get('authority_policy')):
            raise ValueError('AUTHORITY_PROTOCOL_CHANGED: reread state before retrying; no write performed')
        require_legacy(actual)
        if shared and control is not None:
            require_legacy(read_json(control))
        yield


def _write_once(root, label, raw):
    """Closed temporary -> atomic no-replace hard link; never truncate evidence."""
    folder = Path(root)/'00_输入审计/authority_versions'
    folder.mkdir(exist_ok=True)
    sha = hashlib.sha256(raw).hexdigest(); path = folder/(label+'-'+sha+'.json')
    if folder.is_symlink() or path.is_symlink(): raise ValueError('AUTHORITY_HOLD: linked evidence destination')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('wb', dir=folder, delete=False) as stream:
            temporary = Path(stream.name); stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        try: os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw: raise ValueError('AUTHORITY_HOLD: existing immutable evidence changed')
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)
    return {'path': path.relative_to(root).as_posix(), 'sha256': sha}


def update_approvals(state_path, expected_state_sha256, *, register=(), revoke=()):
    """One episode, one CAS, exact caller-supplied proof and revocation scope.

    register rows: {approval: path/sha ref, phase, panel_ids}.
    revoke rows: {approval: path/sha ref, message: actual user message fields}.
    A revocation tombstone applies to the original proof, including embedded
    copies. Restoring that same proof in an index cannot resurrect its authority.
    """
    from review_policy import PHASES
    from staged_workflow import approval_errors
    from execution_contract import state_errors as execution_errors
    from codex_reference_contract import _FILE_SESSION
    if _FILE_SESSION.get() is not None:
        raise ValueError('AUTHORITY_REQUIRES_OWN_TRANSACTION: cannot commit inside a caller read transaction')
    path = Path(state_path).resolve(); root = path.parent.parent
    if any(not isinstance(rows, (list, tuple)) or any(not isinstance(row, dict) for row in rows)
           for rows in (register, revoke)):
        raise ValueError('AUTHORITY_HOLD: register/revoke must be explicit row lists')
    if not register and not revoke: raise ValueError('AUTHORITY_HOLD: explicit registration or revocation required')
    with state_write_lock(path, force_shared=True):
        if digest(path) != expected_state_sha256: raise ValueError('STATE_CHANGED: authority update not committed')
        state = read_json(path); require_legacy(state)
        if state.get('execution_mode') != 'episode_async_v1': raise ValueError('AUTHORITY_HOLD: only explicit episode runs')
        known = {r['panel_id'] for r in state['panels']}
        pending_proofs = []; pending_revocations = []
        with file_session(), authority_context(state, root) as authority:
            # Never install the authority marker through a newer global entry
            # while an old frozen writer can silently ignore it.
            errors = execution_errors(state, root)
            if errors: raise ValueError(';'.join(errors))
            index = read_json(checked_file(root, state['approval_index'])) if state.get('approval_index') else {
                'policy': 'approval_index_v1', 'book_id': state['book_id'], 'entries': []}
            if (index.get('policy') != 'approval_index_v1' or index.get('book_id') not in (None, state['book_id']) or
                    not isinstance(index.get('entries'), list)):
                raise ValueError('AUTHORITY_HOLD: invalid original approval index')
            for row in register:
                ref = row['approval']; raw = read_bytes(checked_file(root, ref)); proof = json.loads(raw)
                phase = row['phase']; ids = row['panel_ids']
                if (phase not in PHASES or proof.get('phase') not in (None, phase) or not isinstance(ids, list) or
                        not ids or len(set(ids)) != len(ids) or not set(ids) <= known):
                    raise ValueError('AUTHORITY_HOLD: exact phase and local panel scope required')
                if proof.get('panel_ids') is not None and not all(
                        pid in proof['panel_ids'] or state['episode_id']+'-'+pid in proof['panel_ids'] for pid in ids):
                    raise ValueError('AUTHORITY_HOLD: index cannot expand original proof scope')
                errors = approval_errors(proof, root, proof.get('artifacts', []), state['book_id'], state['episode_id'],
                                         phase=phase, panel_ids=ids)
                if errors: raise ValueError(';'.join(errors))
                if not proof.get('artifacts'): raise ValueError('AUTHORITY_HOLD: missing approved versions')
                pending_proofs.append((phase, list(ids), raw, proof_signature(proof)))
            for row in revoke:
                ref = row['approval']; raw = read_bytes(checked_file(root, ref)); proof = json.loads(raw)
                message = row['message']
                if (proof.get('book_id') != state['book_id'] or not (proof.get('episode_id') == state['episode_id'] or
                        state['episode_id'] in proof.get('episode_ids', [])) or
                        message.get('source_kind') != 'user_message' or any(
                            not isinstance(message.get(k), str) or not message[k].strip() for k in ('quote', 'source_locator'))):
                    raise ValueError('AUTHORITY_HOLD: actual scoped user revocation required')
                pending_revocations.append((raw, proof_signature(proof), {k: message[k] for k in ('source_kind', 'quote', 'source_locator')}))
            withdrawn = authority['revoked'] | {signature for _, signature, _ in pending_revocations}
            if any(signature in withdrawn for _, _, _, signature in pending_proofs):
                raise ValueError('APPROVAL_REVOKED: same proof cannot be registered again')
        # Read transaction and dependency recheck finish BEFORE evidence/index/state writes.
        new = copy.deepcopy(state)
        for phase, ids, raw, _ in pending_proofs:
            proof_ref = _write_once(root, 'proof', raw)
            entry = {'book_id': state['book_id'], 'episode_ids': [state['episode_id']],
                     'phase': phase, 'panel_ids': ids, 'approval': proof_ref}
            if entry not in index['entries']: index['entries'].append(entry)
        revocations = list(new.get('approval_revocations', []))
        for raw, signature, message in pending_revocations:
            proof_ref = _write_once(root, 'proof', raw)
            report = {'policy': 'approval_revocation_v1', 'status': 'REVOKED', **message,
                      'book_id': state['book_id'], 'episode_id': state['episode_id'],
                      'approval': proof_ref, 'proof_signature': signature}
            report_ref = _write_once(root, 'revocation', _encoded(report))
            if report_ref not in revocations: revocations.append(report_ref)
        new['approval_index'] = _write_once(root, 'approval-index', _encoded(index))
        new.update(authority_policy=POLICY, authority_revision=state.get('authority_revision', 0)+1,
                   approval_revocations=revocations)
        if digest(path) != expected_state_sha256: raise ValueError('STATE_CHANGED: authority update not committed')
        atomic_json(path, new)
        return {'status': 'AUTHORITY_UPDATED', 'state_sha256': digest(path),
                'authority_revision': new['authority_revision'], 'registered': len(pending_proofs),
                'revoked': len(pending_revocations), 'image_calls': 0, 'short_lock_enabled': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True); parser.add_argument('--expected-state-sha256', required=True)
    parser.add_argument('--changes', required=True, help='Explicit register/revoke rows; does not interpret messages')
    args = parser.parse_args(); changes = read_json(Path(args.changes))
    if not isinstance(changes, dict) or not set(changes) <= {'register', 'revoke'}:
        raise ValueError('AUTHORITY_HOLD: unknown change fields')
    print(json.dumps(update_approvals(args.state, args.expected_state_sha256, **changes), ensure_ascii=False))


if __name__ == '__main__':
    from platform_io import configure_stdio
    # Validators import authority_updates by name. Run that same module's
    # entrypoint so the CLI and validators cannot own different ContextVars.
    from authority_updates import main as module_main
    configure_stdio()
    try: module_main()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'HOLD', 'errors': [str(exc)], 'image_calls': 0}, ensure_ascii=False))
        raise SystemExit(1)
