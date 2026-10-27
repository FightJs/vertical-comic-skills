#!/usr/bin/env python3
"""Frozen-runtime host commands. No image service, inferred QA or parallel ledger."""
import sys
sys.dont_write_bytecode=True
import argparse, copy, hashlib, importlib.util, json, os, subprocess
from pathlib import Path
from datetime import datetime, timezone

HOST=Path(__file__).resolve().parent
# Receiver fixture observed on the legacy commit-only protocol. Full snapshot
# verification is still required; these two hashes do not grant approval.
LEGACY_PAIRS={('ed63dbc9e0d082d9e059f0c841699cdfde8f26737a8f00159a5c8daae03709b3',
               '5cb321a1078a6747c13ea61f9a41c144bb144f7e75eed67462ae2deec3cfa279')}


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
    if (digest(scripts/'production_runtime.py'),digest(scripts/'async_generation.js')) in LEGACY_PAIRS:
        return 'frozen_commit_inflight_v1'
    raise ValueError('UNSUPPORTED_LEGACY_PROTOCOL: preserve snapshot; explicit adapter required')


def activate(state_path):
    state_path=Path(state_path).resolve();state=read(state_path)
    manifest=Path(state['runtime_snapshot']['path'])
    if not manifest.is_absolute() or digest(manifest)!=state['runtime_snapshot']['sha256']:raise ValueError('SNAPSHOT_HOLD')
    scripts=manifest.parent/'skills/vertical-comic-preproduction/scripts'
    sys.path.insert(0,str(scripts))
    from runtime_snapshot import verify
    verified=verify(state['runtime_snapshot'])
    if Path(verified['scripts']).resolve()!=scripts.resolve():raise ValueError('SNAPSHOT_SCRIPT_SCOPE')
    caps=read(scripts/'runtime_capabilities.json');kind=protocol(scripts,caps)
    return state_path,state,state_path.parent.parent,scripts,kind


def inspect_runtime(state_path):
    path,state,root,scripts,kind=activate(state_path)
    return {'status':'RUNTIME_COMPATIBLE','submission_protocol':kind,'state':str(path),
            'frozen_manifest':state['runtime_snapshot'],'frozen_scripts':str(scripts),
            'executor':reference(scripts/'async_generation.js',scripts),
            'runtime_script':str(scripts/'production_runtime.py'),
            'clock_check':'installed_host_before_submit','image_calls':0,'dispatch_authorized':False}


def checked_job(state,root,job):
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


def save_return(state_path,job_path,raw_path,call_locator,result_locator,selected_index=None):
    path,state,root,scripts,kind=activate(state_path);job=read(job_path)
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
    bound,proof=binding_view(state,root,packet,packet_path.parent)
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
            'returned_at':now(),'save_started_at':now(),'saved_at':now()}
    result=commit_updates(path,digest(path),[update])
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
    worker=WorkflowSession()
    for line in sys.stdin:
        if not line.strip():continue
        request={}
        try:
            request=json.loads(line)
            if request.get('state') is not None and Path(request['state']).resolve()!=path:
                raise ValueError('WORKER_CANNOT_SWITCH_FROZEN_OWNER')
            request['state']=str(path)
            if request['action'] in {'reserve','submit'}:
                check_write_scope(path,root)
                check=subprocess.run([sys.executable,'-X','utf8','-B',str(HOST/'generation_host.py'),'clock-check','--state',str(path)],
                    capture_output=True,text=True,encoding='utf-8',env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
                if check.returncode:raise ValueError('HOST_CLOCK_HOLD: '+check.stdout+check.stderr)
            result=worker.execute(request)
        except (OSError,ValueError,KeyError,TypeError,StopIteration) as exc:
            result={'status':'HOLD','error':str(exc),'image_calls':0,'dispatch_authorized':False}
        print(json.dumps({'request_id':request.get('request_id'),'result':result},ensure_ascii=False),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['inspect-runtime','check-bindings','compile','prepare-submit','save-return','prepare-qa','clock-check','replay-return','recover-no-image','serve'])
    p.add_argument('--state',required=True);p.add_argument('--job');p.add_argument('--raw-result')
    p.add_argument('--output');p.add_argument('--call-locator');p.add_argument('--result-locator');p.add_argument('--selected-index',type=int)
    p.add_argument('--recovery-request');p.add_argument('--expected-state-sha256')
    p.add_argument('--panels',nargs='+');a=p.parse_args()
    try:
        if a.action=='clock-check':
            from runtime_clock import require_dispatch
            clock=require_dispatch(a.state)
            result={'status':'CLOCK_CHECKED','clock_observed':clock is not None,'image_calls':0}
        elif a.action=='recover-no-image':
            proc=subprocess.run([sys.executable,'-X','utf8','-B',str(HOST/'generation_host.py'),'clock-check','--state',a.state],
                                capture_output=True,text=True,encoding='utf-8',env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
            if proc.returncode:raise ValueError('HOST_CLOCK_HOLD: '+proc.stdout+proc.stderr)
            request=read(a.recovery_request)
            path,state,root,scripts,kind=activate(a.state)
            # Load the installed adapter without putting it into the frozen import path.
            spec=importlib.util.spec_from_file_location('_host_recovery_compatibility',HOST/'recovery_compatibility.py')
            compat=importlib.util.module_from_spec(spec);spec.loader.exec_module(compat)
            adapter=compat.prepare(a.state,request)
            check_write_scope(path,root)
            module=compat.load(adapter,path,request)
            if state.get('dispatch_consistency'):
                from managed_dispatch import authority
                with authority([path]):result=module.recover(path,a.expected_state_sha256,request)
            else:result=module.recover(path,a.expected_state_sha256,request)
            result['compatibility_adapter']=adapter
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
                if kind=='durable_image_submission_v1':
                    from production_runtime import submit
                    result=submit(path,job)
                else:
                    if row['package_manifest']!=job['package_manifest'] or row['status'] not in {'PENDING','REPAIR_AUTHORIZED'}:raise ValueError('DO_NOT_RESEND_ATTEMPT')
                    update={k:row[k] for k in ('panel_id','attempt_id','round_id')};update.update(status='IN_FLIGHT',submitted_at=now())
                    result=commit_updates(path,digest(path),[update])
                    result={**result,'submission_protocol':kind,'next':'Use frozen executor invoke callback once; old receipt is not SUBMISSION_REGISTERED'}
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
