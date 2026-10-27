"""Prepare and save one content-bound observation, with optional delegated B/package decisions."""
import argparse
import copy
import json
import uuid
from pathlib import Path
from codex_reference_contract import checked_file, digest, read_json, file_session
from preparation_gate_policy import enabled, template, reviewed, FIELD, POLICY


def inputs_for(state, root, panel_ids=None, completion=False, dependency_plan=None):
    from input_semantics import actual_input, planned_input, dependency_rows
    from panel_readiness import review_context
    if not enabled(state): raise ValueError('旧冻结运行不自动迁移轻门禁')
    source = read_json(checked_file(root, state['source_snapshot']))
    order = source['panel_ids']
    selected = order if panel_ids is None else panel_ids
    if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(order):
        raise ValueError('选集须为准确、不重复的源格')
    shots = {r['panel_id']: r for r in read_json(checked_file(root, state['shot_manifest']))['panels']}
    records = {r['panel_id']: r for r in state['panels']}
    plans = dependency_rows(state, root, dependency_plan)
    result = {}
    with review_context(state, root, not completion):
        for pid in selected:
            if shots[pid].get('generation_dependencies') and not completion:
                result[pid] = planned_input(state, root, shots[pid], plans[pid])
            else:
                path = checked_file(root, records[pid]['package_manifest'])
                result[pid] = actual_input(state, root, shots[pid], read_json(path), path.parent)
    return result


def prepare(state_path, panel_ids=None, completion=False, dependency_plan=None):
    path = Path(state_path).resolve(); root = path.parent.parent
    with file_session():
        state = read_json(path)
        inputs = inputs_for(state, root, panel_ids, completion, dependency_plan)
        return {'policy': POLICY, 'book_id': state['book_id'], 'episode_id': state['episode_id'],
                'completion': completion, 'dependency_plan': dependency_plan, 'panels': [
                    {'panel_id': pid, 'input_digest': template(value)['input_digest'],
                     'inputs': value, 'observation': template(value)['observation']}
                    for pid, value in inputs.items()], 'dispatch_authorized': False, 'image_calls': 0}


def save(state_path, observations, reviewer, *, authority_ref=None):
    from authority_updates import state_write_lock
    from platform_io import atomic_json
    from input_semantics import panel_errors, coverage
    from preparation_gate_policy import observation_errors
    path = Path(state_path).resolve(); root = path.parent.parent
    if not isinstance(reviewer, str) or not reviewer.strip(): raise ValueError('须提供实际审核者')
    with file_session():
        state = read_json(path); original = copy.deepcopy(state)
        if not enabled(state): raise ValueError('旧冻结运行不自动迁移轻门禁')
        if (observations.get('policy') != POLICY or observations.get('book_id') != state['book_id']
                or observations.get('episode_id') != state['episode_id']
                or type(observations.get('completion')) is not bool):
            raise ValueError('观察的策略/书话/阶段不一致')
        rows = observations.get('panels')
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise ValueError('观察须为逐格对象列表')
        ids = [r.get('panel_id') for r in rows]
        dependency_plan = observations.get('dependency_plan')
        inputs = inputs_for(state, root, ids, observations['completion'], dependency_plan)
        audit = copy.deepcopy(read_json(checked_file(root, state['semantic_audit'])))
        source = read_json(checked_file(root, state['source_snapshot']))
        if (audit.get('policy') != 'semantic_audit_v1' or audit.get('panel_ids') != source['panel_ids']
                or [r.get('panel_id') for r in audit.get('panels', [])] != source['panel_ids']
                or any(audit.get(k) != state[k] for k in ('book_id','episode_id','source_snapshot','visual_basis','shot_manifest'))):
            raise ValueError('审查归属/版本/源格序不一致')
        by_id = {r['panel_id']: r for r in audit['panels']}
        field = 'dependency_completion_review' if observations['completion'] else 'execution_review'
        for row in rows:
            pid = row['panel_id']
            review = reviewed(inputs[pid], row.get('observation'), reviewer, row.get('input_digest'))
            by_id[pid][field] = review
        audit[FIELD] = POLICY
        folder = root/'00_输入审计'/'preparation_reviews'/uuid.uuid4().hex
        folder.mkdir(parents=True, exist_ok=False)
        def store(name, value):
            dest = folder/name
            with dest.open('x', encoding='utf-8') as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
            return {'path': dest.relative_to(root).as_posix(), 'sha256': digest(dest)}
        state['semantic_audit'] = store('semantic-audit.json', audit)
        # Scoped validation, no full-episode recompile for one observation edit.
        result = coverage(state, root, dependency_plan, panel_ids=ids)
        decisions = []
        if authority_ref is not None:
            if result['errors']: raise ValueError('存在阻断项，不能登记采用输入的决定')
            if observations['completion']: raise ValueError('实图依赖复核不重新签发B/包批准')
            from production_runtime import preparation_review
            from review_policy import bundle_proposal, delegated_decisions
            combined = preparation_review(state, root, dependency_plan, panel_ids=ids)
            package = combined['generation_package']
            if set(package.get('approval_panel_ids', [])) != set(ids):
                raise ValueError('所选输入尚未全部可执行，不能登记决定')
            package_ref = store('generation-package.json', package)
            proposal = bundle_proposal(state, root, package_ref)
            # Avoid approving unrelated ready designs when saving a local observation.
            for item in proposal['items']: item['panel_ids'] = ids
            from review_policy import proposal as make_proposal
            proposal = make_proposal(state['book_id'], state['episode_id'], proposal['items'], root)
            decisions = delegated_decisions(proposal, [i['item_id'] for i in proposal['items']],
                authority_ref, reviewer, '同次快审观察：' + state['semantic_audit']['path'], root)
            index = copy.deepcopy(read_json(checked_file(root, state['approval_index']))) if state.get('approval_index') else {'policy':'approval_index_v1','entries':[]}
            for decision in decisions:
                ref = store(decision['phase'] + '-decision.json', decision)
                index['entries'].append({'phase':decision['phase'], 'book_id':state['book_id'],
                    'episode_ids':[state['episode_id']], 'panel_ids':ids, 'approval':ref})
            state['approval_index'] = store('approval-index.json', index)
            state.setdefault('generation_packages', {}).setdefault('EPISODE', []).append(package_ref)
        # Verify all read dependencies on leaving file_session, then short CAS write.
    with state_write_lock(path):
        if read_json(path) != original: raise ValueError('STATE_CHANGED:记录期间状态变化；未覆盖当前状态')
        atomic_json(path, state)
    return {'status':'SAVED_WITH_HOLDS' if result['errors'] else 'SAVED', 'panel_ids':ids,
            'semantic_audit':state['semantic_audit'], 'review':result,
            'decision_phases':[d['phase'] for d in decisions], 'dispatch_authorized':False,'image_calls':0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--panels', nargs='+')
    parser.add_argument('--completion', action='store_true')
    parser.add_argument('--dependency-plan', help='已有补齐方案，相对运行根')
    parser.add_argument('--output', help='新观察模板；保存时无需此参数')
    parser.add_argument('--observations', help='填写过的观察模板JSON')
    parser.add_argument('--reviewer')
    parser.add_argument('--authority', help='已有用户委托文件，须在运行根内；同时登记B/包决定')
    args = parser.parse_args()
    try:
        if args.observations:
            if args.panels or args.completion or args.output or args.dependency_plan: raise ValueError('保存范围与阶段来自观察模板')
            root = Path(args.state).resolve().parent.parent
            authority = None
            if args.authority:
                grant = Path(args.authority).resolve(); grant.relative_to(root)
                authority = {'path':grant.relative_to(root).as_posix(),'sha256':digest(grant)}
            value = save(args.state, read_json(Path(args.observations)), args.reviewer, authority_ref=authority)
        else:
            if args.authority or args.reviewer: raise ValueError('准备模板不登记决定')
            if not args.output: raise ValueError('准备模板须指定--output新文件')
            root = Path(args.state).resolve().parent.parent
            plan = None
            if args.dependency_plan:
                plan_path = (root/args.dependency_plan).resolve(); plan_path.relative_to(root)
                plan = {'path':plan_path.relative_to(root).as_posix(), 'sha256':digest(plan_path)}
            value = prepare(args.state, args.panels, args.completion, plan)
            with Path(args.output).open('x',encoding='utf-8') as stream:
                json.dump(value,stream,ensure_ascii=False,indent=2)
            value = {'status':'UNREVIEWED_TEMPLATE','output':args.output,'image_calls':0}
        print(json.dumps(value,ensure_ascii=False));return 0
    except (OSError,ValueError,TypeError,KeyError,AttributeError) as exc:
        print(json.dumps({'status':'HOLD','errors':[str(exc)]},ensure_ascii=False));return 1

if __name__ == '__main__':
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
