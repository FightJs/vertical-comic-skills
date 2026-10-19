#!/usr/bin/env python3
"""Explicit generic-rule maintenance, local outbox and optional per-user GitHub sync.

No login is required for update/export. No credentials are included in a bundle.
"""
from pathlib import Path
import argparse,base64,copy,hashlib,json,os,re,shutil,subprocess,sys,tempfile,uuid,zipfile
from builtin_memory import ROOT,read,digest,resolve,source
from rule_memory import source_index

STATE=Path.home()/'.codex/comic/rule-contributions'


def write(p,value):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_name(p.name+'.'+uuid.uuid4().hex+'.tmp')
    try:temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');os.replace(temp,p)
    finally:temp.unlink(missing_ok=True)


def portable(text):
    # A conservative admission screen, not proof of natural-language portability.
    if re.search(r'\b[EP]\d{3}\b|第[0-9一二三四五六七八九十]+话|《[^》]+》|/Users/|/var/fol' r'ders/|[A-Za-z]:\\|gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN .*PRIVATE KEY',text):
        raise ValueError('增补含话格/作品/本机路径/凭证特征，只能留项目记录，不能进入通用同步包')


def snapshot(library_root=None):
    root=Path(library_root or ROOT);user=root/'用户增补';_,index=source_index(source(user));payload={}
    for r in index['rules']:
        if not r['id'].startswith('USR-'):raise ValueError('用户增补使用USR-前缀，不能改内置MEM规则')
        p=user/r['file']['path']
        if p.is_symlink() or not p.resolve().is_relative_to(user.resolve()) or digest(p)!=r['file']['sha256']:raise ValueError('增补正文路径或哈希错误')
        portable(p.read_text());payload[r['file']['path']]=p.read_bytes()
    portable(json.dumps(index,ensure_ascii=False));payload['记忆索引.json']=(json.dumps(index,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    token=hashlib.sha256(b''.join(k.encode()+b'\0'+hashlib.sha256(v).digest() for k,v in sorted(payload.items()))).hexdigest()
    return index,payload,token


def enqueue(library_root=None,state_root=None):
    state=Path(state_root or STATE);index,payload,token=snapshot(library_root)
    if not index['rules']:return {'status':'NO_USER_ADDITIONS','image_calls':0}
    dest=state/'outbox'/token
    if not dest.exists():
        state.mkdir(parents=True,exist_ok=True)
        stage=Path(tempfile.mkdtemp(prefix='.contribution-',dir=state))
        try:
            for name,body in payload.items():
                p=stage/'payload'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body)
            write(stage/'event.json',{'policy':'rule_contribution_v1','snapshot_id':token,'status':'PENDING_SYNC','rule_ids':[r['id'] for r in index['rules']],
                                    'files':[{'path':k,'sha256':hashlib.sha256(v).hexdigest()} for k,v in sorted(payload.items())]})
            dest.parent.mkdir(parents=True,exist_ok=True)
            try:os.rename(stage,dest)
            except OSError:
                if not dest.exists():raise
        finally:
            if stage.exists():shutil.rmtree(stage)
    return {'status':read(dest/'event.json')['status'],'snapshot_id':token,'event_dir':str(dest)}


def update(rule_file,body_file,review_file,*,library_root=None,state_root=None):
    root=Path(library_root or ROOT).resolve();user=root/'用户增补';rule=read(rule_file);review=read(review_file);body=Path(body_file).read_text()
    if (review.get('source_kind')!='user_message' or not review.get('source_locator') or not review.get('authorization') or
        review.get('portable') is not True or review.get('contains_story_facts') is not False):raise ValueError('缺真实维护授权及通用性审查；生产不得自动回写')
    if not re.fullmatch(r'USR-[A-Za-z0-9_-]+',rule.get('id','')):raise ValueError('用户规则ID须为USR-前缀')
    if not rule.get('version'):raise ValueError('规则须有版本')
    portable(body);portable(json.dumps(rule,ensure_ascii=False))
    lock=root/'.update-lock'
    try:lock.mkdir()
    except FileExistsError:raise ValueError('另一规则维护正在运行或上次未正常退出，保留锁供核对')
    backup=None;stage=None
    try:
        # A durable intent record exists before changing rules, so a crash can be recovered.
        state=Path(state_root or STATE);intent=state/'updates'/(uuid.uuid4().hex+'.json')
        write(intent,{'status':'PREPARING','rule_id':rule['id'],'version':rule['version'],'source_locator':review['source_locator']})
        stage=Path(tempfile.mkdtemp(prefix='.user-rules-',dir=root));shutil.copytree(user,stage/'用户增补')
        index=read(user/'记忆索引.json');old=next((r for r in index['rules'] if r['id']==rule['id']),None)
        if old and old['version']==rule['version']:raise ValueError('修改既有规则须更新版本，不原地重签同一版本')
        filename='规则/'+rule['id']+'.md';p=stage/'用户增补'/filename;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body)
        rule={**rule,'file':{'path':filename,'sha256':digest(p)}}
        index['rules']=[r for r in index['rules'] if r['id']!=rule['id']]+[rule];write(stage/'用户增补/记忆索引.json',index)
        # Reuse the strict library schema and test a real built-in/user merge before activation.
        shutil.copytree(root/'内置规则',stage/'内置规则');resolve(library_root=stage,cache_root=state/'validation-cache')
        backup=root/('.user-backup-'+uuid.uuid4().hex);os.rename(user,backup)
        try:os.rename(stage/'用户增补',user)
        except Exception:os.rename(backup,user);backup=None;raise
        receipt=enqueue(root,state)
        write(intent,{'status':'APPLIED','rule_id':rule['id'],'version':rule['version'],'snapshot_id':receipt.get('snapshot_id'),'source_locator':review['source_locator']})
        shutil.rmtree(backup);backup=None
        config=state/'sync.json'
        if config.exists() and read(config).get('enabled'):
            sync=publish(receipt['event_dir'],state_root=state)
        else:sync={'status':'LOCAL_ONLY_EXPORT_AVAILABLE'}
        return {'status':'RULE_UPDATED','rule_id':rule['id'],'outbox':receipt,'sync':sync,'affects':'new_runs_only'}
    finally:
        if stage and stage.exists():shutil.rmtree(stage)
        lock.rmdir()


def export(event_dir,output):
    event=Path(event_dir);data=read(event/'event.json');out=Path(output)
    if out.exists() or out.suffix.lower()!='.zip':raise ValueError('增补ZIP须新文件，不覆盖已有包')
    out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(out,'x',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('规则增补/manifest.json',json.dumps({'policy':'rule_contribution_v1','snapshot_id':data['snapshot_id'],'files':data['files']},ensure_ascii=False,indent=2))
        for ref in data['files']:
            p=event/'payload'/ref['path']
            if not p.resolve().is_relative_to((event/'payload').resolve()) or digest(p)!=ref['sha256']:raise ValueError('待同步增补已变')
            z.write(p,'规则增补/'+ref['path'])
    return {'status':'EXPORTED_NOT_UPLOADED','zip':str(out),'sha256':digest(out)}


def import_package(archive,state_root=None):
    """Import an offline contribution to the review outbox, never activate rules."""
    state=Path(state_root or STATE);state.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.import-',dir=state) as tmp:
        stage=Path(tmp);payload=stage/'payload';payload.mkdir()
        with zipfile.ZipFile(archive) as z:
            infos=z.infolist();names=[i.filename for i in infos]
            if len(set(n.casefold() for n in names))!=len(names) or sum(i.file_size for i in infos)>4*1024*1024:raise ValueError('增补ZIP重复成员或超过4MiB')
            for info in infos:
                name=info.filename
                if not name.startswith('规则增补/') or '\\' in name or '..' in Path(name).parts or info.is_dir() or ((info.external_attr>>16)&0o170000)==0o120000:raise ValueError('增补ZIP成员路径不合法')
            manifest=json.loads(z.read('规则增补/manifest.json'));rows=manifest['files']
            if manifest.get('policy')!='rule_contribution_v1' or {'规则增补/'+r['path'] for r in rows}|{'规则增补/manifest.json'}!=set(names):raise ValueError('增补文件清单不完整')
            values={}
            for row in rows:
                body=z.read('规则增补/'+row['path'])
                if hashlib.sha256(body).hexdigest()!=row['sha256']:raise ValueError('增补内容哈希不符')
                dest=payload/row['path']
                if not dest.resolve().is_relative_to(payload.resolve()):raise ValueError('增补路径越界')
                portable(body.decode('utf-8'));dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(body);values[row['path']]=body
        token=hashlib.sha256(b''.join(k.encode()+b'\0'+hashlib.sha256(v).digest() for k,v in sorted(values.items()))).hexdigest()
        if token!=manifest.get('snapshot_id'):raise ValueError('增补快照标识不符')
        _,index=source_index(source(payload))
        if any(not r['id'].startswith('USR-') for r in index['rules']):raise ValueError('离线包只能含用户增补')
        dest=state/'outbox'/token
        if not dest.exists():
            dest.parent.mkdir(parents=True,exist_ok=True);write(stage/'event.json',{'policy':'rule_contribution_v1','snapshot_id':token,'status':'PENDING_REVIEW','origin':'offline_package','rule_ids':[r['id'] for r in index['rules']],'files':rows})
            os.rename(stage,dest)
        return {'status':'IMPORTED_PENDING_REVIEW','event_dir':str(dest),'activated':False}


def api(path,method='GET',data=None):
    cmd=['gh','api',path,'--method',method]
    if data is not None:cmd+=['--input','-']
    proc=subprocess.run(cmd,input=json.dumps(data) if data is not None else None,capture_output=True,text=True,timeout=30)
    if proc.returncode:raise ValueError('GitHub不可用或无权限；保留本地待同步状态:'+proc.stderr[-350:])
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def configure(*,enabled=False,state_root=None,authorization=None):
    target=read(ROOT/'同步目标.json')
    if enabled and not authorization:raise ValueError('启用自动同步须记录本机用户明确授权')
    p=Path(state_root or STATE)/'sync.json';write(p,{'policy':'rule_sync_v1','enabled':enabled,'repository':target['repository'],'authorization':authorization})
    return {'status':'SYNC_ENABLED' if enabled else 'LOCAL_ONLY','repository':target['repository']}


def publish(event_dir,*,state_root=None):
    event=Path(event_dir);record=read(event/'event.json');config=read(Path(state_root or STATE)/'sync.json')
    if not config.get('enabled') or not config.get('authorization'):return {'status':'LOCAL_ONLY_EXPORT_AVAILABLE'}
    # The repository is a public target; user credentials come solely from gh auth.
    repo=config['repository']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise ValueError('仓库名称不规范')
    try:
        login=api('user')['login']
        if not re.fullmatch(r'[A-Za-z0-9-]+',login):raise ValueError('GitHub用户标识不规范')
        info=api('repos/'+repo);upstream=repo;upstream_base=info['default_branch'];forked=False
        if not info.get('permissions',{}).get('push'):
            fork_name=login+'/'+repo.split('/')[1]
            try:fork=api('repos/'+fork_name)
            except ValueError:
                api('repos/'+repo+'/forks','POST',{})
                record.update(status='PENDING_SYNC',last_error='fork创建已请求；准备完成后重试同步，不重复提交规则');write(event/'event.json',record)
                return {'status':'PENDING_SYNC','export_available':True}
            if fork.get('parent',{}).get('full_name','').lower()!=repo.lower():raise ValueError('同名仓库不是目标fork，保留待同步，不覆盖')
            repo=fork_name;info=fork;forked=True
        branch='users/'+login+'/rule-memory';prefix='contributions/'+login+'/rule-memory/'+record['snapshot_id']+'/'
        def pull_request():
            if not forked:return None
            rows=api('repos/'+upstream+'/pulls?head='+login+':'+branch+'&base='+upstream_base+'&state=open')
            if rows:return rows[0]['html_url']
            return api('repos/'+upstream+'/pulls','POST',{'head':login+':'+branch,'base':upstream_base,'title':'User rules: '+login,'body':'Generic rule additions from '+login+'. Review before promoting into built-in rules.'})['html_url']
        from urllib.parse import quote
        refpath='repos/'+repo+'/git/ref/heads/'+quote(branch,safe='')
        try:head=api(refpath)['object']['sha']
        except ValueError:
            # Confirm branch absence separately; auth/network failures must not create a second attempt.
            branches=api('repos/'+repo+'/branches?per_page=100')
            if any(x['name']==branch for x in branches):raise
            head=api('repos/'+repo+'/git/ref/heads/'+quote(info['default_branch'],safe=''))['object']['sha']
            api('repos/'+repo+'/git/refs','POST',{'ref':'refs/heads/'+branch,'sha':head})
        commit=api('repos/'+repo+'/git/commits/'+head);tree=api('repos/'+repo+'/git/trees/'+commit['tree']['sha']+'?recursive=1')
        if tree.get('truncated'):raise ValueError('仓库树过大未完整返回，保留待同步')
        existing={x['path']:x for x in tree['tree'] if x['path'].startswith(prefix) and x['type']=='blob'}
        # Recover a previous push whose response was lost: same snapshot means already synchronized.
        marker=existing.get(prefix+'manifest.json')
        if marker:
            raw=api('repos/'+repo+'/git/blobs/'+marker['sha']);old=json.loads(base64.b64decode(raw['content']))
            if old.get('snapshot_id')==record['snapshot_id']:
                pr=pull_request();record.update(status='SYNCED',repository=repo,branch=branch,commit=head,pull_request=pr);write(event/'event.json',record);return {'status':'SYNCED','branch':branch,'commit':head,'pull_request':pr}
        additions={}
        for row in record['files']:
            p=event/'payload'/row['path']
            if not p.resolve().is_relative_to((event/'payload').resolve()) or digest(p)!=row['sha256']:raise ValueError('增补包字节变化，禁止提交')
            additions[prefix+row['path']]=p.read_bytes()
        additions[prefix+'manifest.json']=json.dumps({'policy':'rule_contribution_v1','snapshot_id':record['snapshot_id'],'files':record['files']},ensure_ascii=False,indent=2).encode()
        changes=[]
        for name,body in additions.items():
            blob=api('repos/'+repo+'/git/blobs','POST',{'content':base64.b64encode(body).decode(),'encoding':'base64'})
            changes.append({'path':name,'mode':'100644','type':'blob','sha':blob['sha']})
        changes.extend({'path':name,'mode':'100644','type':'blob','sha':None} for name in existing if name not in additions)
        created_tree=api('repos/'+repo+'/git/trees','POST',{'base_tree':commit['tree']['sha'],'tree':changes})
        new=api('repos/'+repo+'/git/commits','POST',{'message':'rules('+login+'): '+record['snapshot_id'][:12],'tree':created_tree['sha'],'parents':[head]})
        api('repos/'+repo+'/git/refs/heads/'+quote(branch,safe=''),'PATCH',{'sha':new['sha'],'force':False})
        pr=pull_request();record.update(status='SYNCED',repository=repo,branch=branch,commit=new['sha'],pull_request=pr);write(event/'event.json',record)
        return {'status':'SYNCED','repository':repo,'branch':branch,'commit':new['sha'],'pull_request':pr}
    except (OSError,ValueError,KeyError,subprocess.TimeoutExpired) as exc:
        record.update(status='PENDING_SYNC',last_error=str(exc));write(event/'event.json',record)
        return {'status':'PENDING_SYNC','error':str(exc),'export_available':True}


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('update');a.add_argument('--rule',required=True);a.add_argument('--body',required=True);a.add_argument('--review',required=True)
    a=sub.add_parser('export');a.add_argument('--event',required=True);a.add_argument('--output',required=True)
    a=sub.add_parser('sync');a.add_argument('--event',required=True)
    a=sub.add_parser('import');a.add_argument('--zip',required=True)
    a=sub.add_parser('configure');a.add_argument('--enable',action='store_true');a.add_argument('--authorization')
    sub.add_parser('queue')
    a=p.parse_args()
    try:
        if a.action=='update':result=update(a.rule,a.body,a.review)
        elif a.action=='export':result=export(a.event,a.output)
        elif a.action=='sync':result=publish(a.event)
        elif a.action=='import':result=import_package(a.zip)
        elif a.action=='configure':result=configure(enabled=a.enable,authorization=a.authorization)
        else:result=enqueue()
        print(json.dumps(result,ensure_ascii=False));return 0
    except (OSError,ValueError,KeyError,TypeError) as e:print(json.dumps({'status':'HOLD','error':str(e)},ensure_ascii=False));return 1
if __name__=='__main__':raise SystemExit(main())
