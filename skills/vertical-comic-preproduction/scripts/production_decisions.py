"""Decisions after existing QA; never changes observations, attempts or approvals.

The policy is a version contract for new runs, not a selectable production mode.
Issue observations are JSON pointers into the original single-panel QA item.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from codex_reference_contract import checked_file, read_json, digest

POLICY = 'first_batch_production_v1'
ACTIONS = {'complete', 'defer_manual', 'needs_user', 'stop_diagnose',
           'local_edit', 'regenerate', 'rebuild_inputs', 'crop_candidate'}
CALL_ACTIONS = {'local_edit', 'regenerate', 'rebuild_inputs'}
MAJOR = {'identity', 'core_costume', 'scene_identity', 'major_continuity',
         'action_target', 'extra_limb', 'limb_ownership', 'overall_structure', 'style'}
OUTCOMES = ('DELIVERABLE', 'MANUAL_RETOUCH', 'MANUAL_PRIORITY', 'INCOMPLETE')
LABELS = dict(zip(OUTCOMES, ('可交付', '可交付，人工后修', '待人工优先处理', '未完成')))


def text(v):
    return isinstance(v, str) and bool(v.strip())


def enabled(state):
    value = state.get('production_policy')
    if value not in (None, POLICY):
        raise ValueError('未知生产决策合同；不能降级')
    return value == POLICY


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def pointer(item, path):
    if not isinstance(path, str) or not path.startswith('/'):
        raise ValueError('问题须引用原QA的JSON pointer')
    for key in path[1:].split('/'):
        key = key.replace('~1', '/').replace('~0', '~')
        item = item[int(key)] if isinstance(item, list) else item[key]
    return item


def findings(item, prefix=''):
    """Only discover recorded FAIL/unresolved observations, never infer pixels."""
    result = set()
    if isinstance(item, dict):
        if item.get('status') in {'FAIL', 'UNREVIEWED', 'HOLD'}:
            result.add(prefix)
        if item.get('clarity_status') in {'FAIL', 'UNREVIEWED', 'HOLD'}:
            result.add(prefix + '/clarity_status')
        for key, value in item.items():
            if key == 'inspection_plan': continue  # organizer template, not a visual verdict
            if key in {'camera_match','shot_scale_match','background_view_match','body_crop_match','required_visible_information_preserved','no_extra_offscreen_characters','composition_match'} and value is False:
                result.add(prefix + '/' + key)
            escaped = str(key).replace('~', '~0').replace('/', '~1')
            result.update(findings(value, prefix + '/' + escaped))
    elif isinstance(item, list):
        for index, value in enumerate(item):
            result.update(findings(value, prefix + '/' + str(index)))
    return result


def attempts(record):
    return [*record.get('attempt_history', []), record]


def attempt_for(record, attempt_id):
    matches = [a for a in attempts(record) if a.get('attempt_id') == attempt_id]
    if len(matches) != 1:
        raise ValueError('采用/决定须绑定本格唯一真实attempt')
    return matches[0]


def decision_errors(decision, attempt, item):
    errors = []
    for key, value in {'policy': POLICY, 'panel_id': attempt.get('panel_id'),
                       'attempt_id': attempt.get('attempt_id'),
                       'image': attempt.get('output'), 'qa_report': attempt.get('qa_report')}.items():
        if decision.get(key) != value:
            errors.append('决定未绑定本格原图/原QA/尝试:' + key)
    if not text(decision.get('reviewer')) or not text(decision.get('reason')):
        errors.append('缺实际决定者和简短理由')
    action = decision.get('action')
    if action not in ACTIONS:
        errors.append('缺合法处理动作')
    issues = decision.get('issues')
    if not isinstance(issues, list):
        return errors + ['问题须为列表']
    ids, covered = [], set()
    for issue in issues:
        if not isinstance(issue, dict):
            errors.append('问题须为对象'); continue
        ident = issue.get('id'); ids.append(ident if isinstance(ident, str) else '')
        if (not text(ident) or type(issue.get('category')) is not int or issue.get('category') not in (1, 2, 3)
                or issue.get('certainty') not in {'confirmed', 'unverified'}
                or any(not text(issue.get(k)) for k in ('kind', 'location', 'problem', 'target', 'basis', 'handling'))):
            errors.append('缺问题分类、位置、目标、依据或处理情况')
        if (issue.get('kind') in MAJOR or issue.get('story_critical') is True) and issue.get('category') != 1:
            errors.append('身份/核心衣装/关键叙事/整体结构错误不能降级')
        refs = issue.get('observations')
        if not isinstance(refs, list) or not refs:
            errors.append('问题须引用已有实际观察'); continue
        for ref in refs:
            try:
                observed = pointer(item, ref)
                if observed is None or observed == '':
                    raise ValueError('空观察')
                if issue.get('category') != 1 and (ref.startswith('/dimension_review/identity') or ref.startswith('/style_review')):
                    errors.append('原身份/整体画风失败不能用局部问题类别降级')
                covered.add(ref)
            except (KeyError, IndexError, TypeError, ValueError):
                errors.append('原QA观察引用无效:' + str(ref))
    if any(not isinstance(i,dict) for i in issues): return errors
    if len(ids) != len(set(ids)):
        errors.append('问题ID须唯一')
    light = item.get('light_review', {}).get('policy') == 'light_story_review_v1'
    if light:
        from light_review import decision_errors as light_decision_errors
        errors.extend(light_decision_errors(decision, attempt, item))
    if not light and not findings(item) <= covered:
        errors.append('所有FAIL和未核实项须有准确问题去向:' + ','.join(sorted(findings(item) - covered)))
    groups = [decision.get(k, []) for k in ('fix_now', 'opportunistic', 'manual')]
    if any(not isinstance(g, list) or any(not text(x) for x in g) for g in groups):
        return errors + ['修复目标须为问题ID列表']
    else:
        flat = sum(groups, [])
        if set(flat) != set(ids) or len(flat) != len(set(flat)):
            errors.append('必须修/顺带修/留人工须互斥并覆盖本图全部问题')
        if any(i.get('category') == 3 and i.get('id') not in groups[2] for i in issues):
            errors.append('第三类默认留人工，不自动追修')
    if action == 'needs_user' and (decision.get('question_kind') not in
            {'tradeoff','design_change','additional_budget','user_reserved'} or not text(decision.get('recommendation'))):
        errors.append('待决项须有真实待决类型及一句话推荐动作')
    if action == 'needs_user' and decision.get('question_kind') == 'tradeoff' and not any(
            i.get('category') in (1, 2) for i in issues):
        errors.append('仅第三类问题留人工，不逐格发起取舍问题')
    if action == 'complete' and issues:
        errors.append('有遗留问题不能声明无问题完成')
    if action in CALL_ACTIONS:
        if attempt.get('round_id') != 1 or attempt.get('status') != 'VISUAL_FAIL':
            errors.append('仅真实首轮失败可使用唯一自动修复；不自动追加预算')
        target_ids = set(decision.get('fix_now', []) + decision.get('opportunistic', []))
        if not target_ids or not any(i.get('id') in target_ids and i.get('category') in (1, 2) and
                                     i.get('certainty') == 'confirmed' for i in issues):
            errors.append('没有值得自动处理的已确认第一/二类问题')
        if (not text(decision.get('method_key')) or not text(decision.get('cause_key')) or not decision.get('preserve_constraints')
                or any(not text(x) for x in decision.get('preserve_constraints', []))):
            errors.append('修复须明确方法及正确内容保留约束')
    if any(i.get('category') == 2 for i in issues) and action in CALL_ACTIONS:
        factors = decision.get('factors', {})
        if any(not text(factors.get(k)) for k in ('impact', 'distribution', 'scope', 'preservation_risk', 'history', 'manual_cost')):
            errors.append('第二类须简记六项取舍依据，不按数量机械重生')
    from coordinate_repair import decision_errors as coordinate_errors
    errors.extend(coordinate_errors(decision))
    from spatial_contract import decision_errors as spatial_errors
    errors.extend(spatial_errors(decision))
    return errors


def load_decision(root, record, attempt_id):
    attempt = attempt_for(record, attempt_id)
    ref = record.get('production_decisions', {}).get(attempt_id)
    decision = read_json(checked_file(Path(root), ref))
    report = read_json(checked_file(Path(root), attempt['qa_report']))
    if len(report.get('panels', [])) != 1:
        raise ValueError('决定须绑定唯一逐格QA')
    item = report['panels'][0]
    if item.get('panel_id') != attempt['panel_id'] or item.get('image_sha256') != attempt['output']['sha256']:
        raise ValueError('QA与实际采用图不一致')
    from light_review import at_root, FIELD, POLICY as LIGHT_POLICY
    if at_root(root) != (report.get(FIELD) == LIGHT_POLICY):
        raise ValueError('QA review profile differs from the frozen run')
    errors = decision_errors(decision, attempt, item)
    if errors:
        raise ValueError(';'.join(errors))
    return attempt, decision, item, ref


def selected(root, record):
    adoption = record.get('adoption', {})
    if not text(adoption.get('reason')):
        raise ValueError('缺采用版本及选择理由')
    attempt, decision, item, ref = load_decision(root, record, adoption.get('attempt_id'))
    if adoption.get('decision') != ref:
        raise ValueError('采用版本与问题决定版本不一致')
    return attempt, decision, item, ref


def outcome(decision, *, complete=True):
    if not complete:
        return 'INCOMPLETE'
    if any(i['category'] == 1 and i['certainty'] == 'confirmed' for i in decision['issues']):
        return 'MANUAL_PRIORITY'
    return 'MANUAL_RETOUCH' if decision['issues'] else 'DELIVERABLE'


def repeated_method(state, root, decision):
    """Reuse actual common-cause diagnosis, not an error-count threshold."""
    report = state.get('episode_failure_diagnosis', {})
    stopped = report.get('stopped_methods', [])
    if stopped and not report.get('source'): raise ValueError('停止方法须有真实共因诊断来源')
    if report.get('source'):
        actual = read_json(checked_file(Path(root), report['source']))
        if {**actual, 'source': report['source']} != report:
            raise ValueError('共因诊断来源不一致')
    method = decision.get('method_key')
    cause = decision.get('cause_key')
    if any(r.get('method_key') == method and r.get('cause_key') == cause for r in stopped):
        return not text(decision.get('different_plan'))
    return False


def priority(state, record, shot, root):
    """Do not turn delivery eligibility into dependency/reference acceptance."""
    from stage_deadlines import enabled as speed_enabled
    if speed_enabled(state):
        return 0 if record.get('status') == 'PENDING' else 1
    if record.get('status') == 'PENDING':
        return 2
    try:
        old = record.get('attempt_history', [])[-1]
        _, d, _, _ = load_decision(root, record, old['attempt_id'])
        major = any(i['category'] == 1 for i in d['issues'])
        dependency = any(record['panel_id'] in p.get('generation_dependencies', []) for p in shot)
        return 0 if major and dependency else 1 if major else 3
    except (ValueError, KeyError, IndexError, OSError, TypeError):
        return 3


def register(state_path, expected_sha256, proposal_ref):
    from runtime_clock import require_step
    require_step(state_path)
    from runtime_pipeline import POLICY, record
    from codex_reference_contract import file_session,verify_read_snapshot
    from authority_updates import state_write_lock
    import time
    path=Path(state_path).resolve();state=read_json(path)
    if state.get('runtime_pipeline_policy')!=POLICY or 'dispatch_consistency' in state:
        return _register(path,expected_sha256,proposal_ref)
    started=time.monotonic()
    with file_session() as snapshot:
        updated,seen=_register(path,expected_sha256,proposal_ref,_prepare_only=True)
    validated=time.monotonic()
    with state_write_lock(path):
        acquired=time.monotonic();verify_read_snapshot(snapshot,refresh_views=False)
        result=_persist_register(path,expected_sha256,updated,seen)
        written=time.monotonic()
    timing={'validation':validated-started,'lock_wait':acquired-validated,'lock_hold':written-acquired}
    result['pipeline_timing']=timing
    try:result['pipeline_metric']=record(path,'decisions-register',timing,panel_ids=seen)
    except OSError as exc:result['timing_record_error']=str(exc)
    return result


def _register(state_path, expected_sha256, proposal_ref, *, _prepare_only=False):
    """CAS-register immutable decisions/adoption; preserve every execution field."""
    from authority_updates import state_write_lock
    from dispatch_publication import require_legacy
    from platform_io import atomic_json
    from batch_round import attempt_errors
    state_path = Path(state_path).resolve(); root = state_path.parent.parent
    from contextlib import nullcontext
    with (nullcontext() if _prepare_only else state_write_lock(state_path)):
        state = read_json(state_path); require_legacy(state)
        if not enabled(state) or digest(state_path) != expected_sha256:
            raise ValueError('STATE_CHANGED或原运行未声明新合同；不迁移旧RV')
        proposal = read_json(checked_file(root, proposal_ref))
        updated = copy.deepcopy(state)
        seen = set()
        for entry in proposal.get('panels', []):
            pid = entry['panel_id']
            if pid in seen:
                raise ValueError('重复格号')
            seen.add(pid)
            row = next(r for r in updated['panels'] if r['panel_id'] == pid)
            ref = entry['decision']; decision = read_json(checked_file(root, ref))
            attempt = attempt_for(row, decision.get('attempt_id'))
            errors = attempt_errors(state, root, attempt)
            if errors:
                raise ValueError(';'.join(errors))
            row.setdefault('production_decisions', {})[attempt['attempt_id']] = ref
            load_decision(root, row, attempt['attempt_id'])
            if entry.get('adopt'):
                row['adoption'] = {'attempt_id': attempt['attempt_id'], 'decision': ref,
                                   'reason': entry['adoption_reason']}
                selected(root, row)
        if proposal.get('delivery_review'):
            from panel_delivery import build
            ref = proposal['delivery_review']
            if read_json(checked_file(root, ref)) != build(updated, root):
                raise ValueError('交接审查索引与当前采用版本不一致')
            updated['delivery_review'] = ref
        if not seen and not proposal.get('delivery_review'):
            raise ValueError('没有待登记决定')
        if _prepare_only:return updated, sorted(seen)
        return _persist_register(state_path, expected_sha256, updated, sorted(seen))


def _persist_register(state_path, expected_sha256, updated, seen):
    from platform_io import atomic_json
    history = state_path.parent / 'runtime_history'; history.mkdir(exist_ok=True)
    original = history / (expected_sha256 + '.json')
    if not original.exists(): original.write_bytes(state_path.read_bytes())
    if digest(state_path) != expected_sha256:
        raise ValueError('STATE_CHANGED')
    from runtime_clock import require_step
    require_step(state_path)
    atomic_json(state_path, updated)
    return {'status': 'DECISIONS_RECORDED', 'panel_ids': seen,
            'state_sha256': digest(state_path), 'image_calls': 0, 'user_approval': 'NOT_GRANTED'}
