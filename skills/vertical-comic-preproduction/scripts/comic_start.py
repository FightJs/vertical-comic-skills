#!/usr/bin/env python3
"""Short first-use prepare/receive entry. Does not approve or generate images."""
from pathlib import Path
import argparse,copy,datetime,json,subprocess,sys,uuid
from usage_config import read_config,memory_source
from runtime_snapshot import create
from builtin_memory import resolve
from handoff_zip import extract,rehearse,read,write,check_delivery_archive
from handoff_delivery import bind

BASE=Path(__file__).resolve().parents[1]

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

def prepare(project,book,ids,*,script=None,assets=None,output=None,workers=None):
    project=Path(project).resolve();ids=episodes(ids)
    if not project.is_dir():raise ValueError('项目目录不存在')
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
    config=read(BASE/'assets/templates/默认使用配置.json');config.update(production={'book':book,'episodes':ids},inputs=inputs)
    if workers is not None:
        if type(workers) is not int or workers<1:raise ValueError('执行agent数量须为正整数')
        config['generation']['episode_workers']=workers
    # Validate all inputs and bundled rules before creating a project run.
    effective=resolve();config['inputs']['memory_root']=effective['root'];config['memory'].update(source='builtin',index_sha256=effective['index_sha256'])
    output_base=Path(output).resolve() if output else project/'条漫输出'/book.replace('/','_')/('_'.join((ids[0],ids[-1])))
    stamp=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')
    run=output_base/('RV_'+stamp+'_'+uuid.uuid4().hex[:6]);run.mkdir(parents=True)
    cfg=run/'本次配置.json';write(cfg,config);read_config(cfg)
    snap=create(run/'00_总控/运行版本',memory_source=memory_source(config))
    for eid in ids:
        cmd=[sys.executable,'-B',str(Path(snap['path']).parent/'skills/vertical-comic-preproduction/scripts/init_preproduction.py'),'--book',book,'--episode',eid,'--config',str(cfg),'--runtime-snapshot',snap['path'],'--output',str(run/eid),'--backend','codex_builtin_imagegen']
        proc=subprocess.run(cmd,capture_output=True,text=True)
        if proc.returncode:raise ValueError('初始化失败，保留诊断运行目录:'+eid+':'+proc.stderr[-1000:])
    if old is None:
        profile_dir.mkdir(parents=True,exist_ok=True);write(profile,{'policy':'comic_book_profile_v1','book':book,**inputs})
    result={'status':'INITIALIZED_NOT_PRODUCTION_APPROVAL','book':book,'episode_ids':ids,'run_root':str(run),'config':str(cfg),'profile':str(profile),'image_calls':0,'next':'核对源稿实际格数/格序，再按A及B/包审查推进；模板没有批准'}
    write(run/'启动摘要.json',result);return result

def receive(zip_path,*,output=None):
    archive=Path(zip_path).resolve();side=Path(str(archive)+'.sha256')
    checked=check_delivery_archive(archive,checksum_file=side if side.is_file() else None)
    checksum=side if checked['format']=='legacy_with_checksum' else None
    base=Path(output).resolve() if output else archive.parent/'接包生产'
    target=base/('RV_'+uuid.uuid4().hex[:12]);target.mkdir(parents=True)
    received=extract(archive,target/'收到原件',checksum_file=checksum)
    bound=bind(received['root'],target/'本地运行')
    result=rehearse(archive,received['root'],bound['run_root'],bound['run_index'],target/'接包预检')
    return {'status':'READY_FOR_PRODUCTION_ROUTING' if result['status']=='RELEASE_CANDIDATE' else 'HOLD','run_root':str(target),'episode_results':result['results'],'image_calls':0,'next':'通过后仍按H001/高风险/D审核节点及真实许可生产'}

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('prepare');p.add_argument('--project',required=True);p.add_argument('--book',required=True);p.add_argument('--episodes',nargs='+',required=True);p.add_argument('--script');p.add_argument('--assets');p.add_argument('--output');p.add_argument('--workers',type=int)
    p=sub.add_parser('receive');p.add_argument('--zip',required=True);p.add_argument('--output')
    a=parser.parse_args()
    try:
        result=prepare(a.project,a.book,a.episodes,script=a.script,assets=a.assets,output=a.output,workers=a.workers) if a.action=='prepare' else receive(a.zip,output=a.output)
        print(json.dumps(result,ensure_ascii=False));return int(result['status']=='HOLD')
    except (OSError,ValueError,KeyError,TypeError) as e:print(json.dumps({'status':'HOLD','error':str(e)},ensure_ascii=False));return 1
if __name__=='__main__':raise SystemExit(main())
