"""Append reviewed assets with immutable objects and a locked, replayable index."""
import hashlib,json,os,shutil,tempfile
from pathlib import Path
from platform_io import atomic_json,file_lock,portable_relative

POLICY='costume_asset_append_v1'

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def _validate_new_record(root,record,source,reuse_plan):
    if not source.is_file():raise ValueError("ASSET_PUBLICATION_HOLD: source missing")
    for key in ('book_id','asset_id','character_id','costume_id','authorization','review','source_basis','future_occurrences'):
        if not record.get(key):raise ValueError('ASSET_PUBLICATION_HOLD: missing '+key)
    if record['review'].get('status')!='PASS' or not record['review'].get('evidence') or not record['review'].get('reviewer'):
        raise ValueError('ASSET_PUBLICATION_HOLD: actual review required')
    if record['authorization'].get('source_kind')!='user_message' or not record['authorization'].get('source_locator') or not record['authorization'].get('quote'):
        raise ValueError('ASSET_PUBLICATION_HOLD: scoped authorization required')
    from costume_requirements import plan as recalculate
    if reuse_plan.get('book_id')!=record['book_id'] or reuse_plan.get('production_episode_ids')!=record.get('production_episode_ids'):
        raise ValueError('ASSET_PUBLICATION_HOLD: reuse plan scope mismatch')
    raw=[r for r in reuse_plan['input_requirements'] if r.get('character_id')==record['character_id'] and r.get('costume_id')==record['costume_id']]
    matches=recalculate(reuse_plan['book_id'],reuse_plan['production_episode_ids'],raw,reuse_plan['observations'],coverage=reuse_plan['coverage'],source_catalog=reuse_plan['source_catalog'])['requirements']
    if not matches or not any(r['publication_required'] and r['future_occurrences']==record['future_occurrences'] for r in matches):
        raise ValueError('ASSET_PUBLICATION_HOLD: no matching verified reuse plan')
    if record.get('policy')!=POLICY or len({(x['episode_id'],x['panel_id']) for x in record['future_occurrences']})<2:
        raise ValueError('ASSET_PUBLICATION_HOLD: confirmed future reuse required')
    if any(x.get('match')!='CONFIRMED' or x.get('visible') is not True or not x.get('evidence') or not x.get('source_sha256') for x in record['future_occurrences']):
        raise ValueError('ASSET_PUBLICATION_HOLD: incomplete reuse evidence')
    digest=sha(source)
    from asset_format import review_errors
    format_errors=review_errors(record.get("format_review"),digest)
    if format_errors:raise ValueError(";".join(format_errors))
    auth=record['authorization']; review=record['review']
    if (auth.get('book_id')!=record['book_id'] or record['asset_id'] not in auth.get('asset_ids',[]) or
        'publish' not in auth.get('operations',[]) or not auth.get('episode_ids')):
        raise ValueError('ASSET_PUBLICATION_HOLD: authorization scope mismatch')
    if review.get('asset_id')!=record['asset_id'] or review.get('image_sha256')!=digest:
        raise ValueError('ASSET_PUBLICATION_HOLD: review image mismatch')
    current=record.get('production_episode_ids')
    if not current or any(not isinstance(x,str) or not x.startswith('E') or not x[1:].isdigit() for x in current):
        raise ValueError('ASSET_PUBLICATION_HOLD: production scope missing')
    if not set(current).intersection(auth['episode_ids']):raise ValueError('ASSET_PUBLICATION_HOLD: authorization episode scope mismatch')
    last=max(int(x[1:]) for x in current)
    if any(x.get('character_id')!=record['character_id'] or x.get('costume_id')!=record['costume_id'] or
           not isinstance(x.get('episode_id'),str) or not x['episode_id'].startswith('E') or
           not x['episode_id'][1:].isdigit() or int(x['episode_id'][1:])<=last or not x.get('panel_id')
           for x in record['future_occurrences']):
        raise ValueError('ASSET_PUBLICATION_HOLD: future occurrence scope mismatch')
    if digest!=record.get('sha256'):raise ValueError('ASSET_PUBLICATION_HOLD: source hash mismatch')
    return digest

def publish(root,record,source,*,reuse_plan):
    root=Path(root).resolve();source=Path(source).resolve()
    if not root.is_dir() or not isinstance(record,dict):raise ValueError('ASSET_PUBLICATION_HOLD: root or record invalid')
    name=record.get('relative_path');portable_relative(name);dest=(root/name).resolve()
    if not dest.is_relative_to(root):raise ValueError('ASSET_PUBLICATION_HOLD: destination escape')
    record_bytes=json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    record_digest=hashlib.sha256(record_bytes).hexdigest()
    proof_digest=hashlib.sha256(json.dumps(reuse_plan,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    meta=root/'07_元数据';meta.mkdir(exist_ok=True);index=meta/'衣装增量索引.json'
    receipt_dir=meta/'资产发布记录';receipt=receipt_dir/(record_digest+'.json')
    expected_receipt={'policy':POLICY,'record_sha256':record_digest,'reuse_plan_sha256':proof_digest,'record':record}
    with file_lock(meta/'衣装增量索引.lock'):
        data=json.loads(index.read_text(encoding='utf-8')) if index.exists() else {'policy':POLICY,'entries':[]}
        if data.get('policy')!=POLICY:raise ValueError('ASSET_PUBLICATION_HOLD: index policy')
        hits=[x for x in data['entries'] if x['asset_id']==record.get('asset_id')]
        if hits:
            if hits[0]!=record or not dest.is_file() or sha(dest)!=record.get('sha256'):raise ValueError('ASSET_PUBLICATION_CONFLICT')
            return {'status':'ALREADY_PUBLISHED','reference':name,'sha256':record['sha256']}
        durable=False
        if receipt.exists():
            saved=json.loads(receipt.read_text(encoding='utf-8'))
            if saved!=expected_receipt:raise ValueError('ASSET_PUBLICATION_CONFLICT: saved transaction changed')
            durable=dest.is_file() and sha(dest)==record.get('sha256')
        digest=record.get('sha256') if durable else _validate_new_record(root,record,source,reuse_plan)
        same=[x for x in data['entries'] if x.get('book_id')==record['book_id'] and x.get('character_id')==record['character_id'] and x.get('costume_id')==record['costume_id']]
        if same and (record.get('supersedes') not in {x['asset_id'] for x in same} or not record.get('revision_reason')):
            raise ValueError('ASSET_PUBLICATION_CONFLICT: same costume already exists; reuse or specify revision evidence')
        if any(x['relative_path']==name for x in data['entries']):raise ValueError('ASSET_PUBLICATION_CONFLICT: path already indexed')
        if dest.exists() and (not dest.is_file() or sha(dest)!=digest):raise ValueError('ASSET_PUBLICATION_CONFLICT: destination exists')
        receipt_dir.mkdir(exist_ok=True)
        if not receipt.exists():atomic_json(receipt,expected_receipt)
        if not dest.exists():
            dest.parent.mkdir(parents=True,exist_ok=True)
            fd,tmp=tempfile.mkstemp(prefix='.asset-',dir=dest.parent);os.close(fd)
            try:
                with source.open('rb') as src,open(tmp,'wb') as target:
                    shutil.copyfileobj(src,target);target.flush();os.fsync(target.fileno())
                if sha(tmp)!=digest:raise ValueError('ASSET_PUBLICATION_HOLD: copy mismatch')
                try:os.link(tmp,dest)
                except FileExistsError:
                    if not dest.is_file() or sha(dest)!=digest:raise ValueError('ASSET_PUBLICATION_CONFLICT: destination raced')
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
        data['entries'].append(record);atomic_json(index,data)
    return {'status':'PUBLISHED','reference':name,'sha256':digest}

def list_assets(root, *, book_id, character_id=None):
    root=Path(root).resolve();index=root/'07_元数据/衣装增量索引.json'
    if not index.is_file():return []
    data=json.loads(index.read_text(encoding='utf-8-sig'))
    if data.get('policy')!=POLICY:raise ValueError('ASSET_PUBLICATION_HOLD: index policy')
    found=[]
    for row in data.get('entries',[]):
        if row.get('book_id')!=book_id or character_id and row.get('character_id')!=character_id:continue
        portable_relative(row['relative_path']);p=(root/row['relative_path']).resolve()
        if not p.is_relative_to(root) or not p.is_file() or sha(p)!=row['sha256']:
            found.append({**row,'file_status':'MISSING_OR_CHANGED'})
        else:found.append({**row,'file_status':'VERIFIED_NOT_VISUALLY_REVIEWED'})
    return found

def match_candidates(root, *, book_id, character_id, index_references):
    """Search explicitly selected index evidence; return candidates only."""
    root=Path(root).resolve();results=[];seen=set()
    for ref in index_references:
        portable_relative(ref.get('path'));path=(root/ref['path']).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha(path)!=ref.get('sha256'):
            raise ValueError('ASSET_MATCH_HOLD: selected index missing or changed')
        data=json.loads(path.read_text(encoding='utf-8-sig'))
        if data.get('book',data.get('book_id'))!=book_id:raise ValueError('ASSET_MATCH_HOLD: book mismatch')
        for key in ('assets','new_assets','canonical_promotions','current_use_overrides'):
            for row in data.get(key,[]):
                name=row.get('canonical_file') or row.get('relative_path');owner=row.get('subject_id') or row.get('character_id') or row.get('asset_id')
                if not name:continue
                # Filename is merely a lookup hint, never a confirmed identity.
                strength='EXACT_ID' if owner==character_id else 'FILENAME_HINT' if character_id in Path(name).name else None
                if not strength:continue
                portable_relative(name);image=(root/name).resolve();expected=row.get('sha256','').lower()
                status='MISSING_OR_CHANGED'
                if image.is_relative_to(root) and image.is_file() and expected and sha(image)==expected:status='FILE_HASH_VERIFIED'
                token=(name,expected,ref['path'])
                if token in seen:continue
                seen.add(token);results.append({'character_id':character_id,'match_strength':strength,'reference':{'path':name,'sha256':expected},
                    'file_status':status,'source_index':ref,'source_status':row.get('status'),'metadata':row,
                    'selection':'CANDIDATE_NOT_APPROVED'})
    for row in list_assets(root,book_id=book_id,character_id=character_id):
        results.append({'character_id':character_id,'match_strength':'EXACT_ID','reference':{'path':row['relative_path'],'sha256':row['sha256']},
                        'file_status':row['file_status'],'metadata':row,'selection':'CANDIDATE_NOT_APPROVED'})
    return results

def publish_batch(root,entries):
    """Publish independently reviewed states; one blocked state cannot stop others."""
    if not isinstance(entries,list):raise ValueError('ASSET_PUBLICATION_HOLD: batch must be a list')
    results=[]
    for entry in entries:
        try:
            if not isinstance(entry,dict):raise ValueError('batch entry must be object')
            result=publish(root,entry['record'],entry['source'],reuse_plan=entry['reuse_plan'])
        except (OSError,ValueError,KeyError,TypeError) as exc:
            result={'status':'ASSET_HOLD','error':str(exc)}
        row=entry.get('record',{}) if isinstance(entry,dict) else {}
        results.append({'asset_id':row.get('asset_id') if isinstance(row,dict) else None,**result})
    return {'status':'BATCH_COMPLETED' if all(x['status'] in ('PUBLISHED','ALREADY_PUBLISHED') for x in results) else 'PARTIAL_HOLD','results':results}

def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--asset-root',required=True);p.add_argument('--batch');p.add_argument('--record');p.add_argument('--source');p.add_argument('--reuse-plan');p.add_argument('--book');p.add_argument('--character');p.add_argument('--indices');a=p.parse_args()
    if a.batch:
        if a.book or a.record or a.source or a.reuse_plan:raise ValueError('cannot combine batch and other modes')
        result=publish_batch(a.asset_root,json.loads(Path(a.batch).read_text(encoding='utf-8-sig')))
    elif a.book:
        if a.record or a.source:raise ValueError('cannot combine list and publish')
        if a.indices:
            if not a.character:raise ValueError('character required for historical candidates')
            refs=json.loads(Path(a.indices).read_text(encoding='utf-8-sig'))
            result={'status':'CANDIDATES_NOT_APPROVAL','assets':match_candidates(a.asset_root,book_id=a.book,character_id=a.character,index_references=refs)}
        else:result={'status':'CANDIDATES_NOT_APPROVAL','assets':list_assets(a.asset_root,book_id=a.book,character_id=a.character)}
    else:
        if not a.record or not a.source or not a.reuse_plan:raise ValueError('record, source and reuse-plan required')
        result=publish(a.asset_root,json.loads(Path(a.record).read_text(encoding='utf-8-sig')),a.source,reuse_plan=json.loads(Path(a.reuse_plan).read_text(encoding='utf-8-sig')))
    print(json.dumps(result,ensure_ascii=False))
    return 1 if result.get('status') in {'PARTIAL_HOLD','CONTINUITY_CONFLICT','CONTINUITY_HOLD','ASSET_HOLD'} else 0
if __name__=='__main__':
    from platform_io import configure_stdio
    configure_stdio()
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,TypeError) as exc:
        import json
        print(json.dumps({'status':'ASSET_PUBLICATION_HOLD','error':str(exc)},ensure_ascii=False))
        raise SystemExit(1)
