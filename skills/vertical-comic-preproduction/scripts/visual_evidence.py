"""Concrete visual expectations, frozen provenance and recorded observations.

These checks validate declarations, not pixels or natural-language geometry.
Legacy runs without this policy retain their frozen contract.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

POLICY = 'visual_evidence_v1'
KINDS = {'space', 'presence', 'contact', 'hand', 'accessory', 'clarity'}
VISIBILITY = {'visible', 'occluded', 'out_of_frame', 'off_scene', 'omitted_by_design'}
BACKGROUND_POLICY = 'narrative_background_v1'
SIMPLIFIED_BACKGROUNDS = {'scene_flat', 'scene_softened', 'scene_outline'}
BACKGROUND_TREATMENTS = {'clear_limited', 'approved_depth_of_field'} | SIMPLIFIED_BACKGROUNDS
BODY_CROP_LABELS = {'waist_up': '腰以上', 'chest_up': '胸以上',
    'shoulders_up': '肩以上', 'face_detail': '面部局部', 'hands_detail': '手部局部',
    'object_detail': '物件局部', 'full_body': '全身', 'mixed': '逐人物指定裁切',
    'environment': '必要环境范围'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def text(value):
    return isinstance(value, str) and bool(value.strip())


def feasibility_questions(panel):
    """Concrete human review targets; this does not prove semantic geometry."""
    value = {'crop_and_required_information':{'visible_region':panel.get('visible_region'),
                'required_visible':panel.get('framing',{}).get('required_visible',[]),
                'check':'裁切内是否同时保留全部必显信息及接触'},
            'camera_and_fixed_layout':{'camera_position':panel.get('camera_position'),
                'camera_facing':panel.get('camera_facing'),
                'check':'该机位能否看见指定对象，固定布局、承托和反射是否成立'},
            'source_and_actual_prompt':{'check':'原源及B的湿斑、道具、动作对象与下缘要求是否进入实际输入，是否残留相反描述'}}
    if panel.get('input_quality_policy'):
        value['execution_inputs'] = {'policy':panel['input_quality_policy'], 'actions':[c for c in panel.get('visual_evidence',{}).get('checks',[]) if c.get('kind') in {'hand','contact'}], 'scene_view':panel.get('visual_evidence',{}).get('scene_view'), 'detail_visibility':panel.get('visual_evidence',{}).get('detail_visibility')}
        value['contact_readability'] = {
            'check':'关键手和接触能否在本裁切内辨认所属肩肘腕、目标部位及动作阶段；真实遮挡不强求五指全露。复杂接触读不清先修机位，不交模型补猜。'}
        value['reference_conflicts'] = {
            'check':'当前视图/衣装细节是否清晰且随实际输入携带；画风图或编辑底图是否含与本格相反的发型、饰品、肢体或场景。'}
        value['staging_readability'] = {
            'characters_visible':panel.get('characters_visible'),
            'fixed_props_visible':panel.get('fixed_props_visible'),
            'blocking':panel.get('visual_evidence',{}).get('blocking'),
            'visibility':panel.get('visual_evidence',{}).get('visibility'),
            'check':'分别核对摄影机、头部与视线目标；使用者和摄影机各看到物件哪一面；全身肢体任务、承托及持续在场实体是否相容。抽象表现不得未经解释变成实物。'}
    if 'semantic_facts' in panel or 'subject_visibility' in panel:
        value['explicit_execution_scope'] = {
            'body_crop': panel.get('framing', {}).get('body_crop'),
            'subject_visibility': panel.get('subject_visibility', {}),
            'semantic_facts': panel.get('semantic_facts', []),
            'adjacent_face_comparison': panel.get('adjacent_face_comparison', {}),
            'check': '源指定状态、逐人物可见面、下沿及必显手势须相容；身份可辨与面部可比较分别判断'}
    return copy.deepcopy(value)


def feasibility_errors(panel, check):
    from input_semantics import conflict_errors
    conflicts = conflict_errors(panel, '')
    if conflicts: return conflicts
    if (check.get('status')!='PASS' or not text(check.get('evidence'))
            or check.get('expected')!=feasibility_questions(panel)):
        return [str(panel.get('panel_id'))+':镜头可实现性与实际输入尚未按当前镜头核对']
    return []


def background_binding_errors(state, *documents):
    policy = state.get('background_policy')
    if policy not in (None, BACKGROUND_POLICY):
        return ['BACKGROUND_HOLD:未知背景策略']
    errors = []
    if policy and state.get('visual_evidence_policy') != POLICY:
        errors.append('BACKGROUND_HOLD:背景策略须配套visual_evidence_v1')
    for doc in documents:
        if doc.get('background_policy') != policy:
            errors.append('BACKGROUND_HOLD:背景策略与冻结来源不同')
    return errors


def background_config_errors(value):
    if not isinstance(value, dict) or value != {
            'policy': BACKGROUND_POLICY, 'selection': 'content_driven',
            'closeup_preference': 'scene_flat'}:
        return ['背景配置须为narrative_background_v1/content_driven/scene_flat']
    return []


def background_plan_errors(panel, context=None):
    framing = panel.get('framing') or {}
    mode = framing.get('background_treatment')
    policy = panel.get('background_policy')
    if policy is None:
        return ['BACKGROUND_HOLD:新背景模式/计划须声明背景策略'] if (
            mode in SIMPLIFIED_BACKGROUNDS or 'background_plan' in framing) else []
    errors = background_binding_errors(panel)
    if mode not in BACKGROUND_TREATMENTS:
        errors.append('BACKGROUND_HOLD:缺合法背景模式')
    plan = framing.get('background_plan')
    if not isinstance(plan, dict): return errors + ['BACKGROUND_HOLD:缺本格背景计划']
    if any(not text(plan.get(k)) for k in ('reason', 'profile_id')):
        errors.append('BACKGROUND_HOLD:缺选择理由/场景色调依据')
    ids = {}
    for name in ('retain', 'omit'):
        rows = plan.get(name)
        if not isinstance(rows, list): errors.append('BACKGROUND_HOLD:'+name+'须为清单'); continue
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or not text(row.get('id')) or not text(row.get('expected')):
                errors.append('BACKGROUND_HOLD:保留/省略项须有稳定ID与具体描述'); continue
            if row['id'] in seen: errors.append('BACKGROUND_HOLD:保留/省略项重复')
            seen.add(row['id'])
        ids[name] = seen
    if ids.get('retain', set()) & ids.get('omit', set()):
        errors.append('BACKGROUND_HOLD:同一内容不能同时保留和省略')
    focus = plan.get('sharp_focus')
    if not isinstance(focus, list) or not focus or any(not text(v) for v in focus):
        errors.append('BACKGROUND_HOLD:缺本格重点清晰对象')
    # Exact declarations only. Natural-language equivalence still needs B semantic review.
    omissions = {r.get('expected') for r in plan.get('omit', []) if isinstance(r, dict)} if isinstance(plan.get('omit'), list) else set()
    if omissions & set(framing.get('required_visible') or []):
        errors.append('BACKGROUND_HOLD:必显内容不能列为省略项')
    ev = panel.get('visual_evidence') or {}
    people = set(ev.get('blocking') or {}) | set((panel.get('continuity_contract') or {}).get('subjects') or {})
    if ids.get('omit', set()) & people:
        errors.append('BACKGROUND_HOLD:不能把在场人物列为背景省略项')
    for entity in ids.get('retain', set()):
        status = (ev.get('visibility') or {}).get(entity, {}).get('status')
        if status in {'off_scene', 'out_of_frame', 'omitted_by_design'}:
            errors.append('BACKGROUND_HOLD:保留项与本机位可见性相冲突')
    ctx = context if context is not None else panel.get('visual_evidence_context')
    profile = ctx.get('background_profile') if isinstance(ctx, dict) else None
    if ctx is None: return errors  # Shot-only structural validation; packet gate supplies derived context.
    if not isinstance(profile, dict): return errors + ['BACKGROUND_HOLD:缺基准派生背景资料']
    ev = panel.get('visual_evidence') or {}
    if (profile.get('profile_id') != plan.get('profile_id') or
            profile.get('scene_id') != panel.get('scene_id') or
            profile.get('space_id') != ev.get('space_id', panel.get('scene_id')) or
            profile.get('scene_run_id') != ev.get('scene_run_id')):
        errors.append('BACKGROUND_HOLD:色调依据不属于本格场景/子空间/连续状态')
    if any(not text(profile.get(k)) for k in ('base_color', 'line_color', 'lighting', 'reference_sha256')):
        errors.append('BACKGROUND_HOLD:场景色调/光向/来源不完整')
    # Required physical structures may not be dropped by changing spatial applicability.
    if plan.get('retain') and ev.get('spatial_applicability') != 'REQUIRED':
        errors.append('BACKGROUND_HOLD:保留实体的格须检查空间')
    return errors


def background_execution_lines(panel, context=None):
    framing = panel['framing']; plan = framing['background_plan']
    ctx = context if context is not None else panel.get('visual_evidence_context')
    if not isinstance(ctx, dict) or not isinstance(ctx.get('background_profile'), dict):
        raise ValueError('BACKGROUND_HOLD:实际编译缺基准派生背景资料')
    profile = ctx['background_profile']; mode = framing['background_treatment']
    wording = {
        'clear_limited': '必要实景：保留本格需要的场景结构与清楚轮廓，无关细节按省略清单处理。',
        'scene_flat': '同色留白：成图采用人物漫画＋场景同色平涂底。人物外轮廓到画幅边界之间的留白区域是一整片均匀实色，仅在下列保留项所在局部绘必要实体；其余区域不重建房间透视或任何未保留的物件轮廓，不用渐变、散景或纹理填充。',
        'scene_softened': '实景柔化：保留必要结构的位置、轮廓与遮挡，以二维大色块降低后景纹理、边缘和对比；不使用摄影散景或光斑。',
        'scene_outline': '轮廓概括：次要对象使用低对比色块和简洁实体轮廓，保持必要数量、位置与遮挡；不得把真实人物画成墙面投影。',
        'approved_depth_of_field': '特殊景深仅执行本格批准设计。',
    }
    lines = [wording[mode],
        f"场景底色：{profile['base_color']}；轮廓色：{profile['line_color']}；人物及环境光向：{profile['lighting']}。",
        '必须保留：' + ('；'.join(r['expected'] for r in plan['retain']) or '本格无必显环境实体，人物与动作仍按原约束执行') + '。',
        '本格省略绘制：' + ('；'.join(r['expected'] for r in plan['omit']) or '无额外省略项') + '。',
        '重点清晰：' + '；'.join(plan['sharp_focus']) + '；人物轮廓、服装配饰、手部和动作对象不得因背景处理一起变软。',
        '场景参考职责：提供批准布局、环境色、光向及必要空间关系；宽景、材质与全套陈设不要求完整迁移到本格。',
        '省略仅改变绘制信息量，世界位置、人物在场状态、承托、接触、遮挡和剧情线索保持本格批准依据；不添加新灯具或装饰。']
    if mode == 'scene_flat':
        permitted = '；'.join(r['expected'] for r in plan['retain'])
        lines.insert(1, '最终背景绘制范围：' + (permitted if permitted else '没有需要绘出的环境实体或结构线，人物身后完整使用同色实色底') + '。')
        lines.append('场景参考中未列为保留项的镜框、镜面反射、灯带、窗框和柜体均不出现在最终留白区域；原物理环境仍存在但本格不绘出。人物和必要动作物件继续完整绘制。')
    return lines


def framing_errors(panel, *, prompt=False):
    """Opt-in framing extension; never changes a frozen legacy packet implicitly."""
    framing = panel.get('framing')
    if not isinstance(framing, dict) or 'background_treatment' not in framing:
        return background_plan_errors(panel)
    treatment = framing['background_treatment']
    if not isinstance(treatment, str) or treatment not in BACKGROUND_TREATMENTS:
        return ['background_treatment须为已支持的实景/留白/柔化/轮廓或批准景深']
    errors = background_plan_errors(panel)
    if (not isinstance(framing.get('body_crop'), str) or
            framing['body_crop'] not in BODY_CROP_LABELS or not text(framing.get('focus'))):
        errors.append('构图执行须有具体身体裁切和视觉重点')
    visible = framing.get('required_visible')
    if not isinstance(visible, list) or not visible or any(not text(v) for v in visible):
        errors.append('构图执行须列本格必显信息')
    if not text(panel.get('visible_region')):
        errors.append('背景处理须有本机位具体可见区域，不能只写简化背景')
    if treatment == 'approved_depth_of_field' and not text(framing.get('background_treatment_basis')):
        errors.append('特殊景深须说明本格实际批准设计依据')
    if prompt and not errors and (not isinstance(panel.get('prompt'), str) or
            framing_execution_block(panel) not in panel['prompt']):
        errors.append('实际提示词缺少本格构图与背景处理执行块')
    return errors


def framing_execution_block(panel, context=None):
    """Compile concrete approved framing, not a fixed subject-size quota."""
    framing = panel.get('framing') or {}
    if not isinstance(framing, dict) or 'background_treatment' not in framing:
        return ''
    checked_panel = {**panel, 'visual_evidence_context': context} if context is not None else panel
    errors = framing_errors(checked_panel)
    if errors:
        raise ValueError(';'.join(errors))
    lines = ['本格构图与背景处理',
        f"视觉重点：{framing['focus']}；身体裁切：{BODY_CROP_LABELS[framing['body_crop']]}。",
        '必显信息：' + '；'.join(framing['required_visible']) + '。',
        f"本机位可见区域：{panel['visible_region']}。"]
    if panel.get('background_policy') == BACKGROUND_POLICY:
        lines.extend(background_execution_lines(panel, context))
        if framing['background_treatment'] == 'approved_depth_of_field':
            lines.append(framing['background_treatment_basis'])
    elif framing['background_treatment'] == 'clear_limited':
        lines.append('保留的背景清晰、简洁并符合批准画风；通过机位与取景范围减少背景面积，不加入背景虚化、散景或光斑，不移动固定实体或丢失必显动作。')
    else:
        lines.append('背景清晰度与景深执行本格批准设计：' + framing['background_treatment_basis'])
    return '\n'.join(lines)


def binding_errors(state, *documents):
    from input_quality import bindings as input_bindings
    from appearance_lock import bindings as appearance_bindings
    background_errors = background_binding_errors(state, *documents) + input_bindings(state, *documents) + appearance_bindings(state, *documents)
    policy = state.get('visual_evidence_policy')
    if policy not in (None, POLICY):
        return ['VISUAL_EVIDENCE_HOLD:未知质量证据策略']
    if policy is None:
        return background_errors + (['VISUAL_EVIDENCE_HOLD:质量判据不能删除策略后作为旧包执行'] if 'visual_evidence' in state else [])
    return background_errors + ['VISUAL_EVIDENCE_HOLD:依据/执行包缺少冻结质量策略'
            for document in documents if document.get('visual_evidence_policy') != policy]


def basis_errors(basis):
    from appearance_lock import basis_errors as appearance_basis_errors
    if basis.get('visual_evidence_policy') is None:
        return background_binding_errors(basis) + appearance_basis_errors(basis)
    from input_quality import basis_errors as input_basis_errors
    errors = binding_errors(basis) + input_basis_errors(basis) + appearance_basis_errors(basis)
    refs = {r.get('sha256') for r in basis.get('reference_files', [])}
    for name in ('scene_layouts', 'appearance_details'):
        if not isinstance(basis.get(name), dict):
            errors.append(f'VISUAL_EVIDENCE_HOLD:基准{name}须为对象，确无内容用空对象')
    if errors: return errors
    for sid, layout in basis.get('scene_layouts', {}).items():
        if not isinstance(layout, dict) or not text(layout.get('layout_id')):
            errors.append(f'{sid}:布局缺layout_id'); continue
        entities = layout.get('entities')
        if not isinstance(entities, dict) or not entities or any(
                not text(k) or not text(v) for k, v in entities.items()):
            errors.append(f'{sid}:布局须列具体实体及来源支持的描述'); entities = {}
        relations = layout.get('relations')
        if not isinstance(relations, list) or not relations:
            errors.append(f'{sid}:布局缺少实际固定关系'); continue
        seen = set()
        for row in relations:
            if not isinstance(row, dict): errors.append(f'{sid}:关系须为对象'); continue
            if not text(row.get('id')) or row.get('id') in seen:
                errors.append(f'{sid}:关系ID缺失或重复')
            seen.add(row.get('id'))
            if any(row.get(k) not in entities for k in ('subject', 'object')) or row.get('subject') == row.get('object'):
                errors.append(f'{sid}:关系两端须为不同已登记实体')
            if not text(row.get('expected')) or row.get('reference_sha256') not in refs:
                errors.append(f'{sid}:关系缺具体判据或批准参考来源')
    if basis.get('background_policy') == BACKGROUND_POLICY:
        profiles = basis.get('scene_background_profiles')
        if not isinstance(profiles, dict):
            errors.append('BACKGROUND_HOLD:基准scene_background_profiles须为对象')
        else:
            for pid, row in profiles.items():
                if (not isinstance(row, dict) or row.get('profile_id') != pid or
                        any(not text(row.get(k)) for k in ('scene_id', 'space_id', 'scene_run_id', 'base_color', 'line_color', 'lighting')) or
                        row.get('reference_sha256') not in refs):
                    errors.append(f'{pid}:BACKGROUND_HOLD:色调依据/场景状态/批准参考缺失')
    for did, detail in basis.get('appearance_details', {}).items():
        if not isinstance(detail, dict) or any(not text(detail.get(k)) for k in
                ('subject_id', 'costume_state', 'expected')) or detail.get('reference_sha256') not in refs:
            errors.append(f'{did}:细节缺所属人物/衣装/具体判据/批准参考来源')
    return errors


def context_for(basis, panel):
    """Small execution copy; compared with approved originals at every gate."""
    ev = panel['visual_evidence']
    details = {key: basis['appearance_details'][key] for key in ev.get('detail_visibility', {})}
    space = ev.get('space_id', panel.get('scene_id'))
    layout = basis['scene_layouts'].get(space)
    if layout and layout.get('scene_id', space) != panel.get('scene_id'):
        raise ValueError('布局不属于本格场景；酒店不同房间须绑定真实子空间')
    result = {'layout': copy.deepcopy(layout), 'details': copy.deepcopy(details)}
    if panel.get('background_policy') == BACKGROUND_POLICY:
        pid = panel['framing']['background_plan']['profile_id']
        result['background_profile'] = copy.deepcopy(basis['scene_background_profiles'][pid])
    from input_quality import context_for as quality_context
    result.update(quality_context(basis, panel))
    return result


def panel_errors(panel, context=None, *, prompt=False):
    if panel.get('visual_evidence_policy') is None:
        return binding_errors(panel) + framing_errors(panel, prompt=prompt)
    checked_panel = {**panel, 'visual_evidence_context': context} if context is not None else panel
    errors = binding_errors(panel) + framing_errors(checked_panel, prompt=prompt)
    ev = panel.get('visual_evidence')
    if not isinstance(ev, dict): return errors + ['VISUAL_EVIDENCE_HOLD:缺少本格具体质量判据']
    context = context if context is not None else panel.get('visual_evidence_context')
    if not isinstance(context, dict): return errors + ['VISUAL_EVIDENCE_HOLD:缺少基准派生上下文']
    if not text(ev.get('scene_run_id')):
        errors.append('连续场景须有scene_run_id')
    extra=ev.get('comparison_panel_ids',[])
    if (not isinstance(extra,list) or any(not text(pid) for pid in extra)
            or len(set(extra))!=len(extra) or panel.get('panel_id') in extra):
        errors.append('补充连续性比较须为不重复的前序格ID，不能指向自己')
    spatial = ev.get('spatial_applicability')
    if spatial not in {'REQUIRED', 'NOT_VISIBLE'} or not text(ev.get('spatial_reason')):
        errors.append('须说明本格空间检查适用性和依据')
    if panel.get('framing', {}).get('background_level') != 'minimal' and spatial != 'REQUIRED':
        errors.append('有背景空间的批准镜头不能豁免空间检查')
    layout = context.get('layout')
    if spatial == 'REQUIRED' and not isinstance(layout, dict): errors.append('缺适用批准布局')
    blocking, visibility = ev.get('blocking'), ev.get('visibility')
    if not isinstance(blocking, dict) or not isinstance(visibility, dict):
        return errors + ['blocking/visibility须为实体映射']
    known = set(blocking) | set((layout or {}).get('entities', {}))
    if not set(blocking) <= set(visibility): errors.append('在场状态中的实体须逐项说明本格可见性')
    for entity, state in blocking.items():
        if not isinstance(state, dict) or any(not text(state.get(k)) for k in ('position', 'facing', 'basis')) or state.get('presence') not in {'present', 'off_scene'}:
            errors.append(f'{entity}:缺世界位置、朝向、在场状态或来源')
    for entity, row in visibility.items():
        if entity not in known or not isinstance(row, dict) or row.get('status') not in VISIBILITY or any(
                not text(row.get(k)) for k in ('expected', 'basis')):
            errors.append(f'{entity}:可见性缺具体判据/依据或实体未登记'); continue
        if row['status'] == 'omitted_by_design':
            plan = (panel.get('framing') or {}).get('background_plan') or {}
            omitted = {r.get('id') for r in plan.get('omit', []) if isinstance(r, dict)}
            if panel.get('background_policy') != BACKGROUND_POLICY or entity not in omitted or entity in blocking:
                errors.append(f'{entity}:只有批准省略的环境实体可标omitted_by_design，人物不得消失')
        if entity in blocking and isinstance(blocking[entity], dict):
            departed = blocking[entity].get('presence') == 'off_scene'
            if departed != (row['status'] == 'off_scene'): errors.append(f'{entity}:离场与画外/遮挡不能混用')
    for subject in panel.get('continuity_contract', {}).get('subjects', {}):
        if visibility.get(subject, {}).get('status') != 'visible':
            errors.append(f'{subject}:实际入画人物必须在可见性记录中为visible')
    checks = ev.get('checks')
    if not isinstance(checks, list) or not checks: return errors + ['缺少可观察检查项']
    ids, kinds = set(), set()
    for check in checks:
        if not isinstance(check, dict): errors.append('检查项须为对象'); continue
        cid, kind = check.get('id'), check.get('kind')
        if not text(cid) or cid in ids or kind not in KINDS or not text(check.get('expected')):
            errors.append('检查项ID/类别/具体预期缺失或重复')
        ids.add(cid); kinds.add(kind)
        if not isinstance(check.get('subject_ids'), list) or not check['subject_ids'] or any(not text(s) for s in check['subject_ids']):
            errors.append('检查项须指向具体实体/部位')
        if kind == 'contact' and any(not text(check.get(k)) for k in
                ('actor', 'actor_limb', 'target', 'target_part', 'visible_path')):
            errors.append('接触检查须写主动者、肢体、对象、接触部位和连接路径')
    if 'clarity' not in kinds: errors.append('每张图须检查原尺寸主体细节清晰度')
    if spatial == 'REQUIRED' and 'space' not in kinds: errors.append('空间适用格缺具体空间检查')
    if blocking and 'presence' not in kinds: errors.append('在场实体缺连续性检查')
    if 'multi_person_contact' in panel.get('memory_tags', []) and 'contact' not in kinds:
        errors.append('多人接触缺逐人物具体检查')
    hands = ev.get('hands')
    if not isinstance(hands, dict) or hands.get('applicability') not in {'REQUIRED', 'NOT_VISIBLE', 'NOT_APPLICABLE'} or not text(hands.get('basis')):
        errors.append('须明确手部适用性；真实遮挡不等于缺指')
    elif hands['applicability'] == 'REQUIRED' and 'hand' not in kinds: errors.append('可见手部缺具体检查项')
    details = ev.get('detail_visibility')
    if not isinstance(details, dict): errors.append('detail_visibility须明确记录细节可见性')
    else:
        if set(details) != set(context.get('details', {})): errors.append('细节与派生上下文不一致')
        for did, row in details.items():
            if not isinstance(row, dict) or row.get('status') not in VISIBILITY - {'off_scene', 'omitted_by_design'} or not text(row.get('basis')):
                errors.append(f'{did}:细节可见性/遮挡依据缺失')
            elif row['status'] == 'visible' and not any(c.get('kind') == 'accessory' and c.get('detail_id') == did for c in checks if isinstance(c, dict)):
                errors.append(f'{did}:可见细节缺专项检查')
    from input_quality import errors as input_errors
    errors.extend(input_errors(panel, context))
    from appearance_lock import panel_errors as appearance_errors, prompt_errors as appearance_prompt_errors
    errors.extend(appearance_errors(panel, context))
    if prompt: errors.extend(appearance_prompt_errors(panel))
    if prompt and not errors:
        block = execution_block(panel, context)
        if panel.get('visual_execution_block') != block or block not in panel.get('prompt', ''):
            errors.append('VISUAL_EVIDENCE_HOLD:实际提示词缺少冻结的具体空间/细节约束')
    return errors


def execution_block(panel, context=None):
    ev = panel['visual_evidence']; context = context or panel['visual_evidence_context']
    lines = ['本格可见关系与细节']
    framing = framing_execution_block(panel, context)
    if framing:
        lines.append(framing)
    if ev['spatial_applicability'] == 'REQUIRED':
        for row in (context.get('layout') or {}).get('relations', []):
            if panel.get('input_quality_policy') == 'execution_quality_v1':
                needed = set((ev.get('scene_view') or {}).get('required_anchors', [])) | set(ev['blocking'])
                if not {row['subject'], row['object']} <= needed: continue
            if any(ev['visibility'].get(entity, {}).get('status') == 'visible' for entity in (row['subject'], row['object'])):
                lines.append(row['expected'])
    for entity, state in ev['blocking'].items():
        if ev['visibility'].get(entity, {}).get('status') == 'visible':
            lines.append(f"{entity}仍在{state['position']}，朝向{state['facing']}。")
    for entity, row in ev['visibility'].items():
        if panel.get('input_quality_policy') == 'execution_quality_v1' and entity not in set(ev['blocking']) | set((ev.get('scene_view') or {}).get('required_anchors', [])): continue
        lines.append(f"{entity}：{row['status']}；{row['expected']}。")
    for row in ev['checks']:
        lines.append(row['expected'])
        if row['kind'] == 'contact':
            lines.append('；'.join(row[k] for k in ('actor', 'actor_limb', 'target', 'target_part', 'visible_path')))
    for did, row in ev['detail_visibility'].items():
        if row['status'] == 'visible': lines.append(context['details'][did]['expected'])
    from input_quality import execution_block as input_block
    quality_text = input_block(panel, context)
    if quality_text: lines.append(quality_text)
    from appearance_lock import execution_block as appearance_block
    detail_text=appearance_block(panel,context)
    if detail_text:lines.append(detail_text)
    return '\n'.join(dict.fromkeys(lines))


def shot_collection_errors(state, basis, shots, blocked=()):
    if state.get('visual_evidence_policy') is None: return []
    errors = binding_errors(state, basis, shots) + basis_errors(basis)
    previous = {}; seen = {}
    for p in shots.get('panels', []):
        pid = p.get('panel_id'); sid = p.get('scene_id'); ev = p.get('visual_evidence', {})
        scope = (sid, ev.get('space_id', sid))
        extra=ev.get('comparison_panel_ids',[])
        if isinstance(extra,list):
            for target in extra:
                ref=seen.get(target) if text(target) else None
                rev=(ref or {}).get('visual_evidence',{})
                if (ref is None or (ref.get('scene_id'),rev.get('space_id',ref.get('scene_id')))!=scope
                        or rev.get('scene_run_id')!=ev.get('scene_run_id')):
                    errors.append(f'{pid}:补充比较须指向已出现的同子空间/连续状态格，不得引用未来或其他场景')
        seen[pid]=p
        if pid in blocked:
            previous[scope] = p; continue
        errors.extend(f'{pid}:{e}' for e in binding_errors(state, p))
        try: context = context_for(basis, p)
        except (KeyError, TypeError, ValueError): errors.append(f'{pid}:具体质量依据、布局归属或引用缺失'); previous[scope] = p; continue
        errors.extend(f'{pid}:{e}' for e in panel_errors(p, context))
        prior = previous.get(scope)
        if ev.get('previous_panel_id') != (prior or {}).get('panel_id'):
            errors.append(f'{pid}:须关联同场景最近前序格，切场不重置连续性')
        if prior:
            old = prior.get('visual_evidence', {})
            if old.get('scene_run_id') != ev.get('scene_run_id'):
                if not text(ev.get('run_change_basis')): errors.append(f'{pid}:时间/场景状态重置缺原稿依据')
            else:
                before, after = old.get('blocking', {}), ev.get('blocking', {})
                changes = ev.get('changes', [])
                if not isinstance(changes, list): changes = []; errors.append(f'{pid}:changes须为清单')
                if set(before) - set(after): errors.append(f'{pid}:在场实体不能无记录消失；离场仍须保留状态')
                for entity in set(before) & set(after):
                    for field in ('position', 'facing', 'presence'):
                        if before[entity].get(field) != after[entity].get(field) and not any(
                                isinstance(c, dict) and c.get('entity_id') == entity and c.get('field') == field
                                and c.get('from') == before[entity].get(field) and c.get('to') == after[entity].get(field)
                                and text(c.get('basis')) for c in changes):
                            errors.append(f'{pid}:{entity}.{field}变化缺具体前后值和剧情依据')
        previous[scope] = p
    return errors


def packet_errors(state, shot, panel, basis):
    if state.get('visual_evidence_policy') is None: return framing_errors(panel, prompt=True)
    errors = binding_errors(state, shot, panel, basis)
    if panel.get('background_policy') and panel.get('framing') != shot.get('framing'):
        errors.append('BACKGROUND_HOLD:执行背景计划与批准镜头不同')
    if panel.get('visual_evidence') != shot.get('visual_evidence'): errors.append('执行包质量判据与获批镜头不同')
    if panel.get('frame_policy') and panel.get('frame_plan')!=shot.get('frame_plan'): errors.append('SINGLE_FRAME_HOLD:执行包与本格已选单画面不一致')
    try:
        context = context_for(basis, shot)
        if panel.get('visual_evidence_context') != context: errors.append('空间/细节派生上下文与批准基准不同')
        # Every approved detail for the actual visible costume must be accounted for.
        subjects = panel.get('continuity_contract', {}).get('subjects', {})
        expected = {key for key, d in basis.get('appearance_details', {}).items()
                    if d['subject_id'] in subjects and subjects[d['subject_id']].get('costume_state') == d['costume_state']}
        if set(panel.get('visual_evidence', {}).get('detail_visibility', {})) != expected:
            errors.append('当前可见人物衣装的批准细节未逐项说明可见性')
        errors.extend(panel_errors(panel, context, prompt=True))
        if panel.get('input_quality_policy'):
            view = context.get('scene_view')
            if view and not detail_carried(view, panel.get('reference_images', [])):
                errors.append('INPUT_QUALITY_HOLD:本机位场景视图/选区未随实际调用携带')
        if panel.get('background_policy') == BACKGROUND_POLICY:
            profile = context['background_profile']
            if not detail_carried(profile, panel.get('reference_images', [])):
                errors.append('BACKGROUND_HOLD:场景色调与空间参考未随实际调用携带')
        for did, row in panel['visual_evidence']['detail_visibility'].items():
            detail = context['details'][did]
            if row['status'] == 'visible' and not detail_carried(detail, panel.get('reference_images', [])):
                errors.append(f'{did}:细节依据未随实际调用携带')
    except (KeyError, TypeError, AttributeError, ValueError): errors.append('质量依据结构或布局归属无效')
    return errors


def detail_carried(detail, references):
    source = detail['reference_sha256']
    if any(r.get('sha256') == source for r in references): return True
    required = detail.get('source_region')
    # An atlas crop of the same source is insufficient unless it covers this detail.
    if not isinstance(required, list) or len(required) != 4: return False
    for ref in references:
        for region in ref.get('source_regions', []):
            crop = region.get('crop_rect_pixels', [])
            if (region.get('source_file', {}).get('sha256') == source and len(crop) == 4
                    and crop[0] <= required[0] < required[2] <= crop[2]
                    and crop[1] <= required[1] < required[3] <= crop[3]): return True
    return False


def write_review_regions(image_path, regions, output):
    """Lossless inspection derivatives; never resize or replace a production image."""
    from PIL import Image
    from codex_reference_contract import digest
    image_path = Path(image_path).resolve(); output = Path(output).resolve()
    with Image.open(image_path) as source:
        source.load(); width, height = source.size
        checked = []
        if not isinstance(regions, list) or not regions: raise ValueError('须提供实际观察区域')
        for i, row in enumerate(regions):
            box = row.get('region')
            if not text(row.get('check_id')) or not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box) or not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
                raise ValueError('区域须为实际原图范围内的整数xyxy')
            checked.append((i, row, box))
        output.mkdir(parents=True, exist_ok=False)
        manifest = {'policy':'original_pixel_inspection_v1', 'source_image':{'path':str(image_path),'sha256':digest(image_path)},
                    'source_size':[width,height], 'status':'UNREVIEWED', 'regions':[]}
        for i, row, box in checked:
            dest = output / f'region_{i+1:03d}.png'
            source.crop(box).save(dest, format='PNG')
            manifest['regions'].append({'check_id':row['check_id'],'region':box,'scale':'original_pixels',
                'image_sha256':manifest['source_image']['sha256'], 'inspection_file':{'path':str(dest),'sha256':digest(dest)}})
        (output/'原尺寸审阅索引.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n', encoding='utf-8', newline='\n')
    return manifest


def review_template(panel):
    if panel.get('visual_evidence_policy') != POLICY: return None
    ev = panel['visual_evidence']
    from appearance_lock import review_template as appearance_review_template
    result = {**appearance_review_template(panel),'policy': POLICY, 'expectations_sha256': fingerprint(ev),
            'context_sha256': fingerprint(panel.get('visual_evidence_context')),
            **({'background_sha256': fingerprint({'policy': panel['background_policy'], 'framing': panel['framing']})}
               if panel.get('background_policy') == BACKGROUND_POLICY else {}),
            'full_image_review': {'status': 'UNREVIEWED', 'evidence': ''},
            **({'background_observation': {
                'mode': panel['framing']['background_treatment'], 'image_sha256': None,
                'observed': '', 'sharpness_observed': '',
                'retained': {r['id']: '' for r in panel['framing']['background_plan']['retain']},
                'omitted': {r['id']: '' for r in panel['framing']['background_plan']['omit']}}}
               if panel.get('background_policy') == BACKGROUND_POLICY else {}),
            'observations': [{**copy.deepcopy(c), 'status': 'UNREVIEWED', 'reviewer': '',
                              'observed': '', 'view': None} for c in ev['checks']],
            'continuity_comparisons': [], 'detail_visibility_observations': {},
            'visibility_observations': {}}
    if panel.get('operation')=='repair' and panel.get('repair_focus',{}).get('structural_change'):
        result['repair_comparison']={'whole_subject_recheck':{'status':'UNREVIEWED','observed':''}}
    return result


def continuity_targets(panel):
    """Nearest scene panel plus selected earlier anchors; no generation dependency."""
    ev=panel.get('visual_evidence',{})
    extra=ev.get('comparison_panel_ids',[])
    ids=[ev.get('previous_panel_id'),*(extra if isinstance(extra,list) else [])]
    return list(dict.fromkeys(pid for pid in ids if text(pid)))


def review_errors(panel, item, *, require_pass=True, image_size=None):
    if panel.get('visual_evidence_policy') is None: return []
    expected = review_template(panel); actual = item.get('visual_evidence_review')
    if not isinstance(actual, dict): return ['缺原图/局部/连续性实际审查记录']
    from appearance_lock import review_errors as appearance_review_errors
    errors = appearance_review_errors(panel,item,require_pass=require_pass)
    verdicts = {'PASS'} if require_pass else {'PASS', 'FAIL'}
    size = list(image_size) if image_size is not None else item.get('image_size')
    if image_size is not None and item.get('image_size') != size:
        errors.append('审查尺寸与实际返回原图不同，不能使用虚构边界验证局部')
    if not isinstance(size, list) or len(size) != 2 or any(type(v) is not int or v <= 0 for v in size):
        return errors + ['缺实际原图尺寸，无法核对原尺寸区域']
    for key in ('policy', 'expectations_sha256', 'context_sha256', *(['background_sha256'] if panel.get('background_policy') else [])):
        if actual.get(key) != expected[key]: errors.append('质量审查判据或基准版本已改变')
    if panel.get('background_policy') == BACKGROUND_POLICY:
        observed = actual.get('background_observation')
        plan = panel['framing']['background_plan']
        if (not isinstance(observed, dict) or
                observed.get('mode') != panel['framing']['background_treatment'] or
                observed.get('image_sha256') != item.get('image_sha256') or
                not text(observed.get('observed')) or not text(observed.get('sharpness_observed'))):
            errors.append('BACKGROUND_HOLD:缺当前图的背景模式及主体清晰度实际观察')
        else:
            for key in ('retained', 'omitted'):
                rows = observed.get(key)
                original = plan['retain' if key == 'retained' else 'omit']
                if (not isinstance(rows, dict) or set(rows) != {r['id'] for r in original} or
                        any(not text(v) for v in rows.values())):
                    errors.append('BACKGROUND_HOLD:保留/省略项实际观察缺项')
    full = actual.get('full_image_review', {})
    if full.get('status') not in verdicts or not text(full.get('evidence')): errors.append('尚未完成实际全图检查')
    observations = actual.get('observations', [])
    if not isinstance(observations, list) or [c.get('id') for c in observations] != [c['id'] for c in expected['observations']]:
        return errors + ['具体观察缺项、重复或乱序']
    for original, row in zip(expected['observations'], observations):
        if any(row.get(k) != v for k, v in original.items() if k not in {'status', 'reviewer', 'observed', 'view'}):
            errors.append('不得事后改写本格质量判据')
        view = row.get('view')
        if row.get('status') not in verdicts or not text(row.get('reviewer')) or not text(row.get('observed')):
            errors.append(f"{row['id']}:缺具体实际观察或未通过")
        if not isinstance(view, dict) or view.get('image_sha256') != item.get('image_sha256'):
            errors.append(f"{row['id']}:观察未绑定实际图片")
        elif row.get('kind') in {'hand', 'accessory', 'contact', 'clarity'}:
            box = view.get('region')
            if view.get('scale') != 'original_pixels' or not isinstance(box, list) or len(box) != 4 or any(
                    type(n) is not int for n in box) or not (0 <= box[0] < box[2] <= size[0] and 0 <= box[1] < box[3] <= size[1]):
                errors.append(f"{row['id']}:细节须在原尺寸有效区域实际检查")
            if 'inspection_targets' in original:
                covered=view.get('covered_targets')
                if (not isinstance(covered,list) or any(not text(t) for t in covered) or len(covered)!=len(set(covered))
                        or set(covered)!=set(original['inspection_targets'])):
                    errors.append(f"{row['id']}:原尺寸观察未覆盖已冻结的所属肢体/接触对象/清晰度目标")
            if view.get('resampled') is True or ('source_size' in view and view['source_size'] != size):
                errors.append(f"{row['id']}:放大或重采样审阅不能冒充原生细节观察")
    ev = panel['visual_evidence']
    for name, plan in (('visibility_observations', ev['visibility']), ('detail_visibility_observations', ev['detail_visibility'])):
        rows = actual.get(name, {})
        if not isinstance(rows, dict) or set(rows) != set(plan): errors.append(name + ':可见性观察缺项'); continue
        for entity, result in rows.items():
            if (not isinstance(result, dict) or result.get('status') not in verdicts or
                    result.get('actual_visibility') not in VISIBILITY or
                    result.get('status') == 'PASS' and result.get('actual_visibility') != plan[entity]['status'] or
                    not text(result.get('observed'))):
                errors.append(entity + ':实际可见性与计划不符或未检查')
    comparisons = actual.get('continuity_comparisons', [])
    for prior in continuity_targets(panel):
        if require_pass and (not isinstance(comparisons, list) or not any(
                isinstance(c, dict) and c.get('panel_id') == prior and c.get('status') == 'PASS'
                and isinstance(c.get('image'), dict) and text(c['image'].get('path')) and text(c['image'].get('sha256'))
                and text(c.get('observed')) for c in comparisons)):
            errors.append(f'{prior}:缺同场景真实前序图连续性比较；独立生图不必等待，但验收须补齐')
    if panel.get('operation') == 'repair':
        repair = actual.get('repair_comparison', {})
        source = panel.get('repair_source', {})
        if (repair.get('base_image_sha256') != source.get('image_sha256') or
                repair.get('clarity_status') not in verdicts or not text(repair.get('observed')) or
                repair.get('preserved_features') != source.get('preserved_features')):
            errors.append('返修缺与所选清晰底图的细节/已完成修正保留比较')
        if panel.get('repair_focus',{}).get('structural_change'):
            whole=repair.get('whole_subject_recheck',{})
            if whole.get('status') not in verdicts or not text(whole.get('observed')):
                errors.append('结构返修须重数全人物肢体并核对旧结构移除、归属连接和承托；局部正确不能放行')
        regions=source.get('preservation_regions')
        if regions is not None:
            observed=repair.get('preserved_observations')
            if (not isinstance(observed,dict) or set(observed)!=set(regions)
                    or any(not isinstance(o,dict) or o.get('status') not in verdicts
                           or not text(o.get('observed')) for o in observed.values())):
                errors.append('返修未逐项核对明确保留区域，不能仅以修复处正确放行')
    return errors


def repair_source_errors(panel):
    if panel.get('visual_evidence_policy') != POLICY: return []
    source = panel.get('repair_source')
    if not isinstance(source, dict): return ['返修缺所选底图及保留依据']
    errors = []
    if any(not text(source.get(k)) for k in ('image_sha256', 'source_attempt_id', 'selection_reason')):
        errors.append('返修底图缺真实哈希、来源尝试或选择理由')
    if 'preservation_regions' in source:
        regions=source['preservation_regions']
        if (not isinstance(regions,dict) or not regions or any(not text(k) or not isinstance(b,list)
                or len(b)!=4 or any(type(n) is not int for n in b)
                or not (0<=b[0]<b[2] and 0<=b[1]<b[3]) for k,b in regions.items())):
            errors.append('返修保留区域须为具名的有效原图整数框')
    features = source.get('preserved_features')
    if not isinstance(features, list) or not features or any(not text(v) for v in features):
        errors.append('返修须明确保留特征及此前有效修正')
    elif any(v not in panel.get('prompt', '') for v in features):
        errors.append('实际返修提示词未携带全部保留特征/有效修正')
    if panel.get('repair_method') == 'regenerate':
        if panel.get('production_policy') != 'first_batch_production_v1':
            errors.append('重生须来自新生产合同，不向旧运行添加后门')
        if any(r.get('sha256') == source.get('image_sha256') for r in panel.get('reference_images', [])):
            errors.append('重生不携带错误图，使用批准参考；底图仅留比较证据')
        return errors
    matching = [r for r in panel.get('reference_images', []) if r.get('sha256') == source.get('image_sha256')]
    if not matching:
        errors.append('所选返修底图未实际携带；审阅截图不能冒充原始返回底图')
    targets = [r for r in matching if r.get('role') in {'repair_target', 'edit_target', 'failed_image'} or
               'REPAIR_TARGET' in str(r.get('alias', '')).upper()]
    aliases = {r.get('alias') for r in targets}
    if not targets:
        errors.append('返修原图须明确标为编辑目标，不能绕过repair_focus冲突检查')
    bindings = [b for b in panel.get('reference_bindings', []) if b.get('alias') in aliases]
    if not bindings or any(b.get('purpose') not in {'pose_interaction', 'scene_view', 'framing', 'spatial_layout', 'prop_state'} for b in bindings):
        errors.append('返修底图只可作编辑/空间/动作/道具参考，不得升为身份衣装或画风依据')
    return errors


def repair_binding_errors(panel, record):
    if panel.get('visual_evidence_policy') != POLICY or panel.get('operation') != 'repair': return []
    source = panel.get('repair_source', {})
    candidates = [record, *record.get('attempt_history', [])]
    if not any(c.get('attempt_id') == source.get('source_attempt_id') and
               c.get('output', {}).get('sha256') == source.get('image_sha256') for c in candidates):
        return ['返修底图不属于本格已记录的真实返回尝试；不得使用截图或别格图']
    return []


def repair_basis(state, root, panel, basis, records):
    """Extend the execution reference allowlist only with this panel's real target."""
    if state is None or state.get('visual_evidence_policy') != POLICY or panel.get('operation') != 'repair':
        return basis
    from codex_reference_contract import checked_file
    record = records.get(panel.get('panel_id'), {})
    errors = repair_source_errors(panel) + repair_binding_errors(panel, record)
    if errors: raise ValueError(';'.join(errors))
    source = panel['repair_source']
    match = next(c for c in [record, *record.get('attempt_history', [])]
                 if c.get('attempt_id') == source['source_attempt_id'] and
                 c.get('output', {}).get('sha256') == source['image_sha256'])
    original=checked_file(Path(root), match['output'])
    if source.get('preservation_regions'):
        from PIL import Image
        from reference_atlas import rect
        with Image.open(original) as im:
            for box in source['preservation_regions'].values():rect(box,im.size)
    return {**basis, 'reference_files': [*basis['reference_files'], match['output']]}


def repair_binding_extension_valid(panel, shot):
    """Structural append-only exception; the state gate verifies the real return."""
    if (panel.get('visual_evidence_policy') != POLICY or shot.get('visual_evidence_policy') != POLICY
            or panel.get('operation') != 'repair'):
        return False
    from repair_input_guard import repair_errors
    if repair_errors(panel): return False
    old = shot.get('reference_bindings', []); current = panel.get('reference_bindings', [])
    if current[:len(old)] != old or len(current) <= len(old): return False
    source = panel['repair_source']['image_sha256']
    aliases = {r.get('alias') for r in panel.get('reference_images', []) if r.get('sha256') == source
               and (r.get('role') in {'repair_target', 'edit_target', 'failed_image'} or
                    'REPAIR_TARGET' in str(r.get('alias', '')).upper())}
    return all(b.get('alias') in aliases and b.get('purpose') in
               {'pose_interaction', 'scene_view', 'framing', 'spatial_layout', 'prop_state'} for b in current[len(old):])


def comparison_errors(panel, item, records, root):
    """Bind visual comparisons to the latest actual episode records, not labels."""
    if panel.get('visual_evidence_policy') != POLICY: return []
    from codex_reference_contract import checked_file
    errors = []
    rows = item.get('visual_evidence_review', {}).get('continuity_comparisons', [])
    if not isinstance(rows,list):return ['连续性比较须为实际图片记录清单']
    for prior in continuity_targets(panel):
        current = records.get(prior, {}).get('output')
        if not current:
            errors.append(f'{prior}:同场景前序真实图尚未返回；本格可独立生成，连续性暂未验收'); continue
        comparisons = [c for c in rows if isinstance(c, dict) and c.get('panel_id') == prior]
        if len(comparisons) != 1 or comparisons[0].get('image') != current:
            errors.append(f'{prior}:同场景比较未绑定当前实际前序图版本；换版须重新比较'); continue
        try: checked_file(Path(root), current)
        except (OSError, ValueError, TypeError): errors.append('连续性比较原图缺失或哈希变化')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--basis')
    parser.add_argument('--panel')
    parser.add_argument('--review-image', help='真实原图，生成仅供审阅的原尺寸局部')
    parser.add_argument('--regions', help='JSON清单，每项check_id和整数region=[x0,y0,x1,y1]')
    parser.add_argument('--output', help='必须不存在的新审阅目录')
    args = parser.parse_args()
    if args.review_image:
        if not args.regions or not args.output or args.basis or args.panel: parser.error('审阅模式须仅指定review-image、regions、output')
        print(json.dumps(write_review_regions(args.review_image,json.loads(Path(args.regions).read_text(encoding='utf-8-sig')),args.output),ensure_ascii=False,indent=2))
        return 0
    if not args.basis or not args.panel: parser.error('编译模式须提供basis和panel')
    basis = json.loads(Path(args.basis).read_text(encoding='utf-8-sig'))
    panel = json.loads(Path(args.panel).read_text(encoding='utf-8-sig'))
    context = context_for(basis, panel)
    errors = basis_errors(basis) + panel_errors(panel, context)
    print(json.dumps({'status': 'HOLD' if errors else 'CANDIDATE_BLOCK_NOT_APPROVAL', 'errors': errors,
                     'visual_evidence_context': context,
                     'visual_execution_block': None if errors else execution_block(panel, context)}, ensure_ascii=False, indent=2))
    return bool(errors)


if __name__ == '__main__':
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
