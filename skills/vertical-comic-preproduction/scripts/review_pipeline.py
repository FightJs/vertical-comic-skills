"""Save observed QA, decisions and adoption in one CAS; revise without rewriting history."""
from pathlib import Path
import argparse,copy,json,time
from codex_reference_contract import read_json,checked_file,digest,file_session,verify_read_snapshot,_FILE_SESSION
from authority_updates import _write_once,_encoded,state_write_lock
from dispatch_publication import require_legacy
from platform_io import atomic_json
from runtime_pipeline import POLICY,record

PROTECTED={'expected','policy','panel_id','image','image_sha256','image_size','source_manifest_sha256',
           'reference_files','traits','memory_id','rule_version','rule_sha256','rule_signature',
           'expectations_sha256','context_sha256','background_sha256','id','target','criterion'}
ROOT_FIELDS={'dimension_review','style_review','memory_review','visual_evidence_review','notes',
             'camera_match','shot_scale_match','background_view_match','body_crop_match',
             'required_visible_information_preserved','no_extra_offscreen_characters','composition_match'}
OBSERVED_STRUCTURES={'view','visibility_observations','detail_visibility_observations',
                     'appearance_observations','continuity_comparisons','preserved_observations',
                     'fixed_observations','coordinate_observations','retained','omitted'}

def overlay(target,patch,reviewer,path=''):
    """Accept observations only. Templates own identity, paths and expected facts."""
    if not isinstance(patch,dict) or not isinstance(target,dict):raise ValueError('QA_FIELD:'+path+': object required')
    for key,value in patch.items():
        at=path+'/'+str(key)
        if key in PROTECTED:raise ValueError('QA_FIELD:'+at+': bound field is filled by the tool')
        if not path and key not in ROOT_FIELDS:raise ValueError('QA_FIELD:'+at+': unknown observation field')
        if key=='reviewed':
            if '/memory_review/' not in path or value is not True:raise ValueError('QA_FIELD:'+at+': expected true on a matched rule')
            target['decision']='APPLIED';continue
        if key=='decision' and '/memory_review/' in path and value not in {'APPLIED','USER_EXCEPTION'}:
            raise ValueError('QA_FIELD:'+at+': use reviewed:true; APPLIES describes applicability, not a QA application')
        if key not in target:raise ValueError('QA_FIELD:'+at+': not in the current QA template')
        old=target[key]
        if key in OBSERVED_STRUCTURES:
            # These are reviewer-created image observations, not approved input
            # expectations. Original validators still verify exact IDs/coverage.
            target[key]=copy.deepcopy(value);continue
        if isinstance(value,dict):
            if isinstance(old,list):
                for index,patch_item in value.items():
                    if not str(index).isdigit() or int(index)>=len(old):raise ValueError('QA_FIELD:'+at+': invalid review index')
                    overlay(old[int(index)],patch_item,reviewer,at+'/'+str(index))
            else:overlay(old,value,reviewer,at)
        elif isinstance(old,(dict,list)) and key not in {'continuity_comparisons','view'}:
            raise ValueError('QA_FIELD:'+at+': patch individual observations')
        else:target[key]=copy.deepcopy(value)
    if 'reviewer' in target and patch:target['reviewer']=reviewer

def save(state_path,expected_state,proposal):
    """No CAS retries; a conflict cannot silently overwrite a peer's review."""
    if _FILE_SESSION.get() is not None:raise ValueError('WRITE_REQUIRES_OWN_READ_TRANSACTION')
    path=Path(state_path).resolve();root=path.parent.parent;started=time.monotonic()
    # Copy actual caller observations; never default UNREVIEWED fields to PASS.
    proposal=copy.deepcopy(proposal)
    if any(not isinstance(proposal.get(k),str) or not proposal[k].strip() for k in ('panel_id','attempt_id','reviewer','reason')):
        raise ValueError('QA_FIELD: panel_id/attempt_id/reviewer/reason required')
    if proposal.get('verdict') not in {'PASS','FAIL'}:raise ValueError('QA_FIELD: observed verdict must be PASS or FAIL')
    viewing=proposal.get('observed_review_seconds')
    if viewing is not None and (type(viewing) not in (int,float) or not 0<=viewing<86400):
        raise ValueError('QA_FIELD: observed_review_seconds invalid')
    if 'adopt' in proposal and type(proposal['adopt']) is not bool:raise ValueError('QA_FIELD: adopt must be boolean')
    with file_session() as initial_snapshot:
        state=read_json(path);require_legacy(state)
        if state.get('runtime_pipeline_policy')!=POLICY:raise ValueError('PIPELINE_NOT_ENABLED: preserve frozen legacy runtime')
        if digest(path)!=expected_state:raise ValueError('STATE_CHANGED')
        original=next((r for r in state['panels'] if r['panel_id']==proposal['panel_id']),None)
        if original is None or original['attempt_id']!=proposal['attempt_id'] or original.get('status') not in {'GENERATED','VISUAL_PASS','VISUAL_FAIL'}:
            raise ValueError('QA_ATTEMPT_CHANGED: only the current saved attempt may be reviewed; UNKNOWN and old attempts remain untouched')
        if proposal.get('base_qa')!=original.get('qa_report'):
            raise ValueError('QA_REVISION_CHANGED: base_qa must match the exact current QA reference')
        template_ref=original.get('qa_report') or proposal.get('qa_template')
        if not template_ref:raise ValueError('QA_TEMPLATE_REQUIRED: use production_runtime review --prepare-qa first')
        template=read_json(checked_file(root,template_ref));items=template.get('panels',[])
        if len(items)!=1 or items[0].get('panel_id')!=original['panel_id']:raise ValueError('QA_TEMPLATE_SCOPE')
        if template.get('source_manifest_sha256')!=original['package_manifest']['sha256'] or items[0].get('image_sha256')!=original['output']['sha256']:
            raise ValueError('QA_TEMPLATE_CHANGED: template is not bound to the current saved image/package')
        from production_decisions import findings
        previous_findings=findings(items[0])
    overlay(items[0],proposal.get('observations',{}),proposal['reviewer'])
    # Observation views refer to this actual image; comparison records bind
    # the exact adopted predecessor. The reviewer supplies observations, not hashes.
    def bind_view(value):
        if isinstance(value,dict):
            if 'image_sha256' in value and value['image_sha256'] is None:
                value['image_sha256']=original['output']['sha256']
            for child in value.values():bind_view(child)
        elif isinstance(value,list):
            for child in value:bind_view(child)
    bind_view(items[0])
    comparisons=items[0].get('visual_evidence_review',{}).get('continuity_comparisons',[])
    for comparison in comparisons:
        prior=next((r for r in state['panels'] if r['panel_id']==comparison.get('panel_id')),None)
        if prior is not None:
            image=prior.get('output')
            if prior.get('adoption'):
                from production_decisions import selected
                image=selected(root,prior)[0].get('output')
            comparison['image']=image
    # Both execution and image identity are always copied from the observed run.
    template['source_manifest_sha256']=original['package_manifest']['sha256']
    items[0]['image_sha256']=original['output']['sha256']
    qa_ref=_write_once(root,'qa-review',_encoded(template))
    with file_session() as snapshot:
        if digest(path)!=expected_state:raise ValueError('STATE_CHANGED')
        if read_json(path)!=state:raise ValueError('STATE_CHANGED')
        checked_file(root,template_ref)
        for comparison in comparisons:
            if comparison.get('image'):checked_file(root,comparison['image'])
        new=copy.deepcopy(state);row=next(r for r in new['panels'] if r['panel_id']==original['panel_id'])
        row['qa_report']=qa_ref;row['status']='VISUAL_'+proposal['verdict']
        checked_file(root,row['output']);checked_file(root,row['package_manifest'])
        if proposal['verdict']=='FAIL':
            diagnosis=proposal.get('failure_diagnosis',original.get('failure_diagnosis'))
            if not isinstance(diagnosis,dict):raise ValueError('QA_FIELD: failure_diagnosis requires observed layer and evidence')
            row['failure_diagnosis']={**diagnosis,'reviewer':proposal['reviewer']}
        else:row.pop('failure_diagnosis',None)
        from batch_round import attempt_errors
        errors=attempt_errors(new,root,row)
        if errors:raise ValueError('QA_VALIDATION: '+';'.join(errors))
        pending=[]
        if proposal['verdict']=='PASS' and state.get('visual_evidence_policy'):
            from visual_evidence import comparison_errors
            packet=read_json(checked_file(root,row['package_manifest']))
            pending=comparison_errors(packet['panels'][0],items[0],{r['panel_id']:r for r in new['panels']},root)
        row['quality_review']={'status':proposal['verdict'],'qa_report':qa_ref,'pending_comparisons':pending}
        # Single-image quality and comparison readiness are distinct. A picture
        # awaiting comparisons cannot become a qualified production reference.
        if pending:row['status']='GENERATED'
        from production_decisions import decision_errors,selected
        old_decision=original.get('production_decisions',{}).get(row['attempt_id'])
        supplied=proposal.get('decision')
        if supplied is not None:
            if not isinstance(supplied,dict) or set(supplied)&{'policy','panel_id','attempt_id','image','qa_report','reviewer'}:
                raise ValueError('QA_FIELD: tool fills decision identity and references')
            decision=copy.deepcopy(supplied)
        elif old_decision:
            if previous_findings!=findings(items[0]):raise ValueError('QA_DECISION: changed findings require an updated handling decision')
            decision=read_json(checked_file(root,old_decision))
        else:decision=None
        decision_ref=None
        if decision is not None:
            decision.update(policy='first_batch_production_v1',panel_id=row['panel_id'],attempt_id=row['attempt_id'],
                            image=row['output'],qa_report=qa_ref,reviewer=proposal['reviewer'])
            errors=decision_errors(decision,{**row,'status':'VISUAL_'+proposal['verdict']},items[0])
            if errors:raise ValueError('QA_DECISION: '+';'.join(errors))
            # Publish after ending the read transaction; new paths are never
            # mistaken for previously missing dependencies of this validation.
        revisions=row.setdefault('qa_revisions',[])
        revisions.append({'qa_report':original.get('qa_report'),'status':original['status'],
                          'decision':old_decision,'reason':proposal['reason'],'reviewer':proposal['reviewer']})
        old_adoption=original.get('adoption',{})
        adopt=proposal.get('adopt',old_adoption.get('attempt_id')==row['attempt_id'])
        if adopt and decision is None:raise ValueError('QA_DECISION: adoption requires an observed decision')
    if decision is not None:
        decision_ref=_write_once(root,'qa-decision',_encoded(decision))
        row.setdefault('production_decisions',{})[row['attempt_id']]=decision_ref
        if adopt:
            row['adoption']={'attempt_id':row['attempt_id'],'decision':decision_ref,
                             'reason':proposal.get('adoption_reason',old_adoption.get('reason',proposal['reason']))}
            new.setdefault('delivery_materials',{})[row['panel_id']]={
                'attempt_id':row['attempt_id'],'image':row['output'],'qa_report':qa_ref,
                'decision':decision_ref,'issues':copy.deepcopy(decision['issues']),
                'quality_status':proposal['verdict'],'pending_comparisons':pending,
                'status':'MATERIALS_ONLY_NOT_FINAL_DELIVERY'}
    invalidated=[]
    if qa_ref!=original.get('qa_report') and new.get('delivery_review'):
        invalidated.append(new.pop('delivery_review'))
        new.setdefault('delivery_review_history',[]).extend(invalidated)
    # Final decisions bind exact old artifacts, so no final approval is re-signed.
    from execution_timing import observe
    row.pop('qa_recorded_at',None);row.get('timing_observations',{}).pop('qa_recorded_at',None)
    observe(new,row,'qa_registered')
    validated=time.monotonic()
    with state_write_lock(path):
        acquired=time.monotonic();verify_read_snapshot(initial_snapshot);verify_read_snapshot(snapshot)
        if digest(path)!=expected_state:raise ValueError('STATE_CHANGED')
        history=path.parent/'runtime_history';history.mkdir(exist_ok=True)
        old=history/(expected_state+'.json')
        if not old.exists():old.write_bytes(path.read_bytes())
        atomic_json(path,new);written=time.monotonic()
    segments={'review_validation':validated-started,'lock_wait':acquired-validated,
              'lock_hold':written-acquired,'registration_total':written-started}
    # Caller may supply actual viewing duration, never derive it from queue delay.
    if viewing is not None:segments['observed_image_review']=viewing
    result={'status':'QA_AND_DECISION_SAVED','panel_id':row['panel_id'],'qa_report':qa_ref,
            'decision':decision_ref,'pending_comparisons':pending,'invalidated_delivery_reviews':invalidated,
            'state_sha256':digest(path),'segments_seconds':segments,'image_calls':0,'user_approval':'NOT_GRANTED'}
    try:result['metric']=record(path,'qa-save',segments,panel_ids=[row['panel_id']])
    except OSError as exc:result['timing_record_error']=str(exc)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',required=True)
    p.add_argument('--expected-state-sha256',required=True);p.add_argument('--observations',required=True)
    a=p.parse_args()
    try:result=save(a.state,a.expected_state_sha256,read_json(Path(a.observations)))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'HOLD','error':str(exc),'image_calls':0},ensure_ascii=False));return 1
    print(json.dumps(result,ensure_ascii=False));return 0

if __name__=='__main__':
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
