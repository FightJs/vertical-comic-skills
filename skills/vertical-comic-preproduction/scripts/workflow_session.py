"""Local JSON-line worker for a single skill run. Never invokes image services."""
from pathlib import Path
from contextlib import nullcontext
from source_input_contract import strict_reads
import argparse,json,sys,time
from codex_reference_contract import read_json,file_session,digest
from validation_pool import ValidationPool,session
from runtime_pipeline import POLICY,record,budget

class WorkflowSession:
    def __init__(self, active_context=None):
        self.pool=ValidationPool();self.active_context=active_context;self.last_forecast=0

    def execute(self,request):
        if not isinstance(request,dict):raise ValueError('request must be an object')
        action=request['action'];path=Path(request['state']).resolve();root=path.parent.parent
        from runtime_clock import require_step
        from stage_deadlines import checkpoint, enabled as speed_enabled
        initial = read_json(path)
        speed = speed_enabled(initial)
        schedule=require_step(path,action,optional=request.get('optional',False) and not speed) if action not in {'commit','save-return','capture-return','register-return','recover-returns','executor-lifecycle','invocation-event','context-rebind-status','capture-envelope','record-envelope','delivery-status','qa-save-batch','review-submit-batch','prepare-qa'} else None
        if speed and (request.get('optional') or action == 'pilot-check'):
            from runtime_clock import execution_context
            context=execution_context(path)
            phase='preparation' if context and context['role']=='preparation' else 'intake'
            mark=checkpoint(path,phase,state=initial)
            if mark['degraded'] or action=='pilot-check':
                return {'status':'OPTIONAL_WORK_SKIPPED','stage_budget':mark,'action':action,
                        'next_action':'CONTINUE_REQUIRED_PRODUCTION_OR_DELIVERY',
                        'image_calls':0,'dispatch_authorized':False,'user_approval':'NOT_GRANTED'}
        started=time.monotonic()
        # Final delivery always reruns the full existing gate in a fresh pool.
        with (strict_reads() if action=='final-check' else nullcontext()), session(None if action=='final-check' else self.pool), budget(path,enabled=bool(schedule) or action in {'compile','receiver-audit','preparation-review'}):
            if action=='prepare-inputs':
                from prepared_job_store import store
                result=store(path).prepare(request.get('panels'),request.get('workers','all'))
            elif action=='claim-and-register':
                from generation_host import check_write_scope
                from runtime_pipeline import claim_and_register
                check_write_scope(path,root)
                result=claim_and_register(path,request['prepared_reference'])
            elif action=='ready-inputs':
                from prepared_job_store import store
                current=store(path)
                excluded=request.get('exclude_record_digests',[])
                limit=request.get('limit')
                if not isinstance(excluded,list) or any(not isinstance(k,str) for k in excluded):
                    raise ValueError('READY_EXCLUSIONS_INVALID')
                if limit is not None and (type(limit) is not int or limit<1):raise ValueError('READY_LIMIT_INVALID')
                excluded=set(excluded)
                selected=request.get('panels')
                if selected is not None and (not isinstance(selected,list) or any(not isinstance(p,str) for p in selected)):
                    raise ValueError('READY_PANEL_SELECTION_INVALID')
                selected=None if selected is None else set(selected)
                pending={r['panel_id']:r['attempt_id'] for r in initial['panels'] if r['status'] in {'PENDING','REPAIR_AUTHORIZED'}}
                with current.lock:
                    revision=current.revision
                    candidates=[current.ref(current.entries[k]) for p,k in current.ready.items() if k not in excluded and (selected is None or p in selected) and pending.get(p)==current.entries[k]['attempt_id']]
                jobs=[];invalid=[]
                for ref in candidates:
                    try:current.get(ref,initial);jobs.append(ref)
                    except (OSError,ValueError,KeyError,TypeError,StopIteration) as exc:
                        invalid.append({'panel_id':ref['panel_id'],'reason':str(exc)})
                    if limit is not None and len(jobs)>=limit:break
                result={'jobs':jobs,'revision':revision,'invalidated':invalid,'preparing':current.preparing,
                        'preparation_complete':current.preparation_started and not current.preparing and current.preparation_error is None,
                        'preparation_error':current.preparation_error,
                        'blocked_panels':[r for r in current.last_reports if r.get('status')!='PASS'],
                        'image_calls':0,'dispatch_authorized':False}
            elif action=='runtime-forecast':
                from stage_deadlines import forecast
                result=forecast(request.get('states',[str(path)]),schedule or {})
            elif action=='stage-check':
                result={'status':'STAGE_BUDGET','stage_budget':checkpoint(path,request['phase'],request.get('panel_id'),state=initial),'image_calls':0,'dispatch_authorized':False}
            elif action=='context-rebind-plan':
                from context_rebind import plan
                result=plan(path,request['replacements'])
            elif action=='context-rebind-apply':
                from context_rebind import apply
                result=apply(path,request['plan'])
            elif action=='context-rebind-status':
                from context_rebind import status
                result=status(path,request['plan_id'])
            elif action=='executor-lifecycle':
                from worker_watchdog import evaluate
                result=evaluate(request['snapshot'])
                if result['state']=='EXECUTOR_TERMINATED' and result['alerts']:
                    from generation_host import recover_returns
                    result['saved_return_reconciliation']=recover_returns(path,_context=self.active_context)
                result['image_calls']=0;result['dispatch_authorized']=False
            elif action=='recover-no-image':
                if request.get('terminal'):
                    from no_image_recovery import prepare_request
                    request={**request,'recovery':prepare_request(path,request['panel_id'],request['terminal'],
                        request['authorization'],diagnosis=request.get('diagnosis'))}
                if initial.get('dispatch_consistency'):
                    from managed_dispatch import call
                    result=call(path,action,expected_sha256=request['expected_state'],request=request['recovery'])
                else:
                    from no_image_recovery import recover
                    result=recover(path,request['expected_state'],request['recovery'])
            elif action=='invocation-event':
                from runtime_pipeline import record_invocation_event
                result=record_invocation_event(path,request['job'],request['event'])
            elif action=='capture-envelope':
                from generation_host import capture_envelope
                result=capture_envelope(path,request['job'],request['packet'],request.get('item',{}),context=self.active_context)
            elif action=='record-envelope':
                from generation_host import record_envelope
                result=record_envelope(path,request['job'],request.get('packet'),request['item'],request.get('authorization'))
            elif action=='delivery-status':
                from lean_delivery import MATERIAL,binding
                pending=[r['panel_id'] for r in initial['panels'] if initial.get('delivery_materials',{}).get(r['panel_id'],{}).get('policy')!=MATERIAL or initial['delivery_materials'][r['panel_id']].get('binding')!=binding(r)]
                import hashlib
                revision=hashlib.sha256(json.dumps([initial.get('approval_index'),[(r['panel_id'],r.get('adoption'),r.get('qa_report')) for r in initial['panels']]],sort_keys=True).encode()).hexdigest()
                result={'dispatch_revision':revision,'status':'CONTINUE_REQUIRED' if pending else 'MATERIALS_READY','pending_panel_ids':pending,
                    'runnable':[{'panel_id':r['panel_id'],'attempt_id':r['attempt_id']} for r in initial['panels'] if r['status'] in {'PENDING','REPAIR_AUTHORIZED'}], 'image_calls':0}
            elif action=='prepare-qa':
                from generation_host import prepare_qa
                result=prepare_qa(initial,root,request.get('panels'))
            elif action in {'qa-save-batch','review-submit-batch'}:
                from review_followup import submit
                results=[]
                for observation in request['observations']:
                    try:
                        if action=='review-submit-batch':
                            from codex_reference_contract import checked_file
                            ticket=read_json(checked_file(root,observation['review_ticket']))
                            current=read_json(path)
                            row=next(r for r in current['panels'] if r['panel_id']==ticket['panel_id'])
                            if (ticket.get('policy')!='observed_review_ticket_v1' or
                                any(ticket.get(k)!=current[k] for k in ('book_id','episode_id')) or
                                ticket['attempt_id']!=row['attempt_id'] or ticket['output']!=row.get('output')):
                                raise ValueError('OBSERVED_IMAGE_CHANGED')
                            fields={k:ticket[k] for k in ('panel_id','attempt_id','qa_template','base_qa')}
                            patch=observation['observation']
                            if set(patch)&set(fields):raise ValueError('REVIEW_IDENTITY_TOOL_OWNED')
                            observation={**patch,**fields}
                        results.append(submit(path,observation))
                    except (ValueError,KeyError,TypeError,OSError) as exc:results.append({'status':'HOLD','panel_id':observation.get('panel_id'),'error':str(exc)})
                result={'status':'OBSERVATIONS_RECORDED','results':results,'image_calls':0}
            elif action in {'capture-return','capture-envelope'}:
                from generation_host import capture_return
                result=capture_return(path,request['job'],request['raw'],request['call_locator'],request['result_locator'],request.get('selected_index'),_context=self.active_context,observed=request.get('observed'))
            elif action=='register-return':
                from generation_host import register_return
                result=register_return(path,request['capture'],_context=self.active_context)
            elif action=='recover-returns':
                from generation_host import recover_returns
                result=recover_returns(path,_context=self.active_context)
            elif action=='save-return':
                from generation_host import save_return
                result=save_return(path,request['job'],request['raw'],request['call_locator'],
                    request['result_locator'],request.get('selected_index'),_context=self.active_context,observed=request.get('observed'))
            elif action=='submit':
                from production_runtime import submit
                result=submit(path,request['job'])
            elif action=='commit':
                from production_runtime import commit_updates
                result=commit_updates(path,request['expected_state'],request['updates'])
            elif action=='qa-save':
                from review_pipeline import save
                result=save(path,request['expected_state'],request['observations'])
            elif action=='reserve':
                from episode_dispatch_queue import reserve_ready
                result=reserve_ready(path,request['expected_state'],request['expected_control'],request.get('max_count'))
            else:
                with file_session():
                    state=read_json(path)
                    if action=='compile':
                        from production_runtime import compile_jobs
                        result=compile_jobs(state,root,request.get('panels'),candidate=request.get('candidate',False),input_audit=request.get('input_audit',False))
                    elif action=='receiver-audit':
                        from production_runtime import receiver_audit
                        from codex_reference_contract import checked_file
                        ids=read_json(checked_file(root,state['source_snapshot']))['panel_ids']
                        result=receiver_audit(state,root,None,ids)
                    elif action=='preparation-review':
                        from production_runtime import preparation_review
                        result=preparation_review(state,root,panel_ids=request.get('panels'))
                    elif action=='final-check':
                        from staged_workflow import evaluate
                        result=evaluate(state,root,'deliver')
                    elif action=='pilot-check':result=pilot(state,root,request)
                    else:raise ValueError('unsupported workflow action: '+str(action))
        if action in {'capture-return','capture-envelope'}:
            result['workflow_timing']={'action':action,'elapsed_seconds':time.monotonic()-started}
            return result
        from runtime_clock import execution_context,status
        context=execution_context(path)
        if context and context.get('clock_required'):
            result['runtime_schedule']=status(context['clock_directory'])
            if action in {'reserve','save-return'} and time.monotonic()-self.last_forecast>=30:
                self.last_forecast=time.monotonic()
                try:
                    from stage_deadlines import forecast
                    state_paths=[path]
                    parallel=initial.get('parallel_context')
                    if parallel:
                        control=read_json(Path(parallel['control_file']))
                        state_paths=[Path(j['root'])/j.get('state_file','00_输入审计/生产流程.json') for j in control['jobs']]
                    result['completion_forecast']=forecast(state_paths,result['runtime_schedule'])
                except (OSError,ValueError,KeyError,TypeError) as exc:
                    result['forecast_unavailable']=str(exc)
        elapsed=time.monotonic()-started
        result['workflow_timing']={'action':action,'elapsed_seconds':elapsed,
                                   'validation_pool':dict(self.pool.statistics)}
        if action not in {'context-rebind-plan','context-rebind-status'} and request.get('record_timing',True) and read_json(path).get('runtime_pipeline_policy')==POLICY:
            try:result['workflow_metric']=record(path,action,{'operation':elapsed,**({'local_queue':max(0,started-request['_enqueued_monotonic'])} if '_enqueued_monotonic' in request else {})},panel_ids=request.get('panels',[]),operation_id=request.get('request_id'),parent_operation_id=None)
            except OSError as exc:result['timing_record_error']=str(exc)
        return result

def pilot(state,root,request):
    """Inspect actual completed evidence; synthetic API tests cannot certify it."""
    from production_evidence import attempt_errors
    from production_decisions import selected
    rows={r['panel_id']:r for r in state['panels']};ids=request.get('panels')
    if not isinstance(ids,list) or not ids or any(p not in rows for p in ids):raise ValueError('pilot requires exact complex panel IDs')
    errors=[]
    for pid in ids:
        errors.extend(attempt_errors(state,root,rows[pid]))
        try:selected(root,rows[pid])
        except (OSError,ValueError,KeyError,TypeError) as exc:errors.append(pid+':'+str(exc))
    repaired=request.get('repair_panel');row=rows.get(repaired,{})
    if row.get('round_id')!=2 or not row.get('attempt_history'):
        errors.append('REAL_REPAIR_NOT_OBSERVED: no completed second-attempt path')
    else:
        errors.extend(attempt_errors(state,root,row['attempt_history'][0]))
        errors.extend(attempt_errors(state,root,row))
        from codex_reference_contract import checked_file
        packet=read_json(checked_file(root,row['package_manifest']))
        panel=packet['panels'][0]
        if panel.get('operation')!='repair' or panel.get('repair_method','local_edit') not in {'local_edit','coordinate_local_edit'}:
            errors.append('REAL_LOCAL_REPAIR_NOT_OBSERVED')
        try:selected(root,row)
        except (OSError,ValueError,KeyError,TypeError) as exc:errors.append(str(exc))
    return {'status':'PILOT_EVIDENCE_COMPLETE' if not errors else 'PILOT_INCOMPLETE','errors':errors,
            'reviewed_panel_ids':ids,'repair_panel':repaired,'dispatch_authorized':False,
            'image_calls':0,'user_approval':'NOT_GRANTED'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--serve',action='store_true')
    p.add_argument('--request',help='single request JSON file; a worker shares memory only with --serve')
    a=p.parse_args();worker=WorkflowSession()
    if a.serve and a.request:p.error('choose --serve or --request')
    if not a.serve and not a.request:p.error('--serve or --request required')
    if a.serve and hasattr(sys.stdin,'reconfigure'):
        sys.stdin.reconfigure(encoding='utf-8',errors='strict')
    lines=sys.stdin if a.serve else [Path(a.request).read_text(encoding='utf-8-sig')]
    failed=False
    for line in lines:
        if not line.strip():continue
        request={}
        try:
            request=json.loads(line);result=worker.execute(request)
        except (OSError,ValueError,KeyError,TypeError,IndexError,StopIteration) as exc:
            failed=True;result={'status':'HOLD','error':str(exc),'image_calls':0,'dispatch_authorized':False}
        print(json.dumps({'request_id':request.get('request_id') if isinstance(request,dict) else None,'result':result},ensure_ascii=False),flush=True)
    return 0 if a.serve or not failed else 1

if __name__=='__main__':
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
