#!/usr/bin/env python3
"""Content-bound QA memo within one gate run; reuse proposals never grant user approval."""
import argparse
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
from codex_reference_contract import read_json, checked_file, digest

_SESSION=ContextVar('comic_qa_memo',default=None)


def fingerprint(root, record):
    root=Path(root).resolve(); files={}; seen=set()
    def walk(value, base):
        if isinstance(value,dict):
            if value.get('frame_ratio_policy')=='content_balanced_ratios_v1':
                for key in ('frame_ratio_plan','source_snapshot'):
                    if value.get(key):walk(value[key],root)
                value={k:v for k,v in value.items() if k not in {'frame_ratio_plan','source_snapshot'}}
            if value.get('derivation_policy')=='faithful_atlas_v1':
                for region in value.get('source_regions',[]):
                    source=region.get('source_file')
                    if isinstance(source,str):walk({'path':source,'sha256':region.get('source_sha256')},base)
            if 'identity_registry' in value:
                walk(value['identity_registry'],root)
                value={k:v for k,v in value.items() if k!='identity_registry'}
            if value.get('policy')=='visual_evidence_v1' and 'continuity_comparisons' in value:
                walk(value['continuity_comparisons'],root)
                value={k:v for k,v in value.items() if k!='continuity_comparisons'}
            if value.get('policy')=='approved_shot_context_v1':
                for source in value.get('sources',[]):walk(source,Path(source['root']))
                return
            if value.get('policy')=='scoped_rule_exception_v1':
                walk(value.get('artifacts',[]),Path(value['evidence_root']))
                return
            if isinstance(value.get('path'),str) and isinstance(value.get('sha256'),str):
                file=checked_file(base,value); collect(file,base)
            else:
                for v in value.values():walk(v,base)
        elif isinstance(value,list):
            for v in value:walk(v,base)
    def collect(file,base,recursive=True):
        file=Path(file).resolve(); token=(str(file),str(base))
        if token in seen:return
        seen.add(token); files[str(file)]=digest(file)
        if recursive and file.suffix.lower()=='.json':walk(json.loads(file.read_text(encoding='utf-8-sig')),base)
    manifest=checked_file(root,record['package_manifest']); collect(manifest,manifest.parent)
    qa=checked_file(root,record['qa_report']);collect(qa,manifest.parent)
    collect(checked_file(root,record['output']),root)
    # This snapshot may mirror package-relative panel references while living
    # at the episode root. Its bytes bind the snapshot; validate_panel reads
    # the real package's references, already walked from the package root.
    if record.get('shot_subset'):collect(checked_file(root,record['shot_subset']),root,False)
    data=json.loads(manifest.read_text(encoding='utf-8-sig')); panel=data['panels'][0]; rules=[]
    # validate_panel also reads this unhashed string path. It must invalidate a
    # memo just like a hashed image/reference/receipt does.
    prompt_name=Path(str(panel.get('prompt_file',f"{panel.get('panel_id')}/prompt.txt")))
    prompt=(manifest.parent/prompt_name).resolve()
    if prompt_name.is_absolute() or not prompt.is_relative_to(manifest.parent):
        raise ValueError('prompt_file越出执行包')
    collect(prompt,manifest.parent)
    if data.get('memory_source'):
        from rule_memory import select, source_index
        tags=[]
        if data.get('execution_contract')=='comic_execution_v2':
            from continuity_context import rule_tags
            tags=rule_tags(data,manifest.parent,panel)
        library,_=source_index(data['memory_source'])
        for stage in ('generation','image_review'):
            for match in select(data['memory_source'],stage,panel,tags):
                rule=match['rule'];collect(checked_file(library,rule['file']),library)
                rules.append((stage,rule['id'],match['rule_signature']))
    value={'policy':'qa_content_bound_v2','root':str(root),'panel_id':record['panel_id'],
           'files':sorted(files.items()),'rules':rules}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


@contextmanager
def session(enabled):
    from rule_memory import routing_session
    if not enabled or _SESSION.get() is not None:
        with routing_session(enabled):yield _SESSION.get()
        return
    data={'passed':set(),'hits':0,'misses':0};token=_SESSION.set(data)
    try:
        with routing_session(True):yield data
    finally:_SESSION.reset(token)


def cached_qa(root,record,compute):
    data=_SESSION.get()
    if data is None:return compute()
    try:key=fingerprint(root,record)
    except (OSError,ValueError,TypeError,KeyError,AttributeError):return compute()
    if key in data['passed']:
        data['hits']+=1;return []
    data['misses']+=1;errors=compute()
    if not errors:data['passed'].add(key)
    return errors


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',required=True);p.add_argument('--panel',required=True);p.add_argument('--write',required=True)
    a=p.parse_args()
    try:
        path=Path(a.state).resolve();root=path.parent.parent;state=json.loads(path.read_text());record=next(r for r in state['panels'] if r['panel_id']==a.panel)
        from staged_workflow import qa_errors
        errors=qa_errors(root,record)
        if errors:raise ValueError(';'.join(errors))
        value={'policy':'qa_reuse_candidate_v1','panel_id':a.panel,'fingerprint':fingerprint(root,record),
               'output':record['output'],'qa_report':record['qa_report'],'package_manifest':record['package_manifest'],
               'status':'REUSE_RECORDED_VISUAL_QA','user_approval':'NOT_GRANTED','scope':'Original QA only; current scope/basis/dispatch gates still required'}
        dest=Path(a.write).resolve();dest.relative_to(root)
        with dest.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')
        print(json.dumps(value,ensure_ascii=False));return 0
    except (OSError,ValueError,TypeError,KeyError,StopIteration) as exc:
        print(json.dumps({'status':'HOLD','errors':[str(exc)]},ensure_ascii=False));return 1

if __name__=='__main__':raise SystemExit(main())
