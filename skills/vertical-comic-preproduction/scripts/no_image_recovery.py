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
         'registered_at','invocation_requested_at','native_started_at','native_completed_at','invocation_events',
         'timing_observations','quality_review','qa_revisions','prepared_registration_id')

def put(root, folder, value):
    raw=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    code=hashlib.sha256(raw).hexdigest();path=Path(folder)/('managed-'+code+'.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=raw:raise ValueError('RECOVERY_EVIDENCE_CONFLICT')
    else:atomic_json(path,value)
    return {'path':path.relative_to(root).as_posix(),'sha256':digest(path)}


def prepare_request(state_path, panel_id, terminal_ref, authorization_ref, *, diagnosis=None):
    """Build scope/identity from the actual attempt and an observed terminal.

    This only prepares evidence; recover still enforces settlement, authority,
    clock, CAS and retry limits. Generic errors/timeouts cannot prove no output.
    """
    path=Path(state_path).resolve();root=path.parent.parent;state=read_json(path)
    row=next(r for r in state['panels'] if r['panel_id']==panel_id)
    terminal=read_json(checked_file(root,terminal_ref))
    if terminal.get('attempt_id')!=row['attempt_id']:raise ValueError('NO_IMAGE_TERMINAL_ATTEMPT_CHANGED')
    if terminal.get('registration_id')!=row.get('prepared_registration_id') or not terminal.get('registration_id'):
        raise ValueError('NO_IMAGE_TERMINAL_REGISTRATION_REQUIRED')
    report=copy.deepcopy(terminal)  # Retain rejection_kind and original unknown evidence.
    report.update({k:state[k] for k in ('book_id','episode_id')})
    report.update({k:row[k] for k in ('panel_id','attempt_id','round_id')})
    report['evidence_files']=[terminal_ref, *terminal.get('evidence_files', [])]
    evidence=put(root,path.parent/'no_image_evidence',report)
    proof(state,root,row,evidence,authorization_ref,allow_content=True)
    request={'request_id':hashlib.sha256(json.dumps([row['attempt_id'],terminal_ref,authorization_ref,diagnosis],sort_keys=True).encode()).hexdigest(),
             'panel_id':panel_id,'original_attempt_id':row['attempt_id'],'evidence':evidence,'authorization':authorization_ref}
    if diagnosis is not None:request['diagnosis']=diagnosis
    return request

def proof(state, root, row, evidence_ref, authorization_ref, *, allow_content=False):
    report=read_json(checked_file(root,evidence_ref))
    expected={k:row[k] for k in ('panel_id','attempt_id','round_id')}
    expected.update(book_id=state['book_id'],episode_id=state['episode_id'])
    if any(report.get(k)!=v for k,v in expected.items()):raise ValueError('NO_IMAGE_SCOPE_CHANGED')
    if (report.get('no_image_confirmed') is not True or report.get('outcome') not in OUTCOMES or
        report.get('source_kind') not in {'observed_executor_outcome','observed_tool_error','observed_resolution'} or
        not report.get('source_locator') or not report.get('evidence')):
        raise ValueError('NO_IMAGE_NOT_PROVEN: timeout or missing file alone is insufficient')
    if report.get('rejection_kind')=='content_policy' and not allow_content:raise ValueError('CONTENT_RESTRICTION_REQUIRES_COMPLIANT_INPUT')
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
    if report.get('rejection_kind')=='content_policy' and 'content_failure_delivery' not in auth.get('operations',[]):
        raise ValueError('CONTENT_RESTRICTION_AUTHORIZATION_REQUIRED')
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

NETWORK_POLICY = 'network_four_retries_v1'
NETWORK_MAX_RETRIES = 4


def network_error(root, report):
    """Classify observed error fields only, after separate no-output proof.

    Prompt text, diagnosis prose, timeout and missing files are not evidence of
    a terminal network failure. Reference bytes remain content-bound.
    """
    if report.get('outcome') not in {'FAILED_NO_OUTPUT', 'RESOLVED_NO_OUTPUT'} or report.get('rejection_kind') == 'content_policy':
        return None
    messages = []
    def errors(value):
        if not isinstance(value, dict): return
        error = value.get('error')
        if isinstance(error, dict): error = error.get('message')
        if isinstance(error, str): messages.append(error)
        for key in ('error_message', 'reason'):
            if isinstance(value.get(key), str): messages.append(value[key])
    errors(report)
    for ref in report.get('evidence_files', []):
        path = checked_file(root, ref)
        if path.suffix.lower() != '.json': continue
        value = read_json(path)
        # A different panel's error cannot classify this attempt.
        if isinstance(value, dict) and value.get('attempt_id') == report.get('attempt_id'):
            errors(value)
    # Do not misclassify a content-policy refusal mentioning a network problem.
    if any(any(word in m.lower() for word in ('content policy', 'content_policy', 'safety policy')) for m in messages): return None
    return next((m for m in messages if any(word in m.lower() for word in
                ('network error', 'error sending request', 'econnreset', 'econnrefused', 'enotfound', '网络错误'))), None)


def network_failures(root, row, current_report):
    result = []
    for entry in row.get('no_image_history', []):
        report = read_json(checked_file(root, entry['evidence']))
        message = network_error(root, report)
        if message:
            result.append({'attempt_id': entry['original_attempt']['attempt_id'],
                           'error': message, 'evidence': entry['evidence']})
    message = network_error(root, current_report)
    if message: result.append({'attempt_id': row['attempt_id'], 'error': message})
    return result


def network_exhaustion(state, root, row):
    """Revalidate a narrowly authorized missing-image disposition, never QA PASS."""
    ref = row.get('network_retry_exhausted')
    if not ref: return None
    value = read_json(checked_file(root, ref))
    if (value.get('policy') != NETWORK_POLICY or value.get('attempt_id') != row.get('attempt_id')
            or row.get('status') != 'CALL_FAILED' or row.get('output')):
        raise ValueError('NETWORK_EXHAUSTION_SCOPE_CHANGED')
    problems = history_errors(state, root, row)
    if problems: raise ValueError(';'.join(problems))
    report, auth = proof(state, root, row, value['evidence'], value['authorization'])
    packet = read_json(checked_file(root, row['package_manifest']))
    if packet['panels'][0].get('generation_execution', {}).get('status') == 'COMPLETED':
        raise ValueError('RECOVERY_HAS_ACTUAL_RETURN: save the existing image')
    failures = network_failures(root, row, report)
    if ('network_failure_delivery' not in auth.get('operations', [])
            or len(failures) < NETWORK_MAX_RETRIES + 1 or not network_error(root, report)
            or value.get('failure_count') != len(failures) or value.get('max_retries') != NETWORK_MAX_RETRIES
            or value.get('last_error') != failures[-1]['error']):
        raise ValueError('NETWORK_EXHAUSTION_NOT_PROVEN')
    return value


def network_delivery_refs(root, row):
    value = read_json(checked_file(root, row['network_retry_exhausted']))
    refs = [row['network_retry_exhausted'], value['evidence'], value['authorization']]
    for entry in row.get('no_image_history', []):
        refs += [entry['evidence'], entry['authorization'], entry['original_attempt']['package_manifest']]
    for ref in [value['evidence'], *[e['evidence'] for e in row.get('no_image_history', [])]]:
        refs.extend(read_json(checked_file(root, ref))['evidence_files'])
    return refs


def network_missing_summary(value):
    return (f"工具返回网络错误；累计{value['failure_count']}次确认无图，首次调用后最多重试4次，已停止该格；"
            f"最后错误：{value['last_error']}。服务端根因未证实；保留源格编号，不提供占位图。")


CONTENT_POLICY = 'content_refusal_delivery_v1'

def content_error(root, report):
    """Only a real terminal rejection for this attempt, backed by error bytes."""
    if (report.get('rejection_kind')!='content_policy' or report.get('outcome') not in {'REJECTED_NO_OUTPUT','FAILED_NO_OUTPUT','RESOLVED_NO_OUTPUT'}
            or report.get('source_kind') not in {'observed_tool_error','observed_resolution'}):return None
    messages=[]
    for ref in report.get('evidence_files',[]):
        path=checked_file(root,ref)
        if path.suffix.lower()!='.json':continue
        value=read_json(path)
        if not isinstance(value,dict) or value.get('attempt_id')!=report.get('attempt_id'):continue
        error=value.get('error')
        if isinstance(error,dict):
            messages.extend(str(error[k]) for k in ('message','code','type') if error.get(k))
        elif isinstance(error,str):messages.append(error)
        messages.extend(str(value[k]) for k in ('error_message','reason','code') if value.get(k))
    terms=('content policy','content_policy','content-policy','safety policy','safety_policy','moderation','安全审核','内容审核','内容政策','内容安全')
    return next((m for m in messages if any(term in m.lower() for term in terms)),None)


def content_refusal(state, root, row):
    ref=row.get('content_refusal_delivery')
    if not ref:return None
    value=read_json(checked_file(root,ref))
    if (value.get('policy')!=CONTENT_POLICY or value.get('attempt_id')!=row.get('attempt_id')
            or row.get('status')!='CALL_FAILED' or row.get('output')):raise ValueError('CONTENT_REFUSAL_SCOPE_CHANGED')
    errors=history_errors(state,root,row)
    if errors:raise ValueError(';'.join(errors))
    report,auth=proof(state,root,row,value['evidence'],value['authorization'],allow_content=True)
    packet=read_json(checked_file(root,row['package_manifest']))
    if packet['panels'][0].get('generation_execution',{}).get('status')=='COMPLETED':raise ValueError('RECOVERY_HAS_ACTUAL_RETURN')
    error=content_error(root,report)
    if not error or value.get('last_error')!=error:raise ValueError('CONTENT_REFUSAL_NOT_PROVEN')
    return value


def content_delivery_refs(root,row):
    ref=row['content_refusal_delivery'];value=read_json(checked_file(root,ref))
    report=read_json(checked_file(root,value['evidence']))
    return [ref,value['evidence'],value['authorization'],*report['evidence_files']]


def content_raw_evidence(root,value):
    report=read_json(checked_file(root,value['evidence']))
    return list({(ref['path'],ref['sha256']):ref for ref in report['evidence_files']}.values())


def content_missing_summary(value):
    return '图像服务内容审核拒绝，本格确认无图，未继续重试；原始错误：'+value['last_error']+'。保留源格编号，不提供占位图。'


def recover(state_path, expected_sha256, request):
    """Prepare outside the state lock, then atomically publish against the read set."""
    import time
    from codex_reference_contract import file_session
    start=time.monotonic();lock_wait=lock_hold=0.0
    path=Path(state_path).resolve();root=path.parent.parent
    with file_session() as snapshot:
        result=_recover_prepared(state_path,expected_sha256,request,snapshot)
    if '_recovery_commit' in result:
        from codex_reference_contract import verify_read_snapshot
        from runtime_clock import require_dispatch
        new=result['_recovery_commit'];result=result['_result']
        waiting=time.monotonic()
        with state_write_lock(path):
            acquired=time.monotonic();lock_wait=acquired-waiting
            verify_read_snapshot(snapshot,refresh_views=False)
            if digest(path)!=expected_sha256:raise ValueError('STATE_CHANGED')
            if result['status'] in {'CONTENT_REFUSAL_DELIVERY','NETWORK_RETRY_EXHAUSTED'}:
                from runtime_clock import require_step
                require_step(path,'preserve-delivery')
            else:require_dispatch(path)
            current=next(r for r in read_json(path)['panels'] if r['panel_id']==request['panel_id'])
            capture_key=hashlib.sha256(json.dumps([current['panel_id'],current['attempt_id'],current['round_id']],ensure_ascii=False).encode()).hexdigest()
            if (root/'05_生成原图/实际返回'/capture_key/'raw-return.json').exists():
                raise ValueError('RECOVERY_HAS_CAPTURED_RETURN: reconcile original, never resend')
            history=path.parent/'runtime_history';history.mkdir(exist_ok=True)
            previous_path=history/(expected_sha256+'.json')
            if not previous_path.exists():previous_path.write_bytes(path.read_bytes())
            atomic_json(path,new)
        lock_hold=time.monotonic()-acquired
        result={**result,'state_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    try:
        from runtime_pipeline import record
        record(state_path,'no-image-recovery',{'recovery':time.monotonic()-start,'lock_wait':lock_wait,'lock_hold':lock_hold},panel_ids=[request.get('panel_id')])
    except OSError as exc:result['timing_record_error']=str(exc)
    return result


def _recover_prepared(state_path, expected_sha256, request, snapshot):
    """One CAS transaction, stable request id, new attempt; no extra quality round."""
    from runtime_clock import require_dispatch
    path=Path(state_path).resolve();root=path.parent.parent
    if not isinstance(request,dict) or not isinstance(request.get('request_id'),str) or not request['request_id'].strip():
        raise ValueError('RECOVERY_STABLE_REQUEST_ID_REQUIRED')
    key=hashlib.sha256(request['request_id'].encode()).hexdigest()
    request_digest=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
    def finish(new,result):
        return {'_recovery_commit':new,'_result':result}
    state=read_json(path);require_legacy(state)
    previous=state.get('no_image_recoveries',{}).get(key)
    if previous:
        if previous['request_digest']!=request_digest:raise ValueError('RECOVERY_REQUEST_CONFLICT')
        return {**previous['result'],'status':previous['result']['status'] if previous['result']['status'] in {'NETWORK_RETRY_EXHAUSTED','CONTENT_REFUSAL_DELIVERY'} else 'NO_IMAGE_RECOVERY_ALREADY_SAVED','image_calls':0,'invoke_allowed':False}
    if digest(path)!=expected_sha256:raise ValueError('STATE_CHANGED')
    from runtime_clock import require_step
    require_step(path,'preserve-delivery')
    if state.get('execution_mode')!='episode_async_v1':raise ValueError('NO_IMAGE_RECOVERY_REQUIRES_EPISODE_MODE')
    row=next(r for r in state['panels'] if r['panel_id']==request['panel_id'])
    if row.get('attempt_id')!=request.get('original_attempt_id'):raise ValueError('RECOVERY_OLD_ATTEMPT_CHANGED')
    if row.get('status') not in {'IN_FLIGHT','CALL_FAILED','RESULT_UNKNOWN','CANCELLED'} or row.get('output'):
        raise ValueError('RECOVERY_ONLY_CONFIRMED_NO_IMAGE')
    capture_key=hashlib.sha256(json.dumps([row['panel_id'],row['attempt_id'],row['round_id']],ensure_ascii=False).encode()).hexdigest()
    if (root/'05_生成原图/实际返回'/capture_key/'raw-return.json').exists():
        raise ValueError('RECOVERY_HAS_CAPTURED_RETURN: reconcile original, never resend')
    errors=history_errors(state,root,row)
    if errors:raise ValueError(';'.join(errors))
    report,auth=proof(state,root,row,request['evidence'],request['authorization'],allow_content=True)
    if row['status']=='IN_FLIGHT' and report['outcome']!='NOT_INVOKED':
        raise ValueError('SAVE_ACTUAL_FAILURE_OR_RESOLVE_UNKNOWN_FIRST')
    packet_path=checked_file(root,row['package_manifest']);packet=read_json(packet_path)
    if packet['panels'][0].get('generation_execution',{}).get('status')=='COMPLETED':
        raise ValueError('RECOVERY_HAS_ACTUAL_RETURN: save the existing image')
    if report.get('rejection_kind')=='content_policy':
        error=content_error(root,report)
        if not error or row['status']!='CALL_FAILED':raise ValueError('CONTENT_REFUSAL_NOT_PROVEN')
        if row.get('content_refusal_delivery'):
            content_refusal(state,root,row)
            return {'status':'CONTENT_REFUSAL_DELIVERY','panel_id':row['panel_id'],'image_calls':0,'invoke_allowed':False,
                    'next_action':'CONTINUE_OTHER_PANELS_THEN_REPORT_CONTENT_REFUSAL'}
        value={'policy':CONTENT_POLICY,'attempt_id':row['attempt_id'],'last_error':error,
               'evidence':request['evidence'],'authorization':request['authorization']}
        new=copy.deepcopy(state);target=next(r for r in new['panels'] if r['panel_id']==row['panel_id'])
        target['content_refusal_delivery']=put(root,path.parent/'no_image_recovery'/key,value)
        from slot_leases import close_no_image
        close_no_image(new,row,request['evidence'])
        confirmed=content_refusal(new,root,target)
        from lean_delivery import gap
        gap(new,target,'CONTENT_REFUSED',content_missing_summary(confirmed))
        result={'status':'CONTENT_REFUSAL_DELIVERY','panel_id':row['panel_id'],'image_calls':0,'invoke_allowed':False,
                'next_action':'CONTINUE_OTHER_PANELS_THEN_REPORT_CONTENT_REFUSAL'}
        new.setdefault('no_image_recoveries',{})[key]={'request_digest':request_digest,'result':result}
        return finish(new,result)
    # Fixed per-panel budget across input versions and invocation contexts.
    network = network_error(root, report)
    failures = network_failures(root, row, report)
    if len(failures) >= NETWORK_MAX_RETRIES + 1:
        if not network or row['status'] != 'CALL_FAILED':
            return {'status':'NETWORK_RETRY_LIMIT_REACHED','image_calls':0,'invoke_allowed':False,
                    'next_action':'RECONCILE_CURRENT_ATTEMPT_NO_NEW_CALL'}
        if 'network_failure_delivery' not in auth.get('operations', []):
            return {'status':'NETWORK_RETRY_LIMIT_REACHED','image_calls':0,'invoke_allowed':False,
                    'next_action':'RECORD_EXISTING_SCOPED_MISSING_DELIVERY_AUTHORITY'}
        if row.get('network_retry_exhausted'):
            value = network_exhaustion(state, root, row)
            return {'status':'NETWORK_RETRY_EXHAUSTED','panel_id':row['panel_id'],
                    'failure_count':value['failure_count'],'image_calls':0,'invoke_allowed':False,
                    'next_action':'CONTINUE_OTHER_PANELS_THEN_DELIVER_WITH_NETWORK_GAP'}
        value = {'policy':NETWORK_POLICY,'attempt_id':row['attempt_id'],
                 'max_retries':NETWORK_MAX_RETRIES,'failure_count':len(failures),
                 'last_error':network,'evidence':request['evidence'],'authorization':request['authorization']}
        new=copy.deepcopy(state);target=next(r for r in new['panels'] if r['panel_id']==row['panel_id'])
        target['network_retry_exhausted']=put(root,path.parent/'no_image_recovery'/key,value)
        from slot_leases import close_no_image
        close_no_image(new,row,request['evidence'])
        confirmed=network_exhaustion(new,root,target)
        from lean_delivery import gap
        gap(new,target,'NETWORK_FAILED',network_missing_summary(confirmed))
        result={'status':'NETWORK_RETRY_EXHAUSTED','panel_id':row['panel_id'],
                'failure_count':len(failures),'max_retries':NETWORK_MAX_RETRIES,
                'next_action':'CONTINUE_OTHER_PANELS_THEN_DELIVER_WITH_NETWORK_GAP',
                'image_calls':0,'invoke_allowed':False}
        new.setdefault('no_image_recoveries',{})[key]={'request_digest':request_digest,'result':result}
        return finish(new,result)
    # Two consecutive retries of identical inputs require a substantive, evidenced diagnosis.
    if not network and len(row.get('no_image_history',[]))>=2:
        diagnosis=request.get('diagnosis')
        if not isinstance(diagnosis,dict) or not diagnosis.get('cause') or not diagnosis.get('remediation'):
            return {'status':'NO_IMAGE_DIAGNOSIS_REQUIRED','panel_id':row['panel_id'],'image_calls':0,'invoke_allowed':False,
                    'next_action':'DIAGNOSE_CAUSE_AND_CONTINUE_OTHER_READY_PANELS'}
        checked_file(root,diagnosis['evidence'])
        if any(e.get('diagnosis')==diagnosis for e in row['no_image_history']):raise ValueError('REPEATED_RECOVERY_METHOD: use a different evidenced remedy')
    from production_runtime import package_signature
    require_dispatch(path)
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
            'next_action':'PREPARE_AFFECTED_PANEL_THEN_CLAIM_AND_REGISTER','image_calls':0,'invoke_allowed':False}
    new.setdefault('no_image_recoveries',{})[key]={'request_digest':request_digest,'result':result}
    return finish(new,result)
