#!/usr/bin/env python3
"""Copy one batch's executable skills and rule bytes; never migrate an old RV."""
from __future__ import annotations
from codex_reference_contract import is_file, is_symlink, path_exists, read_json, resolve_path, scan_directory
import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from platform_io import portable_relative, check_destination_paths

POLICY = 'batch_snapshot_v1'
SKILLS = ('vertical-comic-preproduction', 'vertical-comic-visual-assets',
          'vertical-comic-shot-design', 'vertical-comic-panel-generation', 'vertical-comic-image-review')


def sha(path):
    from codex_reference_contract import digest
    return digest(Path(path))


def _verify(ref, *, executing_script=None):
    path = Path(ref['path'])
    if not path.is_absolute() or is_symlink(path) or sha(path) != ref['sha256']:
        raise ValueError('SNAPSHOT_HOLD: manifest版本不一致')
    path = resolve_path(path)
    data = read_json(path)
    if data.get('policy') != POLICY or not isinstance(data.get('files'), list) or not data['files']:
        raise ValueError('SNAPSHOT_HOLD: 清单无效')
    root = resolve_path(path.parent)
    names = set()
    for item in data['files']:
        portable_relative(item['path'])
        name = Path(item['path']); target = root / name
        if name.is_absolute() or '..' in name.parts or item['path'] in names:
            raise ValueError('SNAPSHOT_HOLD: 清单路径重复或越界')
        names.add(item['path'])
        if not resolve_path(target).is_relative_to(root) or is_symlink(target) or sha(target) != item['sha256']:
            raise ValueError('SNAPSHOT_HOLD: 实际运行文件已变化: '+str(name))
    actual = {p.relative_to(root).as_posix() for p in scan_directory(root,recursive=True,
              excluded_parts=('__pycache__','__MACOSX'),excluded_names=('.DS_Store',),excluded_suffixes=('.pyc',),excluded_paths=(path.name,)) if is_file(p)
              and p != path and '__pycache__' not in p.parts and '__MACOSX' not in p.parts and p.name!='.DS_Store' and p.suffix != '.pyc'}
    if actual != names:
        raise ValueError('SNAPSHOT_HOLD: 快照文件集合变化')
    scripts = root / 'skills/vertical-comic-preproduction/scripts'
    if executing_script is not None and resolve_path(Path(executing_script)).parent != scripts:
        raise ValueError('SNAPSHOT_HOLD: 请从本批快照scripts运行，不能混用安装入口')
    memory = data.get('memory_source')
    if memory:
        memory = {**memory, 'root': str(root / 'memory'), 'runtime_snapshot': ref}
    return {'scripts': str(scripts), 'memory_source': memory, 'data': data}


def verify(ref, *, executing_script=None):
    from audit_cache import derived
    return __import__('copy').deepcopy(derived('runtime_snapshot',[ref,str(executing_script) if executing_script else None],
                   lambda:_verify(ref,executing_script=executing_script)))


def create(destination, *, skills_root=None, memory_source=None):
    dest = resolve_path(Path(destination))
    if path_exists(dest):
        raise ValueError('快照目录已存在；恢复请使用原manifest，不覆盖或重建')
    source = Path(skills_root or resolve_path(Path(__file__)).parents[2])
    check_destination_paths(dest, ['skills/' + p.relative_to(source).as_posix() for name in SKILLS for p in (source / name).rglob('*') if is_file(p)])
    dest.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.comic-snapshot-', dir=dest.parent))
    try:
        origins = []
        for name in SKILLS:
            folder = source / name
            if not is_file(folder / 'SKILL.md'):raise ValueError('缺少skill入口:'+name)
            for p in sorted(folder.rglob('*')):
                if not is_file(p) or p.name=='.DS_Store' or any(x in p.parts for x in ('__pycache__', '__MACOSX', '.git', 'tests')) or p.suffix == '.pyc':
                    continue
                rel = Path('skills') / name / p.relative_to(folder)
                target = stage / rel; target.parent.mkdir(parents=True, exist_ok=True)
                before = sha(p); shutil.copyfile(p, target)
                if before != sha(p) or before != sha(target):
                    raise ValueError('创建时来源仍在变化，请在维护完成后重建快照')
                origins.append((p, before))
        frozen_memory = None
        if memory_source:
            from rule_memory import source_index
            root, index = source_index(memory_source)
            refs = [{'path': memory_source.get('index', '记忆索引.json'),
                     'sha256': sha(root / memory_source.get('index', '记忆索引.json'))}]
            refs.extend(r['file'] for r in index['rules'])
            if index.get('maintenance_guide'):refs.append(index['maintenance_guide'])
            for item in refs:
                p = resolve_path(root / item['path'])
                if not p.is_relative_to(root) or sha(p) != item['sha256']:
                    raise ValueError('规则来源变化或越界')
                target = stage / 'memory' / item['path']; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, target); origins.append((p, item['sha256']))
            frozen_memory = {k:v for k,v in memory_source.items() if k not in {'root','runtime_snapshot'}}
        if any(sha(p) != expected for p, expected in origins):
            raise ValueError('快照收尾时来源变化；未激活本批版本')
        files = [{'path':p.relative_to(stage).as_posix(), 'sha256':sha(p)}
                 for p in sorted(stage.rglob('*')) if is_file(p)]
        for item in files:
            portable_relative(item['path'])
        manifest = {'policy':POLICY, 'files':files, 'memory_source':frozen_memory,
                    'origin_skills_root':str(resolve_path(source)),
                    'origin_memory_root':(memory_source or {}).get('root')}
        (stage / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
        os.rename(stage, dest)
    finally:
        if path_exists(stage): shutil.rmtree(stage)
    ref = {'path':str(dest / 'manifest.json'), 'sha256':sha(dest / 'manifest.json')}
    verify(ref)
    return ref


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--destination', required=True)
    p.add_argument('--config')
    a = p.parse_args()
    memory = None
    if a.config:
        from usage_config import read_config, memory_source
        memory = memory_source(read_config(a.config))
    if memory is None:
        from builtin_memory import resolve
        memory=resolve()
    ref = create(a.destination, memory_source=memory)
    print(json.dumps({'runtime_snapshot':ref, **{k:v for k,v in verify(ref).items() if k!='data'}}, ensure_ascii=False))


if __name__ == '__main__':
    from platform_io import configure_stdio
    configure_stdio()
    main()
