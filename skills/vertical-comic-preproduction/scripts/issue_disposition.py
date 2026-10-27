"""Separate work disposition from validation truth; never grant dispatch authority.

Only explicit editorial suggestions are nonblocking. Existing validator errors,
unknown note codes and all legacy holds retain their original blocking semantics.
"""
POLICY = 'preparation_issue_disposition_v1'
ADVISORY = {
    'OPTIONAL_CAMERA_VARIANT': '已有可行机位，停止探索可选机位',
    'OPTIONAL_PROMPT_POLISH': '已有可执行提示词，停止无必要润色',
    'REDUNDANT_EXPLANATION': '保留既有依据引用，不重复写说明',
    'OPTIONAL_EXTRA_REFERENCE': '现有参考充分，不新增可选参考',
}

REPAIR = {
    'PATH_REBIND_REQUIRED': '在当前授权内重新绑定可核实的本地路径，再核对哈希',
    'DERIVED_FIELD_SYNC_REQUIRED': '从现有权威输入同步派生字段，再检查实际输入',
}


def planning_notes(notes, panel_id):
    """Return work items from explicitly structured notes, not error-text matching."""
    if not isinstance(notes, list):
        notes = [{'code': 'INVALID_PLANNING_NOTES', 'detail': 'planning_notes须为清单'}]
    items = []
    for note in notes:
        valid = isinstance(note, dict) and isinstance(note.get('detail'), str) and bool(note['detail'].strip())
        code = note.get('code') if isinstance(note, dict) else None
        advisory = valid and isinstance(code, str) and code in ADVISORY
        repair = valid and isinstance(code, str) and code in REPAIR
        items.append({'code': code if isinstance(code, str) else 'UNCLASSIFIED_NOTE',
                      'detail': note['detail'] if valid else str(note),
                      'panel_ids': [panel_id],
                      'action': 'RECORD_CONTINUE' if advisory else 'AUTO_REPAIR' if repair else 'LOCAL_BLOCK',
                      'blocks_input': not advisory,
                      'next_action': ADVISORY[code] if advisory else REPAIR[code] if repair else '诊断并修复本格，不自动转成人工裁决'})
    return items


def summarize(global_errors=(), local_errors=None, notes=(), ready_ids=()):
    """Scopes come from validators; do not infer severity from human wording."""
    items = [{'action': 'GLOBAL_BLOCK', 'detail': str(error), 'panel_ids': [],
              'next_action': '先修复共同依据；保留原门禁结论'} for error in global_errors]
    for pid, errors in (local_errors or {}).items():
        if errors:
            items.append({'action': 'LOCAL_BLOCK', 'panel_ids': [pid],
                          'detail': errors, 'next_action': '在已有授权内修复并仅重检真实影响范围'})
    items.extend(notes)
    global_block = any(i['action'] == 'GLOBAL_BLOCK' for i in items)
    blocked = set(p for i in items if i['action'] in {'LOCAL_BLOCK','AUTO_REPAIR'} for p in i['panel_ids'])
    ready = [p for p in ready_ids if p not in blocked] if not global_block else []
    return {'policy': POLICY, 'items': items, 'continue_panel_ids': ready,
            'next_action': 'FIX_GLOBAL_BASIS' if global_block else
                           'CONTINUE_INDEPENDENT_AND_REPAIR' if blocked else 'CONTINUE',
            'authority': 'FOLLOW_LATEST_USER_DELEGATION', 'dispatch_authorized': False}


def gate_disposition(report):
    """Attach scope guidance without changing any gate result or eligible set."""
    rows = report.get('reports', [])
    local = {r['panel_id']: r.get('errors', []) or [r.get('next_action', '本格尚未就绪')]
             for r in rows if r.get('panel_id') and r.get('status') != 'PASS'}
    # Batch-level errors are shared unless the original gate supplies an exact scope.
    errors = report.get('errors', [])
    blocked = report.get('blocked_panel_ids', [])
    if errors and blocked:
        for pid in blocked: local.setdefault(pid, []).extend(errors)
        errors = []
    return summarize(errors, local, ready_ids=report.get('ready_panel_ids', []))
