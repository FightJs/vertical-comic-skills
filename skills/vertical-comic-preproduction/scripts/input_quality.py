"""Executable, opt-in input constraints; validates evidence bindings, not image truth."""
from __future__ import annotations
import copy

POLICY = 'execution_quality_v1'

def text(v): return isinstance(v,str) and bool(v.strip())
def enabled(v): return v.get('input_quality_policy') == POLICY

def bindings(state,*docs):
    policy=state.get('input_quality_policy')
    errors=[]
    if policy not in (None,POLICY):errors.append('INPUT_QUALITY_HOLD:未知执行质量策略')
    if policy and state.get('visual_evidence_policy')!='visual_evidence_v1':errors.append('INPUT_QUALITY_HOLD:须配套visual_evidence_v1')
    errors += ['INPUT_QUALITY_HOLD:执行质量策略与批准来源不同' for d in docs if d.get('input_quality_policy')!=policy]
    return errors

def basis_errors(basis):
    if not enabled(basis):return []
    errors=[];refs={r.get('sha256') for r in basis.get('reference_files',[])}
    views=basis.get('scene_views')
    if not isinstance(views,dict):return ['INPUT_QUALITY_HOLD:缺scene_views，确无空间可用空对象']
    axes={'N','NE','E','SE','S','SW','W','NW','DETAIL'}
    for vid,v in views.items():
        if (not isinstance(v,dict) or v.get('view_id')!=vid or
            any(not text(v.get(k)) for k in ('scene_id','space_id','description')) or
            not isinstance(v.get('camera_axes'),list) or not v['camera_axes'] or
            any(not text(a) or a not in axes for a in v['camera_axes']) or
            not isinstance(v.get('visible_anchors'),list) or any(not text(a) for a in v['visible_anchors']) or
            v.get('reference_sha256') not in refs):errors.append(f'{vid}:INPUT_QUALITY_HOLD:场景方向/来源不完整')
        if isinstance(v,dict) and 'source_region' in v:
            box=v['source_region']
            if not isinstance(box,list) or len(box)!=4 or any(type(n) is not int for n in box) or not (0<=box[0]<box[2] and 0<=box[1]<box[3]):errors.append(f'{vid}:场景选区无效')
    for did,d in basis.get('appearance_details',{}).items():
        if d.get('presence') not in {'present','absent'}:errors.append(f'{did}:须明确批准细节有/无，遮挡另记可见性')
    return errors

def context_for(basis,panel):
    if not enabled(panel):return {}
    ev=panel.get('visual_evidence') or {}
    if ev.get('spatial_applicability')!='REQUIRED':return {'scene_view':None}
    selection=ev.get('scene_view') or {}
    return {'scene_view':copy.deepcopy(basis['scene_views'][selection['view_id']])}

def errors(panel,context=None):
    if not enabled(panel):return bindings(panel)
    out=bindings(panel);ev=panel.get('visual_evidence') or {};hands=ev.get('hands') or {}
    if hands.get('narrative_role') not in {'critical','incidental','not_visible'}:out.append('INPUT_QUALITY_HOLD:手部须区分剧情关键/非关键/不可见')
    if hands.get('narrative_role')=='critical' and hands.get('applicability')!='REQUIRED':out.append('INPUT_QUALITY_HOLD:剧情手不能豁免或裁掉')
    checks=ev.get('checks') or []
    if not isinstance(checks,list):return out+['INPUT_QUALITY_HOLD:checks须为列表']
    relevant=[c for c in checks if isinstance(c,dict) and (c.get('kind')=='contact' or c.get('kind')=='hand' and hands.get('narrative_role')=='critical')]
    for c in relevant:
        fields=('action_stage','target','target_part','visible_path','support','occlusion','forbidden_substitute')
        if c.get('kind')=='hand':fields+=('actor','actor_limb','palm_orientation','thumb_side')
        if any(not text(c.get(k)) for k in fields):out.append(str(c.get('id'))+':INPUT_QUALITY_HOLD:动作阶段/对象/承托/遮挡/手部结构未具体化')
    # Same declared limb at one instant cannot silently acquire a second task.
    # This checks exact IDs, not natural-language synonyms or physical feasibility.
    allocations={}
    for c in relevant:
        if all(text(c.get(k)) for k in ('actor','actor_limb','target')):
            allocations.setdefault((c['actor'],c['actor_limb']),[]).append(c)
    for (actor,limb),rows in allocations.items():
        if len({c['target'] for c in rows})>1:
            bases=[c.get('combined_grip_basis') for c in rows]
            if not all(text(b) for b in bases) or len(set(bases))!=1:
                out.append(f'{actor}/{limb}:INPUT_QUALITY_HOLD:同一肢体分配多个对象，须先解决冲突；真实共同握持须有一致combined_grip_basis')
    for c in checks:
        if isinstance(c,dict) and 'inspection_targets' in c:
            targets=c['inspection_targets']
            if (not isinstance(targets,list) or not targets or any(not text(t) for t in targets)
                    or len(set(targets))!=len(targets)):
                out.append(str(c.get('id'))+':INPUT_QUALITY_HOLD:局部检查目标须具体且不重复')
    ctx=context if context is not None else panel.get('visual_evidence_context')
    if not isinstance(ctx,dict):return out+['INPUT_QUALITY_HOLD:缺派生场景资料']
    if ev.get('spatial_applicability')=='REQUIRED':
        view=ctx.get('scene_view');sel=ev.get('scene_view') or {}
        if not isinstance(view,dict):return out+['INPUT_QUALITY_HOLD:缺当前方向场景参考']
        if (sel.get('view_id')!=view.get('view_id') or view.get('scene_id')!=panel.get('scene_id') or
            view.get('space_id')!=ev.get('space_id',panel.get('scene_id')) or
            sel.get('camera_axis') not in view.get('camera_axes',[]) or not text(sel.get('direction_basis'))):out.append('INPUT_QUALITY_HOLD:房间/子空间/观看方向不匹配')
        anchors=sel.get('required_anchors')
        if not isinstance(anchors,list) or any(not text(a) for a in anchors) or not set(anchors)<=set(view.get('visible_anchors',[])):out.append('INPUT_QUALITY_HOLD:必要锚点不在所选视图覆盖范围')
    for did,d in ctx.get('details',{}).items():
        if d.get('presence') not in {'present','absent'}:out.append(did+':细节有无依据缺失')
    return out

def execution_block(panel,context=None):
    if not enabled(panel):return ''
    ctx=context if context is not None else panel.get('visual_evidence_context');issues=errors(panel,ctx)
    if issues:raise ValueError(';'.join(issues))
    ev=panel['visual_evidence'];lines=['本格具体执行约束']
    view=ctx.get('scene_view')
    if view:
        sel=ev['scene_view'];lines.append(f"场景仅选参考中的{view['description']}，观看方向{sel['camera_axis']}；必要锚点："+'、'.join(sel['required_anchors'])+'。其余房间/视图不迁移到本格，原世界位置不随画面左右变化。')
        if view.get('source_region'):lines.append('场景来源选区xyxy='+str(view['source_region'])+'；此坐标仅定位参考子图，不画坐标或标注。')
    for c in ev['checks']:
        if c.get('kind')=='contact' or c.get('kind')=='hand' and ev['hands'].get('narrative_role')=='critical':
            lines.append('；'.join(f'{k}：{c[k]}' for k in ('actor','actor_limb','action_stage','target','target_part','visible_path','support','occlusion','palm_orientation','thumb_side','forbidden_substitute','combined_grip_basis') if text(c.get(k))))
    kinds={c.get('kind') for c in ev['checks']}
    if kinds & {'hand','contact'}:
        lines.append('逐人物保持唯一左右肢体及当前任务；手掌、手腕、袖口沿所属前臂连接，不为递接或修复另生一只手。握持围绕用途和受力，肘腕自然；物件相对手和头的尺度稳定，不靠向观众硬伸道具突出重点。')
    if ev.get('blocking'):
        lines.append('摄影机高度、人物头部朝向与目光目标分别执行；俯拍不使人物自动仰头看镜头。可见身体沿肩、髋、膝、脚连贯转动，承托面和遮挡按本格具体关系保持。')
    if 'space' in kinds:
        lines.append('有正反面的物件按使用者视线与当前机位呈现；不为展示内容把屏幕翻向观众。信息传递示意不画成实物光线或连线，除非本格明确批准该表现。')
    for did,row in ev['detail_visibility'].items():
        d=ctx['details'][did]
        if row.get('status')=='visible':lines.append(('可见细节保持：' if d['presence']=='present' else '本格可见区域保持无该装饰：')+d['expected'])
    lines.append('五官、剧情手、可见关键首饰和动作物件保持清楚轮廓与结构；环境简化不扩散到主体。真实遮挡处允许隐藏，未被遮住的眼部、指掌和连接不能空白或涂抹；不为露出五指扭曲握持。')
    return '\n'.join(lines)

def repair_decision_errors(decision,record,*,require_image_call=False,state=None,root=None,new_package=None):
    from repair_routes import plan
    try:
        selected=plan(decision,record)
        if selected['route']=='rebuild_inputs' and state is not None and root is not None:
            from pathlib import Path
            from codex_reference_contract import checked_file,read_json
            resolved=decision.get('input_resolution') or {}
            if (resolved.get('visual_basis')==state.get('visual_basis') and resolved.get('shot_manifest')==state.get('shot_manifest') and text(resolved.get('evidence'))):
                old=read_json(checked_file(Path(root),record['package_manifest']))['panels'][0]
                new=read_json(checked_file(Path(root),new_package))['panels'][0]
                if any(old.get(k)!=new.get(k) for k in ('framing','visual_evidence','reference_images','visible_region','reference_bindings')):
                    selected['image_call_allowed']=True
                    # This is not an approval. Original complete generate gates still verify A/B/package.
        if require_image_call and not selected['image_call_allowed']:return ['REPAIR_ROUTE_HOLD:当前诊断应先裁切/修依据/停止，不能直接再次生图']
        return []
    except (KeyError,ValueError,TypeError,OSError) as exc:return ['REPAIR_ROUTE_HOLD:'+str(exc)]


def _scene_reference_errors(panel,root):
    if not enabled(panel):return []
    from pathlib import Path
    from codex_reference_contract import checked_file
    view=(panel.get('visual_evidence_context') or {}).get('scene_view')
    if not view:return []
    from visual_evidence import detail_carried
    if not detail_carried(view,panel.get('reference_images',[])):
        return ['INPUT_QUALITY_HOLD:当前场景视图未进入实际参考；资产库存在不能替代上传']
    if view.get('multi_view') is True and 'source_region' not in view:return ['INPUT_QUALITY_HOLD:多视图场景板须指定准确选区']
    box=view.get('source_region')
    if box is None:return []
    # For a full original reference, bounds are verified from the actual passed file.
    ref=next((r for r in panel.get('reference_images',[]) if r.get('sha256')==view.get('reference_sha256')),None)
    if ref:
        try:
            from PIL import Image
            with Image.open(checked_file(Path(root),ref)) as im:
                if (not isinstance(box,list) or len(box)!=4 or any(type(v) is not int for v in box) or
                    not (0<=box[0]<box[2]<=im.width and 0<=box[1]<box[3]<=im.height)):
                    return ['INPUT_QUALITY_HOLD:场景选区超出实际上传原板']
        except (OSError,ValueError,TypeError):return ['INPUT_QUALITY_HOLD:实际场景参考无法核对']
    return []


def scene_reference_errors(panel,root):
    from appearance_lock import reference_errors
    return _scene_reference_errors(panel,root) + reference_errors(panel,root)
