"""Managed-install backups and rollback; never touches project RVs or credentials."""
from pathlib import Path
from contextlib import contextmanager
import hashlib,json,os,shutil,subprocess,sys,tempfile,datetime
from platform_io import file_lock,portable_relative

NAME='vertical-comic-skills'
USER='skills/vertical-comic-preproduction/assets/rule-memory/用户增补'
SKILLS=('vertical-comic-preproduction','vertical-comic-visual-assets','vertical-comic-shot-design','vertical-comic-panel-generation','vertical-comic-image-review')
TARGETS=['skills/'+s for s in SKILLS]+['skill-bundles/'+NAME+'/memory']

def digest(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,value):
    Path(p).parent.mkdir(parents=True,exist_ok=True)
    Path(p).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
def safe(base,relative):
    portable_relative(relative);base=Path(base);p=base/relative
    if any(q.is_symlink() for q in [p,*p.parents] if q.is_relative_to(base)):raise ValueError('Refusing symlink installation path')
    return p

def inventory(root,targets=TARGETS):
    rows={}
    for rel in targets:
        target=safe(root,rel)
        for p in sorted(target.rglob('*')) if target.exists() else []:
            if p.is_symlink():raise ValueError('Refusing symlink backup')
            if p.is_file() and '__pycache__' not in p.parts and p.name!='.DS_Store' and p.suffix!='.pyc':rows[p.relative_to(root).as_posix()]=digest(p)
    return rows

@contextmanager
def installation_lock(home):
    managed=Path(home)/'skill-bundles'/NAME;managed.mkdir(parents=True,exist_ok=True)
    with file_lock(managed/'installation.lock',timeout=0):yield

def begin_backup(home,backup):
    home=Path(home);backup=Path(backup);rows=inventory(home)
    if not rows:return None
    marker=home/'skill-bundles'/NAME/'installed.json'
    metadata={'policy':'comic_install_backup_v1','status':'INCOMPLETE','files':rows,'targets':TARGETS,'previous_marker':read(marker) if marker.is_file() else None}
    write(backup/'backup.json',metadata);return metadata

def complete_backup(backup,metadata):
    if metadata:
        if inventory(backup)!=metadata['files']:raise ValueError('Backup changed during installation')
        write(Path(backup)/'backup.json',{**metadata,'status':'COMPLETE'})

def available_backups(home):
    base=Path(home)/'skill-bundles'/NAME/'backups';result=[]
    for p in sorted(base.glob('*/backup.json'),reverse=True):
        try:
            value=read(p)
            if value.get('status')=='COMPLETE' and value.get('previous_marker'):
                result.append({'id':p.parent.name,'version':value['previous_marker'].get('version'),'path':str(p.parent)})
        except (OSError,ValueError,KeyError):continue
    return result

def restore(home,backup_id=None,*,replace_existing=False):
    home=Path(home).expanduser().resolve()
    with installation_lock(home):
        options=available_backups(home)
        selected=next((x for x in options if x['id']==backup_id),None) if backup_id else next(iter(options),None)
        if not selected:raise ValueError('没有可恢复的完整托管备份；旧版无元数据备份需人工核对')
        backup=Path(selected['path']);metadata=read(backup/'backup.json')
        if metadata.get('targets')!=TARGETS or inventory(backup)!=metadata.get('files'):raise ValueError('备份完整性失配，未改变安装')
        marker_path=home/'skill-bundles'/NAME/'installed.json';current=read(marker_path)
        actual=inventory(home);expected={k:v for k,v in current['files'].items() if not k.startswith(USER+'/')}
        actual={k:v for k,v in actual.items() if not k.startswith(USER+'/')}
        conflicts=sorted(k for k in set(actual)|set(expected) if actual.get(k)!=expected.get(k))
        if conflicts and not replace_existing:raise ValueError('LOCAL_CHANGES: '+', '.join(conflicts[:8]))
        managed=marker_path.parent;stage=Path(tempfile.mkdtemp(prefix='.restore-',dir=managed))
        recovery=managed/'backups'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        moved=[];activated=[];before=None
        try:
            for rel in TARGETS:
                source=safe(backup,rel)
                if source.exists():shutil.copytree(source,safe(stage,rel))
            # Keep present-day user rules even when restoring older program files.
            user=safe(home,USER);staged=safe(stage,USER)
            if user.exists():
                before=inventory(home,[USER])
                if staged.exists():shutil.rmtree(staged)
                shutil.copytree(user,staged)
                if inventory(home,[USER])!=before:raise ValueError('用户规则变动中，请稍后重试')
            scripts=stage/'skills/vertical-comic-preproduction/scripts'
            subprocess.run([sys.executable,'-X','utf8','-B',str(scripts/'runtime_environment.py')],check=True,capture_output=True,text=True,encoding='utf-8')
            if (scripts/'builtin_memory.py').exists():
                code='import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from builtin_memory import resolve;resolve(library_root=Path(sys.argv[2]),cache_root=Path(sys.argv[3]))'
                subprocess.run([sys.executable,'-X','utf8','-B','-c',code,str(scripts),str(staged.parent),str(stage/'.validation-cache')],check=True,capture_output=True,text=True,encoding='utf-8')
            if before is not None and inventory(home,[USER])!=before:raise ValueError('用户规则在验证期间变动，未改变安装')
            previous=begin_backup(home,recovery)
            for rel in TARGETS:
                target=safe(home,rel);saved=safe(recovery,rel)
                if target.exists():saved.parent.mkdir(parents=True,exist_ok=True);os.replace(target,saved);moved.append((saved,target))
                source=safe(stage,rel)
                if source.exists():target.parent.mkdir(parents=True,exist_ok=True);os.replace(source,target);activated.append(target)
            complete_backup(recovery,previous)
            restored={**metadata['previous_marker'],'restored_from':selected['id'],'rollback_backup':str(recovery),'python':sys.executable}
            temp=stage/'marker.json';write(temp,restored);os.replace(temp,marker_path)
        except Exception:
            for target in reversed(activated):
                if target.exists():shutil.rmtree(target)
            for saved,target in reversed(moved):os.replace(saved,target)
            raise
        finally:shutil.rmtree(stage,ignore_errors=True)
        return {'status':'RESTORED','version':restored.get('version'),'backup':str(recovery),'codex_home':str(home),'next':'新运行使用恢复版；旧RV继续使用原冻结版本'}
