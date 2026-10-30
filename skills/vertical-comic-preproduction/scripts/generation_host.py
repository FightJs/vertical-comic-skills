#!/usr/bin/env python3
"""Pinned current-executor host commands. No image service, inferred QA or parallel ledger."""
import sys
sys.dont_write_bytecode=True
import argparse, copy, hashlib, importlib.util, json, os, subprocess
from pathlib import Path
from datetime import datetime, timezone

HOST=Path(__file__).resolve().parent


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def reference(path,root):return {'path':os.path.relpath(Path(path).resolve(),Path(root).resolve()).replace(os.sep,'/'),'sha256':digest(path)}
def now():return datetime.now(timezone.utc).isoformat()


def protocol(scripts,caps):
    if caps.get('policy')!='comic_runtime_capabilities_v1':raise ValueError('UNKNOWN_FROZEN_CAPABILITIES')
    durable=caps.get('durable_image_submission')
    if durable is not None:
        if not isinstance(durable,dict):raise ValueError('INVALID_SUBMISSION_CAPABILITY')
        if durable.get('policy')!='durable_image_submission_v1':raise ValueError('UNKNOWN_SUBMISSION_PROTOCOL')
        return 'durable_image_submission_v1'
    raise ValueError('IMPORT_REQUIRED: old submission protocol is evidence only')


def activate(state_path, *, recovery_only=False):
    state_path=Path(state_path).resolve();state=read(state_path)
    runtime_ref=state['runtime_snapshot']
    if state.get('runtime_import'):
        from runtime_import import verify_binding
        receipt,_=verify_binding(state,state_path.parent.parent)
        runtime_ref=receipt['executor_manifest']
    manifest=Path(runtime_ref['path'])
    if not manifest.is_absolute() or digest(manifest)!=runtime_ref['sha256']:raise ValueError('SNAPSHOT_HOLD')
    scripts=manifest.parent/'skills/vertical-comic-preproduction/scripts'
    from runtime_snapshot import verify
    verified=verify(runtime_ref)
    if Path(verified['scripts']).resolve()!=scripts.resolve():raise ValueError('SNAPSHOT_SCRIPT_SCOPE')
    caps=read(scripts/'runtime_capabilities.json')
    if not isinstance(caps,dict) or caps.get('production_executor')!='whole_episode_light_v1':
        if not recovery_only:
            raise ValueError('IMPORT_REQUIRED: source-package code cannot execute; use receive/resume import')
        # Preservation only: current installed readers save a proven old return
        # or record confirmed no-image. This context cannot compile or submit.
        return state_path,state,state_path.parent.parent,HOST,'recovery_only_no_dispatch'
    kind=protocol(scripts,caps)
    sys.path.insert(0,str(scripts))
    return state_path,state,state_path.parent.parent,scripts,kind


def runtime_ref_for(state,root):
    if state.get('runtime_import'):
        from runtime_import import verify_binding
        return verify_binding(state,root)[0]['executor_manifest']
    return state['runtime_snapshot']


def inspect_runtime(state_path):
    path,state,root,scripts,kind=activate(state_path)
    return {'status':'RUNTIME_COMPATIBLE','submission_protocol':kind,'state':str(path),
            'source_manifest':state['runtime_snapshot'],'executor_manifest':runtime_ref_for(state,root),'frozen_scripts':str(scripts),
            'prepared_dispatch':read(scripts/'runtime_capabilities.json').get('prepared_dispatch'),
            'executor':reference(scripts/'async_generation.js',scripts),
            'image_tool_bridge':reference(scripts/'image_tool_bridge.js',scripts) if (scripts/'image_tool_bridge.js').is_file() else None,
            'prepared_input_source':reference(scripts/'prepared_input_source.js',scripts) if (scripts/'prepared_input_source.js').is_file() else None,
            'runtime_script':str(scripts/'production_runtime.py'),
            'clock_check':'installed_host_before_submit','image_calls':0,'dispatch_authorized':False}


def checked_job(state,root,job):
    if job.get('submission',{}).get('policy')=='prepared_dispatch_v1':
        return checked_prepared_job(state,root,job)
    if job.get('status')!='NOT_RUN' or job.get('candidate_only') or job.get('input_audit_only') or job.get('dispatch_authorized') is False:
        raise ValueError('AUDIT_OR_CANDIDATE_JOB_NOT_DISPATCHABLE')
    if any(job.get(k)!=state.get(k) for k in ('book_id','episode_id')):raise ValueError('JOB_SCOPE_CHANGED')
    row=next(r for r in state['panels'] if r['panel_id']==job['panel_id'])
    if any(job.get(k)!=row.get(k) for k in ('attempt_id','round_id')):raise ValueError('JOB_ATTEMPT_CHANGED')
    from codex_reference_contract import checked_file,validate_panel
    packet_path=checked_file(root,row['package_manifest']);packet=read(packet_path)
    errors,submission=validate_panel(packet['panels'][0],packet_path.parent)
    if errors or submission is None or submission['arguments']!=job['arguments']:raise ValueError('JOB_INPUT_CHANGED: '+str(errors))
    return row,packet_path,packet,submission


def binding_view(state,root,packet,package_root):
    # Load only this adapter's pure binding function, keeping all validators from
    # the activated frozen toolchain. No source module is replaced or patched.
    spec=importlib.util.spec_from_file_location('_receiver_binding',HOST/'handoff_delivery.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.local_execution_view(state,root,packet,package_root)


def checked_prepared_job(state,root,job):
    from submission_contract import registration,job_binding,fingerprint
    from prepared_job_store import store
    key,_=registration(job);entry=state.get('submission_registrations',{}).get(key)
    if (not entry or entry['job_digest']!=fingerprint(job_binding(job)) or
            any(entry.get('prepared_dispatch',{}).get('prepared_reference',{}).get(k)!=job.get('prepared_reference',{}).get(k)
                for k in ('prepared_input_id','record_digest'))):
        raise ValueError('RETURN_REGISTRATION_MISMATCH')
    row=next(r for r in state['panels'] if r['panel_id']==job['panel_id'])
    if any(job.get(k)!=row.get(k) for k in ('attempt_id','round_id')):raise ValueError('RETURN_ATTEMPT_CHANGED')
    if any(job.get(k)!=state.get(k) for k in ('book_id','episode_id')):raise ValueError('RETURN_SCOPE_CHANGED')
    value=store(Path(root)/'00_输入审计/生产流程.json').get(job['prepared_reference'],check_inputs=False,check_state=False)
    if value['arguments']!=job['arguments'] or value['package_manifest']!=job['package_manifest']:raise ValueError('RETURN_INPUT_CHANGED')
    packet_path=Path(root)/value['package_manifest']['path']
    return row,packet_path,copy.deepcopy(value['packet']),copy.deepcopy(value['submission_plan'])


def capture_return(state_path,job_path,raw_path,call_locator,result_locator,selected_index=None, *, _context=None, observed=None):
    """Independent durable I/O. Preserve first; registration may be replayed later."""
    import time
    from image_return_io import persist,put
    path=Path(state_path).resolve();root=path.parent.parent;job=read(job_path)
    if not call_locator or not result_locator:raise ValueError('REAL_CALL_AND_RETURN_LOCATORS_REQUIRED')
    started=time.monotonic()
    key=hashlib.sha256(json.dumps([job['panel_id'],job['attempt_id'],job['round_id']],ensure_ascii=False).encode()).hexdigest()
    folder=root/'05_生成原图/实际返回'/key
    # Store invocation identity before parsing: malformed returns remain recoverable.
    identity={'policy':'durable_return_capture_v1','state':str(path),'job':job,
              'call_locator':call_locator,'result_locator':result_locator,'observed':observed or {}}
    put(folder/'capture-job.json',(json.dumps(identity,ensure_ascii=False,sort_keys=True)+'\n').encode())
    receipt=persist(raw_path,folder,selected_index=selected_index)
    envelope={**identity,'receipt':reference(folder/'receipt.json',root)}
    put(folder/'capture.json',(json.dumps(envelope,ensure_ascii=False,sort_keys=True)+'\n').encode())
    capture=reference(folder/'capture.json',root)
    # Only an exact registered prepared job can free service capacity. A failed
    # settlement leaves the original receipt on disk and cannot grant a retry.
    settlement=None
    if job.get('submission',{}).get('policy')=='prepared_dispatch_v1':
        from runtime_pipeline import settle_captured_return
        try:settlement=settle_captured_return(path,job,capture,receipt)
        except (ValueError,KeyError,TypeError,StopIteration) as exc:
            # Captured bytes survive stale identity or a per-panel state conflict.
            # This does not grant a new service permit; registration will reconcile.
            settlement={'status':'SERVICE_SETTLEMENT_PENDING','error':str(exc)}
    result={'status':'RETURN_CAPTURED','capture':capture,'image_calls':0,'visual_review':'UNREVIEWED',
            'image':str(folder/receipt['outputs'][receipt['selected_index']]['path']),
            'service_settlement':settlement}
    try:
        from runtime_pipeline import record
        record(path,'return-captured',{'capture':time.monotonic()-started},panel_ids=[job['panel_id']],attempt_id=job['attempt_id'])
    except OSError as exc:result['timing_record_error']=str(exc)
    return result


def register_return(state_path,capture_ref, *, _context=None):
    from codex_reference_contract import checked_file
    from image_return_io import put
    import time
    started=time.monotonic();path=Path(state_path).resolve();root=path.parent.parent
    capture_path=checked_file(root,capture_ref);envelope=read(capture_path)
    if envelope.get('policy')!='durable_return_capture_v1' or envelope.get('state')!=str(path):
        raise ValueError('CAPTURE_OWNER_CHANGED')
    receipt=read(checked_file(root,envelope['receipt']));folder=capture_path.parent
    checked_file(folder,receipt['raw'])
    for output in receipt['outputs']:checked_file(folder,output)
    job_path=folder/'captured-job.json'
    put(job_path,(json.dumps(envelope['job'],ensure_ascii=False,sort_keys=True)+'\n').encode())
    result=_register_return(path,job_path,folder/'raw-return.json',envelope['call_locator'],envelope['result_locator'],
        receipt['selected_index'],_context=_context,observed=envelope['observed'],_captured=(folder,receipt))
    put(folder/'registered.json',(json.dumps({'capture':capture_ref,'image':result['image']},sort_keys=True)+'\n').encode())
    try:
        from runtime_pipeline import record
        record(path,'return-registered',{'registration':time.monotonic()-started},panel_ids=[envelope['job']['panel_id']],attempt_id=envelope['job']['attempt_id'])
    except OSError as exc:result['timing_record_error']=str(exc)
    return result


def recover_returns(state_path, *, _context=None):
    """Replay saved originals only; individual registration failures stay local."""
    path=Path(state_path).resolve();folder=path.parent.parent/'05_生成原图/实际返回';results=[]
    for capture in sorted(folder.glob('*/capture.json')):
        if (capture.parent/'registered.json').exists():continue
        ref=reference(capture,path.parent.parent)
        try:result=register_return(path,ref,_context=_context)
        except (OSError,ValueError,KeyError,TypeError,StopIteration) as exc:
            result={'status':'RETURN_REGISTRATION_PENDING','error':str(exc)}
        results.append({'capture':ref,**result})
    return {'status':'RETURNS_RECONCILED','results':results,'image_calls':0,'dispatch_authorized':False}


def save_return(state_path,job_path,raw_path,call_locator,result_locator,selected_index=None, *, _context=None, observed=None):
    captured=capture_return(state_path,job_path,raw_path,call_locator,result_locator,selected_index,
                           _context=_context,observed=observed)
    return register_return(state_path,captured['capture'],_context=_context)


def _register_return(state_path,job_path,raw_path,call_locator,result_locator,selected_index=None, *, _context=None, observed=None, _captured=None):
    if _context is None:
        path,state,root,scripts,kind=activate(state_path,recovery_only=True)
    else:
        path,_,root,scripts,kind=_context
        if Path(state_path).resolve()!=path:raise ValueError('RETURN_OWNER_CHANGED')
        state=read(path)
    job=read(job_path)
    from image_return_io import put
    folder,receipt=_captured
    save_started=datetime.fromtimestamp((folder/'raw-return.json').stat().st_mtime,timezone.utc).isoformat()
    captured_at=datetime.fromtimestamp((folder/'receipt.json').stat().st_mtime,timezone.utc).isoformat()
    key=folder.name
    row,packet_path,packet,submission=checked_job(state,root,job)
    observed=observed or {}
    from execution_timing import checked_invocation_event
    return_observed=save_started
    if observed.get('returned_at'):
        return_observed=checked_invocation_event({'kind':'RETURNED','at':observed['returned_at'],
            'source_kind':'observed_tool_result','source_locator':result_locator})['at']
    from runtime_pipeline import record_invocation_event
    for field,kind,source,locator in [('native_started_at','STARTED','observed_tool_call',call_locator),
                                     ('native_completed_at','RETURNED','observed_tool_result',result_locator)]:
        if observed.get(field):
            record_invocation_event(path,job,{'kind':kind,'at':observed[field],'source_kind':source,'source_locator':locator})
    image=folder/receipt['outputs'][receipt['selected_index']]['path']
    if row['status'] in {'GENERATED','VISUAL_PASS','VISUAL_FAIL'}:
        if row.get('output',{}).get('sha256')!=digest(image):raise ValueError('ATTEMPT_RETURN_CONFLICT')
        return {'status':'RETURN_ALREADY_SAVED','image':str(image),'image_calls':0,'visual_review':'UNCHANGED'}
    if row['status']!='IN_FLIGHT':raise ValueError('RETURN_RECONCILIATION_REQUIRED: preserve original attempt and use its resolution protocol')
    if row['package_manifest']!=job['package_manifest']:raise ValueError('JOB_PACKAGE_CHANGED')
    if job.get('submission',{}).get('policy')=='prepared_dispatch_v1':
        from prepared_job_store import store
        value=store(path).get(job['prepared_reference'],check_inputs=False,check_state=False)
        bound,proof=copy.deepcopy(value['packet']),value['binding']
        if job.get('dispatch_receipt'):
            bound['dispatch_receipt']=job['dispatch_receipt']
            bound['dispatch_source_package']=job['package_manifest']
    else:bound,proof=binding_view(state,root,packet,packet_path.parent)
    request={**copy.deepcopy(submission),'backend_id':'codex_builtin_imagegen','panel_id':row['panel_id'],
             'attempt_id':row['attempt_id'],'source_kind':'observed_tool_call','source_locator':call_locator}
    response={'attempt_id':row['attempt_id'],'status':'COMPLETED','source_kind':'observed_tool_result',
              'source_locator':result_locator,'outputs':[reference(image,packet_path.parent)],
              'raw_tool_result':reference(folder/'raw-return.json',packet_path.parent)}
    for name,value in [('request.json',request),('response.json',response),('binding.json',proof)]:
        put(folder/name,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode())
    bound['panels'][0]['generation_execution']={'status':'COMPLETED','attempt_id':row['attempt_id'],
        'request_evidence':reference(folder/'request.json',packet_path.parent),
        'response_evidence':reference(folder/'response.json',packet_path.parent)}
    executed=packet_path.parent/('实际执行_'+key+'.json')
    put(executed,(json.dumps(bound,ensure_ascii=False,indent=2)+'\n').encode())
    from production_runtime import commit_updates
    update={'panel_id':row['panel_id'],'attempt_id':row['attempt_id'],'round_id':row['round_id'],
            'status':'GENERATED','package_manifest':reference(executed,root),'output':reference(image,root),
            'returned_at':return_observed,'save_started_at':save_started,'saved_at':captured_at}
    for retry in range(3):
        latest=read(path)
        current=next(r for r in latest['panels'] if r['panel_id']==row['panel_id'])
        if any(current.get(k)!=row.get(k) for k in ('attempt_id','round_id')):
            raise ValueError('RETURN_ATTEMPT_CHANGED: original bytes preserved')
        if current.get('status') in {'GENERATED','VISUAL_PASS','VISUAL_FAIL'}:
            if current.get('output')!=update['output']:raise ValueError('ATTEMPT_RETURN_CONFLICT')
            return {'status':'RETURN_ALREADY_SAVED','image':str(image),'image_calls':0,'visual_review':'UNCHANGED'}
        try:
            result=commit_updates(path,digest(path),[update]);break
        except ValueError as exc:
            if retry==2 or not str(exc).startswith(('STATE_CHANGED','CHECK_SNAPSHOT_CHANGED')):raise

    return {**result,'image':str(image),'raw_result':str(folder/'raw-return.json'),
            'execution_manifest':reference(executed,root),'visual_review':'UNREVIEWED','image_calls':0}


def replay_return(state_path,job_path,raw_path,output,selected_index=None):
    """Replay a historically completed return; never create a fake live submission."""
    path,state,root,scripts,kind=activate(state_path)
    dest=Path(output).resolve()
    snapshot=Path(state['runtime_snapshot']['path']).parent
    if dest.is_relative_to(root) or root.is_relative_to(dest) or dest.is_relative_to(snapshot):
        raise ValueError('REPLAY_OUTPUT_MUST_BE_ISOLATED')
    if dest.exists():raise ValueError('REPLAY_OUTPUT_MUST_BE_NEW')
    job=read(job_path);row,package,packet,submission=checked_job(state,root,job)
    if row['status'] not in {'GENERATED','VISUAL_PASS','VISUAL_FAIL','USER_ACCEPTED'}:
        raise ValueError('REPLAY_REQUIRES_COMPLETED_HISTORICAL_RETURN')
    from codex_reference_contract import checked_file,execution_errors
    execution=packet['panels'][0].get('generation_execution',{})
    if execution.get('status')!='COMPLETED' or execution.get('attempt_id')!=row['attempt_id']:
        raise ValueError('REPLAY_EXECUTION_NOT_COMPLETED')
    errors=execution_errors(execution,submission,package.parent,row['panel_id'])
    if errors:raise ValueError('REPLAY_EVIDENCE_HOLD: '+str(errors))
    from image_return_io import persist,put
    receipt=persist(raw_path,dest/'returned',selected_index=selected_index)
    returned=dest/'returned'/receipt['outputs'][receipt['selected_index']]['path']
    image=checked_file(root,row['output'])
    response=read(checked_file(package.parent,execution['response_evidence']))
    if digest(returned)!=digest(image) or digest(image) not in {r['sha256'] for r in response['outputs']}:
        raise ValueError('REPLAY_NOT_THE_HISTORICAL_IMAGE')
    originals={path:digest(path),package:digest(package),image:digest(image)}
    from make_generation_qa import _main
    from contextlib import redirect_stdout
    import io
    with redirect_stdout(io.StringIO()):
        _main(['--package',str(package.parent),'--manifest',package.name,'--images',str(image.parent),
               '--image-path',str(image),'--output',str(dest/'qa'),'--episode-root',str(root),
               '--panel-ids',row['panel_id'],'--skip-contact-sheet'])
    qa=read(dest/'qa/生成图QA报告.json')
    if qa.get('source_manifest_sha256')!=digest(package):raise ValueError('REPLAY_QA_BINDING_CHANGED')
    if any(digest(p)!=h for p,h in originals.items()):raise ValueError('REPLAY_ORIGINAL_CHANGED')
    result={'status':'HISTORICAL_RETURN_REPLAYED','source':'historical_return_replay',
            'historical_state':reference(path,root),'historical_execution':reference(package,root),
            'qa':reference(dest/'qa/生成图QA报告.json',dest),'qa_status':qa['status'],
            'technical_errors':qa.get('errors',[]),'visual_review':'NOT_PERFORMED',
            'dispatch_authorized':False,'image_calls':0,'not_final_delivery':True}
    put(dest/'replay.json',(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode())
    return result


def check_write_scope(path,root):
    marker=root.parent/'接收审计活动.json'
    if marker.is_file():
        activity=read(marker)
        if activity.get('policy')!='receiver_active_read_scopes_v1':raise ValueError('UNKNOWN_RECEIVER_READ_SCOPE')
        if str(path) in activity.get('protected_state_paths',[]):
            raise ValueError('RECEIVER_READ_CONFLICT: defer this write until dependent input audits complete')


def capture_envelope(state_path, job, packet, item, *, context=None):
    """Official in-memory tool envelope adapter; durable capture remains authoritative."""
    from image_return_io import put
    import tempfile
    path=Path(state_path).resolve();root=path.parent.parent
    if not isinstance(packet,dict) or 'result' not in packet:raise ValueError('TOOL_RESULT_ENVELOPE_REQUIRED')
    # Temporary serialized input is removed only after persist has its durable copy.
    folder=root/'00_输入审计/return-ingest';folder.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder) as temp:
        temp=Path(temp);jp=temp/'job.json';rp=temp/'raw.json'
        put(jp,json.dumps(job,ensure_ascii=False).encode());put(rp,json.dumps(packet['result'],ensure_ascii=False).encode())
        return capture_return(path,jp,rp,packet['call_locator'],packet['result_locator'],
                              _context=context,observed=item)


def record_envelope(state_path, job, packet, item, authorization=None):
    """Persist actual errors. Generic transport rejection remains UNKNOWN."""
    from image_return_io import put
    from production_runtime import commit_updates
    from submission_contract import registration
    path=Path(state_path).resolve();root=path.parent.parent;state=read(path)
    row=next(r for r in state['panels'] if r['panel_id']==job['panel_id'])
    reg,_=registration(job)
    if row['attempt_id']!=job['attempt_id'] or row.get('prepared_registration_id')!=reg:
        raise ValueError('FAILURE_ATTEMPT_CHANGED')
    error=item.get('error') or (packet or {}).get('error') or {'message':item.get('reason','Tool returned no usable image')}
    text=json.dumps(error,ensure_ascii=False)
    content='moderation_blocked' in text or 'rejected by the safety system' in text
    terminal=(packet or {}).get('terminal') or {}
    confirmed=content or (terminal.get('no_image_confirmed') is True and
        terminal.get('outcome') in {'NOT_INVOKED','REJECTED_NO_OUTPUT','FAILED_NO_OUTPUT','RESOLVED_NO_OUTPUT'} and
        terminal.get('attempt_id')==job['attempt_id'] and terminal.get('registration_id')==reg and
        terminal.get('source_kind') in {'observed_executor_outcome','observed_tool_error','observed_resolution'} and
        terminal.get('source_locator') and terminal.get('evidence'))
    status='CALL_FAILED' if confirmed else 'RESULT_UNKNOWN'
    locator=(packet or {}).get('call_locator') or item.get('call_locator')
    if not locator:raise ValueError('ACTUAL_ERROR_LOCATOR_REQUIRED')
    raw_error=json.dumps({'packet':packet,'error':error},ensure_ascii=False,sort_keys=True).encode()
    original=root/'00_输入审计/tool-errors'/(hashlib.sha256(raw_error).hexdigest()+'.json')
    put(original,raw_error)
    evidence={**terminal,'book_id':state['book_id'],'episode_id':state['episode_id'],
        'panel_id':row['panel_id'],'attempt_id':row['attempt_id'],'round_id':row['round_id'],
        'registration_id':reg,'status':status,'source_kind':'observed_tool_error','source_locator':locator,
        'evidence':text,'error':error,'no_image_confirmed':bool(confirmed),'evidence_files':[reference(original,root)],
        **({'outcome':'REJECTED_NO_OUTPUT','rejection_kind':'content_policy'} if content else {})}
    raw=(json.dumps(evidence,ensure_ascii=False,sort_keys=True)+'\n').encode()
    dest=root/'00_输入审计/tool-errors'/(hashlib.sha256(raw).hexdigest()+'.json');put(dest,raw);ref=reference(dest,root)
    if row['status']=='IN_FLIGHT':
        commit_updates(path,digest(path),[{'panel_id':row['panel_id'],'attempt_id':row['attempt_id'],
            'round_id':row['round_id'],'status':status,'call_evidence':ref}])
    elif row.get('status')!=status or row.get('call_evidence')!=ref:raise ValueError('ERROR_REPLAY_CONFLICT')
    result={'status':'FAILURE_RECORDED' if confirmed else 'UNKNOWN_RECORDED','call_evidence':ref,'image_calls':0}
    if confirmed and authorization:
        from no_image_recovery import prepare_request,recover
        request=prepare_request(path,row['panel_id'],ref,authorization)
        result['recovery']=recover(path,digest(path),request)
    return result


def prepare_qa(state,root,panels=None):
    from review_queue import build_queue
    from production_runtime import prepare_review
    from codex_reference_contract import checked_file
    plan=read(checked_file(root,state['batch_plan']))
    items=[]
    for batch in plan['batches']:
        if panels is not None and not set(batch['panel_ids']) & set(panels):continue
        if panels is not None:batch={**batch,'panel_ids':[p for p in batch['panel_ids'] if p in panels]}
        queue=build_queue(state,root,batch,incremental=True)
        items.extend(i for i in queue['items'] if panels is None or i['panel_id'] in panels)
    result=prepare_review(state,root,{'items':items,'status':'REVIEW_TASKS_ONLY'})
    from image_return_io import put
    records={r['panel_id']:r for r in state['panels']}
    for item in result['items']:
        if not item.get('qa_template'):continue
        row=records[item['panel_id']]
        ticket={'policy':'observed_review_ticket_v1','book_id':state['book_id'],'episode_id':state['episode_id'],
            'panel_id':row['panel_id'],'attempt_id':row['attempt_id'],'output':row['output'],
            'qa_template':item['qa_template'],'base_qa':row.get('qa_report')}
        raw=json.dumps(ticket,ensure_ascii=False,sort_keys=True).encode()
        path=Path(root)/'06_图片验收/review-tickets'/(hashlib.sha256(raw).hexdigest()+'.json')
        put(path,raw);item['review_ticket']=reference(path,root)
    return result


def serve(state_path):
    """One new frozen owner process, bounded existing validation pool, JSONL I/O."""
    path,state,root,scripts,kind=activate(state_path)
    if state.get('runtime_pipeline_policy')!='observed_incremental_pipeline_v1':
        raise ValueError('PERSISTENT_WORKER_REQUIRES_NEW_PIPELINE: old contract unchanged')
    from workflow_session import WorkflowSession
    worker=WorkflowSession(active_context=(path,state,root,scripts,kind))
    from machine_resources import Coordinator
    resources=Coordinator()
    # Recover only saved returns; failures remain scoped and never invoke images.
    recover_returns(path,_context=(path,state,root,scripts,kind))
    import queue, threading, time
    from concurrent.futures import ThreadPoolExecutor
    requests=queue.PriorityQueue();output_lock=threading.Lock()
    capture_pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='comic-capture')
    capture_capacity=threading.BoundedSemaphore(8)
    def ingest():
        for serial,line in enumerate(sys.stdin):
            if not line.strip():continue
            try:
                request=json.loads(line)
                if not isinstance(request,dict):raise ValueError('request must be an object')
            except ValueError:request={'action':'invalid','request_id':None}
            request['_enqueued_monotonic']=time.monotonic()
            if request.get('action') in {'capture-return','capture-envelope'}:
                if not capture_capacity.acquire(blocking=False):
                    # Protocol clients admit at most eight captures; an excess
                    # caller keeps its raw return and can retry capture, never generation.
                    with output_lock:
                        print(json.dumps({'request_id':request.get('request_id'),'result':{
                            'status':'HOLD','error':'CAPTURE_CAPACITY_BUSY_RETAIN_RETURN',
                            'retry_action':request['action'],'image_calls':0}}),flush=True)
                    continue
                def capture_work(request=request):
                    respond(request,WorkflowSession(active_context=(path,state,root,scripts,kind)),capture_capacity.release)
                capture_pool.submit(capture_work)
                continue
            priority=0 if request.get('action') in {'save-return','register-return','recover-returns','commit','recover-no-image'} else 1
            requests.put((priority,serial,request))
        requests.put((10,float('inf'),None))
    def respond(request,session,on_ready=None):
        started=time.monotonic()
        try:
            if request.get('state') is not None and Path(request['state']).resolve()!=path:
                raise ValueError('WORKER_CANNOT_SWITCH_FROZEN_OWNER')
            request['state']=str(path)
            if request['action'] in {'reserve','submit','claim-and-register'}:
                check_write_scope(path,root)
                from runtime_clock import require_dispatch
                require_dispatch(path)
            if request['action']=='resource-status':
                result=resources.status(root)
            elif request['action']=='resource-acquire':
                from runtime_clock import require_dispatch
                clock=require_dispatch(path)
                if clock:resources.observe_run(str(root),clock.get('active_segment'))
                result=resources.acquire('image',str(path)+' / '+request['key'],1,disk=root)
                from slot_leases import resize
                try:result['production_capacity']=resize(path,result['limits']['image'])
                except Exception:
                    if result.get('token'):resources.release(result['token'])
                    raise
            elif request['action']=='resource-returned':
                result=resources.returned(request['token'],request['bytes'])
            elif request['action']=='resource-release':
                result=resources.release(request['token'],completed=request.get('completed',False),preserved=request.get('preserved',True))
            elif request['action']=='wait-prepared-change':
                from prepared_job_store import store
                result=store(path).wait_for_change(request['revision'],request.get('timeout_seconds',2))
            else:
                result=session.execute(request)
                if result.get('status')=='RETURN_CAPTURED':
                    try:
                        if request.get('resource_token'):resources.release(request['resource_token'],completed=True)
                        else:
                            # Explicit replay may have only the saved job, not the
                            # transient transport token. Release only its exact local key.
                            captured_job=request.get('job')
                            if isinstance(captured_job,str):captured_job=read(captured_job)
                            if isinstance(captured_job,dict):
                                key=json.dumps([captured_job['episode_id'],captured_job['panel_id'],captured_job['attempt_id']],ensure_ascii=False,separators=(',',':'))
                                resources.release_image_key(str(path)+' / '+key)
                    except (OSError,ValueError,KeyError,TypeError) as exc:
                        result['resource_release_error']=str(exc) # Durable capture remains a valid receipt.

        except Exception as exc:
            result={'status':'HOLD','error':str(exc),'image_calls':0,'dispatch_authorized':False}
        result['local_queue_seconds']=max(0,started-request.get('_enqueued_monotonic',started))
        if on_ready:on_ready() # Release before the receipt can admit the next capture.
        with output_lock:
            print(json.dumps({'request_id':request.get('request_id'),'result':result},ensure_ascii=False),flush=True)
    reader=threading.Thread(target=ingest,daemon=True);reader.start()
    # Long readers never run on the state writer. Each reader owns its contexts.
    with ThreadPoolExecutor(max_workers=1,thread_name_prefix='comic-prepare') as preparation, ThreadPoolExecutor(max_workers=2,thread_name_prefix='comic-ready-wait') as notifications:
        while True:
            _,_,request=requests.get()
            if request is None:break
            if request.get('action')=='wait-prepared-change':
                notifications.submit(respond,request,worker)
            elif request.get('action')=='prepare-inputs':
                preparation.submit(respond,request,WorkflowSession(active_context=(path,state,root,scripts,kind)))
            else:respond(request,worker)
    reader.join();capture_pool.shutdown(wait=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['inspect-runtime','check-bindings','compile','prepare-submit','save-return','capture-return','register-return','recover-returns','prepare-qa','clock-check','replay-return','recover-no-image','serve','prepare-inputs','claim-and-register'])
    p.add_argument('--state',required=True);p.add_argument('--job');p.add_argument('--raw-result')
    p.add_argument('--output');p.add_argument('--call-locator');p.add_argument('--result-locator');p.add_argument('--selected-index',type=int)
    p.add_argument('--capture',help='JSON capture reference file');p.add_argument('--recovery-request');p.add_argument('--expected-state-sha256')
    p.add_argument('--panels',nargs='+');p.add_argument('--workers',default='all');a=p.parse_args()
    try:
        if a.action in {'prepare-inputs','claim-and-register'}:
            path,state,root,scripts,kind=activate(a.state)
            from workflow_session import WorkflowSession
            request={'action':a.action,'state':str(path),'panels':a.panels,'workers':a.workers if a.workers=='all' else int(a.workers)}
            if a.job:request['prepared_reference']=read(a.job)
            result=WorkflowSession(active_context=(path,state,root,scripts,kind)).execute(request)
        elif a.action=='clock-check':
            from runtime_clock import require_dispatch
            clock=require_dispatch(a.state)
            result={'status':'CLOCK_CHECKED','clock_observed':clock is not None,'image_calls':0}
        elif a.action=='recover-no-image':
            proc=subprocess.run([sys.executable,'-X','utf8','-B',str(HOST/'generation_host.py'),'clock-check','--state',a.state],
                                capture_output=True,text=True,encoding='utf-8',env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
            if proc.returncode:raise ValueError('HOST_CLOCK_HOLD: '+proc.stdout+proc.stderr)
            request=read(a.recovery_request)
            path,state,root,scripts,kind=activate(a.state,recovery_only=True)
            check_write_scope(path,root)
            from no_image_recovery import recover
            if state.get('dispatch_consistency'):
                from managed_dispatch import authority
                with authority([path]):result=recover(path,a.expected_state_sha256,request)
            else:result=recover(path,a.expected_state_sha256,request)
        elif a.action=='serve':
            serve(a.state);return 0
        elif a.action=='inspect-runtime':result=inspect_runtime(a.state)
        elif a.action=='replay-return':result=replay_return(a.state,a.job,a.raw_result,a.output,a.selected_index)
        elif a.action=='capture-return':result=capture_return(a.state,a.job,a.raw_result,a.call_locator,a.result_locator,a.selected_index)
        elif a.action=='register-return':result=register_return(a.state,read(a.capture))
        elif a.action=='recover-returns':result=recover_returns(a.state)
        elif a.action=='save-return':result=save_return(a.state,a.job,a.raw_result,a.call_locator,a.result_locator,a.selected_index)
        else:
            # Clock check runs in its own installed process before importing old modules.
            if a.action=='prepare-submit':
                proc=subprocess.run([sys.executable,'-X','utf8','-B',str(HOST/'generation_host.py'),'clock-check','--state',a.state],
                                    capture_output=True,text=True,encoding='utf-8',env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
                if proc.returncode:raise ValueError('HOST_CLOCK_HOLD: '+proc.stdout+proc.stderr)
            path,state,root,scripts,kind=activate(a.state)
            from production_runtime import compile_jobs,commit_updates
            if a.action in {'compile','prepare-submit','prepare-qa'}:
                spec=importlib.util.spec_from_file_location('_host_recovery_history',HOST/'no_image_recovery.py')
                recovery=importlib.util.module_from_spec(spec);spec.loader.exec_module(recovery)
                for row in state['panels']:
                    if a.panels is None or row['panel_id'] in a.panels:
                        errors=recovery.history_errors(state,root,row)
                        if errors:raise ValueError(';'.join(errors))
            if a.action=='prepare-submit':check_write_scope(path,root)
            if a.action=='compile':result=compile_jobs(state,root,a.panels)
            elif a.action=='check-bindings':
                from codex_reference_contract import checked_file,file_session
                count=0
                with file_session():
                    for row in state['panels']:
                        package=checked_file(root,row['package_manifest'])
                        binding_view(state,root,read(package),package.parent);count+=1
                result={'status':'LOCAL_BINDINGS_VERIFIED','panel_count':count,'dispatch_authorized':False,'image_calls':0}
            elif a.action=='prepare-submit':
                job=read(a.job);row,package,packet,submission=checked_job(state,root,job)
                from production_runtime import submit
                result=submit(path,job)
            elif a.action=='prepare-qa':result=prepare_qa(state,root,a.panels)
        print(json.dumps(result,ensure_ascii=False));return 0
    except (OSError,ValueError,KeyError,TypeError,StopIteration,ImportError,AttributeError) as exc:
        print(json.dumps({'status':'HOLD','error':str(exc),'image_calls':0,'dispatch_authorized':False},ensure_ascii=False));return 1

if __name__=='__main__':raise SystemExit(main())
