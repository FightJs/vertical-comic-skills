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
from platform_io import portable_relative, check_destination_paths
import shutil
import stat
import subprocess
import sys
import zipfile
from handoff_scope import EPISODE_POLICY, episode_mode, validate_episode, ready_ids, ready_key, count_key

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
    with Path(path).open('x',encoding='utf-8', newline='\n') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')


def relative(value):
    return portable_relative(value)


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


def frozen_task_contract(root,episode):
    """The marker contract applies only if the verified frozen toolchain has it."""
    from runtime_snapshot import verify
    path=reference(root,episode['runtime_manifest'])
    frozen=verify({'path':str(path.resolve()),'sha256':episode['runtime_manifest']['sha256']})
    return any(row['path']=='skills/vertical-comic-preproduction/scripts/task_context.py' for row in frozen['data']['files'])


def handoff_history_errors(package_root,episode,context,state,run_root):
    from task_context import history_errors,ORIGIN_FILE
    # Modern or already marked templates remain strict. An old verified snapshot
    # must not acquire a new origin-file requirement merely by being received.
    require_origin=True
    if context is not None and not (Path(run_root)/ORIGIN_FILE).exists():
        require_origin=frozen_task_contract(package_root,episode)
    return history_errors(context,episode,state,run_root,lambda ref:reference(package_root,ref),require_origin=require_origin)


def audit_index(root):
    root=Path(root);data=read(root/INDEX)
    from task_context import validate as validate_task
    context=data.get('task_context')
    if context is not None:
        validate_task(context)
        if context['book_id']!=data.get('book_id'):raise ValueError('TASK_SCOPE_HOLD:交接书名与任务失配')
    if data.get('policy') not in {POLICY,EPISODE_POLICY} or not data.get('package_id') or not data.get('book_id'):
        raise ValueError('缺交接验收索引策略、包ID或书ID')
    for name in REQUIRED:
        if not (root/name).is_file() or not (root/name).read_text(encoding='utf-8-sig').strip():raise ValueError('缺交接入口或内容为空:'+name)
    whole=episode_mode(data)
    if whole and data.get('delivery_policy')!='direct_delivery_v2':raise ValueError('新版整话交接须完整direct_delivery_v2')
    episodes=data.get('episodes')
    if not isinstance(episodes,list) or not episodes:raise ValueError('缺准确话号与逐格交接范围')
    seen=set()
    for episode in episodes:
        eid=episode.get('episode_id');ids=episode.get('panel_ids');halves=episode.get('halves',{})
        if not isinstance(eid,str) or eid in seen:raise ValueError('话号缺失/重复')
        seen.add(eid)
        if not eid or len(relative(eid).parts)!=1:raise ValueError('话号须为安全单层名称')
        if not isinstance(ids,list) or not ids or any(not isinstance(p,str) or not p for p in ids) or len(set(ids))!=len(ids):raise ValueError(eid+':源格序缺失/重复')
        validate_episode(data,episode)
        for key in ('source_snapshot','runtime_manifest','approval_evidence','path_binding_plan'):
            reference(root,episode.get(key))
        source=read(reference(root,episode['source_snapshot']))
        source_ids=source.get('panel_ids') or (source.get('id_mapping') or {}).get('panel_ids')
        if source_ids!=ids:raise ValueError(eid+':源快照格序与交接不一致')
        panels=episode.get('panels')
        if not isinstance(panels,list) or [p.get('panel_id') for p in panels]!=ids:raise ValueError(eid+':逐格准备/历史清单不完整')
        for row in panels:
            pid=row['panel_id'];kind=row.get('classification')
            if kind not in (KINDS if not whole else {'READY','WAIT_DEPENDENCY','HOLD','REUSE'}):raise ValueError(pid+':未知交接状态')
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
        if episode.get('run_template'):
            plan=read(reference(root,episode['run_template']))
            template=inside(root,plan['root']);state=read(inside(template,plan['state_file']))
            errors=handoff_history_errors(root,episode,context,state,template)
            from input_semantics import enabled as semantics_enabled
            if semantics_enabled(state):
                if episode.get('input_semantics_policy')!=state['input_semantics_policy']:
                    errors.append(eid+':交接索引与运行模板的语义审查策略不同')
                audit=reference(root,episode.get('semantic_audit'))
                from codex_reference_contract import checked_file
                if sha(audit)!=sha(checked_file(template,state['semantic_audit'])):
                    errors.append(eid+':交接语义证据与运行模板不同')
            if errors:raise ValueError(';'.join(errors))
        elif context is not None:
            raise ValueError('TASK_SCOPE_HOLD:本任务零调用须由实际运行模板核对，不能只填空历史')
    if context is not None and [eid for eid in context['episode_ids'] if eid in seen]!=[e['episode_id'] for e in episodes]:
        raise ValueError('TASK_SCOPE_HOLD:交接范围不属于任务话序；缩小范围仍须准确输入批准')
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


def directory_inventory(package_root):
    """Verify extracted payload bytes without recreating or claiming a ZIP."""
    root=Path(package_root)
    if root.is_symlink() or root.is_junction() or not root.is_dir():raise ValueError('交接目录不存在或是链接')
    root=root.resolve();seen=set()
    for p in root.rglob('*'):
        name=p.relative_to(root).as_posix();relative(name)
        if p.is_symlink() or p.is_junction():raise ValueError('包内不得有符号链接或目录联接:'+name)
        if name.casefold() in seen:raise ValueError('目录路径大小写冲突:'+name)
        seen.add(name.casefold())
        if not p.is_file() and not p.is_dir():raise ValueError('包内不是普通文件或目录:'+name)
    inventory=root/INVENTORY
    if not inventory.is_file():raise ValueError('缺少'+INVENTORY+'；请指定含清单和交接验收索引的包根目录')
    manifest=read(inventory)
    if manifest.get('policy')!=POLICY:raise ValueError('目录文件清单策略错误')
    rows=manifest.get('files')
    if not isinstance(rows,list):raise ValueError('目录文件清单缺失')
    expected={};folded=set()
    for row in rows:
        if not isinstance(row,dict):raise ValueError('目录清单条目无效')
        name=row.get('path');relative(name)
        if name==INVENTORY or name.casefold() in folded:raise ValueError('目录清单重复/大小写冲突:'+name)
        folded.add(name.casefold());expected[name]=row
    actual={r['path']:r for r in files(root)}
    missing=sorted(expected.keys()-actual.keys());extra=sorted(actual.keys()-expected.keys())
    changed=sorted(n for n in expected.keys() & actual.keys() if expected[n]!=actual[n])
    if missing or extra or changed:
        raise ValueError('目录清单不一致:'+json.dumps({'missing':missing,'unlisted':extra,'changed':changed},ensure_ascii=False))
    return root,manifest


def delivery_evidence(manifest,read_bytes):
    """Shared release evidence checks for ZIPs and their extracted contents."""
    idx=json.loads(read_bytes(INDEX).decode('utf-8-sig'))
    report_name='演练与导出确认/演练报告.json'
    approval_name='演练与导出确认/用户导出确认.json'
    required={report_name,approval_name,'交接说明.md','接包生产执行要求.md','接包入口.md'}
    if not required.issubset({r['path'] for r in manifest['files']}):raise ValueError('交接包缺交接说明或正式发布证据')
    report_bytes=read_bytes(report_name);report=json.loads(report_bytes.decode('utf-8-sig'))
    approval=json.loads(read_bytes(approval_name).decode('utf-8-sig'))
    if (idx.get('delivery_policy')!='direct_delivery_v2' or manifest.get('package_id')!=idx.get('package_id') or
        report.get('package_id')!=idx.get('package_id') or report.get('policy')!=POLICY or
        report.get('source_kind')!='observed_frozen_gate_rehearsal' or report.get('status')!='RELEASE_CANDIDATE' or
        report.get('originals_unchanged') is not True or report.get('image_calls')!=0 or not report.get(count_key(idx))):
        raise ValueError('交接包正式发布或演练证据不完整')
    results=report.get('results',[])
    if ([r.get('episode_id') for r in results]!=[e['episode_id'] for e in idx['episodes']] or
        any(r.get('status')!='REHEARSED' or r.get('errors') for r in results)):
        raise ValueError('交接包演练未覆盖全部话')
    for episode,result in zip(idx['episodes'],results):
        if result.get(ready_key(idx))!=ready_ids(idx,episode):
            raise ValueError('交接包演练就绪范围失配')
    if report[count_key(idx)]!=sum(len(r[ready_key(idx)]) for r in results):raise ValueError('交接包演练就绪统计失配')
    for ref in report.get('evidence_files',[]):
        relative(ref['path']);body=read_bytes('演练与导出确认/原始预检/'+ref['path'])
        if len(body)!=ref.get('bytes') or hashlib.sha256(body).hexdigest()!=ref.get('sha256'):
            raise ValueError('交接包原始演练证据失配:'+ref['path'])
    literal=approval.get('status')=='APPROVED' and approval.get('source_kind')=='user_message' and approval.get('source_locator') and approval.get('quote')
    exact=(bool(report.get('candidate_zip_sha256')) and approval.get('candidate_zip_sha256')==report.get('candidate_zip_sha256') and
           approval.get('rehearsal_report_sha256')==hashlib.sha256(report_bytes).hexdigest())
    conditional=(approval.get('authorization_mode')=='approved_inputs_auto_export_v1' and
                 approval.get('package_id')==idx['package_id'] and approval.get('after_successful_rehearsal') is True and
                 bool(approval.get('approved_input_digest')))
    if not literal or not (exact or conditional):raise ValueError('交接包缺适用导出授权')
    return {'format':'self_contained_handoff_v1','package_id':idx['package_id']}


def check_delivery_directory(package_root):
    root,manifest=directory_inventory(package_root)
    if manifest.get('container_policy')!='self_contained_handoff_v1':
        raise ValueError('目录缺自包含正式发布证据；候选目录不能接包。旧版仅有外部ZIP校验值时才需原ZIP及校验文件')
    checked=delivery_evidence(manifest,lambda name:inside(root,name).read_bytes())
    data=audit_index(root)
    from handoff_delivery import input_review
    reviewed=input_review(root,data)
    approval=read(root/'演练与导出确认/用户导出确认.json')
    if (approval.get('authorization_mode')=='approved_inputs_auto_export_v1' and
        approval.get('approved_input_digest')!=reviewed['approved_input_digest']):
        # Earlier frozen input_review did not bind task_context as a top-level
        # digest field. Permit that exact old digest only for verified old tools.
        legacy=(data.get('task_context') is not None and
                all(not frozen_task_contract(root,e) for e in data['episodes']))
        old_review=input_review(root,{k:v for k,v in data.items() if k!='task_context'}) if legacy else None
        if old_review is None or approval.get('approved_input_digest')!=old_review['approved_input_digest']:
            raise ValueError('交接包条件导出授权与最终输入摘要失配')
    return {**checked,'root':str(root),'source_type':'extracted_directory','inventory_sha256':sha(root/INVENTORY),
            'file_count':len(manifest['files']),'payload_integrity':'PASS','archive_crc':'NOT_AVAILABLE_EXTRACTED_DIRECTORY'}


def pack(root,output):
    root=Path(root).resolve();output=Path(output).resolve()
    if output.suffix.lower()!='.zip' or output.exists() or output.is_relative_to(root):raise ValueError('输出须为包外不存在的ZIP，不覆盖原包')
    rows=files(root)
    data=audit_index(root)
    if episode_mode(data):
        from handoff_delivery import formal_context_errors
        errors=formal_context_errors(root,data)
        if errors:raise ValueError(';'.join(errors))
    manifest={'policy':POLICY,'package_id':data['package_id'],'files':rows}
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
            line=Path(checksum_file).read_text(encoding='utf-8-sig').strip().split(maxsplit=1)
            if len(line)!=2 or line[1]!=Path(zip_path).name or line[0]!=sha(zip_path):raise ValueError('正式ZIP外部SHA256或文件名不符')
            return {'format':'legacy_with_checksum'}
        return delivery_evidence(manifest,lambda name:z.read(top+'/'+name))


def extract(zip_path,destination,*,reserve_bytes=256*1024*1024,checksum_file=None):
    if checksum_file:
        line=Path(checksum_file).read_text(encoding='utf-8-sig').strip().split(maxsplit=1)
        if len(line)!=2 or line[1]!=Path(zip_path).name or line[0]!=sha(zip_path):
            raise ValueError('正式ZIP外部SHA256或文件名不符')
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('解压目录须全新且不存在，不能复用前期运行目录')
    with zipfile.ZipFile(zip_path) as z:
        top,manifest=zip_inventory(z)
        check_destination_paths(destination, [i.filename for i in z.infolist()])
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


def rehearse(zip_path,package_root,run_root,run_index,report,*,timeout=900,budget_path=None,resume_report=None):
    from runtime_snapshot import verify
    if timeout<=0:raise ValueError('预检超时须大于零')
    package_root=Path(package_root).resolve();run_root=Path(run_root).resolve()
    if package_root==run_root or run_root.is_relative_to(package_root) or package_root.is_relative_to(run_root):raise ValueError('收到原件与本地运行须为分离目录')
    if zip_path is None:
        receipt=check_delivery_directory(package_root)
        manifest=read(package_root/INVENTORY)
    else:
        zip_path=Path(zip_path).resolve()
        with zipfile.ZipFile(zip_path) as z:_,manifest=zip_inventory(z)
        receipt={'source_type':'zip','archive_crc':'PASS'}
    before=files(package_root)
    if before!=sorted(manifest['files'],key=lambda r:r['path']):raise ValueError('收到原件不等于交接清单内容')
    data=audit_index(package_root);local=read(run_index)
    whole=episode_mode(data)
    if local.get('package_id')!=data['package_id']:raise ValueError('本地绑定索引属于其他包')
    runs=local.get('episodes',[])
    if [e.get('episode_id') for e in runs]!=[e['episode_id'] for e in data['episodes']]:raise ValueError('接包演练必须覆盖全部交接话')
    report=Path(report).resolve()
    if report.exists() or report.is_relative_to(package_root):raise ValueError('报告目录须为原包外新目录')
    report.mkdir(parents=True);results=[];previous={}
    if resume_report is not None:
        prior_path=Path(resume_report).resolve();prior=read(prior_path)
        if prior.get('package_id')!=data['package_id']:raise ValueError('恢复报告属于其他交接包')
        for item in prior.get('evidence_files',[]):
            reference(prior_path.parent,item)
        shutil.copytree(prior_path.parent,report/'previous')
        previous={r['episode_id']:r for r in prior.get('results',[])}
    def run_gate(argv,eid,label,state_path):
        from audit_process import run,last_progress
        out_name=eid+'_stdout.json' if label=='h001' else eid+'_'+label+'.json'
        err_name=eid+'_stderr.txt' if label=='h001' else eid+'_'+label+'_stderr.txt'
        try:
            return run(argv,cwd=state_path.parent.parent,timeout=timeout,
                       stdout_path=report/out_name,stderr_path=report/err_name,budget_path=budget_path or run_root)
        except subprocess.TimeoutExpired as exc:
            write(report/(eid+'_'+label+'_timeout.json'),
                  {'status':'HOLD','argv':argv,'timeout_seconds':timeout,
                   'last_progress':last_progress(exc.stderr or ''),'stdout':out_name,'stderr':err_name})
            raise ValueError('冻结预检超时；未记通过，原始输出和最后进度已保存') from exc
    # Advisory scheduling scope, not a permit or second request ledger. Actual
    # read transactions still reject concurrent writes from older callers.
    activity=run_root/'接收审计活动.json'
    remaining=list(runs)
    def publish_read_scopes():
        from platform_io import atomic_json
        protected=set()
        for item in remaining:
            path=inside(run_root,item['state']);protected.add(str(path))
            state=read(path);episode_root=path.parent.parent
            for source in state.get('continuity_sources',[]):
                if source.get('approval_resolution')=='source_runtime_gates_v1':
                    base=Path(source['root'])
                    if source.get('root_mode')=='context_relative_v1':base=episode_root/base
                    target=(base/source.get('source_state_file','00_输入审计/生产流程.json')).resolve()
                    if target.is_relative_to(run_root):protected.add(str(target))
        atomic_json(activity,{'policy':'receiver_active_read_scopes_v1','protected_state_paths':sorted(protected),
                             'report_directory':str(report),'dispatch_authorized':False})
    publish_read_scopes()
    for episode,run in zip(data['episodes'],runs):
        eid=episode['episode_id'];errors=[];job_ids=[];raw=None;argv=None;rc=None
        try:
            state_path=inside(run_root,run['state']);state=read(state_path)
            if state.get('book_id')!=data['book_id'] or state.get('episode_id')!=eid:raise ValueError('本地状态书话失配')
            old=previous.get(eid,{})
            if old.get('status')=='REHEARSED' and old.get('input_read_set') and old.get('input_state_sha256')==sha(state_path):
                from codex_reference_contract import verify_exported_read_set
                if verify_exported_read_set(old['input_read_set'],[package_root,run_root]):
                    results.append({**old,'audit_reuse':'CONTENT_REVERIFIED',
                                    'prior_report':{'path':'previous/'+prior_path.name,'sha256':sha(prior_path)}})
                    remaining.remove(run);publish_read_scopes()
                    continue
            scoped=handoff_history_errors(package_root,episode,data.get('task_context'),state,state_path.parent.parent)
            if scoped:raise ValueError(';'.join(scoped))
            mapping=reference(run_root,run['binding_evidence'])
            actual_source=read(reference(state_path.parent.parent,state.get('source_snapshot')))
            actual_ids=actual_source.get('panel_ids') or (actual_source.get('id_mapping') or {}).get('panel_ids')
            if actual_ids!=episode['panel_ids']:raise ValueError('本地生产源序与交接完整源序不一致')
            # Never treat the old snapshot absolute path as the local executable.
            manifest_path=reference(package_root,episode['runtime_manifest']);snap_ref=state.get('runtime_snapshot',{})
            if Path(snap_ref.get('path','')).resolve()!=manifest_path.resolve() or snap_ref.get('sha256')!=sha(manifest_path):raise ValueError('本地运行未绑定解压包内实际冻结快照')
            frozen=verify(snap_ref);script=Path(frozen['scripts'])/'production_runtime.py'
            capability=Path(frozen['scripts'])/'runtime_capabilities.json'
            combined=False
            if capability.is_file() and data.get('delivery_policy')=='direct_delivery_v2' and state.get('execution_mode')=='episode_async_v1':
                caps=read(capability)
                if not isinstance(caps,dict) or caps.get('policy')!='comic_runtime_capabilities_v1' or caps.get('receiver_audit')!='receiver_audit_bundle_v1' or caps.get('input_audit')!='receiver_input_audit_v1':
                    raise ValueError('未知冻结接包审计能力，不能静默降级')
                if whole and caps.get('receiver_episode_audit')!='receiver_episode_audit_v1':
                    raise ValueError('冻结工具不支持整话接包审计，不能降级为半话')
                combined=True
            if whole and not combined:raise ValueError('新版整话包缺冻结整话审计能力，不能降级')
            argv=[sys.executable,'-X','utf8','-B',str(script),'--state',str(state_path)]
            if combined:
                argv.extend(['--action','receiver-audit','--progress'])
                argv.extend(['--episode-scope'] if whole else ['--h001-panels',*episode['halves']['H001']])
                argv.extend(['--panels',*episode['panel_ids']])
                proc=run_gate(argv,eid,'receiver_audit',state_path);rc=proc.returncode
                bundle=json.loads(proc.stdout)
                if (bundle.get('policy')!=('receiver_episode_audit_v1' if whole else 'receiver_audit_bundle_v1') or bundle.get('episode_id')!=eid or bundle.get('book_id')!=data['book_id'] or
                        bundle.get('panel_ids')!=episode['panel_ids'] or
                        (not whole and bundle.get('h001_panel_ids')!=episode['halves']['H001']) or
                        (whole and bundle.get('ready_panel_ids')!=ready_ids(data,episode)) or
                        bundle.get('dispatch_authorized') is not False or bundle.get('image_calls')!=0):
                    raise ValueError('合并接包审计结果缺失或范围失配')
                raw=bundle['all_inputs' if whole else 'h001'];prepared=bundle['preparation'];all_inputs=bundle['all_inputs']
                write(report/(eid+'_stdout.json'),raw)
                write(report/(eid+'_preparation.json'),prepared)
                write(report/(eid+'_all_inputs.json'),all_inputs)
            else:
                argv.extend(['--action','compile','--panels',*episode['halves']['H001']])
                proc=run_gate(argv,eid,'h001',state_path);rc=proc.returncode
                raw=json.loads(proc.stdout)
            if not isinstance(raw,dict) or raw.get('candidate_only') is not False or raw.get('image_calls')!=0:raise ValueError('缺真实非candidate只读预检；不接受候选PASS代替生产预检')
            if combined and any(v.get('audit_policy')!='receiver_input_audit_v1' or v.get('input_audit_only') is not True or
                                v.get('dispatch_authorized') is not False or v.get('candidate_only') is not False or v.get('image_calls')!=0
                                for v in (raw,all_inputs)):
                raise ValueError('合并审计不能授予生产许可或以候选结果代替')
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
                if not combined:
                    prep_argv=[sys.executable,'-X','utf8','-B',str(script),'--state',str(state_path),'--action','readiness']
                    prep=run_gate(prep_argv,eid,'preparation',state_path)
                    prepared=json.loads(prep.stdout)
                required=[p['panel_id'] for p in episode['panels'] if p['classification']!='REUSE']
                if state.get('input_semantics_policy'):
                    semantic = bundle.get('final_input_semantics', {}) if combined else prepared.get('final_input_semantics', {})
                    if (semantic.get('policy') != state['input_semantics_policy']
                            or semantic.get('status') != 'PREPRODUCTION_INPUTS_REVIEWED'
                            or semantic.get('reviewed_panel_ids') != episode['panel_ids']
                            or semantic.get('dispatch_authorized') is not False):
                        raise ValueError('全话最终输入语义审查未闭合或范围失配')
                    write(report/(eid+'_final_input_semantics.json'),semantic)
                if (rc if combined else prep.returncode) or prepared.get('global_errors') or prepared.get('errors') or not set(required).issubset(prepared.get('prepared_panel_ids',[])):
                    raise ValueError('全话准备预检未通过，不能以首半话可启动代替全话交付')
                if not combined:
                    all_argv=[sys.executable,'-X','utf8','-B',str(script),'--state',str(state_path),'--action','compile','--panels',*episode['panel_ids']]
                    all_proc=run_gate(all_argv,eid,'all_inputs',state_path)
                    all_inputs=json.loads(all_proc.stdout)
                full_expected=[p['panel_id'] for p in episode['panels'] if p['classification'] in ({'READY'} if whole else {'READY_H001','PREPARED_H002'})]
                if (rc if combined else all_proc.returncode) or all_inputs.get('candidate_only') is not False or all_inputs.get('image_calls')!=0 or [j.get('panel_id') for j in all_inputs.get('jobs',[])]!=full_expected:
                    raise ValueError('全话实际输入/批准预检未闭合，就绪或依赖范围不符')
                for job in all_inputs.get('jobs',[]):
                    if combined and (job.get('candidate_only') or job.get('input_audit_only') is not True or job.get('dispatch_authorized') is not False or job.get('status')!='INPUT_AUDITED_NOT_DISPATCHABLE'):
                        raise ValueError('全话审计作业不能授予生产许可')
                    for value in job.get('arguments',{}).get('referenced_image_paths',[]):
                        path=Path(value).resolve()
                        if not path.is_file() or not (path.is_relative_to(package_root) or path.is_relative_to(run_root)):raise ValueError('全话参考仍缺失或依赖来源机器；当前生图人员须报告准确受影响格并直接询问用户')
            if combined and bundle.get('technical_compatibility',{}).get('local_rule_bindings')!='VERIFIED':
                # Old frozen input audits did not traverse the QA address source.
                # Use the installed read-only adapter; never patch frozen tools.
                host=Path(__file__).resolve().parent/'generation_host.py'
                checked_binding=run_gate([sys.executable,'-X','utf8','-B',str(host),
                    'check-bindings','--state',str(state_path)],eid,'local_bindings',state_path)
                if checked_binding.returncode:raise ValueError('LOCAL_EXECUTION_BINDING_HOLD: '+checked_binding.stdout)
            pre=raw.get('preflight') or {}
            expected=ready_ids(data,episode)
            job_ids=[j.get('panel_id') for j in raw.get('jobs',[])]
            if job_ids!=expected:errors.append('实际就绪格与交接声明不符')
            if any(j.get('candidate_only') or j.get('status')!=('INPUT_AUDITED_NOT_DISPATCHABLE' if combined else 'NOT_RUN') or
                   combined and (j.get('input_audit_only') is not True or j.get('dispatch_authorized') is not False) for j in raw.get('jobs',[])):errors.append('预检作业状态不合法')
            permission_invalid=(pre.get('audit_policy')!='receiver_input_audit_v1' or pre.get('input_audit_only') is not True or pre.get('dispatch_authorized') is not False) if combined else pre.get('dispatch_authorized') is False
            if raw.get('global_errors') or (pre.get('errors') and not pre.get('reports')) or (expected and (permission_invalid or rc!=0 or pre.get('status') not in {'READY','PARTIAL_READY'})):
                errors.append('冻结原门禁尚未放行：保留stdout/stderr供前期处理')
            # Every actual image path must resolve under received originals or the new local run.
            for job in raw.get('jobs',[]):
                for value in job.get('arguments',{}).get('referenced_image_paths',[]):
                    p=Path(value).resolve()
                    if not (p.is_relative_to(package_root) or p.is_relative_to(run_root)):errors.append('实际请求仍引用旧电脑/外部参考路径')
                    if not p.is_file():errors.append('实际请求参考不存在')
        except (OSError,ValueError,KeyError,TypeError) as exc:errors.append(str(exc))
        reason=None
        if errors:
            reason=('AUDIT_TIMEOUT' if any('超时' in e for e in errors) else
                    'SNAPSHOT_CHANGED' if any('SNAPSHOT_CHANGED' in e for e in errors) else
                    'PROCESS_ERROR' if rc not in (None,0) else 'CONTENT_HOLD')
        row={'episode_id':eid,'status':'HOLD' if errors else 'REHEARSED',ready_key(data):job_ids if not errors else [],
             'errors':errors,'reason_code':reason,'argv':argv,'returncode':rc}
        if not errors and combined and bundle.get('input_read_set'):
            row['input_read_set']=bundle['input_read_set'];row['input_state_sha256']=sha(state_path)
        results.append(row)
        remaining.remove(run);publish_read_scopes()
    activity.unlink(missing_ok=True)
    if files(package_root)!=before:raise ValueError('演练改动收到原件，禁止发布')
    if zip_path is None and sha(package_root/INVENTORY)!=receipt['inventory_sha256']:raise ValueError('演练期间交接清单变化')
    ready=sum(len(r[ready_key(data)]) for r in results)
    result={'policy':POLICY,'source_kind':'observed_frozen_gate_rehearsal','package_id':data['package_id'],'candidate_zip_sha256':sha(zip_path) if zip_path else None,'reception':receipt,'originals_unchanged':True,'image_calls':0,'environment':{'python':sys.version,'executable':sys.executable,'platform':platform.platform()},'results':results,count_key(data):ready,'status':'RELEASE_CANDIDATE' if ready and all(r['status']=='REHEARSED' for r in results) else 'HOLD','not_production_authorization':True}
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
                if e.get('input_semantics_policy'):refs.append(e.get('semantic_audit'))
                for p in e['panels']:
                    if p['classification']=='WAIT_DEPENDENCY':refs.append(p.get('production_dependency',{}).get('completion_plan'))
                    if p['classification']=='REUSE':refs.extend(p.get(k) for k in ('current_design_review','accepted_image','accepted_qa','acceptance'))
            for ref in refs:
                if not isinstance(ref,dict):raise ValueError('缺直接交付闭环引用')
                dest=inside(root,ref['path']);dest.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(top+'/'+ref['path']) as src,dest.open('wb') as dst:shutil.copyfileobj(src,dst)
            errors=closure(root,delivery_index,verify_runtime=False)
            if errors:raise ValueError(';'.join(errors))
            reviewed=input_review(root,delivery_index)
    if (report.get('policy')!=POLICY or report.get('source_kind')!='observed_frozen_gate_rehearsal' or
            report.get('status')!='RELEASE_CANDIDATE' or not report.get('originals_unchanged') or report.get('image_calls')!=0 or
            report.get('candidate_zip_sha256')!=sha(candidate_zip) or not report.get(count_key(delivery_index))):raise ValueError('未完成真实解压预检或无就绪格，不可发布正式可生产ZIP')
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
            expected=ready_ids(idx,episode)
            if result.get(ready_key(idx))!=expected:raise ValueError('演练就绪范围与候选不一致')
            raw_name=episode['episode_id']+'_stdout.json'
            if raw_name not in {r['path'] for r in report.get('evidence_files',[])}:raise ValueError('缺冻结门禁原始输出')
        if report[count_key(idx)]!=sum(len(r[ready_key(idx)]) for r in report['results']):raise ValueError('演练就绪统计失配')
        additions={'演练与导出确认/演练报告.json':rehearsal_report.read_bytes(),'演练与导出确认/用户导出确认.json':Path(approval_file).read_bytes()}
        for ref in report.get('evidence_files',[]):additions['演练与导出确认/原始预检/'+ref['path']]=reference(rehearsal_report.parent,ref).read_bytes()
        additions['接包入口.md']=('# 正式交接包\n\n仅交付本ZIP，无需外置校验文件或再次解压套包；接收方已经解压时可直接提供完整包根目录。\n在Codex中使用 $vertical-comic-preproduction，填写：接包生产：【本ZIP或已解压包根的本机绝对路径】；输出位置：【本机目录】；审核人是我。\n接收端使用安装版comic_start.py receive：ZIP用--zip，已解压目录用--package-root；先校验包内清单及正式发布证据，ZIP解压后、目录直接进入绑定和演练；通过后依包内审核节点生产。\n详细范围、历史预算与步骤见交接说明.md、接包生产执行要求.md及交接验收索引.json。\n内部哈希用于完整性核对，不证明发布者身份；本ZIP最终SHA256只记录于导出日志，不写入自身。\n').encode('utf-8')
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
    return {'status':'RELEASED_DIRECT_DELIVERY_ZIP','zip':str(output),'sha256':sha(output),count_key(delivery_index):report[count_key(delivery_index)],'not_production_authorization':True}


def publish(source_zip,contract,output):
    from delivery_publish import publish_preparation
    return publish_preparation(contract,source_zip,output)


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    q=sub.add_parser('bind');q.add_argument('--package-root',required=True);q.add_argument('--run-root',required=True)
    q=sub.add_parser('review');q.add_argument('--root',required=True)
    q=sub.add_parser('pack');q.add_argument('--root',required=True);q.add_argument('--output',required=True)
    q=sub.add_parser('extract');q.add_argument('--zip',required=True);q.add_argument('--destination',required=True);q.add_argument('--reserve-bytes',type=int,default=256*1024*1024);q.add_argument('--sha256-file')
    q=sub.add_parser('rehearse');q.add_argument('--zip',help='省略时核验已解压正式目录及内置发布证据');q.add_argument('--package-root',required=True);q.add_argument('--run-root',required=True);q.add_argument('--run-index',required=True);q.add_argument('--report-dir',required=True);q.add_argument('--timeout',type=int,default=900);q.add_argument('--budget-root',help='实际职责计时根目录；所有话共用剩余预算，不重置')
    q=sub.add_parser('release');q.add_argument('--zip',required=True);q.add_argument('--rehearsal-report',required=True);q.add_argument('--approval',required=True);q.add_argument('--output',required=True);q.add_argument('--transport-output',help='正式发布后自动导出微信运输包到全新目录')
    q=sub.add_parser('assemble');q.add_argument('--root',required=True);q.add_argument('--plan',required=True);q.add_argument('--output',required=True)
    q=sub.add_parser('publish');q.add_argument('--zip',required=True);q.add_argument('--contract',required=True);q.add_argument('--output',required=True)
    a=p.parse_args()
    try:
        if a.action=='bind':
            from handoff_delivery import bind
            r=bind(a.package_root,a.run_root)
        elif a.action=='review':
            from handoff_delivery import input_review
            r={'status':'FINAL_INPUTS_FOR_HUMAN_REVIEW',**input_review(a.root,audit_index(a.root))}
        elif a.action=='assemble':
            from handoff_delivery import copy_assembly_plan
            r=copy_assembly_plan(a.root,a.output,read(a.plan))
        elif a.action=='publish':r=publish(a.zip,a.contract,a.output)
        elif a.action=='pack':r=pack(a.root,a.output)
        elif a.action=='extract':
            if a.reserve_bytes<0:raise ValueError('空间预留不得为负数')
            r=extract(a.zip,a.destination,reserve_bytes=a.reserve_bytes,checksum_file=a.sha256_file)
        elif a.action=='rehearse':r=rehearse(a.zip,a.package_root,a.run_root,a.run_index,a.report_dir,timeout=a.timeout,budget_path=a.budget_root)
        else:
            r=release(a.zip,a.rehearsal_report,a.approval,a.output)
            if a.transport_output:
                from handoff_transport import export
                r['transport']=export(a.output,a.transport_output)
        print(json.dumps(r,ensure_ascii=False));return 1 if r['status']=='HOLD' else 0
    except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile) as exc:
        print(json.dumps({'status':'HOLD','errors':[str(exc)]},ensure_ascii=False));return 1


if __name__=='__main__':
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
