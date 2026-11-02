"""Portable boundary records. They are evidence for A, not automatic approval."""
import hashlib,json,os,shutil,tempfile
from pathlib import Path
from platform_io import atomic_json,file_lock,portable_relative

POLICY='handoff_costume_continuity_v1'

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def row_references(row):
    refs=[]
    if row.get('identity_reference'):refs.append(row['identity_reference'])
    if row.get('verification_status')=='CONFIRMED':refs.append(row['reference'])
    return refs

def record_references(record):
    refs={}
    for row in record.get('characters',[]):
        for ref in row_references(row):
            portable_relative(ref.get('path'))
            prior=refs.get(ref['path'])
            if prior and prior!=ref:raise ValueError('CONTINUITY_CONFLICT: one image path has conflicting hashes')
            refs[ref['path']]=ref
    return list(refs.values())

def require_format_policy(index,record):
    from asset_format import POLICY as FORMAT
    if any(e.get('asset_format_policy')==FORMAT for e in index.get('episodes',[])) and record.get('asset_format_policy')!=FORMAT:
        raise ValueError('ASSET_FORMAT_HOLD: new package boundary must retain format policy')

def validate(record,root):
    root=Path(root).resolve()
    if record.get('policy')!=POLICY or not all(record.get(k) for k in ('book_id','next_episode_id','source_package_id','characters')):
        raise ValueError('CONTINUITY_HOLD: boundary identity missing')
    from asset_format import POLICY as FORMAT, review_errors
    if record.get("asset_format_policy") not in (None,FORMAT):raise ValueError("ASSET_FORMAT_HOLD: unknown boundary format policy")
    ids=set()
    for row in record['characters']:
        cid=row.get('character_id')
        if not cid or cid in ids or row.get('verification_status') not in ('CONFIRMED','UNRESOLVED'):
            raise ValueError('CONTINUITY_HOLD: character duplicate or status invalid')
        ids.add(cid)
        if row['verification_status']=='UNRESOLVED':continue
        if not all(row.get(k) for k in ('costume_id','appearance_state_id','identity_basis','last_confirmed_source_panel','applicability','reference')):
            raise ValueError('CONTINUITY_HOLD: confirmed state missing evidence')
        if record.get("asset_format_policy")==FORMAT:
            errors=review_errors(row.get("format_review"),row["reference"].get("sha256"))
            if errors:raise ValueError(";".join(errors))
    for ref in record_references(record):
        if Path(ref['path']).suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}:raise ValueError('CONTINUITY_HOLD: reference must be an image')
        p=(root/ref['path']).resolve()
        if not p.is_relative_to(root) or not p.is_file() or sha(p)!=ref.get('sha256'):
            raise ValueError('CONTINUITY_HOLD: reference missing or changed: '+ref['path'])
    return {'status':'BOUNDARY_EVIDENCE_VALID','book_id':record['book_id'],
            'next_episode_id':record['next_episode_id'],'not_approval':True}

def publish(root,record,staged_root,*,release_receipt):
    root=Path(root).resolve();staged_root=Path(staged_root).resolve()
    validate(record,staged_root)
    if (release_receipt.get('status')!='RELEASED_DIRECT_DELIVERY_ZIP' or
        release_receipt.get('package_id')!=record['source_package_id'] or not release_receipt.get('sha256')):
        raise ValueError('CONTINUITY_HOLD: matching formal release required')
    from handoff_zip import check_delivery_archive,zip_inventory,read_zip_json,INDEX
    import zipfile
    archive=Path(release_receipt.get('zip','')).resolve()
    if not archive.is_file() or sha(archive)!=release_receipt['sha256']:
        raise ValueError('CONTINUITY_HOLD: released archive missing or changed')
    check_delivery_archive(archive)
    with zipfile.ZipFile(archive) as z:
        top,manifest=zip_inventory(z);idx=read_zip_json(z,top+'/'+INDEX)
        if idx.get('package_id')!=record['source_package_id']:
            raise ValueError('CONTINUITY_HOLD: release package identity mismatch')
        require_format_policy(idx,record)
        ref=idx.get('continuity_boundary')
        if not isinstance(ref,dict) or not ref.get('path') or not ref.get('sha256'):
            raise ValueError('CONTINUITY_HOLD: package does not bind boundary')
        portable_relative(ref['path']);raw=z.read(top+'/'+ref['path'])
        if hashlib.sha256(raw).hexdigest()!=ref['sha256'] or json.loads(raw)!=record:
            raise ValueError('CONTINUITY_HOLD: package boundary mismatch')
        inventory={x['path']:x for x in manifest['files']}
        for r in record_references(record):
            item=inventory.get(r['path'])
            if not item or item['sha256']!=r['sha256']:
                raise ValueError('CONTINUITY_HOLD: package missing reference')
    directory=root/'跨交接衔接';directory.mkdir(parents=True,exist_ok=True)
    # Stable hash-derived names avoid unsafe book/episode strings in paths.
    key=hashlib.sha256((record['book_id']+'\0'+record['next_episode_id']).encode()).hexdigest()[:24]
    content=json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode(); version=hashlib.sha256(content).hexdigest()
    target=directory/key/version
    with file_lock(directory/'索引.lock'):
        index_path=directory/'索引.json';index=json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else {'policy':POLICY,'entries':[]}
        if index.get('policy')!=POLICY:raise ValueError('CONTINUITY_HOLD: index policy')
        entry={'book_id':record['book_id'],'next_episode_id':record['next_episode_id'],'source_package_id':record['source_package_id'],
               'record_sha256':version,'directory':key+'/'+version,'release_sha256':release_receipt['sha256']}
        existing=[x for x in index['entries'] if x['book_id']==record['book_id'] and x['next_episode_id']==record['next_episode_id'] and x['source_package_id']==record['source_package_id']]
        if existing and existing[0]!=entry:raise ValueError('CONTINUITY_CONFLICT: same source package changed')
        if not target.exists():
            target.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(dir=target.parent,prefix='.continuity-') as tmp:
                stage=Path(tmp)/'data';stage.mkdir()
                for ref in record_references(record):
                    dst=stage/ref['path'];dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(staged_root/ref['path'],dst)
                atomic_json(stage/'状态.json',record);validate(record,stage);os.replace(stage,target)
        saved_record=json.loads((target/'状态.json').read_text(encoding='utf-8'))
        if saved_record!=record:raise ValueError('CONTINUITY_CONFLICT: saved record changed')
        # Missing files can be restored from this verified formal ZIP; never replace altered originals.
        for ref in record_references(record):
            dest=target/ref['path']
            if dest.exists():
                if not dest.is_file() or sha(dest)!=ref['sha256']:raise ValueError('CONTINUITY_CONFLICT: saved image changed')
                continue
            dest.parent.mkdir(parents=True,exist_ok=True)
            fd,temp=tempfile.mkstemp(prefix='.restore-',dir=dest.parent);os.close(fd)
            try:
                with (staged_root/ref['path']).open('rb') as src,open(temp,'wb') as out:
                    shutil.copyfileobj(src,out);out.flush();os.fsync(out.fileno())
                if sha(temp)!=ref['sha256']:raise ValueError('CONTINUITY_HOLD: restored image hash mismatch')
                try:os.link(temp,dest)
                except FileExistsError:
                    if not dest.is_file() or sha(dest)!=ref['sha256']:raise ValueError('CONTINUITY_CONFLICT: restore raced')
            finally:
                if os.path.exists(temp):os.unlink(temp)
        validate(saved_record,target)
        if not existing:index['entries'].append(entry);atomic_json(index_path,index)
    return {'status':'CONTINUITY_PUBLISHED','entry':entry}

def resolve(root,book_id,next_episode_id,*,source_package_id=None):
    directory=Path(root).resolve()/'跨交接衔接';path=directory/'索引.json'
    if not path.is_file():return {'status':'NO_BOUNDARY','characters':[]}
    index=json.loads(path.read_text(encoding='utf-8'))
    if index.get('policy')!=POLICY:raise ValueError('CONTINUITY_HOLD: index policy')
    matches=[e for e in index['entries'] if e['book_id']==book_id and e['next_episode_id']==next_episode_id and (source_package_id is None or e['source_package_id']==source_package_id)]
    if len(matches)>1:return {'status':'CONTINUITY_CONFLICT','candidates':matches}
    if not matches:return {'status':'NO_BOUNDARY','characters':[]}
    entry=matches[0];portable_relative(entry['directory']);base=(directory/entry['directory']).resolve()
    if not base.is_relative_to(directory.resolve()):raise ValueError('CONTINUITY_HOLD: directory escape')
    record=json.loads((base/'状态.json').read_text(encoding='utf-8'))
    actual=hashlib.sha256(json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if actual!=entry['record_sha256']:raise ValueError('CONTINUITY_HOLD: record changed')
    characters=record.get('characters',[])
    ids=[r.get('character_id') for r in characters]
    if not ids or len(ids)!=len(set(ids)) or not all(ids):raise ValueError('CONTINUITY_HOLD: missing or duplicate characters')
    issues=[]
    for row in characters:
        try:validate({**record,'characters':[row]},base)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            issues.append({'character_id':row.get('character_id'),'reason':str(exc)})
    checked={**record,'characters':[
        ({**row,'verification_status':'UNRESOLVED','reason':next(x['reason'] for x in issues if x['character_id']==row.get('character_id'))}
         if any(x['character_id']==row.get('character_id') for x in issues) else row)
        for row in record.get('characters',[])]}
    return {'status':'PARTIAL_HOLD' if issues else 'CANDIDATE_FOR_A','record':checked,'record_root':str(base),
            'issues':issues,'not_approval':True}

def stage_boundary(package_root,record,*,expected_index_sha256,source_root=None):
    """Add evidence to an unapproved candidate; the signed index is written last."""
    from handoff_zip import INDEX
    root=Path(package_root).resolve();index_path=root/INDEX
    source_root=Path(source_root).resolve() if source_root else root
    if not root.is_dir() or not index_path.is_file():raise ValueError('CONTINUITY_HOLD: candidate index missing')
    if (root/'接包入口.md').exists() or (root/'演练与导出确认').exists():
        raise ValueError('CONTINUITY_HOLD: formally released package is immutable')
    with file_lock(root.parent/('.'+root.name+'.continuity-boundary.lock')):
        index=json.loads(index_path.read_text(encoding='utf-8-sig'))
        if record.get('book_id')!=index.get('book_id') or record.get('source_package_id')!=index.get('package_id'):
            raise ValueError('CONTINUITY_HOLD: boundary book or package mismatch')
        prior=index.get('continuity_boundary')
        if prior:
            portable_relative(prior['path']);saved=(root/prior['path']).resolve()
            if saved.is_relative_to(root) and saved.is_file() and sha(saved)==prior['sha256'] and json.loads(saved.read_text(encoding='utf-8-sig'))==record:
                validate(record,root)
                return {'status':'ALREADY_STAGED_NOT_APPROVED','boundary':prior,'index_sha256':sha(index_path)}
            raise ValueError('CONTINUITY_CONFLICT: candidate boundary differs')
        if sha(index_path)!=expected_index_sha256:raise ValueError('CONTINUITY_CONFLICT: candidate index changed')
        if record.get('book_id')!=index.get('book_id') or record.get('source_package_id')!=index.get('package_id'):
            raise ValueError('CONTINUITY_HOLD: boundary book or package mismatch')
        if index.get('continuity_boundary'):raise ValueError('CONTINUITY_CONFLICT: candidate already has boundary')
        for ref in record_references(record):
            target=(root/ref['path']).resolve();source=(source_root/ref['path']).resolve()
            if not target.is_relative_to(root) or not source.is_relative_to(source_root):raise ValueError('CONTINUITY_HOLD: reference escapes root')
            if target.exists():
                if not target.is_file() or sha(target)!=ref['sha256']:raise ValueError('CONTINUITY_CONFLICT: reference changed')
            else:
                if not source.is_file() or sha(source)!=ref['sha256']:raise ValueError('CONTINUITY_HOLD: source reference missing')
                target.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(prefix='.boundary-',dir=target.parent);os.close(fd)
                try:
                    shutil.copyfile(source,tmp)
                    if sha(tmp)!=ref['sha256']:raise ValueError('CONTINUITY_HOLD: copied reference mismatch')
                    try:os.link(tmp,target)
                    except FileExistsError:
                        if not target.is_file() or sha(target)!=ref['sha256']:raise ValueError('CONTINUITY_CONFLICT: reference raced')
                finally:
                    if os.path.exists(tmp):os.unlink(tmp)
        validate(record,root)
        raw=(json.dumps(record,ensure_ascii=False,indent=2)+'\n').encode('utf-8');digest=hashlib.sha256(raw).hexdigest()
        dest=root/'跨交接衔接'/('状态_'+digest+'.json');dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists() and sha(dest)!=digest:raise ValueError('CONTINUITY_CONFLICT: boundary file changed')
        if not dest.exists():atomic_json(dest,record)
        if sha(dest)!=digest:raise ValueError('CONTINUITY_HOLD: boundary file mismatch')
        index['continuity_boundary']={'path':dest.relative_to(root).as_posix(),'sha256':digest}
        atomic_json(index_path,index)
    return {'status':'BOUNDARY_STAGED_NOT_APPROVED','boundary':index['continuity_boundary'],'index_sha256':sha(index_path)}

def reconcile(boundary, episode_id, panel_order, observations):
    """Apply explicit script observations in source order; conflicts stay local."""
    if boundary.get('policy')!=POLICY or boundary.get('next_episode_id')!=episode_id or not panel_order or len(set(panel_order))!=len(panel_order):
        raise ValueError('CONTINUITY_HOLD: episode or panel order mismatch')
    by_panel={p:[] for p in panel_order}
    for obs in observations:
        if obs.get('panel_id') not in by_panel or not obs.get('character_id') or not obs.get('source_evidence') or obs.get('decision') not in ('INHERIT','CHANGE','CONFLICT'):
            raise ValueError('CONTINUITY_HOLD: invalid script observation')
        by_panel[obs['panel_id']].append(obs)
    state={r['character_id']:r for r in boundary['characters']};output=[]
    for pid in panel_order:
        for obs in by_panel[pid]:
            cid=obs['character_id'];prior=state.get(cid)
            if obs['decision']=='CONFLICT':
                state[cid]={**(prior or {}),'character_id':cid,'verification_status':'UNRESOLVED','reason':obs['source_evidence']}
            elif obs['decision']=='CHANGE':
                if not obs.get('costume_id') or not obs.get('appearance_state_id') or not obs.get('reference'):
                    raise ValueError('CONTINUITY_HOLD: change missing state or reference')
                state[cid]={'character_id':cid,'verification_status':'CONFIRMED','costume_id':obs['costume_id'],
                            'appearance_state_id':obs['appearance_state_id'],'reference':obs['reference'],'source_evidence':obs['source_evidence']}
            elif prior and any(obs.get(k) is not None and obs[k]!=prior.get(k) for k in ('costume_id','appearance_state_id','reference')):
                state[cid]={**prior,'character_id':cid,'verification_status':'UNRESOLVED','reason':'INHERIT contradicts prior state','previous_confirmed_state':prior}
            elif not prior or prior.get('verification_status')!='CONFIRMED':
                state[cid]={**(prior or {}),'character_id':cid,'verification_status':'UNRESOLVED','reason':'inheritance has no confirmed source'}
            output.append({'panel_id':pid,'character_id':cid,'decision':obs['decision'],'state':state[cid]})
    return {'status':'CANDIDATE_TRANSITIONS_NOT_APPROVAL','book_id':boundary['book_id'],'episode_id':episode_id,'bindings':output}

def publish_from_archive(asset_root, archive):
    """Replay boundary publication from an already formally released archive."""
    import zipfile
    from handoff_zip import check_delivery_archive,zip_inventory,read_zip_json,INDEX
    archive=Path(archive).resolve();check_delivery_archive(archive)
    with zipfile.ZipFile(archive) as z:
        top,_=zip_inventory(z);index=read_zip_json(z,top+'/'+INDEX)
        ref=index.get('continuity_boundary')
        if not ref:return {'status':'NO_BOUNDARY_IN_PACKAGE'}
        portable_relative(ref['path']);data=z.read(top+'/'+ref['path'])
        if hashlib.sha256(data).hexdigest()!=ref['sha256']:raise ValueError('CONTINUITY_HOLD: boundary digest mismatch')
        record=json.loads(data)
        receipt={'status':'RELEASED_DIRECT_DELIVERY_ZIP','package_id':index['package_id'],'zip':str(archive),'sha256':sha(archive)}
        with tempfile.TemporaryDirectory(prefix='comic-continuity-') as tmp:
            stage=Path(tmp)
            for reference in record_references(record):
                target=stage/reference['path'];target.parent.mkdir(parents=True,exist_ok=True)
                with z.open(top+'/'+reference['path']) as source,target.open('wb') as dest:shutil.copyfileobj(source,dest)
            return publish(asset_root,record,stage,release_receipt=receipt)

def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    q=sub.add_parser('resolve');q.add_argument('--asset-root',required=True);q.add_argument('--book',required=True);q.add_argument('--next-episode',required=True);q.add_argument('--source-package')
    q=sub.add_parser('publish');q.add_argument('--asset-root',required=True);q.add_argument('--record',required=True);q.add_argument('--staged-root',required=True);q.add_argument('--release-receipt',required=True)
    q=sub.add_parser('recover');q.add_argument('--asset-root',required=True);q.add_argument('--zip',required=True)
    q=sub.add_parser('stage');q.add_argument('--package-root',required=True);q.add_argument('--record',required=True);q.add_argument('--expected-index',required=True);q.add_argument('--source-root')
    q=sub.add_parser('reconcile');q.add_argument('--input',required=True);q.add_argument('--output',required=True)
    a=p.parse_args()
    if a.action=='resolve':result=resolve(a.asset_root,a.book,a.next_episode,source_package_id=a.source_package)
    elif a.action=='recover':result=publish_from_archive(a.asset_root,a.zip)
    elif a.action=='stage':result=stage_boundary(a.package_root,json.loads(Path(a.record).read_text(encoding='utf-8-sig')),expected_index_sha256=a.expected_index,source_root=a.source_root)
    elif a.action=='reconcile':
        data=json.loads(Path(a.input).read_text(encoding='utf-8-sig'))
        result=reconcile(data['boundary'],data['episode_id'],data['panel_order'],data['observations'])
        output=Path(a.output)
        if output.exists():raise ValueError('CONTINUITY_HOLD: output exists')
        atomic_json(output,result)
    else:result=publish(a.asset_root,json.loads(Path(a.record).read_text(encoding='utf-8-sig')),a.staged_root,release_receipt=json.loads(Path(a.release_receipt).read_text(encoding='utf-8-sig')))
    print(json.dumps(result,ensure_ascii=False))
    return 1 if result.get('status') in {'PARTIAL_HOLD','CONTINUITY_CONFLICT','CONTINUITY_HOLD','ASSET_HOLD'} else 0
if __name__=='__main__':
    from platform_io import configure_stdio
    configure_stdio()
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,TypeError) as exc:
        import json
        print(json.dumps({'status':'CONTINUITY_HOLD','error':str(exc)},ensure_ascii=False))
        raise SystemExit(1)
