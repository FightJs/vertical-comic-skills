#!/usr/bin/env python3
"""Coordinator assigns capacity; episode owners atomically own request ledgers.

No time-based reclamation or automatic retries. Shared control is written only
by allocate(); owners update dispatch_ledger in their existing state transaction.
"""
from __future__ import annotations
import argparse
import copy
import fcntl
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from codex_reference_contract import digest, read_json, checked_file

POLICY = 'episode_slot_lease_v1'
ACTIVE = {'RESERVED','IN_FLIGHT','RESULT_UNKNOWN'}


def enabled(control):return control.get('dispatch_policy')==POLICY


def effective_control(control, state, context):
    """Present the local ledger to the unchanged receipt and scope validators."""
    if not enabled(control):return control
    if control.get('permits'):
        raise ValueError('LEASE_HOLD: 租约不能混入旧共享permit')
    if state.get('execution_mode')!='episode_async_v1':raise ValueError('租约只用于整话新RV')
    if state.get('runtime',{}).get('dispatch_policy')!=POLICY:raise ValueError('本话未显式启用租约策略')
    jobs=control.get('jobs',[]);total=0;lease_ids=[]
    for job in jobs:
        lease=job.get('slot_lease')
        if not lease:continue
        if (type(lease.get('slots')) is not int or lease['slots']<1 or
                lease.get('worker_id')!=job.get('worker_id') or lease.get('epoch')!=control.get('epoch')
                or not lease.get('lease_id') or lease['slots']>job.get('max_inflight',0)
                or job.get('status') not in {'ASSIGNED','RUNNING','WAIT_REVIEW','HOLD','COMPLETED','CANCELLED'}):
            raise ValueError('LEASE_HOLD: 分配额度或owner无效')
        total+=lease['slots'];lease_ids.append(lease['lease_id'])
    if len(set(lease_ids))!=len(lease_ids) or total>control.get('max_inflight',0):
        raise ValueError('LEASE_HOLD: 重复租约或全局超额')
    job=next(j for j in jobs if j['job_id']==context['job_id'])
    lease=job.get('slot_lease')
    ledger=state.get('dispatch_ledger',[])
    if not isinstance(ledger,list):raise ValueError('LEASE_HOLD: 请求账本无效')
    for item in ledger:
        if item.get('job_id')!=job['job_id'] or not item.get('lease_id'):
            raise ValueError('LEASE_HOLD: 请求不属于本话租约')
        grants=[*(control.get('lease_history',[])), *([{**lease,'job_id':job['job_id']}] if lease else [])]
        if not any(all(item.get(k)==g.get(k) for k in ('lease_id','epoch','worker_id','job_id')) for g in grants):
            raise ValueError('LEASE_HOLD: 请求缺少原真实租约分配')
        if item.get('status') in ACTIVE:
            if not lease or any(item.get(k)!=lease.get(k) for k in ('lease_id','epoch','worker_id')):
                raise ValueError('LEASE_HOLD: 活动请求不能转移owner或epoch')
    if len([x for x in ledger if x.get('status') in ACTIVE])>(lease or {}).get('slots',0):
        raise ValueError('LEASE_HOLD: 本话超租约额度')
    return {**control,'permits':ledger}


def advance(state, pid, status, output=None):
    """Called only after full preflight or actual return/QA evidence validation."""
    row=next(p for p in state['panels'] if p['panel_id']==pid)
    entries=[p for p in state.get('dispatch_ledger',[]) if p.get('status')!='RELEASED' and p.get('panel_id')==pid
             and p.get('attempt_id')==row['attempt_id'] and p.get('round_id')==row['round_id']]
    if len(entries)!=1:raise ValueError('LEASE_HOLD: 缺少唯一准确尝试回执')
    item=entries[0]
    expected={'IN_FLIGHT':{'RESERVED'},'GENERATED':{'IN_FLIGHT','RESULT_UNKNOWN'},
              'RESULT_UNKNOWN':{'IN_FLIGHT'},'CALL_FAILED':{'IN_FLIGHT','RESULT_UNKNOWN'}}
    if status not in expected:return
    if item.get('status') not in expected[status]:raise ValueError('LEASE_HOLD: 调度状态转换无效')
    target={'GENERATED':'COMPLETED','CALL_FAILED':'COMPLETED'}.get(status,status)
    item.setdefault('events',[]).append({'from':item['status'],'to':target,
        'at':datetime.now(timezone.utc).isoformat(),'evidence_status':status})
    item['status']=target
    if status=='GENERATED':item['output_sha256']=output['sha256']


def resolution_errors(state, root, original, update, report):
    errors=[]
    expected={'policy':'unknown_result_resolution_v1','status':'REVIEWED',
              'panel_id':original['panel_id'],'attempt_id':original['attempt_id'],
              'round_id':original['round_id'],'original_call_evidence':original.get('call_evidence')}
    if state.get('runtime',{}).get('dispatch_policy')!=POLICY or original.get('status')!='RESULT_UNKNOWN':
        errors.append('只允许查证原租约未知请求，不增加新尝试')
    if any(report.get(k)!=v for k,v in expected.items()) or not original.get('call_evidence'):
        errors.append('未知查证报告与原请求不一致')
    conclusion={'GENERATED':'RESULT_RECOVERED','CALL_FAILED':'CONFIRMED_NO_OUTPUT'}.get(update.get('status'))
    if not conclusion or report.get('conclusion')!=conclusion or not all(report.get(k) for k in ('reviewer','evidence','source_locator')):
        errors.append('须有实际查证结果、审查者和来源；超时不证明无输出')
    try:
        checked_file(Path(root),original.get('call_evidence'))
        checked_file(Path(root),report.get('service_evidence'))
    except (OSError,ValueError,TypeError) as exc:errors.append(str(exc))
    return errors


def allocate(control_path, expected_sha256, allocations, *, old_writers_stopped=False):
    """Root-only operation. Lock each old owner's state before moving any slots."""
    from contextlib import ExitStack
    from episode_dispatch_queue import _atomic_json
    path=Path(control_path).resolve()
    if not isinstance(allocations,dict) or not allocations or any(type(x) is not int or x<0 for x in allocations.values()):
        raise ValueError('须明确每话非负整数额度')
    initial=read_json(path)
    jobs=initial.get('jobs',[])
    if set(allocations)!={j['job_id'] for j in jobs}:raise ValueError('须覆盖全部job，未派发填0')
    if sum(allocations.values())>initial.get('max_inflight',0):raise ValueError('全局租约额度超限')
    if initial.get('dispatch_policy') not in (None,POLICY):raise ValueError('未知调度策略')
    if any(p.get('status') in ACTIVE for p in initial.get('permits',[])):
        raise ValueError('旧permit仍活动，不得切换')
    # Every prior lease is replaced, so all former owners must be quiescent.
    if enabled(initial) and not old_writers_stopped:raise ValueError('重新分配前须确认旧写入者已停止')
    states=[]
    for job in jobs:
        root=Path(job['root']).resolve(); name=Path(job.get('state_file','00_输入审计/生产流程.json'))
        state_path=(root/name).resolve()
        if name.is_absolute() or not state_path.is_relative_to(root):raise ValueError('state_file越界')
        if allocations[job['job_id']] or job.get('slot_lease'):
            states.append((job,state_path))
    locks=sorted({path.with_suffix('.dispatch.lock'),*(p.with_suffix('.runtime.lock') for _,p in states)})
    with ExitStack() as stack:
        for lock_path in locks:
            lock=stack.enter_context(lock_path.open('a'));fcntl.flock(lock,fcntl.LOCK_EX)
        if digest(path)!=expected_sha256:raise ValueError('CONTROL_CHANGED')
        for job,state_path in states:
            state=read_json(state_path)
            if state.get('execution_mode')!='episode_async_v1' or state.get('runtime',{}).get('dispatch_policy')!=POLICY:
                raise ValueError('须新整话RV明确租约策略')
            context=state.get('parallel_context',{})
            if (state.get('episode_id')!=job['episode_id'] or state.get('book_id')!=initial.get('book_id')
                    or Path(context.get('control_file','')).resolve()!=path
                    or any(context.get(k)!=v for k,v in {'job_id':job['job_id'],
                        'worker_id':job['worker_id'],'epoch':initial['epoch']}.items())):
                raise ValueError('本话唯一owner/上下文与分配不一致')
            if any(p.get('status') in ACTIVE for p in state.get('dispatch_ledger',[])) or any(
                    p.get('status') in {'IN_FLIGHT','RESULT_UNKNOWN'} for p in state.get('panels',[])):
                raise ValueError('活动或未知请求占槽；不得按时间收回')
        new=copy.deepcopy(initial);new['dispatch_policy']=POLICY;new['permits']=[]
        # Preserve legacy and historical receipts for audit; never manufacture completion.
        if initial.get('permits'):new.setdefault('legacy_permit_history',[]).extend(initial['permits'])
        for job in new['jobs']:
            if job.get('slot_lease'):new.setdefault('lease_history',[]).append({**job['slot_lease'],'job_id':job['job_id']})
            count=allocations[job['job_id']]
            if count:
                if (count>job.get('max_inflight',0) or not job.get('worker_id')
                        or job.get('status') not in {'ASSIGNED','RUNNING'} or job.get('active_batch_id')!='EPISODE'):
                    raise ValueError('本话容量/owner/活动范围无效')
                job['slot_lease']={'lease_id':uuid.uuid4().hex,'slots':count,
                                  'worker_id':job['worker_id'],'epoch':new['epoch']}
            else:job.pop('slot_lease',None)
        _atomic_json(path,new)
    return {'status':'LEASES_ASSIGNED','control_sha256':digest(path),'image_calls':0}


def release_unsubmitted(state_path, expected_sha256, panel_ids):
    """Release only RESERVED requests; restore their unchanged original packets."""
    from episode_dispatch_queue import _atomic_json
    path=Path(state_path).resolve();root=path.parent.parent
    with path.with_suffix('.runtime.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if digest(path)!=expected_sha256:raise ValueError('STATE_CHANGED')
        state=read_json(path)
        if state.get('runtime',{}).get('dispatch_policy')!=POLICY:raise ValueError('仅租约入口')
        if not panel_ids or len(set(panel_ids))!=len(panel_ids):raise ValueError('格号须明确且不重复')
        for pid in panel_ids:
            row=next(r for r in state['panels'] if r['panel_id']==pid)
            packet=read_json(checked_file(root,row['package_manifest']))
            receipt=packet['dispatch_receipt']
            entry=next(p for p in state['dispatch_ledger'] if p['permit_id']==receipt['permit_id'])
            if entry['status']!='RESERVED' or row['status'] not in {'PENDING','REPAIR_AUTHORIZED'}:
                raise ValueError('已进入提交窗口或未知结果不能释放')
            source=packet['dispatch_source_package'];checked_file(root,source)
            row['package_manifest']=source;entry['status']='RELEASED'
        _atomic_json(path,state)
    return {'status':'RELEASED','state_sha256':digest(path),'image_calls':0}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--control');p.add_argument('--state')
    p.add_argument('--expected-sha256',required=True);p.add_argument('--allocations')
    p.add_argument('--old-writers-stopped',action='store_true');p.add_argument('--release-panels',nargs='+')
    a=p.parse_args()
    if a.release_panels:result=release_unsubmitted(a.state,a.expected_sha256,a.release_panels)
    else:result=allocate(a.control,a.expected_sha256,json.loads(Path(a.allocations).read_text()),old_writers_stopped=a.old_writers_stopped)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
