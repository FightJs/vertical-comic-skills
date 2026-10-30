"""Time-bounded, read-only delivery of available work using the original ledger.

This publisher does not approve inputs, invoke services, mutate production state,
resolve UNKNOWN or label unreviewed images PASS. A portable evidence map retains
original bytes/addresses; incomplete preparation is explicitly not executable.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import zipfile

from delivery_contract import load_identity, read, digest, reference
from platform_io import atomic_json, file_lock, portable_relative
from production_decisions import selected, outcome, LABELS
from runtime_clock import DELIVERY_SCHEDULE, status

POLICY = 'deadline_delivery_v1'
POINTER = '限时交付.json'


def schedule(identity):
    identity=Path(identity).resolve()
    clock=status(identity.parent)
    if clock.get('delivery_schedule')!=DELIVERY_SCHEDULE:
        raise ValueError('旧运行不迁移限时交付协议')
    return clock


def export(identity, output=None):
    """Publish a coherent snapshot. No final approval or full-episode re-audit gate."""
    identity=Path(identity).resolve();value=load_identity(identity);clock=schedule(identity)
    if clock['state'] in {'PAUSED','WAIT_USER'}:raise ValueError('用户暂停；不得自动继续交付')
    output=Path(output).resolve() if output else identity.parent.parent/'限时交付'
    # Snapshotting must never overwrite the run, its states or existing archives.
    if output==identity.parent or output.is_relative_to(identity.parent):
        raise ValueError('交付目录须在协调记录之外')
    output.mkdir(parents=True,exist_ok=True)
    with file_lock(output/'snapshot.lock'):
        return _export(identity,value,clock,output)


def _export(identity,value,clock,output):
    started=time.monotonic();members={};by_hash={};mapping={};missing=[];indexes=[]
    token=str(time.time_ns());prefix='前期交接' if value['role']=='preparation' else '成品图片'
    archive=output/(prefix+'_'+token+'.zip')
    fd,temporary=tempfile.mkstemp(prefix='.packing-',suffix='.zip',dir=output);os.close(fd)
    path=Path(temporary)
    try:
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as z:
            def data(name,raw):
                portable_relative(name)
                if name in members:raise ValueError('重复交付成员:'+name)
                z.writestr(name,raw);members[name]=hashlib.sha256(raw).hexdigest()
            def obj(name,item):data(name,(json.dumps(item,ensure_ascii=False,indent=2)+'\n').encode())
            def add(source,name,expected=None):
                portable_relative(name)
                if name in members:
                    if expected and members[name]!=expected:raise ValueError('交付成员冲突')
                    return name
                before=source.stat();h=hashlib.sha256()
                with source.open('rb') as src,z.open(name,'w',force_zip64=True) as dest:
                    for chunk in iter(lambda:src.read(1024*1024),b''):h.update(chunk);dest.write(chunk)
                after=source.stat()
                if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns) or (expected and h.hexdigest()!=expected):
                    raise ValueError('SNAPSHOT_CHANGED:'+str(source))
                members[name]=h.hexdigest();by_hash.setdefault(h.hexdigest(),name);return name
            def refs(node,root,relative_base=None):
                if isinstance(node,list):
                    for v in node:refs(v,root,relative_base)
                elif isinstance(node,dict):
                    if isinstance(node.get('path'),str) and isinstance(node.get('sha256'),str):
                        ref=node;key=str(root)+'|'+ref['path']+'|'+ref['sha256']
                        if key in mapping:return
                        raw=Path(ref['path']);candidates=[raw] if raw.is_absolute() else [root/raw, (relative_base or root)/raw]
                        source=next((p for p in candidates if p.is_file() and not p.is_symlink() and digest(p)==ref['sha256']),None)
                        if source is None:
                            mapping[key]={'source':ref,'status':'MISSING_OR_CHANGED'};missing.append(mapping[key]);return
                        name=by_hash.get(ref['sha256']) or '依据/'+ref['sha256']+'/'+source.name
                        mapping[key]={'source':ref,'root':str(root),'member':name}
                        add(source,name,ref['sha256'])
                        if source.suffix.lower()=='.json':
                            try:child=read(source)
                            except (ValueError,UnicodeError):return
                            refs(child,root,source.parent)
                    else:
                        for child in node.values():refs(child,root,relative_base)
            snapshots={}
            for sp,scope in zip(value['states'],value['scope']):
                state_path=Path(sp);raw=state_path.read_bytes();state=json.loads(raw);root=state_path.parent.parent
                if state.get('cancelled'):raise ValueError('用户取消；不得自动继续交付')
                snapshots[sp]=hashlib.sha256(raw).hexdigest();eid=scope[1];portable_relative(eid)
                data(eid+'/原生产状态.json',raw)
                source_ref=state.get('source_snapshot',{});source_path=root/source_ref.get('path','')
                source=read(source_path) if source_path.is_file() and digest(source_path)==source_ref.get('sha256') else {}
                records={r['panel_id']:r for r in state.get('panels',[])}
                source_order=source.get('panel_ids') or source.get('id_mapping',{}).get('panel_ids')
                order=source_order or list(records)
                source_verified=bool(source_order) and len(order)==len(set(order)) and set(order)==set(records)
                rows=[]
                for pid in order:
                    portable_relative(pid)
                    row=records.get(pid,{})
                    item={'panel_id':pid,'current_status':row.get('status','MISSING'), 'outcome':'INCOMPLETE',
                          'issues':[],'incomplete_reasons':[], 'qa_status':'UNREVIEWED'}
                    attempt=None
                    if row.get('adoption'):
                        try:
                            attempt,decision,qa,decision_ref=selected(root,row)
                            item.update(attempt_id=attempt['attempt_id'],image=attempt['output'],
                                qa_report=attempt['qa_report'],decision=decision_ref,issues=decision['issues'],
                                adoption_reason=row['adoption']['reason'],qa_status=qa.get('status','UNREVIEWED'))
                            incomplete=any(i['certainty']=='unverified' for i in decision['issues']) or decision['action'] in {'needs_user','local_edit','regenerate','rebuild_inputs','crop_candidate'}
                            required=('camera_match','shot_scale_match','background_view_match','body_crop_match','required_visible_information_preserved','no_extra_offscreen_characters')
                            if state.get('image_review_profile')=='light_story_review_v1':
                                from light_review import review_errors
                                incomplete=incomplete or bool(review_errors(qa))
                                item['qa_status']=qa['light_review']['status']
                                item['image_review_profile']='light_story_review_v1'
                            else:incomplete=incomplete or any(type(qa.get(k)) is not bool for k in required)
                            item['outcome']=outcome(decision,complete=not incomplete)
                            if incomplete:item['incomplete_reasons'].append('已有逐图审核尚有未核实/未检查项')
                            item['batch_revalidation']='NOT_RERUN_AT_DELIVERY'
                        except (ValueError,KeyError,TypeError,OSError) as exc:
                            # Never silently substitute latest for a broken adopted version.
                            item['incomplete_reasons'].append('采用依据不可验证:'+str(exc));attempt=None
                    elif row.get('output'):
                        attempt=row;item.update(attempt_id=row.get('attempt_id','candidate'),image=row['output'])
                        item['incomplete_reasons'].append('未登记采用/未完成审核；仅提供候选图')
                    else:item['incomplete_reasons'].append('缺图或在途/结果未知，保留原状态，不重发')
                    if attempt:
                        image=attempt.get('output',{});source_image=root/image.get('path','')
                        if source_image.is_file() and not source_image.is_symlink():
                            name=f"{eid}/图片/{pid}_{item['attempt_id']}{source_image.suffix.lower()}"
                            try:
                                add(source_image,name,image.get('sha256'))
                                item['delivered_image']={'path':name[len(eid)+1:],'sha256':members[name]}
                            except ValueError:raise  # Do not publish changed image bytes.
                        else:item['outcome']='INCOMPLETE';item['incomplete_reasons'].append('所选图片不存在')
                    if row.get('status') in {'IN_FLIGHT','RESULT_UNKNOWN','PENDING','REPAIR_AUTHORIZED','GENERATED','CANCELLED'}:
                        item['outcome']='INCOMPLETE';item['incomplete_reasons'].append('当前尝试未闭合；采用旧图不清除在途或待审记录')
                    if value['role']=='preparation':
                        item['incomplete_reasons'].append('前期材料交接；可执行性见原审查记录，未补造批准')
                    if value['role']=='production' and not attempt and row.get('content_refusal_delivery'):
                        from no_image_recovery import content_refusal,content_missing_summary
                        exception=content_refusal(state,root,row)
                        item.update(outcome='CONTENT_REFUSED',content_refusal=exception,
                            incomplete_reasons=[content_missing_summary(exception)])
                    if value['role']=='production' and not attempt and row.get('network_retry_exhausted'):
                        from no_image_recovery import network_exhaustion, network_missing_summary
                        exception=network_exhaustion(state,root,row)
                        item.update(outcome='NETWORK_FAILED',network_failure=exception,
                            incomplete_reasons=[network_missing_summary(exception)])
                    item['label']=LABELS[item['outcome']];rows.append(item)
                index={'episode_id':eid,'book_id':scope[0],'panel_ids':order,'panels':rows,
                    'source_order_verified':source_verified,'image_review_profile':state.get('image_review_profile','full'),'counts':dict(Counter(r['outcome'] for r in rows))}
                indexes.append(index);obj(eid+'/交付索引.json',index)
                from delivery_csv import render
                for name,raw_csv in render([index]).items():data(eid+'/'+name,raw_csv)
                refs(state,root)
            # Preserve the task's actual call/budget/clock/control records; never modify them.
            for folder in (identity.parent,):
                for record in sorted(folder.glob('*.json')):
                    if record.name==POINTER:continue
                    add(record,'任务记录/'+record.name)
            for name,raw_csv in render(indexes,episode_prefix=True).items():data(name,raw_csv)
            obj('依据路径映射.json',list(mapping.values()))
            all_rows=[r for i in indexes for r in i['panels']]
            summary={'policy':POLICY,'role':value['role'],'scope':value['scope'],
                'counts':dict(Counter(r['outcome'] for r in all_rows)),
                'source_panel_count':len(all_rows),'image_count':sum(bool(r.get('delivered_image')) for r in all_rows),
                'source_scope_complete':all(i['source_order_verified'] for i in indexes),
                'images_complete':all(bool(r.get('delivered_image')) for r in all_rows),
                'network_missing_panel_ids':[i['episode_id']+'-'+r['panel_id'] for i in indexes for r in i['panels'] if r['outcome']=='NETWORK_FAILED'],
                'content_refused_panel_ids':[i['episode_id']+'-'+r['panel_id'] for i in indexes for r in i['panels'] if r['outcome']=='CONTENT_REFUSED'],
                'missing_references':missing,'state_snapshots':snapshots,
                'complete_scope':value['role']=='production' and bool(all_rows) and all(i['source_order_verified'] for i in indexes) and all((r.get('delivered_image') and r['outcome']!='INCOMPLETE') or r['outcome'] in {'NETWORK_FAILED','CONTENT_REFUSED'} for r in all_rows),
                'all_usable':bool(all_rows) and all(r['outcome'] in {'DELIVERABLE','MANUAL_RETOUCH'} for r in all_rows),
                'preparation_executable':False if value['role']=='preparation' else None,
                'visual_qa_changed':False,'production_state_changed':False,'image_calls':0,
                'deadline_due_wall':clock.get('delivery_due_wall'),'snapshot_started_wall':time.time()}
            obj('交付索引.json',summary)
            data('请先读.txt',('全部源格须有明确去向且按时发布；经授权、达到网络重试上限的缺格可附说明交付，不代表全部图齐全。其他缺项包仅为恢复材料。详见各话交付索引。\n'
                '原审核FAIL、未知请求、未审核和缺图保持原样；候选不表示可用。\n'
                '前期材料若未完成正式发布，不是可直接生图的正式包。原地址及便携依据文件见依据路径映射.json。\n'
                '未重复整话/跨话深验；按原审核记录使用，不据此生成新的批准。\n').encode('utf-8'))
            obj('文件清单.json',members.copy())
        # Writer already computes CRC. No second full-image read or deep QA at publication.
        with zipfile.ZipFile(path) as z:
            if len(z.infolist())!=len(members):raise ValueError('ZIP成员清单不完整')
        # Metadata only; gap evidence was verified while constructing the index.
        if not summary['complete_scope']:
            archive=output/(('前期恢复材料_' if value['role']=='preparation' else '未完成恢复材料_')+token+'.zip')
        path.rename(archive)
        finished=time.time()
        report={**summary,'status':'FULL_RESULT_READY' if summary['complete_scope'] else 'INCOMPLETE_CHECKPOINT',
            'task_completed':summary['complete_scope'] and finished<=clock['delivery_due_wall'],
            'archive':reference(archive),'bytes':archive.stat().st_size,
            'published_wall':finished,'published_before_deadline':finished<=clock['delivery_due_wall'],
            'pack_seconds':time.monotonic()-started,'full_quality_guaranteed':False}
        atomic_json(output/(archive.stem+'.json'),report)
        atomic_json(identity.parent/POINTER,report)
        return report
    finally:path.unlink(missing_ok=True)


def complete(identity, receipt, archive):
    """Complete only the full, on-time scope. Incomplete checkpoint is never success."""
    identity=Path(identity).resolve();value=load_identity(identity);clock=schedule(identity)
    if clock['state'] not in {'RUNNING','FINISHED'} or not clock.get('remaining_seconds'):
        raise ValueError('FULL_RESULT_REQUIRED: 未在截止前完成验收')
    report=read(receipt);archive=Path(archive).resolve()
    if (report.get('policy')!=POLICY or report.get('role')!='production' or
        report.get('scope')!=value['scope'] or not report.get('task_completed') or
        report.get('deadline_due_wall')!=clock['delivery_due_wall'] or
        not isinstance(report.get('published_wall'),(int,float)) or report['published_wall']>clock['delivery_due_wall'] or
        report.get('status')!='FULL_RESULT_READY' or not report.get('complete_scope') or
        report.get('archive')!=reference(archive) or
        report.get('state_snapshots')!={p:digest(p) for p in value['states']}):
        raise ValueError('FULL_RESULT_REQUIRED: 缺格、待审、超时或内容变化，任务未完成')
    with zipfile.ZipFile(archive) as z:
        summary=json.loads(z.read('交付索引.json'))
        if any(report.get(k)!=v for k,v in summary.items()) or not summary.get('complete_scope'):
            raise ValueError('FULL_RESULT_REQUIRED: 交付摘要与包内实际范围不符')
        count=0;gaps=0
        for _,eid in value['scope']:
            index=json.loads(z.read(eid+'/交付索引.json'))
            if [r['panel_id'] for r in index['panels']]!=index['panel_ids']:
                raise ValueError('FULL_RESULT_REQUIRED: 缺源格')
            sp=next(p for p,s in zip(value['states'],value['scope']) if s[1]==eid)
            state=read(sp);root=Path(sp).parent.parent
            for row in index['panels']:
                if row['outcome']=='CONTENT_REFUSED':
                    from no_image_recovery import content_refusal
                    current=next(r for r in state['panels'] if r['panel_id']==row['panel_id'])
                    exception=content_refusal(state,root,current)
                    if not exception or row.get('content_refusal')!=exception or row.get('delivered_image'):
                        raise ValueError('CONTENT_REFUSAL_NOT_PROVEN')
                    count+=1;gaps+=1;continue
                if row['outcome']=='NETWORK_FAILED':
                    from no_image_recovery import network_exhaustion
                    current=next(r for r in state['panels'] if r['panel_id']==row['panel_id'])
                    exception=network_exhaustion(state,root,current)
                    if not exception or row.get('network_failure')!=exception or row.get('delivered_image'):
                        raise ValueError('NETWORK_EXHAUSTION_NOT_PROVEN')
                    count+=1;gaps+=1;continue
                if row['outcome']=='INCOMPLETE' or eid+'/'+row.get('delivered_image',{}).get('path','') not in z.namelist():
                    raise ValueError('FULL_RESULT_REQUIRED: 缺图或未审')
                count+=1
        if count!=report['source_panel_count'] or count-gaps!=report['image_count']:
            raise ValueError('FULL_RESULT_REQUIRED: 数量不符')
    return report


def start_watch(identity):
    """Start a packaging-only process. No service calls, approvals or new call ledger."""
    identity=Path(identity).resolve();clock=schedule(identity)
    log=identity.parent/'限时封包日志.txt'
    args=[sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'watch','--contract',str(identity)]
    kwargs={'stdin':subprocess.DEVNULL,'stderr':subprocess.STDOUT}
    if os.name=='nt':kwargs['creationflags']=subprocess.CREATE_NEW_PROCESS_GROUP
    else:kwargs['start_new_session']=True
    with log.open('ab') as stream:
        proc=subprocess.Popen(args,stdout=stream,**kwargs)
    result={'policy':POLICY,'pid':proc.pid,'deadline_due_wall':clock['delivery_due_wall'],
            'log':str(log),'receipt':str(identity.parent/POINTER),'image_calls':0}
    atomic_json(identity.parent/'限时封包进程.json',result)
    return result


def watch(identity, *, poll_seconds=30):
    identity=Path(identity).resolve();last_key=None;last_pack=0.;last_duration=0.;completed_slots=set()
    # One packager per task, separate from production locks.
    with file_lock(identity.parent/'deadline-watch.lock'):
        while True:
            clock=schedule(identity)
            if clock['state']=='FINISHED':return
            if clock['state'] in {'PAUSED','WAIT_USER'}:
                if clock.get('remaining_seconds')==0:return
                time.sleep(poll_seconds);continue  # An explicit stop is respected, never hidden work.
            if clock['state']!='RUNNING':return
            remaining=clock.get('remaining_seconds')
            if remaining is None:return
            value=load_identity(identity)
            key=tuple((p,digest(p)) for p in value['states'])
            limit=clock['limit_seconds']
            thresholds=[limit*.5, min(1800,limit*.125), min(900,limit*.0625)]
            slot=sum(remaining<=t for t in thresholds)
            if slot and slot not in completed_slots and key!=last_key and time.monotonic()-last_pack>=min(60,limit/20):
                try:
                    report=export(identity);last_duration=report['pack_seconds'];last_key=key;last_pack=time.monotonic();completed_slots.add(slot)
                    print(json.dumps({'status':report['status'],'archive':report['archive'],'published_before_deadline':report['published_before_deadline']},ensure_ascii=False),flush=True)
                except (ValueError,OSError,KeyError,TypeError) as exc:
                    print(json.dumps({'status':'PACKAGE_ERROR','error':str(exc)},ensure_ascii=False),flush=True)
                    # Prior successful archives remain available. No destructive cleanup/retry loop.
                    last_pack=time.monotonic()
            if remaining<=0:return
            # Wake before the next slot, also for explicitly shortened budgets.
            upcoming=[remaining-t for t in thresholds if remaining>t]
            time.sleep(min(poll_seconds,max(.05,min(upcoming) if upcoming else remaining)))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['export','watch'])
    p.add_argument('--contract',required=True);p.add_argument('--output');a=p.parse_args()
    if a.action=='watch':watch(a.contract);return 0
    result=export(a.contract,a.output);print(json.dumps(result,ensure_ascii=False))
    return 0 if result['task_completed'] else 2

if __name__=='__main__':
    from platform_io import configure_stdio
    configure_stdio();raise SystemExit(main())
