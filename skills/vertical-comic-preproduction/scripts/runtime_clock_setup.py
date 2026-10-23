#!/usr/bin/env python3
"""Stable local runtime and backed-up hook migration; never grant host trust."""
from pathlib import Path
import argparse, datetime, json, os, shutil, subprocess, sys, uuid
from contextlib import nullcontext
from platform_io import atomic_json, file_lock, configure_stdio

NAME='vertical-comic-skills'

def _probe(executable):
    code="import sys,json;import PIL,yaml,openpyxl,et_xmlfile;print(json.dumps({'python':sys.executable,'version':list(sys.version_info[:2])}))"
    p=subprocess.run([str(executable),'-I','-c',code],capture_output=True,text=True,timeout=20)
    if p.returncode:raise ValueError('stable Python/dependency probe failed: '+p.stderr[-500:])
    return json.loads(p.stdout)

def prepare_runtime(home, *, python=None):
    root=Path(home).resolve()/'skill-bundles'/NAME/'runtime'
    root.mkdir(parents=True,exist_ok=True)
    with file_lock(root/'environment.lock'):
        pointer=root/'active.json'
        if pointer.exists():
            old=json.loads(pointer.read_text(encoding='utf-8'));exe=Path(old['python'])
            if not exe.absolute().is_relative_to(root):raise ValueError('unexpected stable runtime path')
            try:return {**old,'probe':_probe(exe),'reused':True}
            except (OSError,ValueError,subprocess.SubprocessError):pass
        source=str(Path(python or sys.executable).absolute())
        _probe(source)  # Required dependencies must already be available; no hidden network install.
        destination=root/('python-'+uuid.uuid4().hex[:12])
        subprocess.run([source,'-m','venv','--copies',str(destination)],check=True,capture_output=True,text=True,timeout=90)
        exe=destination/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        code="import sysconfig,json,importlib.metadata as m;from pathlib import Path;p=Path(sysconfig.get_path('purelib')).resolve();rows=[];\nfor name in ['Pillow','PyYAML','openpyxl','et_xmlfile']:\n d=m.distribution(name)\n for f in d.files or []:\n  q=Path(d.locate_file(f)).resolve()\n  if q.is_file() and q.is_relative_to(p) and '__pycache__' not in q.parts: rows.append([str(q),q.relative_to(p).as_posix()])\nprint(json.dumps(rows))"
        rows=json.loads(subprocess.check_output([source,'-I','-c',code],text=True,timeout=20))
        pure=Path(subprocess.check_output([str(exe),'-I','-c',"import sysconfig;print(sysconfig.get_path('purelib'))"],text=True).strip())
        for original,relative in rows:
            target=pure/relative
            if not target.resolve().is_relative_to(pure.resolve()):raise ValueError('dependency path escapes runtime')
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,target)
        probe=_probe(exe)
        value={'policy':'comic_stable_python_v1','python':str(exe),'version':probe['version'],'created_from':source}
        if pointer.exists():shutil.copy2(pointer,root/('active-'+uuid.uuid4().hex+'.bak.json'))
        atomic_json(pointer,value)
        return {**value,'probe':probe,'reused':False}

def setup(home, *, python=None, apply=False):
    home=Path(home).expanduser().resolve();managed=home/'skill-bundles'/NAME
    script=home/'skills/vertical-comic-preproduction/scripts/runtime_clock_hook.py'
    runtime=prepare_runtime(home,python=python) if apply else None
    pointer=managed/'runtime/active.json'
    if runtime:executable=Path(runtime['python'])
    elif pointer.exists():executable=Path(json.loads(pointer.read_text())['python'])
    else:executable=managed/'runtime/<created-on-apply>/bin/python'
    if apply and not script.is_file():raise ValueError('installed hook script required')
    def quote(v):return "'"+str(v).replace("'","'\"'\"'")+"'"
    command=' '.join(quote(v) for v in (executable,script))
    command_windows=subprocess.list2cmdline([str(executable),str(script)])
    definition={'type':'command','command':command,'commandWindows':command_windows,'timeout':3}
    path=home/'hooks.json';backup=None
    if apply:managed.mkdir(parents=True,exist_ok=True)
    with file_lock(managed/'clock-hooks-setup.lock') if apply else nullcontext():
        if path.is_symlink():raise ValueError('refusing hooks.json symlink')
        value=json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
        original=json.loads(json.dumps(value));hooks=value.setdefault('hooks',{})
        if not isinstance(hooks,dict):raise ValueError('existing hooks schema unsupported; preserved')
        for name in ('Interrupt','PreToolUse','SessionStart'):
            rows=hooks.setdefault(name,[])
            if not isinstance(rows,list):raise ValueError('existing hook schema unsupported; preserved')
            # Migrate only this exact installed handler; preserve unrelated commands and groups.
            kept=[]
            for row in rows:
                remaining=[h for h in row.get('hooks',[]) if str(script) not in h.get('command','') and str(script) not in h.get('commandWindows','')]
                if remaining or not row.get('hooks'):kept.append({**row,'hooks':remaining})
            group={'hooks':[definition]}
            if name=='PreToolUse':group['matcher']='.*'
            kept.append(group);hooks[name]=kept
        changed=value!=original
        if apply and changed:
            if path.exists():
                backup=managed/'backups'/('hooks-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json')
                backup.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,backup)
            atomic_json(path,value)
    return {'status':('CONFIGURED_TRUST_REQUIRED' if changed else 'CONFIGURED_TRUST_NOT_VERIFIED') if apply else 'PREVIEW_ONLY',
            'path':str(path),'backup':str(backup) if backup else None,'runtime':runtime,
            'automatic_pause_verified':False,'proposed':value,
            'next':'Trust exact changed hook definitions in Codex; next relevant tool invocation supplies identity. Real button verification still required.'}

if __name__=='__main__':
    configure_stdio();p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--codex-home',default=os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
    p.add_argument('--python');p.add_argument('--apply',action='store_true');a=p.parse_args()
    try:print(json.dumps(setup(a.codex_home,python=a.python,apply=a.apply),ensure_ascii=False,indent=2))
    except (OSError,ValueError,KeyError,subprocess.SubprocessError) as exc:print(str(exc),file=sys.stderr);raise SystemExit(1)
