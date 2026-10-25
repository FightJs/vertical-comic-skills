"""Validated publication of preparation transport or ordinary panel ZIPs.

Packaging only. Original inputs, adopted image bytes, approvals and budgets stay
unchanged. A raw release is an intermediate artifact, never delivery completion.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from platform_io import atomic_json, file_lock, portable_relative
from delivery_contract import (POLICY, read, digest, fingerprint, reference, checked,
    load_identity, validate_artifact_set, validate_receipt, state_bindings)

REPORT = '交付验收.json'
PART_INDEX = '分包索引.json'


def verify_preparation_source(value, source):
    from handoff_zip import check_delivery_archive, read_zip_json, zip_inventory, INDEX
    from production_progress import source_order, Records
    check_delivery_archive(source)
    with zipfile.ZipFile(source) as z:
        top,_=zip_inventory(z);index=read_zip_json(z,top+'/'+INDEX)
    if [[index['book_id'],e['episode_id']] for e in index['episodes']] != value['scope']:
        raise ValueError('DELIVERY_SCOPE_HOLD:正式包书话范围不符')
    for sp, record in zip(value['states'], index['episodes']):
        state=read(sp);root=Path(sp).parent.parent
        if record['panel_ids'] != source_order(state,root,Records()):
            raise ValueError('DELIVERY_SCOPE_HOLD:正式包源格序不符')
        for key in ('source_script','source_snapshot','visual_basis','shot_manifest'):
            if record[key]['sha256'] != state[key]['sha256']:
                raise ValueError('DELIVERY_SCOPE_HOLD:正式包与当前批准依据不符:'+key)
        current={r['sha256'] for refs in state.get('generation_packages',{}).values() for r in refs}
        if {r['sha256'] for r in record.get('generation_review_packages',[])} != current:
            raise ValueError('DELIVERY_SCOPE_HOLD:正式包执行包版本不符')
    return index


def production_basis(value):
    from panel_delivery import build,gate
    rows=[]
    for sp,scope in zip(value['states'],value['scope']):
        state=read(sp);root=Path(sp).parent.parent
        if [state.get('book_id'),state.get('episode_id')] != scope:
            raise ValueError('DELIVERY_SCOPE_HOLD:成品状态范围不符')
        ref=state.get('delivery_review')
        result=gate(state,root,ref)
        if result['status']!='PASS' or not result['handoff_complete']:
            raise ValueError('DELIVERY_CONTENT_HOLD:成品原门禁未通过:'+scope[1])
        review=build(state,root)
        if read(checked_local(root,ref)) != review:
            raise ValueError('DELIVERY_CONTENT_HOLD:采用审查版本变化')
        rows.append((state,root,review,ref))
    return rows


def checked_local(root,ref):
    from codex_reference_contract import checked_file
    return checked_file(root,ref)


def production_expected(value):
    expected={};indexes={}
    for state,root,review,ref in production_basis(value):
        eid=state['episode_id'];index=copy.deepcopy(review)
        for row in index['panels']:
            if not row.get('image'):
                raise ValueError('DELIVERY_CONTENT_HOLD:完整成品范围缺采用图:'+row['panel_id'])
            source=checked_local(root,row['image'])
            target=f"图片/{row['panel_id']}_{row['attempt_id']}{source.suffix.lower()}"
            portable_relative(target)
            row['delivered_image']={'path':target,'sha256':row['image']['sha256']}
            expected[eid+'/'+target]=row['image']['sha256']
        indexes[eid]=index
        # Exact review bytes are retained; the readable issue table is separately
        # bound by the publisher's member inventory and source index.
        expected[eid+'/交接审查依据.json']=digest(checked_local(root,ref))
    if value.get('csv_policy'):
        from delivery_csv import render
        for eid,index in indexes.items():
            for name,data in render([index]).items():expected[eid+'/'+name]=hashlib.sha256(data).hexdigest()
        for name,data in render(list(indexes.values()),episode_prefix=True).items():expected[name]=hashlib.sha256(data).hexdigest()
    return expected,indexes


def verify_production_files(value, artifacts, members):
    expected,indexes=production_expected(value)
    allowed=set(expected)
    for eid in indexes: allowed.update({eid+'/交付索引.json',eid+'/问题表.md'})
    if set(members)!=allowed:
        raise ValueError('DELIVERY_MEMBERS_HOLD:成品成员清单缺项或夹带工作区文件')
    for name,h in expected.items():
        if members.get(name)!=h: raise ValueError('DELIVERY_IMAGE_HOLD:采用图片或依据哈希不符:'+name)
    seen={};parts=[]
    for artifact in artifacts:
        with zipfile.ZipFile(artifact['path']) as z:
            infos=z.infolist();names=[i.filename for i in infos]
            if len(names)!=len(set(names)) or z.testzip(): raise ValueError('DELIVERY_ZIP_HOLD:重复成员或CRC损坏')
            info=read_member(z,PART_INDEX)
            parts.append(info)
            for i in infos:
                name=i.filename
                if name==PART_INDEX:continue
                portable_relative(name)
                if i.is_dir() or (i.external_attr>>16)&0o170000==0o120000 or name not in members:
                    raise ValueError('DELIVERY_MEMBERS_HOLD:非允许成品成员:'+name)
                with z.open(i) as f:
                    h=hashlib.sha256()
                    for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
                if h.hexdigest()!=members[name]:raise ValueError('DELIVERY_IMAGE_HOLD:成品文件字节变化:'+name)
                if name in seen and '/图片/' in name:raise ValueError('DELIVERY_MEMBERS_HOLD:同一格在分包中重复出现')
                seen[name]=members[name]
                if name.endswith('/交付索引.json') and read_member(z,name)!=indexes[name.split('/')[0]]:
                    raise ValueError('DELIVERY_CONTENT_HOLD:成品索引与当前采用版本不符')
    if set(seen)!=allowed:raise ValueError('DELIVERY_MEMBERS_HOLD:缺分包或缺成品')
    common={'policy':POLICY,'scope':value['scope'],'member_digest':fingerprint(members),'count':len(artifacts)}
    if any(any(part.get(k)!=v for k,v in common.items()) for part in parts):
        raise ValueError('DELIVERY_PARTS_HOLD:分包索引范围不符')
    if (len({p.get('set_id') for p in parts})!=1 or not parts[0].get('set_id')
        or sorted(p.get('number',0) for p in parts)!=list(range(1,len(parts)+1))):
        raise ValueError('DELIVERY_PARTS_HOLD:缺卷、混卷或重复分包')
    return {'status':'PASS','kind':'ordinary_panel_zip_v1','member_count':len(members),
        'panel_count':sum(len(i['panels']) for i in indexes.values())}


def read_member(z,name):
    return json.loads(z.read(name).decode('utf-8-sig'))


def verify_receipt_content(value,report):
    if value['role']=='preparation':
        source=checked(report.get('source'))
        verify_preparation_source(value,source)
        from handoff_transport import check_receipt
        receipt=checked(report.get('transport_receipt'))
        check_receipt(receipt,source,requirements=value)
        transport=read(receipt)
        actual={str((receipt.parent/r['path']).resolve()) for r in transport['files']}
        if actual!={r['path'] for r in report['artifacts']}:
            raise ValueError('DELIVERY_SET_HOLD:发送集合与实际运输产物不一致')
    else:
        result=verify_production_files(value,report['artifacts'],report.get('members',{}))
        if report['content_validation']!=result:raise ValueError('DELIVERY_CONTENT_HOLD:成品核验摘要不符')


def artifact(path):
    return {**reference(path),'bytes':Path(path).stat().st_size}


def _publish(identity,output,operation,*,source=None):
    identity=Path(identity).resolve();value=load_identity(identity);output=Path(output).resolve()
    if output==identity.parent or output.is_relative_to(identity.parent):
        raise ValueError('DELIVERY_OUTPUT_HOLD:发送目录须在协调记录之外')
    key=fingerprint({'requirements':value,'states':state_bindings(value),
        'source':reference(source) if source is not None else None})
    waiting=time.monotonic()
    with file_lock(identity.parent/'delivery-publish.lock'):
        acquired=time.monotonic()
        if output.exists():
            if (output/REPORT).is_file():
                report=validate_receipt(value,output/REPORT);verify_receipt_content(value,report)
                if source is not None and report.get('source')!=reference(source):
                    raise ValueError('DELIVERY_SOURCE_HOLD:已有交付不是本次指定原包')
                return report
            raise ValueError('DELIVERY_OUTPUT_HOLD:输出必须为全新目录，不覆盖候选或原件')
        attempts_path=identity.parent/'打包尝试.json'
        log=read(attempts_path) if attempts_path.exists() else {'policy':POLICY,'attempts':[]}
        failures=[a for a in log['attempts'] if a.get('requirements_sha256')==fingerprint(value) and a.get('status') in {'FAILED','RUNNING'}]
        if any(a['input_key']==key for a in failures):
            raise ValueError('DELIVERY_REPACK_HOLD:相同输入/方案已经失败或终态未知，先查证并作实际修订')
        if len(failures)>=1+value['max_repack_attempts']:
            raise ValueError('DELIVERY_REPACK_HOLD:自动整理次数已用完，需明确不同方案或交付约束决定')
        attempt={'input_key':key,'requirements_sha256':fingerprint(value),'status':'RUNNING'}
        log['attempts'].append(attempt);atomic_json(attempts_path,log)
        before=state_bindings(value)
        try:
            operation_started=time.monotonic()
            report=operation(value,output)
            operation_finished=time.monotonic()
            if before!=state_bindings(value):raise ValueError('DELIVERY_CHANGED_HOLD:打包期间权威状态变化')
            report.update(policy=POLICY,status='DELIVERY_READY',role=value['role'],scope=value['scope'],
                requirements_sha256=fingerprint(value),states=before,image_calls=0,images_reencoded=False)
            report['total_bytes']=sum(r['bytes'] for r in report['artifacts'])
            validate_artifact_set(value,report['artifacts'])
            report['observed_packaging_timing']={'lock_wait_seconds':acquired-waiting,
                'pack_and_content_validation_seconds':operation_finished-operation_started,
                'postpack_verification_seconds':time.monotonic()-operation_finished}
            atomic_json(output/REPORT,report)
            validate_receipt(value,output/REPORT)
            attempt['status']='PASS';attempt['receipt']=reference(output/REPORT)
            atomic_json(attempts_path,log)
            return report
        except BaseException as exc:
            # Only the directory created by this publication call is cleaned.
            if output.is_dir():shutil.rmtree(output)
            attempt.update(status='FAILED',error=str(exc));atomic_json(attempts_path,log)
            raise


def publish_preparation(identity,source,output):
    source=Path(source).resolve()
    def operation(value,out):
        if value['role']!='preparation':raise ValueError('DELIVERY_SCOPE_HOLD:不是前期交付任务')
        verify_preparation_source(value,source)
        from handoff_transport import export
        transported=export(source,out,value['max_file_bytes'],package_mode=value['package_mode'])
        artifacts=[artifact(out/r['path']) for r in transported['files']]
        return {'artifacts':artifacts,'source':reference(source),
            'transport_receipt':reference(out/'运输验证.json'),
            'content_validation':{'status':'PASS','kind':'full_source_recovery_v1',
                'restored_files':transported['original_files']}}
    return _publish(identity,output,operation,source=source)


def pack_panels(value,stage,out):
    sources={p.relative_to(stage).as_posix():p for p in stage.rglob('*') if p.is_file()}
    members={name:digest(p) for name,p in sources.items()}
    _,indexes=production_expected(value)
    images=[eid+'/'+row['delivered_image']['path'] for _,eid in value['scope'] for row in indexes[eid]['panels']]
    metadata=sorted(name for name in sources if name not in images)
    groups=[images];set_id=uuid.uuid4().hex
    def write_group(names,target,number,count):
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
            for name in [*metadata,*names]:
                mode=zipfile.ZIP_STORED if sources[name].suffix.lower() in {'.png','.jpg','.jpeg','.webp'} else zipfile.ZIP_DEFLATED
                z.write(sources[name],name,compress_type=mode)
            z.writestr(PART_INDEX,json.dumps({'policy':POLICY,'scope':value['scope'],
                'member_digest':fingerprint(members),'set_id':set_id,'number':number,'count':count},ensure_ascii=False))
    with tempfile.TemporaryDirectory(dir=out.parent,prefix='.panel-zips-') as tmp:
        tmp=Path(tmp)
        while True:
            paths=[];oversized=[]
            for i,g in enumerate(groups):
                target=tmp/f'{i}.zip';write_group(g,target,i+1,len(groups));paths.append(target)
                if value['max_file_bytes'] is not None and target.stat().st_size>value['max_file_bytes']:oversized.append(i)
            if not oversized:break
            if value['package_mode']=='single_zip':
                size=paths[oversized[0]].stat().st_size
                raise ValueError(f"DELIVERY_SIZE_HOLD:实际ZIP {size}字节，上限{value['max_file_bytes']}，超出{size-value['max_file_bytes']}；不降质、不自动分包")
            if len(groups)==1 and len({n.split('/')[0] for n in images})>1:
                groups=[[n for n in images if n.startswith(eid+'/')] for _,eid in value['scope']]
                continue
            if any(len(groups[i])<2 for i in oversized):
                raise ValueError('DELIVERY_SIZE_HOLD:单幅采用图及必要索引已超限，不能无损继续分割')
            new=[]
            for i,g in enumerate(groups):
                if i in oversized:
                    mid=len(g)//2;new.extend([g[:mid],g[mid:]])
                else:new.append(g)
            groups=new
        out.mkdir()
        artifacts=[]
        for i,p in enumerate(paths):
            name='成品图片包.zip' if len(paths)==1 else f'成品图片包_第{i+1:03d}卷_共{len(paths):03d}卷.zip'
            dest=out/name;shutil.copyfile(p,dest);artifacts.append(artifact(dest))
    validate_artifact_set(value,artifacts)
    validation=verify_production_files(value,artifacts,members)
    return {'artifacts':artifacts,'members':members,'content_validation':validation}


def publish_production(identity,output):
    def operation(value,out):
        if value['role']!='production':raise ValueError('DELIVERY_SCOPE_HOLD:不是成品交付任务')
        from panel_delivery import export
        out.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=out.parent,prefix='.adopted-panels-') as tmp:
            stage=Path(tmp)
            for state,root,_,ref in production_basis(value):
                export(state,root,ref,stage/state['episode_id'])
            from delivery_csv import render,OVERVIEW,DETAILS
            if value.get('csv_policy'):
                _,indexes=production_expected(value)
                for name,data in render(list(indexes.values()),episode_prefix=True).items():(stage/name).write_bytes(data)
            else:
                # Legacy bounded contracts keep their frozen member layout.
                for _,eid in value['scope']:
                    for name in (OVERVIEW,DETAILS):(stage/eid/name).unlink(missing_ok=True)
            return pack_panels(value,stage,out)
    return _publish(identity,output,operation)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('role',choices=['preparation','production'])
    p.add_argument('--contract',required=True,help='本任务00_任务协调/交付身份.json')
    p.add_argument('--source-zip',help='已正式发布的前期内容包；不是候选ZIP')
    p.add_argument('--output',required=True)
    a=p.parse_args()
    try:
        if a.role=='preparation':
            if not a.source_zip:p.error('前期交付缺--source-zip')
            result=publish_preparation(a.contract,a.source_zip,a.output)
        else:result=publish_production(a.contract,a.output)
        print(json.dumps(result,ensure_ascii=False));return 0
    except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile) as exc:
        print(json.dumps({'status':'DELIVERY_HOLD','error':str(exc),'image_calls':0},ensure_ascii=False));return 1


if __name__=='__main__':
    from platform_io import configure_stdio
    configure_stdio();raise SystemExit(main())
