#!/usr/bin/env python3
"""Content-bound grouped questions; caller supplies actual message and accepted IDs.

Never interprets prose, authenticates a message, or infers package approval from B.
Ordinary proof objects remain subject to the existing independent workflow gates.
"""
import argparse
import hashlib
import json
from pathlib import Path
from codex_reference_contract import checked_file

POLICY = 'grouped_review_v1'
PHASES = {'visual_basis','shot_design','generation_package','state_review','final','technical_operations','additional_repair'}
OPERATIONS = {'equal_scale_normalize','information_preserving_crop','faithful_atlas','byte_identical_relocation'}
DECIDED = 'AGENT_DECIDED_UNDER_USER_AUTHORITY'


def decision_errors(proof, root, book, episode):
    """Verify explicit delegation and the agent's scoped decision, not visual truth.

    The caller interprets the actual human message; configuration cannot create
    delegation. No wildcard phases/panels or automatic extra repair budget.
    """
    try:
        grant = json.loads(checked_file(Path(root), proof['authority']).read_text())
        text = lambda v: isinstance(v, str) and bool(v.strip())
        ids = proof.get('panel_ids')
        if (proof.get('status') != DECIDED or proof.get('source_kind') != 'agent_decision'
                or not text(proof.get('reviewer')) or not text(proof.get('evidence'))):
            raise ValueError('缺执行者实际决定与证据')
        if (grant.get('policy') != 'user_delegation_v1' or grant.get('status') != 'AUTHORIZED'
                or grant.get('source_kind') != 'user_message'
                or not text(grant.get('quote')) or not text(grant.get('source_locator'))
                or not isinstance(grant.get('constraints'), list) or not grant['constraints']
                or any(not text(v) for v in grant['constraints'])):
            raise ValueError('缺准确用户授权原文、来源和约束')
        if grant.get('book_id') != book or episode not in grant.get('episode_ids', []):
            raise ValueError('授权书话不符')
        if proof.get('book_id') != book or proof.get('episode_id') != episode:
            raise ValueError('具体决定书话不符')
        allowed = grant.get('panel_ids', {}).get(episode, [])
        if (not isinstance(ids, list) or not ids or len(set(ids)) != len(ids)
                or any(not text(p) for p in ids) or not set(ids) <= set(allowed)
                or set(ids) & set(grant.get('excluded_panel_ids', {}).get(episode, []))):
            raise ValueError('决定格号超出明确授权范围')
        phase = proof.get('phase')
        if (phase not in PHASES or phase not in grant.get('phases', [])
                or phase in grant.get('retained_user_phases', [])):
            raise ValueError('决定阶段未获授权或仍须用户亲审')
        if proof.get('authority_constraints') != grant['constraints']:
            raise ValueError('决定未保留用户授权约束')
        if phase == 'technical_operations':
            operations = proof.get('operations')
            if (not isinstance(operations, list) or not operations
                    or not set(operations) <= OPERATIONS
                    or not set(operations) <= set(grant.get('operations', []))
                    or not proof.get('constraints')):
                raise ValueError('技术操作超出授权或缺具体约束')
        if phase == 'additional_repair':
            attempts = proof.get('attempt_ids')
            allowed_attempts = grant.get('additional_attempt_ids', {}).get(episode, {})
            if (not isinstance(attempts, dict) or set(attempts) != set(ids)
                    or any(not isinstance(attempts[p], list) or not attempts[p]
                           or len(set(attempts[p])) != len(attempts[p])
                           or not set(attempts[p]) <= set(allowed_attempts.get(p, [])) for p in ids)
                    or not proof.get('constraints')):
                raise ValueError('追加次数须绑定准确新attempt；不扩大原自动预算')
        if not isinstance(proof.get('artifacts'), list) or not proof['artifacts']:
            raise ValueError('决定缺准确成果')
        return []
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return ['AUTHORITY_HOLD:' + str(exc)]


def delegated_decisions(review, selected_ids, authority_ref, reviewer, evidence, root):
    expected = proposal(review['book_id'], review['episode_id'], review['items'], root)
    if review != expected or not isinstance(selected_ids, list) or not selected_ids or len(set(selected_ids)) != len(selected_ids) or not set(selected_ids) <= {i['item_id'] for i in review['items']}:
        raise ValueError('决定事项或版本不符')
    grant = json.loads(checked_file(Path(root), authority_ref).read_text())
    proofs = []
    for item in review['items']:
        if item['item_id'] not in selected_ids: continue
        proof = {k: v for k, v in item.items() if k not in {'item_id', 'summary'}}
        proof.update(status=DECIDED, source_kind='agent_decision', authority=authority_ref,
                     authority_constraints=grant.get('constraints'), reviewer=reviewer, evidence=evidence,
                     book_id=review['book_id'], episode_id=review['episode_id'],
                     review_event_id=review['event_id'], review_item_id=item['item_id'])
        errors = decision_errors(proof, root, review['book_id'], review['episode_id'])
        if errors: raise ValueError(';'.join(errors))
        proofs.append(proof)
    return proofs


def proposal(book, episode, items, root):
    if not book or not episode or not isinstance(items,list) or not items:
        raise ValueError('须有书话和准确审查事项')
    ids = set()
    for item in items:
        if not item.get('item_id') or item['item_id'] in ids or item.get('phase') not in PHASES:
            raise ValueError('审查事项ID或阶段无效')
        ids.add(item['item_id'])
        panels = item.get('panel_ids')
        if not isinstance(panels,list) or not panels or len(set(panels))!=len(panels) or any(not isinstance(x,str) or not x for x in panels):
            raise ValueError('须列准确格号范围')
        if not item.get('artifacts') or not item.get('summary'):
            raise ValueError('审查事项缺准确成果或具体方案')
        for ref in item['artifacts']: checked_file(Path(root),ref)
        if item['phase'] in {'technical_operations','additional_repair'} and not item.get('constraints'):
            raise ValueError('操作/追加授权须有明确约束')
        if item['phase']=='technical_operations' and (not item.get('operations') or not set(item['operations'])<=OPERATIONS):
            raise ValueError('技术操作类型无效')
        if item['phase']=='additional_repair' and 'attempt_ids' in item:
            attempts=item['attempt_ids']
            if (not isinstance(attempts,dict) or set(attempts)!=set(panels)
                    or any(not isinstance(v,list) or not v or any(not isinstance(a,str) or not a.strip() for a in v)
                           or len(set(v))!=len(v) for v in attempts.values())):
                raise ValueError('追加attempt须逐格列出不重复的具体新尝试；不能丢失次数绑定')
    body = {'policy':POLICY,'book_id':book,'episode_id':episode,'items':items}
    body['event_id'] = hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return body


def approvals(review, accepted_item_ids, message, root):
    expected = proposal(review['book_id'],review['episode_id'],review['items'],root)
    if review != expected: raise ValueError('审查事项或版本已变化，不能沿用原问题')
    if (message.get('source_kind')!='user_message' or not message.get('quote','').strip()
            or not message.get('source_locator','').strip()):
        raise ValueError('须绑定真实用户原文和来源；不能由配置授予批准')
    ids = accepted_item_ids
    if not isinstance(ids,list) or not ids or len(set(ids))!=len(ids) or not set(ids)<={i['item_id'] for i in review['items']}:
        raise ValueError('只允许明确选中的准确事项，不从B推导包批准')
    proofs = []
    for item in review['items']:
        if item['item_id'] not in ids: continue
        proof = {**message,'status':'APPROVED','book_id':review['book_id'],
                 'episode_id':review['episode_id'],'panel_ids':item['panel_ids'],
                 'artifacts':item['artifacts'],'phase':item['phase'],
                 'review_event_id':review['event_id'],'review_item_id':item['item_id']}
        for field in ('constraints','operations','attempt_ids'):
            if field in item: proof[field]=item[field]
        proofs.append(proof)
    return proofs


def question_action(review, pending):
    found = next((x for x in pending if x.get('event_id')==review['event_id'] and x.get('status')=='PENDING'),None)
    return {'action':'KEEP_PENDING' if found else 'ASK_READY_ITEMS',
            'event_id':review['event_id'],'question_id':found.get('question_id') if found else None}


def bundle_proposal(state, root, bundle_ref):
    """Bind the already-written package; no circular self-hash in the package."""
    from execution_contract import extra_basis_refs
    packet=json.loads(checked_file(Path(root),bundle_ref).read_text())
    if packet.get('policy')!='generation_review_package_v1' or packet.get('scope')!='episode':
        raise ValueError('须为整话候选生图包')
    if any(packet.get(k)!=state.get(k) for k in ('book_id','episode_id','visual_basis','shot_manifest')):
        raise ValueError('候选包与当前本话基准版本不一致')
    items=[]
    designs=packet.get('design_review_panel_ids',packet['panel_ids'])
    ready=packet.get('approval_panel_ids',packet['panel_ids'])
    if designs:items.append({'item_id':'B','phase':'shot_design','panel_ids':designs,
        'artifacts':[state['visual_basis'],state['shot_manifest'],*extra_basis_refs(state)],
        'summary':'批准所列格号的镜头、比例和实际语义方案'})
    if ready:items.append({'item_id':'PACKAGE','phase':'generation_package','panel_ids':ready,
        'artifacts':[bundle_ref,state['visual_basis'],state['shot_manifest']],
        'summary':'批准所列格号的实际输入与已冻结依赖补齐方案'})
    return proposal(state['book_id'],state['episode_id'],items,root)


def technical_errors(proof, root, book, episode, panel_id, operation, source_refs):
    from staged_workflow import approval_errors
    errors = approval_errors(proof,Path(root),source_refs,book,episode,phase='technical_operations',panel_ids=[panel_id])
    if not isinstance(proof,dict):return errors
    if proof.get('phase')!='technical_operations' or operation not in proof.get('operations',[]):
        errors.append('缺少本技术操作授权')
    if panel_id not in proof.get('panel_ids',[]) or not proof.get('constraints'):
        errors.append('技术授权格号或约束不符')
    return errors


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True);p.add_argument('--proposal')
    p.add_argument('--state');p.add_argument('--bundle',help='生成合并B和包审查事项的本话相对包路径')
    p.add_argument('--selection',help='真实消息及accepted_item_ids JSON')
    p.add_argument('--pending',help='已有event_id/status/question_id数组')
    p.add_argument('--authority',help='已记录的真实用户委托文件，相对root；不从配置推断授权')
    p.add_argument('--reviewer');p.add_argument('--evidence')
    a=p.parse_args()
    if a.bundle:
        state=json.loads(Path(a.state).read_text());bundle_path=Path(a.root)/a.bundle
        from codex_reference_contract import digest
        review=bundle_proposal(state,a.root,{'path':a.bundle,'sha256':digest(bundle_path)})
    else:review=json.loads(Path(a.proposal).read_text())
    checked=proposal(review['book_id'],review['episode_id'],review['items'],a.root)
    if a.selection:
        if review!=checked:raise ValueError('须使用已展示的准确event_id')
        selection=json.loads(Path(a.selection).read_text())
        if a.authority:
            from codex_reference_contract import digest
            ref={'path':a.authority,'sha256':digest(Path(a.root)/a.authority)}
            result={'proofs':delegated_decisions(review,selection['accepted_item_ids'],ref,a.reviewer,a.evidence,a.root)}
        else:
            result={'proofs':approvals(review,selection['accepted_item_ids'],selection['message'],a.root)}
    else:
        pending=json.loads(Path(a.pending).read_text()) if a.pending else []
        result={'proposal':checked,**question_action(checked,pending)}
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
