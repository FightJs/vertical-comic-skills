"""One actual image observation, story-critical repairs only; never synthesize full QA."""
from pathlib import Path
from codex_reference_contract import read_json, path_exists, checked_file, digest, physical_file

POLICY = 'light_story_review_v1'
FIELD = 'image_review_profile'
CHECKS = ('identity', 'story_readability')


def enabled(state):
    value = state.get(FIELD)
    if value not in (None, 'full', POLICY):
        raise ValueError('Unknown image review profile')
    return value == POLICY


def at_root(root):
    path = Path(root) / '00_输入审计/生产流程.json'
    return enabled(read_json(path)) if path_exists(path) else False


def template(record):
    return {'panel_id': record['panel_id'], 'image_sha256': record['output']['sha256'],
            'light_review': {'policy': POLICY, 'status': 'UNREVIEWED', 'reviewer': '',
                'checks': {key: {'status': 'UNREVIEWED', 'observed': ''} for key in CHECKS},
                'issues': [], 'scope': '单次全图轻审核；未做六项细节及整话/跨话全面复审'}}


def review_errors(item, *, require_pass=False):
    review = item.get('light_review', {})
    if review.get('policy') != POLICY:
        return ['LIGHT_QA: missing explicit lightweight review contract']
    errors = []
    if review.get('status') not in {'PASS', 'FAIL'} or not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip():
        errors.append('LIGHT_QA: actual reviewer and verdict required')
    checks = review.get('checks')
    if not isinstance(checks, dict) or set(checks) != set(CHECKS):
        errors.append('LIGHT_QA: identity and story_readability observations required')
    else:
        for name, check in checks.items():
            if not isinstance(check, dict) or check.get('status') not in {'PASS', 'FAIL'} or not isinstance(check.get('observed'), str) or not check['observed'].strip():
                errors.append('LIGHT_QA: actual observation required: ' + name)
    issues = review.get('issues')
    if not isinstance(issues, list):
        return errors + ['LIGHT_QA: issues must be a list']
    for issue in issues:
        if not isinstance(issue, dict) or type(issue.get('story_critical')) is not bool or any(
                not isinstance(issue.get(key), str) or not issue[key].strip() for key in ('location', 'problem', 'target')):
            errors.append('LIGHT_QA: each issue needs location/problem/target/story_critical')
    failed = isinstance(checks, dict) and any(isinstance(c, dict) and c.get('status') == 'FAIL' for c in checks.values())
    if failed and not any(isinstance(i, dict) and i.get('story_critical') is True for i in issues):
        errors.append('LIGHT_QA: failed story/identity check needs a critical issue')
    critical = any(isinstance(i, dict) and i.get('story_critical') is True for i in issues)
    if bool(critical or failed) != (review.get('status') == 'FAIL'):
        errors.append('LIGHT_QA: verdict must retain observed issues')
    if require_pass and review.get('status') != 'PASS':
        errors.append('LIGHT_QA: image has recorded issues')
    return errors


def evidence_errors(root, record, *, require_pass=False):
    """Keep content identity, decoding, actual return and request evidence checks."""
    if not at_root(root):
        return ['LIGHT_QA: frozen run has not enabled lightweight review']
    manifest_path = checked_file(root, record['package_manifest'])
    packet = read_json(manifest_path)
    report = read_json(checked_file(root, record['qa_report']))
    output = checked_file(root, record['output'])
    panels = packet.get('panels', []); items = report.get('panels', [])
    if (report.get(FIELD) != POLICY or report.get('source_manifest_sha256') != digest(manifest_path)
            or len(panels) != 1 or len(items) != 1 or panels[0].get('panel_id') != record['panel_id']
            or items[0].get('panel_id') != record['panel_id'] or items[0].get('image_sha256') != digest(output)):
        return ['LIGHT_QA: image/package/review binding mismatch']
    errors = review_errors(items[0], require_pass=require_pass)
    expected = 'VISUAL_' + items[0].get('light_review', {}).get('status', '')
    if record.get('status') not in (expected, 'USER_ACCEPTED'):
        errors.append('LIGHT_QA: recorded verdict mismatch')
    from PIL import Image
    with Image.open(physical_file(output)) as image:
        image.verify()
    from codex_reference_contract import validate_panel, execution_errors
    panel = panels[0]
    preflight, submission = validate_panel(panel, manifest_path.parent, enforce_input_budget=False)
    errors.extend(preflight)
    execution = panel.get('generation_execution', {})
    if execution.get('status') != 'COMPLETED' or execution.get('attempt_id') != record.get('attempt_id') or submission is None:
        errors.append('LIGHT_QA: actual completed generation evidence required')
    else:
        errors.extend(execution_errors(execution, submission, manifest_path.parent, record['panel_id']))
        response = read_json(checked_file(manifest_path.parent, execution.get('response_evidence')))
        if not any(i.get('sha256') == digest(output) for i in response.get('outputs', [])):
            errors.append('LIGHT_QA: image is not an actual returned output')
    return errors


def decision_errors(decision, attempt, item):
    errors = review_errors(item)
    issues = item.get('light_review', {}).get('issues', [])
    if decision.get('action') in {'local_edit', 'regenerate', 'rebuild_inputs', 'crop_candidate'}:
        if attempt.get('round_id') != 1 or not any(i.get('story_critical') is True for i in issues):
            errors.append('LIGHT_QA: only a first-round story-critical problem may be repaired')
        if decision.get('opportunistic'):
            errors.append('LIGHT_QA: no opportunistic cosmetic repairs')
        targets = set(decision.get('fix_now', []))
        if any(i.get('id') in targets and i.get('story_critical') is not True for i in decision.get('issues', [])):
            errors.append('LIGHT_QA: repair targets must be story-critical')
    expected = {f'/light_review/issues/{n}' for n in range(len(issues))}
    actual = {r for i in decision.get('issues', []) for r in i.get('observations', [])}
    if not expected <= actual:
        errors.append('LIGHT_QA: every observed issue needs a handling decision')
    for n, observed in enumerate(issues):
        matched = [i for i in decision.get('issues', []) if f'/light_review/issues/{n}' in i.get('observations', [])]
        if len(matched) != 1 or any(matched[0].get(k) != observed.get(k) for k in ('location', 'problem', 'target', 'story_critical')):
            errors.append('LIGHT_QA: decision must retain the actual observed issue')
    return errors


def prepare_observations(item, proposal, record):
    """Reviewer supplies two quick observations and issues; tool supplies bookkeeping."""
    observed = proposal.get('light_observations')
    if not isinstance(observed, dict) or set(observed) != {'checks', 'issues'}:
        raise ValueError('LIGHT_QA: supply light_observations with checks and issues')
    item['light_review'].update(observed, reviewer=proposal['reviewer'], status=proposal['verdict'])
    errors = review_errors(item)
    if errors: raise ValueError(';'.join(errors))
    if proposal.get('decision') is None:
        issues = []
        for n, issue in enumerate(observed['issues']):
            issues.append({**issue, 'id': f'I{n+1}', 'category': 1 if issue['story_critical'] else 3,
                'certainty': 'confirmed', 'kind': 'story' if issue['story_critical'] else 'cosmetic',
                'basis': '本次实际全图轻审核', 'handling': '待处理' if issue['story_critical'] and record['round_id'] == 1 else '留人工',
                'observations': [f'/light_review/issues/{n}']})
        critical = [i['id'] for i in issues if i['story_critical']]
        # Only serious first-round findings need an explicit repair plan.
        if critical and record['round_id'] == 1:
            raise ValueError('LIGHT_QA: serious first-round issue requires a concrete decision/repair plan')
        action = 'defer_manual' if issues else 'complete'
        proposal['decision'] = {'action': action, 'reason': proposal['reason'], 'issues': issues,
                               'fix_now': [], 'opportunistic': [], 'manual': [i['id'] for i in issues]}
    if proposal['verdict'] == 'FAIL':
        proposal.setdefault('failure_diagnosis', {'layer': 'generation_execution',
            'evidence': '; '.join(i['problem'] for i in observed['issues'])})
