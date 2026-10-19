#!/usr/bin/env python3
"""Install/update the complete bundle; preserve user changes and frozen production RVs."""
from pathlib import Path
import argparse,datetime,hashlib,json,os,shutil,subprocess,sys,tempfile

ROOT=Path(__file__).resolve().parents[1]
NAME='vertical-comic-skills'
USER_ADDITIONS='skills/vertical-comic-preproduction/assets/rule-memory/用户增补'
USER_RULES=USER_ADDITIONS+'/'
def user_rule(name):return name.startswith(USER_RULES)

def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def safe(base,name):
    p=Path(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name:raise ValueError('Unsafe bundle path')
    result=base/p
    if any(x.is_symlink() for x in [result,*result.parents] if x.is_relative_to(base)):raise ValueError('Refusing symlink destination')
    return result

def bundle():
    data=json.loads((ROOT/'bundle.json').read_text())
    if data.get('policy')!='vertical_comic_bundle_v1':raise ValueError('Unknown bundle policy')
    names=data['skills']
    if len(names)!=5 or len(set(names))!=5 or any('/' in n or not n.startswith('vertical-comic-') for n in names):raise ValueError('Incomplete five-Skill bundle')
    seen=set()
    for row in data['files']:
        name=row['path'];p=safe(ROOT,name)
        if name in seen or not p.is_file() or digest(p)!=row['sha256'] or p.stat().st_size!=row['bytes']:raise ValueError('Bundle hash mismatch: '+name)
        seen.add(name)
    actual={p.relative_to(ROOT).as_posix() for folder in ('skills','memory') for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='.DS_Store' and p.suffix!='.pyc'}
    if actual!=seen:raise ValueError('Unlisted bundle files or missing entries')
    return data

def mapped(name):
    if name.startswith('skills/'):return name
    if name.startswith('memory/'):return 'skill-bundles/'+NAME+'/'+name
    raise ValueError('Unknown bundle file namespace')

def tree_files(folder):
    return {p for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='.DS_Store' and p.suffix!='.pyc'} if folder.exists() else set()

def inspect(home,data):
    managed=home/'skill-bundles'/NAME;marker=managed/'installed.json'
    expected={mapped(r['path']):r['sha256'] for r in data['files'] if not user_rule(mapped(r['path']))}
    targets=[safe(home,'skills/'+n) for n in data['skills']]+[managed/'memory']
    old=json.loads(marker.read_text()) if marker.is_file() else None
    conflicts=[]
    if old:
        for name,h in old['files'].items():
            if user_rule(name):continue
            p=safe(home,name)
            if not p.is_file() or digest(p)!=h:conflicts.append(name)
        known=set(old['files'])
        for target in targets:
            conflicts.extend(p.relative_to(home).as_posix() for p in tree_files(target) if p.relative_to(home).as_posix() not in known and not user_rule(p.relative_to(home).as_posix()))
    elif any(t.exists() for t in targets):conflicts.append('Existing installation is not managed by this updater')
    changes=[n for n,h in expected.items() if not safe(home,n).is_file() or digest(safe(home,n))!=h]
    if old:changes.extend(n for n in old['files'] if n not in expected and not user_rule(n))
    return managed,expected,targets,conflicts,changes

def install(home,*,check=False,replace_existing=False):
    home=Path(home).expanduser().resolve();data=bundle()
    managed,expected,targets,conflicts,changes=inspect(home,data)
    if check:return {'status':'LOCAL_CHANGES' if conflicts else 'UPDATE_AVAILABLE' if changes else 'UP_TO_DATE','changed_files':len(changes),'conflicts':conflicts}
    if conflicts and not replace_existing:raise ValueError('Local changes/existing installation preserved. Review --check; explicit --replace-existing backs up then replaces: '+', '.join(conflicts[:8]))
    if not changes and not conflicts:return {'status':'UP_TO_DATE','skills':data['skills']}
    managed.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.stage-',dir=managed));backups=managed/'backups'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    moved=[];activated=[]
    try:
        for row in data['files']:
            dest=safe(stage,mapped(row['path']));dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/row['path'],dest)
            if digest(dest)!=row['sha256']:raise ValueError('Staged file changed')
        source_user=safe(home,USER_RULES.rstrip('/'));staged_user=safe(stage,USER_RULES.rstrip('/'))
        if source_user.exists():
            if any(p.is_symlink() for p in source_user.rglob('*')):raise ValueError('Refusing symlink user rules')
            before={p.relative_to(source_user).as_posix():digest(p) for p in tree_files(source_user)}
            if staged_user.exists():shutil.rmtree(staged_user)
            shutil.copytree(source_user,staged_user)
            if before!={p.relative_to(source_user).as_posix():digest(p) for p in tree_files(source_user)}:raise ValueError('User rules changed during upgrade; retry after maintenance')
        # Validate preserved additions against the new built-ins before activation.
        scripts=stage/'skills/vertical-comic-preproduction/scripts'
        if (scripts/'builtin_memory.py').exists():
            code="import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from builtin_memory import resolve;resolve(library_root=Path(sys.argv[2]),cache_root=Path(sys.argv[3]))"
            subprocess.run([sys.executable,'-B','-c',code,str(scripts),str(staged_user.parent),str(stage/'.validation-cache')],check=True,capture_output=True,text=True)
        for target in targets:
            if target.is_symlink():raise ValueError('Refusing symlink installation')
            rel=target.relative_to(home);saved=backups/rel
            if target.exists():saved.parent.mkdir(parents=True,exist_ok=True);os.replace(target,saved);moved.append((saved,target))
            staged=stage/rel;target.parent.mkdir(parents=True,exist_ok=True);os.replace(staged,target);activated.append(target)
        commit=subprocess.run(['git','-C',str(ROOT),'rev-parse','HEAD'],capture_output=True,text=True) if shutil.which('git') and (ROOT/'.git').exists() else None
        marker={'policy':'vertical_comic_install_v1','repository':'FightJs/'+NAME,'commit':commit.stdout.strip() if commit and commit.returncode==0 else None,'files':expected,'memory_root':str(managed/'memory')}
        tmp=stage/'installed.json';tmp.write_text(json.dumps(marker,ensure_ascii=False,indent=2)+'\n');os.replace(tmp,managed/'installed.json')
    except Exception:
        for target in reversed(activated):
            if target.exists():shutil.rmtree(target)
        for saved,target in reversed(moved):os.replace(saved,target)
        raise
    finally:shutil.rmtree(stage,ignore_errors=True)
    return {'status':'INSTALLED','skills':data['skills'],'memory_root':str(managed/'memory'),'backup':str(backups) if moved else None,'next_step':'在新的Codex轮次说：使用 $vertical-comic-preproduction。第一次使用，请引导我配置，进行前期制作。原冻结生产RV不升级。'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--codex-home',default=os.environ.get('CODEX_HOME',str(Path.home()/'.codex')));p.add_argument('--check',action='store_true');p.add_argument('--update',action='store_true');p.add_argument('--replace-existing',action='store_true');a=p.parse_args()
    if a.update:
        dirty=subprocess.run(['git','-C',str(ROOT),'status','--porcelain'],capture_output=True,text=True,check=True)
        if dirty.stdout.strip():raise ValueError('Repository has local changes; commit or preserve them before updating')
        subprocess.run(['git','-C',str(ROOT),'pull','--ff-only'],check=True)
        args=[x for x in sys.argv[1:] if x!='--update'];os.execv(sys.executable,[sys.executable,str(Path(__file__).resolve()),*args])
    result=install(a.codex_home,check=a.check,replace_existing=a.replace_existing);print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,subprocess.CalledProcessError) as e:print('ERROR: '+str(e),file=sys.stderr);raise SystemExit(1)
