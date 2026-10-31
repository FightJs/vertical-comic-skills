"""Replay observed review follow-ups without repeating QA or inventing permission."""
import copy, hashlib, json
from pathlib import Path
from codex_reference_contract import read_json, checked_file, digest
from authority_updates import _write_once, _encoded

POLICY='observed_followup_v1'

def operation_id(proposal):
    return hashlib.sha256(_encoded(proposal)).hexdigest()

def barrier_info(state, root, panel_id):
    shots=read_json(checked_file(root,state['shot_manifest']))
    panels=shots.get('panels',[])
    seen=set();barriers={}
    for i,p in enumerate(panels):
        keys=set(p.get('visual_state_keys',[]));new=keys-seen;seen.update(keys)
        if p.get('requires_state_review') or p.get('calibration_anchor') or (i and new):
            barriers[p['panel_id']]={'required':bool(p.get('requires_state_review') or p.get('calibration_anchor') or
                state.get('state_dispatch_policy')!='ordinary_state_parallel_v1' or p.get('state_review_policy','user_required')=='user_required'),
                'policy':p.get('state_review_policy','user_required'),
                'affected_panel_ids':[q['panel_id'] for q in panels[i+1:] if
                    panel_id in q.get('generation_dependencies',[]) or set(q.get('visual_state_keys',[])) & (new or keys)]}
    return barriers.get(panel_id,{'required':False,'affected_panel_ids':[]})

def available_authorities(state,root,panel_id):
    """Discover delegation only through existing registered proof references."""
    if not state.get('approval_index'):return []
    entries=read_json(checked_file(root,state['approval_index'])).get('entries',[])
    refs=[]
    from review_policy import decision_errors
    for entry in entries:
        proof=read_json(checked_file(root,entry['approval']))
        authority=proof.get('authority')
        if not authority or authority in refs:continue
        grant=read_json(checked_file(root,authority))
        candidate={'status':'AGENT_DECIDED_UNDER_USER_AUTHORITY','source_kind':'agent_decision',
            'reviewer':'CAPABILITY_CHECK_ONLY','evidence':'not an actual review',
            'authority':authority,'authority_constraints':grant.get('constraints'),
            'book_id':state['book_id'],'episode_id':state['episode_id'],'phase':'state_review',
            'panel_ids':[panel_id],'artifacts':[state['visual_basis'],state['shot_manifest']]}
        if not decision_errors(candidate,root,state['book_id'],state['episode_id']):refs.append(authority)
    return refs

def follow(path, panel_id, operation):
    path=Path(path);root=path.parent.parent;state=read_json(path)
    row=next(r for r in state['panels'] if r['panel_id']==panel_id)
    saved=row.get('review_submission')
    if not saved or saved['operation_id']!=operation:raise ValueError('REVIEW_FOLLOWUP_CHANGED')
    observation=saved.get('state_review');result={'status':'FOLLOWUP_COMPLETE','image_calls':0}
    if observation:
        if not isinstance(observation,dict) or set(observation)-{'observed','verdict','authority'}:
            raise ValueError('STATE_REVIEW_OBSERVATIONS_ONLY')
        if observation.get('verdict')!='PASS' or row['status']!='VISUAL_PASS' or not str(observation.get('observed','')).strip():
            raise ValueError('STATE_REVIEW_ACTUAL_PASS_REQUIRED')
        info=barrier_info(state,root,panel_id)
        if info['required']:
            from review_policy import proposal,delegated_decisions
            review=proposal(state['book_id'],state['episode_id'],[{'item_id':panel_id+'-state',
                'phase':'state_review','panel_ids':[panel_id],
                'artifacts':[state['visual_basis'],state['shot_manifest'],row['output']],
                'summary':observation['observed']}],root)
            proof=delegated_decisions(review,[panel_id+'-state'],observation['authority'],saved['reviewer'],
                observation['observed']+'; QA: '+row['qa_report']['path'],root)[0]
            ref=_write_once(root,'state-review',_encoded(proof))
            entries=read_json(checked_file(root,state['approval_index'])).get('entries',[]) if state.get('approval_index') else []
            if not any(e.get('approval')==ref for e in entries):
                from authority_updates import update_approvals
                update_approvals(path,digest(path),register=[{'approval':ref,'phase':'state_review','panel_ids':[panel_id]}])
            result['state_review']={'status':'REGISTERED','approval':ref,**info}
    elif barrier_info(state,root,panel_id)['required']:
        result['state_review']={'status':'OBSERVATION_REQUIRED',**barrier_info(state,root,panel_id)}
    decision_ref=row.get('production_decisions',{}).get(row['attempt_id'])
    if decision_ref:
        decision=read_json(checked_file(root,decision_ref))
        if decision.get('action') in {'local_edit','regenerate','rebuild_inputs','crop_candidate'}:
            from repair_routes import plan
            from stage_deadlines import checkpoint
            result['repair_budget']=checkpoint(path,'repair',panel_id,state=state)
            result['repair']=plan(decision,row)
            result['repair']['diagnosis']=decision_ref
            result['repair']['panel_id']=panel_id
            result['repair']['source_attempt_id']=row['attempt_id']
            request={**result['repair'],'policy':'observed_repair_request_v1','qa_report':row['qa_report'],
                'image':row['output'],'package_manifest':row['package_manifest'],
                'preserve_constraints':decision.get('preserve_constraints',[]),'fix_now':decision.get('fix_now',[]),
                'issues':decision.get('issues',[]),'new_attempt_authorized':False}
            result['repair_request']=_write_once(root,'repair-request',_encoded(request))
            # The existing scoped input/repair-authorize path consumes this exact request.
    return result

def submit(path, proposal):
    from review_pipeline import save
    path=Path(path);state=read_json(path)
    if state.get('review_followup_policy')!=POLICY:return save(path,digest(path),proposal)
    op=operation_id(proposal);row=next(r for r in state['panels'] if r['panel_id']==proposal['panel_id'])
    previous=row.get('review_submission')
    if previous and previous['operation_id']==op:
        if row['attempt_id']!=proposal['attempt_id'] or previous['qa_report']!=row.get('qa_report'):
            raise ValueError('REVIEW_REPLAY_VERSION_CHANGED')
        result={'status':'QA_AND_DECISION_SAVED','replayed':True,'qa_report':row['qa_report'],'image_calls':0}
    else:
        result=save(path,digest(path),proposal)
    try:result['followup']=follow(path,proposal['panel_id'],op)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        result['followup']={'status':'HOLD','error':str(exc),'retry':'REPLAY_SAME_OBSERVATION','image_calls':0}
    return result
