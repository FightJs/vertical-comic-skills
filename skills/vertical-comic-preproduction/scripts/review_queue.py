#!/usr/bin/env python3
"""Build a source-ordered review queue from persisted results; never image/user approval."""
import argparse,json
from pathlib import Path
from codex_reference_contract import read_json, checked_file,digest


def build_queue(state,root,batch,*,incremental=False,processed=None):
    from review_reuse import fingerprint
    from staged_workflow import qa_errors
    records={r['panel_id']:r for r in state['panels']};items=[];processed=processed or {}
    from scoped_inputs import half_view
    try:
        view=half_view(state,batch['batch_id'])
        shots=read_json(checked_file(root,view['shot_manifest'])).get('panels',[])
    except (OSError,ValueError,TypeError,KeyError):
        shots=[]
    anchors={p['panel_id'] for p in shots if p.get('calibration_anchor') or p.get('requires_state_review')}
    from scoped_inputs import STATE_DISPATCH,state_leads
    if state.get('state_dispatch_policy')==STATE_DISPATCH:
        anchors.update(state_leads([p for p in shots if p.get('panel_id') in batch['panel_ids']]))
    anchors.update(d for p in shots for d in p.get('generation_dependencies',[]))
    for pid in batch['panel_ids']:
        r=records[pid];status=r.get('status')
        if status not in {'GENERATED','VISUAL_PASS','USER_ACCEPTED','VISUAL_FAIL'}:continue
        image=checked_file(root,r.get('output'))
        action='REVIEW_SIX_DIMENSIONS' if status=='GENERATED' else 'DIAGNOSE_FAILED_IMAGE' if status=='VISUAL_FAIL' else 'VERIFY_RECORDED_QA'
        item={'panel_id':pid,'attempt_id':r.get('attempt_id'),'round_id':r.get('round_id'),'image':str(image),'image_sha256':digest(image),'action':action}
        if state.get('production_policy') == 'first_batch_production_v1' and status == 'VISUAL_FAIL':
            from production_decisions import load_decision
            try:
                _, decision, _, ref = load_decision(root, r, r['attempt_id'])
                if decision['action'] in {'defer_manual','stop_diagnose'}:
                    item.update(action='REUSE_RECORDED_PRODUCTION_DECISION', production_decision=ref)
                    if incremental: continue
            except (OSError, ValueError, TypeError, KeyError):
                pass
        item['priority']='DEPENDENCY_OR_STATE' if pid in anchors else 'NORMAL'
        if status in {'VISUAL_PASS','USER_ACCEPTED'}:
            try:
                errors=qa_errors(root,r)
                if not errors:
                    item.update(action='REUSE_CANDIDATE_CHECK_CURRENT_SCOPE',fingerprint=fingerprint(root,r),qa_report=r['qa_report'])
                    if incremental:continue
                else:item.update(action='REVIEW_REQUIRED',errors=errors)
            except (OSError,ValueError,TypeError,KeyError) as exc:item.update(action='REVIEW_REQUIRED',errors=[str(exc)])
        token={k:item.get(k) for k in ('attempt_id','image_sha256','action')}
        token['qa_report']=r.get('qa_report')
        item['review_token']=token
        # A cursor only deduplicates observations; it never proves a visual PASS.
        if processed.get(pid)==token:continue
        items.append(item)
    items.sort(key=lambda i:i['priority']!='DEPENDENCY_OR_STATE')
    return {'policy':'stream_review_queue_v1','batch_id':batch['batch_id'],'items':items,'status':'REVIEW_TASKS_ONLY','user_approval':'NOT_GRANTED'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',required=True);p.add_argument('--batch',required=True);p.add_argument('--write',required=True);p.add_argument('--incremental',action='store_true');a=p.parse_args()
    try:
        path=Path(a.state).resolve();root=path.parent.parent;state=json.loads(path.read_text(encoding='utf-8-sig'));plan=json.loads(checked_file(root,state['batch_plan']).read_text(encoding='utf-8-sig'));batch=next(b for b in plan['batches'] if b['batch_id']==a.batch)
        value=build_queue(state,root,batch,incremental=a.incremental);dest=Path(a.write).resolve();dest.relative_to(root)
        with dest.open('x',encoding='utf-8', newline='\n') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')
        print(json.dumps({'status':value['status'],'items':len(value['items']),'path':str(dest)},ensure_ascii=False));return 0
    except (OSError,ValueError,TypeError,KeyError,StopIteration) as exc:
        print(json.dumps({'status':'HOLD','errors':[str(exc)]},ensure_ascii=False));return 1

if __name__=='__main__':
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
