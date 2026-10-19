#!/usr/bin/env python3
"""ZIP handoff integrity, real relocated frozen-gate rehearsal and scoped release.

Does not bind paths, rewrite approvals, reset attempts, allocate live permits or
call an image service. Local runs must first be prepared using the documented
binding procedure. A passing hash manifest alone never means production-ready.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import zipfile

POLICY = 'rehearsed_zip_handoff_v1'
INDEX = '交接验收索引.json'
INVENTORY = 'ZIP文件清单.json'
REQUIRED = ('交接说明.md', '接包生产执行要求.md', INDEX)
KINDS = {'READY_H001', 'PREPARED_H002', 'WAIT_DEPENDENCY', 'HOLD', 'REUSE'}


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path,value):
    with Path(path).open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')


def relative(value):
    if not isinstance(value,str) or not value or '\\' in value or '\x00' in value:
        raise ValueError('路径须为明确的包内POSIX相对路径')
    p=PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or ':' in p.parts[0] or str(p)!=value:
        raise ValueError('路径越界或非规范相对路径:'+value)
    return p


def inside(root,value):
    relative(value);root=Path(root).resolve();p=root/value
    if any(q.is_symlink() for q in [p,*p.parents] if q.is_relative_to(root)) or not p.resolve().is_relative_to(root):
        raise ValueError('拒绝符号链接或路径越界:'+value)
    return p


def reference(root,ref):
    if not isinstance(ref,dict):raise ValueError('缺文件来源引用')
    p=inside(root,ref.get('path'))
    if not p.is_file() or sha(p)!=ref.get('sha256'):raise ValueError('文件缺失或哈希失配:'+str(p))
    return p


def files(root):
    rows=[]
    for p in sorted(Path(root).rglob('*')):
        if p.is_symlink():raise ValueError('包内不得有符号链接:'+str(p))
        if p.is_file() and p.name not in {'.DS_Store'} and '__MACOSX' not in p.parts:
            rel=p.relative_to(root).as_posix();relative(rel)
            if rel!=INVENTORY:rows.append({'path':rel,'sha256':sha(p),'bytes':p.stat().st_size})
    return sorted(rows,key=lambda r:r['path'])


def audit_index(root):
    root=Path(root);data=read(root/INDEX)
    if data.get('policy')!=POLICY or not data.get('package_id') or not data.get('book_id'):
        raise ValueError('缺交接验收索引策略、包ID或书ID')
    for name in REQUIRED:
        if not (root/name).is_file() or not (root/name).read_text(encoding='utf-8-sig').strip():raise ValueError('缺交接入口或内容为空:'+name)
    episodes=data.get('episodes')
    if not isinstance(episodes,list) or not episodes:raise ValueError('缺准确话号与逐格交接范围')
    seen=set()
    for episode in episodes:
        eid=episode.get('episode_id');ids=episode.get('panel_ids');halves=episode.get('halves',{})
        if not isinstance(eid,str) or eid in seen:raise ValueError('话号缺失/重复')
        seen.add(eid)
        if not eid or len(relative(eid).parts)!=1:raise ValueError('话号须为安全单层名称')
        if not isinstance(ids,list) or not ids or any(not isinstance(p,str) or not p for p in ids) or len(set(ids))!=len(ids):raise ValueError(eid+':源格序缺失/重复')
        cut=(len(ids)+1)//2
        if halves!={'H001':ids[:cut],'H002':ids[cut:]}:raise ValueError(eid+':半话不符合准确源序ceil(N/2)')
        for key in ('source_snapshot','runtime_manifest','approval_evidence','path_binding_plan'):
            reference(root,episode.get(key))
        source=read(reference(root,episode['source_snapshot']))
        source_ids=source.get('panel_ids') or (source.get('id_mapping') or {}).get('panel_ids')
        if source_ids!=ids:raise ValueError(eid+':源快照格序与交接不一致')
        panels=episode.get('panels')
        if not isinstance(panels,list) or [p.get('panel_id') for p in panels]!=ids:raise ValueError(eid+':逐格准备/历史清单不完整')
        for row in panels:
            pid=row['panel_id'];kind=row.get('classification')
            if kind not in KINDS:raise ValueError(pid+':未知交接状态')
            if kind=='READY_H001' and pid not in halves['H001']:raise ValueError(pid+':不能提前放行H002')
            if kind=='PREPARED_H002' and pid not in halves['H002']:raise ValueError(pid+':H002准备范围错误')
            if kind in {'WAIT_DEPENDENCY','HOLD'}:
                blockers=row.get('blockers')
                if not isinstance(blockers,list) or not blockers or any(not isinstance(b,dict) or not all(b.get(k) for k in ('reason','owner','resolution')) for b in blockers):
                    raise ValueError(pid+':阻塞须列具体原因、责任方和解除条件')
            h=row.get('history',{})
            if h.get('status') not in {'NEVER_SUBMITTED','RECONCILED','UNRESOLVED'} or not h.get('evidence'):
                raise ValueError(pid+':缺完整历史核对及来源，PENDING不证明零调用')
            for ref in h['evidence']:reference(root,ref)
            if not h.get('reviewer') or not h.get('conclusion'):raise ValueError(pid+':历史核对须有核对者和具体结论')
            attempts=h.get('attempts')
            if not isinstance(attempts,list):raise ValueError(pid+':缺逐次调用清单，确无调用用空数组并附证')
            if len({a.get('attempt_id') for a in attempts})!=len(attempts) or any(not a.get('attempt_id') for a in attempts):raise ValueError(pid+':调用ID缺失或重复')
            used=0;unknown=False
            for a in attempts:
                if a.get('status') not in {'COMPLETED','FAILED','UNKNOWN'} or not a.get('evidence'):raise ValueError(pid+':历史调用状态或原始证据缺失')
                for ref in a['evidence']:reference(root,ref)
                if a.get('kind') not in {'initial','auto_correction','manual_authorized'}:raise ValueError(pid+':未知调用类型')
                if a['kind']=='manual_authorized':reference(root,a.get('authorization'))
                used+=a.get('kind')=='auto_correction';unknown|=a['status']=='UNKNOWN'
                if a['status']=='COMPLETED':
                    reference(root,a.get('output'));reference(root,a.get('qa'))
            if used>1 or h.get('auto_corrections_used')!=used or h.get('remaining_auto_corrections')!=1-used:
                raise ValueError(pid+':自动返修预算失配/重置，人工追加须另列原授权')
            if h['status']=='NEVER_SUBMITTED' and attempts:raise ValueError(pid+':有历史调用却声明从未提交')
            if (unknown or h['status']=='UNRESOLVED') and kind not in {'HOLD','WAIT_DEPENDENCY'}:
                raise ValueError(pid+':未知历史不得伪记就绪')
            if kind=='REUSE':reference(root,row.get('accepted_image'));reference(root,row.get('accepted_qa'));reference(root,row.get('acceptance'))
    return data


def archive_members(z):
    seen=set();root=None;count=0
    for info in z.infolist():
        name=info.filename.rstrip('/')
        if not name:raise ValueError('空ZIP成员')
        p=relative(name)
        if name.casefold() in seen:raise ValueError('ZIP路径重复或大小写冲突:'+name)
        seen.add(name.casefold())
        if stat.S_ISLNK(info.external_attr>>16):raise ValueError('ZIP包含符号链接')
        if root is None:root=p.parts[0]
        if p.parts[0]!=root or (len(p.parts)<2 and not info.is_dir()):raise ValueError('ZIP须单一顶层目录')
        if not info.is_dir():count+=1
    if not count:raise ValueError('空ZIP')
    return root


def zip_inventory(z):
    top=archive_members(z);manifest=read_zip_json(z,top+'/'+INVENTORY)
    if manifest.get('policy')!=POLICY:raise ValueError('ZIP文件清单策略错误')
    rows=manifest.get('files');actual={i.filename[len(top)+1:] for i in z.infolist() if not i.is_dir() and i.filename!=top+'/'+INVENTORY}
    if not isinstance(rows,list) or len({r.get('path') for r in rows})!=len(rows) or {r.get('path') for r in rows}!=actual:raise ValueError('ZIP文件清单缺项/重复')
    for row in rows:
        relative(row['path']);h=hashlib.sha256();n=0
        with z.open(top+'/'+row['path']) as f:
            for b in iter(lambda:f.read(1024*1024),b''):h.update(b);n+=len(b)
        if h.hexdigest()!=row.get('sha256') or n!=row.get('bytes'):raise ValueError('ZIP成员哈希/长度失配:'+row['path'])
    return top,manifest


def read_zip_json(z,name):return json.loads(z.read(name).decode('utf-8-sig'))


def pack(root,output):
    root=Path(root).resolve();output=Path(output).resolve()
    if output.suffix.lower()!='.zip' or output.exists() or output.is_relative_to(root):raise ValueError('输出须为包外不存在的ZIP，不覆盖原包')
    data=audit_index(root);rows=files(root);manifest={'policy':POLICY,'package_id':data['package_id'],'files':rows}
    output.parent.mkdir(parents=True,exist_ok=True)
    try:
        with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=3,allowZip64=True) as z:
            for row in rows:
                p=root/row['path'];compression=zipfile.ZIP_STORED if p.suffix.lower() in {'.png','.jpg','.jpeg','.webp','.zip'} else zipfile.ZIP_DEFLATED
                z.write(p,root.name+'/'+row['path'],compress_type=compression)
            z.writestr(root.name+'/'+INVENTORY,json.dumps(manifest,ensure_ascii=False,indent=2))
        if files(root)!=rows:raise ValueError('打包过程中源文件变化')
        with zipfile.ZipFile(output) as z:zip_inventory(z)
    except Exception:
        output.unlink(missing_ok=True);raise
    return {'status':'CANDIDATE_ZIP_NOT_RELEASED','zip':str(output),'sha256':sha(output),'file_count':len(rows)+1}


def check_delivery_archive(zip_path,checksum_file=None):
    """Validate a self-contained release before creating the receiver's run.

    Internal hashes detect damage, not publisher identity. Legacy archives still
    require their detached checksum. Production approval is checked by rehearsal.
    """
    if not Path(zip_path).is_file():raise ValueError('正式ZIP不存在')
    with zipfile.ZipFile(zip_path) as z:
        top,manifest=zip_inventory(z)
        if manifest.get('container_policy')!='self_contained_handoff_v1':
            if checksum_file is None:raise ValueError('旧版正式ZIP需要同名.zip.sha256；候选包不能直接接包生产')
            line=Path(checksum_file).read_text().strip().split(maxsplit=1)
            if len(line)!=2 or line[1]!=Path(zip_path).name or line[0]!=sha(zip_path):raise ValueError('正式ZIP外部SHA256或文件名不符')
            return {'format':'legacy_with_checksum'}
        idx=read_zip_json(z,top+'/'+INDEX)
        report_name='演练与导出确认/演练报告.json'
        approval_name='演练与导出确认/用户导出确认.json'
        required={report_name,approval_name,'交接说明.md','接包生产执行要求.md','接包入口.md'}
        if not required.issubset({r['path'] for r in manifest['files']}):raise ValueError('单ZIP缺交接说明或正式发布证据')
        report=read_zip_json(z,top+'/'+report_name);approval=read_zip_json(z,top+'/'+approval_name)
        if (idx.get('delivery_policy')!='direct_delivery_v2' or manifest.get('package_id')!=idx.get('package_id') or
            report.get('package_id')!=idx.get('package_id') or report.get('policy')!=POLICY or
            report.get('source_kind')!='observed_frozen_gate_rehearsal' or report.get('status')!='RELEASE_CANDIDATE' or
            report.get('originals_unchanged') is not True or report.get('image_calls')!=0 or not report.get('ready_h001_count')):
            raise ValueError('单ZIP正式发布或演练证据不完整')
        results=report.get('results',[])
        if ([r.get('episode_id') for r in results]!=[e['episode_id'] for e in idx['episodes']] or
            any(r.get('status')!='REHEARSED' or r.get('errors') for r in results)):
            raise ValueError('单ZIP演练未覆盖全部话')
        literal=approval.get('status')=='APPROVED' and approval.get('source_kind')=='user_message' and approval.get('source_locator') and approval.get('quote')
        exact=(approval.get('candidate_zip_sha256')==report.get('candidate_zip_sha256') and
               approval.get('rehearsal_report_sha256')==hashlib.sha256(z.read(top+'/'+report_name)).hexdigest())
        conditional=(approval.get('authorization_mode')=='approved_inputs_auto_export_v1' and
                     approval.get('package_id')==idx['package_id'] and approval.get('after_successful_rehearsal') is True and
                     bool(approval.get('approved_input_digest')))
        if not literal or not (exact or conditional):raise ValueError('单ZIP缺适用导出授权')
        return {'format':'self_contained_handoff_v1','package_id':idx['package_id']}


def extract(zip_path,destination,*,reserve_bytes=256*1024*1024,checksum_file=None):
    if checksum_file:
        line=Path(checksum_file).read_text().strip().split(maxsplit=1)
        if len(line)!=2 or line[1]!=Path(zip_path).name or line[0]!=sha(zip_path):
            raise ValueError('正式ZIP外部SHA256或文件名不符')
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('解压目录须全新且不存在，不能复用前期运行目录')
    with zipfile.ZipFile(zip_path) as z:
        top,manifest=zip_inventory(z)
        required=sum(i.file_size for i in z.infolist())+reserve_bytes
        parent=destination.parent
        while not parent.exists():parent=parent.parent
        if shutil.disk_usage(parent).free<required:raise ValueError('接收落盘空间不足，未开始解压')
        destination.mkdir(parents=True)
        try:z.extractall(destination)
        except Exception:shutil.rmtree(destination);raise
    root=destination/top
    if files(root)!=sorted(manifest['files'],key=lambda r:r['path']):raise ValueError('解压实体与ZIP文件清单不一致')
    audit_index(root)
    return {'status':'EXTRACTED_CHECKED_NOT_PRODUCTION_APPROVAL','root':str(root),'archive_sha256':sha(zip_path)}


def rehearse(zip_path,package_root,run_root,run_index,report,*,timeout=180):
    from runtime_snapshot import verify
    if timeout<=0:raise ValueError('预检超时须大于零')
    package_root=Path(package_root).resolve();run_root=Path(run_root).resolve();zip_path=Path(zip_path).resolve()
    if package_root==run_root or run_root.is_relative_to(package_root) or package_root.is_relative_to(run_root):raise ValueError('收到原件与本地运行须为分离目录')
    with zipfile.ZipFile(zip_path) as z:
        _,manifest=zip_inventory(z)
    before=files(package_root)
    if before!=sorted(manifest['files'],key=lambda r:r['path']):raise ValueError('收到原件不等于候选ZIP内容')
    data=audit_index(package_root);local=read(run_index)
    if local.get('package_id')!=data['package_id']:raise ValueError('本地绑定索引属于其他包')
    runs=local.get('episodes',[])
    if [e.get('episode_id') for e in runs]!=[e['episode_id'] for e in data['episodes']]:raise ValueError('接包演练必须覆盖全部交接话')
    report=Path(report).resolve()
    if report.exists() or report.is_relative_to(package_root):raise ValueError('报告目录须为原包外新目录')
    report.mkdir(parents=True);results=[]
    for episode,run in zip(data['episodes'],runs):
        eid=episode['episode_id'];errors=[];job_ids=[];raw=None;argv=None;rc=None
        try:
            state_path=inside(run_root,run['state']);state=read(state_path)
            if state.get('book_id')!=data['book_id'] or state.get('episode_id')!=eid:raise ValueError('本地状态书话失配')
            mapping=reference(run_root,run['binding_evidence'])
            actual_source=read(reference(state_path.parent.parent,state.get('source_snapshot')))
            actual_ids=actual_source.get('panel_ids') or (actual_source.get('id_mapping') or {}).get('panel_ids')
            if actual_ids!=episode['panel_ids']:raise ValueError('本地生产源序与交接完整源序不一致')
            # Never treat the old snapshot absolute path as the local executable.
            manifest_path=reference(package_root,episode['runtime_manifest']);snap_ref=state.get('runtime_snapshot',{})
            if Path(snap_ref.get('path','')).resolve()!=manifest_path.resolve() or snap_ref.get('sha256')!=sha(manifest_path):raise ValueError('本地运行未绑定解压包内实际冻结快照')
            frozen=verify(snap_ref);script=Path(frozen['scripts'])/'production_runtime.py'
            argv=[sys.executable,'-B',str(script),'--state',str(state_path),'--action','compile','--panels',*episode['halves']['H001']]
            try:
                proc=subprocess.run(argv,capture_output=True,text=True,timeout=timeout,cwd=state_path.parent.parent);rc=proc.returncode
                (report/(eid+'_stdout.json')).write_text(proc.stdout);(report/(eid+'_stderr.txt')).write_text(proc.stderr)
                raw=json.loads(proc.stdout)
            except subprocess.TimeoutExpired as exc:
                (report/(eid+'_timeout.txt')).write_text(str(exc));raise ValueError('冻结预检超时；未记通过')
            if not isinstance(raw,dict) or raw.get('candidate_only') is not False or raw.get('image_calls')!=0:raise ValueError('缺真实非candidate只读预检；不接受候选PASS代替生产预检')
            if data.get('delivery_policy')=='direct_delivery_v2':
                from handoff_delivery import input_review
                input_review(package_root,data)
                proof=read(mapping)
                if proof.get('policy')!='runtime_only_relocation_v1' or proof.get('local_state_sha256')!=sha(state_path):raise ValueError('须使用包内确定性bind建立运行，不能由接手人临时改状态')
                for key in ('source_script','source_snapshot','visual_basis','shot_manifest'):
                    target='production_source_snapshot' if key=='source_snapshot' else key
                    if sha(reference(state_path.parent.parent,state.get(key)))!=sha(reference(package_root,episode.get(target))):raise ValueError('实际执行依据不等于最终审查输入:'+key)
                actual_packages={r['sha256'] for refs in state.get('generation_packages',{}).values() for r in refs}
                if actual_packages!={r['sha256'] for r in episode['generation_review_packages']}:raise ValueError('实际生图包审查清单换版')
                prep_argv=[sys.executable,'-B',str(script),'--state',str(state_path),'--action','readiness']
                prep=subprocess.run(prep_argv,capture_output=True,text=True,timeout=timeout,cwd=state_path.parent.parent)
                (report/(eid+'_preparation.json')).write_text(prep.stdout);(report/(eid+'_preparation_stderr.txt')).write_text(prep.stderr)
                prepared=json.loads(prep.stdout)
                required=[p['panel_id'] for p in episode['panels'] if p['classification']!='REUSE']
                if prep.returncode or prepared.get('global_errors') or prepared.get('errors') or not set(required).issubset(prepared.get('prepared_panel_ids',[])):
                    raise ValueError('全话准备预检未通过，不能以首半话可启动代替全话交付')
                all_argv=[sys.executable,'-B',str(script),'--state',str(state_path),'--action','compile','--panels',*episode['panel_ids']]
                all_proc=subprocess.run(all_argv,capture_output=True,text=True,timeout=timeout,cwd=state_path.parent.parent)
                (report/(eid+'_all_inputs.json')).write_text(all_proc.stdout);(report/(eid+'_all_inputs_stderr.txt')).write_text(all_proc.stderr)
                all_inputs=json.loads(all_proc.stdout)
                full_expected=[p['panel_id'] for p in episode['panels'] if p['classification'] in {'READY_H001','PREPARED_H002'}]
                if all_inputs.get('candidate_only') is not False or all_inputs.get('image_calls')!=0 or [j.get('panel_id') for j in all_inputs.get('jobs',[])]!=full_expected:
                    raise ValueError('全话实际输入/批准预检未闭合，H002或依赖范围不符')
                for job in all_inputs.get('jobs',[]):
                    for value in job.get('arguments',{}).get('referenced_image_paths',[]):
                        path=Path(value).resolve()
                        if not path.is_file() or not (path.is_relative_to(package_root) or path.is_relative_to(run_root)):raise ValueError('全话参考仍缺失或依赖前期电脑')
            pre=raw.get('preflight') or {}
            expected=[p['panel_id'] for p in episode['panels'] if p['classification']=='READY_H001']
            job_ids=[j.get('panel_id') for j in raw.get('jobs',[])]
            if job_ids!=expected:errors.append('实际就绪格与声称READY_H001不符')
            if any(j.get('candidate_only') or j.get('status')!='NOT_RUN' for j in raw.get('jobs',[])):errors.append('预检作业状态不合法')
            if raw.get('global_errors') or (pre.get('errors') and not pre.get('reports')) or (expected and (pre.get('dispatch_authorized') is False or rc!=0 or pre.get('status') not in {'READY','PARTIAL_READY'})):
                errors.append('冻结原门禁尚未放行：保留stdout/stderr供前期处理')
            # Every actual image path must resolve under received originals or the new local run.
            for job in raw.get('jobs',[]):
                for value in job.get('arguments',{}).get('referenced_image_paths',[]):
                    p=Path(value).resolve()
                    if not (p.is_relative_to(package_root) or p.is_relative_to(run_root)):errors.append('实际请求仍引用旧电脑/外部参考路径')
                    if not p.is_file():errors.append('实际请求参考不存在')
        except (OSError,ValueError,KeyError,TypeError) as exc:errors.append(str(exc))
        results.append({'episode_id':eid,'status':'HOLD' if errors else 'REHEARSED','ready_h001':job_ids if not errors else [],'errors':errors,'argv':argv,'returncode':rc})
    if files(package_root)!=before:raise ValueError('演练改动收到原件，禁止发布')
    ready=sum(len(r['ready_h001']) for r in results)
    result={'policy':POLICY,'source_kind':'observed_frozen_gate_rehearsal','package_id':data['package_id'],'candidate_zip_sha256':sha(zip_path),'originals_unchanged':True,'image_calls':0,'environment':{'python':sys.version,'executable':sys.executable,'platform':platform.platform()},'results':results,'ready_h001_count':ready,'status':'RELEASE_CANDIDATE' if ready and all(r['status']=='REHEARSED' for r in results) else 'HOLD','not_production_authorization':True}
    result['evidence_files']=files(report)
    write(report/'演练报告.json',result)
    return result


def release(candidate_zip,rehearsal_report,approval_file,output):
    candidate_zip=Path(candidate_zip).resolve();rehearsal_report=Path(rehearsal_report).resolve();output=Path(output).resolve()
    report=read(rehearsal_report);approval=read(approval_file)
    from handoff_delivery import closure,input_review,DIRECT
    with zipfile.ZipFile(candidate_zip) as archive:
        top,_=zip_inventory(archive);delivery_index=read_zip_json(archive,top+'/'+INDEX)
        if delivery_index.get('delivery_policy')!=DIRECT:raise ValueError('旧版或范围交接只能诊断，正式包须direct_delivery_v2完整闭环')
        # Validate normalized closure without extracting a second copy of large assets.
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            refs=[]
            for e in delivery_index['episodes']:
                refs.extend(e.get(k) for k in ('run_template','source_script','production_source_snapshot','visual_basis','shot_manifest','runtime_manifest'))
                refs.extend(e.get('generation_review_packages',[]))
                for p in e['panels']:
                    if p['classification']=='WAIT_DEPENDENCY':refs.append(p.get('production_dependency',{}).get('completion_plan'))
                    if p['classification']=='REUSE':refs.extend(p.get(k) for k in ('current_design_review','accepted_image','accepted_qa','acceptance'))
            for ref in refs:
                if not isinstance(ref,dict):raise ValueError('缺直接交付闭环引用')
                dest=inside(root,ref['path']);dest.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(top+'/'+ref['path']) as src,dest.open('wb') as dst:shutil.copyfileobj(src,dst)
            errors=closure(root,delivery_index)
            if errors:raise ValueError(';'.join(errors))
            reviewed=input_review(root,delivery_index)
    if (report.get('policy')!=POLICY or report.get('source_kind')!='observed_frozen_gate_rehearsal' or
            report.get('status')!='RELEASE_CANDIDATE' or not report.get('originals_unchanged') or report.get('image_calls')!=0 or
            report.get('candidate_zip_sha256')!=sha(candidate_zip) or not report.get('ready_h001_count')):raise ValueError('未完成真实解压预检或无就绪格，不可发布正式可生产ZIP')
    if not report.get('results') or any(r.get('status')!='REHEARSED' or r.get('errors') for r in report['results']):raise ValueError('演练仍有系统性阻断')
    for ref in report.get('evidence_files',[]):reference(rehearsal_report.parent,ref)
    literal=(approval.get('status')=='APPROVED' and approval.get('source_kind')=='user_message' and approval.get('source_locator') and approval.get('quote'))
    exact=(approval.get('candidate_zip_sha256')==sha(candidate_zip) and approval.get('rehearsal_report_sha256')==sha(rehearsal_report))
    conditional=(approval.get('authorization_mode')=='approved_inputs_auto_export_v1' and approval.get('package_id')==delivery_index['package_id'] and
                 approval.get('approved_input_digest')==reviewed['approved_input_digest'] and approval.get('after_successful_rehearsal') is True)
    if not literal or not (exact or conditional):
        raise ValueError('缺当前候选真实导出确认或最终输入不变条件导出授权，不得回签旧批准')
    if output.exists() or output.suffix.lower()!='.zip':raise ValueError('正式ZIP须新路径，不覆盖候选或原包')
    with zipfile.ZipFile(candidate_zip) as original:
        top,manifest=zip_inventory(original);idx=read_zip_json(original,top+'/'+INDEX)
        if idx['package_id']!=report['package_id']:raise ValueError('演练包ID不同')
        if [r.get('episode_id') for r in report['results']]!=[e['episode_id'] for e in idx['episodes']]:raise ValueError('演练报告未覆盖准确全部话')
        for episode,result in zip(idx['episodes'],report['results']):
            expected=[p['panel_id'] for p in episode['panels'] if p['classification']=='READY_H001']
            if result.get('ready_h001')!=expected:raise ValueError('演练就绪范围与候选不一致')
            raw_name=episode['episode_id']+'_stdout.json'
            if raw_name not in {r['path'] for r in report.get('evidence_files',[])}:raise ValueError('缺冻结门禁原始输出')
        if report['ready_h001_count']!=sum(len(r['ready_h001']) for r in report['results']):raise ValueError('演练就绪统计失配')
        additions={'演练与导出确认/演练报告.json':rehearsal_report.read_bytes(),'演练与导出确认/用户导出确认.json':Path(approval_file).read_bytes()}
        for ref in report.get('evidence_files',[]):additions['演练与导出确认/原始预检/'+ref['path']]=reference(rehearsal_report.parent,ref).read_bytes()
        additions['接包入口.md']=('# 正式交接包\n\n仅交付本ZIP，无需外置校验文件或再次解压套包。\n在Codex中使用 $vertical-comic-preproduction，填写：接包生产：【本ZIP的本机绝对路径】；输出位置：【本机目录】；审核人是我。\n接收端先校验包内清单及正式发布证据，再解压、绑定和演练；通过后依包内审核节点生产。\n详细范围、历史预算与步骤见交接说明.md、接包生产执行要求.md及交接验收索引.json。\n内部哈希用于完整性核对，不证明发布者身份；本ZIP最终SHA256只记录于导出日志，不写入自身。\n').encode('utf-8')
        reserved={r['path'] for r in manifest['files']}
        if reserved & set(additions):raise ValueError('正式证据路径与原包冲突')
        rows=sorted(manifest['files']+[{'path':k,'sha256':hashlib.sha256(v).hexdigest(),'bytes':len(v)} for k,v in additions.items()],key=lambda r:r['path'])
        output.parent.mkdir(parents=True,exist_ok=True)
        try:
            with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=3,allowZip64=True) as z:
                for info in original.infolist():
                    if info.filename==top+'/'+INVENTORY:continue
                    with original.open(info) as src,z.open(info,'w') as dst:shutil.copyfileobj(src,dst)
                for name,value in additions.items():z.writestr(top+'/'+name,value)
                z.writestr(top+'/'+INVENTORY,json.dumps({**manifest,'container_policy':'self_contained_handoff_v1','files':rows},ensure_ascii=False,indent=2))
            with zipfile.ZipFile(output) as z:zip_inventory(z)
            check_delivery_archive(output)
        except Exception:output.unlink(missing_ok=True);raise
    return {'status':'RELEASED_DIRECT_DELIVERY_ZIP','zip':str(output),'sha256':sha(output),'ready_h001_count':report['ready_h001_count'],'not_production_authorization':True}


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    q=sub.add_parser('bind');q.add_argument('--package-root',required=True);q.add_argument('--run-root',required=True)
    q=sub.add_parser('review');q.add_argument('--root',required=True)
    q=sub.add_parser('pack');q.add_argument('--root',required=True);q.add_argument('--output',required=True)
    q=sub.add_parser('extract');q.add_argument('--zip',required=True);q.add_argument('--destination',required=True);q.add_argument('--reserve-bytes',type=int,default=256*1024*1024);q.add_argument('--sha256-file')
    q=sub.add_parser('rehearse');q.add_argument('--zip',required=True);q.add_argument('--package-root',required=True);q.add_argument('--run-root',required=True);q.add_argument('--run-index',required=True);q.add_argument('--report-dir',required=True);q.add_argument('--timeout',type=int,default=180)
    q=sub.add_parser('release');q.add_argument('--zip',required=True);q.add_argument('--rehearsal-report',required=True);q.add_argument('--approval',required=True);q.add_argument('--output',required=True)
    a=p.parse_args()
    try:
        if a.action=='bind':
            from handoff_delivery import bind
            r=bind(a.package_root,a.run_root)
        elif a.action=='review':
            from handoff_delivery import input_review
            r={'status':'FINAL_INPUTS_FOR_HUMAN_REVIEW',**input_review(a.root,audit_index(a.root))}
        elif a.action=='pack':r=pack(a.root,a.output)
        elif a.action=='extract':
            if a.reserve_bytes<0:raise ValueError('空间预留不得为负数')
            r=extract(a.zip,a.destination,reserve_bytes=a.reserve_bytes,checksum_file=a.sha256_file)
        elif a.action=='rehearse':r=rehearse(a.zip,a.package_root,a.run_root,a.run_index,a.report_dir,timeout=a.timeout)
        else:r=release(a.zip,a.rehearsal_report,a.approval,a.output)
        print(json.dumps(r,ensure_ascii=False));return 1 if r['status']=='HOLD' else 0
    except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile) as exc:
        print(json.dumps({'status':'HOLD','errors':[str(exc)]},ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
