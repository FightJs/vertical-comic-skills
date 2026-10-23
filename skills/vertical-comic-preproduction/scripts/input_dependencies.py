"""Content dependencies for draft derivation, never a persistent PASS cache."""
import hashlib
import json
import os
from pathlib import Path

POLICY = 'draft_input_dependencies_v1'

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def references(value):
    """Only explicit file references; ordinary prose is not a filesystem query."""
    if isinstance(value,dict):
        if isinstance(value.get('path'),str) and 'sha256' in value: yield value
        for item in value.values(): yield from references(item)
    elif isinstance(value,list):
        for item in value: yield from references(item)

def observe(path, *, scan=False):
    path=Path(os.path.abspath(path))
    link={'physical_target':str(path.resolve())}
    if not path.exists(): return {'path':str(path),'exists':False,**link}
    if path.is_file(): return {'path':str(path),'exists':True,'kind':'file','sha256':file_hash(path),**link}
    if not path.is_dir(): raise ValueError('不支持的依赖文件类型:'+str(path))
    if not scan: raise ValueError('目录依赖须显式声明kind=directory:'+str(path))
    # Capture membership and bytes, not just an mtime. Never run on a timer.
    members=[]
    for item in sorted(path.rglob('*')):
        if item.is_symlink():
            raise ValueError('目录扫描不递归复用符号链接；显式登记目标文件:'+str(item))
        members.append({'name':item.relative_to(path).as_posix(),'kind':'directory' if item.is_dir() else 'file',
                        **({'sha256':file_hash(item)} if item.is_file() else {})})
    return {'path':str(path),'exists':True,'kind':'directory','members':members,**link}

def capture(value, root, queries=(), memo=None):
    """Include transitive JSON refs, absent files and explicit directory queries."""
    root=Path(root); memo={} if memo is None else memo
    found={}; visiting=set()
    def visit(ref, base):
        raw=Path(ref['path']); path=Path(os.path.abspath(raw if raw.is_absolute() else base/raw))
        if not raw.is_absolute() and not path.exists() and (root/raw).exists():
            absent=observe(path);found[str(path)]=absent
            path=Path(os.path.abspath(root/raw))
        key=(str(path),False)
        if key not in memo: memo[key]=observe(path)
        observation=memo[key]
        if not observation.get('exists'): observation={**observation,'required_missing':True}
        found[str(path)]=observation
        if observation.get('exists') and observation.get('kind')=='file':
            if ref.get('sha256') and observation['sha256']!=ref['sha256']:
                raise ValueError('依赖哈希不匹配:'+str(path))
            if path.suffix.lower()=='.json' and str(path) not in visiting:
                visiting.add(str(path))
                parse_key=('json',str(path))
                if parse_key not in memo: memo[parse_key]=json.loads(path.read_text(encoding='utf-8-sig'))
                nested=memo[parse_key]
                for child in references(nested): visit(child,path.parent)
    for ref in references(value): visit(ref,root)
    for query in queries:
        path=Path(query['path']);path=path if path.is_absolute() else root/path
        scan=query.get('kind')=='directory';key=(str(path.absolute()),scan)
        if key not in memo: memo[key]=observe(path,scan=scan)
        found.setdefault(str(path.absolute()),memo[key])
    return [found[k] for k in sorted(found)]

def recheck(observations):
    for previous in observations:
        current=observe(previous['path'],scan=previous.get('kind')=='directory')
        if previous.get('required_missing') and not current.get('exists'): current['required_missing']=True
        if current!=previous: raise ValueError('DRAFT_DEPENDENCY_CHANGED:'+previous['path'])

def affected(old, current):
    """Conservative graph closure; no automatic adjacency or permission inference."""
    before={p['panel_id']:p for p in (old or {}).get('panels',[])}
    rows={p['panel_id']:p for p in current['panels']}
    changed={pid for pid,row in rows.items() if before.get(pid,{}).get('input_key')!=row['input_key']}
    removed=set(before)-set(rows)
    touched=set(changed); reasons={pid:['input_or_dependency_changed'] for pid in changed}
    while True:
        more={pid for pid,row in rows.items() if set(row.get('depends_on',[])) & (touched|removed)}-touched
        if not more: break
        for pid in more: reasons[pid]=['actual_dependency_changed']
        touched.update(more)
    comparison_only={pid for pid,row in rows.items() if set(row.get('comparison_with',[])) & (touched|removed)}-touched
    return {'review_panel_ids':[p for p in rows if p in touched|comparison_only],
            'comparison_only_panel_ids':[p for p in rows if p in comparison_only],
            'changed_panel_ids':[p for p in rows if p in changed],
            'affected_panel_ids':[p for p in rows if p in touched],
            'unchanged_panel_ids':[p for p in rows if p not in touched],
            'removed_panel_ids':sorted(removed),'reasons':reasons,
            'review_reuse_authorized':False,'dispatch_authorized':False}
