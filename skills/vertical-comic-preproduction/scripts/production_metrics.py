"""Read-only production metrics. Terminal events, attempts, files and QA are separate populations."""
from __future__ import annotations
import argparse,csv,json,hashlib
from collections import Counter
from datetime import datetime
from pathlib import Path

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def instant(s):
    try:
        value=datetime.fromisoformat(s.replace('Z','+00:00'))
        return value.timestamp() if value.tzinfo is not None else None
    except (ValueError,AttributeError,TypeError):return None

def union_seconds(windows):
    """Wall-clock coverage, not the sum of concurrent attempt durations."""
    merged=[]
    for start,end in sorted(windows):
        if not merged or start>merged[-1][1]:merged.append([start,end])
        else:merged[-1][1]=max(end,merged[-1][1])
    return sum(end-start for start,end in merged)

def _build(state_paths,*,native_events=None,verify_images=False,capacity=None):
    attempts={};panels={};warnings=[];sources=[];episodes=set();duplicates=0;diagnostics=Counter();windows=[];qa_windows=[];verified=set();declared=set();reads=[];conflicts=set()
    timings={k:[] for k in ('ready_to_submit','submit_to_return','return_to_save','save_to_qa','save_to_qa_registration')}
    edit_reviews=[]
    production_actions=Counter();delivery_outcomes=Counter();issue_classes=Counter();decision_errors=[]
    def referenced(root,ref):
        if not isinstance(ref,dict) or not isinstance(ref.get('path'),str):return None
        p=Path(ref['path']);p=p if p.is_absolute() else root/p
        return p if p.is_file() else None
    for sp in state_paths:
        sp=Path(sp).resolve();data=json.loads(sp.read_text(encoding='utf-8-sig'));root=sp.parent.parent
        eid=data.get('episode_id',data.get('episode',str(root)));book=data.get('book_id',data.get('book','UNKNOWN'))
        if (book,eid) in episodes:raise ValueError('每话只指定一个权威状态，禁止混算迁移RV：'+str(eid))
        episodes.add((book,eid));sources.append({'path':str(sp),'sha256':digest(sp)})
        if data.get('production_policy') == 'first_batch_production_v1':
            from production_decisions import load_decision, selected, outcome
            for row in data.get('panels', []):
                for aid in row.get('production_decisions', {}):
                    try:
                        _, d, _, _ = load_decision(root, row, aid)
                        production_actions[d['action']] += 1
                    except (ValueError, KeyError, TypeError, OSError) as exc: decision_errors.append(str(exc))
                try:
                    _, d, _, _ = selected(root, row)
                    delivery_outcomes[outcome(d)] += 1
                    issue_classes.update(str(i['category']) for i in d['issues'])
                except (ValueError, KeyError, TypeError, OSError): delivery_outcomes['INCOMPLETE'] += 1
        for current in data.get('panels',[]):
            pid=current['panel_id'];panels[(book,eid,pid)]=current
            history=[*(e['original_attempt'] for e in current.get('no_image_history',[])),*current.get('attempt_history',[]),current]
            for row in history:
                aid=row.get('attempt_id')
                if not aid:continue
                key=(book,eid,pid,aid)
                if key in attempts:
                    duplicates+=1
                    if attempts[key].get('output')!=row.get('output'):
                        warnings.append('同attempt输出冲突：'+str(key));conflicts.add(key)
                    else:attempts[key]={**attempts[key],**row}
                    continue
                attempts[key]=row
                image=referenced(root,row.get('output'))
                if row.get('output'):declared.add(key)
                if image:
                    if verify_images:
                        try:
                            from PIL import Image
                            with Image.open(image) as im:im.verify()
                            if digest(image)!=row['output'].get('sha256'):raise ValueError('图像哈希不符')
                            verified.add(key)
                        except (OSError,ValueError) as e:warnings.append(str(key)+':'+str(e))
                elif row.get('output'):warnings.append(str(key)+':所引用原图缺失')
                req=referenced(root,row.get('request_evidence') or row.get('call_evidence'))
                actual_request=False
                if req:
                    try:
                        d=json.loads(req.read_text(encoding='utf-8-sig'));actual_request=d.get('source_kind')=='observed_tool_call' and bool(d.get('source_locator'))
                    except (ValueError,OSError):pass
                if actual_request:reads.append(key)
                start,end=instant(row.get('submitted_at')),instant(row.get('returned_at'))
                if start is not None and end is not None and end>=start:windows.append((start,end))
                else:
                    # Missing times stay unavailable, not zero-duration service.
                    pass
                qa=instant(row.get('qa_completed_at'));saved=instant(row.get('saved_at'))
                if qa is not None and saved is not None and qa>=saved:qa_windows.append(qa-saved)
                stamps={'ready':instant(row.get('ready_at')),'submit':start,'return':end,'save':saved,'qa':qa,'qa_registered':instant(row.get('qa_recorded_at'))}
                for phase,a,b in [('ready_to_submit','ready','submit'),('submit_to_return','submit','return'),('return_to_save','return','save'),('save_to_qa','save','qa'),('save_to_qa_registration','save','qa_registered')]:
                    if stamps[a] is not None and stamps[b] is not None and stamps[b]>=stamps[a]:timings[phase].append((stamps[a],stamps[b]))
                qpath=referenced(root,row.get('qa_report'))
                if qpath and digest(qpath)==row['qa_report'].get('sha256'):
                    try:
                        document=json.loads(qpath.read_text(encoding='utf-8-sig'))
                        item=next(q for q in document.get('panels',[]) if q.get('panel_id')==pid and q.get('image_sha256')==row.get('output',{}).get('sha256'))
                        comparison=item.get('visual_evidence_review',{}).get('repair_comparison',{})
                        preserved=comparison.get('preserved_observations')
                        if (comparison.get('base_image_sha256') and comparison.get('clarity_status') in {'PASS','FAIL'}
                                and isinstance(preserved,dict) and preserved
                                and all(isinstance(v,dict) and v.get('status') in {'PASS','FAIL'} for v in preserved.values())):
                            edit_reviews.append(comparison['clarity_status']=='FAIL' or any(v['status']=='FAIL' for v in preserved.values()))
                    except (ValueError,TypeError,AttributeError,StopIteration):warnings.append(str(key)+':QA统计结构无法核对')
                if row.get('status')=='VISUAL_FAIL':
                    diagnosis=row.get('failure_diagnosis')
                    if isinstance(diagnosis,dict) and diagnosis.get('layer'):diagnostics[str(diagnosis['layer'])]+=1
                    for reason in row.get('visual_failure_reasons',[]):diagnostics[str(reason).split(':')[0]]+=1
    first=[(k,r) for k,r in attempts.items() if r.get('round_id')==1 and k not in conflicts]
    reviewed=[(k,r) for k,r in first if r.get('status') in {'VISUAL_PASS','VISUAL_FAIL'}]
    first_by_panel={}
    for k,r in first:first_by_panel.setdefault(k[:3],[]).append(r)
    unambiguous=[v[0] for v in first_by_panel.values() if len(v)==1]
    panel_reviewed=[r for r in unambiguous if r.get('status') in {'VISUAL_PASS','VISUAL_FAIL'}]
    ambiguous=[list(k) for k,v in first_by_panel.items() if len(v)>1]
    count_pass=sum(r.get('status')=='VISUAL_PASS' for _,r in reviewed)
    final_pass=sum(r.get('status')=='VISUAL_PASS' for r in panels.values())
    terminal=None
    if native_events:
        with Path(native_events).open(encoding='utf-8-sig') as f:events=list(csv.DictReader(f))
        keys={(r.get('lane'),r.get('id')) for r in events if r.get('id')}
        terminal={'source':str(Path(native_events).resolve()),'rows':len(events),'unique_lane_event_ids':len(keys),'duplicate_rows':len(events)-len(keys),'by_status':dict(Counter(r.get('status','UNKNOWN') for r in events)),'successful_images':None,'note':'完成事件不证明成功返回PNG，不与状态attempt相加，也不证明服务计费量'}
    utilisation=None
    if capacity is not None:
        if type(capacity) is not int or capacity<=0:raise ValueError('capacity须为真实核定正整数')
        if windows:
            span=max(e for _,e in windows)-min(s for s,_ in windows)
            utilisation=sum(e-s for s,e in windows)/(span*capacity) if span else None
            if utilisation is not None and utilisation>1:warnings.append('观察在途率超过容量，核查时间/容量；不截断掩盖异常')
    current_statuses=dict(Counter(r.get('status','UNKNOWN') for r in panels.values()))
    return {'policy':'production_metrics_v1','read_only':True,'sources':sources,'panels':len(panels),'current_record_statuses':current_statuses,'visual_pass_panels_recorded':final_pass,'user_accepted_panels':None,
        'unique_attempt_records':len(attempts),'duplicate_attempt_records_ignored':duplicates,'observed_request_evidence_records':len(set(reads)),
        'declared_output_attempts':len(declared),'verified_original_image_attempts':len(verified-conflicts) if verify_images else None,'conflicting_attempts_excluded_from_verified_count':[list(k) for k in sorted(conflicts)],
        'first_round':{'attempts_recorded':len(first),'reviewed_records':len(reviewed),'pass_records':count_pass,'pass_rate_among_reviewed':count_pass/len(reviewed) if reviewed else None,'unreviewed_or_unknown':len(first)-len(reviewed),'rate_population':'登记为round_id=1的尝试，不一定是独立格的真正首次请求','ambiguous_first_round_panels':ambiguous,'unambiguous_panel_pass_rate':sum(r.get('status')=='VISUAL_PASS' for r in panel_reviewed)/len(panel_reviewed) if panel_reviewed else None,'unambiguous_reviewed_panels':len(panel_reviewed)},
        'recorded_attempts_per_visual_pass_panel':len(attempts)/final_pass if final_pass else None,
        'confirmed_requests_per_accepted_panel':None,
        'diagnostic_mentions_not_disjoint_error_counts':dict(diagnostics),'native_terminal_events':terminal,
        'timing':{'complete_request_windows':len(windows),'request_window_seconds_sum_not_wall_time':sum(e-s for s,e in windows) if windows else None,'observed_span_capacity_utilisation':utilisation,'save_to_qa_seconds_sum_not_active_review_time':sum(qa_windows) if qa_windows else None,
                  'phase_windows':{k:{'samples':len(v),'sum_seconds_not_wall_time':sum(e-s for s,e in v) if v else None,'union_seconds':union_seconds(v) if v else None} for k,v in timings.items()},
                  'timestamp_coverage':{key:sum(instant(row.get(key)) is not None for row in attempts.values()) for key in ('ready_at','submitted_at','returned_at','saved_at','qa_completed_at','qa_recorded_at')},
                  'note':'各阶段并集分别报告，不相加冒充互斥总耗时；ready_at是实际观察就绪，qa_recorded_at是通过校验的QA登记时间，不冒充人工审图结束或主动工作时长；缺失保持未知。'},
        'edit_regression':{'complete_structured_comparisons':len(edit_reviews),'regressed':sum(edit_reviews),'rate':sum(edit_reviews)/len(edit_reviews) if edit_reviews else None,'population':'有图像hash绑定QA且清晰度与保留区域均有明确结论的编辑结果'},
        'unavailable':['服务计费请求总量及原生事件与attempt的完整对应','用户最终批准数量（不能由VISUAL_PASS推导）','准备/人工/总控握手/依赖等待的互斥区间','局部编辑新增错误率（缺少前后错误分类时不推断）'],
        'first_batch_decisions':{'recorded_actions':dict(production_actions),
            'adopted_problem_class_mentions':dict(issue_classes),
            'declared_outcomes_before_final_gate':dict(delivery_outcomes),
            'decision_evidence_errors':decision_errors,'actual_user_question_count':None,
            'actual_repeat_ineffective_call_count':None,
            'note':'决定数不是实际提问/调用数，采用问题统计不代表最终交付门禁通过；缺事件数据不填0'},
        'warnings':warnings,'limitations':'状态比率为登记口径，历史未保留的调用和失败不可补造；verify-images仅核验原图格式和哈希，不授予视觉通过。'}

def build(state_paths,*,native_events=None,verify_images=False,capacity=None,delivery_identity=None):
    state_paths=list(state_paths)
    result=_build(state_paths,native_events=native_events,verify_images=verify_images,capacity=capacity)
    from runtime_pipeline import metrics as pipeline_metrics
    result['pipeline_timing']=pipeline_metrics(state_paths)
    if delivery_identity is not None:
        from delivery_contract import load_identity,capacity_summary
        from production_progress import source_order,Records
        value=load_identity(delivery_identity)
        if set(value['states'])!={str(Path(p).resolve()) for p in state_paths}:
            raise ValueError('DELIVERY_SCOPE_HOLD:容量统计范围与交付任务不符')
        total=sum(len(source_order(json.loads(Path(p).read_text(encoding='utf-8-sig')),Path(p).parent.parent,Records())) for p in state_paths)
        result['delivery_capacity']=capacity_summary(value['states'],total)
        result['delivery_capacity'].update(max_file_bytes=value['max_file_bytes'],package_mode=value['package_mode'])
    return result


def draft_metrics(paths, atlas_paths=None):
    """Read explicit actual receipts only, no periodic scanning or inferred timing."""
    if not paths and not atlas_paths: return None
    receipts={};warnings=[]
    for path in paths or []:
        try:
            value=json.loads(Path(path).read_text(encoding='utf-8-sig'))
            if value.get('policy')!='panel_derivation_v1': raise ValueError('非草稿派生记录')
            key=hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            receipts[key]=value
        except (OSError,ValueError,TypeError) as exc: warnings.append(str(path)+':'+str(exc))
    compiled=reused=repeat=0;seen=set();elapsed=[]
    for value in receipts.values():
        for row in value.get('panels',[]):
            if row.get('error'): continue
            if row.get('reused'): reused+=1
            elif row.get('artifacts'):
                compiled+=1;token=(value['book_id'],value['episode_id'],row['panel_id'],row['input_key'])
                if token in seen: repeat+=1
                seen.add(token)
        timing=value.get('metrics',{}).get('elapsed_seconds')
        if isinstance(timing,(int,float)): elapsed.append(timing)
    atlas={}
    for path in atlas_paths or []:
        try:
            value=json.loads(Path(path).read_text(encoding='utf-8-sig'))
            if value.get('derivation_policy')!='faithful_atlas_v1' or type(value.get('cache_reused')) is not bool or not value.get('observation_id'):
                raise ValueError('非实际图集操作回执')
            atlas[value['observation_id']]=value
        except (OSError,ValueError,TypeError) as exc: warnings.append(str(path)+':'+str(exc))
    return {'receipt_samples':len(receipts),'compiled_panels':compiled if receipts else None,'reused_panels':reused if receipts else None,
            'repeated_compilations_same_input':repeat if receipts else None,'observed_derivation_seconds_sum_not_wall_time':sum(elapsed) if elapsed else None,
            'warnings':warnings,'review_reuse_count':None,
            'atlas_created_count':sum(not r['cache_reused'] for r in atlas.values()) if atlas else None,
            'atlas_reuse_count':sum(r['cache_reused'] for r in atlas.values()) if atlas else None,
            'note':'只统计提供的实际派生记录；不推算未记录的设计/审核/服务耗时，不代表生图提速'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',action='append',required=True);p.add_argument('--native-events');p.add_argument('--verify-images',action='store_true');p.add_argument('--capacity',type=int);p.add_argument('--draft-receipt',action='append');p.add_argument('--atlas-receipt',action='append');p.add_argument('--delivery-identity');a=p.parse_args()
    value=build(a.state,native_events=a.native_events,verify_images=a.verify_images,capacity=a.capacity,delivery_identity=a.delivery_identity)
    value['draft_preparation']=draft_metrics(a.draft_receipt,a.atlas_receipt)
    from runtime_clock import locate, status as clock_status
    clocks = {locate(path) for path in a.state} - {None}
    value['task_runtime_clocks'] = [dict(directory=str(d), **clock_status(d)) for d in sorted(clocks)]
    print(json.dumps(value,ensure_ascii=False,indent=2))
if __name__=='__main__':
    from platform_io import configure_stdio
    configure_stdio()
    main()
