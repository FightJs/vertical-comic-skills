"""Scoped reuse of compiled inputs. Authority refresh never compiles or invokes."""
import copy
from codex_reference_contract import checked_file, read_json
from submission_contract import fingerprint

POLICY = 'prepared_scope_v2'
COLLECTIONS = {'shot_manifest', 'semantic_audit', 'approval_index', 'generation_packages',
               'authority_policy', 'authority_revision', 'approval_revocations'}


def audit_decisions(row):
    """Explanatory prose changes do not alter verdicts, issues or input identity."""
    row=copy.deepcopy(row)
    def prose(obj):
        if isinstance(obj,dict):
            for key in ('reviewer','evidence'):
                if key in obj:obj[key]=isinstance(obj[key],str) and bool(obj[key].strip())
    prose(row)
    for check in row.get('checks',{}).values():prose(check)
    for field in ('execution_review','dependency_completion_review'):
        review=row.get(field,{})
        prose(review);prose(review.get('observation'))
        for check in review.get('checks',{}).values():prose(check)
    return row


def shared_basis(state):
    from prepared_job_store import _PROGRESS
    return fingerprint({k: v for k, v in state.items() if k not in _PROGRESS | COLLECTIONS})


def snapshot(state, root, pid):
    """Keep unknown headers/fields conservative; only select known row collections."""
    from audit_cache import derived, content_key
    key = content_key([str(root), state.get('shot_manifest'), state.get('semantic_audit'), pid])
    def compute():
        shots = read_json(checked_file(root, state['shot_manifest']))
        audit = read_json(checked_file(root, state['semantic_audit']))
        if any(audit.get(k) != state.get(k) for k in ('book_id', 'episode_id', 'source_snapshot', 'visual_basis', 'shot_manifest')):
            raise ValueError('PREPARED_AUDIT_BINDING_CHANGED')
        rows = {p['panel_id']: p for p in shots['panels']}
        audits = {p['panel_id']: p for p in audit['panels']}
        order = [p['panel_id'] for p in shots['panels']]
        if len(rows) != len(order) or list(audits) != order or len(audit['panels']) != len(order):
            raise ValueError('PREPARED_COLLECTION_SCOPE_CHANGED')
        selected = {pid}; todo = [pid]
        while todo:
            row = rows[todo.pop()]
            for dep in row.get('generation_dependencies', []) + row.get('design_dependencies', []):
                if dep not in selected: selected.add(dep); todo.append(dep)
        return {'shots_header': {k:v for k,v in shots.items() if k != 'panels'},
                'audit_header': {k:v for k,v in audit.items() if k not in {'panels','shot_manifest'}},
                'order': order, 'shots': {p:rows[p] for p in sorted(selected)},
                'audit': {p:audit_decisions(audits[p]) for p in sorted(selected)}}
    return derived('prepared_scope', key, compute)


def refresh(state, root, value):
    """Only unchanged scoped content qualifies. Recheck current A/B/package grants."""
    from authority_updates import authority_context
    from scoped_inputs import approval_for
    from execution_contract import extra_basis_refs
    from production_runtime import package_approval_errors
    pid = value['panel_id']
    if shared_basis(state) != value.get('shared_basis') or snapshot(state, root, pid) != value.get('scope_snapshot'):
        raise ValueError('PREPARED_SCOPED_INPUT_CHANGED:' + pid)
    with authority_context(state, root):
        gates = state.get('gates', {})
        errors = approval_for(state, root, 'visual_basis',
            [state['source_script'],state['source_snapshot'],state['visual_basis']], [pid], gates.get('visual_basis'))
        errors += approval_for(state, root, 'shot_design',
            [state['visual_basis'],state['shot_manifest'],*extra_basis_refs(state)], [pid], gates.get('shot_design'))
        row = next(r for r in state['panels'] if r['panel_id'] == pid)
        errors += package_approval_errors(state, root, {'batch_id':'EPISODE'}, row, value['package_signature'])
        if errors: raise ValueError('PREPARED_AUTHORITY_HOLD:' + ';'.join(errors))
    shots = read_json(checked_file(root, state['shot_manifest']))
    return [{k:p.get(k) for k in ('panel_id','generation_dependencies','visual_state_keys')} for p in shots['panels']]
