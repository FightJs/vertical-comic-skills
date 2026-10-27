"""Explicit immutable-input admission and optimistic lease reservations.

Only cooperative, quiesced writers using exclusive evidence publication are
supported. This is not an automatic migration or an image service adapter.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from contextvars import ContextVar
import copy
import hashlib
import json
from pathlib import Path
import uuid
import time

from codex_reference_contract import digest, read_json, file_session
from platform_io import atomic_json, portable_relative

POLICY = 'managed_immutable_dispatch_v1'
_ACTIVE = ContextVar('managed_dispatch_authority', default=None)


def permitted(value):
    marker = value.get('dispatch_consistency')
    active = _ACTIVE.get()
    return (isinstance(marker, dict) and set(marker) == {'policy', 'admission_id', 'store', 'writer_protocol'}
            and marker.get('policy') == POLICY and marker.get('writer_protocol') == 'exclusive_evidence_v1'
            and isinstance(marker.get('admission_id'), str) and len(marker['admission_id']) == 32
            and isinstance(marker.get('store'), str) and Path(marker['store']).is_absolute()
            and active is not None and marker['admission_id'] in active)


@contextmanager
def authority(paths):
    """Internal gateway scope: exact admitted IDs, never a global bypass."""
    from execution_contract import toolchain
    if _ACTIVE.get() is not None: raise ValueError('MANAGED_HOLD: nested writer gateway')
    bases = {}
    # Close this shared read transaction BEFORE any writer takes owner locks.
    # Actual tools, snapshot metadata and original frozen files reuse hashes
    # within this command; no PASS survives the transaction or process.
    with file_session():
        actual = toolchain()
        for path in paths:
            state = read_json(Path(path))
            marker = state.get('dispatch_consistency')
            if (not isinstance(marker, dict) or state.get('toolchain') != actual or
                    state.get('authority_policy') != 'locked_authority_v1'):
                raise ValueError('MANAGED_HOLD: explicit admission and exact frozen tools required')
            bases[marker.get('admission_id')] = _verify_frozen_basis(state, Path(path).resolve())
    token = _ACTIVE.set(bases)
    try:
        for path in paths:
            if not permitted(read_json(Path(path))): raise ValueError('MANAGED_HOLD: invalid or changed admission')
        yield
    finally: _ACTIVE.reset(token)



def _verify_frozen_basis(state, path):
    """Outside owner locks: reject generators overwriting admitted input bytes.

    New proofs/results use new paths and state references. The four original
    global frozen inputs cannot be hot-swapped within the admitted job.
    """
    from immutable_inputs import ReadView, _tuples
    import codex_reference_contract as contract
    ref=state.get('dispatch_admission',{}).get('base_read_set')
    if not isinstance(ref,dict):raise ValueError('MANAGED_HOLD: missing frozen basis')
    view=ReadView(ref)
    if (view.metadata['scope']!={'book_id':state['book_id'],'episode_id':state['episode_id']} or
            view.metadata['state_path']!=str(path) or state['dispatch_consistency']['store']!=str(path.parent/'immutable_dispatch')):
        raise ValueError('MANAGED_HOLD: frozen basis scope/path mismatch')
    frozen_state=json.loads(view.files[str(path)].read_bytes())
    fixed=('source_script','source_snapshot','visual_basis','shot_manifest','memory_source','runtime_snapshot',
           'runtime','runtime_execution_context','execution_mode','optimization_policy','preparation_policy','readiness_policy',
           'execution_contract','toolchain','parallel_context','production_authorization')
    if any(state.get(key)!=frozen_state.get(key) for key in fixed):
        raise ValueError('MANAGED_HOLD: frozen run identity/input references changed; new run required')
    mutable={str(path),str(Path(state['parallel_context']['control_file']).resolve())}
    with file_session() as memo:
        for row in view.metadata['files']:
            if row['logical'] not in mutable and digest(Path(row['logical'])) != row['sha256']:
                raise ValueError('IMMUTABLE_INPUT_CHANGED: publish a new candidate; do not overwrite admitted inputs')
        for kind,logical,options,value in view.metadata['observations']:
            if logical in mutable:continue
            token=(kind,logical,_tuples(options));memo['observations'][token]=_tuples(value)
            contract.recheck_dependencies([token])
    return view.metadata


def admit(state_path, expected_state, expected_control, *, old_writers_stopped=False,
          immutable_inputs=False, saver_protocol=None, reason=None):
    """Opt in only with no reserved, in-flight or unknown requests.

    Caller attests that generators use new candidate paths and the saving host
    publishes evidence exclusively. No existing runtime is migrated implicitly.
    """
    from authority_updates import state_write_lock
    from execution_contract import state_errors
    from slot_leases import effective_control, ACTIVE
    from dispatch_publication import require_legacy
    path = Path(state_path).resolve(); root = path.parent.parent
    if (old_writers_stopped is not True or immutable_inputs is not True or
            saver_protocol != 'exclusive_evidence_v1' or not isinstance(reason, str) or not reason.strip()):
        raise ValueError('ADMISSION_HOLD: stopped writers, immutable inputs, exclusive saver protocol and reason required')
    capability=read_json(Path(__file__).with_name('runtime_capabilities.json')).get('managed_dispatch',{})
    if capability.get('policy')!=POLICY or capability.get('default_enabled') is not False:
        raise ValueError('ADMISSION_HOLD: explicit compatible capability required')
    initial = read_json(path); require_legacy(initial)
    from immutable_inputs import capture
    base_read_set = capture(path, path.parent/'immutable_dispatch')
    context = initial.get('parallel_context', {}); control_path = Path(context.get('control_file', '')).resolve()
    from immutable_inputs import ReadView
    captured={row['logical']:row['sha256'] for row in ReadView(base_read_set).metadata['files']}
    if captured.get(str(path))!=expected_state or captured.get(str(control_path))!=expected_control:
        raise ValueError('ADMISSION_CONFLICT: captured state/control differs from requested version')
    with state_write_lock(path, force_shared=True):
        if digest(path) != expected_state or digest(control_path) != expected_control: raise ValueError('ADMISSION_CONFLICT')
        with file_session():
            state = read_json(path); control = read_json(control_path)
            issues = state_errors(state, root)
            if issues: raise ValueError(';'.join(issues))
            if control.get('dispatch_policy') != 'episode_slot_lease_v1': raise ValueError('ADMISSION_HOLD: lease mode required')
            effective_control(control, state, context)
            if any(p.get('status') in ACTIVE for p in state.get('dispatch_ledger', [])) or any(
                    p.get('status') in {'IN_FLIGHT', 'RESULT_UNKNOWN'} for p in state['panels']):
                raise ValueError('ADMISSION_HOLD: active/unknown requests belong to the old protocol')
            remaining={r['panel_id'] for r in state['panels'] if r.get('status') not in {'VISUAL_PASS','USER_ACCEPTED'}}
            if not remaining or set(base_read_set['result'].get('ready_panel_ids',[]))!=remaining:
                raise ValueError('ADMISSION_HOLD: only a fully prepared request scope; incomplete/deferred inputs stay on the legacy path')
        new = copy.deepcopy(state)
        new.setdefault('authority_policy', 'locked_authority_v1'); new.setdefault('authority_revision', 1)
        new.setdefault('approval_revocations', [])
        new['dispatch_consistency'] = {'policy': POLICY, 'admission_id': uuid.uuid4().hex,
            'store': str(path.parent/'immutable_dispatch'), 'writer_protocol': saver_protocol}
        new['dispatch_admission'] = {'reason': reason, 'previous_state_sha256': expected_state,
                                    'control_sha256': expected_control, 'old_writers_stopped': True,
                                    'immutable_inputs': True, 'base_read_set': {k: base_read_set[k] for k in ('policy','store','scope','version')}}
        atomic_json(path, new)
    return {'status': 'ADMITTED', 'state_sha256': digest(path), 'image_calls': 0}


def _publish_reads(path, memo):
    """Freeze exact observed inputs after the caller's gate, before commit locks."""
    from dispatch_publication import publish, _bytes
    state = read_json(path); files = {}
    base = _ACTIVE.get()[state['dispatch_consistency']['admission_id']]
    frozen = {row['logical']: row for row in base['files']}
    mutable = {str(path), str(Path(state['parallel_context']['control_file']).resolve())}
    inherited = {}
    for logical in tuple(memo['files']):
        # Share immutable BYTES, never cached validation results. Every inherited
        # object was verified by authority() in this command and its live input
        # hash was checked again by the real gate's read transaction.
        if logical in frozen and logical not in mutable:
            if memo['files'][logical][1] != frozen[logical]['sha256']:
                raise ValueError('IMMUTABLE_INPUT_CHANGED: frozen basis drifted during preflight')
            inherited[logical] = frozen[logical]['stored']
            continue
        from codex_reference_contract import read_bytes
        files['data/'+hashlib.sha256(logical.encode()).hexdigest()] = read_bytes(logical)
    files['reads.json'] = _bytes({'policy': 'composed_dispatch_read_set_v1',
        'base_read_set': state['dispatch_admission']['base_read_set'], 'inherited': inherited,
        'files': {name: item[1] for name, item in memo['files'].items()},
        'observations': [[kind, logical, options, value] for (kind, logical, options), value in memo['observations'].items()]})
    return state, files


def reserve(state_path, expected_state, expected_control, *, max_count=None, request_id,
            max_retries=0):
    """Lock-free full gate; short locked whole-state/control CAS and one ledger write.

    Retry only preflight conflicts, at most two, never image calls. Request IDs
    are persisted with receipts; lost success responses cannot reserve again.
    """
    from runtime_clock import require_dispatch
    require_dispatch(state_path)
    from episode_dispatch_queue import _prepare, _commit, _dispatch_reads, _timed_locks
    from dispatch_publication import publish
    if file_session_active(): raise ValueError('RESERVATION_REQUIRES_OWN_TRANSACTION')
    if (not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128 or
            type(max_retries) is not int or not 0 <= max_retries <= 2 or
            max_count is not None and (type(max_count) is not int or max_count < 1)):
        raise ValueError('MANAGED_HOLD: stable request_id, positive max_count and retry limit 0..2 required')
    path = Path(state_path).resolve()
    metrics = {'policy': 'dispatch_metrics_v2', 'not_authorization': True, 'conflicts': [],
        'discarded_preflights': 0, 'outer_run_lock': 'NONE', 'requested_max_count': max_count,
        'ready_wait': {'policy': 'observed_ready_to_reserve_v1', 'clock': 'perf_counter',
                       'historical_ready_to_reserve_seconds': None, 'panels': []}}
    with authority([path]):
        initial = read_json(path); control = Path(initial['parallel_context']['control_file']).resolve()
        locks = sorted((path.with_suffix('.runtime.lock'), control.with_suffix('.dispatch.lock')))
        for attempt in range(max_retries+1):
            # Idempotent lookup is under the same locks even with stale caller CAS.
            with _timed_locks(locks, metrics):
                current = read_json(path)
                if not permitted(current): raise ValueError('MANAGED_HOLD: admission changed')
                existing = current.get('reservation_requests', {}).get(request_id)
                if existing is not None:
                    if existing.get('max_count') != max_count: raise ValueError('REQUEST_ID_CONFLICT')
                    return {'status': 'ALREADY_RESERVED', **copy.deepcopy(existing),
                            'state_sha256': digest(path), 'control_sha256': digest(control), 'image_calls': 0,
                            'dispatch_metrics': metrics}
            context = current['parallel_context']
            try:
                with _dispatch_reads(metrics) as memo:
                    prepared = _prepare(path, path, control, control, context,
                                        expected_state, expected_control, max_count, metrics)
                    if prepared.get('prepared'):
                        _, files = _publish_reads(path, memo)
            except ValueError as exc:
                actual_state, actual_control = digest(path), digest(control)
                changed = actual_state != expected_state or actual_control != expected_control
                if not changed or not str(exc).startswith(('CHECK_SNAPSHOT_CHANGED', 'STATE_OR_CONTROL_CHANGED')): raise
                metrics['conflicts'].append({'attempt': attempt+1, 'phase': 'read_transaction',
                    'state': actual_state != expected_state, 'control': actual_control != expected_control,
                    'reason': str(exc)})
                metrics['discarded_preflights'] = len(metrics['conflicts'])
                if attempt == max_retries:
                    return {'status': 'PREFLIGHT_CONFLICT', 'reserved': [], 'image_calls': 0,
                            'state_sha256': actual_state, 'control_sha256': actual_control, 'dispatch_metrics': metrics}
                expected_state, expected_control = actual_state, actual_control
                continue
            metrics['discarded_preflights'] = len(metrics['conflicts'])
            if not prepared.get('prepared'): return prepared
            # Publication copies/verification have their own lock, never the
            # shared coordinator lock; no hash traversal is moved into commit.
            publication_started=time.perf_counter()
            reference = publish(current['dispatch_consistency']['store'],
                {'book_id': current['book_id'], 'episode_id': current['episode_id']}, files)
            metrics['publication_seconds']=round(time.perf_counter()-publication_started,6)
            with _timed_locks(locks, metrics):
                state_now = read_json(path)
                existing = state_now.get('reservation_requests', {}).get(request_id)
                if existing is not None:
                    if existing.get('max_count') != max_count: raise ValueError('REQUEST_ID_CONFLICT')
                    return {'status': 'ALREADY_RESERVED', **copy.deepcopy(existing), 'image_calls': 0,
                            'state_sha256': digest(path), 'control_sha256': digest(control), 'dispatch_metrics': metrics}
                actual_state, actual_control = digest(path), digest(control)
                if actual_state != expected_state or actual_control != expected_control:
                    metrics['conflicts'].append({'attempt': attempt+1, 'phase': 'commit_cas', 'state': actual_state != expected_state,
                                                'control': actual_control != expected_control})
                    metrics['discarded_preflights'] = len(metrics['conflicts'])
                    if attempt == max_retries:
                        return {'status': 'PREFLIGHT_CONFLICT', 'reserved': [], 'image_calls': 0,
                                'state_sha256': actual_state, 'control_sha256': actual_control, 'dispatch_metrics': metrics}
                    expected_state, expected_control = actual_state, actual_control
                    continue
                if not permitted(state_now): raise ValueError('MANAGED_HOLD: admission changed')
                prepared['state']['last_dispatch_read_set'] = reference
                value = _commit(prepared, path, control, context, expected_state, metrics, request_id=request_id)
                # max_count is part of the atomically stored request identity.
                return value
    raise AssertionError('bounded retry exhausted without result')


def file_session_active():
    from codex_reference_contract import _FILE_SESSION, _READ_VIEW
    return _FILE_SESSION.get() is not None or _READ_VIEW.get() is not None



def publish_evidence(state_path, relative, source, expected_sha256):
    """Exclusive durable bytes in the original parent; preserve relative bases.

    JSON is never rewritten to invent provenance. Caller supplies actual saved
    evidence and uses this returned reference when composing its next evidence.
    """
    from platform_io import file_lock
    from dispatch_publication import _sha
    import os, tempfile
    path = Path(state_path).resolve(); root = path.parent.parent
    name = portable_relative(relative); parent = root/name.parent
    if not parent.resolve().is_relative_to(root) or any(p.is_symlink() for p in (parent, *parent.parents)):
        raise ValueError('EVIDENCE_HOLD: invalid parent')
    with authority([path]):
        raw = Path(source).read_bytes()
        if _sha(raw) != expected_sha256: raise ValueError('EVIDENCE_HOLD: source changed')
        parent.mkdir(parents=True, exist_ok=True)
        destination = parent/('managed-'+expected_sha256+name.suffix)
        if destination.is_symlink(): raise ValueError('EVIDENCE_HOLD: linked destination')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('wb', dir=parent, delete=False) as stream:
                temporary = Path(stream.name); stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            try: os.link(temporary, destination)
            except FileExistsError:
                if destination.read_bytes() != raw: raise ValueError('EVIDENCE_HOLD: immutable content changed')
        finally:
            if temporary is not None: temporary.unlink(missing_ok=True)
        return {'path': destination.relative_to(root).as_posix(), 'sha256': expected_sha256}



def _versioned(root, ref, base):
    from codex_reference_contract import checked_file
    target=checked_file(root,ref)
    known={row['logical']:row['sha256'] for row in base['files']}
    if known.get(str(target))!=ref['sha256'] and target.name!='managed-'+ref['sha256']+target.suffix:
        raise ValueError('EVIDENCE_HOLD: publish new evidence exclusively before adopting its reference')
    return target


def _validate_updates(path, updates):
    state=read_json(path);root=path.parent.parent
    base=_ACTIVE.get()[state['dispatch_consistency']['admission_id']]
    records={r['panel_id']:r for r in state['panels']}
    with file_session():
        for update in updates:
            old=records[update['panel_id']]
            status=update.get('status')
            fixed=(('package_manifest','output','qa_report','failure_diagnosis') if status=='IN_FLIGHT' else
                   ('package_manifest','output','call_evidence') if status in {'VISUAL_PASS','VISUAL_FAIL'} else ())
            if any(key in update and update[key]!=old.get(key) for key in fixed):
                raise ValueError('EVIDENCE_HOLD: locked execution evidence cannot change during submission or QA')
            for key in ('output','qa_report','call_evidence','package_manifest'):
                ref=update.get(key)
                if ref is None or ref==old.get(key):continue
                target=_versioned(root,ref,base)
                if key=='package_manifest':
                    packet=read_json(target);execution=packet['panels'][0].get('generation_execution',{})
                    for evidence in ('request_evidence','response_evidence'):
                        if evidence not in execution:continue
                        evidence_path=_versioned(target.parent,execution[evidence],base)
                        if evidence=='response_evidence':
                            for output in read_json(evidence_path).get('outputs',[]):
                                _versioned(target.parent,output,base)


def save(state_path, updates, save_id, *, resolution_ref=None):
    """Durable return intent before ledger commit; exact retries are idempotent.

    This accepts actual result/QA evidence, never infers a visual verdict. Only
    state CAS is retried, up to three times; no image request is submitted.
    """
    from platform_io import file_lock
    from dispatch_publication import _bytes, _sha
    path=Path(state_path).resolve()
    if not isinstance(save_id, str) or not save_id.strip(): raise ValueError('SAVE_HOLD: stable save_id required')
    with authority([path]):
        folder=path.parent/'saved_intents';folder.mkdir(exist_ok=True)
        name=_sha(save_id.encode());intent=folder/(name+'.json')
        payload={'policy':'actual_result_intent_v1','save_id':save_id,'updates':updates,'resolution_ref':resolution_ref}
        with file_lock(folder/'intents.lock'):
            if intent.exists():
                if read_json(intent)!=payload:raise ValueError('SAVE_ID_CONFLICT: preserve the original result')
            else:
                _validate_updates(path,updates)
                atomic_json(intent,payload)
        for retry in range(3):
            from production_runtime import commit_updates
            try:
                value=commit_updates(path,digest(path),updates,resolution_ref=resolution_ref)
                return {**value,'intent':str(intent),'image_calls':0}
            except ValueError as exc:
                if not str(exc).startswith('STATE_CHANGED') or retry==2:raise
    raise AssertionError('unreachable')



def submit(state_path, panel_id=None, attempt_id=None, round_id=None, permit_id=None, *, job=None):
    """Use the same durable registration under the admitted writer authority."""
    from runtime_clock import require_dispatch
    require_dispatch(state_path)
    path=Path(state_path).resolve()
    with authority([path]):
        if job is None:
            # Compatibility for existing supported callers; derive actual input,
            # never authorize a caller-supplied stale permit or attempt.
            from codex_reference_contract import checked_file, validate_panel
            from submission_contract import panel_job
            state=read_json(path)
            row=next(r for r in state['panels'] if r['panel_id']==panel_id)
            packet_path=checked_file(path.parent.parent,row['package_manifest'])
            packet=read_json(packet_path)
            errors,plan=validate_panel(packet['panels'][0],packet_path.parent)
            if errors or plan is None:raise ValueError('SUBMISSION_HOLD: '+ ';'.join(errors))
            job=panel_job(state,path.parent.parent,row,packet,plan['arguments'])
            if (job['attempt_id']!=attempt_id or job['round_id']!=round_id or
                (job.get('dispatch_receipt') or {}).get('permit_id')!=permit_id):
                raise ValueError('SUBMISSION_HOLD: exact receipt/attempt required')
        from production_runtime import submit as register
        return register(path,job)


def recover_saved(state_path, intent):
    path=Path(state_path).resolve(); target=Path(intent).resolve()
    if target.parent != path.parent/'saved_intents':raise ValueError('SAVE_HOLD: intent outside this owner')
    value=read_json(target)
    from dispatch_publication import _sha
    if (value.get('policy')!='actual_result_intent_v1' or target.stem!=_sha(value['save_id'].encode())):
        raise ValueError('SAVE_HOLD: invalid intent')
    return save(path,value['updates'],value['save_id'],resolution_ref=value['resolution_ref'])


def coordinator(control_path, action, **kwargs):
    control=read_json(Path(control_path)); paths=[]
    for job in control['jobs']:
        path=Path(job['root'])/job.get('state_file','00_输入审计/生产流程.json')
        if 'dispatch_consistency' in read_json(path):paths.append(path)
    if not paths:raise ValueError('MANAGED_HOLD: no admitted owners')
    with authority(paths):
        if action=='control':
            from control_updates import update
            return update(control_path,**kwargs)
        if action=='allocate':
            from slot_leases import allocate
            return allocate(control_path,**kwargs)
        raise ValueError('MANAGED_HOLD: unsupported coordinator operation')


def call(state_path, action, **kwargs):
    """The supported writer/reader gateway. Existing validators stay intact.

    Non-dispatch updates retain conservative locks. They invalidate an optimistic
    preflight via whole-state/control CAS; there is no local-field relaxation.
    """
    path = Path(state_path).resolve()
    with authority([path]):
        if action == 'compile':
            from production_runtime import compile_jobs
            with file_session():
                state=read_json(path);value=compile_jobs(state,path.parent.parent,**kwargs)
                from codex_reference_contract import checked_file
                for job in value['jobs']:
                    record=next(r for r in state['panels'] if r['panel_id']==job['panel_id'])
                    job['dispatch_receipt']=read_json(checked_file(path.parent.parent,record['package_manifest'])).get('dispatch_receipt')
                    job['managed_submission_required']=True
                return value
        if action == 'recover-no-image':
            from no_image_recovery import recover
            return recover(path, **kwargs)
        if action == 'submission-status':
            from production_runtime import submission_status
            return submission_status(path,kwargs['job'])
        if action == 'commit':
            _validate_updates(path,kwargs['updates'])
            from production_runtime import commit_updates
            return commit_updates(path, **kwargs)
        if action == 'approvals':
            from authority_updates import update_approvals
            return update_approvals(path, **kwargs)
        if action == 'release':
            from slot_leases import release_unsubmitted
            return release_unsubmitted(path, **kwargs)
        if action == 'repair':
            base=_ACTIVE.get()[read_json(path)['dispatch_consistency']['admission_id']]
            root=path.parent.parent;ref={'path':kwargs['authorization_ref'],'sha256':digest(root/kwargs['authorization_ref'])}
            report=read_json(_versioned(root,ref,base))
            for key in ('new_package_manifest','new_shot_subset'):_versioned(root,report[key],base)
            from production_runtime import authorize_episode_repair
            return authorize_episode_repair(path, **kwargs)
        if action == 'diagnosis':
            base=_ACTIVE.get()[read_json(path)['dispatch_consistency']['admission_id']]
            root=path.parent.parent
            _versioned(root,{'path':kwargs['diagnosis_ref'],'sha256':digest(root/kwargs['diagnosis_ref'])},base)
            from production_runtime import record_episode_diagnosis
            return record_episode_diagnosis(path, **kwargs)
        raise ValueError('MANAGED_HOLD: unsupported operation')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--action', choices=('admit', 'reserve', 'compile', 'commit', 'approvals', 'release', 'repair', 'diagnosis', 'evidence', 'save', 'recover', 'submit', 'submission-status', 'recover-no-image', 'control', 'allocate'), required=True)
    parser.add_argument('--arguments', required=True, help='Explicit JSON arguments; never image calls')
    args = parser.parse_args(); kwargs = read_json(Path(args.arguments))
    if args.action == 'admit': value = admit(args.state, **kwargs)
    elif args.action == 'reserve': value = reserve(args.state, **kwargs)
    elif args.action == 'evidence': value = publish_evidence(args.state, **kwargs)
    elif args.action == 'save': value = save(args.state, **kwargs)
    elif args.action == 'submit': value = submit(args.state, **kwargs)
    elif args.action == 'recover': value = recover_saved(args.state, **kwargs)
    elif args.action in {'control','allocate'}:
        value = coordinator(read_json(Path(args.state))['parallel_context']['control_file'],args.action,**kwargs)
    else: value = call(args.state, args.action, **kwargs)
    print(json.dumps(value, ensure_ascii=False))
    if args.action=='reserve':return 0 if value.get('status') in {'RESERVED','ALREADY_RESERVED','CAPACITY_FULL'} else 1
    if args.action=='compile':return 0 if value.get('preflight',{}).get('status') in {'READY','PARTIAL_READY'} else 1
    return 0


if __name__ == '__main__':
    from platform_io import configure_stdio
    configure_stdio()
    from managed_dispatch import main as module_main
    try: raise SystemExit(module_main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'HOLD', 'errors': [str(exc)], 'image_calls': 0}, ensure_ascii=False))
        raise SystemExit(1)
