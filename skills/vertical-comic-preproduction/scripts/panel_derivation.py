#!/usr/bin/env python3
"""Incremental WORKING_DRAFT materialization. No QA/approval/state registration."""
import argparse
import copy
import json
import time
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import nullcontext
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
    from spatial_contract import override_errors
    errors=override_errors(shot,execution)
    if errors: raise ValueError(';'.join(errors))
    return shot,{**shot,**execution},expand(row['packet_header'],library)

def facial_continuity_block(panel):
    """Use only this panel's bound, actually supplied identity references."""
    aliases={r.get('alias') for r in panel.get('reference_images', []) if isinstance(r,dict)}
    people=[];seen=set()
    for binding in panel.get('character_bindings', []):
        if not isinstance(binding,dict) or not binding.get('on_screen') or binding.get('asset_exemption'):
            continue
        cid=binding.get('character_id');alias=binding.get('identity_asset_alias')
        visibility=(panel.get('subject_visibility') or {}).get(cid) or {}
        if visibility.get('face_visible') is False:continue
        if cid and isinstance(alias,str) and alias and alias in aliases and (cid,alias) not in seen:
            seen.add((cid,alias));people.append(f'{cid}：身份参考{alias}')
    if not people:return ''
    return ('人物五官一致性：'+'；'.join(people)+'。面部可见时，依据各自身份参考保持脸型、眉眼形状与间距、鼻唇形态和相对比例稳定，避免人物之间串脸；表情、视线与透视随本格动作和机位自然变化，遮挡或画外部分不强行露出。')

def render(source,row,panel,header,previous,following):
    if row['render_mode']=='preserved_import':
        # Imported prose is preserved byte-for-byte; changes need actual recompilation.
        if fingerprint(panel)!=row.get('import_panel_key'):
            raise ValueError('导入的文字与创作输入已变化，请切换structured_v2或重新导入已实际编译的候选')
        return panel
    from spatial_contract import selection_errors,projection_errors
    errors=selection_errors(panel)+projection_errors(panel)
    if errors: raise ValueError(';'.join(errors))
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
    facial=facial_continuity_block(panel)
    if facial:prompt+='\n\n'+facial
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

def selected_rows(source,panel_ids=None):
    if source.get('policy')=='preparation_scope_source_v1':
        if panel_ids is None:raise ValueError('INTERNAL_SCOPE_REQUIRES_PANEL_IDS')
        from preparation_workspace import validate_scope
        validate_scope(source)
    else:validate(source)
    selected=source['panel_ids'] if panel_ids is None else list(panel_ids)
    if not selected or len(selected)!=len(set(selected)) or set(selected)-set(source['panel_ids']):
        raise ValueError('派生作用域缺格/重复/未知格')
    rows={row['panel_id']:row for row in source['panels']}
    if set(selected)-set(rows):raise ValueError('派生作用域包含未完成行')
    return [rows[pid] for pid in source['panel_ids'] if pid in set(selected)]


def prepare(source,panel_ids=None):
    rows=selected_rows(source,panel_ids);memo={};panels=[];prepared={};header=expand(source['shot_header'],source['shared'])
    source_ref=source['source_snapshot']
    source_path=Path(source_ref['path'])
    if not source_path.is_absolute(): source_path=Path(source['run_root'])/source_path
    if file_hash(source_path)!=source_ref['sha256']: raise ValueError('源稿快照哈希失配')
    original=read(source_path)
    if original['panel_ids']!=source['panel_ids']: raise ValueError('主表改变了原始源序')
    versions=tool_versions()
    # Read the source/header transitive closure once, not once per panel.
    common_error=None
    try:common_observations=capture([source['source_snapshot'],header],source['run_root'],memo=memo)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        common_observations=[];common_error=str(exc)
    # Top-level ratio authority participates in the read transaction even when
    # it is not duplicated into prompt headers. Its own changed row fields, not
    # unrelated plan members, determine the panel compilation key.
    administrative_observations=capture(source.get('frame_ratio_plan'),source['run_root'],memo=memo)
    authored={row['panel_id']:row for row in source['panels']}
    positions={pid:position for position,pid in enumerate(source['panel_ids'])}
    def actual(pid):
        if pid not in prepared:
            prepared[pid]=effective(source,authored[pid])
            if prepared[pid][0].get('locked_script')!=original['locked_scripts'][pid]:
                raise ValueError('主表不能改写原稿:'+pid)
        return prepared[pid]
    for row in rows:
        shot,panel,packet_header=actual(row['panel_id'])
        deps=list(dict.fromkeys([*shot.get('generation_dependencies',[]),*shot.get('design_dependencies',[]),*row.get('dependencies',[])]))
        # Explicit comparison links can reference remote episodes too; never add every neighbor.
        neighbor_inputs=[];neighbor_shots=[];missing_neighbors=[]
        if row.get('neighbor_context'):
            position=positions[row['panel_id']]
            for target in (position-1,position+1):
                if not 0<=target<len(source['panel_ids']):
                    neighbor_inputs.append(None);continue
                pid=source['panel_ids'][target];deps.append(pid)
                if pid not in authored:
                    missing_neighbors.append(pid);neighbor_inputs.append({'panel_id':pid,'missing':True})
                else:
                    neighbor=actual(pid)[0];neighbor_shots.append(neighbor)
                    neighbor_inputs.append({'panel_id':pid,'shot':neighbor})
        prior=shot.get('continuity_contract',{}).get('scene',{}).get('previous_panel_id')
        comparisons=[prior] if prior else []
        dependency_error=None
        try:
            local=capture([shot,panel,packet_header,*neighbor_shots],source['run_root'],row.get('dependency_queries',[]),memo)
            observations=sorted({o['path']:o for o in [*common_observations,*local]}.values(),key=lambda o:o['path'])
            if common_error:raise ValueError(common_error)
            missing=[o['path'] for o in observations if o.get('required_missing')]
            if missing: dependency_error='必要文件缺失:'+','.join(missing)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            observations=[];dependency_error=str(exc)
        if missing_neighbors:
            dependency_error=';'.join(filter(None,['NEEDS_AUTHORING_NEIGHBOR:'+','.join(missing_neighbors),dependency_error]))
        key_inputs=[source['book_id'],source['episode_id'],header,{k:v for k,v in shot.items() if k not in {'planning_notes','inspection_plan'}},{k:v for k,v in panel.items() if k not in {'planning_notes','inspection_plan'}},packet_header,row['render_mode'],row.get('required_reference_aliases'),row.get('neighbor_context',False),deps,observations,dependency_error,versions]
        # Explicit neighbor context consumes authored inputs, not merely IDs.
        # Bind their bytes even when only this panel is selected for derivation.
        if row.get('neighbor_context'):key_inputs.append(neighbor_inputs)
        key=fingerprint(key_inputs)
        panels.append({'panel_id':row['panel_id'],'input_key':key,'depends_on':deps,'comparison_with':comparisons,'observations':observations,**({'dependency_error':dependency_error} if dependency_error else {})})
    return ({'policy':POLICY,'book_id':source['book_id'],'episode_id':source['episode_id'],
            'panel_ids':source['panel_ids'],'selected_panel_ids':[row['panel_id'] for row in rows],
            'panels':panels,'tool_versions':versions,'common_observations':administrative_observations,
            'dispatch_authorized':False,'review_reuse_authorized':False},rows,prepared)


def build_index(source, *, panel_ids=None):
    return prepare(source,panel_ids)[0]

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

def receipt_pointer(source_path):
    source_path=Path(source_path).resolve()
    return source_path.parent/'.derivation-cache'/(fingerprint(str(source_path))+'.json')


def resolve_previous(source_path, source, previous=None, output=None):
    """Find only this authoring file's receipts; mtime selects, hashes validate reuse."""
    if previous is not None:
        return previous_receipt(previous,source), {'mode':'explicit','path':str(Path(previous).resolve())}
    root=Path(source['run_root']).resolve();source_path=Path(source_path).resolve()
    if not source_path.is_relative_to(root):
        return None, {'mode':'external_source_no_automatic_reuse','path':None}
    pointer=receipt_pointer(source_path);candidates=[];seen=set()
    if pointer.is_file():
        try:
            item=read(pointer);target=Path(item['path']).resolve()
            if item.get('source_path')==str(source_path) and target.is_relative_to(root) and file_hash(target)==item['sha256']:
                candidates.append(target)
        except (OSError,ValueError,KeyError,TypeError):pass
    # Recovery for pre-index runs: bounded directory depth, never walk the whole RV.
    parents={root/'04_B提示词包_CANDIDATE'}
    if output is not None:
        parent=Path(output).resolve().parent
        if parent.is_relative_to(root):parents.add(parent)
    def choices():
        yield from candidates
        yield from sorted({p for parent in parents if parent.is_dir() for p in parent.glob('*/派生记录.json')},
                          key=lambda p:p.stat().st_mtime_ns,reverse=True)
    for path in choices():
        if path in seen:continue
        seen.add(path)
        try:
            value=read(path)
            if (not path.resolve().is_relative_to(root) or
                Path(value.get('source_file',{}).get('path','')).resolve()!=source_path or
                value.get('policy')!=POLICY or any(value.get(k)!=source[k] for k in ('book_id','episode_id'))):continue
            if any(not Path(ref['path']).resolve().is_relative_to(root) for row in value.get('panels',[]) for ref in row.get('artifacts',[])):continue
            return previous_receipt(path,source), {'mode':'automatic','path':str(path.resolve())}
        except (OSError,ValueError,KeyError,TypeError):continue
    return None, {'mode':'first_derivation','path':None}


def remember_receipt(source_path,receipt_path):
    from platform_io import atomic_json,file_lock
    pointer=receipt_pointer(source_path);pointer.parent.mkdir(parents=True,exist_ok=True)
    with file_lock(pointer.with_suffix('.lock')):
        atomic_json(pointer,{'source_path':str(Path(source_path).resolve()),
            'path':str(Path(receipt_path).resolve()),'sha256':file_hash(receipt_path)})


def plan(source_path,previous=None):
    source=read(source_path);index=build_index(source);old,resolution=resolve_previous(source_path,source,previous)
    return {**index,'impact':affected(old,index),'previous_derivation':resolution,'status':'DRAFT_PLAN_ONLY',
            'errors':{p['panel_id']:p['dependency_error'] for p in index['panels'] if p.get('dependency_error')}}

def worker_count(workers):
    if workers=='all':return os.cpu_count() or 1
    if type(workers) is not int or workers<1:raise ValueError('workers须为正整数或all')
    return workers


class DerivationExecutor:
    """One batch-wide thread pool; Coordinator controls actual concurrent work.

    Threads share immutable prepared inputs, avoiding per-panel interpreters/IPC.
    A host supplying another executor must explicitly own its machine admission
    by setting resource_admission='host_managed'. This is never image authority.
    """
    resource_admission='coordinator_managed'
    def __init__(self,workers='all',*,coordinator=None,disk=None):
        from machine_resources import Coordinator
        self.resources=coordinator or Coordinator();self.disk=Path(disk or self.resources.home)
        self.worker_limit=worker_count(workers)
        self.pool=ThreadPoolExecutor(max_workers=self.worker_limit,thread_name_prefix='panel-derive')
        self.host_token=None;self.lock=threading.Lock();self.admission=threading.Condition();self.closed=False
    def pending_limit(self):
        view=self.resources.status(disk=self.disk)
        return max(1,min(self.worker_limit,view['limits']['compile']))
    def _acquire(self,kind,key,budget_path=None):
        from runtime_clock import require_step
        with self.admission:
            while True:
                require_step(budget_path or self.disk,'compile')
                permit=self.resources.acquire(kind,key,disk=self.disk)
                if permit['status']=='RESOURCE_GRANTED':return permit['token']
                # Local completion wakes queued work immediately. The timeout
                # only reconciles pressure or leases owned by other processes.
                self.admission.wait(permit.get('retry_after_ms',500)/1000)
    def submit(self,fn,*args,**kwargs):
        budget_path=args[0]['run_root'] if args and isinstance(args[0],dict) and 'run_root' in args[0] else self.disk
        with self.lock:
            if self.closed:raise RuntimeError('派生pool已关闭')
            if self.host_token is None:self.host_token=self._acquire('host','derive-host/'+uuid.uuid4().hex,budget_path)
        def admitted():
            token=self._acquire('compile','derive-panel/'+uuid.uuid4().hex,budget_path);completed=False
            try:
                result=fn(*args,**kwargs);completed=not result.get('error');return result
            finally:
                with self.admission:
                    self.resources.release(token,completed=completed)
                    self.admission.notify_all()
        return self.pool.submit(admitted)
    def __enter__(self):return self
    def __exit__(self,*exc):self.shutdown()
    def shutdown(self,wait=True):
        # A host lease cannot be released before all submitted work has drained.
        if not wait:raise ValueError('DERIVATION_POOL_MUST_DRAIN')
        with self.lock:self.closed=True
        self.pool.shutdown(wait=True)
        if self.host_token is not None:
            self.resources.release(self.host_token);self.host_token=None


def _compile_panel(source,row,prepared,indexed,output,neighbors):
    pid=row['panel_id'];shot,panel,header=prepared[pid];started=time.monotonic()
    def timing():return {'started_monotonic':started,'completed_monotonic':time.monotonic()}
    try:
        from runtime_clock import require_step
        require_step(source['run_root'],'compile')
        panel=render(source,row,copy.deepcopy(panel),header,*neighbors)
        from codex_reference_contract import invalidate_execution
        invalidate_execution(panel)
        panel['generation_execution']={'status':'NOT_RUN','reason':'WORKING_DRAFT_NOT_DISPATCHED'}
        panel['prompt_file']='prompt.txt';panel['negative_prompt_file']='negative_prompt.txt'
        directory=output/pid;manifest=directory/'manifest.json';prompt=directory/'prompt.txt'
        write_new(manifest,{**header,'panels':[panel]})
        with prompt.open('x',encoding='utf-8',newline='\n') as stream:stream.write(panel['prompt'])
        negative=directory/'negative_prompt.txt'
        with negative.open('x',encoding='utf-8',newline='\n') as stream:stream.write(panel.get('negative_prompt',''))
        artifacts=[{'path':str(p),'sha256':file_hash(p)} for p in (manifest,prompt,negative)]
        return {**indexed[pid],'artifacts':artifacts,'reused':False,'compile_timing':timing()}
    except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
        return {**indexed[pid],'artifacts':[],'error':str(exc),'reused':False,'compile_timing':timing()}


class PublicationGuard:
    """Content-verified read transaction for each streamed technical publication.

    Cached bytes are reused only while physical target, device/inode, size and
    nanosecond mtime/ctime remain identical, as in the existing file_session.
    Directory observations retain every recorded member/directory stamp, so an
    insertion anywhere in a consumed directory invalidates the proof.
    """
    def __init__(self,source_path,source_hash,index):
        self.source_path=Path(source_path);self.source_hash=source_hash
        self.index=index;self.files={};self.observations={}
        self.tool_root=Path(__file__).parent
    @staticmethod
    def stamp(path):
        path=Path(path)
        def identity(stat):return (stat.st_dev,stat.st_ino,stat.st_mode,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
        try:link=identity(path.lstat());target=identity(path.stat())
        except FileNotFoundError:link=target=None
        return (str(path.resolve()),link,target)
    def file(self,path,expected):
        path=Path(path);key=str(path);current=self.stamp(path);saved=self.files.get(key)
        error='派生期间输入或工具变化，请从现有草稿恢复'
        if saved is not None:
            if saved!=(current,expected):raise ValueError(error)
            return
        if file_hash(path)!=expected or self.stamp(path)!=current:raise ValueError(error)
        self.files[key]=(current,expected)
    def observation(self,observation):
        key=fingerprint(observation);path=Path(observation['path'])
        names=[path,*[path/row['name'] for row in observation.get('members',[])]]
        current=tuple(self.stamp(name) for name in names)
        saved=self.observations.get(key)
        if saved is not None:
            if saved!=current:raise ValueError('DRAFT_DEPENDENCY_CHANGED:'+str(path))
            return
        recheck([observation])
        if tuple(self.stamp(name) for name in names)!=current:
            raise ValueError('DRAFT_DEPENDENCY_CHANGED:'+str(path))
        self.observations[key]=current
    def check(self,row):
        expected=self.index['tool_versions']
        if [p.name for p in sorted(self.tool_root.glob('*.py'))]!=list(expected):
            raise ValueError('派生期间输入或工具变化，请从现有草稿恢复')
        for name,sha256 in expected.items():self.file(self.tool_root/name,sha256)
        self.file(self.source_path,self.source_hash)
        observations=[*self.index.get('common_observations',[]),*row['observations']]
        for observation in observations:self.observation(observation)
        # Verify the complete selected proof again after its last content read;
        # a concurrently changed shared file must not reach the callback.
        for path,(stamp,_) in self.files.items():
            if self.stamp(path)!=stamp:raise ValueError('派生期间输入或工具变化，请从现有草稿恢复')
        for observation in observations:self.observation(observation)


def derive(source_path,output,previous=None,*,panel_ids=None,workers='all',sink=None,executor=None):
    started=time.monotonic();source_hash=file_hash(source_path);source=read(source_path)
    index,rows,prepared=prepare(source,panel_ids)
    if file_hash(source_path)!=source_hash:raise ValueError('派生期间输入或工具变化，请从现有草稿恢复')
    old,resolution=resolve_previous(source_path,source,previous,output)
    # Rows outside an explicit selection still exist in the original episode.
    # A partial derivation must not turn them into removed dependencies.
    impact_old=old
    if old is not None and panel_ids is not None:
        selected=set(index['selected_panel_ids'])
        impact_old={**old,'panels':[row for row in old.get('panels',[]) if row['panel_id'] in selected]}
    impact=affected(impact_old,index)
    old_rows={p['panel_id']:p for p in (old or {}).get('panels',[])}
    changed=set(impact['affected_panel_ids']);output=Path(output).resolve()
    if output.exists():raise ValueError('派生输出必须是新目录；不覆盖草稿或批准版本')
    worker_count(workers)
    if executor is not None and getattr(executor,'resource_admission',None) not in {'host_managed','coordinator_managed'}:
        raise ValueError('DERIVATION_EXECUTOR_RESOURCE_ADMISSION_REQUIRED')
    indexed={p['panel_id']:p for p in index['panels']}
    for row in rows:
        pid=row['panel_id'];portable_relative(pid)
        if '/' in pid or '\\' in pid:raise ValueError('格号不能是目录路径')
    output.mkdir(parents=True,exist_ok=False)
    materialized=[prepared[row['panel_id']][0] for row in rows]
    completed={};published=set();failures={};new_count=0;reuse_count=0;first_ready=None;peak_pending=0
    source_rows={row['panel_id']:row for row in source['panels']}
    publication=PublicationGuard(source_path,source_hash,index) if sink is not None else None
    def accept(result):
        nonlocal first_ready
        pid=result['panel_id'];completed[pid]=result
        if result.get('error'):failures[pid]=result['error']
        # A dependent may finish before its prerequisite; publish only when its
        # in-scope dependency closure has a known technical outcome.
        blocked=set(failures)
        while True:
            more={p for p,r in indexed.items() if set(r['depends_on'])&blocked}-blocked
            if not more:break
            blocked.update(more)
        def settled(pid,visiting=None):
            visiting=set() if visiting is None else visiting
            if pid in visiting:return True
            if pid not in completed:return False
            return all(settled(d,visiting|{pid}) for d in indexed[pid]['depends_on'] if d in indexed)
        for pid,result in completed.items():
            if pid in published or not settled(pid):continue
            if pid in blocked:result['pending']=True
            if sink is not None:
                publication.check(result)
                sink(copy.deepcopy(result))
            if first_ready is None and not result.get('pending'):first_ready=time.monotonic()-started
            published.add(pid)
    todo=[]
    for row in rows:
        pid=row['panel_id']
        if indexed[pid].get('dependency_error'):
            accept({**indexed[pid],'artifacts':[],'error':indexed[pid]['dependency_error'],'reused':False})
        elif pid not in changed:
            # resolve_previous already validated every reused artifact in this
            # read transaction. Do not hash the same artifacts a second time.
            accept({**indexed[pid],'artifacts':old_rows[pid]['artifacts'],'reused':True});reuse_count+=1
        else:todo.append(row)
    if todo:
        context=nullcontext(executor) if executor is not None else DerivationExecutor(workers,disk=source['run_root'])
        with context as pool:
            remaining=iter(todo);exhausted=False;futures={}
            while futures or not exhausted:
                limit=pool.pending_limit() if callable(getattr(pool,'pending_limit',None)) else min(worker_count(workers),getattr(pool,'_max_workers',worker_count(workers)))
                while not exhausted and len(futures)<limit:
                    try:row=next(remaining)
                    except StopIteration:exhausted=True;break
                    from runtime_clock import require_step
                    require_step(source['run_root'],'compile')
                    pid=row['panel_id'];position=source['panel_ids'].index(pid);neighbors=[]
                    for offset in (-1,1):
                        target=position+offset
                        neighbor_id=source['panel_ids'][target] if 0<=target<len(source['panel_ids']) else None
                        if row.get('neighbor_context') and neighbor_id is not None:
                            if neighbor_id not in source_rows:raise ValueError('相邻格上下文未完成:'+neighbor_id)
                            neighbors.append(prepared[neighbor_id][0] if neighbor_id in prepared else effective(source,source_rows[neighbor_id])[0])
                        else:neighbors.append(None)
                    futures[pool.submit(_compile_panel,source,row,prepared,indexed,output,neighbors)]=pid
                    peak_pending=max(peak_pending,len(futures))
                if futures:
                    ready,_=wait(futures,return_when=FIRST_COMPLETED)
                    for future in ready:
                        del futures[future]
                        result=future.result();new_count+=not bool(result.get('error'));accept(result)
    results=[completed[row['panel_id']] for row in rows]
    # Dependents of a failed derivation stay explicitly pending, never silently ready.
    blocked=set(failures)
    while True:
        more={p['panel_id'] for p in index['panels'] if set(p['depends_on'])&blocked}-blocked
        if not more: break
        blocked.update(more)
    for row in results:
        if row['panel_id'] in blocked: row['pending']=True
    observations={fingerprint(o):o for o in [*index.get('common_observations',[]),*[o for p in index['panels'] for o in p['observations']]]}
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
    events=[]
    for row in results:
        if row.get('compile_timing'):
            events.extend([(row['compile_timing']['started_monotonic'],1),(row['compile_timing']['completed_monotonic'],-1)])
    active=peak=0
    for _,delta in sorted(events):active+=delta;peak=max(peak,active)
    receipt={**index,'panels':results,'impact':impact,'previous_derivation':resolution,'source_file':{'path':str(Path(source_path).resolve()),'sha256':source_hash},
             'status':'DRAFT_PARTIAL' if blocked else 'DRAFT_MATERIALIZED_NOT_APPROVED',
             'pending_panel_ids':[pid for pid in source['panel_ids'] if pid in blocked],'errors':failures,
             'metrics':{'compiled_panels':new_count,'reused_panels':reuse_count,'elapsed_seconds':time.monotonic()-started,'peak_active_compiles':peak,'peak_pending_compiles':peak_pending,'first_ready_seconds':first_ready,'published_panels':len(published)},
             'next':'核对新镜头与实际输入，更新准确引用，按原候选/语义/批准入口完成实际审查；不要因DRAFT成功跳过门禁'}
    write_new(output/'派生记录.json',receipt)
    if Path(source_path).resolve().is_relative_to(Path(source['run_root']).resolve()):
        try:remember_receipt(source_path,output/'派生记录.json')
        except OSError as exc:receipt['reuse_index_warning']=str(exc)
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
