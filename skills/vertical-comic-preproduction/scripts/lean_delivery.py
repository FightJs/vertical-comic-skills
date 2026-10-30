"""Incremental image delivery. No creative gate, image service, or inferred QA."""
from pathlib import Path
import copy, hashlib, io, json, os, time, zipfile
from platform_io import atomic_json

PROFILE = 'minimal_panel_delivery_v1'
MATERIAL = 'observed_delivery_material_v1'
CSV = '图片清单.csv'
_VERIFIED = {}


def enabled(value):
    return value.get('completion_profile') == PROFILE


def stamp(path):
    s = Path(path).stat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def binding(row):
    return {k:copy.deepcopy(row.get(k)) for k in ('panel_id','source_panel_id','attempt_id','status','output','qa_report','adoption',
            'content_refusal_delivery','network_retry_exhausted')}


def adopt(state, row, decision, *, image_verified=True):
    """Called only after the existing observed-review transaction validates."""
    from production_decisions import outcome
    old=state.get('delivery_materials',{}).get(row['panel_id'],{})
    material={**old,'policy':MATERIAL,'source_panel_id':row.get('source_panel_id',row['panel_id']),
        'attempt_id':row['adoption']['attempt_id'],'image':copy.deepcopy(row['output']),
        'qa_report':copy.deepcopy(row['qa_report']),'decision':copy.deepcopy(row['adoption']['decision']),
        'issues':copy.deepcopy(decision.get('issues',[])), 'outcome':outcome(decision),
        'image_verified':bool(image_verified),'binding':binding(row)}
    state.setdefault('delivery_materials',{})[row['panel_id']]=material


def gap(state, row, kind, summary):
    state.setdefault('delivery_materials',{})[row['panel_id']]={
        'policy':MATERIAL,'source_panel_id':row.get('source_panel_id',row['panel_id']),
        'attempt_id':row['attempt_id'],'outcome':kind,'summary':summary,'binding':binding(row)}


def import_materials(state, root):
    """Once at explicit import, validate adopted historical metadata, never re-review."""
    from production_decisions import selected
    from no_image_recovery import content_refusal, network_exhaustion, content_missing_summary, network_missing_summary
    from PIL import Image
    for row in state['panels']:
        old=state.get('delivery_materials',{}).get(row['panel_id'],{})
        if old.get('policy')==MATERIAL and old.get('binding')==binding(row):continue
        if row.get('adoption'):
            attempt,decision,_,_=selected(root,row)
            image=Path(root)/attempt['output']['path']
            with Image.open(image) as opened:opened.verify()
            # selected validates QA/image identities; image bytes are hash checked while packing.
            view={**row,**{k:attempt[k] for k in ('output','qa_report')},'adoption':row['adoption']}
            adopt(state,view,decision)
            state['delivery_materials'][row['panel_id']]['binding']=binding(row)
        elif row.get('content_refusal_delivery'):
            gap(state,row,'CONTENT_REFUSED',content_missing_summary(content_refusal(state,root,row)))
        elif row.get('network_retry_exhausted'):
            gap(state,row,'NETWORK_FAILED',network_missing_summary(network_exhaustion(state,root,row)))


def inventory(value):
    """Read only source order and the incremental material projection, never history."""
    from delivery_contract import read, checked, fingerprint
    from delivery_csv import encode
    files={};rows=[];states={};sources={};gaps={'network_missing_panel_ids':[],'content_refused_panel_ids':[]}
    for sp,scope in zip(value['states'],value['scope']):
        raw=Path(sp).read_bytes();state=json.loads(raw.decode('utf-8-sig'));root=Path(sp).parent.parent
        states[sp]=hashlib.sha256(raw).hexdigest()
        if [state['book_id'],state['episode_id']]!=scope or state.get('cancelled') or state.get('holds'):
            raise ValueError('LEAN_SCOPE_OR_HOLD')
        src=state['source_snapshot'];source_path=Path(src['path']);source_path=source_path if source_path.is_absolute() else root/source_path
        source=read(checked({'path':str(source_path.resolve()),'sha256':src['sha256']}))
        sources[str(source_path.resolve())]=stamp(source_path)
        order=source['panel_ids'];records=state['panels']
        if len(set(order))!=len(order) or [r['panel_id'] for r in records]!=order:
            raise ValueError('LEAN_SOURCE_ORDER_CHANGED')
        mapping={r['panel_id']:r['source_panel_id'] for r in source.get('id_mapping',{}).get('pairs',[])}
        seen=set()
        for row in records:
            pid=row['panel_id'];m=state.get('delivery_materials',{}).get(pid,{})
            if m.get('policy')!=MATERIAL or m.get('binding')!=binding(row):
                raise ValueError('LEAN_MATERIAL_MISSING_OR_CHANGED:'+pid)
            source_id=m['source_panel_id']
            if source_id!=mapping.get(pid,pid) or source_id in seen:raise ValueError('LEAN_SOURCE_MAPPING:'+pid)
            seen.add(source_id)
            if row['status'] in {'PENDING','IN_FLIGHT','GENERATED','REPAIR_AUTHORIZED','RESULT_UNKNOWN','CANCELLED'}:
                raise ValueError('LEAN_UNFINISHED:'+pid)
            outcome=m['outcome'];target='';summary=m.get('summary','')
            if outcome in {'CONTENT_REFUSED','NETWORK_FAILED'}:
                key='content_refusal_delivery' if outcome=='CONTENT_REFUSED' else 'network_retry_exhausted'
                if row.get('adoption') or not row.get(key) or not summary:raise ValueError('LEAN_GAP_NOT_RECORDED:'+pid)
                gaps['content_refused_panel_ids' if outcome=='CONTENT_REFUSED' else 'network_missing_panel_ids'].append(state['episode_id']+'-'+pid)
            else:
                if not row.get('adoption') or m.get('attempt_id')!=row['adoption']['attempt_id'] or not m.get('image_verified'):
                    raise ValueError('LEAN_ADOPTION_NOT_VERIFIED:'+pid)
                if any(i.get('story_impact')=='scene_background_missing' for i in m.get('issues',[])):
                    raise ValueError('LEAN_SEVERE_BLANK:'+pid)
                image=m['image'];path=Path(image['path']);path=path if path.is_absolute() else root/path
                path=path.resolve()
                if not path.is_file() or path.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}:raise ValueError('LEAN_IMAGE_MISSING:'+pid)
                eid=state['episode_id']
                for part in (eid,source_id):
                    if not part or part in {'.','..'} or any(c in part for c in '/\\\x00:'):raise ValueError('LEAN_UNSAFE_FILENAME')
                target=eid+'/'+source_id+path.suffix.lower()
                if target in files:raise ValueError('LEAN_DUPLICATE_IMAGE')
                files[target]={'path':str(path),'sha256':image['sha256'],'stamp':stamp(path)}
                summary='；'.join(i.get('problem','') for i in m.get('issues',[]))
            rows.append({'话号':state['episode_id'],'源格号':source_id,'图片路径':target,'交付状态':outcome,'遗留问题或缺图原因':summary})
    csv=encode(('话号','源格号','图片路径','交付状态','遗留问题或缺图原因'),rows)
    return {'files':files,'csv':csv,'states':states,'sources':sources,'total':len(rows),**gaps}


class HashWriter:
    """Non-seekable ZIP output: hash final bytes on their sole write."""
    def __init__(self, stream):self.stream=stream;self.hash=hashlib.sha256();self.size=0
    def write(self,data):
        n=self.stream.write(data)
        if n!=len(data):raise OSError('short ZIP write')
        self.hash.update(data);self.size+=n;return n
    def tell(self):return self.size
    def flush(self):return self.stream.flush()
    def seek(self,*args):raise OSError('streaming ZIP')


def pack(value, out):
    started=time.monotonic();data=inventory(value);out=Path(out);out.mkdir()
    target=out/'成品图片包.zip';members={};read_bytes=0
    with target.open('xb') as stream:
        writer=HashWriter(stream)
        with zipfile.ZipFile(writer,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as z:
            for name,ref in data['files'].items():
                h=hashlib.sha256()
                with open(ref['path'],'rb') as image,z.open(name,'w',force_zip64=True) as dest:
                    for chunk in iter(lambda:image.read(1024*1024),b''):
                        dest.write(chunk);h.update(chunk);read_bytes+=len(chunk)
                if h.hexdigest()!=ref['sha256'] or stamp(ref['path'])!=ref['stamp']:raise ValueError('LEAN_IMAGE_CHANGED:'+name)
                members[name]=h.hexdigest()
            z.writestr(CSV,data['csv']);members[CSV]=hashlib.sha256(data['csv']).hexdigest()
        stream.flush();os.fsync(stream.fileno())
    written=time.monotonic()
    # One readback; ZipExtFile verifies CRC while we check exact member bytes.
    with zipfile.ZipFile(target) as z:
        if len(z.namelist())!=len(members) or set(z.namelist())!=set(members):raise ValueError('LEAN_ZIP_MEMBERS')
        for name,expected in members.items():
            h=hashlib.sha256()
            with z.open(name) as member:
                for chunk in iter(lambda:member.read(1024*1024),b''):h.update(chunk)
            if h.hexdigest()!=expected:raise ValueError('LEAN_ZIP_CONTENT')
    for ref in data['files'].values():
        if stamp(ref['path'])!=ref['stamp']:raise ValueError('LEAN_IMAGE_CHANGED_DURING_PACK')
    for path,saved in data['sources'].items():
        if stamp(path)!=saved:raise ValueError('LEAN_SOURCE_CHANGED_DURING_PACK')
    artifact={'path':str(target.resolve()),'sha256':writer.hash.hexdigest(),'bytes':writer.size}
    remember(artifact)
    return {'artifacts':[artifact],'members':members,
        'source_files':{**{r['path']:r['stamp'][2:] for r in data['files'].values()},**{p:v[2:] for p,v in data['sources'].items()}},
        'content_validation':{
        'status':'PASS','kind':PROFILE,'panel_count':data['total'],'image_count':len(data['files']),
        'images_complete':len(data['files'])==data['total'],
        **{k:data[k] for k in ('network_missing_panel_ids','content_refused_panel_ids')}},
        'lean_timing':{'inventory_and_write_seconds':written-started,'verify_seconds':time.monotonic()-written,
                       'source_image_read_bytes':read_bytes,'creative_gate_calls':0,'zip_readback_passes':1}}


def remember(artifact):
    _VERIFIED[(artifact['path'],artifact['sha256'])]=stamp(artifact['path'])


def check_artifact(artifact):
    """Same process completion is O(1); restart verifies archive hash once."""
    key=(artifact['path'],artifact['sha256']);before=stamp(artifact['path'])
    if before[2]!=artifact['bytes']:raise ValueError('LEAN_ZIP_SIZE_CHANGED')
    if _VERIFIED.get(key)!=before:
        h=hashlib.sha256()
        with open(artifact['path'],'rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
        if h.hexdigest()!=artifact['sha256'] or stamp(artifact['path'])!=before:raise ValueError('LEAN_ZIP_CHANGED')
        _VERIFIED[key]=before


def finish(directory, archive, task, requirements, identity, delivery_report):
    from delivery_contract import assert_completion,reference
    from production_progress import stat,read,fingerprint,refresh
    report=assert_completion(requirements,delivery_report,archive)
    paths=[str(delivery_report),identity['path'],*[r['path'] for r in report['artifacts']]]
    atomic_json(Path(directory)/'delivered.json',{'policy':requirements['policy'],'completion_profile':PROFILE,
        'zip':str(archive),'stat':stat(archive),'delivery_report':reference(delivery_report),'artifacts':report['artifacts'],
        'dependencies':{**report.get('source_files',{}),**{p:stat(p) for p in paths}},'states':{p:fingerprint(read(p)) for p in task['states']},
        **{k:report['content_validation'][k] for k in ('network_missing_panel_ids','content_refused_panel_ids')}})
    result=refresh(directory,activity='图片与CSV已交付',next_action='使用成品图片包')
    if result['percent']!=100:raise ValueError('LEAN_FINISH_CHANGED')
    from runtime_clock import locate,event,release
    clock=locate(directory)
    if clock:event(clock,'finish','minimal-delivery-finished');release(clock)
    result['delivery_artifacts']=report['artifacts'];return result


def progress_snapshot(directory, task, requirements, *, activity=None, next_action=None, wait_kind='NONE'):
    from production_progress import read,stat,fingerprint
    directory=Path(directory);episodes=[];files={};state_keys={};total=0;closed=0;blockers=[]
    for sp in task['states']:
        state=read(sp);files[sp]=stat(sp);state_keys[sp]=fingerprint(state)
        n=len(state['panels']);total+=n;counts={'images':0,'reviewed':0,'adopted':0,'inflight':0,'unknown':0,
            'DELIVERABLE':0,'MANUAL_RETOUCH':0,'MANUAL_PRIORITY':0,'INCOMPLETE':0}
        resolved=0
        for row in state['panels']:
            m=state.get('delivery_materials',{}).get(row['panel_id'],{})
            valid=m.get('policy')==MATERIAL and m.get('binding')==binding(row)
            counts['inflight']+=row['status']=='IN_FLIGHT';counts['unknown']+=row['status']=='RESULT_UNKNOWN'
            if row.get('output'):counts['images']+=1
            if valid:
                resolved+=1
                if m.get('image'):
                    counts['reviewed']+=1;counts['adopted']+=1
                    counts[m.get('outcome','DELIVERABLE')]=counts.get(m.get('outcome','DELIVERABLE'),0)+1
                    path=Path(m['image']['path']);path=path if path.is_absolute() else Path(sp).parent.parent/path
                    files[str(path)]=stat(path)
            else:counts['INCOMPLETE']+=1
        closed+=resolved
        if state.get('holds') or state.get('cancelled'):blockers.append({'scope':state['episode_id'],'reason':'HOLD_OR_CANCELLED'})
        episodes.append({'book_id':state['book_id'],'episode_id':state['episode_id'],'total':n,'counts':counts,
            'stages':{'receive':n,'images':counts['images'],'review':counts['reviewed'],'adoption':resolved,'continuity':resolved,'delivery':0},'blockers':[],'notes':[]})
    units={k:sum(e['stages'].get(k,0) for e in episodes) for k in task['weights']}
    delivered_path=directory/'delivered.json';done=False;gaps={}
    if delivered_path.exists():
        d=read(delivered_path)
        done=(d.get('states')==state_keys and stat(d['zip'])==d['stat'] and
              all(stat(p)==v and v is not None for p,v in d.get('dependencies',{}).items()))
        if done:
            gaps={k:d.get(k,[]) for k in ('network_missing_panel_ids','content_refused_panel_ids')}
            files.update(d['dependencies']);units={k:total for k in units}
    percent=100 if done else min(99,int(95*closed/total)) if total else 0
    snapshot={'policy':task['policy'],'role':'production','target':'图片＋CSV成品ZIP','total':total,
        'percent':percent,'stage':'delivery' if done or closed==total else 'images','stage_units':units,'episodes':episodes,
        'blockers':blockers,'activity':activity or '按逐格已登记结果推进','next':next_action or '继续未完成格',
        'wait_kind':wait_kind,'observed_at':time.time(),'files':files,'not_approval_evidence':True,**gaps}
    if done:snapshot['completion_basis']='AVAILABLE_IMAGES_WITH_AUTHORIZED_FAILURE_GAPS' if any(gaps.values()) else 'FULL_SOURCE_SCOPE_WITH_RECORDED_QA'
    atomic_json(directory/'snapshot.json',snapshot)
    return snapshot


def finalize(identity, output, *, coordination=None):
    """One automatic publish/finish operation, no additional approval files."""
    from delivery_contract import load_identity
    from delivery_publish import publish_production,REPORT
    value=load_identity(identity)
    if not enabled(value):raise ValueError('LEAN_PROFILE_REQUIRED')
    report=publish_production(identity,output)
    coord=Path(coordination) if coordination else Path(identity).parent
    from task_coordination import read,finish as complete
    current=read(coord/'coordination.json')
    result=complete(coord,current['revision'],report['artifacts'][0]['path'],delivery_report=Path(output)/REPORT)
    if result.get('status')!='READY_TO_DELIVER':return result
    return {'status':'DELIVERY_FINISHED','report':str(Path(output)/REPORT),'artifacts':report['artifacts'],'completion':result}


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--identity',required=True);p.add_argument('--output',required=True)
    a=p.parse_args()
    try:print(json.dumps(finalize(a.identity,a.output),ensure_ascii=False))
    except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile) as e:
        print(json.dumps({'status':'DELIVERY_HOLD','error':str(e)},ensure_ascii=False));raise SystemExit(1)
