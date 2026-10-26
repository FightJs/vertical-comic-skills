"""Persist observed image returns without shell base64, image calls or state writes."""
from pathlib import Path
import base64, hashlib, io, json, os, re, tempfile


def sha(data): return hashlib.sha256(data).hexdigest()


def put(path, data):
    """Publish immutable bytes; a retry may only reuse identical bytes."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.is_symlink() or path.read_bytes()!=data:raise ValueError('RETURN_EVIDENCE_CONFLICT: '+str(path))
        return
    fd,tmp=tempfile.mkstemp(prefix='.return-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        try:os.link(tmp,path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes()!=data:raise ValueError('RETURN_EVIDENCE_CONFLICT: '+str(path))
    finally:Path(tmp).unlink(missing_ok=True)


def hint_paths(text):
    """Extract paths, never join two drive prefixes or interpret HTTP as local."""
    if text.startswith(('http://','https://','data:')):return []
    windows=re.findall(r'[A-Za-z]:[\\/][^\r\n"<>|:]*?\.(?:png|jpe?g|webp)\b',text,re.I)
    quoted=re.findall(r'["\'](/[^\r\n"\']+\.(?:png|jpe?g|webp))["\']',text,re.I)
    bare=re.findall(r'(?<![\w:/])/(?:[^\s"<>]+/)*[^\s"<>]+\.(?:png|jpe?g|webp)\b',text,re.I)
    return list(dict.fromkeys(windows+quoted+bare))


def _image(data):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        kind=im.format;size=list(im.size);im.verify()
    ext={'PNG':'.png','JPEG':'.jpg','WEBP':'.webp'}.get(kind)
    if ext is None:raise ValueError('UNSUPPORTED_RETURN_IMAGE: '+str(kind))
    return ext,size


def persist(raw_path, destination, *, selected_index=None):
    """Retain exact raw bytes first, then deduplicated verified images and a receipt."""
    raw=Path(raw_path).read_bytes();dest=Path(destination).resolve()
    put(dest/'raw-return.json',raw)
    obj=json.loads(raw.decode('utf-8-sig'))
    blobs=[];local=[]
    def walk(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if k=='image_url' and isinstance(v,dict):v=v.get('url')
                if k=='image_url' and isinstance(v,str) and v.startswith('data:'):
                    head,body=v.split(',',1)
                    if head not in ('data:image/png;base64','data:image/jpeg;base64','data:image/webp;base64'):
                        raise ValueError('UNSUPPORTED_IMAGE_DATA_URL')
                    data=base64.b64decode(body,validate=True);ext,_=_image(data)
                    if ext!={'data:image/png;base64':'.png','data:image/jpeg;base64':'.jpg','data:image/webp;base64':'.webp'}[head]:
                        raise ValueError('RETURN_MIME_MISMATCH')
                    blobs.append((data,'data_url'))
                elif k in ('local_paths','artifacts'):
                    items=v if isinstance(v,list) else [v]
                    for item in items:
                        path=item.get('path',item.get('local_path')) if isinstance(item,dict) else item
                        if isinstance(path,str):local.append(path)
                elif k=='output_hint' and isinstance(v,str):local.extend(hint_paths(v))
                elif k=='type' and v=='image' and isinstance(value.get('data'),str):
                    blobs.append((base64.b64decode(value['data'],validate=True),'image_content'))
                elif isinstance(v,(dict,list)):walk(v)
        elif isinstance(value,list):
            for v in value:walk(v)
    walk(obj)
    local_blobs=[]
    for name in dict.fromkeys(local):
        path=Path(name)
        if path.is_absolute() and path.is_file():
            data=path.read_bytes();_image(data);local_blobs.append((data,'local_path:'+str(path.resolve())))
    # Both representations of a single image must agree, including all middle bytes.
    if len(blobs)==1 and len(local_blobs)==1 and sha(blobs[0][0])!=sha(local_blobs[0][0]):
        raise ValueError('RETURN_IMAGE_BYTES_MISMATCH: raw result retained; do not resend')
    unique={}
    for data,source in blobs+local_blobs:
        key=sha(data)
        if key not in unique:
            ext,size=_image(data);name='image-'+key+ext;put(dest/name,data)
            unique[key]={'path':name,'sha256':key,'bytes':len(data),'size':size,'sources':[]}
        if source not in unique[key]['sources']:unique[key]['sources'].append(source)
    outputs=list(unique.values())
    if not outputs:raise ValueError('NO_RETURN_IMAGE_BYTES: raw result retained; do not resend')
    if selected_index is None:
        if len(outputs)!=1:raise ValueError('MULTIPLE_RETURNED_IMAGES: select explicit index; raw and images retained')
        selected_index=0
    if type(selected_index) is not int or not 0<=selected_index<len(outputs):raise ValueError('INVALID_RETURN_SELECTION')
    receipt={'policy':'observed_image_return_v1','raw':{'path':'raw-return.json','sha256':sha(raw)},
             'outputs':outputs,'selected_index':selected_index,'image_calls':0,'visual_review':'UNREVIEWED'}
    put(dest/'receipt.json',(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n').encode())
    return receipt
