"""Closed read-set snapshots and candidate bindings; no production activation.

Logical paths and original approval bytes are preserved. Replaying a snapshot
executes the gates again; it never reuses a stored PASS or falls back to live data.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

import codex_reference_contract as contract
import dispatch_publication as publication

POLICY = 'immutable_read_set_v1'


def _key(kind, path, options=()):
    return publication._bytes([kind, os.path.abspath(path), options]).decode('utf-8')


def _tuples(value):
    return tuple(_tuples(v) for v in value) if isinstance(value, list) else value


def _run(state_path, check, requested):
    from staged_workflow import evaluate
    from parallel_dispatch import context_errors
    state = contract.read_json(state_path); root = Path(state_path).parent.parent
    context = state.get('parallel_context')
    if context is not None:
        errors = context_errors(context, root, state['book_id'], state['episode_id'])
        if errors: raise ValueError(';'.join(errors))
    return state, evaluate(state, root, check, requested)


def capture(state_path, store, *, check='reservation_batch', requested=None):
    """Capture observed bytes AND exact queries, then publish after read recheck.

    Unobserved branches are not implicitly covered. A replay needing an extra
    path, query, scan filter or permission mode must fail and be recaptured.
    """
    if contract._FILE_SESSION.get() is not None or contract._READ_VIEW.get() is not None:
        raise ValueError('READ_SET_REQUIRES_OWN_TRANSACTION')
    state_path = Path(state_path).resolve()
    if check not in {'status', 'reservation_batch', 'candidate_batch', 'generate_batch', 'input_audit_batch'}:
        raise ValueError('READ_SET_CHECK_UNSUPPORTED')
    if requested is None and check == 'reservation_batch':
        requested = {'limit': len(contract.read_json(state_path)['panels']), 'excluded': []}
    files = {}
    from source_input_contract import strict_reads
    from validation_pool import session as pool_session
    with strict_reads(), pool_session(None), contract.file_session() as memo:
        state, result = _run(state_path, check, requested)
        # Files are already content-validated by the real gate, not a guessed
        # traversal of arbitrary JSON. Include failures/negative queries too.
        for logical in tuple(memo['files']):
            raw = contract.read_bytes(logical)
            name = 'data/'+hashlib.sha256(logical.encode('utf-8')).hexdigest()
            files[name] = raw
        mapping = [{'logical': name, 'stored': 'data/'+hashlib.sha256(name.encode('utf-8')).hexdigest(),
                    'sha256': memo['files'][name][1]} for name in sorted(memo['files'])]
    # memo observations include the transaction's successful final recheck.
    metadata = {'policy': POLICY, 'read_policy': contract.READ_POLICY,
                'scope': {'book_id': state['book_id'], 'episode_id': state['episode_id']},
                'state_path': str(state_path), 'check': check, 'requested': requested,
                'toolchain': state.get('toolchain'), 'files': mapping,
                'observations': [[kind, path, options, value] for (kind, path, options), value
                                 in sorted(memo['observations'].items(), key=lambda item: repr(item[0]))]}
    files['read-set.json'] = publication._bytes(metadata)
    ref = publication.publish(store, metadata['scope'], files)
    return {'policy': POLICY, 'store': str(Path(store).resolve()), **ref,
            'check': check, 'captured_files': len(mapping), 'captured_queries': len(metadata['observations']),
            'captured_state_sha256': next(row['sha256'] for row in mapping if row['logical'] == str(state_path)),
            'result': result, 'dispatch_authorized': False, 'image_calls': 0}


class ReadView:
    def __init__(self, ref):
        if ref.get('policy') != POLICY: raise ValueError('READ_SET_POLICY_HOLD')
        self.store = Path(ref['store']).resolve(); self.version = ref['version']; self.failure = None
        manifest = publication.verify(self.store, self.version, ref['scope'])
        self.base = self.store/'versions'/self.version/'files'
        self.metadata = json.loads((self.base/'read-set.json').read_bytes())
        meta = self.metadata
        if (meta.get('policy') != POLICY or meta.get('read_policy') != contract.READ_POLICY or
                meta.get('scope') != ref['scope'] or meta.get('check') not in {
                    'status', 'reservation_batch', 'candidate_batch', 'generate_batch', 'input_audit_batch'}):
            raise ValueError('READ_SET_METADATA_HOLD')
        rows = {row['path']: row for row in manifest['files']}
        self.files = {}; self.physical_paths = set()
        for row in meta['files']:
            logical = row['logical']; stored = row['stored']
            if (not Path(logical).is_absolute() or os.path.abspath(logical) != logical or logical in self.files or
                    stored != 'data/'+hashlib.sha256(logical.encode('utf-8')).hexdigest() or
                    rows.get(stored, {}).get('sha256') != row['sha256']):
                raise ValueError('READ_SET_MAPPING_HOLD')
            self.files[logical] = self.base/stored
            self.physical_paths.add(str(self.base/stored))
        if set(rows) != {'read-set.json', *(row['stored'] for row in meta['files'])}:
            raise ValueError('READ_SET_MAPPING_HOLD: unbound members')
        self.queries = {}
        for kind, path, options, value in meta['observations']:
            if kind not in {'resolve', 'exists', 'is_file', 'is_dir', 'is_symlink', 'directory'}:
                raise ValueError('READ_SET_QUERY_HOLD')
            token = _key(kind, path, options)
            if token in self.queries: raise ValueError('READ_SET_QUERY_HOLD: duplicate query')
            self.queries[token] = _tuples(value)
        from execution_contract import toolchain
        # Real executing tools, not projected bytes, must be this exact version.
        if meta.get('toolchain') != toolchain():
            raise ValueError('READ_SET_TOOLCHAIN_CHANGED: use the original frozen tools')
        self.code_root = Path(__file__).resolve().parent
        self.library_roots = (Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve())

    def fail(self, reason):
        if self.failure is None: self.failure = 'READ_SET_HOLD: '+str(reason)
        raise ValueError(self.failure)

    def check(self):
        if self.failure is not None: raise ValueError(self.failure)

    def query(self, kind, path, options=()):
        self.check(); key = _key(kind, path, options)
        if key not in self.queries: self.fail(f'unrecorded {kind}: {path}; no live fallback')
        return self.queries[key]

    def physical(self, path):
        self.check(); logical = os.path.abspath(path)
        resolved = self.query('resolve', logical, (False,))
        if resolved in self.files: return self.files[resolved]
        if self.queries.get(_key('is_file', logical)) is False or self.queries.get(_key('is_file', resolved)) is False:
            raise FileNotFoundError(logical)
        self.fail('unrecorded file contents: '+logical)

    def authorize_check(self, check, requested):
        if publication._bytes([check, requested]) != publication._bytes([self.metadata['check'], self.metadata['requested']]):
            self.fail('check mode/options changed; capture that exact check separately')

    def audit_io(self, event, args):
        if event == 'open':
            path, mode, flags = args
            if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR) != os.O_RDONLY:
                self.fail('write attempted inside read-only snapshot')
            if isinstance(path, int): self.fail('untracked file descriptor read')
            name = os.path.abspath(os.fsdecode(path)); target = Path(name)
            if name in self.physical_paths: return
            if target.is_relative_to(self.code_root) and target.suffix in {'.py', '.pyc'} and _importing(): return
            # Registered live files must never bypass their projected copies.
            if name in self.files: self.fail('raw live file read: '+name)
            if any(target.is_relative_to(root) for root in self.library_roots): return
            self.fail('untracked raw file read: '+name)
        elif event in {'os.scandir', 'os.listdir'}:
            if args[0] is None or isinstance(args[0], int): self.fail('untracked directory handle')
            path = Path(os.path.abspath(os.fsdecode(args[0])))
            if any(path.is_relative_to(root) for root in self.library_roots): return
            if path == self.code_root and _importing(): return
            self.fail('raw directory scan; use recorded scan_directory')
        elif event in {'os.rename', 'os.remove', 'os.rmdir', 'os.mkdir', 'os.link', 'os.symlink',
                       'subprocess.Popen', 'os.system', 'socket.connect'}:
            self.fail('side effect attempted inside read-only snapshot: '+event)


def _importing():
    frame = sys._getframe(1)
    while frame is not None:
        if frame.f_globals.get('__name__') in {'importlib._bootstrap_external', '_frozen_importlib_external'}: return True
        frame = frame.f_back
    return False


def _audit_hook(event, args):
    view = contract._READ_VIEW.get()
    if view is not None: view.audit_io(event, args)


sys.addaudithook(_audit_hook)


@contextmanager
def session(ref):
    if contract._FILE_SESSION.get() is not None or contract._READ_VIEW.get() is not None:
        raise ValueError('READ_SET_REQUIRES_OWN_TRANSACTION')
    view = ReadView(ref)
    token = contract._READ_VIEW.set(view)
    try:
        with contract.file_session() as memo:
            yield view, memo
            view.check()
    finally: contract._READ_VIEW.reset(token)


def replay(ref):
    with session(ref) as (view, memo):
        state, result = _run(view.metadata['state_path'], view.metadata['check'], copy.deepcopy(view.metadata['requested']))
        stats = {k: memo[k] for k in ('json_parses', 'hash_reads', 'hash_bytes', 'dependency_checks', 'dependency_invalidations')}
    return {'policy': POLICY, 'status': 'SNAPSHOT_REPLAYED_NOT_DISPATCHABLE',
            'scope': {'book_id': state['book_id'], 'episode_id': state['episode_id']},
            'version': ref['version'], 'result': result, 'file_statistics': stats,
            'dispatch_authorized': False, 'image_calls': 0}


def bind(ref, expected_state_sha256, expected_control_sha256, expected_head_sha256):
    """Bind an audited candidate head under the actual state/control locks.

    The head is separate from state: it binds exact whole-file state/control
    bytes without self-referential hashes. A later owner write makes it stale,
    even if that writer has not yet refreshed the head. No short-lock capability
    is inferred from this sidecar existing.
    """
    from authority_updates import state_write_lock
    from platform_io import atomic_json
    if contract._FILE_SESSION.get() is not None or contract._READ_VIEW.get() is not None:
        raise ValueError('READ_SET_REQUIRES_OWN_TRANSACTION')
    with session(ref) as (view, _):
        state, result = _run(view.metadata['state_path'], view.metadata['check'], copy.deepcopy(view.metadata['requested']))
        meta = copy.deepcopy(view.metadata)
    if (meta['check'] != 'reservation_batch' or meta['requested'] != {'limit': len(state['panels']), 'excluded': []}):
        raise ValueError('READ_SET_BIND_HOLD: capture the full reservation scope, not a candidate/limited subset')
    path = Path(meta['state_path']); context = state.get('parallel_context', {})
    if not Path(context.get('control_file', '')).is_absolute(): raise ValueError('READ_SET_BIND_HOLD: explicit parallel context required')
    control = Path(context['control_file']).resolve(); head = path.parent/'input_read_head.json'
    captured = {row['logical']: row['sha256'] for row in meta['files']}
    if captured.get(str(path)) != expected_state_sha256 or captured.get(str(control)) != expected_control_sha256:
        raise ValueError('READ_SET_BIND_HOLD: snapshot does not bind the requested current state/control bytes')
    with state_write_lock(path, force_shared=True):
        if contract.digest(path) != expected_state_sha256 or contract.digest(control) != expected_control_sha256:
            raise ValueError('READ_SET_BIND_CONFLICT: state/control changed; no head committed')
        actual_head = contract.digest(head) if head.exists() else None
        if actual_head != expected_head_sha256: raise ValueError('READ_SET_BIND_CONFLICT: head changed; no retry performed')
        old = contract.read_json(head) if actual_head is not None else None
        if old is not None and (old.get('policy') != 'bound_read_set_candidate_v1' or type(old.get('revision')) is not int or
                old['revision'] < 1 or old.get('scope') != meta['scope'] or
                old.get('state_path') != str(path) or old.get('control_path') != str(control)):
            raise ValueError('READ_SET_BIND_HOLD: unknown current head; do not downgrade')
        current = {'policy': 'bound_read_set_candidate_v1', 'status': 'BOUND_NOT_DISPATCHABLE',
                   'scope': meta['scope'], 'revision': old['revision']+1 if old else 1,
                   'state_path': str(path), 'control_path': str(control),
                   'state_sha256': expected_state_sha256, 'control_sha256': expected_control_sha256,
                   'previous_head_sha256': actual_head,
                   'read_set': {k: ref[k] for k in ('policy', 'store', 'scope', 'version')}}
        atomic_json(head, current)
        token = contract.digest(head)
    return {'status': 'BOUND_NOT_DISPATCHABLE', 'head': str(head), 'head_sha256': token,
            'revision': current['revision'], 'scope': meta['scope'], 'state_sha256': expected_state_sha256,
            'control_sha256': expected_control_sha256, 'dispatch_authorized': False, 'image_calls': 0}



def head_status(state_path):
    """Inspect a candidate binding only; freshness is never dispatch authority.

    This checks current references under owner locks, not every immutable byte.
    The real gate and publication verification must still run before use.
    """
    from authority_updates import state_write_lock
    if contract._FILE_SESSION.get() is not None or contract._READ_VIEW.get() is not None:
        raise ValueError('READ_SET_REQUIRES_OWN_TRANSACTION')
    path = Path(state_path).resolve(); head = path.parent/'input_read_head.json'
    with state_write_lock(path, force_shared=True):
        state = contract.read_json(path)
        if not head.exists():
            return {'status': 'HEAD_MISSING', 'dispatch_authorized': False}
        value = contract.read_json(head)
        control = Path(state.get('parallel_context', {}).get('control_file', '')).resolve()
        if (value.get('policy') != 'bound_read_set_candidate_v1' or
                value.get('status') != 'BOUND_NOT_DISPATCHABLE' or
                type(value.get('revision')) is not int or value['revision'] < 1 or
                value.get('scope') != {'book_id': state['book_id'], 'episode_id': state['episode_id']} or
                value.get('state_path') != str(path) or value.get('control_path') != str(control)):
            raise ValueError('READ_SET_HEAD_HOLD: invalid head binding')
        changed = [name for name, source in (('state', path), ('control', control))
                   if contract.digest(source) != value.get(name+'_sha256')]
        return {'status': 'HEAD_STALE' if changed else 'HEAD_CURRENT_NOT_DISPATCHABLE',
                'changed': changed, 'head_sha256': contract.digest(head),
                'revision': value['revision'], 'dispatch_authorized': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    make = sub.add_parser('capture'); make.add_argument('--state', required=True); make.add_argument('--store', required=True)
    run = sub.add_parser('replay'); run.add_argument('--reference', required=True)
    attach = sub.add_parser('bind'); attach.add_argument('--reference', required=True)
    attach.add_argument('--expected-state-sha256', required=True); attach.add_argument('--expected-control-sha256', required=True)
    attach.add_argument('--expected-head-sha256')
    args = parser.parse_args()
    if args.action == 'capture': value = capture(args.state, args.store)
    elif args.action == 'replay': value = replay(contract.read_json(Path(args.reference)))
    else: value = bind(contract.read_json(Path(args.reference)), args.expected_state_sha256,
                       args.expected_control_sha256, args.expected_head_sha256)
    print(json.dumps(value, ensure_ascii=False))


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    from platform_io import configure_stdio
    configure_stdio()
    # Share the same hook/context implementation with imported validators.
    from immutable_inputs import main as module_main
    try: module_main()
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({'status': 'HOLD', 'errors': [str(exc)], 'dispatch_authorized': False, 'image_calls': 0}, ensure_ascii=False))
        raise SystemExit(1)
