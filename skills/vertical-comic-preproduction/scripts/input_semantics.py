"""Content-bound review of final inputs. No inference of human approval or image QA.

The checker proves coverage and detects a small set of explicit contradictions;
the reviewer must still read the final prompt and actual references. Legacy
frozen states without this capability keep their original contract.
"""
from __future__ import annotations
from codex_reference_contract import resolve_path

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

from codex_reference_contract import checked_file, digest, read_json, validate_panel

POLICY = 'final_input_semantics_v1'
PREPARED_POLICY = 'final_input_semantics_v2'
POLICIES = {POLICY, PREPARED_POLICY}
PREPARED_CHECKS = ('continuity_and_dependencies', 'rule_execution_coverage', 'appearance_anchors')
CHECKS = ('source_and_expression', 'crop_and_required_information',
          'per_subject_visibility', 'action_and_space', 'actual_references',
          'all_execution_text_and_criteria')
VALUES = {'eyes': {'wide', 'narrow', 'half_closed', 'closed'},
          'mouth': {'parted', 'closed'}, 'focus': {'focused', 'unfocused'},
          'face': {'visible', 'hidden'}}
PATTERNS = {
    ('eyes', 'wide'): r'睁大|睁得很大|骤然睁大|眼睑抬起',
    ('eyes', 'narrow'): r'眼(?:睑|皮)略收|上眼睑略收',
    ('eyes', 'half_closed'): r'眼(?:皮|睑)半耷|眼皮沉|半闭',
    ('eyes', 'closed'): r'闭上双眼|双眼闭合',
    ('mouth', 'parted'): r'嘴唇微张|双唇微张|嘴微张',
    ('mouth', 'closed'): r'自然闭合|双唇闭合|嘴唇闭合|闭嘴',
    ('focus', 'focused'): r'专注|目光聚焦|视线聚焦|瞳孔朝向作用对象',
    ('focus', 'unfocused'): r'失焦|无法聚焦|视线涣散',
}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def enabled(state):
    policy = state.get('input_semantics_policy')
    if policy is not None and policy not in POLICIES:
        raise ValueError('INPUT_SEMANTICS_HOLD:未知最终输入审查策略')
    return policy in POLICIES


def _content(value):
    """Hash references by content, not a receiver's root; preserve other fields."""
    if isinstance(value, list):
        return [_content(v) for v in value]
    if isinstance(value, dict):
        return {k: _content(v) for k, v in value.items()
                if not (k == 'path' and 'sha256' in value)}
    return value


def _asserted(text):
    # Narrow positive clauses only. Negation, quoted history and other instants
    # are left to human review, never interpreted as positive requirements.
    for clause in re.split(r'[。；;\n]', text):
        if re.search(r'禁止|不得|不要|不能|避免|并非|不是|不要求|不应|不表现|不再|去掉|删除|上一格|前一格|此前|原先|之后|随后', clause):
            continue
        yield clause


def scoped_input_signals(panel, prompt, context=None):
    """Narrow review hints from final input; not verdicts or an extra model pass."""
    signals = []
    checks = (panel.get('visual_evidence') or {}).get('checks', [])
    hand_checks = [c for c in checks if isinstance(c, dict) and c.get('actor_limb') in {'left_hand','right_hand','both_hands'}]
    for line in prompt.splitlines():
        if not any(mark in line for mark in ('世界固定依据：','场景仅选参考','_STATE：')):
            continue
        for clause in _asserted(line):
            if re.search(r'(?:窗台|桌面|台面|床沿)承托双手', clause) and hand_checks:
                signals.append({'kind':'scene_action_leak', 'source_text':clause.strip(),
                    'related_actions':[{k:c.get(k) for k in ('actor','actor_limb','target','target_part','visible_path')} for c in hand_checks],
                    'question':'场景固定描述是否错误分配双手？仅核对当前人物任务，不从关键词直接判冲突。'})
    details = (context or panel.get('visual_evidence_context') or {}).get('details', {})
    for ident,d in details.items():
        if not isinstance(d,dict): continue
        attachment = (d.get('placement') or {}).get('attachment','')
        expected = d.get('expected','')
        if ('领口、肩袖与身体连续连接' in attachment and
                (d.get('subject_kind') == 'animal' or re.search(r'鳞|皮毛|羽毛|爪', expected))):
            signals.append({'kind':'subject_template_mismatch','detail_id':ident,
                'source_text':attachment,'expected':expected,
                'question':'核对批准主体是否实际穿衣；自然体表不能套用人类领口肩袖模板。'})
    # Location prose inside appearance projections is only a review hint.
    # Do not infer a semantic contradiction or strip author text with a regex.
    ev = panel.get('visual_evidence') or {}
    for ident, row in (ev.get('detail_visibility') or {}).items():
        if not isinstance(row, dict): continue
        projection = row.get('projection') or {}
        if not isinstance(projection, dict): continue
        position = projection.get('screen_position', '')
        if isinstance(position, str) and re.search(r'门外|门内|楼梯|楼道|走廊|退路|站在|坐在|躺在|前往|到达', position):
            signals.append({'kind':'appearance_location_leak', 'detail_id':ident,
                'source_text':position, 'current_blocking':ev.get('blocking', {}),
                'question':'核对细节投影是否夹带旧人物站位；世界位置以当前镜头为准，允许必要的环境遮挡描述。'})
    for line in prompt.splitlines():
        for clause in _asserted(line):
            match = re.search(r'本(?:镜头|细节投影)位置[=:：]([^；。\n]+)', clause)
            if match and re.search(r'门外|门内|楼梯|楼道|走廊|退路|站在|坐在|躺在|前往|到达', match.group(1)):
                position = match.group(1).strip()
                if not any(s.get('kind') == 'appearance_location_leak' and s.get('source_text') == position for s in signals):
                    signals.append({'kind':'appearance_location_leak', 'source_text':position,
                        'current_blocking':ev.get('blocking', {}),
                        'question':'实际配饰执行段是否夹带另一瞬间/旧镜头的人物站位？与当前镜头对照，不能直接由关键词判FAIL。'})
    return signals


def conflict_errors(shot, prompt, *, detail_warnings=None):
    """Only facts with explicit subject/instant attribution can auto-block."""
    from spatial_contract import selection_errors, projection_errors
    errors = selection_errors(shot) + projection_errors(shot)
    details = errors if detail_warnings is None else detail_warnings
    facts = shot.get('semantic_facts', [])
    if not isinstance(facts, list):
        return ['INPUT_CONFLICT:semantic_facts须为列表']
    seen = {}
    source_text = json.dumps(shot.get('locked_script', {}), ensure_ascii=False)
    for fact in facts:
        if not isinstance(fact, dict):
            errors.append('INPUT_CONFLICT:事实须为对象'); continue
        subject, name = fact.get('subject_id'), fact.get('subject_name')
        attr, value = fact.get('attribute'), fact.get('value')
        quote = fact.get('source_quote')
        if (not subject or not name or fact.get('instant') != 'current'
                or attr not in VALUES or value not in VALUES.get(attr, set())
                or not isinstance(quote, str) or not quote or quote not in source_text):
            errors.append('INPUT_CONFLICT:事实须绑定人物、当前瞬间、合法状态及准确源句'); continue
        key = (subject, attr)
        if key in seen and seen[key] != value:
            errors.append(f'INPUT_CONFLICT:{subject}:{attr}:同一瞬间互斥状态')
        seen[key] = value
        for clause in _asserted(quote):
            if any(field == attr and alternative != value and re.search(pattern, clause)
                   for (field, alternative), pattern in PATTERNS.items()):
                errors.append(f'INPUT_CONFLICT:{subject}:{attr}:结构化状态与引用源句相反')
        for line in prompt.splitlines():
            # Do not infer ownership across people or paragraphs. Ambiguous
            # multi-person lines are still mandatory manual review targets.
            if name not in line or any(f.get('subject_name') != name and
                    f.get('subject_name') and f['subject_name'] in line for f in facts if isinstance(f, dict)):
                continue
            for clause in _asserted(line):
                for (field, alternative), pattern in PATTERNS.items():
                    if field == attr and alternative != value and re.search(pattern, clause):
                        details.append(f'INPUT_CONFLICT:{subject}:{attr}:{value}与最终文字“{clause.strip()}”冲突')
    framing = shot.get('framing') or {}
    required = '；'.join(map(str, framing.get('required_visible', [])))
    crop = framing.get('body_crop')
    if crop in {'chest_up', 'shoulders_up', 'face_detail'} and (
            re.search(r'腰部以上|腰以上|腰部入画', required) or
            re.search(r'(?:自然)?(?:垂|下垂).*(?:完整|指尖)|完整.*(?:垂|下垂)', required)):
        errors.append('INPUT_CONFLICT:批准裁切无法容纳腰部/自然下垂完整手势，须修镜头')
    regions = shot.get('subject_visibility', {})
    if not isinstance(regions, dict):
        return errors + ['INPUT_CONFLICT:subject_visibility须为逐人物对象']
    for subject, row in regions.items():
        if not isinstance(row, dict) or not isinstance(row.get('face_visible'), bool) or not row.get('evidence'):
            errors.append(f'INPUT_CONFLICT:{subject}:缺面部可见性及依据'); continue
        if row['face_visible']:
            continue
        if (shot.get('adjacent_face_comparison', {}).get(subject, {}) or {}).get('face_comparable') is True:
            details.append(f'INPUT_CONFLICT:{subject}:脸不可见却声明面部可比较')
        name = row.get('subject_name')
        if name:
            for line in prompt.splitlines():
                if name not in line:
                    continue
                if any(other != subject and item.get('subject_name') and item['subject_name'] in line
                       for other, item in regions.items() if isinstance(item, dict)):
                    continue
                if any(re.search(r'瞳孔|嘴唇|双唇|眼睑|眉形', c) for c in _asserted(line)):
                    details.append(f'INPUT_CONFLICT:{subject}:不可见面部仍有五官绘制指令')
    return list(dict.fromkeys(errors))


def _basis(state, root, shot):
    source = read_json(checked_file(root, state['source_snapshot']))
    if source['locked_scripts'][shot['panel_id']] != shot.get('locked_script'):
        raise ValueError('INPUT_SEMANTICS_HOLD:镜头与源文字不同')
    if not isinstance(shot.get('semantic_facts'), list) or not isinstance(shot.get('subject_visibility'), dict):
        raise ValueError('INPUT_SEMANTICS_HOLD:新镜头须明确semantic_facts与subject_visibility；确无项目用空列表/对象')
    for binding in shot.get('character_bindings', []):
        if not binding.get('on_screen'): continue
        subject = binding.get('character_id')
        row = shot['subject_visibility'].get(subject, {})
        if (not subject or not isinstance(row.get('face_visible'), bool)
                or not isinstance(row.get('identity_observable'), bool) or not row.get('subject_name') or not row.get('evidence')):
            raise ValueError(f'INPUT_SEMANTICS_HOLD:{subject}:缺逐人物面部/身份可观察性及依据')
    basis = checked_file(root, state['visual_basis'])
    from panel_readiness import design_signature
    memory = state.get('memory_source') or {}
    rule_hash = digest(Path(memory['root']) / memory.get('index', '记忆索引.json')) if memory.get('root') else None
    toolchain = state.get('toolchain') or {}
    if state.get('runtime_import'):
        from runtime_import import verify_binding
        _,original=verify_binding(state,root)
        if all(state.get(k)==original.get(k) for k in ('source_snapshot','visual_basis','shot_manifest','semantic_audit')):
            toolchain=original.get('toolchain') or {}
    from preparation_gate_policy import enabled as light_preparation, FIELD
    return {**({FIELD: state[FIELD]} if light_preparation(state) else {}),
            'book_id': state['book_id'], 'episode_id': state['episode_id'],
            'panel_id': shot['panel_id'], 'source': source['locked_scripts'][shot['panel_id']],
            'shot_signature': design_signature(shot), 'visual_basis_sha256': digest(basis),
            'rule_index_sha256': rule_hash, 'tool_files': toolchain.get('files', []),
            'skill_entries': [r.get('sha256') for r in toolchain.get('skill_entries', [])]}


def actual_input(state, root, shot, packet, package_root):
    from audit_cache import derived, content_key
    authority = {k: state.get(k) for k in ('book_id', 'episode_id', 'source_snapshot',
                 'visual_basis', 'shot_manifest', 'toolchain', 'memory_source', 'input_semantics_policy', 'preparation_gate_policy','runtime_import')}
    from panel_readiness import review_scope
    return derived('final_semantic_input', content_key([str(root), str(package_root), authority, shot, packet, review_scope()]),
                   lambda: _actual_input(state, root, shot, packet, package_root))


def _actual_input(state, root, shot, packet, package_root):
    # validate_panel reads prompt.txt directly; register it in the transaction's
    # dependency set as well so a warm result cannot hide a later edit.
    panel = packet['panels'][0]
    digest(Path(package_root) / panel.get('prompt_file', panel['panel_id'] + '/prompt.txt'))
    problems, submission = validate_panel(packet['panels'][0], Path(package_root))
    if problems or submission is None:
        raise ValueError(';'.join(problems) or '缺最终实际请求')
    panel = packet['panels'][0]
    if panel.get('panel_id') != shot['panel_id']:
        raise ValueError('INPUT_SEMANTICS_HOLD:实际请求格号失配')
    args = submission['arguments']
    references = []
    for ref, path in zip(panel['reference_images'], args['referenced_image_paths']):
        references.append({**_content(ref), 'sha256': digest(Path(path))})
    return {**_basis(state, Path(root), shot),
            **preparation_basis(state, root, shot, panel, args['prompt']), 'prompt': args['prompt'],
            'transparent_background': args['transparent_background'],
            'output_spec': panel.get('output_spec'), 'references': references,
            'execution_metadata': _content({k: panel.get(k) for k in (
                'character_bindings', 'reference_bindings', 'framing', 'visible_region',
                'visual_evidence', 'visual_evidence_context', 'continuity_contract',
                'adjacent_face_comparison', 'semantic_facts', 'subject_visibility',
                'memory_applications', 'rule_exceptions', 'repair_source')},
                **({'coordinate_edit': panel['repair_focus']['coordinate_edit']}
                   if isinstance(panel.get('repair_focus'), dict) and panel['repair_focus'].get('coordinate_edit') is not None else {}))}


def planned_input(state, root, shot, plan_row):
    args = plan_row.get('arguments', {})
    refs = plan_row.get('reference_files', [])
    paths = args.get('referenced_image_paths', [])
    if (plan_row.get('panel_id') != shot['panel_id'] or not isinstance(args.get('prompt'), str)
            or not args['prompt'].strip() or len(refs) != len(paths) or not 1 <= len(refs) <= 5
            or not plan_row.get('reference_bindings') or plan_row.get('reference_path_basis') != 'run_root'):
        raise ValueError('INPUT_SEMANTICS_HOLD:依赖模板缺真实prompt/参考用途/准确槽位')
    found, references = [], []
    for path, ref in zip(paths, refs):
        if ref.get('path') != path:
            raise ValueError('INPUT_SEMANTICS_HOLD:依赖参考顺序失配')
        if path.startswith('@DEPENDENCY:'):
            found.append(path.split(':', 1)[1]); references.append({'dependency': found[-1]})
        else:
            fixed = checked_file(Path(root), ref)
            from PIL import Image
            from codex_reference_contract import physical_file
            with Image.open(physical_file(fixed)) as image: image.verify()
            references.append(_content(ref))
    if sorted(found) != sorted(shot.get('generation_dependencies', [])) or len(found) != len(set(found)):
        raise ValueError('INPUT_SEMANTICS_HOLD:依赖槽与真实前置不符')
    return {**_basis(state, Path(root), shot),
            **preparation_basis(state, root, shot, {**shot, 'memory_applications': plan_row.get('memory_applications', shot.get('memory_applications', {}))}, args['prompt']), 'prompt': args['prompt'],
            'transparent_background': args.get('transparent_background'),
            'output_spec': plan_row.get('output_spec'), 'references': references,
            'reference_bindings': plan_row['reference_bindings'], 'dependency_plan': True}


def review_checks(policy):
    return CHECKS + (PREPARED_CHECKS if policy == PREPARED_POLICY else ())


def preparation_basis(state, root, shot, panel, prompt):
    """Read existing authorities once; expose concrete review targets, not new approvals."""
    if state.get('input_semantics_policy') != PREPARED_POLICY:
        return {}
    from visual_evidence import context_for, continuity_targets, execution_block
    basis = read_json(checked_file(Path(root), state['visual_basis']))
    context = context_for(basis, shot) if shot.get('visual_evidence_policy') else {}
    contract = shot.get('continuity_contract') or {}
    deps = shot.get('generation_dependencies', [])
    reasons = contract.get('generation_dependency_reasons', {})
    if (not isinstance(deps, list) or any(not isinstance(d, str) or not d.strip() for d in deps)
            or len(deps) != len(set(deps)) or shot.get('panel_id') in deps
            or not isinstance(reasons, dict) or set(reasons) != set(deps)
            or any(not isinstance(v, str) or not v.strip() for v in reasons.values())):
        raise ValueError('INPUT_SEMANTICS_HOLD:真实实图依赖须逐项说明用途与等待原因；比较关系不自动成为生图依赖')
    if panel.get('generation_dependencies', []) != deps or panel.get('continuity_contract') != shot.get('continuity_contract'):
        raise ValueError('INPUT_SEMANTICS_HOLD:实际包连续性或实图依赖与镜头不同')
    if shot.get('visual_evidence_policy'):
        # Includes invisible accessory constraints; planned inputs need them too.
        block = execution_block({**shot, 'visual_evidence_context': context}, context)
        if block not in prompt:
            raise ValueError('INPUT_SEMANTICS_HOLD:最终输入缺已准备的可见关系/服饰约束')
    from rule_memory import select, execution_constraints
    from continuity_context import rule_tags
    source = state.get('memory_source')
    # Contextual tags belong to the whole manifest, including cross-episode context.
    manifest_path = checked_file(Path(root), state['shot_manifest'])
    manifest = read_json(manifest_path)
    tags = rule_tags(manifest, manifest_path.parent, shot) if source else []
    rules = {}
    for stage in ('shot_design', 'generation', 'image_review'):
        rows = []
        for match in select(source, stage, panel, tags):
            rule = match['rule']; checked_file(Path(source['root']), rule['file'])
            apps = (panel.get('memory_applications') or {}).get(stage, [])
            app = next((a for a in apps if a.get('memory_id') == rule['id']), {})
            constraints = app.get('prompt_constraints', []) if stage == 'generation' else []
            if stage == 'generation' and (app.get('decision') not in {'APPLIED', 'NOT_APPLICABLE'}
                    or app.get('rule_signature') != match['rule_signature']
                    or app.get('decision') == 'NOT_APPLICABLE' and (match['matched_tags'] or not app.get('reason'))):
                raise ValueError('INPUT_SEMANTICS_HOLD:'+rule['id']+':缺准确规则执行或排除依据')
            if stage == 'generation' and rule['requirements'][stage]['prompt_constraints'] and app.get('decision') != 'NOT_APPLICABLE':
                if not constraints or any(not isinstance(x, str) or not x.strip() or x not in prompt for x in constraints):
                    raise ValueError('INPUT_SEMANTICS_HOLD:'+rule['id']+':本格规则约束未落实到最终prompt')
            rows.append({'memory_id':rule['id'], 'rule_signature':match['rule_signature'],
                         'matched_tags':match['matched_tags'], 'matched_terms':match['matched_terms'],
                         'checks':rule['requirements'][stage]['checks'],
                         'decision':app.get('decision'), 'evidence':app.get('evidence'),
                         'prompt_constraints':constraints})
        rules[stage] = rows
    if any(line not in prompt for line in execution_constraints(panel)):
        raise ValueError('INPUT_SEMANTICS_HOLD:已收敛的规则约束未全部进入实际输入')
    targets = {
        'continuity_and_dependencies': {'design':contract, 'generation_dependencies':deps,
            'comparison_panel_ids':continuity_targets(shot) if shot.get('visual_evidence_policy') else []},
        'rule_execution_coverage': rules,
        'appearance_anchors': {'details':context.get('details', {}),
            'visibility':(shot.get('visual_evidence') or {}).get('detail_visibility', {}),
            'checks': [c for c in (shot.get('visual_evidence') or {}).get('checks', []) if c.get('kind') == 'accessory']}}
    from preparation_gate_policy import enabled as light_preparation
    detail_signals = []
    if light_preparation(state): conflict_errors(shot, prompt, detail_warnings=detail_signals)
    signals = scoped_input_signals(panel, prompt, context)
    if detail_signals: targets['detail_warnings'] = detail_signals
    if signals:
        targets['all_execution_text_and_criteria'] = {'scoped_conflict_signals': signals,
            'instruction': '仅核对这些疑点与相关原输入；在本项evidence说明修正或不构成冲突的依据，不另开审查轮次。'}
    return {'input_semantics_policy': PREPARED_POLICY, 'preparation_targets':copy.deepcopy(targets)}


def review_template(inputs):
    from preparation_gate_policy import FIELD, POLICY as LIGHT, template
    if inputs.get(FIELD) == LIGHT: return template(inputs)
    policy = inputs.get('input_semantics_policy', POLICY)
    return {'policy': policy, 'status': 'UNREVIEWED', 'reviewer': '', 'evidence': '',
            'input_digest': fingerprint(inputs), 'checks': {
                key: {'status': 'UNREVIEWED', 'evidence': '',
                      **({'expected': copy.deepcopy(inputs['preparation_targets'][key])}
                         if key in inputs.get('preparation_targets', {}) else {})}
                for key in review_checks(policy)}}


def review_errors(review, inputs):
    from preparation_gate_policy import FIELD, POLICY as LIGHT, review_errors as quick_errors
    if inputs.get(FIELD) == LIGHT: return quick_errors(review, inputs)
    if not isinstance(review, dict):
        return ['INPUT_SEMANTICS_HOLD:缺最终输入逐格审查']
    policy = inputs.get('input_semantics_policy', POLICY)
    if review.get('policy') != policy or review.get('input_digest') != fingerprint(inputs):
        return ['INPUT_SEMANTICS_HOLD:最终输入已变化或审查版本失配']
    if (review.get('status') != 'REVIEWED' or not review.get('reviewer')
            or not review.get('evidence') or review.get('unresolved_issues', [])):
        return ['INPUT_SEMANTICS_HOLD:最终输入未实审或存在未解决项']
    return ['INPUT_SEMANTICS_HOLD:' + key + ':缺具体审查依据' for key in review_checks(policy)
            if (key in inputs.get('preparation_targets', {}) and
                review.get('checks', {}).get(key, {}).get('expected') != inputs['preparation_targets'][key])
            or review.get('checks', {}).get(key, {}).get('status') != 'PASS'
            or not review.get('checks', {}).get(key, {}).get('evidence')]


def _audit_row(state, root, pid):
    audit = read_json(checked_file(Path(root), state['semantic_audit']))
    source = read_json(checked_file(Path(root), state['source_snapshot']))
    expected = {k: state[k] for k in ('book_id', 'episode_id', 'source_snapshot', 'visual_basis', 'shot_manifest')}
    if (audit.get('policy') != 'semantic_audit_v1' or any(audit.get(k) != v for k, v in expected.items())
            or audit.get('panel_ids') != source['panel_ids']
            or [r.get('panel_id') for r in audit.get('panels', [])] != source['panel_ids']):
        raise ValueError('INPUT_SEMANTICS_HOLD:全话审查归属/范围失配')
    from preparation_gate_policy import FIELD
    if audit.get(FIELD) != state.get(FIELD): raise ValueError('前期审查策略与运行模板不同')
    return next(r for r in audit['panels'] if r['panel_id'] == pid)


def panel_errors(state, root, shot, packet=None, package_root=None, *, plan_row=None):
    try:
        if not enabled(state):
            return []
        from preparation_gate_policy import enabled as light_preparation
        def conflicts(prompt):
            return conflict_errors(shot, prompt, detail_warnings=[] if light_preparation(state) else None)
        inputs = planned_input(state, root, shot, plan_row) if plan_row is not None else actual_input(state, root, shot, packet, package_root)
        row = _audit_row(state, root, shot['panel_id'])
        review = row.get('execution_review')
        # After real dependency insertion, both the static plan's approval and
        # a review of the resulting real reference array are required. Existing
        # dependency_plan_matches still verifies allowed substitutions.
        if plan_row is None and shot.get('generation_dependencies'):
            plan = dependency_rows(state, root).get(shot['panel_id'])
            if plan is None:
                return ['INPUT_SEMANTICS_HOLD:缺批准依赖模板']
            static = planned_input(state, root, shot, plan)
            static_errors = review_errors(review, static) + conflicts(static['prompt'])
            if static_errors: return static_errors
            review = row.get('dependency_completion_review')
        return conflicts(inputs['prompt']) + review_errors(review, inputs)
    except (OSError, ValueError, TypeError, KeyError, IndexError, StopIteration, AttributeError) as exc:
        return ['INPUT_SEMANTICS_HOLD:' + str(exc)]


def dependency_rows(state, root, dependency_plan=None):
    refs = [dependency_plan] if dependency_plan else []
    if not refs:
        for ref in state.get('generation_packages', {}).get('EPISODE', []):
            bundle = read_json(checked_file(Path(root), ref))
            if (bundle.get('book_id') == state['book_id'] and bundle.get('episode_id') == state['episode_id']
                    and bundle.get('shot_manifest') == state['shot_manifest'] and bundle.get('dependency_completion_plan')):
                refs.append(bundle['dependency_completion_plan'])
    rows = {}
    for ref in refs:
        plan = read_json(checked_file(Path(root), ref))
        if (plan.get('policy') != 'dependency_completion_plan_v1' or plan.get('scope') != 'episode'
                or any(plan.get(k) != state.get(k) for k in ('book_id', 'episode_id', 'visual_basis', 'shot_manifest'))):
            raise ValueError('INPUT_SEMANTICS_HOLD:补齐方案归属失配')
        seen = set()
        for row in plan['inputs']:
            pid = row['panel_id']
            if pid in seen or pid in rows and rows[pid] != row:
                raise ValueError('INPUT_SEMANTICS_HOLD:依赖模板重复或多个版本冲突')
            seen.add(pid); rows[pid] = row
    return rows


def coverage(state, root, dependency_plan=None, *, panel_ids=None):
    if not enabled(state):
        return {'policy': None, 'status': 'LEGACY_FROZEN_CONTRACT'}
    from audit_cache import derived, content_key
    from codex_reference_contract import file_session
    # This is also a public read-only entry, used without production_runtime.
    # Keep all panels in one transaction; nested runtime callers reuse theirs.
    selected=tuple(panel_ids) if panel_ids is not None else None
    with file_session():
        return derived('final_semantic_coverage', content_key([str(root), state, dependency_plan, selected]),
                       lambda: _coverage(state, root, dependency_plan, panel_ids=selected))


def _coverage(state, root, dependency_plan=None, *, panel_ids=None):
    root = Path(root)
    source = read_json(checked_file(root, state['source_snapshot']))
    shots = {p['panel_id']: p for p in read_json(checked_file(root, state['shot_manifest']))['panels']}
    records = {r['panel_id']: r for r in state['panels']}
    plans = dependency_rows(state, root, dependency_plan)
    selected=source['panel_ids'] if panel_ids is None else [p for p in source['panel_ids'] if p in panel_ids]
    if panel_ids is not None and (not panel_ids or len(set(panel_ids))!=len(panel_ids) or set(selected)!=set(panel_ids)):
        raise ValueError('语义选集须准确属于源序，不为空且不重复')
    errors, pending = {}, []
    for pid in selected:
        try:
            if shots[pid].get('generation_dependencies'):
                found = panel_errors(state, root, shots[pid], plan_row=plans[pid]); pending.append(pid)
            else:
                path = checked_file(root, records[pid]['package_manifest'])
                found = panel_errors(state, root, shots[pid], read_json(path), path.parent)
            if found: errors[pid] = found
        except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
            errors[pid] = ['INPUT_SEMANTICS_HOLD:' + str(exc)]
    from preparation_gate_policy import enabled as light_preparation, warnings, FIELD
    extra = {}
    if light_preparation(state):
        audit = read_json(checked_file(root, state['semantic_audit']))
        extra = {FIELD: state[FIELD], 'warnings': {r['panel_id']: warnings(r) for r in audit['panels'] if r['panel_id'] in selected and warnings(r)}}
    return {**extra, 'policy': state['input_semantics_policy'], 'status': 'HOLD' if errors else 'SCOPED_INPUTS_REVIEWED' if panel_ids is not None else 'PREPRODUCTION_INPUTS_REVIEWED',
            'scope':'selected' if panel_ids is not None else 'episode',
            'panel_ids': selected, 'reviewed_panel_ids': [p for p in selected if p not in errors],
            'pending_real_reference_review_ids': pending, 'errors': errors,
            'dispatch_authorized': False, 'image_calls': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--output', help='新审查模板路径；不覆盖、不更新生产状态')
    parser.add_argument('--dependency-plan', help='相对运行根的已保存补齐方案')
    parser.add_argument('--panels', nargs='+', help='仅重建选中格；其余审查原样保留')
    parser.add_argument('--completion', action='store_true', help='为真实依赖补入后的请求生成未审模板')
    args = parser.parse_args()
    try:
        path = resolve_path(Path(args.state)); root = path.parent.parent; state = read_json(path)
        if not enabled(state): raise ValueError('旧冻结运行不自动启用新审查')
        plan_ref = {'path': args.dependency_plan, 'sha256': digest(root / args.dependency_plan)} if args.dependency_plan else None
        if not args.output:
            from codex_reference_contract import file_session
            with file_session():
                if read_json(path) != state:
                    raise ValueError('CHECK_SNAPSHOT_CHANGED: 生产状态在审计开始前变化')
                report = coverage(state, root, plan_ref, panel_ids=args.panels)
            print(json.dumps(report, ensure_ascii=False))
            return 0 if report['status'] != 'HOLD' else 1
        from panel_readiness import review_context
        from codex_reference_contract import file_session
        with file_session(), review_context(state, root, not args.completion):
            if read_json(path) != state:
                raise ValueError('CHECK_SNAPSHOT_CHANGED: 生产状态在审计开始前变化')
            audit = copy.deepcopy(read_json(checked_file(root, state['semantic_audit'])))
            shots = {r['panel_id']: r for r in read_json(checked_file(root, state['shot_manifest']))['panels']}
            records = {r['panel_id']: r for r in state['panels']}
            plans = {r['panel_id']: r for r in read_json(checked_file(root, plan_ref))['inputs']} if plan_ref else {}
            selected = args.panels or audit['panel_ids']
            if not set(selected) <= set(audit['panel_ids']): raise ValueError('选集不属于全话源格')
            for row in audit['panels']:
                pid = row['panel_id']
                if pid not in selected: continue
                _audit_row(state, root, pid)
                if shots[pid].get('generation_dependencies') and not args.completion:
                    inputs = planned_input(state, root, shots[pid], plans[pid])
                else:
                    packet_path = checked_file(root, records[pid]['package_manifest'])
                    inputs = actual_input(state, root, shots[pid], read_json(packet_path), packet_path.parent)
                field = 'dependency_completion_review' if args.completion else 'execution_review'
                row[field] = review_template(inputs)
                row[field]['detected_conflicts'] = conflict_errors(shots[pid], inputs['prompt'])
        output = resolve_path(Path(args.output)); output.relative_to(root)
        with output.open('x', encoding='utf-8') as f: json.dump(audit, f, ensure_ascii=False, indent=2)
        print(json.dumps({'status': 'UNREVIEWED_TEMPLATE', 'output': str(output), 'image_calls': 0, 'dispatch_authorized': False}))
        return 0
    except (OSError, ValueError, TypeError, KeyError, IndexError, StopIteration) as exc:
        print(json.dumps({'status': 'HOLD', 'errors': [str(exc)]}, ensure_ascii=False)); return 1


if __name__ == '__main__':
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())

