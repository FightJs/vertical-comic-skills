#!/usr/bin/env python3
"""Build one immutable, account-free installer ZIP from a validated bundle."""
from pathlib import Path
import argparse,hashlib,json,re,zipfile
from sync_skills import bundle,ROOT,digest

def build(output):
    data=bundle();version=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'v\d{4}\.\d{2}\.\d{2}\.\d+',version):raise ValueError('Invalid release version')
    user=ROOT/'skills/vertical-comic-preproduction/assets/rule-memory/用户增补'
    if json.loads((user/'记忆索引.json').read_text(encoding='utf-8-sig')).get('rules') or {p.relative_to(user).as_posix() for p in user.rglob('*') if p.is_file()}!={'记忆索引.json'}:
        raise ValueError('Release must not include personal user additions')
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    archive=output/('vertical-comic-skills-'+version+'.zip');side=Path(str(archive)+'.sha256')
    if archive.exists() or side.exists():raise ValueError('Release artifacts already exist; do not overwrite')
    sources=[ROOT/p for p in ('README.md','VERSION','bundle.json','requirements.txt','.gitattributes')]
    for folder in ('skills','memory','tools','tests'):
        sources.extend(sorted(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc' and p.name!='.DS_Store'))
    if any(p.is_symlink() for p in sources):raise ValueError('Symlink in release')
    before={p.relative_to(ROOT).as_posix():digest(p) for p in sources};top='vertical-comic-skills-'+version
    try:
        with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=5) as z:
            for p in sources:z.write(p,top+'/'+p.relative_to(ROOT).as_posix())
        if before!={p.relative_to(ROOT).as_posix():digest(p) for p in sources}:raise ValueError('Release inputs changed while packing')
        with zipfile.ZipFile(archive) as z:
            if z.testzip():raise ValueError('ZIP CRC failure')
        side.write_text(digest(archive)+'  '+archive.name+'\n',encoding='utf-8',newline='\n')
    except Exception:archive.unlink(missing_ok=True);side.unlink(missing_ok=True);raise
    return {'version':version,'zip':str(archive),'checksum':str(side),'sha256':digest(archive),'files':len(sources)}
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',default='dist');a=p.parse_args()
    print(json.dumps(build(a.output),ensure_ascii=False))
