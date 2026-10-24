"""Export first-batch panels and a six-column issue table from existing evidence.

No image calls, no visual PASS synthesis, no mutation of the execution ledger.
The saved review binds adopted images, QA, decisions and incomplete source rows.
"""
from __future__ import annotations
import argparse
import copy
import json
import shutil
from pathlib import Path
from collections import Counter
from codex_reference_contract import checked_file, read_json, digest, file_session
from production_decisions import enabled, selected, outcome, LABELS, fingerprint, text
from authority_updates import authority_scoped, state_write_lock


@authority_scoped
def build(state, root):
    from execution_contract import state_errors
    from task_context import state_errors as task_errors
    from batch_workflow import completed_errors
    from scoped_inputs import approval_for
    if state.get('cancelled'): raise ValueError('用户取消；不得自动继续导出')
    from batch_round import settings
    settings(state)
    if not enabled(state):
        raise ValueError('旧冻结运行保持原交付合同')
    errors = state_errors(state, root) + task_errors(state, root)
    if errors:
        raise ValueError(';'.join(errors))
    checked_file(root, state['source_script'])
    source = read_json(checked_file(root, state['source_snapshot']))
    order = source['panel_ids']; records = state['panels']
    if ([r.get('panel_id') for r in records] != order or
            source.get('source_sha256') != state['source_script']['sha256']):
        raise ValueError('交接索引须完整保留真实源格序及源版本')
    from batch_round import attempt_errors
    from episode_repair import repair_errors
    for row in records:
        if type(row.get('round_id')) is not int or row['round_id'] not in (1, 2):
            raise ValueError('交接不能绕过轮次/预算')
        if row['round_id'] == 2:
            history_errors = repair_errors(state, root, row)
            if history_errors: raise ValueError(';'.join(history_errors))
        elif row.get('attempt_history') or row.get('status') == 'REPAIR_AUTHORIZED':
            raise ValueError('返修不能伪装成首轮')
        if row.get('status') in {'RESULT_UNKNOWN', 'CALL_FAILED', 'CANCELLED', 'VISUAL_PASS', 'USER_ACCEPTED', 'VISUAL_FAIL'}:
            call_errors = attempt_errors(state, root, row)
            if call_errors: raise ValueError(';'.join(call_errors))
    basis = read_json(checked_file(root, state['visual_basis']))
    shots = read_json(checked_file(root, state['shot_manifest']))
    by_shot = {p['panel_id']: p for p in shots['panels']}
    if list(by_shot) != order or any(by_shot[p].get('locked_script') != source['locked_scripts'][p] for p in order):
        raise ValueError('镜头源序不完整')
    # Use the adopted versions for actual continuity comparisons. This view is
    # local only; it never rewrites state.output or dependency acceptance.
    chosen = {}; loaded = {}
    for row in records:
        if row.get('adoption'):
            attempt, decision, item, ref = selected(root, row)
            chosen[row['panel_id']] = attempt
            loaded[row['panel_id']] = (decision, item, ref)
    rows = []; refs = [state['source_script'], state['source_snapshot'],
                      state['visual_basis'], state['shot_manifest']]
    for row in records:
        pid = row['panel_id']; shot = by_shot[pid]
        result = {'panel_id': pid, 'source_panel_id': row.get('source_panel_id'),
                  'current_attempt_id': row.get('attempt_id'),
                  'current_status': row.get('status'), 'outcome': 'INCOMPLETE',
                  'issues': [], 'incomplete_reasons': []}
        if pid not in chosen:
            result['incomplete_reasons'] = ['缺图、未审或尚未登记采用版本；保留原状态']
            if row.get('call_evidence'):
                checked_file(root, row['call_evidence']); refs.append(row['call_evidence'])
            rows.append(result); continue
        attempt = chosen[pid]; decision, item, ref = loaded[pid]
        # Reuse the original full completion validator, accepting recorded FAIL
        # as an observation only. Source/input/receipt/QA checks remain active.
        evidence_errors = completed_errors(state, root, attempt, shot, basis, chosen, require_pass=False)
        if evidence_errors:
            raise ValueError(pid + ':交接证据无效:' + ';'.join(evidence_errors))
        for phase, artifacts in (
            ('visual_basis', [state['source_script'], state['source_snapshot'], state['visual_basis']]),
            ('shot_design', [state['visual_basis'], state['shot_manifest']])):
            from execution_contract import extra_basis_refs
            if phase == 'shot_design': artifacts += extra_basis_refs(state)
            approval_errors = approval_for(state, root, phase, artifacts, [pid], state.get('gates', {}).get(phase))
            if approval_errors: raise ValueError(pid + ':' + ';'.join(approval_errors))
        incomplete = result['incomplete_reasons']
        from scoped_inputs import blocked_panels
        blocked, reasons = blocked_panels(state.get('holds'), order, {'batch_id':'EPISODE','panel_ids':order}, shots['panels'])
        if pid in blocked: incomplete.append('当前原HOLD尚未解决：'+json.dumps(reasons,ensure_ascii=False))
        if shot.get('requires_state_review') or shot.get('calibration_anchor') or shot.get('state_review_policy') == 'user_required':
            approval_errors = approval_for(state, root, 'state_review',
                [state['visual_basis'],state['shot_manifest'],attempt['output']], [pid], state.get('state_reviews',{}).get(pid))
            if approval_errors: incomplete.append('用户保留的高风险实图确认尚未完成')
        if row.get('call_evidence'): refs.append(row['call_evidence'])
        for old in row.get('attempt_history', []):
            for key in ('package_manifest','output','qa_report','call_evidence'):
                if old.get(key): checked_file(root, old[key]); refs.append(old[key])
        if row.get('status') in {'RESULT_UNKNOWN', 'IN_FLIGHT', 'GENERATED', 'REPAIR_AUTHORIZED', 'PENDING', 'CANCELLED'}:
            incomplete.append('当前尝试尚未闭合；采用旧图不清除在途/未知/待审/取消记录')
        for field in ('camera_match','shot_scale_match','background_view_match','body_crop_match',
                      'required_visible_information_preserved','no_extra_offscreen_characters'):
            if type(item.get(field)) is not bool:
                incomplete.append('原QA必审项尚未完成：'+field)
        if any(i['certainty'] == 'unverified' for i in decision['issues']):
            incomplete.append('存在尚未核实的观察；疑点不当成已确认错误')
        if decision['action'] in {'needs_user', 'local_edit', 'regenerate', 'rebuild_inputs', 'crop_candidate'}:
            incomplete.append('尚有未完成的处理动作或人工决定')
        comparisons = item.get('visual_evidence_review', {}).get('continuity_comparisons', [])
        from visual_evidence import continuity_targets
        for prior in continuity_targets(shot):
            comparisons_for = [c for c in comparisons if c.get('panel_id') == prior]
            if prior not in chosen or len(comparisons_for) != 1:
                incomplete.append(prior + ':必要连续性比较尚未完成')
            elif (comparisons_for[0].get('image') != chosen[prior].get('output') or
                  comparisons_for[0].get('status') not in {'PASS', 'FAIL'} or not text(comparisons_for[0].get('observed'))):
                incomplete.append(prior + ':比较未绑定采用版本或尚未完成')
        # Existing episode continuity report is reused, including truthful FAIL.
        review_ref = state.get('batch_reviews', {}).get('EPISODE')
        review = read_json(checked_file(root, review_ref)) if review_ref else {}
        if (review.get('policy') != 'batch_review_v1' or review.get('book_id') != state['book_id'] or
                review.get('episode_id') != state['episode_id'] or review.get('batch_id') != 'EPISODE' or
                review.get('panel_ids') != order or review.get('visual_basis') != state['visual_basis'] or
                review.get('shot_manifest') != state['shot_manifest'] or
                review.get('outputs') != [chosen.get(p, {}).get('output') for p in order] or
                review.get('status') not in {'PASS', 'FAIL'} or
                not text(review.get('reviewer')) or not text(review.get('evidence'))):
            incomplete.append('原整话连续性报告未覆盖当前采用版本')
        if review.get('status') == 'FAIL' and not any(
                i.get('kind') in {'major_continuity', 'space_detail', 'prop_state'} for i in decision['issues']):
            incomplete.append('整话连续性FAIL尚未定位到本图问题或标明不受影响')
        if review_ref: refs.append(review_ref)
        if state.get('parallel_context'):
            from batch_workflow import cross_episode_errors
            if cross_episode_errors(state['parallel_context'], first_batch=True):
                incomplete.append('必要跨话比较尚未闭合')
        result.update(attempt_id=attempt['attempt_id'], image=attempt['output'],
                      qa_report=attempt['qa_report'], package_manifest=attempt['package_manifest'],
                      decision=ref, adoption_reason=row['adoption']['reason'],
                      issues=copy.deepcopy(decision['issues']),
                      outcome=outcome(decision, complete=not incomplete))
        result['label'] = LABELS[result['outcome']]
        refs.extend([attempt['output'], attempt['qa_report'], attempt['package_manifest'], ref])
        rows.append(result)
    for row in rows: row['label'] = LABELS[row['outcome']]
    unique = list({(r['path'], r['sha256']): r for r in refs}.values())
    counts = dict(Counter(r['outcome'] for r in rows))
    value = {'policy': 'first_batch_delivery_v1', 'book_id': state['book_id'],
             'episode_id': state['episode_id'], 'source_snapshot': state['source_snapshot'],
             'panel_ids': order, 'panels': rows, 'counts': counts, 'artifacts': unique,
             'all_usable': all(r['outcome'] in {'DELIVERABLE', 'MANUAL_RETOUCH'} for r in rows),
             'handoff_complete': all(r['outcome'] != 'INCOMPLETE' for r in rows),
             'image_calls': 0, 'visual_qa_changed': False, 'user_approval': 'NOT_GRANTED'}
    value['delivery_digest'] = fingerprint(value)
    return value


@authority_scoped
def gate(state, root, review_ref=None, *, allow_partial=False):
    from scoped_inputs import approval_for
    value = build(state, root)
    ref = review_ref or state.get('delivery_review')
    if not ref:
        return {'status': 'HOLD', 'next_action': 'PREPARE_DELIVERY_REVIEW', 'review': value,
                'errors': ['先保存本交接审查索引，再沿用原D/委托范围决定']}
    saved = read_json(checked_file(root, ref))
    if saved != value:
        raise ValueError('交接索引与当前采用版本/QA/问题/未完成范围不一致')
    errors = approval_for(state, root, 'final', [*value['artifacts'], ref], value['panel_ids'],
                          state.get('gates', {}).get('final'))
    incomplete = [r['panel_id'] for r in value['panels'] if r['outcome'] == 'INCOMPLETE']
    if incomplete and not allow_partial:
        errors.append('完整交付仍有未完成源格：' + ','.join(incomplete))
    return {'status': 'HOLD' if errors else 'PASS',
            'next_action': 'COMPLETE_SOURCE_SCOPE' if incomplete and not allow_partial else 'WAIT_FINAL_APPROVAL' if errors else 'READY_FOR_PARTIAL_HANDOFF' if incomplete else 'READY_FOR_HANDOFF',
            'errors': errors, 'counts': value['counts'], 'all_usable': value['all_usable'],
            'delivery_review': ref, 'handoff_complete': value['handoff_complete'],
            'user_acceptance': 'NOT_GRANTED_BY_SCRIPT'}


def _export_candidate(state, root, review_ref, destination, *, allow_partial=False):
    result = gate(state, root, review_ref, allow_partial=allow_partial)
    if result['status'] != 'PASS': raise ValueError(';'.join(result['errors']))
    review = read_json(checked_file(root, review_ref)); destination = Path(destination).resolve()
    if destination.exists(): raise ValueError('交付目录必须为不存在的新目录')
    # Check all sources before creating a clean package. A failure never leaves
    # a final-looking partially exported directory.
    image_sources = {r['panel_id']: checked_file(root, r['image']) for r in review['panels'] if r.get('image')}
    from PIL import Image
    for source in image_sources.values():
        with Image.open(source) as im: im.verify()
    import tempfile
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.panel-delivery-', dir=destination.parent))
    try:
        (stage / '图片').mkdir()
        index = copy.deepcopy(review); table = []
        def cell(v): return str(v).replace('|', '\\|').replace('\n', ' ')
        for row in index['panels']:
            pid = row['panel_id']; target = None
            if pid in image_sources:
                original = image_sources[pid]
                target = f"图片/{pid}_{row['attempt_id']}{original.suffix.lower()}"
                # Source IDs/attempt IDs are data, not filesystem instructions.
                if Path(target).parent != Path('图片') or not pid or '/' in pid or '\\' in pid or '\\' in row['attempt_id']:
                    raise ValueError('格号/尝试编号不能构成输出路径')
                shutil.copyfile(original, stage / target)
                if digest(stage / target) != row['image']['sha256']: raise ValueError('导出图片哈希不一致')
                row['delivered_image'] = {'path': target, 'sha256': row['image']['sha256']}
            link = f"[{cell(pid)}]({target})" if target else cell(pid) + '（无采用图）'
            for issue in row['issues']:
                priority = '高' if issue['category'] == 1 else '普通' if issue['category'] == 2 else '低'
                certainty = '已确认' if issue['certainty'] == 'confirmed' else '未核实疑点，请勿据此直接改图'
                table.append((issue['category'], f"| {link} | {'①②③'[issue['category']-1]} | {cell(issue['location'])} | {cell(issue['problem'])} → {cell(issue['target'])} | {priority} | {cell(issue['handling'])}；{certainty} |"))
        summary = '；'.join(f'{LABELS[k]} {review["counts"].get(k, 0)}格' for k in LABELS)
        lines = [f"{review['episode_id']}：{summary}。", '',
                 '| 格号／图片 | 类别 | 位置 | 当前问题 → 正确目标 | 优先级 | 处理情况 |',
                 '|---|---|---|---|---|---|', *[line for _, line in sorted(table, key=lambda p: p[0])],
                 '', '所有源格去向见交付索引；原QA中的FAIL保持原样。未完成格：']
        lines += [f"- {cell(r['panel_id'])}：{cell('；'.join(r['incomplete_reasons']))}" for r in review['panels'] if r['outcome'] == 'INCOMPLETE']
        (stage / '问题表.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        (stage / '交付索引.json').write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        from delivery_csv import render
        for name,data in render([index]).items():(stage/name).write_bytes(data)
        shutil.copyfile(checked_file(root, review_ref), stage / '交接审查依据.json')
        # All files/decisions were checked in the original read transaction.
        # Verify the same immutable inputs once more before publishing copied bytes.
        for ref in review['artifacts']: checked_file(root, ref)
        checked_file(root, review_ref)
        # Publication happens only after the outer read transaction completes.
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True); raise
    return stage, destination, {**result, 'path': str(destination), 'image_calls': 0}


def export(state, root, review_ref, destination, *, allow_partial=False):
    stage = None
    try:
        with file_session():
            stage, destination, result = _export_candidate(state, root, review_ref, destination, allow_partial=allow_partial)
        # Invalidated reads leave no final-looking package.
        stage.rename(destination)
        return result
    except BaseException:
        if stage is not None: shutil.rmtree(stage, ignore_errors=True)
        raise


def publish_batch(contract,destination):
    from delivery_publish import publish_production
    return publish_production(contract,destination)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state'); p.add_argument('--write')
    p.add_argument('--publish',help='完整成品ZIP交付的新输出目录')
    p.add_argument('--contract',help='本任务交付身份.json')
    p.add_argument('--review'); p.add_argument('--export')
    p.add_argument('--partial', action='store_true', help='仅用户明确要求部分材料时使用；不声明完整交付')
    a = p.parse_args()
    if a.publish:
        if not a.contract or any((a.state,a.write,a.review,a.export,a.partial)):p.error('publish仅用contract及输出目录')
        try:
            print(json.dumps(publish_batch(a.contract,a.publish),ensure_ascii=False));return 0
        except (OSError,ValueError,KeyError) as exc:
            print(json.dumps({'status':'DELIVERY_HOLD','error':str(exc)},ensure_ascii=False));return 1
    if not a.state:p.error('目录导出或审查须提供state')
    path = Path(a.state).resolve(); root = path.parent.parent
    if a.partial and not a.export: p.error('--partial仅用于明确请求的部分导出')
    if a.export:
        if not a.review: p.error('导出须绑定已获D/委托决定的--review')
        # Existing episode lock protects the state/approval pointers during export.
        with state_write_lock(path):
            state = read_json(path)
            ref = {'path': a.review, 'sha256': digest(root / a.review)}
            value = export(state, root, ref, a.export, allow_partial=a.partial)
    else:
        with file_session():
            value = build(read_json(path), root)
        if a.write:
            dest = Path(a.write).resolve(); dest.relative_to(root)
            with dest.open('x', encoding='utf-8') as f: json.dump(value, f, ensure_ascii=False, indent=2)
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
