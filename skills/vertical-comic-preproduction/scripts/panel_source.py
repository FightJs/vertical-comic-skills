#!/usr/bin/env python3
"""Episode-authoring source. No production state, approval or ledger writes."""
import argparse
import copy
import json
from pathlib import Path
from input_dependencies import fingerprint, file_hash
from platform_io import configure_stdio

POLICY='panel_authoring_source_v1'

def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write_new(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')

def shared_ref(library,value):
    key=fingerprint(value);library.setdefault(key,copy.deepcopy(value));return key

def expand(value, library):
    if isinstance(value,dict):
        if set(value)=={'$shared'}: return copy.deepcopy(library[value['$shared']])
        return {k:expand(v,library) for k,v in value.items()}
    if isinstance(value,list): return [expand(v,library) for v in value]
    return copy.deepcopy(value)

def normalize_refs(value, root, fallback=None):
    """Resolve portable draft sources; distribution later uses the existing binder."""
    from codex_reference_contract import digest as cached_digest
    if isinstance(value,dict):
        result={k:normalize_refs(v,root,fallback) for k,v in value.items()}
        if isinstance(value.get('path'),str) and 'sha256' in value:
            raw=Path(value['path'])
            candidates=[raw] if raw.is_absolute() else [Path(root)/raw,Path(fallback)/raw] if fallback else [Path(root)/raw]
            matched=[p for p in candidates if p.is_file() and cached_digest(p)==value.get('sha256')]
            if matched: result['path']=str(matched[0].absolute())
            elif any(p.exists() for p in candidates): raise ValueError('草稿引用哈希不一致:'+value['path'])
            else: result['path']=str(candidates[0].absolute())  # Absence is a tracked dependency.
        return result
    if isinstance(value,list): return [normalize_refs(v,root,fallback) for v in value]
    return copy.deepcopy(value)

def validate(value):
    if value.get('policy')!=POLICY or value.get('status')!='WORKING_DRAFT': raise ValueError('须为主表工作草稿')
    order=value['panel_ids']; rows=value['panels']
    if not order or len(set(order))!=len(order) or [p['panel_id'] for p in rows]!=order: raise ValueError('主表缺格/乱序/重复')
    if not value.get('book_id') or not value.get('episode_id'): raise ValueError('主表缺书话')
    library=value['shared']; header=expand(value['shot_header'],library)
    if any(header.get(k)!=value[k] for k in ('book_id','episode_id')): raise ValueError('主表与镜头书话失配')
    for row in rows:
        shot=expand(row['shot'],library); execution=expand(row['execution'],library)
        if shot.get('panel_id')!=row['panel_id']: raise ValueError('主表镜头ID失配')
        if set(execution)&set(shot): raise ValueError('同一创作字段只能维护一次:'+row['panel_id'])
        if row.get('render_mode') not in {'preserved_import','structured_v2'}: raise ValueError('未知派生方式')
        packet_header=expand(row['packet_header'],library)
        if any(packet_header.get(k)!=value[k] for k in ('book_id','episode_id')): raise ValueError('生图包书话不符')
    return value

def import_state(state_path):
    from codex_reference_contract import file_session,checked_file,read_json
    from batch_workflow import SHOT_FIELDS
    path=Path(state_path).resolve();root=path.parent.parent
    with file_session():
        state=read_json(path);source=read_json(checked_file(root,state['source_snapshot']))
        shots=read_json(checked_file(root,state['shot_manifest']))
        order=source['panel_ids'];records={p['panel_id']:p for p in state['panels']}
        if [p['panel_id'] for p in shots['panels']]!=order: raise ValueError('镜头不符合原始源格序')
        shared={};rows=[]
        header=normalize_refs({k:v for k,v in shots.items() if k!='panels'},root)
        for shot in shots['panels']:
            pid=shot['panel_id'];manifest=checked_file(root,records[pid]['package_manifest']);packet=read_json(manifest)
            if len(packet.get('panels',[]))!=1: raise ValueError('导入只接受逐格包')
            panel=packet['panels'][0]
            if panel.get('panel_id')!=pid or shot.get('locked_script')!=source['locked_scripts'][pid]: raise ValueError('源稿/包格号失配')
            if any(panel.get(k)!=shot.get(k) for k in SHOT_FIELDS): raise ValueError('先消解镜头与包的创作差异:'+pid)
            if records[pid].get('status') in {'IN_FLIGHT','RESULT_UNKNOWN'} or records[pid].get('output'): raise ValueError('不导入在途/未知请求为新工作输入')
            canonical=normalize_refs(shot,root)
            execution={k:v for k,v in panel.items() if k not in shot}
            # Differing duplicated creative fields must be resolved, never silently picked.
            if any(panel[k]!=shot[k] for k in set(panel)&set(shot) if k not in {'status','planning_notes'}):
                raise ValueError('重复创作字段有冲突:'+pid)
            for field in ('generation_execution','generation_execution_history','output','qa_report','request_evidence','call_evidence'):
                execution.pop(field,None)
            execution=normalize_refs(execution,manifest.parent,root)
            rows.append({'panel_id':pid,'shot':canonical,'execution':execution,
                         'packet_header':{'$shared':shared_ref(shared,normalize_refs({k:v for k,v in packet.items() if k!='panels'},manifest.parent,root))},
                         'render_mode':'preserved_import','import_creative_key':fingerprint(canonical),
                         'dependencies':[],'dependency_queries':[]})
        value={'policy':POLICY,'status':'WORKING_DRAFT','book_id':state['book_id'],'episode_id':state['episode_id'],
               'run_root':str(root),'source_snapshot':normalize_refs(state['source_snapshot'],root),
               'panel_ids':order,'shared':shared,'shot_header':header,'panels':rows,
               'dispatch_authorized':False,'user_approval':'NOT_GRANTED'}
        # Intern repeated structured rule/identity/appearance contexts once.
        fields={'identity_registry','visual_evidence_context','memory_applications','style_contract'}
        for row in rows:
            for section in ('shot','execution'):
                for field in fields & set(row[section]):
                    row[section][field]={'$shared':shared_ref(shared,row[section][field])}
        for row in rows:
            row['import_panel_key']=fingerprint({**expand(row['shot'],shared),**expand(row['execution'],shared)})
        return validate(value)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    try:
        value=import_state(a.state);write_new(a.output,value)
        print(json.dumps({'status':'WORKING_SOURCE_SAVED','path':str(Path(a.output).resolve()),'panel_count':len(value['panels']),'dispatch_authorized':False},ensure_ascii=False));return 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'SOURCE_HOLD','error':str(exc)},ensure_ascii=False));return 1
if __name__=='__main__': configure_stdio();raise SystemExit(main())
