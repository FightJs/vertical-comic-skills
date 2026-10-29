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


def save_return(state_path,job_path,raw_path,call_locator,result_locator,selected_index=None, *, _context=None):
    if _context is None:
        path,state,root,scripts,kind=activate(state_path,recovery_only=True)
    else:
        path,_,root,scripts,kind=_context
        if Path(state_path).resolve()!=path:raise ValueError('RETURN_OWNER_CHANGED')
        state=read(path)
    job=read(job_path)
    save_started=now()
    if not call_locator or not result_locator:raise ValueError('REAL_CALL_AND_RETURN_LOCATORS_REQUIRED')
    # Persist bytes even if a later runtime or CAS check cannot finish.
    from image_return_io import persist,put
    key=hashlib.sha256(json.dumps([job['panel_id'],job['attempt_id'],job['round_id']],ensure_ascii=False).encode()).hexdigest()
    folder=root/'05_生成原图/实际返回'/key
    receipt=persist(raw_path,folder,selected_index=selected_index)
    row,packet_path,packet,submission=checked_job(state,root,job)
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
            'returned_at':save_started,'save_started_at':save_started,'saved_at':now()}
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


def serve(state_path):
    """One new frozen owner process, bounded existing validation pool, JSONL I/O."""
    path,state,root,scripts,kind=activate(state_path)
    if state.get('runtime_pipeline_policy')!='observed_incremental_pipeline_v1':
        raise ValueError('PERSISTENT_WORKER_REQUIRES_NEW_PIPELINE: old contract unchanged')
    from workflow_session import WorkflowSession
    worker=WorkflowSession(active_context=(path,state,root,scripts,kind))
    import queue, threading, time
    from concurrent.futures import ThreadPoolExecutor
    requests=queue.PriorityQueue();output_lock=threading.Lock()
    def ingest():
        for serial,line in enumerate(sys.stdin):
            if not line.strip():continue
            try:
                request=json.loads(line)
                if not isinstance(request,dict):raise ValueError('request must be an object')
            except ValueError:request={'action':'invalid','request_id':None}
            request['_enqueued_monotonic']=time.monotonic()
            priority=0 if request.get('action') in {'save-return','commit','recover-no-image'} else 1
            requests.put((priority,serial,request))
        requests.put((10,float('inf'),None))
    def respond(request,session):
        started=time.monotonic()
        try:
            if request.get('state') is not None and Path(request['state']).resolve()!=path:
                raise ValueError('WORKER_CANNOT_SWITCH_FROZEN_OWNER')
            request['state']=str(path)
            if request['action'] in {'reserve','submit','claim-and-register'}:
                check_write_scope(path,root)
                from runtime_clock import require_dispatch
                require_dispatch(path)
            result=session.execute(request)
        except Exception as exc:
            result={'status':'HOLD','error':str(exc),'image_calls':0,'dispatch_authorized':False}
        result['local_queue_seconds']=max(0,started-request.get('_enqueued_monotonic',started))
        with output_lock:
            print(json.dumps({'request_id':request.get('request_id'),'result':result},ensure_ascii=False),flush=True)
    reader=threading.Thread(target=ingest,daemon=True);reader.start()
    # Long readers never run on the state writer. Each reader owns its contexts.
    with ThreadPoolExecutor(max_workers=1,thread_name_prefix='comic-prepare') as preparation:
        while True:
            _,_,request=requests.get()
            if request is None:break
            if request.get('action')=='prepare-inputs':
                preparation.submit(respond,request,WorkflowSession(active_context=(path,state,root,scripts,kind)))
            else:respond(request,worker)
    reader.join()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['inspect-runtime','check-bindings','compile','prepare-submit','save-return','prepare-qa','clock-check','replay-return','recover-no-image','serve','prepare-inputs','claim-and-register'])
    p.add_argument('--state',required=True);p.add_argument('--job');p.add_argument('--raw-result')
    p.add_argument('--output');p.add_argument('--call-locator');p.add_argument('--result-locator');p.add_argument('--selected-index',type=int)
    p.add_argument('--recovery-request');p.add_argument('--expected-state-sha256')
    p.add_argument('--panels',nargs='+');a=p.parse_args()
    try:
        if a.action in {'prepare-inputs','claim-and-register'}:
            path,state,root,scripts,kind=activate(a.state)
            from workflow_session import WorkflowSession
            request={'action':a.action,'state':str(path),'panels':a.panels}
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
            elif a.action=='prepare-qa':
                from review_queue import build_queue
                from production_runtime import prepare_review
                from codex_reference_contract import checked_file
                plan=read(checked_file(root,state['batch_plan']))
                batches=[b for b in plan['batches'] if a.panels is None or set(b['panel_ids']) & set(a.panels)]
                items=[]
                for batch in batches:
                    queue=build_queue(state,root,batch,incremental=True)
                    items.extend(i for i in queue['items'] if a.panels is None or i['panel_id'] in a.panels)
                result=prepare_review(state,root,{'items':items,'status':'REVIEW_TASKS_ONLY'})
        print(json.dumps(result,ensure_ascii=False));return 0
    except (OSError,ValueError,KeyError,TypeError,StopIteration,ImportError,AttributeError) as exc:
        print(json.dumps({'status':'HOLD','error':str(exc),'image_calls':0,'dispatch_authorized':False},ensure_ascii=False));return 1

if __name__=='__main__':raise SystemExit(main())
