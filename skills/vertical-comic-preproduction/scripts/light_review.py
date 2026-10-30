"""One actual image observation, story-critical repairs only; never synthesize full QA."""
from pathlib import Path
from codex_reference_contract import read_json, path_exists, checked_file, digest, physical_file

from contextvars import ContextVar
from contextlib import contextmanager
_HISTORICAL = ContextVar('comic_original_review_contract', default=False)

@contextmanager
def original_review_contract():
    token=_HISTORICAL.set(True)
    try: yield
    finally: _HISTORICAL.reset(token)

POLICY = 'light_story_review_v1'
FIELD = 'image_review_profile'
CHECKS = ('identity', 'story_readability')
REPAIR_FIELD = 'repair_threshold_policy'
REPAIR_POLICY = 'essential_story_only_v1'
ESSENTIAL_IMPACTS = {'main_character_misidentified', 'key_event_missing', 'story_reversed', 'story_unreadable', 'scene_background_missing'}


def strict_repair(state):
    value=state.get(REPAIR_FIELD)
    if value not in (None,REPAIR_POLICY):raise ValueError('Unknown repair threshold policy')
    if value and state.get(FIELD)!=POLICY:raise ValueError('Essential repair threshold requires light review')
    return value==REPAIR_POLICY


def missing_scene_background(item):
    return any(isinstance(i,dict) and i.get('story_impact')=='scene_background_missing'
               for i in item.get('light_review',{}).get('issues',[]))


def repair_eligible(issue, strict=False):
    return issue.get('story_critical') is True and (not strict or issue.get('story_impact') in ESSENTIAL_IMPACTS)



def enabled(state):
    value = state.get(FIELD)
    if value not in (None, 'full', POLICY):
        raise ValueError('Unknown image review profile')
    strict_repair(state)
    return value == POLICY


def at_root(root):
    if _HISTORICAL.get(): return False
    path = Path(root) / '00_输入审计/生产流程.json'
    from source_input_contract import read as source_inputs
    return enabled(source_inputs(path)) if path_exists(path) else False


def template(record, state=None):
    strict=strict_repair(state or {})
    item= {'panel_id': record['panel_id'], 'image_sha256': record['output']['sha256'],
            'light_review': {'policy': POLICY, 'status': 'UNREVIEWED', 'reviewer': '',
                'checks': {key: {'status': 'UNREVIEWED', 'observed': ''} for key in CHECKS},
                'issues': [], 'scope': '单次全图轻审核：人物、剧情及是否严重空背景；未做六项细节及整话/跨话全面复审'}}
    if strict:
        item['light_review'].update({REPAIR_FIELD:REPAIR_POLICY,'single_observation':''})
        item['light_review'].pop('checks')
    return item


def review_errors(item, *, require_pass=False):
    review = item.get('light_review', {})
    if review.get('policy') != POLICY:
        return ['LIGHT_QA: missing explicit lightweight review contract']
    errors = []
    strict=review.get(REPAIR_FIELD)==REPAIR_POLICY
    if review.get(REPAIR_FIELD) not in (None,REPAIR_POLICY):errors.append('LIGHT_QA: unknown repair threshold')
    if review.get('status') not in {'PASS', 'FAIL'} or not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip():
        errors.append('LIGHT_QA: actual reviewer and verdict required')
    checks = review.get('checks')
    single = review.get('single_observation')
    if single is not None:
        if not isinstance(single, str) or not single.strip() or checks is not None:
            errors.append('LIGHT_QA: one actual identity/story observation required')
    elif not isinstance(checks, dict) or set(checks) != set(CHECKS):
        errors.append('LIGHT_QA: identity and story_readability observations required')
    elif single is None:
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
        if isinstance(issue,dict) and issue.get('story_impact')=='scene_background_missing' and issue.get('story_critical') is not True:
            errors.append('LIGHT_QA: severe blank background is a delivery-blocking issue')
        if strict and isinstance(issue,dict) and issue.get('story_critical') and issue.get('story_impact') not in ESSENTIAL_IMPACTS|{'readable'}:
            errors.append('LIGHT_QA: critical issue needs actual story_impact')
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
    state_path=Path(root)/'00_输入审计/生产流程.json'
    from source_input_contract import read as source_inputs
    state=source_inputs(state_path)
    if state.get('runtime_import'):
        from runtime_import import historical_record
        old=historical_record(state,root,record)
        if old is not None and not enabled(old):
            from production_evidence import attempt_errors
            with original_review_contract():
                errors=attempt_errors(old,root,record)
            if require_pass and record.get('status') not in {'VISUAL_PASS','USER_ACCEPTED'}:
                errors.append('Imported review records actual visual issues')
            return errors
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
    from source_input_contract import read as source_inputs
    state=source_inputs(Path(root)/'00_输入审计/生产流程.json')
    if items[0].get('light_review',{}).get(REPAIR_FIELD)!=state.get(REPAIR_FIELD):
        return ['LIGHT_QA: frozen repair threshold mismatch']
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
    strict=item.get('light_review',{}).get(REPAIR_FIELD)==REPAIR_POLICY
    if decision.get('action') in {'local_edit', 'regenerate', 'rebuild_inputs', 'crop_candidate'}:
        if attempt.get('round_id') != 1 or not any(i.get('story_critical') is True for i in issues):
            errors.append('LIGHT_QA: only a first-round story-critical problem may be repaired')
        if decision.get('opportunistic'):
            errors.append('LIGHT_QA: no opportunistic cosmetic repairs')
        targets = set(decision.get('fix_now', []))
        if any(i.get('id') in targets and i.get('story_critical') is not True for i in decision.get('issues', [])):
            errors.append('LIGHT_QA: repair targets must be story-critical')
        if strict and any(i.get('id') in targets and (not repair_eligible(i,True) or i.get('certainty')!='confirmed') for i in decision.get('issues', [])):
            errors.append('LIGHT_QA: repair requires an essential story impact')
    expected = {f'/light_review/issues/{n}' for n in range(len(issues))}
    actual = {r for i in decision.get('issues', []) for r in i.get('observations', [])}
    if not expected <= actual:
        errors.append('LIGHT_QA: every observed issue needs a handling decision')
    for n, observed in enumerate(issues):
        matched = [i for i in decision.get('issues', []) if f'/light_review/issues/{n}' in i.get('observations', [])]
        if len(matched) != 1 or any(matched[0].get(k) != observed.get(k) for k in (('location', 'problem', 'target', 'story_critical','story_impact') if strict else ('location', 'problem', 'target', 'story_critical'))):
            errors.append('LIGHT_QA: decision must retain the actual observed issue')
    return errors


def prepare_observations(item, proposal, record, *, allow_manual_critical=False):
    """Reviewer supplies two quick observations and issues; tool supplies bookkeeping."""
    observed = proposal.get('light_observations')
    if not isinstance(observed, dict) or set(observed) not in ({'checks', 'issues'}, {'single_observation', 'issues'}):
        raise ValueError('LIGHT_QA: supply light_observations with checks and issues')
    strict=item['light_review'].get(REPAIR_FIELD)==REPAIR_POLICY
    if strict:
        for issue in observed.get('issues',[]):
            if isinstance(issue,dict):issue.setdefault('story_critical',issue.get('story_impact') in ESSENTIAL_IMPACTS)
    item['light_review'].pop('checks' if 'single_observation' in observed else 'single_observation', None)
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
        critical = [i['id'] for i in issues if repair_eligible(i,strict)]
        # Only serious first-round findings need an explicit repair plan.
        if critical and record['round_id'] == 1 and not allow_manual_critical:
            raise ValueError('LIGHT_QA: serious first-round issue requires a concrete decision/repair plan')
        action = 'defer_manual' if issues else 'complete'
        proposal['decision'] = {'action': action, 'reason': proposal['reason'], 'issues': issues,
                               'fix_now': [], 'opportunistic': [], 'manual': [i['id'] for i in issues]}
    if strict and proposal['decision'].get('action') in {'local_edit','regenerate','rebuild_inputs','crop_candidate'}:
        decision=proposal['decision']
        for issue in decision.get('issues',[]):
            matches=[o for n,o in enumerate(observed['issues']) if f'/light_review/issues/{n}' in issue.get('observations',[])]
            if len(matches)==1:issue.setdefault('story_impact',matches[0].get('story_impact'))
        # Match by the actual observation pointer, not reviewer-supplied issue IDs.
        eligible={i['id'] for i in decision.get('issues',[]) if any(
            f'/light_review/issues/{n}' in i.get('observations',[]) and repair_eligible(o,True)
            for n,o in enumerate(observed['issues']))}
        decision['fix_now']=[i for i in decision.get('fix_now',[]) if i in eligible]
        decision['opportunistic']=[]
        decision['manual']=[i['id'] for i in decision.get('issues',[]) if i['id'] not in decision['fix_now']]
        if not decision['fix_now']:
            decision.update(action='defer_manual',reason='未达必要返修阈值：保留实际问题，采用现有图供人工后修')
            proposal['adopt']=True
    if strict and proposal.get('decision',{}).get('action')=='defer_manual':proposal['adopt']=True
    if missing_scene_background(item):proposal['adopt']=False
    if proposal['verdict'] == 'FAIL':
        proposal.setdefault('failure_diagnosis', {'layer': 'generation_execution',
            'evidence': '; '.join(i['problem'] for i in observed['issues'])})
