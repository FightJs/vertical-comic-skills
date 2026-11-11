"""Preparation domain adapters: byte-preserving binding and original final gates."""
import copy
import json
from pathlib import Path
import shutil
from input_dependencies import fingerprint,file_hash
from platform_io import atomic_json,file_lock
from panel_source import read,expand


def reference(path,root=None):
    path=Path(path).resolve()
    return {'path':path.relative_to(Path(root).resolve()).as_posix() if root else str(path),'sha256':file_hash(path)}


def bind_packet(packet,shot,manifest,root,output):
    """Bind real hashes to episode-relative files; never alter creative inputs."""
    root=Path(root).resolve();origin=Path(manifest).resolve().parent
    def walk(value):
        if isinstance(value,list):return [walk(v) for v in value]
        if not isinstance(value,dict):return copy.deepcopy(value)
        result={k:walk(v) for k,v in value.items()}
        if isinstance(value.get('path'),str) and isinstance(value.get('sha256'),str):
            raw=Path(value['path']);choices=[raw] if raw.is_absolute() else [origin/raw,root/raw]
            path=next((p.resolve() for p in choices if p.is_file() and file_hash(p)==value['sha256']),None)
            if path is None:raise ValueError('WORKING_BINDING_MISSING_OR_CHANGED:'+value['path'])
            if not path.is_relative_to(root):
                destination=root/'.preparation-inputs'/(value['sha256']+path.suffix)
                destination.parent.mkdir(exist_ok=True)
                if not destination.exists():
                    temp=destination.with_suffix(destination.suffix+'.tmp');shutil.copyfile(path,temp)
                    if file_hash(temp)!=value['sha256']:raise ValueError('WORKING_BINDING_COPY_CHANGED')
                    temp.replace(destination)
                if file_hash(destination)!=value['sha256']:raise ValueError('WORKING_BINDING_CACHE_CHANGED')
                path=destination
            result['path']=path.relative_to(root).as_posix()
        return result
    bound=walk(packet);bound_shot=walk(shot)
    for panel in bound['panels']:
        for key,default in [('prompt_file','prompt.txt'),('negative_prompt_file','negative_prompt.txt')]:
            raw=Path(packet['panels'][0].get(key,default));path=raw if raw.is_absolute() else origin/raw
            if not path.is_file():raise ValueError('WORKING_BINDING_PROMPT_MISSING:'+str(path))
            panel[key]=path.resolve().relative_to(root).as_posix()
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    for panel in bound['panels']:
        sidecar=root/('.preparation-panel-'+fingerprint(str(Path(output).resolve()))+'.json')
        panel['panel_json_file']=sidecar.relative_to(root).as_posix()
        atomic_json(sidecar,panel)
    atomic_json(output,bound)
    return bound,bound_shot,reference(output),root


def combined_previous(config,output):
    """Latest exact row receipts, not an assertion that every source row exists."""
    if not config.get('panels'):return None
    if config.get('derivations'):last=read(config['derivations'][-1]['path'])
    else:
        from panel_derivation import POLICY
        from preparation_workspace import Workspace
        last={'policy':POLICY,'book_id':expand(config['shot_header'],config['shared'])['book_id'],'episode_id':config['episode_id'],'panel_ids':Workspace(config['run_root']).read()['panel_ids']}
    rows={p:row['derivation'] for p,row in config['panels'].items() if row.get('derivation')}
    last['panels']=[rows[p] for p in last['panel_ids'] if p in rows]
    last['selected_panel_ids']=[p['panel_id'] for p in last['panels']]
    atomic_json(output,last);return output


def bootstrap_state(config,source_script=None,state_updates=None):
    """Create truthful pending records from a complete source, with no fake shots."""
    from authority_updates import state_write_lock
    from scoped_inputs import build_plan
    path=Path(config['state_path']);root=Path(config['run_root']);old=read(path);state=copy.deepcopy(old)
    source_ref=config['source_snapshot'];source=read(root/source_ref['path'])
    if state.get('source_snapshot') not in (None,source_ref):raise ValueError('CONFIGURE_SOURCE_BINDING_CONFLICT')
    source_script=source_script or state.get('source_script')
    if source_script is None:raise ValueError('CONFIGURATION_REQUIRED:source_script')
    from codex_reference_contract import checked_file
    checked_file(root,source_script);checked_file(root,source_ref)
    state.update(state_updates or {});state.update(source_script=source_script,source_snapshot=source_ref,
        frame_ratio_policy='content_balanced_ratios_v1',frame_ratio_plan=config['frame_ratio_plan'])
    existing={p['panel_id']:p for p in state.get('panels',[])}
    if existing and list(existing)!=source['panel_ids']:raise ValueError('CONFIGURE_EXISTING_SOURCE_ORDER_CHANGED')
    state['panels']=[existing.get(pid,{'panel_id':pid,'source_panel_id':episode_pid(state['episode_id'],pid),
        'status':'PENDING','round_id':1,'attempt_id':pid+'-r1'}) for pid in source['panel_ids']]
    folder=root/'.preparation-pipeline';folder.mkdir(exist_ok=True)
    batch=folder/'batch-plan.json';atomic_json(batch,build_plan(state,source));state['batch_plan']=reference(batch,root)
    if not state.get('semantic_audit'):
        audit=folder/'pending-semantic-audit.json';atomic_json(audit,{'policy':'semantic_audit_v1','status':'WORKING_DRAFT',
            'book_id':state['book_id'],'episode_id':state['episode_id'],'source_snapshot':source_ref,
            'visual_basis':state.get('visual_basis'),'shot_manifest':None,'panel_ids':source['panel_ids'],
            'panels':[{'panel_id':pid,'status':'PENDING'} for pid in source['panel_ids']]})
        state['semantic_audit']=reference(audit,root)
    with state_write_lock(path):
        if read(path)!=old:raise ValueError('CONFIGURE_STATE_CHANGED')
        atomic_json(path,state)
    return state


def episode_pid(episode,pid):return pid if pid.startswith(episode+'-') else episode+'-'+pid


def seal_episode(host,episode,config,request):
    """Materialize complete legacy state, rebind exact observations, then old gates.

    A truthful HOLD with missing package_root/assembly/export inputs is expected
    until a factual handoff assembly has been supplied. No template is invented.
    """
    from preparation_workspace import Workspace
    from panel_derivation import derive
    from preparation_scope import rebind
    from input_semantics import actual_input,planned_input,dependency_rows,coverage
    from codex_reference_contract import checked_file
    from authority_updates import state_write_lock
    from preparation_review import finalize
    root=Path(config['run_root']);state_path=Path(config['state_path']);workspace=Workspace(root)
    revision=workspace.read()['revision'];folder=root/'.preparation-pipeline'/'sealed'/str(revision);folder.mkdir(parents=True,exist_ok=True)
    domain_receipt=folder/'domain-receipt.json'
    if domain_receipt.exists():
        saved=read(domain_receipt)
        if saved['panels_digest']==fingerprint(config['panels']) and saved['state']==reference(state_path):
            return _seal_package(host,episode,config,request,copy.deepcopy(saved['result']),folder)
    source=folder/'full-authoring.json'
    if not source.exists():workspace.materialize(source)
    previous=combined_previous(config,folder/'prior-rows.json');output=folder/'derived';receipt_path=output/'派生记录.json'
    if receipt_path.is_file():derived=read(receipt_path)
    else:derived=derive(source,output,previous=previous,executor=host.derivation)
    if derived.get('errors') or derived.get('pending_panel_ids'):
        return {'status':'HOLD','errors':derived.get('errors'),'missing_panel_ids':derived.get('pending_panel_ids',[])}
    old=read(state_path);state=copy.deepcopy(old);shots=read(output/'镜头派生.json');bound_shots=[];by_id={p['panel_id']:p for p in state['panels']}
    derived_rows={row['panel_id']:row for row in derived['panels']}
    final_packets={}
    for shot in shots['panels']:
        pid=shot['panel_id'];row=derived_rows[pid];manifest=row['artifacts'][0]['path'];packet=read(manifest)
        # Bind the actual current derivation; stale collected shots cannot be
        # substituted merely because their row version happened not to change.
        packet,bound_shot,bound_ref,_=bind_packet(packet,shot,manifest,root,root/('.preparation-sealed-'+str(revision)+'-'+pid+'.json'))
        bound_shots.append(bound_shot);final_packets[pid]=packet
        by_id[pid]['package_manifest']=reference(bound_ref['path'],root)
        by_id[pid]['shot_subset']=by_id[pid]['package_manifest']
    bound_header,_,_,_=bind_packet({**{k:v for k,v in shots.items() if k!='panels'},'panels':[]},{},output/'镜头派生.json',root,folder/'bound-header.json')
    shots={**bound_header,'panels':bound_shots}
    shot_path=folder/'shots.json';atomic_json(shot_path,shots);state['shot_manifest']=reference(shot_path,root)
    source_state=workspace.read();state['source_snapshot']=source_state['source_snapshot']
    # Rebind same-episode context to the current full collection using the
    # existing runtime-gate resolver. It reads real current A/B authorities;
    # no old approval is relabelled to changed shots.
    for shot in bound_shots:
        pid=shot['panel_id'];packet=final_packets[pid]
        if packet.get('continuity_context'):
            original_context=read(root/packet['continuity_context']['path']);context=copy.deepcopy(original_context)
            for context_source in context.get('sources',[]):
                if context_source['episode_id']!=episode:continue
                context_source.update(root='.',root_mode='context_relative_v1',source_script=state['source_script'],
                    source_snapshot=state['source_snapshot'],visual_basis=state['visual_basis'],shot_manifest=state['shot_manifest'],
                    approval_resolution='source_runtime_gates_v1',source_state_file=state_path.relative_to(root).as_posix())
                for field in ('visual_approval','shot_approval','shot_approvals'):context_source.pop(field,None)
            context_path=root/('.preparation-context-'+str(revision)+'-'+pid+'.json');atomic_json(context_path,context)
            packet['continuity_context']=reference(context_path,root)
        # A literal source subset is separate from the execution payload.
        packet_path=root/('.preparation-sealed-'+str(revision)+'-'+pid+'.json');atomic_json(packet_path,packet)
        by_id[pid]['package_manifest']=reference(packet_path,root)
        subset=root/('.preparation-subset-'+str(revision)+'-'+pid+'.json')
        atomic_json(subset,{**{k:v for k,v in packet.items() if k!='panels'},'panels':[shot]})
        by_id[pid]['shot_subset']=reference(subset,root)

    audit=read(checked_file(root,old['semantic_audit']));original_audit=copy.deepcopy(audit)
    audit.update(book_id=state['book_id'],episode_id=episode,source_snapshot=state['source_snapshot'],
        visual_basis=state['visual_basis'],shot_manifest=state['shot_manifest'],panel_ids=source_state['panel_ids'])
    audit['panels']=[];plan=config.get('dependency_plan');plans=dependency_rows(state,root,plan)
    for shot in bound_shots:
        pid=shot['panel_id'];record=config['panels'][pid];packet=final_packets[pid]
        inputs=planned_input(state,root,shot,plans[pid]) if shot.get('generation_dependencies') else actual_input(state,root,shot,packet,root)
        review=rebind(record['review'],record['inputs'],inputs)
        audit['panels'].append({'panel_id':pid,'execution_review':review})
    audit['preparation_gate_policy']=state['preparation_gate_policy']
    audit_path=folder/'semantic-audit.json';atomic_json(audit_path,audit);state['semantic_audit']=reference(audit_path,root)
    # Original observations and their source binding remain immutable evidence.
    history=folder/'scope-history.json';atomic_json(history,{'policy':'preparation_scope_history_v1','original_audit':original_audit,
        'original_audit_ref':old['semantic_audit'],'scopes':{pid:{'inputs':row['inputs'],'review':row['review']} for pid,row in config['panels'].items()}})
    state['preparation_scope_history']=reference(history,root)
    with state_write_lock(state_path):
        if read(state_path)!=old:raise ValueError('SEAL_STATE_CHANGED')
        if workspace.read()['revision']!=revision:raise ValueError('SEAL_WORKSPACE_CHANGED')
        atomic_json(state_path,state)
    # Existing full validator is authoritative. Rebind is not a replacement gate.
    final=finalize(state_path,dependency_plan=plan)
    state=read(state_path);domain=coverage(state,root,plan)
    if domain['errors']:return {'status':'HOLD','domain_status':domain['status'],'errors':domain['errors'],'finalization':final}
    if config.get('authority'):
        final=finalize(state_path,authority_ref=config['authority'],reviewer=config.get('reviewer'),dependency_plan=plan)
        if final.get('review',{}).get('errors'):return {'status':'HOLD','errors':final['review']['errors'],'finalization':final}
    result={'status':'HOLD','domain_status':domain['status'],'finalization':final,
        'state':reference(state_path),'authoring_source':reference(source),'derivation_metrics':derived['metrics'],'image_calls':0,'dispatch_authorized':False}
    atomic_json(domain_receipt,{'panels_digest':fingerprint(config['panels']),'state':reference(state_path),'result':result})
    return _seal_package(host,episode,config,request,result,folder)


def _seal_package(host,episode,config,request,result,folder):
    settings={**config.get('seal',{}),**{k:v for k,v in request.items() if k not in {'request_id','action','episode_id','operation_id'}}}
    if not settings.get('package_root'):
        from preparation_handoff import build_package
        states=[str(Path(v['path'] if isinstance(v,dict) else v).resolve()) for v in host.descriptor.get('states',[])]
        assembled=build_package(host.root,states,{**host.descriptor,**settings})
        if not assembled.get('package_root'):
            needed=folder/('assembly-needed-'+fingerprint(assembled.get('missing',[]))+'.json');atomic_json(needed,assembled)
            task_id='batch:handoff-plan:'+fingerprint(assembled.get('missing',assembled.get('missing_keys',[])))
            with host.lock:
                host.scheduler.register([host._task(task_id,'handoff_assembly_plan',episode,[reference(needed)],
                    {'submission_action':'seal','missing':assembled.get('missing',[]),'missing_keys':assembled.get('missing_keys',[])})],epoch=host.epoch)
            return {**result,'assembly':assembled,'missing_keys':assembled.get('missing_keys',[]),'host_needed_task_id':task_id}
        settings['package_root']=assembled['package_root']
        result['assembly']=assembled
    from handoff_zip import audit_index,pack,release
    package=Path(settings['package_root']).resolve()
    if settings.get('assembly_plan'):
        from handoff_delivery import copy_assembly_plan
        plan_value=settings['assembly_plan'];plan_value=read(plan_value) if isinstance(plan_value,str) else plan_value
        if not settings.get('assembly_destination'):return {**result,'missing_keys':['assembly_destination']}
        destination=Path(settings['assembly_destination'])
        if not destination.exists():copy_assembly_plan(package,destination,plan_value)
        package=destination
    index=audit_index(package)
    current={read(Path(v['path'] if isinstance(v,dict) else v))['episode_id']:read(Path(v['path'] if isinstance(v,dict) else v)) for v in host.descriptor.get('states',[])}
    if index.get('book_id')!=host.descriptor['book_id'] or set(e['episode_id'] for e in index['episodes'])!=set(current):
        raise ValueError('HANDOFF_CURRENT_BATCH_MISMATCH')
    for episode_index in index['episodes']:
        state=current[episode_index['episode_id']]
        for key in ('source_script','source_snapshot','visual_basis','shot_manifest','semantic_audit'):
            if state.get(key) and episode_index.get(key,{}).get('sha256')!=state[key].get('sha256'):
                raise ValueError('HANDOFF_CURRENT_INPUT_MISMATCH:'+episode_index['episode_id']+':'+key)
    # A supplied factual plan closes obsolete planning work. Unknown native
    # executions retain their occupancy until their own host is reconciled.
    proof_path=folder/'assembly-satisfied.json';atomic_json(proof_path,{'policy':'preparation_assembly_satisfied_v1',
        'package_root':str(package),'index':reference(package/'交接验收索引.json')})
    with host.lock:planning=[t for t in host.scheduler.status()['tasks'].values() if t['kind']=='handoff_assembly_plan' and t['status'] not in {'COMMITTED','SUPERSEDED','STOPPED'}]
    for task in planning:
        if task['status']=='READY':
            with host.lock:host.scheduler.claim(task['task_id'],epoch=host.epoch)
            host._finish_task(task['task_id'],[reference(proof_path)],{'status':'ASSEMBLY_FACTS_SATISFIED'})
        elif not task.get('native_inflight') or request.get('task_id')==task['task_id']:
            host._finish_task(task['task_id'],[reference(proof_path)],{'status':'ASSEMBLY_FACTS_SATISFIED'})
        else:
            with host.lock:host.scheduler.reconcile({task['task_id']:{'status':'SUPERSEDED','evidence':reference(proof_path),
                'wait_reason':'FACTS_SUPPLIED_NATIVE_OUTCOME_STILL_REQUIRES_RECONCILIATION'}},epoch=host.epoch)
    candidate=Path(settings.get('candidate_zip',str(folder/'candidate.zip')))
    if not candidate.exists():pack(package,candidate)
    result.update(candidate_zip=str(candidate),package_root=str(package),missing_keys=[])
    if not settings.get('export_authorization'):return {**result,'missing_keys':['export_authorization']}
    if not settings.get('output'):return {**result,'missing_keys':['output']}
    # approved_inputs_content_export_v1 intentionally permits a real content
    # export without rehearsal. Other authorizations retain original release rules.
    released=release(candidate,settings.get('rehearsal_report'),settings['export_authorization'],settings['output'])
    return {**result,**released,'status':released['status'],'missing_keys':[]}
