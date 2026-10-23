#!/usr/bin/env python3
"""Durable coordinator checkpoints, not a scheduler or production authorization.

Only the coordinator writes. CAS revisions reject stale coordinators; host status
is observed by the caller, never inferred from elapsed time or a worker's prose.
"""
from pathlib import Path
import argparse
import hashlib
import json
from platform_io import atomic_json, file_lock, configure_stdio

POLICY = 'task_coordination_v1'
STATUSES = {'RUNNING', 'UNKNOWN', 'RESULT_READY', 'FAILED', 'STOPPED'}

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()

def reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': digest(path)}

def verify(ref):
    if not isinstance(ref, dict) or not Path(ref.get('path', '')).is_absolute():
        raise ValueError('证据须为准确绝对文件路径和SHA256')
    if digest(ref['path']) != ref.get('sha256'): raise ValueError('证据内容已变化')

def initialize(directory, display):
    directory, display = Path(directory).resolve(), Path(display).resolve()
    task = read(display/'task.json')
    directory.mkdir(parents=True, exist_ok=True)
    with file_lock(directory/'coordination.lock'):
        path = directory/'coordination.json'
        if path.exists():
            value = read(path)
            if value['display'] != str(display) or value['scope'] != task['scope']:
                raise ValueError('已有协调记录范围不符')
            return value
        value = {'policy': POLICY, 'revision': 0, 'display': str(display),
                 'scope': task['scope'], 'tasks': {}, 'events': [], 'checkpoint': None}
        atomic_json(path, value)
        return value

def update(directory, expected_revision, event):
    directory = Path(directory)
    with file_lock(directory/'coordination.lock'):
        path = directory/'coordination.json'; value = read(path)
        if value['policy'] != POLICY: raise ValueError('未知协调协议')
        # A response lost after commit can be recovered without replaying it.
        if not isinstance(event.get('event_id'), str) or not event['event_id'].strip():
            raise ValueError('缺唯一事件ID')
        previous = next((e for e in value['events'] if e['event_id'] == event['event_id']), None)
        if previous is not None:
            if previous != event: raise ValueError('同一事件ID内容冲突')
            return value
        if value['revision'] != expected_revision: raise ValueError('STALE_COORDINATOR:重新读取检查点')
        action = event.get('action'); key = event.get('task_id')
        if action == 'register':
            if not isinstance(key, str) or not key.strip() or key in value['tasks']:
                raise ValueError('子任务ID缺失或重复，不自动重新派发')
            if not event.get('host_id') or not event.get('assignment'):
                raise ValueError('缺宿主任务标识或职责')
            if type(event.get('required', True)) is not bool: raise ValueError('required须为布尔值')
            value['tasks'][key] = {'host_id': event['host_id'], 'assignment': event['assignment'],
                'required': event.get('required', True), 'status': 'RUNNING', 'artifacts': []}
        elif action in {'observe', 'accept'}:
            item = value['tasks'][key]
            verify(event.get('evidence'))
            if action == 'observe':
                status = event.get('status')
                if status not in STATUSES: raise ValueError('无效宿主状态')
                # Observations can invalidate acceptance, never manufacture it.
                artifacts = event.get('artifacts', [])
                if status == 'RESULT_READY' and not artifacts: raise ValueError('结束但缺实际成果')
                for ref in artifacts: verify(ref)
                item.update(status=status, artifacts=artifacts, observation=event['evidence'])
                item.pop('acceptance', None)
            else:
                if item['status'] != 'RESULT_READY': raise ValueError('须先核实执行已结束且结果待验收')
                for ref in item['artifacts']: verify(ref)
                if not event.get('reviewer') or not event.get('conclusion'):
                    raise ValueError('缺实际验收人员与结论')
                item.update(status='ACCEPTED', acceptance=event['evidence'])
        elif action == 'work':
            from issue_disposition import ADVISORY
            work_id=event.get('work_id');status=event.get('status')
            if not work_id or status not in {'OPEN','RESOLVED'} or not event.get('scope') or not event.get('next_action'):
                raise ValueError('工作项须有稳定ID、范围、状态和下一步')
            blocking=event.get('blocks_delivery',True)
            if type(blocking) is not bool or not blocking and event.get('code') not in ADVISORY:
                raise ValueError('只有明确可选建议可不阻断交付')
            if status=='RESOLVED': verify(event.get('evidence'))
            works=value.setdefault('work_items',{});old=works.get(work_id,{})
            attempts=old.get('attempts',0)+(1 if status=='OPEN' else 0)
            works[work_id]={'scope':event['scope'],'status':status,'blocks_delivery':blocking,
                            'next_action':event['next_action'],'attempts':attempts,
                            'common_cause_diagnosis_due':attempts>=2,
                            **({'evidence':event['evidence']} if status=='RESOLVED' else {})}
        elif action == 'checkpoint':
            if not event.get('next_action'): raise ValueError('缺恢复下一步')
            verify(event.get('evidence'))
            value['checkpoint'] = {k: event[k] for k in ('next_action', 'evidence')}
        else: raise ValueError('未知协调动作')
        value['events'].append(event); value['revision'] += 1
        value.pop('finish', None)
        atomic_json(path, value)
        return value

def pending(value):
    blockers = []
    for key, item in value['tasks'].items():
        status = item['status']
        if status == 'ACCEPTED':
            try:
                verify(item['observation']); verify(item['acceptance'])
                for ref in item['artifacts']: verify(ref)
            except (OSError, ValueError, KeyError): blockers.append({'task_id': key, 'reason': '验收证据或成果已失效'})
        elif status == 'STOPPED' and not item['required']:
            try: verify(item['observation'])
            except (OSError, ValueError, KeyError): blockers.append({'task_id': key, 'reason': '停止证据失效'})
        else: blockers.append({'task_id': key, 'reason': status})
    for key,item in value.get('work_items',{}).items():
        if item['blocks_delivery'] and item['status']!='RESOLVED':
            blockers.append({'work_id':key,'reason':'OPEN_WORK_ITEM','scope':item['scope'],'next_action':item['next_action']})
        elif item['blocks_delivery'] and item['status']=='RESOLVED':
            try: verify(item['evidence'])
            except (OSError,ValueError,KeyError): blockers.append({'work_id':key,'reason':'工作项解决证据失效'})
    return blockers

def resume(directory):
    value = read(Path(directory)/'coordination.json')
    from runtime_clock import status as clock_status
    clock = clock_status(directory) if (Path(directory)/'runtime-clock.json').is_file() else None
    return {'runtime_clock': clock, 'status': 'RECONCILE_BEFORE_RESUME', 'revision': value['revision'],
            'clock_resume_requires_explicit_work':True, 'tasks': value['tasks'], 'work_items':value.get('work_items',{}), 'blockers': pending(value), 'checkpoint': value['checkpoint'],
            'next': '先用宿主工具核实所有旧任务；不可达记UNKNOWN，不重新派发；此命令不唤醒会话'}

def finish(directory, expected_revision, archive):
    directory = Path(directory)
    with file_lock(directory/'coordination.lock'):
        path = directory/'coordination.json'; value = read(path)
        if value['revision'] != expected_revision: raise ValueError('STALE_COORDINATOR')
        blockers = pending(value)
        if blockers: return {'status': 'CONTINUE_REQUIRED', 'blockers': blockers}
        # Real delivery validator remains authoritative; no caller-supplied PASS.
        from production_progress import complete
        before = reference(archive)
        result = complete(value['display'], archive, _coordination_checked=True)
        verify(before)
        if result['percent'] != 100: raise ValueError('交付尚未完成')
        value['revision'] += 1
        value['finish'] = {'status': 'READY_TO_DELIVER', 'archive': before,
                           'revision': value['revision']}
        atomic_json(path, value)
        return value['finish']

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'event', 'resume', 'finish-check'])
    parser.add_argument('--directory', required=True); parser.add_argument('--display')
    parser.add_argument('--revision', type=int); parser.add_argument('--event'); parser.add_argument('--zip')
    a = parser.parse_args()
    try:
        if a.action == 'init':
            if not a.display: raise ValueError('init缺--display')
            result = initialize(a.directory, a.display)
        elif a.action == 'resume': result = resume(a.directory)
        elif a.action == 'event':
            if a.revision is None or not a.event: raise ValueError('event缺--revision/--event')
            result = update(a.directory, a.revision, read(a.event))
        else:
            if a.revision is None or not a.zip: raise ValueError('finish-check缺--revision/--zip')
            result = finish(a.directory, a.revision, a.zip)
        print(json.dumps(result, ensure_ascii=False)); return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'COORDINATION_HOLD', 'error': str(exc)}, ensure_ascii=False)); return 1

if __name__ == '__main__':
    configure_stdio(); raise SystemExit(main())
