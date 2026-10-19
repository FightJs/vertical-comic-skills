"""Task-scoped provenance: independent remakes are not resumptions of namesakes.

No directory discovery, image calls, approval synthesis or budget reset.
Legacy states without this contract remain on their frozen contract.
"""
import json
import uuid
from pathlib import Path

POLICY = 'task_scoped_history_v1'
ORIGIN_FILE = '00_输入审计/任务来源.json'
UNSENT = {'PENDING', 'REPAIR_AUTHORIZED', 'NOT_RUN'}


def validate(context):
    if not isinstance(context, dict) or context.get('policy') != POLICY:
        raise ValueError('TASK_SCOPE_HOLD:任务来源合同缺失/未知')
    if not all(isinstance(context.get(k), str) and context[k].strip() for k in ('task_id', 'book_id')):
        raise ValueError('TASK_SCOPE_HOLD:缺任务身份')
    ids = context.get('episode_ids')
    if not isinstance(ids, list) or not ids or any(not isinstance(e, str) or not e for e in ids) or len(set(ids)) != len(ids):
        raise ValueError('TASK_SCOPE_HOLD:任务话号缺失/重复')
    if context.get('origin') not in {'fresh', 'reuse_selected'}:
        raise ValueError('TASK_SCOPE_HOLD:恢复/接包须保留原任务，不用prepare重建')
    if context.get('input_scope') != 'script_and_assets':
        raise ValueError('TASK_SCOPE_HOLD:输入范围不明确')
    source = context.get('request_source', {})
    if source.get('source_kind') not in {'user_message', 'tool_invocation'} or not source.get('source_locator') or not source.get('quote'):
        raise ValueError('TASK_SCOPE_HOLD:缺真实任务请求来源；程序调用不是用户批准')
    imports = context.get('imports')
    if not isinstance(imports, list) or (context['origin'] == 'fresh' and imports):
        raise ValueError('TASK_SCOPE_HOLD:独立重做不能自动继承旧成果')
    if context['origin'] == 'reuse_selected' and (not imports or source['source_kind'] != 'user_message'):
        raise ValueError('TASK_SCOPE_HOLD:复用须有准确用户请求及选定成果')
    for item in imports:
        if not isinstance(item, dict) or not item.get('source_task_id') or item['source_task_id'] == context['task_id'] or item.get('episode_id') not in ids:
            raise ValueError('TASK_SCOPE_HOLD:复用任务归属错误')
        panels = item.get('panel_ids')
        if not isinstance(panels, list) or not panels or any(not isinstance(p, str) or not p for p in panels) or len(set(panels)) != len(panels) or not item.get('evidence'):
            raise ValueError('TASK_SCOPE_HOLD:复用须限定格号和真实来源引用')
    return context


def fresh(book, episodes, request_source=None):
    return validate({'policy': POLICY, 'task_id': 'TASK_' + uuid.uuid4().hex,
                     'book_id': book, 'episode_ids': list(episodes), 'origin': 'fresh',
                     'input_scope': 'script_and_assets', 'imports': [],
                     'request_source': request_source or {
                         'source_kind': 'tool_invocation', 'source_locator': 'comic_start.prepare',
                         'quote': 'prepare creates an independent task from the supplied script and assets; no human approval implied'}})


def state_errors(state, root):
    """Bind a new state to its original initialization, including after relocation."""
    marker = Path(root) / ORIGIN_FILE
    context = state.get('task_context')
    if context is None and not marker.exists():
        return []  # Old RV: do not silently upgrade its contract.
    try:
        validate(context)
        origin = json.loads(marker.read_text(encoding='utf-8-sig'))
        if origin.get('task_context') != context or origin.get('episode_id') != state.get('episode_id') or origin.get('initial_body_calls') != 0:
            raise ValueError('初始化任务身份失配；换RV不得重写来源')
        if context['book_id'] != state.get('book_id') or state.get('episode_id') not in context['episode_ids']:
            raise ValueError('任务与本书/本话失配')
        return []
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return ['TASK_SCOPE_HOLD:' + str(exc)]


def history_errors(context, episode, state, root, reference):
    """Cross-check the declared body history against the supplied task's real state.

An empty handoff array is insufficient: inspect retained attempts and request
receipts in the actual run template. Asset history is a separate ledger.
"""
    errors = state_errors(state, root)
    if errors:
        return errors
    if state.get('task_context') != context:
        return ['TASK_SCOPE_HOLD:交接与运行模板任务身份不一致/合同被删除']
    if context is None:
        return []
    records = {r['panel_id']: r for r in state.get('panels', [])}
    for item in context['imports']:
        for ref in item['evidence']:
            reference(ref)
    for panel in episode['panels']:
        pid = panel['panel_id']; history = panel['history']
        if history.get('task_id') != context['task_id']:
            errors.append(pid + ':历史未限定本任务')
        record = records.get(pid)
        if record is None:
            errors.append(pid + ':缺本任务实际逐格状态'); continue
        retained = record.get('attempt_history', [])
        if not isinstance(retained, list):
            errors.append(pid + ':原尝试记录无效'); continue
        calls = [r for r in [*retained, record] if r.get('status') not in UNSENT or
                 any(r.get(k) for k in ('call_evidence', 'output', 'submitted_at'))]
        actual = {r.get('attempt_id'): r for r in calls}
        declared = {a['attempt_id']: a for a in history['attempts']}
        if None in actual or len(actual) != len(calls) or set(actual) != set(declared):
            errors.append(pid + ':本任务真实调用与交接账不一致，不能用空历史证明零调用'); continue
        for receipt in state.get('dispatch_ledger', []):
            if receipt.get('panel_id') == pid and receipt.get('status') in {'IN_FLIGHT','RESULT_UNKNOWN','COMPLETED'} and receipt.get('attempt_id') not in declared:
                errors.append(pid + ':本任务调度账有已提交请求，不能声明零调用')
        for aid, attempt in declared.items():
            owner = actual[aid].get('source_task_id', context['task_id'])
            allowed = owner == context['task_id'] or any(
                i['source_task_id'] == owner and i['episode_id'] == episode['episode_id'] and pid in i['panel_ids']
                for i in context['imports'])
            if not allowed or attempt.get('task_id') != owner:
                errors.append(pid + ':混入未选择继承的其他任务调用')
            status = actual[aid].get('status')
            if actual[aid].get('round_id',1)>1 and attempt.get('kind') == 'initial':
                errors.append(pid + ':返修调用不能改记首轮以重置预算')
            if status in {'IN_FLIGHT', 'RESULT_UNKNOWN', 'CANCELLED'} and attempt['status'] != 'UNKNOWN':
                errors.append(pid + ':原在途/未知请求不得改写成已知结果')
            if status in {'GENERATED', 'VISUAL_PASS', 'VISUAL_FAIL', 'USER_ACCEPTED'}:
                if attempt['status'] != 'COMPLETED' or attempt.get('output', {}).get('sha256') != actual[aid].get('output', {}).get('sha256'):
                    errors.append(pid + ':历史图/返回状态未绑定本任务真实输出')
                if not actual[aid].get('qa_report') or attempt.get('qa', {}).get('sha256') != actual[aid]['qa_report'].get('sha256'):
                    errors.append(pid + ':历史QA未绑定本任务真实审查')
    return errors
