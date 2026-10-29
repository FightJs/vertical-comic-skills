#!/usr/bin/env python3
"""Export the five installed comic skills; never modify the installed sources."""
from pathlib import Path
import argparse,hashlib,json,re,shutil,tempfile

ROOT=Path(__file__).resolve().parents[1]
SKILLS=('vertical-comic-preproduction','vertical-comic-visual-assets','vertical-comic-shot-design','vertical-comic-panel-generation','vertical-comic-image-review')
EXCLUDED={'__pycache__','.git','.DS_Store'}

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def export(skills_root,memory_root):
    from sync_skills import check_production_routes
    check_production_routes(skills_root)
    tracked=[]
    with tempfile.TemporaryDirectory(prefix='.export-',dir=ROOT) as tmp:
        stage=Path(tmp)
        for name in SKILLS:
            source=skills_root/name
            if not (source/'SKILL.md').is_file():raise ValueError('Missing Skill: '+name)
            for p in sorted(source.rglob('*')):
                if p.is_symlink():raise ValueError('Symlink not published: '+str(p))
                if not p.is_file() or EXCLUDED.intersection(p.parts) or any(x.startswith(('.user-backup-','.user-rules-','.update-lock')) for x in p.parts) or p.suffix=='.pyc':continue
                h=digest(p);dest=stage/'skills'/name/p.relative_to(source);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
                tracked.append((p,h))
        memory_root=memory_root or skills_root/'vertical-comic-preproduction/assets/rule-memory/内置规则'
        index=json.loads((memory_root/'记忆索引.json').read_text(encoding='utf-8-sig'))
        memories=[memory_root/'记忆索引.json',memory_root/'规则记忆输入与增添规范.md']
        for rule in index['rules']:
            relative=Path(rule['file']['path'])
            if relative.is_absolute() or '..' in relative.parts:raise ValueError('Memory path escapes library')
            p=memory_root/relative
            if digest(p)!=rule['file']['sha256']:raise ValueError('Rule hash mismatch: '+rule['id'])
            memories.append(p)
        for p in memories:
            h=digest(p);dest=stage/'memory'/p.relative_to(memory_root);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest);tracked.append((p,h))
        # Distribution-only documentation changes: no project paths or local approvals.
        for p in stage.rglob('*'):
            if p.suffix not in {'.md','.yaml','.yml'}:continue
            s=p.read_text(encoding='utf-8-sig')
            s=re.sub(r'\[条漫Skill使用配置\.json\]\(/Users/[^/]+/Desktop/条漫/条漫Skill使用配置\.json\)','[配置示例](../../../examples/comic.config.example.json)',s)
            s=re.sub(r'/Users/[^/]+/Desktop/条漫/条漫Skill使用配置\.json','【项目绝对目录】/条漫Skill使用配置.json',s)
            s=re.sub(r'/Users/[^/]+/Desktop/条漫/规则记忆','【规则记忆绝对目录】',s)
            s=re.sub(r'/Users/[^/]+/\.codex/skills','~/.codex/skills',s)
            s=re.sub(r'[A-Z]:/Users/[^/]+/\.codex/skills','~/.codex/skills',s)
            s=s.replace('老祖心声有点野','示例作品A').replace('天灾末世','示例作品B')
            p.write_text(s, encoding='utf-8', newline='\n')
        # User additions belong to each installation, never to the shared release.
        additions=stage/'skills/vertical-comic-preproduction/assets/rule-memory/用户增补'
        if additions.exists():shutil.rmtree(additions)
        additions.mkdir(parents=True)
        (additions/'记忆索引.json').write_text(json.dumps({'policy':'triggered_rules_v1','loading_policy':'stage_baseline_loading_v1','rules':[]},ensure_ascii=False,indent=2)+'\n', encoding='utf-8', newline='\n')
        # Sanitized maintenance docs are content-bound by the distributed index.
        for index_path in stage.rglob('记忆索引.json'):
            data=json.loads(index_path.read_text(encoding='utf-8-sig'))
            for rule in data.get('rules',[]):
                file=index_path.parent/rule['file']['path']
                rule['file']['sha256']=digest(file)
            guide=data.get('maintenance_guide')
            if guide:guide['sha256']=digest(index_path.parent/guide['path'])
            index_path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n', encoding='utf-8', newline='\n')
        tests=stage/'skills/vertical-comic-preproduction/tests'
        needle=re.compile(r'''["']/Users/[^/]+/Desktop/条漫/条漫Skill使用配置\.json["']''')
        for p in tests.glob('test_*.py'):
            s=p.read_text(encoding='utf-8-sig')
            if not needle.search(s):continue
            s=needle.sub('config_path()',s)
            s=s.replace('老祖心声有点野','SYNTHETIC').replace('天灾末世','SYNTHETIC_B')
            # These modules have no future imports; keep the docstring first.
            lines=s.splitlines(True);lines.insert(1,'from _portable_config import config_path\n');p.write_text(''.join(lines), encoding='utf-8', newline='\n')
        helper=ROOT/'tools/portable_config_fixture.py'
        shutil.copyfile(helper,tests/'_portable_config.py')
        if any(digest(p)!=h for p,h in tracked):raise ValueError('Installed sources changed during export; retry after maintenance stops')
        for folder in ('skills','memory'):
            destination=ROOT/folder
            if destination.exists():shutil.rmtree(destination)
            shutil.move(stage/folder,destination)
    rows=[]
    for folder in ('skills','memory'):
        for p in sorted((ROOT/folder).rglob('*')):
            if p.is_file():rows.append({'path':p.relative_to(ROOT).as_posix(),'sha256':digest(p),'bytes':p.stat().st_size})
    (ROOT/'bundle.json').write_text(json.dumps({'policy':'vertical_comic_bundle_v1','skills':list(SKILLS),'files':rows},ensure_ascii=False,indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps({'skills':len(SKILLS),'rules':len(index['rules']),'files':len(rows)},ensure_ascii=False))

if __name__=='__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--skills-root',type=Path,required=True);parser.add_argument('--memory-root',type=Path);args=parser.parse_args();export(args.skills_root.resolve(),args.memory_root.resolve() if args.memory_root else None)
