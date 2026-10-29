"""Evidence-bound technical retries. Never calls an image service or resets QA rounds."""
from pathlib import Path
import copy, hashlib, json, uuid
from codex_reference_contract import checked_file, read_json, digest
from platform_io import atomic_json
from authority_updates import state_write_lock
from dispatch_publication import require_legacy

POLICY = 'confirmed_no_image_recovery_v1'
OUTCOMES = {'NOT_INVOKED', 'REJECTED_NO_OUTPUT', 'FAILED_NO_OUTPUT', 'RESOLVED_NO_OUTPUT'}
CLEAR = ('output','qa_report','call_evidence','failure_diagnosis','ready_at','submitted_at',
         'returned_at','save_started_at','saved_at','qa_completed_at','qa_recorded_at',
         'timing_observations','quality_review','qa_revisions','prepared_registration_id')

def put(root, folder, value):
    raw=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    code=hashlib.sha256(raw).hexdigest();path=Path(folder)/('managed-'+code+'.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=raw:raise ValueError('RECOVERY_EVIDENCE_CONFLICT')
    else:atomic_json(path,value)
    return {'path':path.relative_to(root).as_posix(),'sha256':digest(path)}

def proof(state, root, row, evidence_ref, authorization_ref):
    report=read_json(checked_file(root,evidence_ref))
    expected={k:row[k] for k in ('panel_id','attempt_id','round_id')}
    expected.update(book_id=state['book_id'],episode_id=state['episode_id'])
    if any(report.get(k)!=v for k,v in expected.items()):raise ValueError('NO_IMAGE_SCOPE_CHANGED')
    if (report.get('no_image_confirmed') is not True or report.get('outcome') not in OUTCOMES or
        report.get('source_kind') not in {'observed_executor_outcome','observed_tool_error','observed_resolution'} or
        not report.get('source_locator') or not report.get('evidence')):
        raise ValueError('NO_IMAGE_NOT_PROVEN: timeout or missing file alone is insufficient')
    if report.get('rejection_kind')=='content_policy':raise ValueError('CONTENT_RESTRICTION_REQUIRES_COMPLIANT_INPUT')
    refs=report.get('evidence_files')
    if not isinstance(refs,list) or not refs:raise ValueError('NO_IMAGE_SOURCE_EVIDENCE_REQUIRED')
    for ref in refs:checked_file(root,ref)
    if row.get('status')=='RESULT_UNKNOWN' and (report['outcome']!='RESOLVED_NO_OUTPUT' or report['source_kind']!='observed_resolution'):
        raise ValueError('UNKNOWN_MUST_BE_RESOLVED_BEFORE_RETRY')
    if row.get('status')=='RESULT_UNKNOWN':
        if not row.get('call_evidence') or report.get('original_call_evidence')!=row['call_evidence']:
            raise ValueError('UNKNOWN_RESOLUTION_MUST_BIND_ORIGINAL_EVIDENCE')
        checked_file(root,row['call_evidence'])
    if report['outcome']=='NOT_INVOKED' and report.get('invocation_started') is not False:
        raise ValueError('NOT_INVOKED_REQUIRES_ACTUAL_EXECUTOR_FACT')
    auth=read_json(checked_file(root,authorization_ref))
    if (auth.get('source_kind')!='user_message' or not auth.get('source_locator') or not auth.get('quote') or
        auth.get('book_id')!=state['book_id'] or state['episode_id'] not in auth.get('episode_ids',[]) or
        row['panel_id'] not in auth.get('panel_ids',[]) or 'no_image_retry' not in auth.get('operations',[])):
        raise ValueError('RECOVERY_AUTHORIZATION_SCOPE: record existing user instruction once; do not invent approval')
    return report,auth

def history_errors(state, root, row):
    errors=[];seen=set();chain=row.get('no_image_history',[])
    if not isinstance(chain,list):return ['NO_IMAGE_HISTORY_INVALID']
    for entry in chain:
        try:
            old=entry['original_attempt'];rid=old['attempt_id']
            if rid in seen or rid==row.get('attempt_id') or old.get('output') or old.get('status') not in {'IN_FLIGHT','CALL_FAILED','RESULT_UNKNOWN','CANCELLED'}:
                raise ValueError('NO_IMAGE_HISTORY_CONFLICT')
            seen.add(rid)
            report,_=proof(state,root,old,entry['evidence'],entry['authorization'])
            if entry.get('policy')!=POLICY or entry.get('panel_id')!=row['panel_id'] or entry.get('round_id')!=old['round_id']:
                raise ValueError('NO_IMAGE_HISTORY_SCOPE')
            old_packet=read_json(checked_file(root,old['package_manifest']))
            if old_packet['panels'][0].get('generation_execution',{}).get('status')=='COMPLETED':
                raise ValueError('NO_IMAGE_CONFLICTS_WITH_COMPLETED_RETURN')
        except (OSError,ValueError,KeyError,TypeError) as exc:errors.append(str(exc))
    return errors

def recover(state_path, expected_sha256, request):
    """One CAS transaction, stable request id, new attempt; no extra quality round."""
    from runtime_clock import require_dispatch
    path=Path(state_path).resolve();root=path.parent.parent
    if not isinstance(request,dict) or not isinstance(request.get('request_id'),str) or not request['request_id'].strip():
        raise ValueError('RECOVERY_STABLE_REQUEST_ID_REQUIRED')
    key=hashlib.sha256(request['request_id'].encode()).hexdigest()
    request_digest=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
    with state_write_lock(path):
        state=read_json(path);require_legacy(state)
        previous=state.get('no_image_recoveries',{}).get(key)
        if previous:
            if previous['request_digest']!=request_digest:raise ValueError('RECOVERY_REQUEST_CONFLICT')
            return {**previous['result'],'status':'NO_IMAGE_RECOVERY_ALREADY_SAVED','image_calls':0,'invoke_allowed':False}
        if digest(path)!=expected_sha256:raise ValueError('STATE_CHANGED')
        require_dispatch(path)
        if state.get('execution_mode')!='episode_async_v1':raise ValueError('NO_IMAGE_RECOVERY_REQUIRES_EPISODE_MODE')
        row=next(r for r in state['panels'] if r['panel_id']==request['panel_id'])
        if row.get('attempt_id')!=request.get('original_attempt_id'):raise ValueError('RECOVERY_OLD_ATTEMPT_CHANGED')
        if row.get('status') not in {'IN_FLIGHT','CALL_FAILED','RESULT_UNKNOWN','CANCELLED'} or row.get('output'):
            raise ValueError('RECOVERY_ONLY_CONFIRMED_NO_IMAGE')
        errors=history_errors(state,root,row)
        if errors:raise ValueError(';'.join(errors))
        report,_=proof(state,root,row,request['evidence'],request['authorization'])
        if row['status']=='IN_FLIGHT' and report['outcome']!='NOT_INVOKED':
            raise ValueError('SAVE_ACTUAL_FAILURE_OR_RESOLVE_UNKNOWN_FIRST')
        # Two consecutive retries of identical inputs require a substantive, evidenced diagnosis.
        if len(row.get('no_image_history',[]))>=2:
            diagnosis=request.get('diagnosis')
            if not isinstance(diagnosis,dict) or not diagnosis.get('cause') or not diagnosis.get('remediation'):
                return {'status':'NO_IMAGE_DIAGNOSIS_REQUIRED','panel_id':row['panel_id'],'image_calls':0,'invoke_allowed':False,
                        'next_action':'DIAGNOSE_CAUSE_AND_CONTINUE_OTHER_READY_PANELS'}
            checked_file(root,diagnosis['evidence'])
            if any(e.get('diagnosis')==diagnosis for e in row['no_image_history']):raise ValueError('REPEATED_RECOVERY_METHOD: use a different evidenced remedy')
        packet_path=checked_file(root,row['package_manifest']);packet=read_json(packet_path)
        if packet['panels'][0].get('generation_execution',{}).get('status')=='COMPLETED':
            raise ValueError('RECOVERY_HAS_ACTUAL_RETURN: save the existing image')
        from production_runtime import package_signature
        signature=package_signature(packet,packet_path.parent)
        # Reuse immutable original local paths; only execution identity changes.
        packet=copy.deepcopy(packet);packet.pop('dispatch_receipt',None);packet.pop('dispatch_source_package',None)
        attempt=row['panel_id']+'-retry-'+uuid.uuid4().hex
        packet['round_context']={**packet['round_context'],'attempt_id':attempt}
        packet['panels'][0]['generation_execution']={'status':'NOT_RUN'}
        folder=path.parent/'no_image_recovery'/key
        # Relative references in the packet retain their original package root.
        packet_ref=put(root,packet_path.parent,packet)
        if package_signature(packet,packet_path.parent)!=signature:raise ValueError('RECOVERY_ACTUAL_INPUT_CHANGED')
        new=copy.deepcopy(state);target=next(r for r in new['panels'] if r['panel_id']==row['panel_id'])
        old={k:copy.deepcopy(v) for k,v in row.items() if k!='no_image_history'}
        entry={'policy':POLICY,'panel_id':row['panel_id'],'round_id':row['round_id'],
               'original_attempt':old,'new_attempt_id':attempt,'evidence':request['evidence'],
               'authorization':request['authorization'],'diagnosis':request.get('diagnosis')}
        target.setdefault('no_image_history',[]).append(entry)
        for name in CLEAR:target.pop(name,None)
        target.update(attempt_id=attempt,package_manifest=packet_ref,
                      status='PENDING' if row['round_id']==1 else 'REPAIR_AUTHORIZED')
        # Existing repair authority gains a versioned technical identity revision only.
        if row['round_id']==2:
            auth_ref=new.get('repair_authorizations',{}).get(row['panel_id'])
            auth=read_json(checked_file(root,auth_ref));auth=copy.deepcopy(auth)
            if auth.get('new_attempt_id')!=row['attempt_id']:raise ValueError('REPAIR_AUTHORITY_ATTEMPT_MISMATCH')
            auth.update(new_attempt_id=attempt,new_package_manifest=packet_ref,
                        technical_retry_of=auth_ref,technical_retry_evidence=request['evidence'])
            new['repair_authorizations'][row['panel_id']]=put(root,folder,auth)
        try:
            from slot_leases import close_no_image
        except ImportError:
            import importlib.util
            spec=importlib.util.spec_from_file_location('_recovery_slots',Path(__file__).with_name('slot_leases.py'))
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            close_no_image=module.close_no_image
        close_no_image(new,row,request['evidence'])
        errors=history_errors(new,root,target)
        if errors:raise ValueError(';'.join(errors))
        result={'status':'NO_IMAGE_RETRY_READY','panel_id':row['panel_id'],'original_attempt_id':row['attempt_id'],
                'attempt_id':attempt,'round_id':row['round_id'],'package_manifest':packet_ref,
                'next_action':'RESERVE_COMPILE_SUBMIT_THROUGH_ORIGINAL_GATES','image_calls':0,'invoke_allowed':False}
        new.setdefault('no_image_recoveries',{})[key]={'request_digest':request_digest,'result':result}
        history=path.parent/'runtime_history';history.mkdir(exist_ok=True)
        previous_path=history/(expected_sha256+'.json')
        if not previous_path.exists():previous_path.write_bytes(path.read_bytes())
        require_dispatch(path)
        atomic_json(path,new)
        return {**result,'state_sha256':digest(path)}
