"""Scoped state-calibration correction, using the same half's round-2 budget."""
from codex_reference_contract import read_json, resolve_path
import argparse,json
from pathlib import Path
from codex_reference_contract import checked_file
from production_evidence import snapshot,attempt_errors,repair_route_errors

POLICY='state_calibration_round_v1'
MARKER='state_calibration_repair_v1'

def binding_extension_valid(packet,panel,shot,root):
    """Preserve approved bindings; append only the hash-bound failed-image target."""
    if packet.get('execution_contract')!='comic_execution_v2' or packet.get('calibration_repair',{}).get('policy')!=MARKER:return False
    old=shot.get('reference_bindings',[]);current=panel.get('reference_bindings',[])
    if current[:len(old)]!=old or len(current)<=len(old):return False
    target=packet.get('repair_source_output',{})
    checked_file(Path(root),target)
    aliases={r['alias'] for r in panel.get('reference_images',[]) if r.get('sha256')==target.get('sha256')}
    return bool(aliases) and all(b.get('alias') in aliases and b.get('purpose') in {'pose_interaction','scene_view','framing','spatial_layout','prop_state'} for b in current[len(old):])

def read(path):return read_json(Path(path))

def validate(state,root,batch,shots,records,pid):
    try:
        ref=state.get('calibration_reviews',{}).get(pid)
        data=read(checked_file(Path(root),ref));record=records[pid];shot=shots[pid]
        expected={'policy':POLICY,'book_id':state['book_id'],'episode_id':state['episode_id'],'batch_id':batch['batch_id'],'panel_ids':[pid],'source_snapshot':state['source_snapshot'],'visual_basis':state['visual_basis'],'shot_manifest':state['shot_manifest']}
        if pid not in batch['panel_ids'] or not (shot.get('requires_state_review') or shot.get('calibration_anchor') or pid in batch.get('state_barriers',[])):raise ValueError('只允许批准的新状态/校准屏障，不把普通格伪装为校准')
        if any(data.get(k)!=v for k,v in expected.items()) or data.get('status')!='REVIEWED' or not data.get('reviewer') or not data.get('evidence'):raise ValueError('校准报告范围/版本失配或未实际审查')
        history=record.get('attempt_history',[])
        if record.get('round_id')==1:
            if record.get('status')!='VISUAL_FAIL' or history:raise ValueError('校准来源须是真实首轮FAIL')
            old=snapshot(record)
        else:
            if record.get('round_id')!=2 or len(history)!=1 or record.get('attempt_id')==history[0].get('attempt_id'):raise ValueError('校准只允许原首轮→唯一第二轮，不重置次数')
            old=snapshot(history[0])
        if old.get('status')!='VISUAL_FAIL' or old.get('round_id')!=1 or data.get('attempts')!=[old]:raise ValueError('校准报告未绑定原始真实失败尝试')
        errors=attempt_errors(state,root,old)
        packet=read(checked_file(Path(root),old['package_manifest']))
        if packet.get('round_context',{}).get('batch_id')!=batch['batch_id']:errors.append('源失败不属于本半话')
        diagnosis=data.get('diagnosis',{});constraints=diagnosis.get('repair_constraints',{})
        if not diagnosis.get('reviewer') or not diagnosis.get('evidence') or not diagnosis.get('earliest_layer') or diagnosis.get('requires_basis_change') is not False or set(constraints)!={pid} or not isinstance(constraints.get(pid),list) or not constraints[pid] or any(not isinstance(x,str) or not x.strip() for x in constraints[pid]):errors.append('校准修正缺具体诊断/保留约束，变基准须回A/B')
        errors.extend(repair_route_errors(state,diagnosis,[pid]))
        if record.get('round_id')==2:
            path=checked_file(Path(root),record['package_manifest']);current=read(path);panel=current['panels'][0];marker=current.get('calibration_repair',{})
            if marker!={'policy':MARKER,'panel_id':pid,'source_review_sha256':ref['sha256'],'source_attempt_id':old['attempt_id']}:errors.append('修正执行包没有原范围校准来源')
            if panel.get('operation')!='repair' or current.get('round_context')!={'batch_id':batch['batch_id'],'round_id':2,'attempt_id':record['attempt_id']} or any(x not in panel.get('prompt','') for x in constraints.get(pid,[])):errors.append('校准修正未使用真实round2或约束未进入实际prompt')
            source=current.get('repair_source_output',{})
            if source.get('sha256')!=old['output']['sha256']:errors.append('编辑目标不是原失败图')
            checked_file(path.parent,source)
        return errors,data,old
    except (OSError,ValueError,TypeError,KeyError,AttributeError,IndexError) as exc:return [f'CALIBRATION_REPAIR_HOLD:{exc}'],None,None

def source_basis(state,root,package_path,packet,basis):
    marker=packet.get('calibration_repair')
    if not marker:return basis
    pid=marker['panel_id'];ref=state.get('calibration_reviews',{}).get(pid)
    data=read(checked_file(Path(root),ref))
    if marker.get('policy')!=MARKER or marker.get('source_review_sha256')!=ref['sha256'] or len(data.get('attempts',[]))!=1:raise ValueError('校准源报告失配')
    old=data['attempts'][0];target=packet.get('repair_source_output',{})
    if old.get('status')!='VISUAL_FAIL' or old.get('panel_id')!=pid or marker.get('source_attempt_id')!=old.get('attempt_id') or target.get('sha256')!=old['output']['sha256']:raise ValueError('校准编辑目标不是本格原FAIL')
    checked_file(Path(root),old['output']);checked_file(package_path.parent,target)
    panel=packet['panels'][0];aliases={r['alias'] for r in panel['reference_images'] if r.get('sha256')==target['sha256']}
    bindings=[b for b in panel['reference_bindings'] if b.get('alias') in aliases]
    if not aliases or not bindings or any(b.get('purpose') not in {'pose_interaction','scene_view','framing','spatial_layout','prop_state'} for b in bindings):raise ValueError('失败图须实际作为编辑目标，不能升为身份/衣装/画风')
    return {**basis,'reference_files':[*basis['reference_files'],target]}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',required=True);p.add_argument('--panel',required=True);p.add_argument('--write',required=True);a=p.parse_args()
    try:
        path=resolve_path(Path(a.state));root=path.parent.parent;state=read(path);pid=a.panel;record=next(r for r in state['panels'] if r['panel_id']==pid)
        from scoped_inputs import half_view
        plan=read(checked_file(root,state['batch_plan']));batch=next(b for b in plan['batches'] if pid in b['panel_ids']);view=half_view(state,batch['batch_id'])
        if record.get('status')!='VISUAL_FAIL' or record.get('round_id')!=1 or record.get('attempt_history'):raise ValueError('候选仅从实际首轮FAIL创建')
        errors=attempt_errors(view,root,record)
        if errors:raise ValueError(';'.join(errors))
        value={'policy':POLICY,'book_id':state['book_id'],'episode_id':state['episode_id'],'batch_id':batch['batch_id'],'panel_ids':[pid],'source_snapshot':state['source_snapshot'],'visual_basis':view['visual_basis'],'shot_manifest':view['shot_manifest'],'attempts':[snapshot(record)],'status':'UNREVIEWED','reviewer':'','evidence':'','diagnosis':{}}
        dest=resolve_path(Path(a.write));dest.relative_to(root)
        with dest.open('x',encoding='utf-8', newline='\n') as f:json.dump(value,f,ensure_ascii=False,indent=2)
        print(json.dumps({'status':'UNREVIEWED_CALIBRATION_REPORT','path':str(dest)},ensure_ascii=False));return 0
    except (OSError,ValueError,TypeError,KeyError,StopIteration) as exc:print(json.dumps({'status':'HOLD','errors':[str(exc)]},ensure_ascii=False));return 1

if __name__=='__main__':
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
