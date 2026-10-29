"""Import production data into a pinned executor. Never execute source-package code."""
from pathlib import Path
import copy, hashlib, json, os
from platform_io import atomic_json, file_lock

POLICY='unified_runtime_import_v1'
FIELD='runtime_import'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def ref(path,root=None):return {'path':Path(path).resolve().relative_to(Path(root).resolve()).as_posix() if root else str(Path(path).resolve()),'sha256':sha(path)}

def inspect_source(state_path):
    path=Path(state_path).resolve();state=read(path)
    if state.get(FIELD):return {'status':'ALREADY_IMPORTED','state':str(path),'image_calls':0}
    if state.get('execution_mode')!='episode_async_v1' or state.get('preparation_policy')!='episode_preparation_v1':
        raise ValueError('IMPORT_SCOPE_UNSUPPORTED: legacy half/batch data requires a complete approved episode input map')
    if state.get('dispatch_consistency'):
        raise ValueError('IMPORT_OWNER_REQUIRED: reconcile the existing managed owner before import')
    if state.get('cancelled'):raise ValueError('IMPORT_CANCELLED')
    rows=state.get('panels',[])
    if not rows or len({r['panel_id'] for r in rows})!=len(rows):raise ValueError('IMPORT_SOURCE_ORDER_INVALID')
    inflight=[r['panel_id'] for r in rows if r.get('status')=='IN_FLIGHT']
    if any(type(r.get('round_id',1)) is not int or r.get('round_id',1)>2 for r in rows):
        raise ValueError('IMPORT_HISTORY_SCOPE_UNSUPPORTED: preserve multi-round user-directed history; explicit source mapping required')
    if inflight:raise ValueError('IMPORT_INFLIGHT_RECONCILIATION_REQUIRED:'+','.join(inflight))
    from runtime_snapshot import verify
    if state.get('runtime_snapshot'):verify(state['runtime_snapshot'])
    from codex_reference_contract import checked_file
    root=path.parent.parent
    source=read(checked_file(root,state['source_snapshot']))
    if [r['panel_id'] for r in rows]!=source.get('panel_ids'):raise ValueError('IMPORT_SOURCE_ORDER_CHANGED')
    for key in ('source_script','visual_basis','shot_manifest'):checked_file(root,state[key])
    return {'status':'IMPORTABLE','state':str(path),'state_sha256':sha(path),
            'panel_ids':source['panel_ids'],'image_calls':0}

def plan_import(state_path, executor_manifest):
    source=inspect_source(state_path)
    if source['status']=='ALREADY_IMPORTED':return source
    from runtime_snapshot import verify
    executor=verify(executor_manifest)
    caps=read(Path(executor['scripts'])/'runtime_capabilities.json')
    if caps.get('runtime_import')!=POLICY:raise ValueError('IMPORT_EXECUTOR_UNSUPPORTED')
    return {**source,'policy':POLICY,'executor_manifest':executor_manifest,
            'review_profile':'light_story_review_v1','preserve_history':True}

def apply_import(state_path, plan):
    path=Path(state_path).resolve();root=path.parent.parent
    if plan.get('status')=='ALREADY_IMPORTED':
        verify_binding(read(path),root);return plan
    if plan.get('policy')!=POLICY or plan.get('state')!=str(path):raise ValueError('IMPORT_PLAN_SCOPE')
    from authority_updates import state_write_lock
    from execution_contract import toolchain
    from runtime_snapshot import verify
    executor=verify(plan['executor_manifest']);new_tools=toolchain(executor['scripts'])
    # All expensive validation precedes the state write lock. CAS decides the
    # winner; stale plans never replace a peer's new output or approval.
    source=inspect_source(path)
    if source['state_sha256']!=plan['state_sha256']:raise ValueError('IMPORT_SOURCE_CHANGED')
    old=read(path);new=copy.deepcopy(old)
    new.update(image_review_profile='light_story_review_v1',repair_threshold_policy='essential_story_only_v1',
               runtime_pipeline_policy='observed_incremental_pipeline_v1',source_input_policy='formal_source_inputs_v1',
               toolchain=new_tools)
    if old.get('runtime_execution_context'):
        from runtime_clock import execution_context
        context=execution_context(path,state=old)
        if context and context.get('clock_required'):new['speed_policy']='bounded_stage_fallback_v1'
    folder=path.parent/'runtime_import'/plan['state_sha256'];folder.mkdir(parents=True,exist_ok=True)
    original=folder/'original-state.json'
    original_bytes=path.read_bytes()
    if hashlib.sha256(original_bytes).hexdigest()!=plan['state_sha256']:raise ValueError('IMPORT_SOURCE_CHANGED')
    if original.exists() and original.read_bytes()!=original_bytes:raise ValueError('IMPORT_HISTORY_CONFLICT')
    if not original.exists():
        with original.open('xb') as f:f.write(original_bytes)
    manifest=folder/'import.json'
    evidence={'policy':POLICY,'book_id':old['book_id'],'episode_id':old['episode_id'],
              'source_state':ref(original,root),'source_runtime_snapshot':old.get('runtime_snapshot'),
              'executor_manifest':plan['executor_manifest'],'executor_toolchain':new_tools,
              'source_panel_ids':[r['panel_id'] for r in old['panels']],
              'clock_reference':old.get('runtime_execution_context'),'history_reset':False,
              'approval_rewritten':False,'review_profile':'light_story_review_v1'}
    if manifest.exists() and read(manifest)!=evidence:raise ValueError('IMPORT_RECEIPT_CONFLICT')
    if not manifest.exists():atomic_json(manifest,evidence)
    new[FIELD]=ref(manifest,root)
    with state_write_lock(path):
        if sha(path)!=plan['state_sha256']:raise ValueError('IMPORT_SOURCE_CHANGED')
        atomic_json(path,new)
    return {'status':'IMPORTED','state':str(path),'state_sha256':sha(path),'import':new[FIELD],
            'image_calls':0,'dispatch_authorized':False,'history_reset':False}

def verify_binding(state,root):
    from codex_reference_contract import checked_file,read_json
    evidence=read_json(checked_file(root,state[FIELD]))
    if (evidence.get('policy')!=POLICY or evidence['book_id']!=state['book_id'] or
        evidence['episode_id']!=state['episode_id'] or evidence['executor_toolchain']!=state.get('toolchain') or
        evidence['source_runtime_snapshot']!=state.get('runtime_snapshot') or
        evidence['clock_reference']!=state.get('runtime_execution_context') or
        evidence['source_panel_ids']!=[r['panel_id'] for r in state['panels']]):raise ValueError('IMPORT_BINDING_CHANGED')
    original=read_json(checked_file(root,evidence['source_state']))
    return evidence,original

def historical_record(state,root,record):
    """Accept only the exact original review identity, never newly supplied full QA."""
    if not state.get(FIELD):return None
    _,old=verify_binding(state,root)
    for row in old['panels']:
        if row['panel_id']!=record['panel_id']:continue
        for prior in [row,*row.get('attempt_history',[])]:
            if all(prior.get(k)==record.get(k) for k in ('attempt_id','round_id','qa_report','output','package_manifest')):
                if prior.get('qa_report') and prior.get('output'):return old
    return None

def resume_import(state_path,executor_manifest):
    return apply_import(state_path,plan_import(state_path,executor_manifest))
