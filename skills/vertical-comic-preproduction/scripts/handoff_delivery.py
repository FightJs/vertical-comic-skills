"""Direct-delivery closure and deterministic runtime-only relocation.

No approval synthesis, creative JSON rewriting, budget changes or image calls.
"""
from pathlib import Path
from platform_io import skill_entry_key
import json,shutil
from handoff_scope import episode_mode, ready_ids

DIRECT='direct_delivery_v2'
TEMPLATE='portable_run_template_v1'


def closure(root,index,*,verify_runtime=True):
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
                review=reference(root,p.get('current_design_review'));data=json.loads(review.read_text(encoding='utf-8-sig'))
                if (data.get('status')!='PASS' or not data.get('reviewer') or not data.get('evidence') or
                    data.get('panel_id')!=pid or data.get('episode_id')!=eid or
                    data.get('accepted_image')!=p['accepted_image'] or data.get('accepted_qa')!=p['accepted_qa'] or
                    data.get('visual_basis')!=e.get('visual_basis') or data.get('shot_manifest')!=e.get('shot_manifest')):
                    errors.append(eid+'/'+pid+':旧图尚未对本次A/B实际复核')
                reference(root,e.get('visual_basis'));reference(root,e.get('shot_manifest'))
        if e.get('input_semantics_policy'):
            plan=json.loads(reference(root,e['run_template']).read_text(encoding='utf-8-sig'))
            from input_semantics import POLICIES, coverage, review_checks
            if e['input_semantics_policy'] not in POLICIES:errors.append(eid+':未知最终输入审查策略')
            audit=reference(root,e.get('semantic_audit'))
            audit_data=json.loads(audit.read_text(encoding='utf-8-sig'))
            if (audit_data.get('episode_id')!=eid or audit_data.get('book_id')!=index['book_id']
                    or audit_data.get('panel_ids')!=e['panel_ids']
                    or [r.get('panel_id') for r in audit_data.get('panels',[])]!=e['panel_ids']):
                errors.append(eid+':最终输入审查范围不完整')
            for row in audit_data.get('panels',[]):
                review=row.get('execution_review',{})
                if (review.get('policy')!=e['input_semantics_policy'] or review.get('status')!='REVIEWED'
                        or not review.get('input_digest') or not review.get('reviewer') or not review.get('evidence')
                        or review.get('unresolved_issues') or any(review.get('checks',{}).get(k,{}).get('status')!='PASS'
                        or not review.get('checks',{}).get(k,{}).get('evidence') for k in review_checks(e['input_semantics_policy']))):
                    errors.append(eid+'/'+row['panel_id']+':最终输入语义审查未闭合')
            if verify_runtime:
                from handoff_zip import inside
                template_root=inside(root,plan['root'])
                state=json.loads(inside(template_root,plan['state_file']).read_text(encoding='utf-8-sig'))
                checked=coverage(state,template_root)
                if checked['status']!='PREPRODUCTION_INPUTS_REVIEWED':
                    errors.append(eid+':最终输入语义审查未闭合:'+json.dumps(checked['errors'],ensure_ascii=False))
                if e.get('input_semantics_policy')!=state['input_semantics_policy']:
                    errors.append(eid+':交接索引缺最终输入审查策略')
                from codex_reference_contract import checked_file, digest
                if digest(audit)!=digest(checked_file(template_root,state['semantic_audit'])):
                    errors.append(eid+':交接审查与运行模板不一致')
        if not ready_ids(index,e) and not all(p['classification']=='REUSE' for p in e['panels']):
            errors.append(eid+':本话没有可启动格，不能让其他话代替本话通过')
    return errors


def formal_context_errors(root,index):
    """Pre-compression reference closure, not another compile or approval format."""
    from handoff_zip import inside,reference
    from codex_reference_contract import file_session,checked_file,read_json
    from continuity_context import load_context
    from panel_readiness import review_context
    errors=[]
    with file_session():
        for episode in index['episodes']:
            plan=read_json(reference(root,episode['run_template']))
            base=inside(root,plan['root'])
            state=read_json(inside(base,plan['state_file']))
            rows={r['panel_id']:r for r in state['panels']}
            # Explicitly leave any caller's candidate review context.
            with review_context(state,base,False):
                for pid in episode['panel_ids']:
                    try:
                        packet=read_json(checked_file(base,rows[pid]['package_manifest']))
                        _,issues=load_context(packet,base,readonly=True)
                        errors.extend('FORMAL_CONTEXT_HOLD:'+episode['episode_id']+'/'+pid+':'+e for e in issues)
                    except (KeyError,TypeError,ValueError,OSError) as exc:
                        errors.append('FORMAL_CONTEXT_HOLD:'+episode['episode_id']+'/'+pid+':'+str(exc))
    return errors


def bind(package_root,run_root,*,execution_context=None):
    from handoff_zip import audit_index,reference,inside,files,sha,write
    from runtime_snapshot import verify
    from execution_contract import toolchain
    package_root=Path(package_root).resolve();run_root=Path(run_root).resolve()
    if run_root.exists() or run_root.is_relative_to(package_root) or package_root.is_relative_to(run_root):raise ValueError('本地运行须为包外全新目录')
    index=audit_index(package_root);plans=[]
    # Validate every source before creating the destination.
    for e in index['episodes']:
        plan=json.loads(reference(package_root,e.get('run_template')).read_text(encoding='utf-8-sig'))
        if plan.get('policy')!=TEMPLATE or plan.get('episode_id')!=e['episode_id']:raise ValueError('运行模板归属错误')
        source=inside(package_root,plan['root']);rows=plan.get('files')
        if not isinstance(rows,list) or sorted(rows,key=lambda x:x['path'])!=files(source):raise ValueError('运行模板文件清单不完整或字节变化')
        for ref in rows:reference(source,ref)
        state_path=inside(source,plan['state_file'])
        if state_path.parent.parent!=source:raise ValueError('模板状态须位于本话根/审计目录/状态文件')
        state=json.loads(state_path.read_text(encoding='utf-8-sig'))
        from dispatch_publication import require_legacy
        require_legacy(state)
        from authority_updates import state_errors as authority_errors
        authority_issues = authority_errors(state)
        if authority_issues: raise ValueError(';'.join(authority_issues))
        if state.get('book_id')!=index['book_id'] or state.get('episode_id')!=e['episode_id']:raise ValueError('运行模板书话不符')
        snap=reference(package_root,e['runtime_manifest']);snap_ref={'path':str(snap),'sha256':sha(snap)}
        frozen=verify(snap_ref)
        if __import__('os').name == 'nt':
            import ast
            for script in Path(frozen['scripts']).glob('*.py'):
                module=ast.parse(script.read_bytes())
                if any(isinstance(node,ast.Import) and any(alias.name=='fcntl' for alias in node.names) for node in module.body):
                    raise ValueError('FROZEN_RUNTIME_UNSUPPORTED: 旧包含Unix专用fcntl；当前生图人员须保留冻结包，在包外建立明确迁移的新本地运行候选并向用户确认受影响范围，不能替换包内脚本或重签原批准')
        new_toolchain=toolchain(frozen['scripts']);old=state.get('toolchain',{})
        # Only roots change; checker and Skill bytes must be the already-frozen ones.
        if (old.get('policy')!=new_toolchain['policy'] or old.get('release')!=new_toolchain['release'] or
            old.get('files')!=new_toolchain['files'] or
            {skill_entry_key(x['path']):x['sha256'] for x in old.get('skill_entries',[])}!=
            {skill_entry_key(x['path']):x['sha256'] for x in new_toolchain['skill_entries']}):
            raise ValueError('模板与冻结工具字节不符，须在前期冻结前修正')
        old_memory={k:v for k,v in (state.get('memory_source') or {}).items() if k not in {'root','runtime_snapshot'}}
        new_memory={k:v for k,v in (frozen['memory_source'] or {}).items() if k not in {'root','runtime_snapshot'}}
        if old_memory!=new_memory:raise ValueError('模板规则版本或索引变化，不能当作路径绑定')
        state={**state,'runtime_snapshot':snap_ref,'toolchain':new_toolchain}
        if execution_context is not None:
            from runtime_clock import execution_context as verify_context
            verify_context(run_root/e['episode_id'],state={'runtime_execution_context':execution_context})
            state['runtime_execution_context']=execution_context
        elif state.get('runtime_execution_context') is not None:
            # Historical preparation timing is not a receiver's clock policy.
            state.pop('runtime_execution_context')
        if frozen['memory_source'] is not None or 'memory_source' in state:state['memory_source']=frozen['memory_source']
        plans.append((e,plan,source,state,sha(state_path)))
    run_root.mkdir(parents=True);runs=[]
    try:
        for e,plan,source,state,old_sha in plans:
            episode_root=inside(run_root,e['episode_id']);shutil.copytree(source,episode_root)
            state_file=inside(episode_root,plan['state_file']);state_file.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n', encoding='utf-8', newline='\n')
            evidence={'policy':'runtime_only_relocation_v1','package_id':index['package_id'],'episode_id':e['episode_id'],
                      'template_state_sha256':old_sha,'local_state_sha256':sha(state_file),'changed_fields':['runtime_snapshot','toolchain','memory_source']+(['runtime_execution_context'] if execution_context is not None else []),
                      'creative_files_unchanged':True,'approval_rewritten':False,'budget_reset':False,
                      'input_mode':'package_only_production','external_inputs_required':False,
                      'usage_config_path_role':'historical_origin_only_not_receiver_configuration'}
            proof=episode_root/'接包路径绑定.json';write(proof,evidence)
            runs.append({'episode_id':e['episode_id'],'state':state_file.relative_to(run_root).as_posix(),
                         'binding_evidence':{'path':proof.relative_to(run_root).as_posix(),'sha256':sha(proof)}})
        dest=run_root/'本地绑定索引.json';write(dest,{'package_id':index['package_id'],'episodes':runs})
    except Exception:
        shutil.rmtree(run_root);raise
    return {'status':'LOCAL_RUN_BOUND_NOT_IMAGE_AUTHORIZATION','input_mode':'package_only_production',
            'external_inputs_required':False,'book_profile_required':False,
            'run_root':str(run_root),'run_index':str(dest),'image_calls':0}


def input_review(root,index):
    """Digest the final creative/executable inputs, excluding later human receipts."""
    from handoff_zip import reference
    import hashlib
    episodes=[]
    for e in index['episodes']:
        selected={k:e[k] for k in (('episode_id','panel_ids') if episode_mode(index) else ('episode_id','panel_ids','halves'))}
        selected['production_scope']=e['panels']
        for k in ('source_script','production_source_snapshot','visual_basis','shot_manifest','runtime_manifest'):
            reference(root,e.get(k));selected[k]=e[k]
        packages=e.get('generation_review_packages')
        if not isinstance(packages,list) or not packages:raise ValueError('缺最终实际生图包审查输入')
        for ref in packages:reference(root,ref)
        selected['generation_review_packages']=packages
        if e.get('input_semantics_policy'):
            from input_semantics import POLICIES
            if e['input_semantics_policy'] not in POLICIES:raise ValueError('未知最终输入审查策略')
            reference(root,e.get('semantic_audit'))
            selected.update(input_semantics_policy=e['input_semantics_policy'],semantic_audit=e['semantic_audit'])
        episodes.append(selected)
    value={'policy':'approved_inputs_auto_export_v1','package_id':index['package_id'],'book_id':index['book_id'],'episodes':episodes}
    if episode_mode(index):
        value.update(handoff_policy=index['policy'],production_window_policy=index['production_window_policy'])
    if 'task_context' in index:value['task_context']=index['task_context']
    return {**value,'approved_input_digest':hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()}


def copy_assembly_plan(source,destination,plan):
    """Create a pre-approval candidate from an explicit reviewed file/dependency plan.

    This is not a heuristic history deleter. Missing/unknown dependencies HOLD;
    original audit_index and runtime manifests remain authoritative after copying.
    """
    from handoff_zip import inside,reference,files,audit_index
    from platform_io import portable_relative
    import tempfile
    source=Path(source).resolve();destination=Path(destination).resolve()
    if (destination.exists() or destination.is_relative_to(source) or source.is_relative_to(destination)):
        raise ValueError('ASSEMBLY_HOLD:候选须为源包外全新目录')
    if (not isinstance(plan,dict) or plan.get('policy')!='explicit_handoff_assembly_v1'
        or plan.get('unresolved_paths')!=[] or not plan.get('reviewer') or not plan.get('evidence')):
        raise ValueError('ASSEMBLY_HOLD:缺明确装配范围/复核依据，未知依赖不能省略')
    rows=plan.get('files');required=plan.get('required_paths');dependencies=plan.get('dependencies')
    if not isinstance(rows,list) or not rows or not isinstance(required,list) or not required or not isinstance(dependencies,dict):
        raise ValueError('ASSEMBLY_HOLD:缺装配清单及必要引用')
    selected={}
    for row in rows:
        if (not isinstance(row,dict) or row.get('reason') not in {'execution','traceability','runtime','release'}
            or not row.get('evidence') or not isinstance(row.get('path'),str)):
            raise ValueError('ASSEMBLY_HOLD:逐文件须有入包原因与依据')
        portable_relative(row['path'])
        if row['path'] in selected:raise ValueError('ASSEMBLY_HOLD:装配路径重复')
        p=reference(source,row)
        if p.is_symlink() or p.stat().st_size!=row.get('bytes'):raise ValueError('ASSEMBLY_HOLD:源文件尺寸或类型不符')
        selected[row['path']]=p
    if not set(required)<=set(selected):raise ValueError('ASSEMBLY_HOLD:缺必要材料')
    for name,targets in dependencies.items():
        if name not in selected or not isinstance(targets,list) or not set(targets)<=set(selected):
            raise ValueError('ASSEMBLY_HOLD:传递引用未闭合')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent,prefix='.handoff-assembly-') as temp:
        stage=Path(temp)/'candidate';stage.mkdir()
        for name,p in selected.items():
            target=inside(stage,name);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
        # Prevent a selected subset from silently breaking real source approvals,
        # run-template inventories, or original frozen runtime dependencies.
        audit_index(stage)
        if files(stage)!=[{k:row[k] for k in ('path','sha256','bytes')} for row in sorted(rows,key=lambda x:x['path'])]:
            raise ValueError('ASSEMBLY_HOLD:复制后清单不符')
        for row in rows:reference(source,row)
        shutil.move(str(stage),str(destination))
    return {'status':'ASSEMBLED_CANDIDATE_NOT_APPROVED','path':str(destination),'files':len(rows),
        'image_calls':0,'approval_created':False}
