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
    from stage_deadlines import poll_compile
    poll_compile()
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


def claim_and_register(state_path, prepared_reference):
    """One owner transaction. Input preparation and file hashing happen before locks."""
    import copy
    from production_activation import require_active
    require_active(state_path)
    from prepared_job_store import store,state_basis
    from submission_contract import prepared_panel_job,registration,prepared_acknowledgement
    from runtime_clock import require_dispatch
    from slot_leases import ACTIVE,POLICY as LEASE
    path=Path(state_path).resolve();started=time.monotonic()
    initial=read_json(path);value=store(path).get(prepared_reference,initial)
    from visual_evidence import production_background_errors
    background_issues=production_background_errors(value['packet']['panels'][0],value['arguments'].get('prompt'))
    if background_issues:raise ValueError(';'.join(background_issues))
    from authority_updates import authority_context
    from staged_workflow import approval_errors
    authorization=initial.get('production_authorization')
    with file_session() as authorization_reads,authority_context(initial,path.parent.parent):
        issues=approval_errors(authorization,path.parent.parent,[initial['source_script']],initial['book_id'],initial['episode_id'])
        if isinstance(authorization,dict) and (authorization.get('policy')=='preparation_authorization_v1' or authorization.get('phase')=='preparation'):
            issues.append('Preparation authorization is not production authorization')
        if value['panel_id'] not in (authorization or {}).get('panel_ids',[]) and initial['episode_id']+'-'+value['panel_id'] not in (authorization or {}).get('panel_ids',[]):
            issues.append('Panel outside production scope')
        if issues:raise ValueError('PRODUCTION_AUTHORITY_HOLD:'+str(issues))
    require_dispatch(path)
    if value['round_id']==2:
        from stage_deadlines import repair_schedule
        schedule=repair_schedule(initial,path.parent.parent)
        if schedule and (not schedule['repair_budget_available'] or schedule['missing'] and value['panel_id'] not in schedule['required_dependency_repairs']):
            return {'status':'REPAIR_DEFERRED','image_calls':0,'dispatch_authorized':False}
    waiting=time.monotonic()
    with state_write_lock(path,force_shared=True):
        locked=time.monotonic()
        from production_activation import assert_current_route
        assert_current_route(path)
        state=read_json(path)
        if state.get('parallel_context')!=initial.get('parallel_context'):raise ValueError('OWNER_CHANGED')
        if state_basis(state)!=value.get('_current_guard',value)['state_basis']:raise ValueError('PREPARED_INPUT_OR_AUTHORITY_CHANGED')
        if state.get('cancelled'):raise ValueError('DISPATCH_HELD')
        from scoped_inputs import blocked_panels,generation_holds
        order=[r['panel_id'] for r in state['panels']]
        blocked,_=blocked_panels(generation_holds(state),order,{'batch_id':'EPISODE','panel_ids':order},value.get('_current_guard',value)['scheduling_rows'])
        if value['panel_id'] in blocked:raise ValueError('PANEL_DISPATCH_HELD')
        row=next(r for r in state['panels'] if r['panel_id']==value['panel_id'])
        if any(row.get(k)!=value[k] for k in ('attempt_id','round_id')):raise ValueError('PREPARED_ATTEMPT_CHANGED')
        # A replay returns the original exact identity, never a fresh invoke grant.
        for old in state.get('submission_registrations',{}).values():
            dynamic=old.get('prepared_dispatch')
            if dynamic and dynamic['panel_id']==row['panel_id'] and dynamic['attempt_id']==row['attempt_id']:
                if dynamic['prepared_reference']!=prepared_reference:raise ValueError('REGISTERED_INPUT_CHANGED')
                job=prepared_panel_job(state,value,dynamic['receipt'])
                job['submission']=dynamic['submission']
                return {'job':job,'ack':prepared_acknowledgement(job,old,fresh=False,state_sha256=digest(path)),'image_calls':0}
        if row['status'] not in {'PENDING','REPAIR_AUTHORIZED'} or row['package_manifest']!=value['package_manifest']:raise ValueError('ATTEMPT_NOT_DISPATCHABLE')
        for dep,output in value['dependencies'].items():
            actual=next(r for r in state['panels'] if r['panel_id']==dep)
            if actual.get('output')!=output or actual['status'] not in {'VISUAL_PASS','USER_ACCEPTED'}:raise ValueError('DEPENDENCY_CHANGED')
        context=state.get('parallel_context');receipt=None
        if context:
            if state.get('runtime',{}).get('dispatch_policy')!=LEASE:raise ValueError('PREPARED_REQUIRES_OWNER_LEASE')
            control=read_json(Path(context['control_file']))
            owner=next(j for j in control['jobs'] if j['job_id']==context['job_id'])
            lease=owner.get('slot_lease',{})
            if control.get('cancelled') or control.get('holds') or control.get('book_id')!=state['book_id']:
                raise ValueError('CONTROL_HELD')
            if Path(owner['root']).resolve()!=path.parent.parent or owner.get('episode_id')!=state['episode_id']:
                raise ValueError('OWNER_SCOPE_CHANGED')
            if sum(j.get('slot_lease',{}).get('slots',0) for j in control['jobs'])>control.get('max_inflight',0):
                raise ValueError('GLOBAL_CAPACITY_EXCEEDED')
            if lease.get('slots',0)>owner.get('max_inflight',0):raise ValueError('OWNER_CAPACITY_EXCEEDED')
            if (control.get('dispatch_policy')!=LEASE or control.get('epoch')!=context['epoch']
                or owner.get('worker_id')!=context['worker_id'] or lease.get('worker_id')!=context['worker_id']
                or lease.get('epoch')!=context['epoch'] or owner.get('status') not in {'ASSIGNED','RUNNING'}
                or owner.get('dispatch_pause') or control.get('dispatch_pause')):raise ValueError('OWNER_OR_CAPACITY_CHANGED')
            if owner.get('active_batch_id')!='EPISODE' or not lease.get('lease_id'):raise ValueError('LEASE_MISSING')
            active=[p for p in state.get('dispatch_ledger',[]) if p['status'] in ACTIVE]
            if any(p.get('lease_id')!=lease['lease_id'] for p in active):raise ValueError('ACTIVE_OWNER_CHANGED')
            if len(active)>=min(lease.get('slots',0),lease.get('dispatch_target',lease.get('slots',0))):return {'status':'CAPACITY_FULL','image_calls':0,'dispatch_authorized':False}
            receipt={**{k:context[k] for k in ('job_id','worker_id','epoch')},'lease_id':lease['lease_id'],
                     'permit_id':uuid.uuid4().hex,'batch_id':'EPISODE','round_id':row['round_id'],'attempt_id':row['attempt_id']}
        elif state.get('runtime',{}).get('dispatch_policy')==LEASE:raise ValueError('WAIT_CAPACITY_ASSIGNMENT')
        require_dispatch(path)
        store(path).assert_unchanged(value)
        verify_read_snapshot(authorization_reads,refresh_views=False)
        job=prepared_panel_job(state,value,receipt);key,entry=registration(job)
        if key in state.get('submission_registrations',{}):raise ValueError('ATTEMPT_ALREADY_REGISTERED_OTHER_PROTOCOL')
        entry['prepared_dispatch']={'panel_id':row['panel_id'],'attempt_id':row['attempt_id'],
             'prepared_reference':prepared_reference,'receipt':receipt,'submission':job['submission']}
        old_sha=digest(path);history=path.parent/'runtime_history';history.mkdir(exist_ok=True)
        previous=history/(old_sha+'.json')
        if not previous.exists():previous.write_bytes(path.read_bytes())
        new=copy.deepcopy(state);current=next(r for r in new['panels'] if r['panel_id']==row['panel_id'])
        current['status']='IN_FLIGHT';current['submitted_at']=datetime.now(timezone.utc).isoformat()
        current['prepared_registration_id']=key
        current['registered_at']=current['submitted_at']
        if value.get('ready_at'):current['ready_at']=value['ready_at']
        if receipt:new.setdefault('dispatch_ledger',[]).append({**receipt,'panel_id':row['panel_id'],'status':'IN_FLIGHT'})
        new.setdefault('submission_registrations',{})[key]=entry
        atomic_json(path,new)
    require_dispatch(path)
    result={'job':job,'ack':prepared_acknowledgement(job,entry,fresh=True,state_sha256=digest(path)),'image_calls':0}
    result['timing']={'operation':time.monotonic()-started,'lock_wait':locked-waiting,'lock_hold':time.monotonic()-locked}
    record(path,'claim-and-register',result['timing'],panel_ids=[row['panel_id']],operation_id=key)
    return result


def record_invocation_event(state_path, job, event):
    """Persist observed execution separately from registration; never grants invoke."""
    from generation_host import checked_job
    from execution_timing import checked_invocation_event
    path=Path(state_path).resolve()
    with state_write_lock(path,force_shared=True):
        state=read_json(path);root=path.parent.parent
        row,_,_,_=checked_job(state,root,job)
        value=checked_invocation_event(event)
        field={'REQUESTED':'invocation_requested_at','STARTED':'native_started_at','RETURNED':'native_completed_at'}[value['kind']]
        previous=row.get('invocation_events',{}).get(value['kind'])
        if previous is not None:
            if previous!=value:raise ValueError('INVOCATION_EVENT_CONFLICT')
            return {'status':'INVOCATION_EVENT_RECORDED','invoke_allowed':False,'image_calls':0,'reused':True}
        row.setdefault('invocation_events',{})[value['kind']]=value
        row[field]=value['at']
        atomic_json(path,state)
    return {'status':'INVOCATION_EVENT_RECORDED','invoke_allowed':False,'image_calls':0,'reused':False}


def settle_captured_return(state_path, job, capture_ref, receipt):
    """Release only the exact registered service permit, never mark QA or output complete."""
    from submission_contract import registration, job_binding, fingerprint
    from codex_reference_contract import checked_file
    from slot_leases import POLICY as LEASE
    path=Path(state_path).resolve();root=path.parent.parent
    checked_file(root,capture_ref)
    if receipt.get('policy')!='observed_image_return_v1' or not receipt.get('outputs'):
        raise ValueError('CAPTURE_RECEIPT_INVALID')
    output=receipt['outputs'][receipt['selected_index']]['sha256']
    key,_=registration(job)
    with state_write_lock(path,force_shared=True):
        state=read_json(path);entry=state.get('submission_registrations',{}).get(key)
        if not entry or entry.get('job_digest')!=fingerprint(job_binding(job)):
            raise ValueError('RETURN_REGISTRATION_MISMATCH')
        row=next(r for r in state['panels'] if r['panel_id']==job['panel_id'])
        if any(row.get(k)!=job.get(k) for k in ('attempt_id','round_id')):
            raise ValueError('RETURN_ATTEMPT_CHANGED: original bytes preserved')
        if any(state.get(k)!=job.get(k) for k in ('book_id','episode_id')):
            raise ValueError('RETURN_SCOPE_CHANGED')
        if row.get('status') not in {'IN_FLIGHT','GENERATED','VISUAL_PASS','VISUAL_FAIL'}:
            raise ValueError('RETURN_RECONCILIATION_REQUIRED')
        if state.get('runtime',{}).get('dispatch_policy')!=LEASE:
            return {'status':'NO_SERVICE_LEASE','image_calls':0}
        entries=[e for e in state.get('dispatch_ledger',[]) if e.get('panel_id')==job['panel_id']
                 and e.get('attempt_id')==job['attempt_id'] and e.get('round_id')==job['round_id']
                 and e.get('status')!='RELEASED']
        if len(entries)!=1:raise ValueError('CAPTURE_LEASE_NOT_UNIQUE')
        item=entries[0];permit=(job.get('dispatch_receipt') or {}).get('permit_id')
        if not permit or item.get('permit_id')!=permit:raise ValueError('CAPTURE_LEASE_MISMATCH')
        if item.get('status')=='COMPLETED':
            if item.get('output_sha256')!=output:raise ValueError('CAPTURE_LEASE_CONFLICT')
            return {'status':'SERVICE_SLOT_ALREADY_SETTLED','image_calls':0}
        if item.get('status') not in {'IN_FLIGHT','RESULT_UNKNOWN'}:raise ValueError('CAPTURE_LEASE_STATUS_INVALID')
        item.setdefault('events',[]).append({'from':item['status'],'to':'COMPLETED','at':datetime.now(timezone.utc).isoformat(),
            'evidence_status':'RETURN_CAPTURED','capture':capture_ref})
        item.update(status='COMPLETED',output_sha256=output,capture_receipt=capture_ref)
        atomic_json(path,state)
    return {'status':'SERVICE_SLOT_SETTLED','image_calls':0}
