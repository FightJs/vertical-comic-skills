"""Observed preparation outside locks, original validation and short state CAS.

Only new runs opt in. Legacy and managed-dispatch writers retain their protocols.
No image calls, inferred observations or implicit retry of submissions.
"""
from pathlib import Path
import json,time,uuid
from datetime import datetime,timezone
from codex_reference_contract import read_json,digest,file_session,verify_read_snapshot,_FILE_SESSION
from authority_updates import state_write_lock
from platform_io import atomic_json
from contextlib import contextmanager
from contextvars import ContextVar

POLICY='observed_incremental_pipeline_v1'
_BUDGET=ContextVar('comic_operation_budget',default=None)

@contextmanager
def budget(path,enabled=True):
    from runtime_clock import require_running
    value=require_running(path) if enabled else None
    active={'path':path,'next_check':time.monotonic()+.5} if value and value.get('state')=='RUNNING' else None
    token=_BUDGET.set(active)
    try:
        yield
        if active:require_running(path)
    finally:_BUDGET.reset(token)

def poll_budget():
    value=_BUDGET.get()
    if value is not None and time.monotonic()>=value['next_check']:
        from runtime_clock import require_running
        require_running(value['path'])
        value['next_check']=time.monotonic()+.5

def record(path, action, segments, **details):
    """One immutable event; missing human/service durations remain missing."""
    path=Path(path).resolve();root=path.parent.parent
    folder=root/'00_输入审计/pipeline_metrics';folder.mkdir(parents=True,exist_ok=True)
    value={'policy':POLICY,'action':action,'at':datetime.now(timezone.utc).isoformat(),
           'episode_state':path.relative_to(root).as_posix(),'segments_seconds':segments,
           'image_calls':0,**details}
    name=folder/(uuid.uuid4().hex+'.json')
    atomic_json(name,value)
    return name.relative_to(root).as_posix()

def commit(state_path, expected_sha256, updates, *, resolution_ref=None, submission_job=None):
    from production_runtime import _commit_updates,_persist_updates
    path=Path(state_path).resolve()
    initial=read_json(path)
    if initial.get('runtime_pipeline_policy')!=POLICY or 'dispatch_consistency' in initial:
        return _commit_updates(path,expected_sha256,updates,resolution_ref=resolution_ref,submission_job=submission_job)
    if _FILE_SESSION.get() is not None:raise ValueError('WRITE_REQUIRES_OWN_READ_TRANSACTION')
    started=time.monotonic()
    # Preserve the original validators and their full transitive input set.
    with file_session() as snapshot:
        prepared=_commit_updates(path,expected_sha256,updates,resolution_ref=resolution_ref,
                                 submission_job=submission_job,_prepare_only=True)
    validated=time.monotonic()
    if 'prepared_state' not in prepared:return prepared  # Existing idempotent receipt.
    with state_write_lock(path):
        acquired=time.monotonic()
        verify_read_snapshot(snapshot,refresh_views=False)
        if digest(path)!=expected_sha256:raise ValueError('STATE_CHANGED')
        writing=time.monotonic()
        result=_persist_updates(path,path.parent.parent,expected_sha256,updates,prepared['prepared_state'],
                                prepared['operation'],prepared['submission_record'],prepared['actual'])
        written=time.monotonic()
    ended=time.monotonic()
    segments={'validation':validated-started,'lock_wait':acquired-validated,
              'version_check':writing-acquired,'state_write':written-writing,
              'lock_hold':ended-acquired,'total':ended-started}
    result['pipeline_timing']=segments
    try:result['pipeline_metric']=record(path,'commit',segments,panel_ids=[u['panel_id'] for u in updates])
    except OSError as exc:result['timing_record_error']=str(exc)  # Committed receipt is never lost.
    return result

def reserve(state_reference,path,control_reference,control_path,context,expected_state,
            expected_control,max_count,metrics,locks):
    """Lease-only: stage packets outside shared locks, then one episode state CAS."""
    from episode_dispatch_queue import _prepare,_commit,_timed_locks,_atomic_json
    from runtime_clock import require_dispatch
    started=time.perf_counter()
    with file_session() as snapshot:
        prepared=_prepare(state_reference,path,control_reference,control_path,context,
                          expected_state,expected_control,max_count,metrics)
    if not prepared.get('prepared'):return prepared
    if not prepared['lease_mode']:raise ValueError('PIPELINE_REQUIRES_EPISODE_LEASE')
    staged=_commit(prepared,path,control_path,context,expected_state,metrics,_stage_only=True)
    staged_at=time.perf_counter()
    # CAS failure leaves unpublished orphan evidence, never a reserved request.
    # It cannot authorize an invocation and is not blindly deleted during recovery.
    with _timed_locks(locks,metrics):
        verify_read_snapshot(snapshot,refresh_views=False)
        if digest(path)!=expected_state or digest(control_path)!=expected_control:
            raise ValueError('STATE_OR_CONTROL_CHANGED')
        require_dispatch(path)
        writing=time.perf_counter();_atomic_json(path,staged['new_state'])
        committed=time.perf_counter()
    metrics.update(preflight_seconds=staged_at-started,write_seconds=committed-writing,
                   file_reuse_statistics={k:snapshot[k] for k in ('hash_reads','hash_hits','json_parses','hash_bytes')},
                   audit_reuse_statistics=snapshot['audit_statistics'])
    metrics['ready_wait']['panels']=[{'panel_id':r['panel_id'],
        'observed_ready_to_reserve_seconds':committed-staged['ready_observed'][r['panel_id']]}
        for r in staged['reserved'] if r['panel_id'] in staged['ready_observed']]
    result={'status':'RESERVED','reserved':staged['reserved'],'state_sha256':digest(path),
            'control_sha256':digest(control_path),'image_calls':0,'dispatch_metrics':metrics,
            'next_step':'compile and register the exact job before invoking once'}
    try:result['pipeline_metric']=record(path,'reserve',{
        'preflight_and_packet_stage':staged_at-started,'lock_wait':metrics.get('lock_wait_seconds',0),
        'lock_hold':metrics.get('lock_hold_seconds',0),'state_write':committed-writing})
    except OSError as exc:result['timing_record_error']=str(exc)
    return result

def metrics(state_paths):
    """Diagnostic observed phases only; overlapping intervals must not be added."""
    import statistics
    groups={};warnings=[];count=0
    for path in state_paths:
        folder=Path(path).resolve().parent/'pipeline_metrics'
        for p in sorted(folder.glob('*.json')):
            try:
                value=json.loads(p.read_text(encoding='utf-8-sig'))
                if value.get('policy')!=POLICY:continue
                for key,seconds in value.get('segments_seconds',{}).items():
                    if type(seconds) not in (int,float) or not 0<=seconds<86400:
                        raise ValueError('Invalid observed duration')
                    groups.setdefault(value['action']+'/'+key,[]).append(seconds)
                count+=1
            except (OSError,ValueError,KeyError,TypeError) as exc:warnings.append(p.name+':'+str(exc))
    return {'policy':POLICY,'events':count,'warnings':warnings,
            'phases':{k:{'samples':len(v),'median_seconds':statistics.median(v),'sum_seconds':sum(v)} for k,v in groups.items()},
            'actual_image_review_seconds':sum(groups.get('qa-save/observed_image_review',[])) if 'qa-save/observed_image_review' in groups else None,
            'missing_observations_are_zero':False,'overlapping_phases_additive':False,
            'service_and_save_intervals':'see existing observed submit/return/save timestamp coverage'}
