"""Prove and adopt prepared equivalent context packages; never repair authority.

Candidates are separately compiled immutable files. Plan is read-only; apply
reproves the plan and atomically changes one episode. Old artifacts are retained.
"""
import copy,hashlib,json
from pathlib import Path
from codex_reference_contract import checked_file,read_json,digest,file_session,verify_read_snapshot,_FILE_SESSION
from authority_updates import state_write_lock,_write_once,_encoded
from source_input_contract import strict_reads
from validation_pool import session
from platform_io import atomic_json

POLICY='equivalent_context_rebind_v1'

def _fingerprint(value):return hashlib.sha256(_encoded(value)).hexdigest()

def _pending(state,row,packet):
    from submission_contract import identity,fingerprint
    key=fingerprint([identity(state),state.get('parallel_context',{}).get('job_id',state['episode_id']),
                     'panel',row['panel_id'],row.get('attempt_id'),row.get('round_id')])
    if key in state.get('submission_registrations',{}):raise ValueError('REBIND_ALREADY_REGISTERED')
    if (row.get('status')!='PENDING' or row.get('round_id')!=1 or
        any(row.get(k) for k in ('attempt_history','output','qa_report','submission_record','submitted_at','ready_at','returned_at')) or
        any(packet.get(k) for k in ('dispatch_receipt','dispatch_source_package')) or
        any(p.get('generation_execution',{}).get('status') not in (None,'NOT_RUN') for p in packet.get('panels',[])) or
        any(p.get('panel_id')==row['panel_id'] for p in state.get('dispatch_ledger',[]))):
        raise ValueError('REBIND_NOT_PENDING: reserved, submitted or historical rows must retain original bindings')

def _context_signature(packet,base):
    from continuity_context import source_base
    from panel_readiness import design_signature
    ref=packet.get('continuity_context')
    if not ref:raise ValueError('REBIND_CONTEXT_REQUIRED')
    path=checked_file(base,ref);context=read_json(path)
    # Preserve all context structure and scope; source versions may differ only
    # when the actual referenced content below proves equivalent.
    signature={k:v for k,v in context.items() if k!='sources'};sources=[]
    for i,source in enumerate(context['sources']):
        root=source_base(source,path.parent)
        fixed={k:v for k,v in source.items() if k not in {'root','root_mode','shot_manifest','visual_approval','shot_approval','shot_approvals'}}
        fixed['root']=str(root)
        for key in ('source_script','source_snapshot','visual_basis'):checked_file(root,source[key])
        shots=read_json(checked_file(root,source['shot_manifest']))
        ids=[e['panel_id'] for e in context['entries'] if e['source']==i]
        rows={r['panel_id']:r for r in shots['panels']}
        sources.append({'source':fixed,'header':{k:v for k,v in shots.items() if k!='panels'},
                        'shots':[(pid,design_signature(rows[pid])) for pid in ids]})
    return {**signature,'sources':sources}

def _prepare(path,replacements):
    from input_semantics import actual_input
    from continuity_context import load_context,binding_errors
    from production_runtime import compile_jobs
    from execution_contract import state_errors
    state=read_json(path);root=path.parent.parent
    if state.get('source_input_policy')!='formal_source_inputs_v1' or state.get('execution_mode')!='episode_async_v1':
        raise ValueError('REBIND_NEW_RUN_ONLY: frozen legacy runs are not migrated')
    if 'dispatch_consistency' in state:raise ValueError('REBIND_MANAGED_PROTOCOL_UNSUPPORTED')
    errors=state_errors(state,root)
    if errors:raise ValueError(';'.join(errors))
    if not isinstance(replacements,list) or not replacements or any(not isinstance(r,dict) or not {'panel_id','package_manifest'}<=set(r) or set(r)-{'panel_id','package_manifest','shot_subset'} for r in replacements):
        raise ValueError('REBIND_EXACT_REPLACEMENTS_REQUIRED')
    ids=[r['panel_id'] for r in replacements]
    if len(set(ids))!=len(ids):raise ValueError('REBIND_DUPLICATE_PANEL')
    rows={r['panel_id']:r for r in state['panels']}
    if not set(ids)<=rows.keys():raise ValueError('REBIND_UNKNOWN_PANEL')
    shots=read_json(checked_file(root,state['shot_manifest']))
    by_id={r['panel_id']:r for r in shots['panels']}
    new=copy.deepcopy(state);updated={r['panel_id']:r for r in new['panels']};changes=[]
    for replacement in sorted(replacements,key=lambda r:list(rows).index(r['panel_id'])):
        pid=replacement['panel_id'];row=rows[pid]
        oldpath=checked_file(root,row['package_manifest']);newpath=checked_file(root,replacement['package_manifest'])
        if oldpath==newpath:raise ValueError('REBIND_NEW_FILE_REQUIRED')
        old=read_json(oldpath);candidate=read_json(newpath)
        _pending(state,row,old);_pending(state,row,candidate)
        if {k:v for k,v in old.items() if k!='continuity_context'}!={k:v for k,v in candidate.items() if k!='continuity_context'}:
            raise ValueError('REBIND_PACKAGE_NOT_EQUIVALENT:'+pid)
        if _context_signature(old,oldpath.parent)!=_context_signature(candidate,newpath.parent):
            raise ValueError('REBIND_CONTEXT_NOT_EQUIVALENT:'+pid)
        previous,issues=load_context(candidate,newpath.parent)
        issues+=binding_errors(new,root,candidate,newpath.parent)
        if issues:raise ValueError(';'.join(issues))
        before=actual_input(state,root,by_id[pid],old,oldpath.parent)
        after=actual_input(new,root,by_id[pid],candidate,newpath.parent)
        if before!=after:raise ValueError('REBIND_ACTUAL_INPUT_CHANGED:'+pid)
        if replacement.get('shot_subset'):
            oldsubset_path=checked_file(root,row['shot_subset']);newsubset_path=checked_file(root,replacement['shot_subset'])
            if oldsubset_path==newsubset_path:raise ValueError('REBIND_NEW_SUBSET_REQUIRED')
            oldsubset=read_json(oldsubset_path);newsubset=read_json(newsubset_path)
            if ({k:v for k,v in oldsubset.items() if k!='continuity_context'}!={k:v for k,v in newsubset.items() if k!='continuity_context'} or
                _context_signature(oldsubset,oldsubset_path.parent)!=_context_signature(newsubset,newsubset_path.parent)):
                raise ValueError('REBIND_SUBSET_NOT_EQUIVALENT:'+pid)
            updated[pid]['shot_subset']=copy.deepcopy(replacement['shot_subset'])
        updated[pid]['package_manifest']=copy.deepcopy(replacement['package_manifest'])
        changes.append({'panel_id':pid,'old':row['package_manifest'],'new':replacement['package_manifest'],
                        'old_shot_subset':row.get('shot_subset'),'new_shot_subset':updated[pid].get('shot_subset'),
                        'actual_input_sha256':_fingerprint(after)})
    # Full original gates check the current approval scope and revocations. An
    # equivalent prompt cannot bypass package approval or a real dependency.
    compiled=compile_jobs(new,root,ids,complete_scope=True)
    if {j['panel_id'] for j in compiled['jobs']}!=set(ids):
        raise ValueError('REBIND_APPROVAL_OR_DEPENDENCY_REVIEW_REQUIRED:'+json.dumps(compiled['preflight'],ensure_ascii=False))
    plan={'policy':POLICY,'state':str(path),'expected_state':digest(path),'changes':changes,
          'replacements':replacements,'dispatch_authorized':False,'image_calls':0}
    plan['plan_id']=_fingerprint(plan)
    return plan,new

def plan(state_path,replacements):
    path=Path(state_path).resolve()
    try:
        with strict_reads(),session(None),file_session():result,_=_prepare(path,replacements)
        return {'status':'EQUIVALENT_READY','plan':result,'dispatch_authorized':False,'image_calls':0}
    except (OSError,ValueError,KeyError,TypeError,StopIteration) as exc:
        return {'status':'REVIEW_REQUIRED','reason':str(exc),'dispatch_authorized':False,'image_calls':0}

def status(state_path,plan_id):
    path=Path(state_path).resolve();state=read_json(path)
    for ref in state.get('context_rebind_history',[]):
        receipt=read_json(checked_file(path.parent.parent,ref))
        if receipt.get('plan_id')==plan_id:
            return {'status':'APPLIED','receipt':ref,'plan_id':plan_id,'image_calls':0,'dispatch_authorized':False}
    return {'status':'NOT_APPLIED','plan_id':plan_id,'image_calls':0,'dispatch_authorized':False}

def apply(state_path,expected_plan):
    if _FILE_SESSION.get() is not None:raise ValueError('WRITE_REQUIRES_OWN_READ_TRANSACTION')
    path=Path(state_path).resolve()
    if expected_plan.get('state')!=str(path) or expected_plan.get('policy')!=POLICY:raise ValueError('REBIND_PLAN_IDENTITY')
    prior=status(path,expected_plan['plan_id'])
    if prior['status']=='APPLIED':return prior
    with strict_reads(),session(None),file_session() as snapshot:
        current,new=_prepare(path,expected_plan['replacements'])
        if current!=expected_plan:raise ValueError('REBIND_PLAN_CHANGED: prepare a fresh plan')
    root=path.parent.parent
    # Evidence is staged before the lock; a failed CAS leaves an unreferenced
    # immutable receipt, not permission to dispatch. Retry status is in state.
    receipt=_write_once(root,'context-rebind',_encoded(current))
    new.setdefault('context_rebind_history',[]).append(receipt)
    with state_write_lock(path):
        verify_read_snapshot(snapshot,refresh_views=False)
        if digest(path)!=current['expected_state']:raise ValueError('STATE_CHANGED')
        atomic_json(path,new)
    return {'status':'APPLIED','receipt':receipt,'plan_id':current['plan_id'],
            'state_sha256':digest(path),'dispatch_authorized':False,'image_calls':0}
