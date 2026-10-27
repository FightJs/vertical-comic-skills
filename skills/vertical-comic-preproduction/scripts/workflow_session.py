"""Local JSON-line worker for a single skill run. Never invokes image services."""
from pathlib import Path
from contextlib import nullcontext
from source_input_contract import strict_reads
import argparse,json,sys,time
from codex_reference_contract import read_json,file_session,digest
from validation_pool import ValidationPool,session
from runtime_pipeline import POLICY,record,budget

class WorkflowSession:
    def __init__(self):self.pool=ValidationPool()

    def execute(self,request):
        if not isinstance(request,dict):raise ValueError('request must be an object')
        action=request['action'];path=Path(request['state']).resolve();root=path.parent.parent
        from runtime_clock import require_step
        from stage_deadlines import checkpoint, enabled as speed_enabled
        initial = read_json(path)
        speed = speed_enabled(initial)
        schedule=require_step(path,action,optional=request.get('optional',False) and not speed) if action not in {'commit','context-rebind-status'} else None
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
            if action=='stage-check':
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
        from runtime_clock import execution_context,status
        context=execution_context(path)
        if context and context.get('clock_required'):
            result['runtime_schedule']=status(context['clock_directory'])
        elapsed=time.monotonic()-started
        result['workflow_timing']={'action':action,'elapsed_seconds':elapsed,
                                   'validation_pool':dict(self.pool.statistics)}
        if action not in {'context-rebind-plan','context-rebind-status'} and request.get('record_timing',True) and read_json(path).get('runtime_pipeline_policy')==POLICY:
            try:result['workflow_metric']=record(path,action,{'operation':elapsed},panel_ids=request.get('panels',[]))
            except OSError as exc:result['timing_record_error']=str(exc)
        return result

def pilot(state,root,request):
    """Inspect actual completed evidence; synthetic API tests cannot certify it."""
    from batch_round import attempt_errors
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
