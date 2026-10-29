#!/usr/bin/env python3
"""Verify bundle integrity, Skill entrypoints, portable rules and private-path hygiene."""
from pathlib import Path
import json,re,sys
import yaml
from sync_skills import bundle,ROOT,digest

def main():
    data=bundle()  # Includes retired route and executor capability checks.
    for name in data['skills']:
        source=(ROOT/'skills'/name/'SKILL.md').read_text(encoding='utf-8-sig');front=source.split('---',2)
        meta=yaml.safe_load(front[1])
        if meta.get('name')!=name or not meta.get('description'):raise ValueError('Invalid Skill entry: '+name)
    index=json.loads((ROOT/'memory/记忆索引.json').read_text(encoding='utf-8-sig'))
    for rule in index['rules']:
        if digest(ROOT/'memory'/rule['file']['path'])!=rule['file']['sha256']:raise ValueError('Memory hash mismatch')
    issues=[]
    for row in data['files']:
        path=ROOT/row['path']
        if path.suffix not in {'.py','.md','.json','.yaml','.yml','.js'}:continue
        text=path.read_text(encoding='utf-8-sig')
        if re.search(r'/Users/[A-Za-z0-9_-]+/|/var/folders/|gh[pousr]_[A-Za-z0-9]{24,}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----',text):issues.append(row['path'])
    if issues:raise ValueError('Local paths or credential-shaped content: '+', '.join(issues))
    print(json.dumps({'status':'PASS','skills':len(data['skills']),'rules':len(index['rules']),'files':len(data['files'])}))
if __name__=='__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    main()
