#!/usr/bin/env python3
"""Short first-use prepare/receive entry. Does not approve or generate images."""
from pathlib import Path
from platform_io import book_directory
from runtime_environment import require_ready
import argparse,copy,datetime,json,subprocess,sys,uuid,zipfile
from usage_config import read_config,memory_source
from runtime_snapshot import create
from builtin_memory import resolve
from handoff_zip import extract,rehearse,read,write,check_delivery_archive,check_delivery_directory,INDEX
from handoff_delivery import bind
from task_context import fresh, validate as validate_task

BASE=Path(__file__).resolve().parents[1]

def start_clock(run, role, limit, session, *, started=None, wall_delivery=False):
    from runtime_clock import initialize_context
    if limit is None:
        return {'runtime_execution_context': initialize_context(run, role, limit)}
    from runtime_clock import initialize, event, bind, status
    from runtime_clock_context import resolve
    # Wall-clock delivery does not depend on optional pause hooks.
    # Keep real host binding when available; never invent a session receipt.
    try:context=resolve(explicit_session=session)
    except ValueError as exc:
        if not wall_delivery: raise
        if 'CLOCK_CONTEXT_UNAVAILABLE' not in str(exc) and 'CLOCK_CONTEXT_STALE' not in str(exc):raise
        context=None
    directory = Path(run)/'00_任务协调'
    initialize(directory, role, limit, hard_deadline=True, at=started, delivery_deadline=wall_delivery)
    binding=bind(directory,context['session_id'],identity_source='host:PreToolUse+CODEX_THREAD_ID') if context else {'session_bound':False,'automatic_pause_verified':False,'timing':'wall_clock_includes_waits'}
    event(directory, 'start', 'initial-start', at=started)
    reference = initialize_context(run, role, limit, hard_deadline=True)
    result = {'clock_directory': str(directory), 'runtime_clock': status(directory)}
    result['runtime_execution_context'] = reference
    result['clock_binding']=binding
    if result['runtime_clock']['remaining_seconds'] is None or result['runtime_clock']['remaining_seconds']<=0:
        raise ValueError('RUNTIME_CLOCK_LIMIT_REACHED: initialization consumed the available active budget')
    return result

def start_display(directory,role,states,*,config=None,rehearsal=None):
    try:
        from production_progress import initialize,observe_runtime,refresh
        initialize(directory,role,states,config=config)
        if rehearsal is not None:
            for path in states: observe_runtime(directory,path,'rehearsal',rehearsal)
            refresh(directory,activity='接包校验与本地运行已建立',next_action='处理准确HOLD或开始获批生产')
        from task_coordination import initialize as initialize_coordination
        coordination = Path(directory).parent/'00_任务协调'
        initialize_coordination(coordination, directory)
        return {'progress_directory':str(directory), 'coordination_directory':str(coordination)}
    except (OSError,ValueError,KeyError,TypeError) as exc:
        return {'progress_warning':str(exc),'progress_recovery':'重建派生显示目录；原生产判定未改变'}

def episodes(values):
    import re
    out=[]
    for v in values:
        match=re.fullmatch(r'E(\d+)[–-]E?(\d+)',v)
        if match:
            a,b=map(int,match.groups())
            if b<a or b-a>200:raise ValueError('话号范围无效或过大')
            out.extend(f'E{i:03d}' for i in range(a,b+1))
        elif re.fullmatch(r'E\d{3,}',v):out.append(v)
        else:raise ValueError('使用准确话号，例如E026–E030')
    if not out or len(set(out))!=len(out):raise ValueError('话号缺失或重复')
    return out

def prepare(project,book,ids,*,script=None,assets=None,output=None,workers=None,request_source=None,reuse_selection=None,runtime_limit_seconds=14400,clock_session_id=None,delivery_mode='allow_parts',max_file_bytes=900000000,image_review_profile='light_story_review_v1',wall_delivery=False):
    if image_review_profile!='light_story_review_v1':raise ValueError('RETIRED_REVIEW_MODE: new production uses light_story_review_v1')
    from runtime_clock import instant
    started=instant()
    project=Path(project).resolve();ids=episodes(ids)
    if not project.is_dir():raise ValueError('项目目录不存在')
    require_ready(probe_root=project)
    import hashlib
    profile_dir=project/'.comic/books';profile=profile_dir/(hashlib.sha256(book.encode()).hexdigest()[:16]+'.json')
    old=read(profile) if profile.exists() else None
    if old and old['book']!=book:raise ValueError('本书配置归属错误')
    inputs={'script_path':str(Path(script).resolve()) if script else (old or {}).get('script_path'),
            'asset_root':str(Path(assets).resolve()) if assets else (old or {}).get('asset_root')}
    for key,isdir in [('script_path',False),('asset_root',True)]:
        p=Path(inputs[key] or '')
        if not inputs[key] or not p.is_absolute() or not (p.is_dir() if isdir else p.is_file()):raise ValueError('首次使用缺少有效'+key)
        if old and old[key]!=inputs[key]:raise ValueError('已有书配置路径不同；先明确更新本书配置，不自动覆盖')
    task=fresh(book,ids,request_source)
    if reuse_selection is not None:
        task.update(origin='reuse_selected',imports=reuse_selection)
        validate_task(task)
    config=read(BASE/'assets/templates/默认使用配置.json');config.update(production={'book':book,'episodes':ids},inputs=inputs)
    if workers is not None:
        if type(workers) is not int or workers<1:raise ValueError('执行agent数量须为正整数')
        config['generation']['episode_workers']=workers
    # Validate all inputs and bundled rules before creating a project run.
    effective=resolve();config['inputs']['memory_root']=effective['root'];config['memory'].update(source='builtin',index_sha256=effective['index_sha256'])
    output_base=Path(output).resolve() if output else project/'条漫输出'/book_directory(book)/('_'.join((ids[0],ids[-1])))
    stamp=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')
    run=output_base/('RV_'+stamp+'_'+uuid.uuid4().hex[:6]);run.mkdir(parents=True)
    clock = start_clock(run, 'preparation', runtime_limit_seconds, clock_session_id, started=started, wall_delivery=wall_delivery)
    task_path=run/'任务来源.json';write(task_path,task)
    cfg=run/'本次配置.json';write(cfg,config);read_config(cfg)
    snap=create(run/'00_总控/运行版本',memory_source=memory_source(config))
    for eid in ids:
        cmd=[sys.executable, '-X', 'utf8','-B',str(Path(snap['path']).parent/'skills/vertical-comic-preproduction/scripts/init_preproduction.py'),'--book',book,'--episode',eid,'--config',str(cfg),'--runtime-snapshot',snap['path'],'--task-context',str(task_path),'--execution-context',clock['runtime_execution_context']['path'],'--output',str(run/eid),'--backend','codex_builtin_imagegen']
        if image_review_profile != 'full': cmd.extend(['--image-review-profile',image_review_profile,'--speed-policy','bounded_stage_fallback_v1'])
        proc=subprocess.run(cmd,capture_output=True,text=True, encoding='utf-8')
        if proc.returncode:raise ValueError('初始化失败，保留诊断运行目录:'+eid+':'+proc.stderr[-1000:])
    if old is None:
        profile_dir.mkdir(parents=True,exist_ok=True);write(profile,{'policy':'comic_book_profile_v1','book':book,**inputs})
    result={'status':'INITIALIZED_NOT_PRODUCTION_APPROVAL','book':book,'episode_ids':ids,'task_context':task,'run_root':str(run),'config':str(cfg),'profile':str(profile),'image_calls':0,'next':'仅审本次脚本与资产需求；不查无关旧生产账。核对实际格数/格序并按A及B/包审查；模板没有批准'}
    from delivery_contract import initialize as initialize_delivery
    result['delivery_identity']=initialize_delivery(run,'preparation',[run/e/'00_输入审计/生产流程.json' for e in ids],
        package_mode=delivery_mode,max_file_bytes=max_file_bytes,task_id=task['task_id'])
    result.update(start_display(run/'00_显示进度','preparation',[run/e/'00_输入审计/生产流程.json' for e in ids],config=config.get('progress')))
    result.update(clock)
    from deadline_delivery import start_watch
    result['deadline_delivery']=start_watch(result['delivery_identity']['path']) if runtime_limit_seconds is not None and wall_delivery else {'status':'ACTIVE_TIME_SCHEDULE' if runtime_limit_seconds is not None else 'LEGACY_UNTIMED'}
    write(run/'启动摘要.json',result);return result

def inspect_received_runtime(run_root, run_index, report_dir):
    from handoff_zip import inside
    local_index=read(run_index);entrypoints=[];compatibility=[]
    from runtime_snapshot import create as freeze_executor
    from runtime_import import resume_import
    executor_dir=Path(run_root).parent/'00_执行器'
    if not executor_dir.exists(): freeze_executor(executor_dir)
    executor_manifest={'path':str((executor_dir/'manifest.json').resolve()),
                       'sha256':__import__('hashlib').sha256((executor_dir/'manifest.json').read_bytes()).hexdigest()}
    folder=Path(report_dir);folder.mkdir(parents=True,exist_ok=False)
    for episode in local_index['episodes']:
        state_path=inside(Path(run_root),episode['state']);state=read(state_path)
        try:
            imported=resume_import(state_path,executor_manifest)
            state=read(state_path)
        except (OSError,ValueError,KeyError) as exc:
            compatibility.append({'episode_id':episode['episode_id'],'status':'HOLD','error':str(exc)})
            continue
        from runtime_import import verify_binding
        pinned=verify_binding(state,state_path.parent.parent)[0]['executor_manifest']
        runtime_manifest=Path(pinned['path'])
        scripts=runtime_manifest.parent/'skills/vertical-comic-preproduction/scripts'
        entry={'episode_id':episode['episode_id'],'state':str(state_path),
               'frozen_runtime_manifest':str(runtime_manifest),'frozen_scripts':str(scripts),
               'runtime_script':str(scripts/'production_runtime.py'),'execution_mode':state.get('execution_mode'),
               'optimization_policy':state.get('optimization_policy'),
               'generation_host':str(scripts/'generation_host.py'),
               'production_actions':['serve','prepare-inputs','ready-inputs','claim-and-register','save-return'],
               'dispatch_protocol':'prepared_dispatch_v1'}
        entrypoints.append(entry)
        proc=subprocess.run([sys.executable,'-X','utf8','-B',entry['generation_host'],'inspect-runtime','--state',entry['state']],
            capture_output=True,text=True,encoding='utf-8')
        (folder/(episode['episode_id']+'_stdout.json')).write_text(proc.stdout,encoding='utf-8')
        (folder/(episode['episode_id']+'_stderr.txt')).write_text(proc.stderr,encoding='utf-8')
        try:item=json.loads(proc.stdout)
        except ValueError:item={'status':'HOLD','error':'INVALID_HOST_RESULT: see preserved stdout/stderr'}
        if proc.returncode:item['status']='HOLD'
        compatibility.append({'episode_id':episode['episode_id'],**item})
    return entrypoints,compatibility


from handoff_zip import reception_cache

@reception_cache
def receive(zip_path=None,*,package_root=None,output=None,runtime_limit_seconds=14400,clock_session_id=None,_started=None,audit_timeout=900, eager_audit=False, wall_delivery=False):
    from runtime_clock import instant
    started=_started or instant()
    if (zip_path is None)==(package_root is None):raise ValueError('接包提供ZIP或已解压包根目录其中一个')
    require_ready()
    if zip_path is not None:
        from handoff_transport import identify, restore
        if identify(zip_path):
            import tempfile
            base=Path(output).resolve() if output else Path(zip_path).resolve().parent/'接包生产'
            base.mkdir(parents=True,exist_ok=True)
            holder=Path(tempfile.mkdtemp(prefix='收到运输原件_',dir=base))
            try:
                restored=restore(zip_path,holder/'完整原件')
            except Exception:
                import shutil
                shutil.rmtree(holder)
                raise
            return receive(package_root=restored['root'],output=base,runtime_limit_seconds=runtime_limit_seconds,clock_session_id=clock_session_id,_started=started,audit_timeout=audit_timeout,eager_audit=eager_audit,wall_delivery=wall_delivery)
    if package_root is not None:
        checked=check_delivery_directory(package_root);originals=Path(checked['root']);archive=None
        base=Path(output).resolve() if output else originals.parent/'接包生产'
        if base==originals or base.is_relative_to(originals):raise ValueError('接包输出须在收到原件目录之外')
    else:
        archive=Path(zip_path).resolve();side=Path(str(archive)+'.sha256')
        checked=check_delivery_archive(archive,checksum_file=side if side.is_file() else None)
        checksum=side if checked['format']=='legacy_with_checksum' else None
        checked={**checked,'source_type':'zip','archive_crc':'PASS'}
        base=Path(output).resolve() if output else archive.parent/'接包生产'
    target=base/('RV_'+uuid.uuid4().hex[:12]);target.mkdir(parents=True)
    clock = start_clock(target, 'production', runtime_limit_seconds, clock_session_id, started=started,wall_delivery=wall_delivery)
    if archive is not None:originals=Path(extract(archive,target/'收到原件',checksum_file=checksum)['root'])
    write(target/'接收校验.json',checked)
    bound=bind(originals,target/'本地运行',execution_context=clock['runtime_execution_context'])
    write(target/'接包恢复索引.json',{'policy':'receiver_resume_v1','package_id':checked.get('package_id'),
        'originals_root':str(originals),'archive':str(archive) if archive else None,
        'run_root':bound['run_root'],'run_index':bound['run_index'],
        'run_index_sha256':__import__('handoff_zip').sha(bound['run_index']),
        'inventory_sha256':__import__('handoff_zip').sha(originals/'ZIP文件清单.json'),'audit_timeout':audit_timeout,
        'input_audit_policy':'EAGER' if eager_audit else 'ON_COMPILE'})
    entrypoints,compatibility=inspect_received_runtime(bound['run_root'],bound['run_index'],target/'接包兼容检查')
    if any(item['status']!='RUNTIME_COMPATIBLE' for item in compatibility):
        result={'status':'HOLD','results':[{'episode_id':item['episode_id'],'status':'HOLD',
                'reason_code':'PROTOCOL_HOLD','errors':[item.get('error','接包协议不兼容，未启动耗时输入审计')]} for item in compatibility]}
    elif eager_audit:
        result=rehearse(archive,originals,bound['run_root'],bound['run_index'],target/'接包预检',
                        timeout=audit_timeout,budget_path=target)
    else:
        # The immutable package was checked above. Each actual compile still
        # runs its frozen input/approval checks; no second full-batch barrier.
        result={'status':'RELEASE_CANDIDATE','results':[], 'input_audit':'DEFERRED_TO_COMPILE'}
    local_index = read(bound['run_index'])
    from delivery_contract import initialize as initialize_delivery
    delivery_identity=initialize_delivery(target,'production',[Path(bound['run_root'])/e['state'] for e in local_index['episodes']],
        package_mode='single_zip')
    from deadline_delivery import start_watch
    deadline_delivery=start_watch(delivery_identity['path']) if runtime_limit_seconds is not None and wall_delivery else {'status':'ACTIVE_TIME_SCHEDULE' if runtime_limit_seconds is not None else 'LEGACY_UNTIMED'}
    progress = start_display(target/'00_显示进度','production',[Path(bound['run_root'])/e['state'] for e in local_index['episodes']],rehearsal=result)
    # A received run is already configured by its verified package, not a new book.
    package_index=read(originals/INDEX)
    return {**progress,**clock,'runtime_compatibility':compatibility,'status':'READY_FOR_PRODUCTION_ROUTING' if result['status']=='RELEASE_CANDIDATE' else 'HOLD',
            'delivery_identity':delivery_identity,'deadline_delivery':deadline_delivery,
            'input_audit':result.get('input_audit','EXECUTED'),
            'input_mode':'package_only_production','external_inputs_required':False,'book_profile_required':False,
            'package_id':package_index['package_id'],'book_id':package_index['book_id'],
            'episode_ids':[e['episode_id'] for e in local_index['episodes']],
            'production_window_policy':package_index.get('production_window_policy'),
            'production_human_review_nodes':package_index.get('production_human_review_nodes'),
            'run_root':str(target),'bound_run_root':bound['run_root'],'run_index':bound['run_index'],
            'production_entrypoints':entrypoints,'originals_root':str(originals),'reception':checked,
            'episode_results':result['results'],'dispatch_authorized':False,'image_calls':0,
            'next':('使用production_entrypoints中的本地状态和统一固定执行器，按包内执行模式、生产窗口、有效授权及真实依赖生产。无需填写外部脚本、资产或本书配置；复用未变输入审查，不重新进行前期设计。' if result['status']=='RELEASE_CANDIDATE' else '按episode_results修复准确HOLD并继续独立工作；未放行范围不生图。不要求重新配置外部脚本、资产或本书profile。')}


def receive_resume(run_root, *, audit_timeout=900):
    """Continue the original reception without binding, clock creation or state writes."""
    target=Path(run_root).resolve();receipt=read(target/'接包恢复索引.json')
    if receipt.get('policy')!='receiver_resume_v1':raise ValueError('缺少原接包恢复索引，不推测或重建运行')
    local_root=Path(receipt['run_root']).resolve();index_path=Path(receipt['run_index']).resolve()
    if not local_root.is_relative_to(target) or not index_path.is_relative_to(local_root):raise ValueError('恢复运行路径越界')
    from handoff_zip import sha,inside
    if sha(index_path)!=receipt.get('run_index_sha256'):raise ValueError('恢复索引变化')
    index=read(index_path);states=[inside(local_root,e['state']) for e in index['episodes']]
    originals=Path(receipt['originals_root']);checked=check_delivery_directory(originals)
    if sha(originals/'ZIP文件清单.json')!=receipt.get('inventory_sha256'):raise ValueError('恢复原件清单变化')
    if checked.get('package_id')!=receipt.get('package_id'):raise ValueError('恢复原件身份变化')
    entries,compatibility=inspect_received_runtime(local_root,index_path,target/('接包兼容检查_恢复_'+uuid.uuid4().hex[:10]))
    if any(item['status']!='RUNTIME_COMPATIBLE' for item in compatibility):
        return {'status':'HOLD','runtime_compatibility':compatibility,'run_root':str(target),'image_calls':0}
    started=any(read(p).get('parallel_context') or any(r['status'] not in {'PENDING','REPAIR_AUTHORIZED'} for r in read(p)['panels']) for p in states)
    if started:
        return {'status':'CONTINUE_ORIGINAL_PRODUCTION','run_root':str(target),'production_entrypoints':entries,
                'dispatch_authorized':False,'image_calls':0,
                'next':'已有许可/调用历史；沿原冻结生产门禁继续，不能重新bind或把接收审计当新提交许可。未完成接收审计需静止范围后单独重验。'}
    from runtime_clock import require_running
    require_running(target)
    if receipt.get('input_audit_policy')=='ON_COMPILE':
        return {'status':'READY_FOR_PRODUCTION_ROUTING','run_root':str(target),
            'production_entrypoints':entries,'dispatch_authorized':False,'image_calls':0,'rebound':False,
            'input_audit':'DEFERRED_TO_COMPILE'}
    reports=sorted(target.glob('接包预检*/演练报告.json'),key=lambda p:p.stat().st_mtime_ns)
    prior=reports[-1] if reports else None
    archive=receipt.get('archive')
    if archive and not Path(archive).is_file():archive=None
    result=rehearse(archive,originals,local_root,index_path,target/('接包预检_恢复_'+uuid.uuid4().hex[:10]),
                    timeout=audit_timeout,budget_path=target,resume_report=prior)
    return {'status':'READY_FOR_PRODUCTION_ROUTING' if result['status']=='RELEASE_CANDIDATE' else 'HOLD',
            'run_root':str(target),'episode_results':result['results'],'production_entrypoints':entries,
            'dispatch_authorized':False,'image_calls':0,'rebound':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('prepare');p.add_argument('--project',required=True);p.add_argument('--book',required=True);p.add_argument('--episodes',nargs='+',required=True);p.add_argument('--script');p.add_argument('--assets');p.add_argument('--output');p.add_argument('--workers',type=int)
    p.add_argument('--request-source',help='真实用户原话及source_locator的JSON；程序调用不冒充批准')
    p.add_argument('--reuse-selection',help='用户明确选中的旧成果来源、准确格号与证据引用JSON数组；不自动发现旧任务')
    p=sub.add_parser('receive');source=p.add_mutually_exclusive_group(required=True);source.add_argument('--zip');source.add_argument('--package-root',help='已解压正式交接包根目录，含ZIP文件清单.json');p.add_argument('--output');p.add_argument('--audit-timeout',type=int,default=900);p.add_argument('--eager-audit',action='store_true',help='显式诊断才重复全包审计；默认逐格编译时校验')
    p=sub.add_parser('receive-resume');p.add_argument('--run-root',required=True);p.add_argument('--audit-timeout',type=int,default=900)
    preparation=sub.choices['prepare']
    preparation.add_argument('--image-review-profile', choices=('light_story_review_v1',), default='light_story_review_v1', help='新制作默认单次轻审核，仅严重剧情问题最多返修一轮')
    preparation.add_argument('--delivery-mode',choices=['single_zip','allow_parts'],default='allow_parts',help='默认单包优先、超限自动分包；仅用户明确限制单文件时选择single_zip')
    preparation.add_argument('--max-file-bytes',type=int,default=900000000,help='微信单文件上限，最大900000000字节')
    for command in sub.choices.values():
        command.add_argument('--clock-mode',choices=('active','wall'),default='active',help='默认暂停不计时；仅明确自然时限时选择wall，恢复保留原时钟')
        command.add_argument('--runtime-limit-seconds', type=int, default=14400, help='新任务默认四小时自然时间交包；等待计时，预留30分钟收尾；只能缩短，不能超过14400秒')
        command.add_argument('--clock-session-id', help='经核实的宿主session_id；需已信任Interrupt Hook')
    a=parser.parse_args()
    try:
        if a.action=='receive-resume':
            result=receive_resume(a.run_root,audit_timeout=a.audit_timeout)
            print(json.dumps(result,ensure_ascii=False));return int(result['status']=='HOLD')
        result=prepare(a.project,a.book,a.episodes,script=a.script,assets=a.assets,output=a.output,workers=a.workers,request_source=read(a.request_source) if a.request_source else None,reuse_selection=read(a.reuse_selection) if a.reuse_selection else None,runtime_limit_seconds=a.runtime_limit_seconds,clock_session_id=a.clock_session_id,delivery_mode=a.delivery_mode,max_file_bytes=a.max_file_bytes,image_review_profile=a.image_review_profile,wall_delivery=a.clock_mode=='wall') if a.action=='prepare' else receive(a.zip,package_root=a.package_root,output=a.output,runtime_limit_seconds=a.runtime_limit_seconds,clock_session_id=a.clock_session_id,audit_timeout=a.audit_timeout,eager_audit=a.eager_audit,wall_delivery=a.clock_mode=='wall')
        print(json.dumps(result,ensure_ascii=False));return int(result['status']=='HOLD')
    except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile) as e:print(json.dumps({'status':'HOLD','error':str(e)},ensure_ascii=False));return 1
if __name__=='__main__':
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
