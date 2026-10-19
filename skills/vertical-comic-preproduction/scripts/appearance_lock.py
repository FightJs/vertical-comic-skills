"""Frozen wardrobe anchors and one-scene panels; validates evidence, not pixels.

Extends existing appearance_details, detail_visibility and visual_evidence_review.
No generation, approval synthesis, changed source script or additional QA store.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

APPEARANCE = 'appearance_lock_v1'
FRAME = 'single_frame_v1'
SIDES = {'left','right','bilateral','center'}
PARTS = {'ear_lobe','neck','chest','wrist','finger','lapel','sleeve','collar','torso','waist','leg','foot','hair','other'}
FINGERS = {'thumb','index','middle','ring','little'}
QUALITY_CHECKS = ('design','attachment','screen_position','clarity')
SINGLE_TEXT = '整张成品只画一个连续场景、一个镜头画面；禁止上下分格、左右分屏、拼贴和漫画内嵌小格。真实镜面或屏幕道具属于同一场景，不另开画格。'


def text(v):return isinstance(v,str) and bool(v.strip())
def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def enabled(v):return v.get('appearance_policy')==APPEARANCE
def single(v):return v.get('frame_policy')==FRAME


def bindings(state,*docs):
    errors=[]
    for key,policy in (('appearance_policy',APPEARANCE),('frame_policy',FRAME)):
        value=state.get(key)
        if value not in (None,policy):errors.append(key+':未知策略')
        if value and state.get('visual_evidence_policy')!='visual_evidence_v1':errors.append(key+':须配套真实原图细节审查')
        if any(d.get(key)!=value for d in docs):errors.append(key+':与冻结依据不一致，不允许删字段降级')
    if 'frame_plan' in state and not single(state):errors.append('单画面计划须声明single_frame_v1')
    return ['APPEARANCE_FRAME_HOLD:'+e for e in errors]


def detail_errors(did,d):
    if not isinstance(d,dict):return [did+':细节须为对象']
    errors=[];placement=d.get('placement',{})
    if not isinstance(placement,dict):return [did+':缺身体锚点']
    if (d.get('category') not in {'garment','accessory'} or d.get('presence') not in {'present','absent'} or
        type(d.get('count')) is not int or d['count']!=(0 if d.get('presence')=='absent' else max(1,d['count']))):
        errors.append(did+':须明确服装/配饰类别、存在状态和准确数量')
    if d.get('presence')=='present':
        design=d.get('design',{})
        if not isinstance(design,dict) or any(not text(design.get(k)) for k in ('style','color','material')):errors.append(did+':缺具体款式/颜色/材质')
    if (placement.get('side_basis')!='wearer_anatomical' or placement.get('side') not in SIDES or
        placement.get('body_part') not in PARTS or placement.get('motion') not in {'fixed','natural_swing','drape'} or
        any(not text(placement.get(k)) for k in ('anchor','attachment'))):
        errors.append(did+':缺角色自身左右、身体部位、附着位置或合理活动方式')
    if placement.get('body_part')=='finger' and (placement.get('finger') not in FINGERS or placement.get('side') not in {'left','right'}):errors.append(did+':戒指须明确角色自身哪只手及哪根手指')
    if not text(d.get('readability_evidence')):errors.append(did+':须实际核对批准原板能看清哪些细节')
    box=d.get('source_region')
    if not isinstance(box,list) or len(box)!=4 or any(type(n) is not int for n in box) or not (0<=box[0]<box[2] and 0<=box[1]<box[3]):errors.append(did+':缺清晰来源的有效原像素裁区')
    for key in ('subject_id','costume_state','expected','reference_sha256'):
        if not text(d.get(key)):errors.append(did+':缺来源/人物/衣装/具体判据')
    return errors


def basis_errors(basis):
    out=bindings(basis)
    if not enabled(basis):return out
    for did,d in basis.get('appearance_details',{}).items():out+=detail_errors(did,d)
    return out


def frame_errors(panel):
    out=bindings(panel)
    if not single(panel):return out
    plan=panel.get('frame_plan')
    if not isinstance(plan,dict):return out+['SINGLE_FRAME_HOLD:缺已选单画面计划']
    if (plan.get('layout')!='single_scene' or plan.get('source_layout') not in {'single','multiple'} or
        not text(plan.get('selected_scene')) or not text(plan.get('selection_reason'))):out.append('SINGLE_FRAME_HOLD:每格只能选择一个连续场景')
    omitted=plan.get('omitted_scenes')
    if (not isinstance(omitted,list) or any(not text(x) for x in omitted) or
        plan.get('source_layout')=='multiple' and not omitted or plan.get('source_layout')=='single' and omitted or
        plan.get('selected_scene') in (omitted or [])):out.append('SINGLE_FRAME_HOLD:须准确记录保留与忽略内容，不能删改源稿')
    return out


def panel_errors(panel,context=None):
    out=frame_errors(panel)
    if not enabled(panel):return out
    ctx=context if context is not None else panel.get('visual_evidence_context')
    if not isinstance(ctx,dict):return out+['APPEARANCE_HOLD:缺当前衣装派生细节']
    ev=panel.get('visual_evidence') or {};details=ctx.get('details',{});visibility=ev.get('detail_visibility',{})
    subjects=(panel.get('continuity_contract') or {}).get('subjects',{})
    if not isinstance(details,dict) or not isinstance(visibility,dict):return out+['APPEARANCE_HOLD:细节和可见性须为映射']
    if not isinstance(subjects,dict):return out+['APPEARANCE_HOLD:人物衣装状态须为映射']
    for owner,state in subjects.items():
        if not isinstance(state,dict):out.append(owner+':人物状态结构无效');continue
        if not any(d.get('subject_id')==owner and d.get('costume_state')==state.get('costume_state') and d.get('category')=='garment' for d in details.values() if isinstance(d,dict)):
            out.append(owner+':缺本套衣装核心款式/层次依据，不能只约束耳环')
    for did,d in details.items():
        issues=detail_errors(did,d);out+=issues
        if issues:continue
        if d['subject_id'] not in subjects or subjects[d['subject_id']].get('costume_state')!=d['costume_state']:out.append(did+':细节归属人物或当前衣装不符')
        row=visibility.get(did,{})
        if not isinstance(row,dict):out.append(did+':可见性结构无效');continue
        if row.get('status')=='visible':
            projection=row.get('projection',{})
            if (not isinstance(projection,dict) or projection.get('surface') not in {'direct','mirror_reflection'} or
                any(not text(projection.get(k)) for k in ('screen_position','occlusion')) or
                projection.get('surface')=='mirror_reflection' and not text(projection.get('reflection_basis'))):out.append(did+':缺本机位画面位置/遮挡或真实反射依据')
            checks=[c for c in ev.get('checks',[]) if isinstance(c,dict) and c.get('kind')=='accessory' and c.get('detail_id')==did]
            if not checks or any(c.get('subject_ids')!=[d['subject_id']] for c in checks):out.append(did+':细节检查须准确归属本人物，不可借他人配饰')
    return out


def visible_details(panel):
    details=(panel.get('visual_evidence_context') or {}).get('details',{})
    return {k:d for k,d in details.items() if (panel.get('visual_evidence') or {}).get('detail_visibility',{}).get(k,{}).get('status')=='visible'}


def execution_block(panel,context=None):
    if not enabled(panel) and not single(panel):return ''
    issues=panel_errors(panel,context)
    if issues:raise ValueError(';'.join(issues))
    lines=[]
    if single(panel):lines += [SINGLE_TEXT,'本格唯一画面：'+panel['frame_plan']['selected_scene']]
    if enabled(panel):
        lines.append('衣装及配饰左右以角色自身为准，画面左右只描述本机位投影；不借其他人物/其他衣装/画风样例中的首饰。')
        details=(context if context is not None else panel['visual_evidence_context'])['details']
        for did,d in details.items():
            row=panel['visual_evidence']['detail_visibility'][did]
            if row['status']!='visible':continue
            a=d['placement'];design=d.get('design',{})
            lines.append(f"{did}｜人物{d['subject_id']}｜当前衣装{d['costume_state']}｜{d['expected']}；数量{d['count']}；"+
                ('保持无该装饰；' if d['presence']=='absent' else '款式/颜色/材质：'+'、'.join(design[k] for k in ('style','color','material'))+'；')+
                f"自身侧={a['side']}，部位={a['body_part']}，手指={a.get('finger','不适用')}；锚点={a['anchor']}；附着={a['attachment']}；活动={a['motion']}；"+
                f"本镜头位置={row['projection']['screen_position']}；遮挡={row['projection']['occlusion']}；呈现={row['projection']['surface']}。"+
                ('反射依据='+row['projection']['reflection_basis'] if row['projection']['surface']=='mirror_reflection' else ''))
        lines.append('不得换人物、换衣装、换佩戴侧或换手指，不增减装饰与层数；允许符合姿态的透视缩短及首饰自然摆动，不把衣料褶皱/高光当新配饰。')
    if panel.get('operation')=='repair' and enabled(panel):
        plan=panel.get('appearance_repair',{})
        for did in plan.get('correct_detail_ids',[]):lines.append('仅纠正'+did+'：'+str(plan.get('instructions',{}).get(did,'')))
        if plan.get('preserve_detail_ids'):lines.append('保持已正确的细节：'+'、'.join(plan['preserve_detail_ids'])+'；保持已正确脸型、动作、光线和背景，并保留此前有效修正。')
    return '\n'.join(lines)


def reference_errors(panel,root):
    if not enabled(panel):return []
    from visual_evidence import detail_carried
    from codex_reference_contract import checked_file
    from PIL import Image
    out=[]
    for did,d in visible_details(panel).items():
        refs=[r for r in panel.get('reference_images',[]) if detail_carried(d,[r])]
        aliases={r.get('alias') for r in refs if text(r.get('alias'))}
        if not any(b.get('alias') in aliases and b.get('purpose')=='costume_state' and d['subject_id'] in b.get('subject_ids',[]) for b in panel.get('reference_bindings',[])):
            out.append(did+':实际细节参考缺本人物的衣装用途绑定')
        # Atlas provenance/crop pixels remain verified by the original reference contract.
        for ref in refs:
            if ref.get('sha256')!=d['reference_sha256']:continue
            try:
                with Image.open(checked_file(Path(root),ref)) as image:
                    x0,y0,x1,y1=d['source_region']
                    if not (0<=x0<x1<=image.width and 0<=y0<y1<=image.height):out.append(did+':来源裁区超出实际上传图')
            except (OSError,KeyError,ValueError,TypeError):out.append(did+':无法核对实际细节参考原图')
    return out


def review_template(panel):
    value={}
    if single(panel):value['frame_observation']={'expectations_sha256':digest(panel['frame_plan']),'status':'UNREVIEWED','reviewer':'','image_sha256':None,'scene_count':None,'layout':None,'observed':''}
    if enabled(panel):
        value['appearance_observations']={did:{'status':'UNREVIEWED','reviewer':'','observed':'','side_evidence':'',
            'actual_owner':None,'actual_costume_state':None,'actual_side':None,'actual_body_part':None,'actual_finger':None,'actual_count':None,
            'checks':{k:{'status':'UNREVIEWED','observed':''} for k in QUALITY_CHECKS},'observation_id':None} for did in visible_details(panel)}
    return value


def review_errors(panel,item,*,require_pass=True):
    actual=item.get('visual_evidence_review') or {};out=[];verdicts={'PASS'} if require_pass else {'PASS','FAIL'}
    if single(panel):
        f=actual.get('frame_observation',{})
        if (not isinstance(f,dict) or f.get('expectations_sha256')!=digest(panel['frame_plan']) or f.get('status') not in verdicts or
            not text(f.get('reviewer')) or f.get('image_sha256')!=item.get('image_sha256') or not text(f.get('observed')) or
            type(f.get('scene_count')) is not int or f['scene_count']<1 or f.get('layout') not in {'single_scene','multiple_scenes'} or
            f.get('status')=='PASS' and (f['scene_count']!=1 or f['layout']!='single_scene')):out.append('SINGLE_FRAME_HOLD:未实审或出现分屏/双格/内嵌格')
    dimensions=item.get('dimension_review') or {}
    if single(panel) and actual.get('frame_observation',{}).get('status')=='FAIL' and dimensions and (dimensions.get('framing') or {}).get('status')!='FAIL':out.append('SINGLE_FRAME_HOLD:多格失败须同时记入原framing维度')
    if not enabled(panel):return out
    rows=actual.get('appearance_observations');details=visible_details(panel)
    if not isinstance(rows,dict) or set(rows)!=set(details):return out+['APPEARANCE_HOLD:可见服装/配饰实际观察缺项']
    observations={r.get('id'):r for r in actual.get('observations',[]) if isinstance(r,dict)}
    for did,d in details.items():
        r=rows[did]
        if not isinstance(r,dict) or r.get('status') not in verdicts or any(not text(r.get(k)) for k in ('reviewer','observed','side_evidence')):
            out.append(did+':服饰位置缺真实观察或未通过');continue
        check=observations.get(r.get('observation_id'),{})
        if check.get('detail_id')!=did or check.get('kind')!='accessory' or check.get('status')!=r['status']:out.append(did+':须引用本细节原尺寸检查，不能借别人的局部')
        checks=r.get('checks',{})
        if not isinstance(checks,dict) or set(checks)!=set(QUALITY_CHECKS) or any(not isinstance(c,dict) or c.get('status') not in verdicts or not text(c.get('observed')) for c in checks.values()):out.append(did+':款式/附着/投影/清晰度尚未逐项观察')
        elif r['status']=='PASS' and any(c['status']!='PASS' for c in checks.values()):out.append(did+':局部失败不能被总PASS覆盖')
        if r['status']=='PASS':
            expected={'actual_owner':d['subject_id'],'actual_costume_state':d['costume_state'],'actual_side':d['placement']['side'],
                      'actual_body_part':d['placement']['body_part'],'actual_finger':d['placement'].get('finger'),'actual_count':d['count']}
            if any(r.get(k)!=v for k,v in expected.items()) or type(r.get('actual_count')) is not int:out.append(did+':人物/衣装/佩戴侧/部位/手指/数量与批准不符')
    if dimensions and any(isinstance(r,dict) and r.get('status')=='FAIL' for r in rows.values()) and (dimensions.get('costume') or {}).get('status')!='FAIL':out.append('APPEARANCE_HOLD:服饰失败须同时记入原costume维度')
    if panel.get('operation')=='repair':
        kept=(panel.get('appearance_repair') or {}).get('preserve_detail_ids',[])
        observed=(actual.get('repair_comparison') or {}).get('preserved_detail_observations',{})
        if not isinstance(observed,dict) or set(observed)!=set(kept) or any(not isinstance(v,dict) or v.get('status') not in verdicts or not text(v.get('observed')) for v in observed.values()):out.append('APPEARANCE_HOLD:返修须实际对照底图逐项核对原正确服饰')
    return out


def repair_errors(panel,actual_prompt=None):
    if panel.get('operation')!='repair' or not enabled(panel):return []
    plan=panel.get('appearance_repair');out=[]
    if not isinstance(plan,dict):return ['APPEARANCE_REPAIR_HOLD:须明确修哪些细节、保留哪些细节']
    changed=plan.get('correct_detail_ids');kept=plan.get('preserve_detail_ids');visible=set(visible_details(panel))
    if any(not isinstance(x,list) or any(not text(v) for v in x) or len(x)!=len(set(x)) for x in (changed,kept)):
        return ['APPEARANCE_REPAIR_HOLD:修正/保留细节ID须为准确无重复清单']
    if set(changed)&set(kept) or set(changed)|set(kept)!=visible:out.append('APPEARANCE_REPAIR_HOLD:修正与保留范围须完整覆盖本格可见服饰且互斥')
    instructions=plan.get('instructions')
    if not isinstance(instructions,dict) or set(instructions)!=set(changed) or any(not text(v) for v in instructions.values()):out.append('APPEARANCE_REPAIR_HOLD:缺具体纠正内容')
    transfers=set((panel.get('repair_focus') or {}).get('failed_transfers',[]))
    details=visible_details(panel)
    if any(details.get(k,{}).get('category')=='accessory' for k in changed) and 'accessories' not in transfers:out.append('APPEARANCE_REPAIR_HOLD:失败图不得继续迁移待修配饰')
    if any(details.get(k,{}).get('category')=='garment' for k in changed) and 'clothing' not in transfers:out.append('APPEARANCE_REPAIR_HOLD:失败图不得继续迁移待修衣装')
    prompt=panel.get('prompt','') if actual_prompt is None else actual_prompt
    if not out:
        try:block=execution_block(panel)
        except (ValueError,KeyError,TypeError) as exc:return ['APPEARANCE_REPAIR_HOLD:'+str(exc)]
        if block not in prompt:out.append('APPEARANCE_REPAIR_HOLD:实际返修prompt缺纠正/保留服饰约束')
    return out


def prompt_errors(panel):
    if not single(panel):return []
    errors=frame_errors(panel)
    if errors:return errors
    prompt=panel.get('prompt','');plan=panel['frame_plan']
    if SINGLE_TEXT not in prompt or plan['selected_scene'] not in prompt:errors.append('SINGLE_FRAME_HOLD:实际prompt未落实唯一已选画面')
    for omitted in plan['omitted_scenes']:
        if omitted not in plan['selected_scene'] and omitted in prompt:errors.append('SINGLE_FRAME_HOLD:忽略的另一幅画面仍进入实际prompt')
    return errors
