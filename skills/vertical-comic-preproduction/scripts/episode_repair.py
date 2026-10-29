"""Validate rolling second-round authorization against an actual failed image."""
from codex_reference_contract import checked_file, read_json
from production_evidence import attempt_errors, snapshot


def returned_authorized_copy(original, returned, root, package_root, record, authorized_ref):
    """Only a new run may append a proven return to the exact authorized input.

    Keep legacy packet equality unchanged. No creative field may change, and
    this exception is unavailable before a real result has been saved.
    """
    import copy
    if record.get('status') not in {'GENERATED', 'VISUAL_PASS', 'VISUAL_FAIL', 'USER_ACCEPTED'}:
        return False
    before = copy.deepcopy(original); after = copy.deepcopy(returned)
    receipt = after.pop('dispatch_receipt', None)
    source = after.pop('dispatch_source_package', None)
    if receipt is not None or source is not None:
        if (source != authorized_ref or not isinstance(receipt, dict) or
                receipt.get('attempt_id') != record.get('attempt_id') or receipt.get('round_id') != 2 or
                receipt.get('batch_id') != 'EPISODE'):
            return False
    try:
        old_execution = before['panels'][0].pop('generation_execution')
        execution = after['panels'][0].pop('generation_execution')
        if before != after or old_execution.get('status') != 'NOT_RUN' or execution.get('status') != 'COMPLETED':
            return False
        from codex_reference_contract import validate_panel, execution_errors, digest
        errors, submission = validate_panel(returned['panels'][0], package_root, enforce_input_budget=False)
        if errors or submission is None or execution_errors(execution, submission, package_root, record['panel_id']):
            return False
        if execution.get('attempt_id') != record['attempt_id']:
            return False
        response = read_json(checked_file(package_root, execution['response_evidence']))
        output = checked_file(root, record['output'])
        return digest(output) in {r.get('sha256') for r in response.get('outputs', [])}
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return False


def failure_ids(records):
    return [r['panel_id'] for r in records if r.get('status') == 'VISUAL_FAIL' or
            any(h.get('status') == 'VISUAL_FAIL' for h in r.get('attempt_history', []))]


def systemic_errors(state, records, root):
    failed = failure_ids(records)
    if len(failed) <= state['review_policy']['systemic_failure_count_gt']:
        return []
    report = state.get('episode_failure_diagnosis', {})
    source = report.get('source')
    if (report.get('policy') != 'episode_failure_diagnosis_v1' or report.get('status') != 'REVIEWED' or
            not report.get('reviewer') or not report.get('evidence') or not report.get('common_cause') or
            not set(failed) <= set(report.get('reviewed_failure_panel_ids', [])) or not isinstance(source, dict)):
        return ['超过5张真实失败图，返修前须记录当前累计失败格的共因诊断']
    try:
        original = read_json(checked_file(root, source))
        if {**original, 'source': source} != report:
            return ['共因诊断文件与当前登记版本不一致']
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return [f'共因诊断依据无效:{exc}']
    return []


def repair_errors(state, root, record):
    pid = record['panel_id']; history = record.get('attempt_history', [])
    if len(history) != 1 or history[0].get('status') != 'VISUAL_FAIL':
        return ['滚动返修须保留唯一首轮真实失败尝试']
    errors = attempt_errors(state, root, history[0])
    auth_ref = state.get('repair_authorizations', {}).get(pid)
    if not isinstance(auth_ref, dict): return errors + ['缺少当前格独立返修授权文件']
    auth = read_json(checked_file(root, auth_ref))
    if any(auth.get(k) != v for k, v in {
            'policy': 'episode_repair_v1', 'panel_id': pid, 'failed_attempt': snapshot(history[0])}.items()):
        errors.append('返修授权未绑定真实失败尝试')
    if not auth.get('reviewer') or not auth.get('evidence') or not isinstance(auth.get('repair_constraints'), list) or not auth['repair_constraints'] or any(not isinstance(c, str) or not c.strip() for c in auth['repair_constraints']):
        errors.append('返修缺实际诊断或非空修正约束')
    if state.get('input_quality_policy') == 'execution_quality_v1' or state.get('production_policy') == 'first_batch_production_v1':
        from input_quality import repair_decision_errors
        errors.extend(repair_decision_errors(auth.get('repair_decision'), history[0], require_image_call=True, state=state, root=root, new_package=auth.get('new_package_manifest')))
    if auth.get('route') != 'targeted_image_repair':
        errors.append('参考、镜头或生图包错误须回原阶段，不按图像执行返修')
    if auth.get('new_attempt_id') != record.get('attempt_id') or auth.get('new_shot_subset') != record.get('shot_subset'):
        errors.append('返修授权与当前新尝试/执行包不一致')
    authorized_packet=auth.get('new_package_manifest')
    current_packet=record.get('package_manifest')
    if authorized_packet != current_packet:
        try:
            dispatched=read_json(checked_file(root,current_packet))
            original=read_json(checked_file(root,authorized_packet))
            receipt=dispatched.get('dispatch_receipt')
            source=dispatched.get('dispatch_source_package')
            actual_return = (state.get('production_policy') == 'first_batch_production_v1' and
                returned_authorized_copy(original, dispatched, root, checked_file(root,current_packet).parent,
                                         record, authorized_packet))
            if not actual_return and (source!=authorized_packet or not isinstance(receipt,dict) or
                    {k:v for k,v in dispatched.items() if k not in {'dispatch_receipt','dispatch_source_package'}}!=original or
                    receipt.get('attempt_id')!=record.get('attempt_id') or receipt.get('round_id')!=2 or receipt.get('batch_id')!='EPISODE'):
                errors.append('返修派发包不是授权包的仅加回执副本')
        except (OSError,ValueError,TypeError,KeyError) as exc:
            errors.append(f'返修派发来源无效:{exc}')
    if record.get('round_id') != 2 or record.get('attempt_id') == history[0].get('attempt_id'):
        errors.append('返修须唯一第二轮及新attempt_id')
    return errors
