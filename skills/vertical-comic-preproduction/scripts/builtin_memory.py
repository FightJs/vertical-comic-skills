"""One built-in rule library plus preserved user additions; immutable resolved cache."""
from pathlib import Path
import hashlib,json,os,shutil,tempfile
from rule_memory import POLICY,LOADING_POLICY,source_index

ROOT=Path(__file__).resolve().parents[1]/'assets/rule-memory'

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def source(root,token=None):
    value={'policy':POLICY,'root':str(Path(root).resolve()),'index':'记忆索引.json','loading_policy':LOADING_POLICY}
    if token:value['index_sha256']=token
    return value

def resolve(*,library_root=None,cache_root=None):
    root=Path(library_root or ROOT).resolve();cache=Path(cache_root or Path.home()/'.codex/comic/cache/rules').resolve()
    entries=[];seen=set();origin=[]
    for name in ('内置规则','用户增补'):
        base=root/name;_,index=source_index(source(base));origin.append((base/'记忆索引.json',digest(base/'记忆索引.json')))
        for rule in index['rules']:
            if rule['id'] in seen:raise ValueError('规则ID冲突，禁止用户增补静默覆盖:'+rule['id'])
            seen.add(rule['id']);p=base/rule['file']['path']
            if not p.resolve().is_relative_to(base) or p.is_symlink() or digest(p)!=rule['file']['sha256']:raise ValueError('规则正文路径或哈希错误')
            entries.append({**rule,'file':{**rule['file'],'path':name+'/'+rule['file']['path']}});origin.append((p,digest(p)))
    index={**read(root/'内置规则/记忆索引.json'),'rules':entries}
    if index.get('maintenance_guide'):
        guide=index['maintenance_guide'];p=root/'内置规则'/guide['path']
        if digest(p)!=guide['sha256']:raise ValueError('规则维护说明哈希不符')
        index['maintenance_guide']={**guide,'path':'内置规则/'+guide['path']};origin.append((p,guide['sha256']))
    raw=(json.dumps(index,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode();token=hashlib.sha256(raw).hexdigest();dest=cache/token
    if not dest.exists():
        cache.mkdir(parents=True,exist_ok=True);stage=Path(tempfile.mkdtemp(prefix='.rules-',dir=cache))
        try:
            for p,expected in origin:
                if p.name=='记忆索引.json':continue
                target=stage/p.relative_to(root);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
                if digest(target)!=expected:raise ValueError('规则复制时变化')
            (stage/'记忆索引.json').write_bytes(raw)
            if any(digest(p)!=v for p,v in origin):raise ValueError('规则合并时变化，请维护完成后重试')
            try:os.rename(stage,dest)
            except OSError:
                if not dest.exists():raise
        finally:
            if stage.exists():shutil.rmtree(stage)
    result=source(dest,token);source_index(result)
    for rule in entries:
        if digest(dest/rule['file']['path'])!=rule['file']['sha256']:raise ValueError('规则缓存已损坏，不复用')
    return result
