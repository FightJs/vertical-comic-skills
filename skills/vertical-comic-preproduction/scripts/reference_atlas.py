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


def select_reference_set(candidates, required_aliases):
    """Explicit visible-use selection; never silently discard a required reference."""
    aliases=[r.get('alias') for r in candidates]
    if len(set(aliases))!=len(aliases): raise ValueError('参考alias重复')
    if not required_aliases or len(set(required_aliases))!=len(required_aliases) or not set(required_aliases)<=set(aliases):
        raise ValueError('须明确本格全部必要参考职责alias')
    chosen=[r for r in candidates if r['alias'] in required_aliases]
    if len(chosen)>5: raise ValueError('必要参考超过五张；先消解职责，再按需复用忠实图集，不截断')
    return chosen


def cached_lossless_atlas(spec, cache, root):
    """Build/reuse exact source crops. Readability and approval remain separate."""
    import json,os,tempfile,uuid
    from PIL import Image
    from platform_io import file_lock,atomic_json,replace_file
    from input_dependencies import fingerprint,file_hash,recheck,observe
    rows=spec.get('regions',[])
    if not rows: raise ValueError('图集缺来源区域')
    observations=[];sizes=[];canonical=[]
    for row in rows:
        if row.get('purpose') not in {'identity','costume_state'} or not row.get('subject_id') or not row.get('asset_id'):
            raise ValueError('图集须明确人物、原资产ID及身份/衣装职责')
        source=checked_file(Path(root),row['source_file'])
        observations.append(observe(source))
        with Image.open(source) as image:
            box=rect(row['crop_rect_pixels'],image.size)
        sizes.append((box[2]-box[0],box[3]-box[1]))
        canonical.append({**row,'source_file':{'path':str(source),'sha256':file_hash(source)}})
    width=max(w for w,h in sizes);height=sum(h for w,h in sizes)
    if width*height>64_000_000: raise ValueError('图集过大；按实际可见需求减小来源范围')
    key=fingerprint({'policy':'lossless_atlas_cache_v1','regions':canonical,'layout':'vertical_no_resize_v1','tool':file_hash(__file__)})
    cache=Path(cache).resolve();cache.mkdir(parents=True,exist_ok=True)
    target=cache/(key+'.png');receipt=cache/(key+'.json')
    with file_lock(cache/(key+'.lock')):
        if target.is_file() and receipt.is_file():
            value=json.loads(receipt.read_text(encoding='utf-8-sig'))
            if value.get('cache_key')==key and value.get('path')==str(target) and value.get('sha256')==file_hash(target):
                recheck(observations)
                return {**value,'reviewed':False,'detail_readability':[],'cache_reused':True,'observation_id':uuid.uuid4().hex}
        atlas=Image.new('RGBA',(width,height),(0,0,0,0));regions=[];offset=0;owners={}
        for row,(w,h) in zip(canonical,sizes):
            with Image.open(row['source_file']['path']) as image:
                crop=image.convert('RGBA').crop(tuple(row['crop_rect_pixels']))
            atlas.paste(crop,(0,offset))
            regions.append({**row,'assembly_region':[0,offset,w,offset+h]});offset+=h
            mapping=owners.setdefault(row['subject_id'],{})
            if row['purpose'] in mapping and mapping[row['purpose']]!=row['asset_id']:
                raise ValueError('同一人物/用途不能在图集混用不同状态资产')
            mapping[row['purpose']]=row['asset_id']
        recheck(observations)
        handle,tmp=tempfile.mkstemp(prefix='.atlas-',suffix='.png',dir=cache);os.close(handle)
        try:
            atlas.save(tmp,format='PNG');replace_file(tmp,target)
        finally:
            Path(tmp).unlink(missing_ok=True)
        value={'path':str(target),'sha256':file_hash(target),'derivation_policy':POLICY,
               'reference_kind':'faithful_reference_atlas','subject_ids':list(owners),'subject_asset_ids':owners,
               'source_regions':regions,'reviewed':False,'detail_readability':[],
               'cache_key':key,'dispatch_authorized':False}
        atomic_json(receipt,value)
        return {**value,'cache_reused':False,'observation_id':uuid.uuid4().hex}


def main():
    import argparse,json
    from platform_io import configure_stdio
    configure_stdio()
    p=argparse.ArgumentParser(description='只构建/复用无缩放技术图集，不授予批准')
    p.add_argument('--spec',required=True);p.add_argument('--cache',required=True);p.add_argument('--root',required=True);a=p.parse_args()
    try:
        spec=json.loads(Path(a.spec).read_text(encoding='utf-8-sig'))
        print(json.dumps(cached_lossless_atlas(spec,a.cache,a.root),ensure_ascii=False));return 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'ATLAS_WORK_ITEM','error':str(exc)},ensure_ascii=False));return 1

if __name__=='__main__': raise SystemExit(main())
