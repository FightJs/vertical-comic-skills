#!/usr/bin/env python3
"""Derived task progress, never an approval/gate or a watchdog progress event.

refresh reads existing small records; show reads only the cached summary and stat
fingerprints. No image API, image decoding, directory scan or full gate on a timer.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import time
from platform_io import atomic_json

POLICY = 'task_progress_v1'
DEFAULTS = {'policy': POLICY, 'active_seconds': 120, 'service_wait_seconds': 300,
            'yield_seconds': 30}
WEIGHTS = {'preparation': {'input': 5, 'visual': 20, 'shots': 25, 'package': 30,
                           'rehearsal': 15, 'delivery': 5},
           'production': {'receive': 5, 'images': 45, 'review': 25, 'adoption': 10,
                          'continuity': 10, 'delivery': 5}}
LABELS = {'input': '输入审计', 'visual': '视觉基准', 'shots': '镜头设计',
          'package': '生图包准备', 'rehearsal': '接包演练', 'delivery': '正式ZIP交付',
          'receive': '接包与本地预检', 'images': '生成与滚动审图', 'review': '实际自审与处理决定',
          'adoption': '返修收敛与采用', 'continuity': '连续性与最终验收'}
OUTCOMES = ('DELIVERABLE', 'MANUAL_RETOUCH', 'MANUAL_PRIORITY', 'INCOMPLETE')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def settings(value=None):
    value = {**DEFAULTS, **(value or {})}
    if value['policy'] != POLICY: raise ValueError('未知显示进度策略')
    for k in ('active_seconds', 'service_wait_seconds', 'yield_seconds'):
        if type(value[k]) is not int or value[k] < 1: raise ValueError('进度间隔须为正整数秒')
    if value['service_wait_seconds'] < value['active_seconds'] or value['yield_seconds'] > 60:
        raise ValueError('服务等待间隔不得短于正常间隔；让出检查上限60秒')
    return value


def stat(path):
    try:
        s = Path(path).stat()
        return [s.st_size, s.st_mtime_ns, s.st_ctime_ns]
    except OSError: return None


def initialize(directory, role, states, *, config=None):
    directory = Path(directory).resolve()
    if role not in WEIGHTS: raise ValueError('职责须为preparation或production')
    paths = [str(Path(p).resolve()) for p in states]
    if not paths or len(paths) != len(set(paths)): raise ValueError('须给出每话唯一权威状态')
    scopes = [(read(p)['book_id'], read(p)['episode_id']) for p in paths]
    if len(set(scopes)) != len(scopes) or len({b for b, _ in scopes}) != 1:
        raise ValueError('同一批一本书，每话只指定一个权威RV')
    task = {'policy': POLICY, 'role': role, 'states': paths, 'scope': [list(x) for x in scopes],
            'settings': settings(config), 'weights': WEIGHTS[role]}
    destination = directory/'task.json'
    if destination.exists() and read(destination) != task: raise ValueError('显示任务范围已锁定，不能换话或重置目标')
    directory.mkdir(parents=True, exist_ok=True)
    atomic_json(destination, task)
    return refresh(directory)


class Records:
    """Only explicitly referenced metadata; remembered stats invalidate display cache."""
    def __init__(self): self.files = {}

    def path(self, root, ref):
        if not isinstance(ref, dict) or not isinstance(ref.get('path'), str): raise ValueError('缺引用')
        p = Path(ref['path']); p = p if p.is_absolute() else Path(root)/p
        p = p.resolve(); self.files[str(p)] = stat(p)
        if self.files[str(p)] is None: raise ValueError('引用文件缺失：'+str(p))
        return p

    def document(self, root, ref):
        p = self.path(root, ref); raw = p.read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref.get('sha256'): raise ValueError('元数据版本不符：'+str(p))
        value = json.loads(raw.decode('utf-8-sig'))
        self.references(root, value)
        return value

    def references(self, root, value):
        if isinstance(value, dict):
            if isinstance(value.get('path'), str) and value.get('sha256'):
                try: self.path(root, value)
                except (OSError, ValueError): pass
            for child in value.values(): self.references(root, child)
        elif isinstance(value, list):
            for child in value: self.references(root, child)


def source_order(state, root, records):
    source = records.document(root, state.get('source_snapshot'))
    order = source.get('panel_ids')
    if (not isinstance(order, list) or not order or any(not isinstance(p, str) or not p for p in order)
            or len(set(order)) != len(order) or source.get('source_sha256') != (state.get('source_script') or {}).get('sha256')
            or set(source.get('locked_scripts', {})) != set(order)):
        raise ValueError('源快照缺真实格序/原文或版本不符')
    script = records.path(root, state['source_script'])
    if hashlib.sha256(script.read_bytes()).hexdigest() != state['source_script']['sha256']:
        raise ValueError('源剧本实际版本不符')
    return order


def approval_count(state, root, phase, artifacts, ids):
    # Invoked only on explicit material-change refresh, never by timed show.
    from scoped_inputs import approval_for
    return sum(not approval_for(state, root, phase, artifacts, [p], state.get('gates', {}).get(phase)) for p in ids)


def episode(state, root, role, records, observation=None):
    value = {'book_id': state['book_id'], 'episode_id': state['episode_id'], 'total': None,
             'stages': {}, 'counts': {}, 'blockers': [], 'notes': []}
    try: order = source_order(state, root, records)
    except (OSError, ValueError, KeyError, TypeError) as e:
        value['blockers'] = [{'kind': 'INPUT', 'scope': state['episode_id'], 'reason': str(e)}]
        return value
    n = value['total'] = len(order)
    rows = state.get('panels', [])
    if [r.get('panel_id') for r in rows] != order:
        value['notes'].append('运行记录尚未完整覆盖源序；缺失格仍计入分母')
    by_id = {r['panel_id']: r for r in rows if r.get('panel_id') in order}
    # A display fraction is source coverage, not dispatch permission.
    if role == 'preparation':
        stages = dict(input=n, visual=0, shots=0, package=0, rehearsal=0, delivery=0)
        try:
            basis = records.document(root, state['visual_basis'])
            if basis.get('book_id') != state['book_id'] or basis.get('episode_id') != state['episode_id'] or not basis.get('reference_files'):
                raise ValueError('视觉基准归属或参考缺失')
            for ref in basis['reference_files']: records.path(root, ref)
            approved = approval_count(state, root, 'visual_basis',
                                      [state['source_script'], state['source_snapshot'], state['visual_basis']], order)
            stages['visual'] = .8*n + .2*approved
        except (OSError, ValueError, KeyError, TypeError) as e: value['notes'].append('视觉基准待补：'+str(e))
        try:
            shots = records.document(root, state['shot_manifest'])
            locked = records.document(root, state['source_snapshot'])['locked_scripts']
            ids = [p['panel_id'] for p in shots['panels'] if p.get('panel_id') in order and p.get('locked_script') == locked[p['panel_id']]]
            if len(set(ids)) != len(ids): raise ValueError('镜头格重复')
            from execution_contract import extra_basis_refs
            approved = approval_count(state, root, 'shot_design',
                                      [state['visual_basis'], state['shot_manifest'], *extra_basis_refs(state)], ids)
            stages['shots'] = .8*len(ids) + .2*approved
            value['counts']['shots_prepared'] = len(ids)
        except (OSError, ValueError, KeyError, TypeError) as e: value['notes'].append('镜头待补：'+str(e))
        prepared, approved = set(), set()
        for refs in state.get('generation_packages', {}).values():
            for ref in refs:
                try:
                    bundle = records.document(root, ref)
                    if (bundle.get('book_id'), bundle.get('episode_id')) != (state['book_id'], state['episode_id']): continue
                    if bundle.get('visual_basis') != state.get('visual_basis') or bundle.get('shot_manifest') != state.get('shot_manifest'): continue
                    ids = set(bundle.get('approval_panel_ids', [p['panel_id'] for p in bundle.get('inputs', [])])) & set(order)
                    prepared.update(ids)
                    for p in ids:
                        if approval_count(state, root, 'generation_package', [ref, state['visual_basis'], state['shot_manifest']], [p]): approved.add(p)
                except (OSError, ValueError, KeyError, TypeError) as e: value['notes'].append('生图包待补：'+str(e))
        stages['package'] = .8*len(prepared) + .2*len(approved)
        value['counts'].update(package_prepared=len(prepared), package_approved=len(approved))
    else:
        counts = Counter({k: 0 for k in ('images', 'reviewed', 'adopted', 'inflight', 'unknown', *OUTCOMES)})
        from production_decisions import selected, outcome
        for pid in order:
            row = by_id.get(pid, {})
            history = [*row.get('attempt_history', []), row]
            images, reviewed = False, False
            for attempt in history:
                try:
                    if attempt.get('output'):
                        records.path(root, attempt['output']); images = True
                    if attempt.get('status') in {'VISUAL_PASS', 'VISUAL_FAIL', 'USER_ACCEPTED'}:
                        qa = records.document(root, attempt.get('qa_report'))
                        if any(p.get('panel_id') == pid and p.get('image_sha256') == attempt.get('output', {}).get('sha256') for p in qa.get('panels', [])):
                            reviewed = True
                except (OSError, ValueError, KeyError, TypeError): pass
            counts['images'] += images; counts['reviewed'] += reviewed
            counts['inflight'] += row.get('status') == 'IN_FLIGHT'
            counts['unknown'] += row.get('status') == 'RESULT_UNKNOWN'
            try:
                # Check small bound QA/decision metadata; do not decode/re-hash images.
                for ref in row.get('production_decisions', {}).values(): records.path(root, ref)
                attempt, decision, _, _ = selected(root, row)
                records.path(root, attempt['output']); records.path(root, attempt['qa_report'])
                closed = (decision['action'] in {'complete', 'defer_manual', 'stop_diagnose'}
                          and row.get('status') not in {'IN_FLIGHT','RESULT_UNKNOWN','GENERATED','REPAIR_AUTHORIZED','PENDING','CANCELLED'}
                          and all(i['certainty'] != 'unverified' for i in decision['issues']))
                if not closed: raise ValueError('处理未闭合')
                counts['adopted'] += 1; counts[outcome(decision)] += 1
            except (OSError, ValueError, KeyError, TypeError): counts['INCOMPLETE'] += 1
        receive = n if observation and observation.get('receiver_pass') else 0
        final = n if observation and observation.get('final_pass') else 0
        stages = dict(receive=receive, images=counts['images'], review=counts['reviewed'],
                      adoption=counts['adopted'], continuity=final, delivery=0)
        value['counts'] = dict(counts)
        if counts['unknown']: value['blockers'].append({'kind':'UNKNOWN','scope':state['episode_id'], 'reason':f"{counts['unknown']}格结果未知，先查证，不重发"})
    for hold in state.get('holds', []):
        value['blockers'].append({'kind': 'HOLD', 'scope': state['episode_id'], 'reason': hold})
    if state.get('cancelled'): value['blockers'].append({'kind': 'CANCELLED', 'scope': state['episode_id'], 'reason': '任务已取消'})
    if observation: value['blockers'].extend(observation.get('blockers',[]))
    value['stages'] = stages
    return value


def receive_binding(state):
    keys = ('book_id','episode_id','source_script','source_snapshot','visual_basis','shot_manifest',
            'semantic_audit','generation_packages','approval_index','gates','runtime_snapshot','toolchain')
    return fingerprint({k:state.get(k) for k in keys})


def observation_binding(state):
    # Runtime updates invalidate receive/final conclusions conservatively.
    return fingerprint(state)


def observe_runtime(directory, state_path, action, result, *, expected_state=None):
    """Consume an existing result only. Does not run a checker or mutate its verdict."""
    directory = Path(directory); task = read(directory/'task.json'); path = str(Path(state_path).resolve())
    if path not in task['states']: raise ValueError('观察结果超出本批状态范围')
    state = read(path)
    if expected_state is not None and state != expected_state: raise ValueError('检查期间状态已变化，不记录旧检查结果')
    p = directory/('episode-'+fingerprint(path)+'.json')
    previous = read(p) if p.exists() else {}
    if previous.get('receive_binding') != receive_binding(state): previous = {}
    if previous.get('binding') != observation_binding(state): previous.pop('final_pass', None)
    rehearsed = (action == 'rehearsal' and result.get('source_kind') == 'observed_frozen_gate_rehearsal'
                 and result.get('status') == 'RELEASE_CANDIDATE'
                 and any(r.get('episode_id') == state['episode_id'] and r.get('status') == 'REHEARSED' for r in result.get('results', [])))
    receiver = action == 'receiver-audit' and all(result.get(k, {}).get('preflight', {}).get('status') in {'READY','PARTIAL_READY'} for k in ('h001','all_inputs')) and not result.get('preparation', {}).get('global_errors') and not result.get('preparation', {}).get('errors')
    gate = result.get('gate', result)
    final = gate.get('status') == 'PASS' and gate.get('next_action') in {'READY_FOR_HANDOFF','READY_TO_PACKAGE'} and gate.get('handoff_complete', True)
    atomic_json(p, {'binding': observation_binding(state), 'receive_binding': receive_binding(state), 'receiver_pass': receiver or rehearsed or final or previous.get('receiver_pass', False),
                   'final_pass': final or previous.get('final_pass', False),
                   'blockers': [{'kind':'CHECK','scope':state['episode_id'],
                                 'panel_ids':gate.get('blocked_panel_ids',[]), 'reason':e} for e in gate.get('errors',[])]})


def refresh(directory, *, activity=None, next_action=None, wait_kind='NONE', stage=None, blockers=None):
    directory = Path(directory); task = read(directory/'task.json'); records = Records(); episodes = []
    from codex_reference_contract import file_session
    with file_session():
        for sp in task['states']:
            records.files[sp] = stat(sp); state = read(sp)
            if [state.get('book_id'),state.get('episode_id')] != task['scope'][len(episodes)]:
                raise ValueError('权威状态书话已变化，不能沿用原显示范围')
            p = directory/('episode-'+fingerprint(sp)+'.json'); obs = read(p) if p.exists() else None
            if obs and obs.get('receive_binding') != receive_binding(state): obs = None
            if obs and obs.get('binding') != observation_binding(state): obs = {**obs, 'final_pass':False, 'blockers':[]}
            episodes.append(episode(state, Path(sp).parent.parent, task['role'], records, obs))
            # Approval sources may live outside state refs; track explicit files,
            # never recurse through directories or read image bytes on a timer.
            def refs(v):
                if isinstance(v, dict):
                    if isinstance(v.get('path'), str) and v.get('sha256'):
                        try: records.path(Path(sp).parent.parent, v)
                        except (OSError, ValueError): pass
                    for x in v.values(): refs(x)
                elif isinstance(v, list):
                    for x in v: refs(x)
            refs(state)
    total = sum(e['total'] or 0 for e in episodes) if all(e['total'] is not None for e in episodes) else None
    units = {k: sum(e['stages'].get(k, 0) for e in episodes) for k in task['weights']}
    percent = math.floor(sum(task['weights'][k]*units[k]/total for k in units)) if total else None
    if stage is not None and stage not in units: raise ValueError('当前阶段不属于本次职责')
    stage = stage or next((k for k in units if total is None or units[k] < total), 'delivery')
    old = read(directory/'snapshot.json') if (directory/'snapshot.json').exists() else {}
    snapshot = {'policy': POLICY, 'role': task['role'], 'target': '正式生图交接ZIP' if task['role']=='preparation' else '指定范围逐格成品ZIP',
                'total': total, 'percent': percent, 'stage': stage, 'stage_units': units, 'episodes': episodes,
                'blockers': [b for e in episodes for b in e['blockers']] + (blockers or []),
                'activity': activity or old.get('activity', '核对当前阶段材料'),
                'next': next_action or old.get('next', '继续当前可执行范围，补齐受影响项'),
                'wait_kind': wait_kind, 'observed_at': time.time(), 'files': records.files,
                'not_approval_evidence': True}
    # A formal ZIP is counted once across the task, after its real checks.
    delivery_path = directory/'delivered.json'
    if delivery_path.exists():
        delivered = read(delivery_path)
        if delivered['states'] == {p: fingerprint(read(p)) for p in task['states']} and stat(delivered['zip']) == delivered['stat'] and all(stat(p)==v for p,v in delivered.get('dependencies',{}).items()):
            snapshot['stage_units']['delivery'] = total or 0
            if task['role'] == 'preparation': snapshot['stage_units']['rehearsal'] = total or 0
            if total:
                snapshot['percent'] = math.floor(sum(task['weights'][k]*snapshot['stage_units'][k]/total for k in units))
                snapshot['stage'] = next((k for k in units if snapshot['stage_units'][k] < total), 'delivery')
            snapshot['files'][delivered['zip']] = delivered['stat']
    meaningful = {k: snapshot[k] for k in ('stage_units','total','blockers')}
    snapshot['last_real_progress_at'] = old.get('last_real_progress_at', snapshot['observed_at']) if meaningful == {k: old.get(k) for k in meaningful} else snapshot['observed_at']
    atomic_json(directory/'snapshot.json', snapshot)
    return snapshot


def stale(snapshot):
    return any(stat(p) != signature for p, signature in snapshot['files'].items())


def due(snapshot, cursor=None, *, now=None, config=None):
    now = time.time() if now is None else now; config = settings(config)
    cursor = cursor or {}
    if snapshot['wait_kind'] in {'HUMAN','ENDED'}: return False
    event = fingerprint([snapshot['stage'], snapshot['blockers'], snapshot['percent'] == 100, snapshot['wait_kind']])
    if event != cursor.get('event'): return True
    interval = config['service_wait_seconds'] if snapshot['wait_kind']=='SERVICE' else config['active_seconds']
    return now-cursor.get('sent_at', 0) >= interval


def format_summary(snapshot):
    progress = '待核定总格数' if snapshot['percent'] is None else f"总进度{snapshot['percent']}%"
    role = '前期制作' if snapshot['role']=='preparation' else '生图生产'
    counts = Counter()
    for e in snapshot['episodes']: counts.update({k:v for k,v in e['counts'].items() if isinstance(v,(int,float))})
    n = snapshot['total'] if snapshot['total'] is not None else '待核定'
    amounts = (f"镜头准备{counts['shots_prepared']}/{n}格；生图包准备{counts['package_prepared']}/{n}格" if snapshot['role']=='preparation' else
               f"已落盘{counts['images']}/{n}格；已审{counts['reviewed']}格；采用{counts['adopted']}格；在途{counts['inflight']}格；可用{counts['DELIVERABLE']}／人工后修{counts['MANUAL_RETOUCH']}／人工优先{counts['MANUAL_PRIORITY']}／未完成{counts['INCOMPLETE']}")
    blockers = '；'.join(f"{b['scope']}：{b['reason']}" for b in snapshot['blockers'][:3]) or ({'SERVICE':'等待生图服务返回','HUMAN':'等待用户决定','DEPENDENCY':'等待实际依赖；准确范围见进行事项'}.get(snapshot['wait_kind'],'无已登记阻塞'))
    return f"【{role}｜{LABELS[snapshot['stage']]}｜{progress}】\n进行中：{snapshot['activity']}\n完成量：{amounts}\n阻塞：{blockers}\n下一步：{snapshot['next']}"


def show(directory, *, now=None, acknowledge=False, force=False):
    directory = Path(directory); task = read(directory/'task.json'); snapshot = read(directory/'snapshot.json')
    # Stat only: on change return refresh-needed, never silently use stale percent.
    if stale(snapshot): return {'status':'REFRESH_REQUIRED','message':'进度来源已变化，先refresh；不得沿用旧百分比'}
    path = directory/'notification.json'; cursor = read(path) if path.exists() else {}
    now = time.time() if now is None else now
    if not force and not due(snapshot,cursor,now=now,config=task['settings']): return {'status':'NOT_DUE'}
    if acknowledge:
        atomic_json(path, {'sent_at':now,'event':fingerprint([snapshot['stage'],snapshot['blockers'],snapshot['percent']==100,snapshot['wait_kind']])})
    return {'status':'REPORT_DUE','message':format_summary(snapshot),'percent':snapshot['percent']}


def complete(directory, archive):
    """Explicit final check once, never from a heartbeat. No permission is granted."""
    import zipfile
    directory = Path(directory); task = read(directory/'task.json'); archive = Path(archive).resolve()
    if archive.suffix.lower() != '.zip': raise ValueError('完整目标须为正式ZIP')
    if task['role'] == 'preparation':
        from handoff_zip import check_delivery_archive, read_zip_json, zip_inventory, INDEX
        check_delivery_archive(archive)
        with zipfile.ZipFile(archive) as z:
            top, _ = zip_inventory(z)
            index = read_zip_json(z,top+'/'+INDEX)
        if not index or index['book_id'] != task['scope'][0][0] or set(e['episode_id'] for e in index['episodes']) != {e for _,e in task['scope']}:
            raise ValueError('正式ZIP书话范围不符')
        for sp in task['states']:
            state = read(sp); record = next(e for e in index['episodes'] if e['episode_id']==state['episode_id'])
            order = source_order(state,Path(sp).parent.parent,Records())
            if record['panel_ids'] != order or record['source_script']['sha256'] != state['source_script']['sha256'] or record['source_snapshot']['sha256'] != state['source_snapshot']['sha256']:
                raise ValueError('正式ZIP源版本或格序不符')
            if any(record[k]['sha256'] != state[k]['sha256'] for k in ('visual_basis','shot_manifest')):
                raise ValueError('正式ZIP视觉/镜头与当前批准版本不符')
            if {r['sha256'] for r in record.get('generation_review_packages',[])} != {r['sha256'] for refs in state.get('generation_packages',{}).values() for r in refs}:
                raise ValueError('正式ZIP生图包版本不符')
    else:
        from panel_delivery import gate, build
        from codex_reference_contract import file_session
        with zipfile.ZipFile(archive) as z, file_session():
            if z.testzip(): raise ValueError('成品ZIP CRC错误')
            indexes = [read_zip(z,n) for n in z.namelist() if n.endswith('交付索引.json')]
            if len(indexes)!=len(task['states']): raise ValueError('ZIP交付话数不符')
            for sp in task['states']:
                state = read(sp); root = Path(sp).parent.parent
                result = gate(state,root)
                if result['status'] != 'PASS' or not result['handoff_complete']: raise ValueError('完整交付门禁尚未通过')
                actual = build(state,root)
                matches = [(name,d) for name,d in indexes if d.get('book_id')==state['book_id'] and d.get('episode_id')==state['episode_id']]
                if len(matches)!=1: raise ValueError('ZIP交付索引缺失或重复')
                name, d = matches[0]
                if d.get('delivery_digest') != actual['delivery_digest'] or d.get('panel_ids') != actual['panel_ids']: raise ValueError('ZIP采用版本不符')
                if [{k:v for k,v in r.items() if k!='delivered_image'} for r in d['panels']] != actual['panels']:
                    raise ValueError('ZIP交付条目与本次采用索引不符')
                for row in d['panels']:
                    ref = row.get('delivered_image',{}); relative = Path(ref.get('path',''))
                    if relative.is_absolute() or '..' in relative.parts: raise ValueError('ZIP图片路径越界')
                    data = z.read((Path(name).parent/relative).as_posix())
                    if hashlib.sha256(data).hexdigest()!=row.get('image',{}).get('sha256') or ref.get('sha256')!=row['image']['sha256']: raise ValueError('ZIP缺采用原图或哈希错误')
                observe_runtime(directory,sp,'deliver',result)
    baseline = refresh(directory)
    atomic_json(directory/'delivered.json', {'zip':str(archive),'stat':stat(archive),
                'dependencies':baseline['files'],'states':{p:fingerprint(read(p)) for p in task['states']}})
    result = refresh(directory,activity='完整ZIP已验证并形成交付',next_action='交付用户')
    if result['percent']!=100: raise ValueError('ZIP已记录，但前序阶段证据尚未闭合；保持未完成百分比')
    return result


def read_zip(z, name):
    return name, json.loads(z.read(name).decode('utf-8-sig'))


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('action',choices=('init','refresh','show','complete'))
    p.add_argument('--directory',required=True); p.add_argument('--role',choices=tuple(WEIGHTS)); p.add_argument('--state',action='append')
    p.add_argument('--stage',choices=tuple(LABELS)); p.add_argument('--blockers',help='准确额外阻塞的JSON数组文件；仅显示，不改变原HOLD')
    p.add_argument('--activity'); p.add_argument('--next'); p.add_argument('--wait-kind',choices=('NONE','SERVICE','DEPENDENCY','HUMAN','ENDED'),default='NONE')
    p.add_argument('--ack',action='store_true',help='仅在总控实际发出消息后确认送达'); p.add_argument('--force',action='store_true'); p.add_argument('--zip')
    a = p.parse_args()
    if a.action=='init': value = initialize(a.directory,a.role,a.state or [])
    elif a.action=='refresh': value = refresh(a.directory,activity=a.activity,next_action=a.next,wait_kind=a.wait_kind,stage=a.stage,blockers=read(a.blockers) if a.blockers else None)
    elif a.action=='complete': value = complete(a.directory,a.zip)
    else: value = show(a.directory,acknowledge=a.ack,force=a.force)
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':
    from platform_io import configure_stdio
    configure_stdio(); main()
