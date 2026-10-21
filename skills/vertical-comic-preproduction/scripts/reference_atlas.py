"""Verify lossless reference layout against original approved assets, never new approval."""
from codex_reference_contract import resolve_path
from pathlib import Path
from codex_reference_contract import checked_file

POLICY = 'faithful_atlas_v1'


def is_atlas(ref):
    return isinstance(ref,dict) and ref.get('derivation_policy') == POLICY


def source_asset_id(ref, subject, purpose):
    if not is_atlas(ref):return ref.get('asset_id')
    return ref.get('subject_asset_ids',{}).get(subject,{}).get(purpose)


def rect(value,size):
    if not isinstance(value,list) or len(value)!=4 or any(type(x) is not int for x in value):raise ValueError('裁区须为4个像素整数')
    x0,y0,x1,y1=value
    if not 0<=x0<x1<=size[0] or not 0<=y0<y1<=size[1]:raise ValueError('裁区越界或为空')
    return tuple(value)


def verify_owner(ref, asset, subject, purpose, root):
    import json,hashlib
    from codex_reference_contract import memoized_validation,digest
    try:
        # Recheck current bytes/stat before using an earlier pixel proof.
        files=[checked_file(Path(root),ref)]
        for region in ref.get('source_regions',[]):
            if region.get('subject_id')!=subject or region.get('purpose')!=purpose:continue
            source=region.get('source_file')
            if isinstance(source,str):source={'path':source,'sha256':region.get('source_sha256')}
            files.append(checked_file(Path(root),source))
        value={'validator_sha256':digest(Path(__file__)),'root':str(resolve_path(Path(root))),'ref':ref,'asset':asset,'subject':subject,'purpose':purpose,'files':[(str(p),digest(p)) for p in files]}
        key=hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        return memoized_validation('faithful_atlas_owner',key,lambda:_verify_owner(ref,asset,subject,purpose,root))
    except (OSError,ValueError,TypeError,KeyError,AttributeError) as exc:return [f'REFERENCE_ATLAS_HOLD:{exc}']

def _verify_owner(ref, asset, subject, purpose, root):
    """Each bound owner/purpose retains the original asset's identity approval."""
    errors=[]
    try:
        if not is_atlas(ref) or purpose not in {'identity','costume_state'}:raise ValueError('图集仅作身份/衣装技术派生')
        if ref.get('reference_kind')!='faithful_reference_atlas':raise ValueError('图集类型缺失')
        if ref.get('reviewed') is not True or not ref.get('reviewer') or not ref.get('evidence'):raise ValueError('图集缺少实际归属/可读性复核')
        if subject not in ref.get('subject_ids',[]):raise ValueError('图集没有登记该人物')
        regions=ref.get('source_regions',[])
        if not isinstance(regions,list) or not regions:raise ValueError('图集缺少逐人物原图裁区')
        selected=[r for r in regions if r.get('subject_id')==subject and r.get('purpose')==purpose]
        if not selected:raise ValueError('该人物/用途没有来源裁区')
        from PIL import Image
        from codex_reference_contract import physical_file
        with Image.open(physical_file(checked_file(Path(root),ref))) as image:atlas=image.convert('RGBA')
        occupied=[]
        for region in regions:
            box=rect(region.get('assembly_region'),atlas.size)
            for other,owner in occupied:
                overlap=max(box[0],other[0])<min(box[2],other[2]) and max(box[1],other[1])<min(box[3],other[3])
                if overlap and owner!=region.get('subject_id'):raise ValueError('不同人物裁区重叠')
            occupied.append((box,region.get('subject_id')))
        for region in selected:
            if region.get('asset_id')!=source_asset_id(ref,subject,purpose):raise ValueError('裁区资产ID与逐人物用途映射不一致')
            source=region.get('source_file')
            if isinstance(source,str):source={'path':source,'sha256':region.get('source_sha256')}
            if not isinstance(source,dict) or source.get('sha256')!=asset.get('sha256'):raise ValueError('裁区不是原批准资产版本')
            if region.get('source_version',asset.get('version'))!=asset.get('version'):raise ValueError('来源版本不匹配')
            with Image.open(physical_file(checked_file(Path(root),source))) as image:
                crop=image.convert('RGBA').crop(rect(region.get('crop_rect_pixels'),image.size))
            target=atlas.crop(rect(region.get('assembly_region'),atlas.size))
            if crop.size!=target.size or crop.tobytes()!=target.tobytes():raise ValueError('图集像素不是原图忠实裁区；禁止缩放、重绘或换人物')
        for detail in ref.get('detail_readability',[]):
            if detail.get('subject_id')!=subject:continue
            if (detail.get('status')!='PASS' or not detail.get('detail_id') or not detail.get('observed')):
                raise ValueError('图集关键细节缺实际可读性观察，忠实像素不等于可辨认')
            box=rect(detail.get('region'),atlas.size)
            if not any((lambda b:b[0]<=box[0]<box[2]<=b[2] and b[1]<=box[1]<box[3]<=b[3])(
                    rect(r['assembly_region'],atlas.size)) for r in selected):
                raise ValueError('关键细节可读性区域不属于当前人物/用途')
    except (OSError,ValueError,TypeError,KeyError,AttributeError) as exc:errors.append(f'REFERENCE_ATLAS_HOLD:{exc}')
    return errors
