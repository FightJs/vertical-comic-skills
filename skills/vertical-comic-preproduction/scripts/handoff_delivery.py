"""Direct-delivery closure and deterministic runtime-only relocation.

No approval synthesis, creative JSON rewriting, budget changes or image calls.
"""
from pathlib import Path
import json,shutil

DIRECT='direct_delivery_v2'
TEMPLATE='portable_run_template_v1'


def closure(root,index):
    from handoff_zip import reference
    errors=[];known={(e['episode_id'],p) for e in index['episodes'] for p in e['panel_ids']}
    for e in index['episodes']:
        eid=e['episode_id']
        if not e.get('run_template'):errors.append(eid+':缺可自动绑定的运行模板')
        else:reference(root,e['run_template'])
        for p in e['panels']:
            pid=p['panel_id'];kind=p['classification'];history=p['history']
            if kind=='HOLD' or history['status']=='UNRESOLVED' or any(a['status']=='UNKNOWN' for a in history['attempts']):
                errors.append(eid+'/'+pid+':前期/历史HOLD未关闭，不能交正式包');continue
            if kind=='WAIT_DEPENDENCY':
                dep=p.get('production_dependency',{})
                source=(dep.get('episode_id'),dep.get('panel_id'))
                if dep.get('kind') not in {'prior_image','state_image_review'} or source not in known or source==(eid,pid):
                    errors.append(eid+'/'+pid+':只能保留包内真实前置实图/状态确认依赖')
                else:
                    ordered=[(x['episode_id'],y) for x in index['episodes'] for y in x['panel_ids']]
                    if ordered.index(source)>=ordered.index((eid,pid)):errors.append(eid+'/'+pid+':前置依赖倒序或循环')
                reference(root,dep.get('completion_plan'))
            if kind=='REUSE':
                review=reference(root,p.get('current_design_review'));data=json.loads(review.read_text())
                if (data.get('status')!='PASS' or not data.get('reviewer') or not data.get('evidence') or
                    data.get('panel_id')!=pid or data.get('episode_id')!=eid or
                    data.get('accepted_image')!=p['accepted_image'] or data.get('accepted_qa')!=p['accepted_qa'] or
                    data.get('visual_basis')!=e.get('visual_basis') or data.get('shot_manifest')!=e.get('shot_manifest')):
                    errors.append(eid+'/'+pid+':旧图尚未对本次A/B实际复核')
                reference(root,e.get('visual_basis'));reference(root,e.get('shot_manifest'))
        first=[p for p in e['panels'] if p['panel_id'] in e['halves']['H001']]
        if not any(p['classification']=='READY_H001' for p in first) and not all(p['classification']=='REUSE' for p in e['panels']):
            errors.append(eid+':本话没有可启动格，不能让其他话代替本话通过')
    return errors


def bind(package_root,run_root):
    from handoff_zip import audit_index,reference,inside,files,sha,write
    from runtime_snapshot import verify
    from execution_contract import toolchain
    package_root=Path(package_root).resolve();run_root=Path(run_root).resolve()
    if run_root.exists() or run_root.is_relative_to(package_root) or package_root.is_relative_to(run_root):raise ValueError('本地运行须为包外全新目录')
    index=audit_index(package_root);plans=[]
    # Validate every source before creating the destination.
    for e in index['episodes']:
        plan=json.loads(reference(package_root,e.get('run_template')).read_text())
        if plan.get('policy')!=TEMPLATE or plan.get('episode_id')!=e['episode_id']:raise ValueError('运行模板归属错误')
        source=inside(package_root,plan['root']);rows=plan.get('files')
        if not isinstance(rows,list) or sorted(rows,key=lambda x:x['path'])!=files(source):raise ValueError('运行模板文件清单不完整或字节变化')
        for ref in rows:reference(source,ref)
        state_path=inside(source,plan['state_file'])
        if state_path.parent.parent!=source:raise ValueError('模板状态须位于本话根/审计目录/状态文件')
        state=json.loads(state_path.read_text())
        if state.get('book_id')!=index['book_id'] or state.get('episode_id')!=e['episode_id']:raise ValueError('运行模板书话不符')
        snap=reference(package_root,e['runtime_manifest']);snap_ref={'path':str(snap),'sha256':sha(snap)}
        frozen=verify(snap_ref);new_toolchain=toolchain(frozen['scripts']);old=state.get('toolchain',{})
        # Only roots change; checker and Skill bytes must be the already-frozen ones.
        if (old.get('policy')!=new_toolchain['policy'] or old.get('release')!=new_toolchain['release'] or
            old.get('files')!=new_toolchain['files'] or
            {Path(x['path']).parent.name:x['sha256'] for x in old.get('skill_entries',[])}!=
            {Path(x['path']).parent.name:x['sha256'] for x in new_toolchain['skill_entries']}):
            raise ValueError('模板与冻结工具字节不符，须在前期冻结前修正')
        old_memory={k:v for k,v in (state.get('memory_source') or {}).items() if k not in {'root','runtime_snapshot'}}
        new_memory={k:v for k,v in (frozen['memory_source'] or {}).items() if k not in {'root','runtime_snapshot'}}
        if old_memory!=new_memory:raise ValueError('模板规则版本或索引变化，不能当作路径绑定')
        state={**state,'runtime_snapshot':snap_ref,'toolchain':new_toolchain}
        if frozen['memory_source'] is not None or 'memory_source' in state:state['memory_source']=frozen['memory_source']
        plans.append((e,plan,source,state,sha(state_path)))
    run_root.mkdir(parents=True);runs=[]
    try:
        for e,plan,source,state,old_sha in plans:
            episode_root=inside(run_root,e['episode_id']);shutil.copytree(source,episode_root)
            state_file=inside(episode_root,plan['state_file']);state_file.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
            evidence={'policy':'runtime_only_relocation_v1','package_id':index['package_id'],'episode_id':e['episode_id'],
                      'template_state_sha256':old_sha,'local_state_sha256':sha(state_file),'changed_fields':['runtime_snapshot','toolchain','memory_source'],
                      'creative_files_unchanged':True,'approval_rewritten':False,'budget_reset':False}
            proof=episode_root/'接包路径绑定.json';write(proof,evidence)
            runs.append({'episode_id':e['episode_id'],'state':state_file.relative_to(run_root).as_posix(),
                         'binding_evidence':{'path':proof.relative_to(run_root).as_posix(),'sha256':sha(proof)}})
        dest=run_root/'本地绑定索引.json';write(dest,{'package_id':index['package_id'],'episodes':runs})
    except Exception:
        shutil.rmtree(run_root);raise
    return {'status':'LOCAL_RUN_BOUND_NOT_IMAGE_AUTHORIZATION','run_root':str(run_root),'run_index':str(dest),'image_calls':0}


def input_review(root,index):
    """Digest the final creative/executable inputs, excluding later human receipts."""
    from handoff_zip import reference
    import hashlib
    episodes=[]
    for e in index['episodes']:
        selected={k:e[k] for k in ('episode_id','panel_ids','halves')}
        selected['production_scope']=e['panels']
        for k in ('source_script','production_source_snapshot','visual_basis','shot_manifest','runtime_manifest'):
            reference(root,e.get(k));selected[k]=e[k]
        packages=e.get('generation_review_packages')
        if not isinstance(packages,list) or not packages:raise ValueError('缺最终实际生图包审查输入')
        for ref in packages:reference(root,ref)
        selected['generation_review_packages']=packages;episodes.append(selected)
    value={'policy':'approved_inputs_auto_export_v1','package_id':index['package_id'],'book_id':index['book_id'],'episodes':episodes}
    return {**value,'approved_input_digest':hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
