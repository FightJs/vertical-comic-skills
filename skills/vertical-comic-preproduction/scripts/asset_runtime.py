"""A-stage image attempt lifecycle, separate from asset design/approval/publication.

All inputs and authorization are explicit scoped references. Never calls imagegen.
"""
import argparse
import json
from pathlib import Path
from codex_reference_contract import checked_file, digest, read_json, file_session
from platform_io import atomic_json, file_lock, configure_stdio
from submission_contract import POLICY, fingerprint, registration, acknowledgement, validate_job
from runtime_clock import execution_context, require_dispatch

LEDGER = 'asset_requests.json'


def compile_job(run_root, definition):
    root=Path(run_root).resolve()
    context=execution_context(root)
    if context is None: raise ValueError('ASSET_HOLD: explicit local execution context required')
    with file_session():
        spec=read_json(checked_file(root,definition))
        if spec.get('policy')!='asset_call_definition_v1' or spec.get('operation') not in {'generate','repair','retry'}:
            raise ValueError('ASSET_HOLD: explicit asset generation/repair definition required')
        keys=('book_id','episode_id','asset_id','attempt_id')
        if any(not isinstance(spec.get(k),str) or not spec[k].strip() for k in keys):
            raise ValueError('ASSET_HOLD: exact asset/attempt/scope required')
        basis=read_json(checked_file(root,spec['visual_basis']))
        if basis.get('book_id')!=spec['book_id'] or basis.get('episode_id')!=spec['episode_id']:
            raise ValueError('ASSET_HOLD: basis owner mismatch')
        needs=[r for r in basis.get('asset_tasks',[]) if r.get('asset_id')==spec['asset_id']]
        if len(needs)!=1 or needs[0].get('episode_id')!=spec['episode_id'] or not needs[0].get('source_basis'):
            raise ValueError('ASSET_HOLD: one existing source-scoped asset need required')
        auth=read_json(checked_file(root,spec['authorization']))
        lists=('episode_ids','asset_ids','operations')
        if any(not isinstance(auth.get(k),list) or not auth[k] or
               any(not isinstance(v,str) or not v for v in auth[k]) or len(set(auth[k]))!=len(auth[k]) for k in lists):
            raise ValueError('ASSET_HOLD: authorization scope must be explicit unique lists')
        if (auth.get('source_kind')!='user_message' or not auth.get('quote') or not auth.get('source_locator') or
            auth.get('book_id')!=spec['book_id'] or spec['episode_id'] not in auth.get('episode_ids',[]) or
            spec['asset_id'] not in auth.get('asset_ids',[]) or spec['operation'] not in auth.get('operations',[]) or
            type(auth.get('max_asset_calls')) is not int or auth['max_asset_calls']<1 or
            type(auth.get('max_inflight')) is not int or auth['max_inflight']<1):
            raise ValueError('ASSET_HOLD: scoped real authorization and confirmed call/capacity limits required')
        args=spec.get('arguments')
        if (not isinstance(args,dict) or set(args)-{'prompt','referenced_image_paths','transparent_background'} or
            not isinstance(args.get('prompt'),str) or not args['prompt'].strip() or
            type(args.get('transparent_background',False)) is not bool):
            raise ValueError('ASSET_HOLD: supported actual image arguments required')
        refs=spec.get('reference_files',[])
        if not isinstance(refs,list) or not 1<=len(refs)<=5:
            raise ValueError('ASSET_HOLD: 1..5 explicitly reviewed reference files required')
        paths=[str(checked_file(root,r).resolve()) for r in refs]
        if len(set(paths))!=len(paths) or args.get('referenced_image_paths')!=paths:
            raise ValueError('ASSET_HOLD: actual references differ from recorded files')
        if spec['operation'] in {'repair','retry'}:
            evidence_key='repair_evidence' if spec['operation']=='repair' else 'retry_evidence'
            if not spec.get('source_attempt_id') or not spec.get(evidence_key):
                raise ValueError('ASSET_HOLD: repair must retain source attempt and diagnosis')
            proof=read_json(checked_file(root,spec[evidence_key]))
            if (proof.get('source_attempt_id')!=spec['source_attempt_id'] or proof.get('asset_id')!=spec['asset_id'] or
                proof.get('episode_id')!=spec['episode_id'] or not proof.get('evidence') or
                (spec['operation']=='retry' and proof.get('no_image_confirmed') is not True)):
                raise ValueError('ASSET_HOLD: exact scoped diagnosis/no-image evidence required')
        job={'kind':'asset','book_id':spec['book_id'],'episode_id':spec['episode_id'],
             'job_id':'ASSET:'+spec['episode_id'],'asset_id':spec['asset_id'],'attempt_id':spec['attempt_id'],
             'arguments':args,'candidate_only':False,'input_audit_only':False,
             'submission':{'policy':POLICY,'task_id':context['run_id'],
                           'execution_context':context['reference'],'definition':definition,
                           'input_digest':fingerprint({'definition':definition,'arguments':args})}}
    return job, auth, spec


def ledger_path(root):
    return Path(root).resolve()/'00_任务协调'/LEDGER


def submit(run_root, job):
    root=Path(run_root).resolve();require_dispatch(root)
    definition=job.get('submission',{}).get('definition')
    if not isinstance(definition,dict): raise ValueError('SUBMISSION_HOLD: asset definition missing')
    path=ledger_path(root)
    with file_lock(path.with_suffix('.lock')):
        actual,auth,spec=compile_job(root,definition);validate_job(job,actual)
        key,record=registration(actual)
        run_id=actual['submission']['task_id']
        ledger=read_json(path) if path.exists() else {'policy':'asset_call_ledger_v1','run_id':run_id,'attempts':{}}
        if ledger.get('policy')!='asset_call_ledger_v1' or ledger.get('run_id')!=run_id:
            raise ValueError('ASSET_HOLD: asset ledger belongs to another run/protocol')
        attempts=ledger['attempts']
        if key in attempts:
            if attempts[key]['job_digest']!=record['job_digest']:raise ValueError('SUBMISSION_HOLD: asset input conflict')
            return acknowledgement(actual,attempts[key],fresh=False,state_sha256=digest(path))
        # Bind the authorization's identity and scope, not a changed file hash,
        # so editing an allowance record cannot reset previous consumption.
        scope=fingerprint([actual['submission']['task_id'],auth['book_id'],sorted(auth['episode_ids']),
                           sorted(auth['asset_ids']),auth['source_locator']])
        relevant=[r for r in attempts.values() if r['budget_scope']==scope]
        if len(relevant)>=auth['max_asset_calls']:raise ValueError('ASSET_BUDGET_EXHAUSTED')
        if sum(r['status'] in {'IN_FLIGHT','RESULT_UNKNOWN'} for r in attempts.values())>=auth['max_inflight']:
            raise ValueError('ASSET_CAPACITY_FULL')
        previous=[r for r in attempts.values() if r['asset_id']==actual['asset_id'] and r['episode_id']==actual['episode_id']]
        if any(r['status'] in {'IN_FLIGHT','RESULT_UNKNOWN'} for r in previous):
            raise ValueError('ASSET_HOLD: outstanding attempt cannot be replaced')
        if previous and spec['operation']=='generate':
            raise ValueError('ASSET_HOLD: existing attempt requires scoped repair or proven-no-image retry')
        if spec['operation']=='repair' and not any(r['attempt_id']==spec['source_attempt_id'] and r['status']=='GENERATED' for r in previous):
            raise ValueError('ASSET_HOLD: repair source must be a saved original attempt')
        if spec['operation']=='retry' and not any(r['attempt_id']==spec['source_attempt_id'] and r['status']=='CALL_FAILED' for r in previous):
            raise ValueError('ASSET_HOLD: retry requires confirmed failed call; never unknown')
        require_dispatch(root)
        attempts[key]={**record,'asset_id':actual['asset_id'],'episode_id':actual['episode_id'],
                       'attempt_id':actual['attempt_id'],'status':'IN_FLIGHT','budget_scope':scope,
                       'definition':definition,'operation':spec['operation'],
                       'source_attempt_id':spec.get('source_attempt_id'),'observed_tool_call':False}
        atomic_json(path,ledger)
        try: require_dispatch(root)
        except (OSError,ValueError) as exc:
            raise ValueError('SUBMISSION_REGISTERED_NO_INVOKE: '+str(exc)) from exc
        return acknowledgement(actual,record,fresh=True,state_sha256=digest(path))


def save(run_root, registration_id, result, *, resolution=None):
    """No clock admission here: already-submitted returns must remain savable."""
    root=Path(run_root).resolve();path=ledger_path(root)
    if not isinstance(result,dict) or result.get('status') not in {'GENERATED','CALL_FAILED','RESULT_UNKNOWN'}:
        raise ValueError('ASSET_SAVE_HOLD: explicit actual outcome required')
    with file_lock(path.with_suffix('.lock')):
        ledger=read_json(path);row=ledger['attempts'][registration_id]
        if result.get('attempt_id')!=row['attempt_id']:raise ValueError('ASSET_SAVE_HOLD: old attempt')
        evidence=read_json(checked_file(root,result['response_evidence']))
        if evidence.get('attempt_id')!=row['attempt_id'] or not evidence.get('source_locator'):
            raise ValueError('ASSET_SAVE_HOLD: exact returned evidence required')
        output=result.get('output')
        if result['status']=='GENERATED':
            checked_file(root,output)
            request=read_json(checked_file(root,result['request_evidence']))
            definition=read_json(checked_file(root,row['definition']))
            if (evidence.get('source_kind')!='observed_tool_result' or evidence.get('status')!='COMPLETED' or
                output not in evidence.get('outputs',[]) or request.get('source_kind')!='observed_tool_call' or
                not request.get('source_locator') or request.get('attempt_id')!=row['attempt_id'] or
                request.get('arguments')!=definition['arguments']):
                raise ValueError('ASSET_SAVE_HOLD: output not bound to actual return')
        elif evidence.get('source_kind') not in {'observed_tool_error','observed_executor_outcome'}:
            raise ValueError('ASSET_SAVE_HOLD: actual failure/unknown evidence required')
        elif result['status']=='CALL_FAILED' and evidence.get('no_image_confirmed') is not True:
            raise ValueError('ASSET_SAVE_HOLD: uncertain request must remain RESULT_UNKNOWN')
        value={k:result.get(k) for k in ('status','attempt_id','request_evidence','response_evidence','output')}
        token=fingerprint(value)
        if row.get('result_digest')==token:return {'status':'ASSET_RESULT_ALREADY_SAVED','registration_id':registration_id}
        if row['status']=='RESULT_UNKNOWN':
            proof=read_json(checked_file(root,resolution)) if resolution else {}
            if (proof.get('registration_id')!=registration_id or proof.get('attempt_id')!=row['attempt_id'] or
                proof.get('source_kind')!='observed_resolution' or not proof.get('source_locator') or
                proof.get('result_digest')!=token):raise ValueError('ASSET_SAVE_HOLD: unknown result requires exact resolution evidence')
        elif row['status']!='IN_FLIGHT':raise ValueError('ASSET_SAVE_HOLD: conflicting repeated return')
        row.setdefault('result_history',[]).append(value)
        row.update(value,result_digest=token)
        if result['status']=='GENERATED':row['observed_tool_call']=True
        atomic_json(path,ledger)
    return {'status':'ASSET_RESULT_SAVED','registration_id':registration_id,'asset_approval':'NOT_GRANTED'}


def main():
    configure_stdio();p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['compile','submit','save','status']);p.add_argument('--run-root',required=True)
    p.add_argument('--definition');p.add_argument('--job');p.add_argument('--result');p.add_argument('--registration-id');p.add_argument('--resolution')
    a=p.parse_args();root=Path(a.run_root).resolve()
    if a.action=='compile':
        q=Path(a.definition).resolve();q.relative_to(root)
        value=compile_job(root,{'path':q.relative_to(root).as_posix(),'sha256':digest(q)})[0]
    elif a.action=='submit':value=submit(root,read_json(Path(a.job)))
    elif a.action=='save':
        resolution=None
        if a.resolution:
            q=Path(a.resolution).resolve();q.relative_to(root);resolution={'path':q.relative_to(root).as_posix(),'sha256':digest(q)}
        value=save(root,a.registration_id,read_json(Path(a.result)),resolution=resolution)
    else:value=read_json(ledger_path(root))
    print(json.dumps(value,ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'ASSET_HOLD','error':str(exc),'image_calls':0},ensure_ascii=False));raise SystemExit(1)
