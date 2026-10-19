"""Carry only applicable first-pass image risks from approved shot into the real prompt."""

KINDS = {'lower_edge', 'action_target', 'support_contact', 'prop_count'}


def shot_errors(shot):
    risks = shot.get('production_risks', [])
    if not isinstance(risks, list):
        return ['production_risks须为清单']
    errors = []
    seen = set()
    for item in risks:
        if not isinstance(item, dict) or set(item) != {'kind', 'constraint'}:
            errors.append('production_risks每项只含kind与constraint'); continue
        kind, constraint = item['kind'], item['constraint']
        if kind not in KINDS or kind in seen:
            errors.append('production_risks类别未知或重复')
        seen.add(kind)
        if not isinstance(constraint, str) or not constraint.strip():
            errors.append('production_risks须写具体可执行约束')
    return errors


def packet_errors(shot, panel):
    errors = shot_errors(shot)
    if errors:
        return errors
    risks = shot.get('production_risks', [])
    if panel.get('production_risks', []) != risks:
        errors.append('生图包production_risks须与获批镜头完全一致')
    prompt = panel.get('prompt', '')
    if not isinstance(prompt, str):
        return errors + ['生图prompt无效']
    for item in risks:
        if item['constraint'] not in prompt:
            errors.append(f"{item['kind']}:实际生图prompt缺少画面约束")
    return errors
