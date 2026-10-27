#!/usr/bin/env python3
"""Merge an opt-in Interrupt hook; never grant host trust or replace other hooks."""
from pathlib import Path
import argparse, datetime, json, os, shutil, subprocess, sys
from contextlib import nullcontext
from platform_io import atomic_json, file_lock, configure_stdio

def setup(home, *, python=None, apply=False):
    home=Path(home).expanduser().resolve()
    script=home/'skills/vertical-comic-preproduction/scripts/runtime_clock_hook.py'
    executable=Path(python or sys.executable).absolute()
    if (apply and not script.is_file()) or not executable.is_file(): raise ValueError('installed hook and Python required')
    def quote_posix(v): return "'" + str(v).replace("'", "'\"'\"'") + "'"
    command=' '.join(quote_posix(v) for v in (executable,script))
    command_windows=subprocess.list2cmdline([str(executable),str(script)])
    definition={'type':'command','command':command,'commandWindows':command_windows,'timeout':3}
    path=home/'hooks.json'; backup=None
    # Lock only setup, not Interrupt; merge against current content under lock.
    if apply: (home/'skill-bundles/vertical-comic-skills').mkdir(parents=True,exist_ok=True)
    with file_lock(home/'skill-bundles/vertical-comic-skills/clock-hooks-setup.lock') if apply else nullcontext():
        if path.is_symlink(): raise ValueError('refusing hooks.json symlink')
        value=json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
        hooks=value.setdefault('hooks',{})
        if not isinstance(hooks,dict): raise ValueError('existing hooks schema unsupported; preserved')
        rows=hooks.setdefault('Interrupt',[])
        if not isinstance(rows,list): raise ValueError('existing Interrupt schema unsupported; preserved')
        for row in rows:
            for old in row.get('hooks',[]):
                if old==definition:
                    return {'status':'CONFIGURED_TRUST_NOT_VERIFIED','path':str(path),'automatic_pause_verified':False}
                if 'runtime_clock_hook.py' in str(old):
                    raise ValueError('existing comic clock hook differs; preserve both definitions for review, do not duplicate')
        rows.append({'hooks':[definition]})
        if apply:
            if path.exists():
                backup=path.with_name('hooks.json.comic-clock-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')+'.bak')
                shutil.copy2(path,backup)
            atomic_json(path,value)
    return {'status':'CONFIGURED_TRUST_REQUIRED' if apply else 'PREVIEW_ONLY',
            'path':str(path),'backup':str(backup) if backup else None,
            'automatic_pause_verified':False,'proposed':value,
            'next':'Review/trust exact hook in Codex, bind current session_id, then real stop/resume test. No automatic resume on arbitrary user messages.'}

if __name__=='__main__':
    configure_stdio();p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--codex-home',default=os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
    p.add_argument('--python');p.add_argument('--apply',action='store_true');a=p.parse_args()
    try: print(json.dumps(setup(a.codex_home,python=a.python,apply=a.apply),ensure_ascii=False,indent=2))
    except (OSError,ValueError,KeyError) as exc: print(str(exc),file=sys.stderr);raise SystemExit(1)
