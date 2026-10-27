#!/usr/bin/env python3
"""Incremental WORKING_DRAFT materialization. No QA/approval/state registration."""
import argparse
import copy
import json
import time
from pathlib import Path
from panel_source import read,write_new,validate,expand
from input_dependencies import fingerprint,file_hash,capture,recheck,affected
from platform_io import configure_stdio,portable_relative

POLICY='panel_derivation_v1'
GENERATED={'prompt','negative_prompt','camera_execution_block','content_execution_block',
           'identity_execution_block','style_execution_block','frame_ratio_execution_block'}

def effective(source,row):
    library=source['shared'];shot=expand(row['shot'],library)
    execution=expand(row['execution'],library)
    return shot,{**shot,**execution},expand(row['packet_header'],library)

def render(source,row,panel,header,previous,following):
    if row['render_mode']=='preserved_import':
        # Imported prose is preserved byte-for-byte; changes need actual recompilation.
        if fingerprint(panel)!=row.get('import_panel_key'):
            raise ValueError('导入的文字与创作输入已变化，请切换structured_v2或重新导入已实际编译的候选')
        return panel
    from repair_prompt_package_v2 import build_prompt,character_details
    names=('camera_angle_family','shot_scale','frame_ratio','camera_position',
           'facing_direction','camera_height','visible_region','camera_view_signature')
    if any(not isinstance(panel.get(k),str) or not panel[k].strip() for k in names):
        raise ValueError('结构派生须明确机位、景别、比例、位置/朝向、高度、可见区域和签名，不猜测缺项')
    if row.get('required_reference_aliases') is not None:
        from reference_atlas import select_reference_set
        panel['reference_images']=select_reference_set(panel.get('reference_images',[]),row['required_reference_aliases'])
    aliases=[ref['alias'] for ref in panel.get('reference_images',[])]
    panel['asset_mentions']=aliases
    angle,scale,ratio,position,facing,height,visible,signature=[panel[k] for k in names]
    from repair_prompt_package_v2 import event_text
    characters=character_details(panel,event_text(panel),angle,visible)
    prompt,negative,blocks=build_prompt(panel,angle,scale,ratio,position,facing,height,visible,aliases,previous,following,signature,characters)
    panel['camera_execution_block'],_,panel['content_execution_block']=blocks.partition('\n\n')
    from input_priority import POLICY as PRIORITY,EXECUTION_BLOCK,resolution_block
    if header.get('input_priority_policy')==PRIORITY or panel.get('input_priority_policy')==PRIORITY:
        prompt+='\n'+'\n'.join(t for t in (EXECUTION_BLOCK,resolution_block(panel.get('visual_resolution'))) if t)
    from identity_confirmation import execution_block as identity_block
    registry=panel.get('identity_registry') or header.get('identity_registry') or expand(source['shot_header'],source['shared']).get('identity_registry')
    if panel.get('character_bindings'):
        if not registry: raise ValueError('缺身份状态注册表')
        panel['identity_execution_block']=identity_block(panel,registry);prompt+='\n\n'+panel['identity_execution_block']
    if panel.get('frame_ratio_policy') or header.get('frame_ratio_policy'):
        from frame_ratio_plan import execution_block
        panel['frame_ratio_execution_block']=execution_block(panel)
        if panel['frame_ratio_execution_block'] not in prompt: prompt+='\n'+panel['frame_ratio_execution_block']
    if panel.get('style_contract'):
        from style_contract import style_block
        panel['style_execution_block']=style_block(panel['style_contract']);prompt+='\n\n'+panel['style_execution_block']
    if panel.get('reference_bindings'):
        from continuity_contract import reference_usage_block
        prompt+='\n\n'+reference_usage_block(panel['reference_bindings'],panel.get('reference_images'))
    from rule_memory import append_execution_constraints
    prompt=append_execution_constraints(prompt,panel)
    if source.get('prompt_tail'):
        raise ValueError('共用规则须写入适用memory_applications，不接受未经绑定的全局prompt_tail')
    if panel.get('reference_input_policy')=='codex_reference_v1' or header.get('reference_input_policy')=='codex_reference_v1':
        from codex_reference_contract import final_prompt
        prompt=final_prompt(prompt,negative)
    from input_semantics import conflict_errors
    errors=conflict_errors(panel,prompt)
    if errors: raise ValueError(';'.join(errors))
    panel.update(prompt=prompt,negative_prompt=negative)
    return panel

def tool_versions():
    # Tool membership and contents bind the draft receipt, never approved-input authority.
    return {p.name:file_hash(p) for p in sorted(Path(__file__).parent.glob('*.py'))}

def build_index(source):
    validate(source);memo={};panels=[];header=expand(source['shot_header'],source['shared'])
    source_ref=source['source_snapshot']
    source_path=Path(source_ref['path'])
    if not source_path.is_absolute(): source_path=Path(source['run_root'])/source_path
    if file_hash(source_path)!=source_ref['sha256']: raise ValueError('源稿快照哈希失配')
    original=read(source_path)
    if original['panel_ids']!=source['panel_ids']: raise ValueError('主表改变了原始源序')
    versions=tool_versions()
    for row in source['panels']:
        shot,panel,packet_header=effective(source,row)
        if shot.get('locked_script')!=original['locked_scripts'][row['panel_id']]: raise ValueError('主表不能改写原稿:'+row['panel_id'])
        deps=list(dict.fromkeys([*shot.get('generation_dependencies',[]),*shot.get('design_dependencies',[]),*row.get('dependencies',[])]))
        # Explicit comparison links can reference remote episodes too; never add every neighbor.
        if row.get('neighbor_context'):
            position=source['panel_ids'].index(row['panel_id'])
            deps.extend(source['panel_ids'][max(0,position-1):position]+source['panel_ids'][position+1:position+2])
        prior=shot.get('continuity_contract',{}).get('scene',{}).get('previous_panel_id')
        comparisons=[prior] if prior else []
        dependency_error=None
        try:
            observations=capture([source['source_snapshot'],header,shot,panel,packet_header],source['run_root'],row.get('dependency_queries',[]),memo)
            missing=[o['path'] for o in observations if o.get('required_missing')]
            if missing: dependency_error='必要文件缺失:'+','.join(missing)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            observations=[];dependency_error=str(exc)
        key=fingerprint([source['book_id'],source['episode_id'],header,{k:v for k,v in shot.items() if k not in {'planning_notes','inspection_plan'}},{k:v for k,v in panel.items() if k not in {'planning_notes','inspection_plan'}},packet_header,row['render_mode'],row.get('required_reference_aliases'),row.get('neighbor_context',False),deps,observations,dependency_error,versions])
        panels.append({'panel_id':row['panel_id'],'input_key':key,'depends_on':deps,'comparison_with':comparisons,'observations':observations,**({'dependency_error':dependency_error} if dependency_error else {})})
    return {'policy':POLICY,'book_id':source['book_id'],'episode_id':source['episode_id'],
            'panel_ids':source['panel_ids'],'panels':panels,'tool_versions':versions,
            'dispatch_authorized':False,'review_reuse_authorized':False}

def previous_receipt(path,source):
    if path is None: return None
    value=read(path)
    if value.get('policy')!=POLICY or any(value.get(k)!=source[k] for k in ('book_id','episode_id')):
        raise ValueError('旧派生记录的策略/书话不符')
    for row in value.get('panels',[]):
        try:
            if row.get('pending') or row.get('error') or not row.get('artifacts'): raise ValueError('旧派生未完成')
            for ref in row['artifacts']:
                if file_hash(ref['path'])!=ref['sha256']: raise ValueError('旧产物失效')
        except (OSError,ValueError,KeyError):
            row['input_key']=None
    return value

def plan(source_path,previous=None):
    source=read(source_path);index=build_index(source);old=previous_receipt(previous,source)
    return {**index,'impact':affected(old,index),'status':'DRAFT_PLAN_ONLY',
            'errors':{p['panel_id']:p['dependency_error'] for p in index['panels'] if p.get('dependency_error')}}

def derive(source_path,output,previous=None):
    started=time.monotonic();source=read(source_path);source_hash=file_hash(source_path)
    index=build_index(source);old=previous_receipt(previous,source);impact=affected(old,index)
    old_rows={p['panel_id']:p for p in (old or {}).get('panels',[])}
    changed=set(impact['affected_panel_ids']);output=Path(output).resolve()
    if output.exists(): raise ValueError('派生输出必须是新目录；不覆盖草稿或批准版本')
    materialized=[];results=[];failures={};new_count=0;reuse_count=0
    indexed={p['panel_id']:p for p in index['panels']}
    for position,row in enumerate(source['panels']):
        pid=row['panel_id'];portable_relative(pid)
        if '/' in pid or '\\' in pid: raise ValueError('格号不能是目录路径')
        shot,panel,header=effective(source,row);materialized.append(shot)
        old_row=old_rows.get(pid,{})
        if indexed[pid].get('dependency_error'):
            failures[pid]=indexed[pid]['dependency_error']
            results.append({**indexed[pid],'artifacts':[],'error':failures[pid],'reused':False})
            continue
        if pid not in changed:
            try:
                for ref in old_row['artifacts']:
                    if file_hash(ref['path'])!=ref['sha256']: raise ValueError('派生产物变化')
                results.append({**indexed[pid],
                                'artifacts':old_row['artifacts'],'reused':True});reuse_count+=1;continue
            except (OSError,ValueError,KeyError): changed.add(pid)
        try:
            previous=effective(source,source['panels'][position-1])[0] if row.get('neighbor_context') and position else None
            following=effective(source,source['panels'][position+1])[0] if row.get('neighbor_context') and position+1<len(source['panels']) else None
            panel=render(source,row,panel,header,previous,following)
            from codex_reference_contract import invalidate_execution
            invalidate_execution(panel)
            panel['generation_execution']={'status':'NOT_RUN','reason':'WORKING_DRAFT_NOT_DISPATCHED'}
            panel['prompt_file']='prompt.txt'
            panel['negative_prompt_file']='negative_prompt.txt'
            directory=output/pid;manifest=directory/'manifest.json';prompt=directory/'prompt.txt'
            write_new(manifest,{**header,'panels':[panel]})
            with prompt.open('x',encoding='utf-8',newline='\n') as stream: stream.write(panel['prompt'])
            negative=directory/'negative_prompt.txt'
            with negative.open('x',encoding='utf-8',newline='\n') as stream: stream.write(panel.get('negative_prompt',''))
            artifacts=[{'path':str(p),'sha256':file_hash(p)} for p in (manifest,prompt,negative)]
            results.append({**indexed[pid],'artifacts':artifacts,'reused':False});new_count+=1
        except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
            failures[pid]=str(exc)
            results.append({**indexed[pid],'artifacts':[],'error':str(exc),'reused':False})
    # Dependents of a failed derivation stay explicitly pending, never silently ready.
    blocked=set(failures)
    while True:
        more={p['panel_id'] for p in index['panels'] if set(p['depends_on'])&blocked}-blocked
        if not more: break
        blocked.update(more)
    for row in results:
        if row['panel_id'] in blocked: row['pending']=True
    observations={fingerprint(o):o for p in index['panels'] for o in p['observations']}
    recheck(observations.values())
    if tool_versions()!=index['tool_versions'] or file_hash(source_path)!=source_hash: raise ValueError('派生期间输入或工具变化，请从现有草稿恢复')
    write_new(output/'镜头派生.json',{**expand(source['shot_header'],source['shared']),'panels':materialized})
    binding_plan={'shot_manifest':{'path':str(output/'镜头派生.json'),'sha256':file_hash(output/'镜头派生.json')},
                  'packages':{r['panel_id']:r['artifacts'][0] for r in results if r['artifacts'] and not r.get('pending')},
                  'dispatch_authorized':False,'status':'REBIND_WORKING_INPUTS_AND_REVIEW',
                  'next':'由执行者将准确工作输入引用同步到本话草稿及语义审查；不覆盖冻结状态，不继承旧批准'}
    write_new(output/'工作绑定计划.json',binding_plan)
    write_new(output/'审查展示.json',{'book_id':source['book_id'],'episode_id':source['episode_id'],
                                   'panels':[{'panel_id':r['panel_id'],'artifacts':r['artifacts'],'pending':r.get('pending',False)} for r in results],
                                   'status':'DRAFT_NOT_REVIEWED','dispatch_authorized':False})
    receipt={**index,'panels':results,'impact':impact,'source_file':{'path':str(Path(source_path).resolve()),'sha256':source_hash},
             'status':'DRAFT_PARTIAL' if blocked else 'DRAFT_MATERIALIZED_NOT_APPROVED',
             'pending_panel_ids':[pid for pid in source['panel_ids'] if pid in blocked],'errors':failures,
             'metrics':{'compiled_panels':new_count,'reused_panels':reuse_count,'elapsed_seconds':time.monotonic()-started},
             'next':'核对新镜头与实际输入，更新准确引用，按原候选/语义/批准入口完成实际审查；不要因DRAFT成功跳过门禁'}
    write_new(output/'派生记录.json',receipt)
    return receipt

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['plan','derive']);p.add_argument('--source',required=True)
    p.add_argument('--output');p.add_argument('--previous');a=p.parse_args()
    try:
        if a.action=='derive' and not a.output: raise ValueError('derive缺--output')
        value=derive(a.source,a.output,a.previous) if a.action=='derive' else plan(a.source,a.previous)
        print(json.dumps(value,ensure_ascii=False));return 1 if value.get('errors') else 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'DRAFT_DERIVATION_HOLD','error':str(exc),'dispatch_authorized':False},ensure_ascii=False));return 1
if __name__=='__main__': configure_stdio();raise SystemExit(main())
