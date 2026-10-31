"""Recoverable production wiring. No image calls or inferred user authorization."""
from pathlib import Path
import copy, hashlib, json, uuid
from platform_io import atomic_json,file_lock

POLICY='production_activation_v1'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def encoded(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
def ref(p):return {'path':str(Path(p).resolve()),'sha256':sha(p)}

def lock_states(stack,names):
    """Same reservation lock order, deduplicated across a relocated owner."""
    from dispatch_publication import require_legacy
    from authority_updates import state_errors
    initial={};locks=set()
    for name in names:
        p=Path(name).resolve();state=read(p);require_legacy(state)
        errors=state_errors(state)
        if errors:raise ValueError(';'.join(errors))
        initial[p]=state;locks.add(p.with_suffix('.runtime.lock'))
        context=state.get('parallel_context')
        if context:locks.add(Path(context['control_file']).with_suffix('.dispatch.lock'))
    for lock in sorted(locks):stack.enter_context(file_lock(lock))
    for p,state in initial.items():
        current=read(p)
        if any(current.get(k)!=state.get(k) for k in ('parallel_context','authority_policy')):
            raise ValueError('ROUTING_OWNER_CHANGED')

def recover(run):
    run=Path(run).resolve();folder=run/'00_任务协调';journal=folder/'routing-transaction.json'
    if not journal.exists():return {'status':'NO_PENDING_TRANSACTION'}
    from contextlib import ExitStack
    from authority_updates import state_write_lock
    with file_lock(folder/'routing.lock'),ExitStack() as stack:
        value=read(journal)
        if value['status']=='COMMITTED':return {'status':'COMMITTED'}
        lock_states(stack,{item['path'] for item in value['writes'] if Path(item['path']).name=='生产流程.json'} | {name for name in value.get('guards',{}) if Path(name).name=='生产流程.json'})
        for name,version in value.get('guards',{}).items():
            if sha(name)!=version:raise ValueError('ROUTING_GUARD_CHANGED:'+name)
        # Validate every target before any further replacement. External edits are a HOLD.
        for item in value['writes']:
            p=Path(item['path']);current=sha(p) if p.exists() else None
            if current not in (item['before'],item['after']):raise ValueError('ROUTING_TARGET_CHANGED:'+str(p))
        for item in value['writes']:
            p=Path(item['path'])
            if p.exists() and sha(p)==item['after']:continue
            p.parent.mkdir(parents=True,exist_ok=True)
            atomic_json(p,item['value'])
            if sha(p)!=item['after']:raise ValueError('ROUTING_WRITE_HASH_MISMATCH')
        value['status']='COMMITTED';atomic_json(journal,value)
        return {'status':'COMMITTED','transaction_id':value['transaction_id'],'image_calls':0}

def transact(run, writes, expected):
    run=Path(run).resolve();folder=run/'00_任务协调';folder.mkdir(exist_ok=True,parents=True)
    writes={str(Path(k).resolve()):v for k,v in writes.items()}
    expected={str(Path(k).resolve()):v for k,v in expected.items()}
    recover(run)
    from contextlib import ExitStack
    from authority_updates import state_write_lock
    with file_lock(folder/'routing.lock'),ExitStack() as stack:
        lock_states(stack,{name for name in set(writes)|set(expected) if Path(name).name=='生产流程.json'})
        for name,version in expected.items():
            if (sha(name) if Path(name).exists() else None)!=version:raise ValueError('ROUTING_VERSION_CHANGED:'+name)
        rows=[]
        for name,value in writes.items():
            p=Path(name).resolve()
            if not p.is_relative_to(run):raise ValueError('ROUTING_PATH_OUTSIDE_RUN')
            before=sha(p) if p.exists() else None
            if str(p) not in expected or before!=expected[str(p)]:raise ValueError('ROUTING_VERSION_CHANGED:'+str(p))
            # atomic_json has one canonical serialization; stage to compute its bytes.
            staged=folder/('routing-stage-'+uuid.uuid4().hex+'.json');atomic_json(staged,value)
            after=sha(staged);staged.unlink()
            rows.append({'path':str(p),'before':before,'after':after,'value':value})
        old=folder/'routing-transaction.json'
        if old.exists():
            history=folder/'routing-history';history.mkdir(exist_ok=True)
            atomic_json(history/(read(old)['transaction_id']+'.json'),read(old))
        atomic_json(old,{'policy':POLICY,'transaction_id':uuid.uuid4().hex,'status':'PREPARED','writes':rows,'guards':{k:v for k,v in expected.items() if k not in writes}})
    return recover(run)

def recover_for(path):
    p=Path(path).resolve()
    for parent in (p.parent,*p.parents):
        if (parent/'00_任务协调/routing-transaction.json').exists():return recover(parent)
    return None

def require_active(path):
    path=Path(path).resolve();recover_for(path)
    assert_current_route(path)

def assert_current_route(path):
    path=Path(path).resolve()
    for parent in path.parents:
        journal=parent/'00_任务协调/routing-transaction.json'
        if journal.exists() and read(journal)['status']!='COMMITTED':raise ValueError('ROUTING_TRANSACTION_PENDING')
        identity=parent/'00_任务协调/交付身份.json'
        if not identity.exists():continue
        marker=read(identity);state=read(path)
        for target,scope in zip(marker.get('states',[]),marker.get('scope',[])):
            if scope==[state['book_id'],state['episode_id']] and Path(target).resolve()!=path:
                raise ValueError('EXECUTION_VIEW_RELOCATED:'+target)
        break

def activate(manifest_path, authorizations, expected_manifest):
    """Existing actual approval proofs keyed by episode; never interprets user prose."""
    manifest_path=Path(manifest_path).resolve();run=manifest_path.parent
    recover(run)
    if sha(manifest_path)!=expected_manifest:raise ValueError('ACTIVATION_MANIFEST_CHANGED')
    manifest=read(manifest_path);writes={};expected={str(manifest_path):expected_manifest};results=[]
    from codex_reference_contract import checked_file
    from staged_workflow import approval_errors
    from authority_updates import authority_context
    from parallel_dispatch import INPUTS
    from slot_leases import POLICY as LEASE
    for entry in manifest['episodes']:
        p=Path(entry['state']).resolve();state=read(p);root=p.parent.parent
        if not p.is_relative_to(run):raise ValueError('ACTIVATION_STATE_OUTSIDE_RUN')
        if state.get('parallel_context'):
            # Never transfer an established owner through an activation shortcut.
            from parallel_dispatch import context_errors
            errors=context_errors(state['parallel_context'],root,state['book_id'],state['episode_id'])
            results.append({'episode_id':entry['episode_id'],'status':'ALREADY_BOUND' if not errors else 'HOLD','errors':errors})
            continue
        if state.get('dispatch_consistency') or any(r.get('status') in {'RESERVED','IN_FLIGHT','RESULT_UNKNOWN'} for r in state['panels']):
            raise ValueError('ACTIVATION_RECONCILIATION_REQUIRED')
        approval=authorizations.get(entry['episode_id'],state.get('production_authorization'))
        if isinstance(approval,dict) and set(approval)=={'path','sha256'}:approval=read(checked_file(root,approval))
        ids=[r['panel_id'] for r in state['panels']]
        with authority_context(state,root):
            errors=approval_errors(approval,root,[state['source_script']],state['book_id'],state['episode_id'])
        if not approval or approval.get('policy')=='preparation_authorization_v1' or approval.get('phase')=='preparation':errors.append('PRODUCTION_AUTHORITY_REQUIRED')
        if not all(pid in (approval or {}).get('panel_ids',[]) or state['episode_id']+'-'+pid in (approval or {}).get('panel_ids',[]) for pid in ids):errors.append('PRODUCTION_SCOPE_MISMATCH')
        source=read(checked_file(root,state['source_snapshot']))
        if source.get('panel_ids')!=ids:errors.append('SOURCE_ORDER_MISMATCH')
        if entry['episode_id']!=state['episode_id'] or manifest['book_id']!=state['book_id'] or entry['panel_count']!=len(ids):errors.append('MANIFEST_SCOPE_MISMATCH')
        if errors:
            results.append({'episode_id':entry['episode_id'],'status':'HOLD','errors':errors});continue
        # Per-episode control retains one writer; machine permits remain shared globally.
        control_path=run/('control-'+state['episode_id']+'.json')
        if control_path.exists():raise ValueError('ACTIVATION_CONTROL_CONFLICT')
        basis_path=checked_file(root,state['visual_basis']);basis=read(basis_path)
        shared={str(basis_path):{'path':basis_path.relative_to(run).as_posix(),'sha256':sha(basis_path),'role':'state_registry'}}
        def visit(v):
            if isinstance(v,dict):
                if isinstance(v.get('path'),str) and isinstance(v.get('sha256'),str):
                    try:
                        file=checked_file(root,v)
                        if file.is_relative_to(run):shared[str(file)]={'path':file.relative_to(run).as_posix(),'sha256':v['sha256']}
                    except (OSError,ValueError):pass
                for x in v.values():visit(x)
            elif isinstance(v,list):
                for x in v:visit(x)
        visit(basis)
        shared[str(basis_path)]['role']='state_registry'
        if not set(basis.get('style',{}).get('reference_sha256',[])) <= {r['sha256'] for r in shared.values()}:raise ValueError('STYLE_REFERENCE_MISSING')
        job_id=state['episode_id'];worker='owner-'+uuid.uuid4().hex
        context={'control_file':str(control_path),'job_id':job_id,'worker_id':worker,'epoch':1}
        count=min(len(ids),manifest['max_inflight'])
        job={'job_id':job_id,'episode_id':state['episode_id'],'worker_id':worker,'root':str(root),
            'state_file':p.relative_to(root).as_posix(),'status':'RUNNING','active_batch_id':'EPISODE',
            'max_inflight':count,'frozen_inputs':{k:state[k] for k in INPUTS},
            'style_basis':shared[str(basis_path)],'slot_lease':{'lease_id':uuid.uuid4().hex,'slots':count,'dispatch_target':count,'worker_id':worker,'epoch':1}}
        control={'policy':'parallel_episodes_v1','version':1,'book_id':state['book_id'],'epoch':1,'cancelled':False,
            'holds':[],'max_workers':1,'max_inflight':count,'style_binding_policy':'style_basis_by_job_v1',
            'shared_files':list(shared.values()),'jobs':[job],'permits':[],'dispatch_policy':LEASE}
        new=copy.deepcopy(state);new['production_authorization']=approval;new['parallel_context']=context
        new.setdefault('runtime',{}).update(dispatch_policy=LEASE,max_inflight=count,active_batch_id='EPISODE')
        writes[str(p)]=new;expected[str(p)]=sha(p);writes[str(control_path)]=control;expected[str(control_path)]=None
        results.append({'episode_id':entry['episode_id'],'status':'ACTIVATED','source_order_verified':True,'production_authority_valid':True,'owner_capacity_bound':True})
    if writes:transact(run,writes,expected)
    return {'status':'ACTIVATED' if all(r['status']!='HOLD' for r in results) else 'PARTIAL_HOLD','episodes':results,'image_calls':0,'next':'BATCH_RUNNER'}

def switch_view(run, old_path, new_path, expected_identity):
    run=Path(run).resolve();recover(run);old_path=str(Path(old_path).resolve());new_path=str(Path(new_path).resolve())
    old_version=sha(old_path);new_version=sha(new_path)
    old=read(old_path);new=read(new_path)
    if any(old.get(k)!=new.get(k) for k in ('book_id','episode_id','panels','production_authorization','runtime_execution_context','source_script','source_snapshot','visual_basis','shot_manifest','approval_index','gates','runtime_snapshot','runtime_import')):
        raise ValueError('VIEW_SWITCH_EVIDENCE_CHANGED')
    if old.get('parallel_context')!=new.get('parallel_context'):raise ValueError('VIEW_SWITCH_OWNER_CHANGED')
    from codex_reference_contract import checked_file
    for state_,path_ in ((old,old_path),(new,new_path)):
        root_=Path(path_).parent.parent
        for key in ('source_script','source_snapshot','visual_basis','shot_manifest'):
            checked_file(root_,state_[key])
        for row in state_['panels']:
            for key in ('output','qa_report','package_manifest','shot_subset'):
                if row.get(key):checked_file(root_,row[key])
    if new.get('runtime_import'):
        from runtime_import import verify_binding
        verify_binding(new,Path(new_path).parent.parent)
    context=old.get('parallel_context')
    if any(r.get('status') in {'RESERVED','IN_FLIGHT','RESULT_UNKNOWN'} for r in old['panels']):
        raise ValueError('VIEW_SWITCH_RECONCILIATION_REQUIRED')
    control_writes={}
    if context:
        control_path=Path(context['control_file']);control=read(control_path)
        if len(control.get('jobs',[]))!=1:raise ValueError('VIEW_SWITCH_SHARED_CONTROL_REQUIRES_HANDOFF')
        if any(r.get('status') in {'RESERVED','IN_FLIGHT','RESULT_UNKNOWN'} for r in old.get('dispatch_ledger',[])):
            raise ValueError('VIEW_SWITCH_RECONCILIATION_REQUIRED')
        next_control_path=run/('view-control-'+uuid.uuid4().hex+'.json')
        next_control=copy.deepcopy(control);job=next_control['jobs'][0]
        for ref_ in next_control['shared_files']:
            ref_['path']=(control_path.parent/ref_['path']).resolve().relative_to(run).as_posix()
        if job.get('style_basis'):
            job['style_basis']['path']=(control_path.parent/job['style_basis']['path']).resolve().relative_to(run).as_posix()
        job['root']=str(Path(new_path).parent.parent);job['state_file']=Path(new_path).relative_to(Path(job['root'])).as_posix()
        new=copy.deepcopy(new);new['parallel_context']={**context,'control_file':str(next_control_path)}
        stopped=copy.deepcopy(control);stopped['jobs'][0].setdefault('holds',[]).append('EXECUTION_VIEW_RELOCATED')
        control_writes={str(next_control_path):next_control,str(control_path):stopped,new_path:new}
    identity=run/'00_任务协调/交付身份.json'
    if sha(identity)!=expected_identity:raise ValueError('VIEW_SWITCH_IDENTITY_CHANGED')
    marker=read(identity);requirements=Path(marker['requirements']['path'])
    targets=[requirements,identity,run/'整批执行清单.json',run/'00_显示进度/task.json',run/'00_任务协调/coordination.json']
    targets += sorted(run.glob('*_执行清单.json'))
    targets=list(dict.fromkeys(p for p in targets if p.exists()))
    writes={};expected={str(p):sha(p) for p in targets}
    expected[old_path]=old_version;expected[new_path]=new_version
    def replace(v):
        if isinstance(v,str):return new_path if v==old_path or (v.startswith('/') and str(Path(v).resolve())==old_path) else v
        if isinstance(v,list):return [replace(x) for x in v]
        if isinstance(v,dict):return {k:replace(x) for k,x in v.items()}
        return v
    # Stage hashes in dependency order using the same atomic writer.
    refs={}
    for p in targets:
        value=replace(read(p))
        def rebind(v):
            if isinstance(v,dict):
                if v.get('path') in refs and 'sha256' in v:v['sha256']=refs[v['path']]
                for x in v.values():rebind(x)
            elif isinstance(v,list):
                for x in v:rebind(x)
        rebind(value)
        temp=run/'00_任务协调'/('view-stage-'+uuid.uuid4().hex+'.json');atomic_json(temp,value);refs[str(p)]=sha(temp);temp.unlink()
        writes[str(p)]=value
    for name,value in control_writes.items():
        expected.setdefault(name,sha(name) if Path(name).exists() else None);writes[name]=value
    return transact(run,writes,expected)

def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest');p.add_argument('--authorizations');p.add_argument('--expected-manifest');p.add_argument('--recover');p.add_argument('--switch-run');p.add_argument('--old-state');p.add_argument('--new-state');p.add_argument('--expected-identity')
    a=p.parse_args()
    if a.recover:result=recover(a.recover)
    elif a.switch_run:result=switch_view(a.switch_run,a.old_state,a.new_state,a.expected_identity)
    else:result=activate(a.manifest,read(a.authorizations) if a.authorizations else {},a.expected_manifest)
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
