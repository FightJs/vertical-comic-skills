#!/usr/bin/env python3
"""Lossless transport for an already released handoff; no production authorization."""
import argparse, hashlib, json, shutil, tempfile, uuid, zipfile
from pathlib import Path
POLICY='handoff_transport_v1'
LIMIT=900000000
INDEX='传输索引.json'
def digest(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def encode(v): return json.dumps(v,ensure_ascii=False,sort_keys=True).encode()
def metadata(z):
    names=z.namelist()
    if len(names)!=len(set(names)): raise ValueError('重复ZIP成员')
    d=json.loads(z.read(INDEX))
    if d.get('policy')!=POLICY: raise ValueError('未知传输格式')
    return d
def identify(p):
    if not Path(p).is_file(): raise ValueError('正式ZIP不存在')
    with zipfile.ZipFile(p) as z:
        return metadata(z).get('kind') if INDEX in z.namelist() else None

def export(source,output,max_file_bytes=LIMIT,*,package_mode="allow_parts"):
    from handoff_zip import check_delivery_archive
    checked=check_delivery_archive(source)
    if checked.get('format')=='legacy_with_checksum': raise ValueError('先使用原发布流程形成内置发布证据的正式包')
    if package_mode not in {'single_zip','allow_parts'}:raise ValueError('未知包数限制')
    source=Path(source).resolve(); output=Path(output).resolve()
    if output.exists(): raise ValueError('输出目录必须全新')
    if not 65536<=max_file_bytes<=LIMIT: raise ValueError('卷容量须在65536至900000000字节之间')
    output.parent.mkdir(parents=True,exist_ok=True)
    before=digest(source)
    with tempfile.TemporaryDirectory(dir=output.parent) as td:
        td=Path(td); archive=td/'transport.zip'; rows=[]; seen=set()
        with zipfile.ZipFile(source) as src, zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as dst:
            for i in src.infolist():
                if i.is_dir(): continue
                temp=td/'object'
                with src.open(i) as a,temp.open('wb') as b: shutil.copyfileobj(a,b,1024*1024)
                h=digest(temp); rows.append({'path':i.filename,'sha256':h,'bytes':i.file_size})
                if h not in seen:
                    dst.write(temp,'objects/'+h);seen.add(h)
            dst.writestr(INDEX,encode({'policy':POLICY,'kind':'objects','source_sha256':before,'files':rows}))
            dst.writestr('交接说明.md','本包为无损精简交接容器。使用最新版Skill接包入口提供此ZIP路径，自动恢复原目录并校验；普通解压不能直接生产。')
        if before!=digest(source): raise ValueError('导出时原包发生变化')
        output.mkdir()
        try:
            if archive.stat().st_size<=max_file_bytes:
                shutil.copyfile(archive,output/'正式交接包.zip')
            else:
                if package_mode=='single_zip':
                    size=archive.stat().st_size
                    raise ValueError(f'DELIVERY_SIZE_HOLD:去重后{size}字节，上限{max_file_bytes}，超出{size-max_file_bytes}；严格单ZIP不自动分卷')
                # Conservative envelope reservation; verify actual ZIP size below.
                chunk=max_file_bytes-32768; parts=[]
                with archive.open('rb') as f:
                    n=0
                    while True:
                        n+=1;p=td/str(n);written=0
                        with p.open('wb') as out:
                            while written<chunk:
                                b=f.read(min(1024*1024,chunk-written))
                                if not b:break
                                out.write(b);written+=len(b)
                        if not written: p.unlink();break
                        parts.append({'number':n,'bytes':written,'sha256':digest(p)})
                index={'policy':POLICY,'kind':'volume','set_id':uuid.uuid4().hex,'container_sha256':digest(archive),'container_bytes':archive.stat().st_size,'parts':parts}
                for part in parts:
                    p=output/('正式交接包_第%03d卷_共%03d卷.zip'%(part['number'],len(parts)))
                    with zipfile.ZipFile(p,'w',compression=zipfile.ZIP_STORED) as z:
                        z.writestr(INDEX,encode(dict(index,number=part['number'])))
                        z.write(td/str(part['number']),'payload.bin')
                        z.writestr('交接说明.md','将全部卷下载到同一个本机目录，无需手动解压。把第001卷拖入已安装条漫Skill的Codex会话并发送，即可接包生产。使用原文件本机路径以便读取同目录其他卷；不能仅上传第001卷到无法访问其他卷的环境。系统自动核对总卷数、序号和哈希，缺卷将提示准确序号。')
                    if p.stat().st_size>max_file_bytes: raise ValueError('分卷包装超出容量，未发布')
            entry=next(iter(sorted(output.glob('*.zip'))))
            restored=td/'verify';recovery=restore(entry,restored)
            report={'policy':POLICY,'status':'VERIFIED_TRANSPORT','source_bytes':source.stat().st_size,'source_sha256':before,'original_files':len(rows),'unique_objects':len(seen),'files':[{'path':p.name,'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(output.glob('*.zip'))]}
            report.update(max_file_bytes=max_file_bytes,package_mode=package_mode,
                transport_bytes=sum(r['bytes'] for r in report['files']),recovery=recovery)
            report['recovery']={k:v for k,v in recovery.items() if k!='root'}
            (output/'运输验证.json').write_bytes(encode(report))
            return report
        except Exception:
            shutil.rmtree(output);raise

from handoff_zip import reception_cache

@reception_cache
def restore(entry,destination):
    from handoff_zip import check_delivery_directory
    from platform_io import check_destination_paths
    entry=Path(entry).resolve(); destination=Path(destination).resolve()
    if destination.exists(): raise ValueError('恢复目录须全新')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as td:
        td=Path(td); archive=entry
        with zipfile.ZipFile(entry) as z: idx=metadata(z)
        if idx['kind']=='volume':
            parts=idx['parts'];found={}
            if [p['number'] for p in parts]!=list(range(1,len(parts)+1)):raise ValueError('分卷顺序错误')
            for p in entry.parent.glob('*.zip'):
                try:
                    with zipfile.ZipFile(p) as z:
                        if INDEX not in z.namelist():continue
                        d=metadata(z)
                        if d.get('set_id')!=idx['set_id']:continue
                        if {k:v for k,v in d.items() if k!='number'}!={k:v for k,v in idx.items() if k!='number'}:raise ValueError('分卷索引冲突')
                        n=d['number']
                        if n in found:raise ValueError('重复分卷')
                        found[n]=p
                except zipfile.BadZipFile: continue
            missing=[p['number'] for p in parts if p['number'] not in found]
            if missing:raise ValueError('缺少分卷: '+str(missing))
            archive=td/'joined.zip'
            with archive.open('wb') as out:
                for part in parts:
                    temp=td/'part'
                    with zipfile.ZipFile(found[part['number']]) as z,z.open('payload.bin') as a,temp.open('wb') as b:shutil.copyfileobj(a,b,1024*1024)
                    if temp.stat().st_size!=part['bytes'] or digest(temp)!=part['sha256']:raise ValueError('分卷损坏')
                    with temp.open('rb') as f:shutil.copyfileobj(f,out,1024*1024)
            if archive.stat().st_size!=idx['container_bytes'] or digest(archive)!=idx['container_sha256']:raise ValueError('重组容器校验失败')
        staging=td/'restored';staging.mkdir()
        with zipfile.ZipFile(archive) as z:
            idx=metadata(z)
            if idx['kind']!='objects':raise ValueError('不是精简容器')
            rows=idx['files']; paths=[r['path'] for r in rows]
            check_destination_paths(staging,paths)
            if len(paths)!=len(set(paths)) or len({p.split('/')[0] for p in paths})!=1:raise ValueError('原路径重复或包根不唯一')
            required=sum(r['bytes'] for r in rows)+256*1024*1024
            if shutil.disk_usage(staging).free<required:raise ValueError('恢复落盘空间不足')
            restored_objects={}
            for row in rows:
                h=row['sha256']
                if len(h)!=64 or any(c not in '0123456789abcdef' for c in h):raise ValueError('非法对象哈希')
                target=staging/row['path'];target.parent.mkdir(parents=True,exist_ok=True)
                original=restored_objects.get(h)
                if original is None:
                    with z.open('objects/'+h) as a,target.open('wb') as b:shutil.copyfileobj(a,b,1024*1024)
                    if target.stat().st_size!=row['bytes'] or digest(target)!=h:raise ValueError('恢复文件损坏: '+row['path'])
                    restored_objects[h]=target
                else:
                    if original.stat().st_size!=row['bytes']:raise ValueError('同一对象大小冲突')
                    shutil.copyfile(original,target)  # Independent bytes, no writable hard links.
                    if target.stat().st_size!=row['bytes']:raise ValueError('恢复副本不完整')
        root=staging/paths[0].split('/')[0];check_delivery_directory(root)
        shutil.move(str(staging),str(destination))
        return {'root':str(destination/root.name),'status':'RESTORED_CHECKED','file_count':len(rows)}

def check_receipt(path,source,*,requirements=None):
    p=Path(path).resolve();d=json.loads(p.read_text(encoding='utf-8'))
    if d.get('status')!='VERIFIED_TRANSPORT' or d.get('source_sha256')!=digest(source):raise ValueError('运输记录与原正式包不符')
    dependencies={str(p):p.stat()}
    for row in d['files']:
        name=row['path']
        if Path(name).name!=name:raise ValueError('运输文件须在报告同目录')
        f=p.parent/name
        if f.stat().st_size!=row['bytes'] or digest(f)!=row['sha256']:raise ValueError('运输文件缺失或变化: '+name)
        dependencies[str(f)]=f.stat()
    if not d['files']:raise ValueError('运输文件集合为空')
    if requirements is not None:
        from delivery_contract import validate_artifact_set
        if (d.get('max_file_bytes')!=requirements['max_file_bytes'] or d.get('package_mode')!=requirements['package_mode']
            or d.get('transport_bytes')!=sum(r['bytes'] for r in d['files'])
            or d.get('recovery',{}).get('status')!='RESTORED_CHECKED'
            or d.get('recovery',{}).get('file_count')!=d.get('original_files')):
            raise ValueError('DELIVERY_RECEIPT_HOLD:运输回执缺容量限制或实际完整恢复结论')
        validate_artifact_set(requirements,[{**r,'path':str(p.parent/r['path'])} for r in d['files']])
    return list(dependencies)

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('export');a.add_argument('--zip',required=True);a.add_argument('--output',required=True);a.add_argument('--max-file-bytes',type=int,default=LIMIT);a.add_argument('--package-mode',choices=['single_zip','allow_parts'],default='allow_parts')
    a=sub.add_parser('restore');a.add_argument('--zip',required=True);a.add_argument('--destination',required=True)
    a=p.parse_args();print(json.dumps(export(a.zip,a.output,a.max_file_bytes,package_mode=a.package_mode) if a.action=='export' else restore(a.zip,a.destination),ensure_ascii=False,indent=2))
if __name__=='__main__':
    from platform_io import configure_stdio
    configure_stdio();main()
