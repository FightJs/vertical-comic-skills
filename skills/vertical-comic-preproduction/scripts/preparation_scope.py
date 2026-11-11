"""Internal content-equivalence evidence, technical readiness and truthful risk reuse."""
import copy
from datetime import datetime, timezone
from pathlib import Path
from input_dependencies import fingerprint, file_hash, references
from panel_source import read
from platform_io import atomic_json, file_lock
from codex_reference_contract import checked_file
from preparation_gate_policy import EXCEPTION, FIELD, exception_record, review_errors

META='_preparation_scope'


def _content(value):
    if isinstance(value,dict):
        return {k:_content(v) for k,v in value.items() if not (k=='path' and 'sha256' in value)}
    if isinstance(value,list):return [_content(v) for v in value]
    return value


def snapshot(inputs, root, *, consumed_facts, file_refs=(), assembly=None, shared=None):
    """Explicit facts are the consumed read set; unknown facts are never discarded."""
    root=Path(root).resolve();files=[]
    for ref in file_refs:
        raw=Path(ref['path'])
        path=raw.resolve() if raw.is_absolute() else checked_file(root,ref)
        if file_hash(path)!=ref.get('sha256'):raise ValueError('SCOPE_FILE_HASH_MISMATCH:'+str(path))
        files.append({**copy.deepcopy(ref),'path':str(path),'sha256':file_hash(path)})
    value=copy.deepcopy(inputs)
    value[META]={'policy':'preparation_content_scope_v1','consumed_facts':copy.deepcopy(consumed_facts),
        'files':files,'assembly':copy.deepcopy(assembly or {}),'shared':copy.deepcopy(shared or {})}
    return value


def _reference_header(packet, shot, panel):
    header={k:copy.deepcopy(v) for k,v in packet.items() if k not in {'panels','visual_basis','shot_manifest'}}
    registry=header.get('identity_registry')
    if not isinstance(registry,dict):return header
    tables={'characters','appearance_states','scene_states','assets'};used=set()
    def strings(value):
        if isinstance(value,str):used.add(value)
        elif isinstance(value,dict):
            for child in value.values():strings(child)
        elif isinstance(value,list):
            for child in value:strings(child)
    strings([shot,panel]);selected={key:{} for key in tables}
    while True:
        before=len(used)
        for table in tables:
            for key,value in registry.get(table,{}).items():
                if key in used:selected[table][key]=value;strings(value)
        if len(used)==before:break
    header['identity_registry']={**registry,**selected}
    return header


def technical_inputs(state, root, shot, packet, package_root, *, dependency_plan=None, plan_row=None):
    """Run the existing compiler and semantic checks on one real completed input."""
    from input_semantics import actual_input, conflict_errors
    from codex_reference_contract import file_session, validate_panel
    from frame_ratio_plan import panel_errors as ratio_errors
    root=Path(root);package_root=Path(package_root)
    if state.get(FIELD)!=EXCEPTION:raise ValueError('SCOPE_EXCEPTION_POLICY_REQUIRED')
    if len(packet.get('panels',[]))!=1:raise ValueError('SCOPE_SINGLE_PANEL_REQUIRED')
    if shot.get('generation_dependencies'):
        return _planned_inputs(state,root,shot,dependency_plan,plan_row)
    with file_session():
        panel=packet['panels'][0]
        for key in ('book_id','episode_id'):
            if packet.get(key)!=state.get(key):raise ValueError('SCOPE_PACKET_AUTHORITY_MISMATCH:'+key)
        for key in ('visual_basis','shot_manifest','source_snapshot'):
            if key in packet and packet[key]!=state.get(key):raise ValueError('SCOPE_PACKET_AUTHORITY_MISMATCH:'+key)
        problems,submission=validate_panel(panel,package_root)
        if problems or submission is None:raise ValueError(';'.join(problems) or 'SCOPE_INPUT_NOT_EXECUTABLE')
        from identity_confirmation import validate_manifest
        problems=validate_manifest(packet,root,prompt=True,reference_root=package_root)
        problems+=conflict_errors(shot,submission['arguments']['prompt'],detail_warnings=[])
        problems+=ratio_errors(state,root,[panel],prompt=True)
        if problems:raise ValueError(';'.join(problems))
        # actual_input enforces source text, identity visibility, continuity,
        # applied rules and final reference bytes through the existing contract.
        value=actual_input(state,root,shot,packet,package_root)
        reference_header=_reference_header(packet,shot,panel)
        local_refs=list(references([shot,panel,reference_header]))
        files=[]
        for ref in local_refs:
            try:path=checked_file(package_root,ref)
            except (OSError,ValueError):path=checked_file(root,ref)
            files.append({**ref,'path':str(path),'sha256':file_hash(path)})
        prompt=package_root/panel.get('prompt_file',panel['panel_id']+'/prompt.txt')
        files.append({'path':str(prompt.resolve()),'sha256':file_hash(prompt),'purpose':'actual_prompt'})
        # The source and selected visual/rule contexts are already consumed by
        # actual_input. Assembly references are not expanded into an episode audit.
        facts={'shot':_content(shot),'panel':_content({k:v for k,v in panel.items() if k not in {'prompt_file','negative_prompt_file'}}),
            'packet_header':_content({k:v for k,v in packet.items() if k not in {'panels','visual_basis','shot_manifest'}}),
            'state':{k:copy.deepcopy(state[k]) for k in ('book_id','episode_id','input_semantics_policy',FIELD,
                'asset_format_policy','frame_ratio_policy') if k in state}}
        result=snapshot(value,root,consumed_facts=facts,file_refs=files,
            assembly={'shot_manifest':state.get('shot_manifest'),'source_snapshot':state.get('source_snapshot')})
        basis_path=checked_file(root,state['visual_basis'])
        result[META]['basis']={'path':str(basis_path),'sha256':file_hash(basis_path),'document':read(basis_path)}
        return result


def _planned_inputs(state, root, shot, dependency_plan, plan_row):
    from input_semantics import planned_input, dependency_rows, conflict_errors
    from visual_evidence import production_background_errors
    from frame_ratio_plan import panel_errors as ratio_errors, enabled as ratios_enabled, execution_block
    from codex_reference_contract import file_session
    with file_session():
        row=plan_row
        if row is None:row=dependency_rows(state,root,dependency_plan).get(shot['panel_id'])
        if row is None:raise ValueError('SCOPE_DEPENDENCY_PLAN_REQUIRED')
        value=planned_input(state,root,shot,row)
        prompt=value['prompt']
        problems=conflict_errors(shot,prompt,detail_warnings=[])+production_background_errors(shot,prompt)
        problems+=ratio_errors(state,root,[shot])
        if ratios_enabled(state) and execution_block(shot) not in prompt:problems.append('SCOPE_PLANNED_RATIO_PROMPT_MISSING')
        if problems:raise ValueError(';'.join(problems))
        files=[ref for ref in row.get('reference_files',[]) if not str(ref.get('path','')).startswith('@DEPENDENCY:')]
        result=snapshot(value,root,consumed_facts={'shot':_content(shot),'planned_row':_content(row)},file_refs=files,
            assembly={'shot_manifest':state.get('shot_manifest'),'source_snapshot':state.get('source_snapshot')})
        basis_path=checked_file(root,state['visual_basis'])
        result[META]['basis']={'path':str(basis_path),'sha256':file_hash(basis_path),'document':read(basis_path)}
        result[META]['dependency_plan']=copy.deepcopy(dependency_plan)
        return result


def _check_files(meta):
    for ref in meta.get('files',[]):
        if file_hash(ref['path'])!=ref['sha256']:raise ValueError('SCOPE_FILE_BYTES_CHANGED:'+ref['path'])
    basis=meta.get('basis')
    if basis and (file_hash(basis['path'])!=basis['sha256'] or read(basis['path'])!=basis['document']):
        raise ValueError('SCOPE_BASIS_EVIDENCE_CHANGED')


def _additive(before, after, path=()):
    """Only append new unused objects in existing named shared dictionaries."""
    if isinstance(before,dict) and isinstance(after,dict):
        if not set(before)<=set(after):return False
        additions=set(after)-set(before)
        table=(len(path)>=2 and path[-2]=='identity_registry' and path[-1] in
               {'characters','appearance_states','scene_states','assets'}) or (len(path)==1 and path[0] in
               {'appearance_details','scene_layouts','scene_views','scene_background_profiles'})
        known_maps={'appearance_details','scene_layouts','scene_views','scene_background_profiles'}
        known_map_addition=not path and all(k in known_maps and isinstance(after[k],dict) for k in additions)
        if additions and not (table or known_map_addition):return False
        return all(_additive(v,after[k],(*path,k)) for k,v in before.items())
    return before==after


def equivalence(previous_inputs, current_inputs):
    """Allow only assembly, identical file relocation and additive unused shared data."""
    old=copy.deepcopy(previous_inputs);new=copy.deepcopy(current_inputs)
    before=old.pop(META,None);after=new.pop(META,None);reasons=[]
    try:
        if before:_check_files(before)
        if after:_check_files(after)
        if before and after:
            known={'policy','consumed_facts','files','assembly','shared','basis','dependency_plan'}
            if not set(before)<=known or not set(after)<=known:reasons.append('unknown_scope_metadata')
            required={'policy','consumed_facts','files','assembly','shared'}
            if not required<=set(before) or not required<=set(after):reasons.append('missing_scope_metadata')
            if before.get('policy')!='preparation_content_scope_v1' or after.get('policy')!=before.get('policy'):reasons.append('scope_policy_changed')
            if not _additive(_content(before.get('consumed_facts')),_content(after.get('consumed_facts'))):reasons.append('consumed_facts_changed')
            if _content(before.get('files'))!=_content(after.get('files')):reasons.append('consumed_file_order_purpose_or_bytes_changed')
            prior=before.get('shared',{});current=after.get('shared',{})
            if any(k not in current or current[k]!=v for k,v in prior.items()):reasons.append('shared_changed_or_removed')
            if before.get('dependency_plan')!=after.get('dependency_plan'):reasons.append('dependency_plan_changed')
            a=before.get('basis');b=after.get('basis')
            if a or b:
                if not a or not b or not _additive(a['document'],b['document']):reasons.append('basis_not_bounded_additive')
                elif old.get('visual_basis_sha256')!=a['sha256'] or new.get('visual_basis_sha256')!=b['sha256']:
                    reasons.append('basis_proof_not_bound_to_input')
                else:
                    old.pop('visual_basis_sha256',None);new.pop('visual_basis_sha256',None)
        elif before or after:
            if old!=new:reasons.append('plain_input_requires_exact_match')
        if _content(old)!=_content(new):reasons.append('consumed_input_changed_or_unknown_difference')
    except (OSError,ValueError,TypeError,KeyError) as exc:reasons.append(str(exc))
    return {'policy':'preparation_equivalence_v1','equivalent':not reasons,'reasons':reasons,
        'previous_digest':fingerprint(previous_inputs),'current_digest':fingerprint(current_inputs),
        'user_approval':'NOT_GRANTED','dispatch_authorized':False}


def rebind(review, previous_inputs, current_inputs, *, target_inputs=None):
    errors=review_errors(review,previous_inputs)
    proof=equivalence(previous_inputs,current_inputs)
    if errors or not proof['equivalent']:raise ValueError('SCOPE_REUSE_HOLD:'+ ';'.join(errors+proof['reasons']))
    if target_inputs is not None:
        plain={k:v for k,v in current_inputs.items() if k!=META}
        if plain!=target_inputs:raise ValueError('SCOPE_TARGET_NOT_EXACT_CURRENT_INPUT')
    result=copy.deepcopy(review)
    result['input_digest']=fingerprint(current_inputs if target_inputs is None else target_inputs)
    result['reused_from']={'review':copy.deepcopy(review),'input_digest':fingerprint(previous_inputs),
        'proof':proof}
    return result


def _finalize(inputs_by_pid, observations, reviewer):
    records={};errors={};targets=[];waiting=[]
    for pid,inputs in inputs_by_pid.items():
        if inputs.get('panel_id',pid)!=pid or inputs.get(FIELD)!=EXCEPTION:
            errors[pid]=['SCOPE_INPUT_POLICY_OR_ID_MISMATCH'];continue
        try:
            if META in inputs:_check_files(inputs[META])
            observation=observations.get(pid)
            if inputs.get('preparation_requirements') and observation is None:
                targets.append(pid);continue
            record=exception_record(inputs,observation,reviewer)
            if record['review_performed']:
                record['observed_at']=copy.deepcopy(observation.get('observed_at'))
                record['recorded_at']=datetime.now(timezone.utc).isoformat()
            problems=review_errors(record,inputs)
            if problems:errors[pid]=problems
            else:
                records[pid]=record
                if inputs.get('dependency_plan'):waiting.append(pid)
        except (OSError,ValueError,TypeError,KeyError) as exc:errors[pid]=[str(exc)]
    return {'policy':'preparation_scope_result_v1','status':'PARTIAL_READY' if records and (errors or targets) else 'HOLD' if errors or targets else 'WAIT_DEPENDENCY' if waiting else 'TECHNICALLY_READY',
        'waiting_dependency_panel_ids':waiting,'records':records,'targeted_panel_ids':targets,'errors':errors,'review_performed':any(r['review_performed'] for r in records.values()),
        'dispatch_authorized':False,'user_approval':'NOT_GRANTED','image_calls':0}


def finalize_scope(inputs_by_pid, observations=None, reviewer=None, *, operation_id=None, receipt_root=None):
    """Receipts and the request are atomically committed before returning success."""
    observations={} if observations is None else observations
    request={'inputs':inputs_by_pid,'observations':observations,'reviewer':reviewer}
    if operation_id is None and receipt_root is None:return _finalize(inputs_by_pid,observations,reviewer)
    if not isinstance(operation_id,str) or not operation_id.strip() or receipt_root is None:
        raise ValueError('SCOPE_OPERATION_AND_RECEIPT_ROOT_REQUIRED')
    folder=Path(receipt_root)/'.preparation-scope-receipts';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(fingerprint(operation_id)+'.json')
    with file_lock(folder/'writer.lock'):
        if path.exists():
            receipt=read(path)
            if receipt['request']!=request:raise ValueError('SCOPE_OPERATION_CONTENT_CONFLICT')
            return copy.deepcopy(receipt['result'])
        result=_finalize(inputs_by_pid,observations,reviewer)
        atomic_json(path,{'operation_id':operation_id,'request':request,'result':result})
        return result
