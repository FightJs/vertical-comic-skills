"""Task-bound delivery constraints. No QA synthesis, image calls or image rewriting."""
from __future__ import annotations
import hashlib
import json
import math
import uuid
from pathlib import Path
from platform_io import atomic_json

POLICY = 'validated_delivery_v1'
LIMIT = 900000000
CONTRACT = '交付要求.json'
IDENTITY = '交付身份.json'
CSV_POLICY = 'adopted_issue_csv_v1'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()


def reference(path):
    p = Path(path).resolve()
    return {'path':str(p), 'sha256':digest(p)}


def checked(ref):
    if not isinstance(ref, dict) or not Path(ref.get('path','')).is_absolute():
        raise ValueError('DELIVERY_CONTRACT_HOLD:缺正式交付记录引用')
    p = Path(ref['path'])
    if not p.is_file() or digest(p) != ref.get('sha256'):
        raise ValueError('DELIVERY_CONTRACT_HOLD:交付记录缺失或内容变化:'+str(p))
    return p


def validate_requirements(value):
    if not isinstance(value, dict) or value.get('policy') != POLICY:
        raise ValueError('DELIVERY_CONTRACT_HOLD:未知交付合同')
    if not value.get('task_id') or value.get('role') not in {'preparation','production'}:
        raise ValueError('DELIVERY_CONTRACT_HOLD:任务身份或职责不明')
    scope, states = value.get('scope'), value.get('states')
    if (not isinstance(scope,list) or not scope or any(not isinstance(x,list) or len(x)!=2
        or any(not isinstance(y,str) or not y for y in x) for x in scope)
        or len({tuple(x) for x in scope}) != len(scope) or len({x[0] for x in scope}) != 1
        or not isinstance(states,list) or len(states)!=len(scope)
        or any(not isinstance(x,str) or not Path(x).is_absolute() for x in states)
        or len(set(states)) != len(states)):
        raise ValueError('DELIVERY_CONTRACT_HOLD:准确书话与权威状态不完整')
    cap=value.get('max_file_bytes')
    unlimited=(value.get('role')=='production' and value.get('csv_policy')==CSV_POLICY and cap is None and value.get('package_mode')=='single_zip')
    if (not unlimited and (type(cap) is not int or not 65536 <= cap <= LIMIT)
        or value.get('package_mode') not in {'single_zip','allow_parts'}
        or value.get('image_policy') != 'preserve_adopted_bytes'
        or type(value.get('max_repack_attempts')) is not int or value.get('max_repack_attempts') != 1):
        raise ValueError('DELIVERY_CONTRACT_HOLD:容量/包数/保真/重打包约束无效')
    if value.get('csv_policy') is not None and not unlimited:
        raise ValueError('DELIVERY_CONTRACT_HOLD:新成品CSV合同不设容量限制或自动分包')
    return value


def initialize(run_root, role, states, *, package_mode=None, max_file_bytes=None, task_id=None):
    if role=='production':
        if package_mode not in (None,'single_zip') or max_file_bytes is not None:
            raise ValueError('成品交付不设容量限制、不自动分包；容量参数仅用于前期交接')
        package_mode='single_zip'
    else:
        package_mode=package_mode or 'allow_parts'
        max_file_bytes=LIMIT if max_file_bytes is None else max_file_bytes
    root = Path(run_root).resolve()/'00_任务协调'
    paths = [str(Path(p).resolve()) for p in states]
    scope = [[read(p)['book_id'],read(p)['episode_id']] for p in paths]
    identity = root/IDENTITY
    if identity.exists():
        old = load_identity(identity)
        requested = {**old,'role':role,'states':paths,'scope':scope,
            'package_mode':package_mode,'max_file_bytes':max_file_bytes}
        if task_id is not None: requested['task_id']=task_id
        if requested != old: raise ValueError('DELIVERY_CONTRACT_HOLD:交付范围已锁定，修改须显式建立新合同')
        return reference(identity)
    if (root/CONTRACT).exists(): raise ValueError('DELIVERY_CONTRACT_HOLD:已有未闭合交付合同，不能按旧模式重建')
    value = validate_requirements({'policy':POLICY,'task_id':task_id or uuid.uuid4().hex,
        'role':role,'scope':scope,'states':paths,'max_file_bytes':max_file_bytes,
        'package_mode':package_mode,'image_policy':'preserve_adopted_bytes','max_repack_attempts':1,
        **({'csv_policy':CSV_POLICY} if role=='production' else {})})
    root.mkdir(parents=True,exist_ok=True)
    # A partial initialization is a HOLD, not an implicit legacy task.
    atomic_json(root/CONTRACT,value)
    atomic_json(identity,{'policy':POLICY,'role':role,'scope':scope,'states':paths,
        'requirements':reference(root/CONTRACT)})
    return reference(identity)


def load_identity(path):
    marker = read(path)
    if marker.get('policy') != POLICY: raise ValueError('DELIVERY_CONTRACT_HOLD:交付身份错误')
    value = validate_requirements(read(checked(marker.get('requirements'))))
    if any(marker.get(k) != value[k] for k in ('role','scope','states')):
        raise ValueError('DELIVERY_CONTRACT_HOLD:交付身份与要求不符')
    for state, scope in zip(value['states'],value['scope']):
        row=read(state)
        if [row.get('book_id'),row.get('episode_id')] != scope:
            raise ValueError('DELIVERY_CONTRACT_HOLD:权威状态书话已改变')
    return value


def for_display(directory, task=None):
    directory=Path(directory).resolve();task=task or {}
    marker=directory.parent/'00_任务协调'/IDENTITY
    requirements=marker.parent/CONTRACT
    ref=task.get('delivery_identity')
    if ref:
        if checked(ref).resolve() != marker: raise ValueError('DELIVERY_CONTRACT_HOLD:任务交付身份地址不符')
    if ref or marker.exists() or requirements.exists() or task.get('completion_policy')==POLICY:
        if not marker.is_file(): raise ValueError('DELIVERY_CONTRACT_HOLD:正式交付身份缺失')
        value=load_identity(marker)
        if task and any(task.get(k)!=value[k] for k in ('role','scope','states')):
            raise ValueError('DELIVERY_CONTRACT_HOLD:显示任务不能换交付范围')
        return value,reference(marker)
    return None,None


def state_bindings(value):
    return {p:digest(p) for p in value['states']}


def validate_artifact_set(value, artifacts):
    validate_requirements(value)
    if not isinstance(artifacts,list) or not artifacts:
        raise ValueError('DELIVERY_SET_HOLD:缺实际发送文件')
    if value['package_mode']=='single_zip' and len(artifacts)!=1:
        raise ValueError('DELIVERY_COUNT_HOLD:严格单ZIP任务不得自动分包')
    seen=set()
    for row in artifacts:
        if not isinstance(row,dict) or not Path(row.get('path','')).is_absolute():
            raise ValueError('DELIVERY_SET_HOLD:发送文件须为本机准确绝对路径')
        path=Path(row['path'])
        if not path.is_file():raise ValueError('DELIVERY_SET_HOLD:发送文件缺失')
        if path.suffix.lower()!='.zip' or str(path) in seen:
            raise ValueError('DELIVERY_SET_HOLD:发送ZIP重复或格式不符')
        seen.add(str(path));size=path.stat().st_size
        if row.get('bytes')!=size: raise ValueError('DELIVERY_SIZE_HOLD:大小记录不符')
        if value['max_file_bytes'] is not None and size > value['max_file_bytes']:
            raise ValueError(f"DELIVERY_SIZE_HOLD:{path.name}实际{size}字节，上限{value['max_file_bytes']}，超出{size-value['max_file_bytes']}字节")
        checked(row)
    return artifacts


def validate_receipt(value, receipt_path):
    report=read(receipt_path)
    if (report.get('policy')!=POLICY or report.get('status')!='DELIVERY_READY'
        or report.get('requirements_sha256')!=fingerprint(value)
        or report.get('role')!=value['role'] or report.get('scope')!=value['scope']
        or report.get('states')!=state_bindings(value)
        or report.get('image_calls')!=0 or report.get('images_reencoded') is not False):
        raise ValueError('DELIVERY_RECEIPT_HOLD:验收记录未绑定当前合同/范围/采用状态')
    artifacts=validate_artifact_set(value,report.get('artifacts'))
    if report.get('total_bytes') != sum(x['bytes'] for x in artifacts):
        raise ValueError('DELIVERY_RECEIPT_HOLD:交付总量不符')
    if report.get('content_validation',{}).get('status')!='PASS':
        raise ValueError('DELIVERY_RECEIPT_HOLD:缺实际内容核验')
    return report


def assert_completion(value, receipt_path, archive):
    report=validate_receipt(value,receipt_path)
    if str(Path(archive).resolve()) not in {x['path'] for x in report['artifacts']}:
        raise ValueError('DELIVERY_SET_HOLD:完成入口必须指向实际发送ZIP，不是内部原包')
    from delivery_publish import verify_receipt_content
    verify_receipt_content(value,report)
    return report


def capacity_summary(states, total=None):
    # Only adopted files and stat metadata; no image decoding, archive or pixel reads.
    count=size=0;missing=[]
    for sp in states:
        state=read(sp);root=Path(sp).parent.parent
        for row in state.get('panels',[]):
            adoption=row.get('adoption') or {}
            if not adoption.get('attempt_id'): continue
            attempts=[*row.get('attempt_history',[]),row]
            selected=[a for a in attempts if a.get('attempt_id')==adoption['attempt_id']]
            if len(selected)!=1 or not selected[0].get('output'): continue
            ref=selected[0]['output'];p=Path(ref['path']);p=p if p.is_absolute() else root/p
            try: size+=p.stat().st_size;count+=1
            except OSError: missing.append(str(p))
    return {'adopted_files':count,'adopted_bytes':size,'missing_files':missing,
        'estimated_image_bytes':math.ceil(size/count*total) if count and total is not None else None,
        'estimate_only':True,'actual_zip_bytes':None}
