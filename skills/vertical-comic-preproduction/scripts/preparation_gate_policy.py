"""One truthful observation for design and final inputs; old frozen runs unchanged."""
import copy

FIELD = 'preparation_gate_policy'
POLICY = 'essential_preparation_v1'
ADVISORY = {'EXPRESSION_DETAIL', 'ACCESSORY_DETAIL', 'COMPOSITION_DETAIL',
            'NONESSENTIAL_SPACE', 'RULE_EXPLANATION'}
BLOCKING = {'CHARACTER_WRONG', 'KEY_EVENT_MISSING', 'STORY_REVERSED', 'STORY_UNREADABLE',
            'REQUIRED_REFERENCE_MISSING', 'REQUEST_NOT_EXECUTABLE'}


def enabled(state):
    value = state.get(FIELD)
    if value not in (None, POLICY):
        raise ValueError('PREPARATION_HOLD:未知前期门禁策略')
    if value and (state.get('input_semantics_policy') != 'final_input_semantics_v2'
                  or state.get('execution_mode') != 'episode_async_v1'):
        raise ValueError('PREPARATION_HOLD:轻门禁要求新整话最终输入合同')
    return value == POLICY


def findings(observation):
    issues = observation.get('issues', [])
    if not isinstance(issues, list):
        raise ValueError('PREPARATION_HOLD:issues须为列表')
    result = []
    for issue in issues:
        if (not isinstance(issue, dict) or issue.get('code') not in ADVISORY | BLOCKING
                or not isinstance(issue.get('detail'), str) or not issue['detail'].strip()
                or type(issue.get('affects_story')) is not bool):
            raise ValueError('PREPARATION_HOLD:问题须包含合法code、具体detail和布尔affects_story')
        blocks = issue['code'] in BLOCKING or issue['affects_story']
        result.append({**issue, 'blocks_input': blocks,
                       'action': 'LOCAL_BLOCK' if blocks else 'RECORD_CONTINUE'})
    return result


def observation_errors(review):
    if not isinstance(review, dict) or review.get(FIELD) != POLICY:
        return ['PREPARATION_HOLD:缺当前策略的一次真实观察']
    observation = review.get('observation')
    if (review.get('status') != 'REVIEWED' or not isinstance(review.get('reviewer'), str)
            or not review['reviewer'].strip() or not isinstance(observation, dict)
            or not isinstance(observation.get('evidence'), str) or not observation['evidence'].strip()):
        return ['PREPARATION_HOLD:尚未实际快审或缺观察内容']
    errors = ['PREPARATION_HOLD:' + key for key in ('characters_correct', 'key_event_readable', 'input_usable')
              if observation.get(key) is not True]
    try:
        errors.extend('PREPARATION_HOLD:' + row['code'] + ':' + row['detail']
                      for row in findings(observation) if row['blocks_input'])
    except ValueError as exc:
        errors.append(str(exc))
    return errors


def template(inputs):
    from input_semantics import fingerprint
    return {'policy': inputs['input_semantics_policy'], FIELD: POLICY,
            'input_digest': fingerprint(inputs), 'status': 'UNREVIEWED', 'reviewer': '',
            'observation': {'evidence': '', 'characters_correct': None,
                            'key_event_readable': None, 'input_usable': None, 'issues': []}}


def reviewed(inputs, observation, reviewer, expected_digest):
    from input_semantics import fingerprint
    if expected_digest != fingerprint(inputs):
        raise ValueError('PREPARATION_HOLD:观察之后输入已改变，请只重新查看本格')
    value = template(inputs)
    value.update(status='REVIEWED', reviewer=reviewer, observation=copy.deepcopy(observation))
    if (not isinstance(observation, dict) or not isinstance(observation.get('evidence'), str)
            or not observation['evidence'].strip()
            or any(type(observation.get(k)) is not bool for k in ('characters_correct','key_event_readable','input_usable'))):
        raise ValueError('PREPARATION_HOLD:须填写一次具体观察和三个布尔结论')
    findings(observation)
    return value


def review_errors(review, inputs):
    from input_semantics import fingerprint
    if (not isinstance(review, dict) or review.get('policy') != inputs.get('input_semantics_policy')
            or review.get('input_digest') != fingerprint(inputs)):
        return ['PREPARATION_HOLD:最终输入已变化或审查版本失配']
    return observation_errors(review)


def design_errors(row):
    return observation_errors(row.get('execution_review'))


def warnings(row):
    review = row.get('execution_review', {})
    if review.get(FIELD) != POLICY or not isinstance(review.get('observation'), dict):
        return []
    try:
        return [item for item in findings(review['observation']) if not item['blocks_input']]
    except ValueError:
        return []
