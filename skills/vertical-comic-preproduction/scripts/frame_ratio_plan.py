"""Episode-wide, source-bound frame proportions; half windows do not reset quotas."""
from codex_reference_contract import read_json, resolve_path
import argparse
import json
import re
from collections import Counter
from pathlib import Path
from codex_reference_contract import checked_file

POLICY = 'content_balanced_ratios_v1'
ALLOWED = ('9:16', '3:4', '4:5', '1:1', '5:4', '16:9')
PORTRAIT = ALLOWED[:3]

def enabled(data):
    return data.get('frame_ratio_policy') == POLICY

def execution_block(panel):
    return f"画幅比例：{panel['frame_ratio']}；按本格批准比例构图，不得默认统一为9:16或其他固定画幅；保留批准裁切与必显信息。"

def statistics(rows):
    n=len(rows);counts=Counter(p.get('frame_ratio') for p in rows)
    portraits=sum(counts[r] for r in PORTRAIT)
    return {'panel_count':n,'counts':{r:counts[r] for r in ALLOWED},'portrait_count':portraits,
            'minimum_portrait_count':3*n//4+1 if n else 0,
            'portrait_fraction':portraits/n if n else None,
            'repeated_adjacent_pairs':[[a['panel_id'],b['panel_id']] for a,b in zip(rows,rows[1:]) if a.get('frame_ratio')==b.get('frame_ratio')],
            'nonportrait_positions':[i+1 for i,p in enumerate(rows) if p.get('frame_ratio') not in PORTRAIT]}

def distribution_errors(rows):
    if not rows:return ['RATIO_PLAN_HOLD:全话比例计划为空']
    errors=[];stats=statistics(rows);n=len(rows);counts=stats['counts']
    if any(p.get('frame_ratio') not in ALLOWED for p in rows):errors.append('RATIO_PLAN_HOLD:比例须从9:16、3:4、4:5、1:1、5:4、16:9选择')
    if n>1 and len({p.get('frame_ratio') for p in rows})<2:errors.append('RATIO_PLAN_HOLD:不允许全话通体同一比例')
    if stats['portrait_count']*4<=3*n:errors.append(f"RATIO_PLAN_HOLD:竖版占比须严格大于3/4，当前{stats['portrait_count']}/{n}")
    if stats['repeated_adjacent_pairs']:errors.append('RATIO_PLAN_HOLD:相邻格比例须交错，不能连续沿用同一比例')
    for group in (PORTRAIT,ALLOWED[3:]):
        if max(counts[r] for r in group)-min(counts[r] for r in group)>1:errors.append('RATIO_PLAN_HOLD:同一方向组内各比例数量须均衡（差不超过1），先按内容重新选择')
    # Weighted prefix discrepancy: proportional to the chosen quotas, never
    # equalize all six ratios and accidentally reduce portrait share to 50%.
    for label,chosen,total,slack in [(r,lambda p,r=r:p.get('frame_ratio')==r,counts[r],2) for r in ALLOWED]+[('方形/横版',lambda p:p.get('frame_ratio') not in PORTRAIT,n-stats['portrait_count'],1)]:
        used=0
        for i,panel in enumerate(rows,1):
            used+=bool(chosen(panel))
            if abs(used*n-total*i)>slack*n:
                errors.append(f'RATIO_PLAN_HOLD:{label}集中堆积，须按全话源序均匀穿插');break
    return errors

def read_plan(data,root):
    path=checked_file(Path(root),data.get('frame_ratio_plan'))
    return read_json(path)

def plan_errors(data,root,source=None):
    if data.get('frame_ratio_policy') is None:
        return ['RATIO_PLAN_HOLD:已有比例计划不能删除画幅策略后放行'] if data.get('frame_ratio_plan') or data.get('requested_framing',{}).get('policy')==POLICY else []
    try:
        if not enabled(data):raise ValueError('未知画幅分布合同')
        plan=read_plan(data,root)
        if source is None:source=read_json(checked_file(Path(root), data['source_snapshot']))
        expected={'policy':POLICY,'book_id':data['book_id'],'episode_id':data['episode_id'],'source_snapshot':data['source_snapshot'],'panel_ids':source['panel_ids']}
        if any(plan.get(k)!=v for k,v in expected.items()):raise ValueError('全话比例计划的书话/源稿版本/源序不一致')
        rows=plan.get('panels',[])
        if [p.get('panel_id') for p in rows]!=source['panel_ids']:raise ValueError('全话比例计划缺格、乱序或重复')
        if any(not isinstance(p.get('frame_ratio_reason'),str) or not p['frame_ratio_reason'].strip() for p in rows):raise ValueError('每格须有具体画面内容选幅依据')
        return distribution_errors(rows)
    except (OSError,ValueError,TypeError,KeyError,AttributeError) as exc:return [f'RATIO_PLAN_HOLD:{exc}']

def binding_errors(state,manifest):
    if not enabled(state):return []
    return ['RATIO_PLAN_HOLD:镜头/生图包未绑定同一全话画幅计划'] if any(manifest.get(k)!=state.get(k) for k in ('frame_ratio_policy','frame_ratio_plan')) else []

def panel_errors(data,root,panels,prompt=False):
    if not enabled(data):return []
    try:
        plan=read_plan(data,root)
        mapping={p['panel_id']:p for p in plan['panels']};errors=[]
        for panel in panels:
            row=mapping.get(panel.get('panel_id'))
            if row is None or any(panel.get(k)!=row.get(k) for k in ('frame_ratio','frame_ratio_reason')):errors.append(f"RATIO_PLAN_HOLD:{panel.get('panel_id')}:比例/选幅依据与全话计划不一致")
            if prompt and (panel.get('frame_ratio_execution_block')!=execution_block(panel) or execution_block(panel) not in str(panel.get('prompt',''))):errors.append(f"RATIO_PLAN_HOLD:{panel.get('panel_id')}:批准比例约束未进入实际prompt")
            if prompt and any(m.group(1)!=panel.get('frame_ratio') for m in re.finditer(r'(?im)^\s*(?:画幅比例|frame\s+ratio|aspect\s+ratio)\s*[:：]\s*(\d+:\d+)',str(panel.get('prompt','')))):errors.append(f"RATIO_PLAN_HOLD:{panel.get('panel_id')}:实际prompt保留了矛盾的旧画幅指令")
        return errors
    except (OSError,ValueError,TypeError,KeyError,AttributeError) as exc:return [f'RATIO_PLAN_HOLD:{exc}']

def classify_size(size):
    w,h=size
    if type(w) is not int or type(h) is not int or min(w,h)<=0:raise ValueError('实际图片尺寸无效')
    actual=w/h
    return min(ALLOWED,key=lambda r:abs(actual/(int(r.split(':')[0])/int(r.split(':')[1]))-1))

def image_errors(panel,size):
    if classify_size(size)!=panel.get('frame_ratio'):return ['IMAGE_RATIO_HOLD:实际画幅更接近其他比例，不能放宽容差通过']
    if (size[0]<size[1])!=(panel.get('frame_ratio') in PORTRAIT):return ['IMAGE_RATIO_HOLD:实际竖/方/横方向与批准比例不符']
    return []

def actual_review(data,root,records):
    if not enabled(data):return {'statistics':None,'errors':[]}
    from PIL import Image
    plan=read_plan(data,root);expected={p['panel_id']:p for p in plan['panels']};rows=[];errors=[]
    if [r['panel_id'] for r in records]!=plan['panel_ids']:return {'statistics':None,'errors':['IMAGE_RATIO_HOLD:全话实际图片缺格或源序不一致']}
    for record in records:
        from codex_reference_contract import physical_file
        with Image.open(physical_file(checked_file(Path(root),record.get('output')))) as im:size=im.size
        errors.extend(f"{record['panel_id']}:{e}" for e in image_errors(expected[record['panel_id']],size))
        rows.append({'panel_id':record['panel_id'],'frame_ratio':classify_size(size)})
    return {'statistics':statistics(rows),'errors':[*errors,*distribution_errors(rows)]}

def actual_errors(data,root,records):return actual_review(data,root,records)['errors']

def template(data,source):
    return {'policy':POLICY,'book_id':data['book_id'],'episode_id':data['episode_id'],'source_snapshot':data['source_snapshot'],'panel_ids':source['panel_ids'],
            'panels':[{'panel_id':pid,'frame_ratio':None,'frame_ratio_reason':''} for pid in source['panel_ids']]}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',required=True);p.add_argument('--write-template');p.add_argument('--actual',action='store_true');a=p.parse_args()
    try:
        path=resolve_path(Path(a.state));root=path.parent.parent;data=read_json(path);source=read_json(checked_file(root, data['source_snapshot']))
        if a.write_template:
            dest=resolve_path(Path(a.write_template));dest.relative_to(root)
            with dest.open('x',encoding='utf-8', newline='\n') as f:json.dump(template(data,source),f,ensure_ascii=False,indent=2)
            print(json.dumps({'status':'UNPLANNED_NOT_APPROVED','path':str(dest)},ensure_ascii=False));return 0
        if not enabled(data):raise ValueError('本任务未启用新画幅合同；旧RV须明确恢复/迁移')
        errors=plan_errors(data,root,source)
        actual=actual_review(data,root,data['panels']) if a.actual and not errors else None
        if actual:errors.extend(actual['errors'])
        value={'status':'HOLD' if errors else 'PASS','scope':'ACTUAL_EPISODE' if a.actual else 'PLANNED_EPISODE','planned_statistics':statistics(read_plan(data,root)['panels']),'actual_statistics':actual['statistics'] if actual else None,'errors':errors,'user_approval':'NOT_GRANTED'}
        print(json.dumps(value,ensure_ascii=False));return bool(errors)
    except (OSError,ValueError,TypeError,KeyError,AttributeError) as exc:print(json.dumps({'status':'HOLD','errors':[str(exc)]},ensure_ascii=False));return 1

if __name__=='__main__':
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
