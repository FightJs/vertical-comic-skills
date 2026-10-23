"""Scoped spatial evidence and repair decisions; no pixel inference or approvals.

Explicit selected_relation_ids opt a panel into the new input contract. Legacy
frozen panels retain their old contract. Content signatures detect stale reviewed
projections; callers must never mint a replacement signature to bypass a review.
"""
from __future__ import annotations
import hashlib
import json

CAMERA_FIELDS = ('scene_id', 'camera_angle_family', 'shot_scale', 'frame_ratio',
                 'camera_position', 'facing_direction', 'camera_height',
                 'visible_region', 'camera_view_signature')
SPATIAL_KINDS = {'rigid_edge', 'projection_conflict', 'layout_connection',
                 'support_invention', 'framing_pressure', 'uncertain'}
GLOBAL_KINDS = {'projection_conflict', 'layout_connection', 'support_invention'}
CALL_ACTIONS = {'local_edit', 'regenerate', 'rebuild_inputs'}


def text(value):
    return isinstance(value, str) and bool(value.strip())


def enabled(panel):
    ev = panel.get('visual_evidence')
    return isinstance(ev, dict) and 'selected_relation_ids' in ev


def projection_signature(panel, context=None):
    ev = panel.get('visual_evidence') or {}
    ctx = context if context is not None else panel.get('visual_evidence_context') or {}
    selected = ev.get('selected_relation_ids')
    selected = selected if isinstance(selected, list) else []
    value = {key: panel.get(key) for key in CAMERA_FIELDS}
    value.update(framing=panel.get('framing'), subjects=panel.get('subject_design'),
                 characters=panel.get('characters_visible', panel.get('characters', panel.get('people'))),
                 blocking=ev.get('blocking'), visibility=ev.get('visibility'),
                 scene_view=ev.get('scene_view'), layout_basis={
                     'layout_id': (ctx.get('layout') or {}).get('layout_id'),
                     'relations': [r for r in (ctx.get('layout') or {}).get('relations', [])
                                   if isinstance(r, dict) and r.get('id') in selected]},
                 view_basis=ctx.get('scene_view'))
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def selection_errors(panel, context=None):
    if not enabled(panel):
        if {'fixed_spatial_relations', 'framing_space_conflict'} & set(panel.get('memory_tags', [])):
            return ['SPATIAL_HOLD:新空间风险标签须显式选择selected_relation_ids，确无固定关系时为空列表']
        return []
    ev = panel['visual_evidence']
    selected = ev['selected_relation_ids']
    if (not isinstance(selected, list) or any(not text(x) for x in selected)
            or len(set(selected)) != len(selected)):
        return ['SPATIAL_HOLD:selected_relation_ids须为不重复的关系ID列表']
    errors = []
    if panel.get('visual_evidence_policy') != 'visual_evidence_v1':
        errors.append('空间选择须沿用visual_evidence_v1及原实图QA')
    ctx = context if context is not None else panel.get('visual_evidence_context') or {}
    layout = ctx.get('layout') or {}
    relations = {r.get('id'): r for r in layout.get('relations', []) if isinstance(r, dict)}
    if selected and ev.get('spatial_applicability') != 'REQUIRED':
        errors.append('选中固定关系不能豁免空间检查')
    checks = ev.get('checks', [])
    checks = checks if isinstance(checks, list) else []
    covered = set()
    for check in checks:
        if not isinstance(check, dict) or 'relation_ids' not in check:
            continue
        ids = check['relation_ids']
        if (check.get('kind') != 'space' or not isinstance(ids, list) or not ids
                or any(not text(x) for x in ids) or len(set(ids)) != len(ids)):
            errors.append('relation_ids只能绑定具体space检查且不得重复'); continue
        if not set(ids) <= set(selected):
            errors.append('空间检查引用未选中的关系')
        covered.update(ids)
    for ident in selected:
        if ident not in relations:
            errors.append('关系不属于当前批准布局:'+ident)
        elif not text(relations[ident].get('reference_sha256')) or not text(relations[ident].get('expected')):
            errors.append('选中关系缺来源或具体判据:'+ident)
        if ident not in covered:
            errors.append('选中关系未绑定具体space观察:'+ident)
    return ['SPATIAL_HOLD:'+e for e in errors]


def projection_errors(panel, context=None):
    if not enabled(panel):
        return []
    signature = projection_signature(panel, context)
    errors = []
    for ident, row in (panel['visual_evidence'].get('detail_visibility') or {}).items():
        if isinstance(row, dict) and row.get('status') == 'visible':
            projection = row.get('projection') or {}
            if not isinstance(projection, dict) or projection.get('basis_sha256') != signature:
                errors.append('SPATIAL_HOLD:'+ident+':细节投影未绑定当前机位/站位/裁切，须复核后重新记录')
    return errors


def override_errors(shot, execution):
    """Reject conflicting repeated sources, never reconcile authored design silently."""
    if not (enabled(shot) or enabled(execution)):
        return []
    errors = []
    for key in (*CAMERA_FIELDS, 'framing', 'subject_design'):
        if key in shot and key in execution and shot[key] != execution[key]:
            errors.append('SPATIAL_HOLD:镜头与执行输入重复定义不一致:'+key)
    a, b = shot.get('visual_evidence') or {}, execution.get('visual_evidence') or {}
    for key in ('blocking', 'visibility', 'scene_view', 'selected_relation_ids'):
        if key in a and key in b and a[key] != b[key]:
            errors.append('SPATIAL_HOLD:镜头与执行空间依据不一致:'+key)
    return errors


def decision_errors(decision):
    issues = decision.get('issues', [])
    rows = [i for i in issues if isinstance(i, dict) and 'spatial_kind' in i] if isinstance(issues, list) else []
    if not rows:
        return []
    errors = []
    for row in rows:
        kind = row.get('spatial_kind')
        if kind not in SPATIAL_KINDS:
            errors.append('未知空间问题类型')
        if kind in GLOBAL_KINDS and row.get('repair_scope') != 'global_space':
            errors.append('布局/投影/承托错误不能标为局部直边问题')
        if kind in {'projection_conflict', 'layout_connection'} and row.get('category') != 1:
            errors.append('整体投影/布局连接错误不能降为局部细节类别')
    action = decision.get('action')
    if action not in CALL_ACTIONS | {'crop_candidate'}:
        return ['SPATIAL_HOLD:'+e for e in errors]
    assessment = decision.get('spatial_assessment')
    if not isinstance(assessment, dict):
        return ['SPATIAL_HOLD:空间返修缺依据与范围诊断']
    if any(not text(assessment.get(k)) for k in ('evidence', 'target_basis', 'input_evidence')):
        errors.append('空间诊断缺原图观察、目标依据或完整输入核对')
    if assessment.get('input_status') not in {'no_conflict_signal', 'resolved'}:
        errors.append('须先解决输入冲突，再选择空间返修方法')
    if assessment.get('input_status') == 'resolved' and not text(assessment.get('resolution_evidence')):
        errors.append('已解决的输入冲突须有实际修订依据')
    targets = set(decision.get('fix_now', []) + decision.get('opportunistic', []))
    for row in rows:
        if row.get('id') not in targets:
            continue
        kind = row.get('spatial_kind')
        if kind == 'uncertain' or row.get('certainty') != 'confirmed':
            errors.append('空间问题未确定，不能直接生成或裁切')
        elif kind in GLOBAL_KINDS and action != 'rebuild_inputs':
            errors.append('整体投影/布局/承托问题须先修输入，不能局部拉直或直接重抽')
        elif kind == 'framing_pressure' and action not in {'crop_candidate', 'rebuild_inputs'}:
            errors.append('构图压力须检查裁切或先修取景输入')
        elif kind == 'rigid_edge' and action == 'local_edit':
            if (row.get('repair_scope') != 'local_structure' or
                    any(assessment.get(k) != 'confirmed' for k in ('layout_status', 'camera_status'))):
                errors.append('局部直边修复要求布局和机位已核对成立')
    # A global unresolved defect anywhere in this image invalidates the premise
    # of a local geometry repair, even when that defect was marked for manual work.
    if action == 'local_edit' and any(r.get('spatial_kind') in GLOBAL_KINDS for r in rows):
        errors.append('同图整体空间未解决，不能把局部修复当作空间解决')
    return ['SPATIAL_HOLD:'+e for e in errors]


def binding_errors(decision, panel):
    targets = set(decision.get('fix_now', []) + decision.get('opportunistic', []))
    rows = [i for i in decision.get('issues', []) if isinstance(i, dict)
            and i.get('id') in targets and 'spatial_kind' in i]
    if not rows:
        return []
    errors = decision_errors(decision)
    focus = (panel.get('repair_focus') or {}).get('spatial_issue_checks')
    checks = {c.get('id'): c for c in (panel.get('visual_evidence') or {}).get('checks', []) if isinstance(c, dict)}
    if not isinstance(focus, dict) or set(focus) != {r['id'] for r in rows}:
        return errors + ['SPATIAL_HOLD:实际返修包须将每个空间问题绑定原有具体检查ID']
    for ident, ids in focus.items():
        if (not isinstance(ids, list) or not ids or any(not text(x) for x in ids)
                or len(set(ids)) != len(ids) or any(i not in checks or checks[i].get('kind') not in {'space','contact'} for i in ids)):
            errors.append('SPATIAL_HOLD:空间修复目标未落实到具体空间/接触判据:'+ident)
    if not enabled(panel):
        errors.append('SPATIAL_HOLD:空间返修包缺明确的关系选择；无固定关系时显式空列表')
    errors.extend(selection_errors(panel))
    errors.extend(projection_errors(panel))
    return errors
