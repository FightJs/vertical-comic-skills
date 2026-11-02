"""Character costume reference format: deterministic brief, human pixel evidence."""
POLICY='character_costume_reference_v1'
PROMPT_MARKER='[character_costume_reference_v1]'
VIEWS=('main_full_body','front','side','back')
ANGLES={'front':0,'side':90,'back':180}
CHECKS=('identity_costume_consistency','readable_labels','key_details','blank_background')

def required(task):
    return bool(task.get('character_id') and task.get('costume_id'))

def contract(task):
    if not required(task):return None
    return {'policy':POLICY,'required_views':list(VIEWS),'full_body_required':True,
            'side_angle_degrees':90,'layout':'independent_full_body_main_and_front_side_back',
            'applies_to':'temporary_and_canonical_costume_references'}

def prompt_block(task):
    if not required(task):return ''
    return (PROMPT_MARKER+'\n人物衣装参考最低版式（临时参考和入库资产同标准）：'
        '制作一张横版规范参考板，包含独立全身主图，以及正面0°、真实侧面90°、背面180°三视图。'
        '四个视图都须从完整头顶到鞋底，全身完整，不裁腿、不裁脚、不以半身或四分之三角度代替正侧面。'
        '三视图保持同一人物、同一衣装状态、同一配饰款式与佩戴侧、身体比例和鞋履；三视图头顶/脚底对齐、比例统一，站姿自然、避免肢体或道具遮挡衣装。'
        '保留批准人物身份和本书画风；只作已授权的衣装变化，不把衣装参考当作剧情伤势或姿态依据。'
        '清楚标注人物ID '+str(task['character_id'])+'、衣装状态ID '+str(task['costume_id'])+'，以及“全身主图”“正面”“侧面90°”“背面”。'
        '有影响识别的衣领、袖口、鞋或配饰时补必要细节小图。使用纯白空白背景，不含走廊、场景、道具或装饰背景，文字可读；临时参考不要求额外九表情整卡。')

def compiled_arguments(arguments,task):
    if not required(task):return arguments
    block=prompt_block(task)
    authored=arguments['prompt']
    if PROMPT_MARKER in authored:raise ValueError('ASSET_FORMAT_HOLD: format block is compiler-owned; remove hand-written marker')
    return {**arguments,'prompt':authored+'\n\n'+block}

def review_template(image_sha256):
    return {'policy':POLICY,'image_sha256':image_sha256,'reviewer':None,
            'views':{name:{'status':'UNREVIEWED','full_body':None,'evidence':'',**({'angle_degrees':None} if name in ANGLES else {})} for name in VIEWS},
            'checks':{name:{'status':'UNREVIEWED','evidence':''} for name in CHECKS}}

def review_errors(review,image_sha256):
    if not isinstance(review,dict):return ['ASSET_FORMAT_HOLD: actual reference format observation missing']
    errors=[]
    if review.get('policy')!=POLICY or review.get('image_sha256')!=image_sha256 or not review.get('reviewer'):
        errors.append('ASSET_FORMAT_HOLD: format observation policy/image/reviewer mismatch')
    views=review.get('views');checks=review.get('checks')
    views=views if isinstance(views,dict) else {}
    checks=checks if isinstance(checks,dict) else {}
    for name in VIEWS:
        row=views.get(name);row=row if isinstance(row,dict) else {}
        if row.get('status')!='PASS' or row.get('full_body') is not True or not row.get('evidence'):
            errors.append('ASSET_FORMAT_HOLD: '+name+' requires a real complete full-body view')
        if name in ANGLES and (type(row.get('angle_degrees')) not in (int,float) or row['angle_degrees']!=ANGLES[name]):
            errors.append('ASSET_FORMAT_HOLD: '+name+' angle must be '+str(ANGLES[name]))
    for name in CHECKS:
        row=checks.get(name);row=row if isinstance(row,dict) else {}
        if row.get('status')!='PASS' or not row.get('evidence'):errors.append('ASSET_FORMAT_HOLD: '+name+' not observed/passed')
    return errors

def panel_errors(state,basis):
    """Only new preparation contracts enforce this; old frozen evidence is unchanged."""
    if state.get('asset_format_policy')!=POLICY:return {}
    result={}
    for task in basis.get('asset_tasks',[]):
        if not required(task):continue
        if task.get('inline_sufficient') is True and task.get('visible_occurrences')==1 and not task.get('reference'):continue
        ref=task.get('reference') or {};errors=review_errors(task.get('format_review'),ref.get('sha256'))
        if not ref.get('sha256'):errors.append('ASSET_FORMAT_HOLD: adopted reference missing')
        for pid in task.get('panel_ids',[]):
            if errors:result.setdefault(pid,[]).extend(errors)
    return result
