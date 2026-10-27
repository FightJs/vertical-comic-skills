#!/usr/bin/env python3
"""Half-episode round records: validate evidence and propose scoped repairs; no image calls."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from codex_reference_contract import read_json, checked_file, digest, execution_errors, validate_panel

MODE = 'half_episode_async_v1'
TERMINAL = {'VISUAL_PASS', 'USER_ACCEPTED', 'VISUAL_FAIL', 'CALL_FAILED', 'RESULT_UNKNOWN', 'CANCELLED'}
PASS = {'VISUAL_PASS', 'USER_ACCEPTED'}
SNAPSHOT_KEYS = ('panel_id', 'source_panel_id', 'attempt_id', 'round_id', 'status', 'package_manifest', 'shot_subset',
                 'qa_report', 'output', 'failure_diagnosis', 'call_evidence')


def read(path): return read_json(path)

def snapshot(record): return {k: record[k] for k in SNAPSHOT_KEYS if k in record}


def settings(state):
    review = state.get('review_policy', {})
    if type(review.get('systemic_failure_count_gt')) is not int or type(review.get('max_auto_correction_rounds')) is not int or review.get('systemic_failure_count_gt') != 5 or review.get('max_auto_correction_rounds') != 1:
        raise ValueError('半话模式须保留超过5张共因诊断与最多一轮自动修正')
    return review


def decision(attempts, round_id):
    if type(round_id) is not int or round_id not in (1, 2) or any(a.get('status') not in TERMINAL for a in attempts):
        raise ValueError('本轮请求须全部结束且完成逐格审查；未返回/未审不能计为通过')
    passed = [a['panel_id'] for a in attempts if a['status'] in PASS]
    failed = [a['panel_id'] for a in attempts if a['status'] == 'VISUAL_FAIL']
    call_failed = [a['panel_id'] for a in attempts if a['status'] == 'CALL_FAILED']
    unknown = [a['panel_id'] for a in attempts if a['status'] in {'RESULT_UNKNOWN', 'CANCELLED'}]
    if call_failed or unknown: strategy = 'CALL_HOLD'
    elif not failed: strategy = 'ALL_PASS'
    elif round_id == 2: strategy = 'STOP_DIAGNOSE'
    elif len(failed) > 5: strategy = 'SYSTEMIC_REPAIR'
    else: strategy = 'LOCAL_REPAIR'
    return {'strategy': strategy, 'passed_panel_ids': passed, 'failed_panel_ids': failed,
            'call_failed_panel_ids': call_failed, 'unknown_panel_ids': unknown,
            'repair_panel_ids': failed if strategy in {'LOCAL_REPAIR', 'SYSTEMIC_REPAIR'} else [],
            'retain_panel_ids': passed}


def attempt_errors(state, root, item):
    from no_image_recovery import history_errors
    errors = history_errors(state, root, item)
    pid = item.get('panel_id')
    if not isinstance(item.get('attempt_id'), str) or not item['attempt_id'].strip() or type(item.get('round_id')) is not int or item['round_id'] not in (1, 2):
        return [f'{pid}:缺少准确尝试编号/轮次']
    if item.get('status') not in TERMINAL: return [f'{pid}:尚未完成请求与逐格审查']
    if item['status'] in {'CALL_FAILED', 'RESULT_UNKNOWN', 'CANCELLED'}:
        log = read(checked_file(root, item.get('call_evidence')))
        if log.get('attempt_id') != item['attempt_id'] or log.get('status') != item['status'] or not log.get('source_locator') or not log.get('evidence'):
            errors.append(f'{pid}:调用异常/取消记录与本轮尝试不一致')
        return errors
    manifest_path = checked_file(root, item.get('package_manifest'))
    packet = read(manifest_path)
    panels = packet.get('panels', [])
    if state.get('execution_contract')=='comic_execution_v2':
        source=read(checked_file(root,state['source_snapshot']));mapping={x['panel_id']:x['source_panel_id'] for x in source['id_mapping']['pairs']}
        if item.get('source_panel_id')!=mapping.get(pid) or not panels or panels[0].get('source_panel_id')!=mapping.get(pid):errors.append('SOURCE_ID_HOLD:历史尝试原格号与准确冻结映射不一致')
    if len(panels) != 1 or panels[0].get('panel_id') != pid or packet.get('execution_mode') != state.get('execution_mode', MODE) or packet.get('book_id') != state['book_id'] or packet.get('episode_id') != state['episode_id']:
        return [f'{pid}:轮次执行包格号/书话/模式不一致']
    if type(packet.get('round_context', {}).get('round_id')) is not int or packet.get('round_context') != {'batch_id': item.get('batch_id', packet.get('round_context', {}).get('batch_id')), 'round_id': item['round_id'], 'attempt_id': item['attempt_id']}:
        errors.append(f'{pid}:执行包与尝试轮次不一致')
    output = checked_file(root, item.get('output'))
    report = read(checked_file(root, item.get('qa_report')))
    items = report.get('panels', [])
    if report.get('source_manifest_sha256') != digest(manifest_path) or len(items) != 1 or items[0].get('panel_id') != pid or items[0].get('image_sha256') != digest(output):
        return errors + [f'{pid}:逐格QA不是当前执行包及返回图']
    if panels[0].get('generation_execution', {}).get('attempt_id') != item['attempt_id']:
        errors.append(f'{pid}:轮次记录与实际调用attempt_id不一致')
    if 'parallel_context' in state:
        from batch_workflow import dispatch_errors
        errors.extend(dispatch_errors(state, root, packet, pid, digest(output)))
    from light_review import enabled as light_enabled, evidence_errors as light_errors
    if light_enabled(state):
        return errors + light_errors(root, item, require_pass=item['status'] in PASS)
    if item['status'] in PASS:
        from staged_workflow import qa_errors
        errors.extend(qa_errors(root, item))
    else:
        from visual_evidence import review_errors as visual_review_errors
        actual_size = None
        if panels[0].get("visual_evidence_policy"):
            from PIL import Image
            from codex_reference_contract import physical_file
            with Image.open(physical_file(output)) as opened: actual_size = opened.size
        errors.extend(visual_review_errors(panels[0], items[0], require_pass=False, image_size=actual_size))
        diagnosis = item.get('failure_diagnosis', {})
        if not diagnosis.get('reviewer') or not diagnosis.get('evidence') or not diagnosis.get('layer'):
            errors.append(f'{pid}:失败缺少实际看图者/依据/最早失败层')
        from continuity_contract import dimension_template
        from style_contract import review_template as style_template
        expected_dimensions = dimension_template(panels[0])
        actual_dimensions = items[0].get('dimension_review', {})
        if set(actual_dimensions) != set(expected_dimensions):
            errors.append(f'{pid}:失败图仍须完整五维与画风自审')
        for key, expected_review in expected_dimensions.items():
            actual = actual_dimensions.get(key, {})
            applicability = (expected_review.get('expected') or {}).get('applicability')
            if actual.get('expected') != expected_review.get('expected') or (applicability == 'REQUIRED' and (actual.get('status') not in {'PASS', 'FAIL'} or not actual.get('reviewer') or not actual.get('evidence'))) or (applicability != 'REQUIRED' and actual.get('status') != applicability):
                errors.append(f'{pid}:{key}未审或修改了批准适用范围')
        style = items[0].get('style_review', {})
        expected_style = style_template(panels[0])
        if style.get('status') not in {'PASS', 'FAIL'} or not style.get('reviewer') or not style.get('evidence') or any(style.get(k) != expected_style[k] for k in ('reference_files', 'traits')):
            errors.append(f'{pid}:失败图画风未按原样例实际核对')
        reviews = [*items[0].get('dimension_review', {}).values(), items[0].get('style_review', {})]
        if not any(isinstance(r, dict) and r.get('status') == 'FAIL' and r.get('reviewer') and r.get('evidence') for r in reviews):
            errors.append(f'{pid}:未在真实六项QA中记录失败项，不能虚增失败张数')
        preflight, submission = validate_panel(panels[0], manifest_path.parent, enforce_input_budget=False)
        errors.extend(preflight)
        execution = panels[0].get('generation_execution', {})
        if execution.get('status') != 'COMPLETED' or execution.get('attempt_id') != item['attempt_id'] or submission is None:
            errors.append(f'{pid}:缺少本尝试真实生图完成证据')
        else:
            errors.extend(execution_errors(execution, submission, manifest_path.parent, pid))
            res = read(checked_file(manifest_path.parent, execution['response_evidence']))
            if not any(r.get('sha256') == digest(output) for r in res.get('outputs', [])):
                errors.append(f'{pid}:失败图不是本次调用实际返回')
    return errors


def repair_route_errors(state, diagnosis, panel_ids):
    if not state.get('runtime'):return []
    routes=diagnosis.get('repair_routes',{})
    errors=[]
    if set(routes)!=set(panel_ids):errors.append('每个失败格须明确最早失败层、修正路线及保留约束')
    for pid in panel_ids:
        route=routes.get(pid,{})
        if route.get('route')!='targeted_image_repair' or route.get('earliest_layer')!='generation_execution' or not route.get('evidence') or not isinstance(route.get('preserve_constraints'),list) or not route['preserve_constraints']:
            errors.append(f'{pid}:输入/基准/镜头/提示词问题应返回对应阶段；仅执行失败可自动定向修图')
    return errors


def report_errors(state, root, batch, report, round_id, records):
    errors = []
    expected = {'policy': 'half_round_v1', 'book_id': state['book_id'], 'episode_id': state['episode_id'],
                'batch_id': batch['batch_id'], 'round_id': round_id, 'panel_ids': batch['panel_ids'],
                'visual_basis': state['visual_basis'], 'shot_manifest': state['shot_manifest'],
                'review_policy': settings(state)}
    if state.get('optimization_policy') == 'scoped_half_review_v1': expected['optimization_policy'] = state['optimization_policy']
    for key, value in expected.items():
        if report.get(key) != value: errors.append(f'轮次报告范围/版本不一致:{key}')
    if type(report.get('round_id')) is not int: errors.append('报告轮次必须为整数')
    if not report.get('reviewer') or not report.get('evidence') or report.get('status') != 'REVIEWED':
        errors.append('轮次汇总尚未实际审查；模板不是通过')
    attempts = report.get('attempts', [])
    if [a.get('panel_id') for a in attempts] != batch['panel_ids']: return errors + ['轮次报告缺格、重复或乱序']
    if round_id == 1 and any(a.get('round_id') != 1 for a in attempts): errors.append('首轮报告不能混入修正轮次')
    for item in attempts:
        pid = item['panel_id']; record = records[pid]
        current = snapshot(record)
        history = [snapshot(h) for h in record.get('attempt_history', [])]
        if item != current and not (round_id == 1 and item in history): errors.append(f'{pid}:报告未绑定当前或保留的原始尝试')
        errors.extend(attempt_errors(state, root, item))
        packet = read(checked_file(root, item['package_manifest'])) if item.get('package_manifest') else {}
        if packet and packet.get('round_context', {}).get('batch_id') != batch['batch_id']:
            errors.append(f'{pid}:尝试属于其他半话批次')
    computed = decision(attempts, round_id)
    for key, value in computed.items():
        if report.get(key) != value: errors.append(f'轮次失败统计/动作不一致:{key}')
    if computed['repair_panel_ids']:
        diagnosis = report.get('diagnosis', {})
        if not diagnosis.get('reviewer') or not diagnosis.get('evidence') or not diagnosis.get('earliest_layer') or diagnosis.get('requires_basis_change') is not False:
            errors.append('修正前须完成最早失败层诊断；批准基准需改则返回A/B，不自动改版')
        errors.extend(repair_route_errors(state, diagnosis, computed['repair_panel_ids']))
        constraints = diagnosis.get('repair_constraints', {})
        if set(constraints) != set(computed['repair_panel_ids']) or any(not isinstance(v, list) or not v or any(not isinstance(s, str) or not s.strip() for s in v) for v in constraints.values()):
            errors.append('缺少每个失败格的定向修正与保留约束')
        if computed['strategy'] == 'SYSTEMIC_REPAIR' and not diagnosis.get('common_cause_analysis'):
            errors.append('超过5张失败须先记录参考/画风/状态/空间/提示词的共因分析')
        if state.get('execution_contract')=='comic_execution_v2':
            for pid in state.get('calibration_reviews',{}):
                if pid not in computed['repair_panel_ids']:continue
                cal=read(checked_file(root,state['calibration_reviews'][pid]))
                if constraints.get(pid)!=cal.get('diagnosis',{}).get('repair_constraints',{}).get(pid):errors.append('校准已经发生的第二轮约束须准确保留，不伪造新诊断/重开次数')
    return errors


def template(state, batch, records, round_id):
    attempts = [snapshot(records[p]) for p in batch['panel_ids']]
    if state.get('execution_contract')=='comic_execution_v2' and round_id==1:
        for i,pid in enumerate(batch['panel_ids']):
            if pid in state.get('calibration_reviews',{}) and records[pid].get('round_id')==2:
                history=records[pid].get('attempt_history',[])
                if len(history)!=1 or history[0].get('round_id')!=1:raise ValueError('校准须保留准确原始首轮失败')
                attempts[i]=snapshot(history[0])
    return {'policy': 'half_round_v1', 'book_id': state['book_id'], 'episode_id': state['episode_id'],
            'batch_id': batch['batch_id'], 'round_id': round_id, 'panel_ids': batch['panel_ids'],
            'visual_basis': state['visual_basis'], 'shot_manifest': state['shot_manifest'], 'review_policy': settings(state),
            **({'optimization_policy':state['optimization_policy']} if state.get('optimization_policy') else {}),
            'status': 'UNREVIEWED', 'reviewer': '', 'evidence': '', 'attempts': attempts,
            **decision(attempts, round_id), 'diagnosis': {}}


def write_contact_sheet(root, batch, records, destination):
    """Actual selected window images in source order; review aid only, no PASS."""
    from PIL import Image, ImageDraw
    dest = Path(destination).resolve(); dest.relative_to(Path(root).resolve())
    tiles = []
    for pid in batch['panel_ids']:
        path = checked_file(root, records[pid].get('output'))
        from codex_reference_contract import physical_file
        with Image.open(physical_file(path)) as opened:
            thumb = opened.convert('RGB'); thumb.thumbnail((360, 480))
        tile = Image.new('RGB', (380, 520), 'white')
        tile.paste(thumb, ((380-thumb.width)//2, 30)); ImageDraw.Draw(tile).text((10,8), pid, fill='black'); tiles.append(tile)
    columns = min(5, len(tiles)); rows = (len(tiles)+columns-1)//columns
    sheet = Image.new('RGB', (380*columns,520*rows), '#dddddd')
    for i,tile in enumerate(tiles): sheet.paste(tile, ((i%columns)*380,(i//columns)*520))
    with dest.open('xb') as output: sheet.save(output, format='JPEG', quality=95)
    return {'status':'UNREVIEWED_CONTACT_SHEET_CREATED','path':str(dest),'panel_ids':batch['panel_ids']}


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--state', required=True); p.add_argument('--batch', required=True)
    p.add_argument('--round', type=int, choices=(1, 2), required=True); p.add_argument('--write'); p.add_argument('--contact-sheet', help='准确本半话实际图总览新JPEG路径；不写QA通过')
    a = p.parse_args()
    try:
        path = Path(a.state).resolve(); root = path.parent.parent; state = read(path)
        if state.get('execution_mode') != MODE: raise ValueError('仅用于显式半话模式')
        plan = read(checked_file(root, state['batch_plan'])); batch = next(b for b in plan['batches'] if b['batch_id'] == a.batch)
        if state.get('optimization_policy') == 'scoped_half_review_v1':
            from scoped_inputs import half_view
            state = half_view(state, batch['batch_id'])
        records = {r['panel_id']: r for r in state['panels']}
        if a.contact_sheet:
            result = write_contact_sheet(root, batch, records, a.contact_sheet)
            print(json.dumps(result, ensure_ascii=False))
        if not a.write:
            if a.contact_sheet: return 0
            raise ValueError('指定write汇总模板或contact-sheet审阅图')
        value = template(state, batch, records, a.round)
        dest = Path(a.write).resolve(); dest.relative_to(root)
        with dest.open('x', encoding='utf-8', newline='\n') as f: json.dump(value, f, ensure_ascii=False, indent=2); f.write('\n')
        print(json.dumps({'status': 'UNREVIEWED_TEMPLATE_CREATED', 'path': str(dest)}, ensure_ascii=False)); return 0
    except (OSError, ValueError, TypeError, KeyError, StopIteration) as exc:
        print(json.dumps({'status': 'HOLD', 'errors': [str(exc)]}, ensure_ascii=False)); return 1

if __name__ == '__main__':
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
