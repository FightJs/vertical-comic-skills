#!/usr/bin/env python3
"""Account-free release updates for the complete comic Skill bundle."""
from pathlib import Path
import argparse,hashlib,json,os,re,shutil,stat,subprocess,sys,tempfile,urllib.request,urllib.error,zipfile
from urllib.parse import urlparse
from platform_io import portable_relative,configure_stdio
from installation_state import read,write,digest,restore,available_backups,inventory,USER,NAME,SKILLS

REPOSITORY='FightJs/vertical-comic-skills'
API='https://api.github.com/repos/'+REPOSITORY
MAX_ARCHIVE=150*1024*1024
MAX_EXPANDED=512*1024*1024

def home_path(explicit=None):
    if explicit:return Path(explicit).expanduser().resolve()
    if os.environ.get('CODEX_HOME'):return Path(os.environ['CODEX_HOME']).expanduser().resolve()
    installed=Path(__file__).resolve().parents[3]
    if (installed/'skill-bundles'/NAME/'installed.json').is_file():return installed
    return Path.home()/'.codex'

def json_request(url):
    request=urllib.request.Request(url,headers={'Accept':'application/vnd.github+json','User-Agent':'vertical-comic-skills-updater'})
    with urllib.request.urlopen(request,timeout=20) as response:
        content=response.read(2*1024*1024+1)
    if len(content)>2*1024*1024:raise ValueError('版本元数据过大')
    return json.loads(content)

def remote_version(channel='stable'):
    if channel=='preview':
        value=json_request(API+'/commits/main');commit=value['sha']
        if not re.fullmatch('[a-f0-9]{40}',commit):raise ValueError('无效预览提交')
        return {'channel':channel,'identity':commit,'url':'https://github.com/'+REPOSITORY+'/archive/'+commit+'.zip','commit':commit}
    release=json_request(API+'/releases/latest');version=release['tag_name']
    if release.get('draft') or release.get('prerelease') or not re.fullmatch(r'v\d{4}\.\d{2}\.\d{2}\.\d+',version):raise ValueError('没有可用稳定发布')
    filename='vertical-comic-skills-'+version+'.zip'
    assets={a['name']:a['browser_download_url'] for a in release.get('assets',[])}
    # Old releases need an explicit new-format release; never silently switch to main.
    if filename not in assets or filename+'.sha256' not in assets:raise ValueError('最新Release尚无统一更新包，请维护者发布新格式稳定版；未改安装')
    for key in (filename,filename+'.sha256'):
        if urlparse(assets[key]).scheme!='https' or urlparse(assets[key]).hostname!='github.com' or not urlparse(assets[key]).path.startswith('/'+REPOSITORY+'/releases/download/'):
            raise ValueError('发布下载来源不符')
    return {'channel':'stable','identity':version,'version':version,'url':assets[filename],'checksum_url':assets[filename+'.sha256'],'filename':filename,'release_url':release['html_url']}

def installed_status(home):
    marker=Path(home)/'skill-bundles'/NAME/'installed.json'
    if not marker.is_file():return {'version':None,'managed':False,'local_changes':[]}
    value=read(marker);actual=inventory(Path(home));expected=value['files']
    changes=sorted(k for k in set(actual)|set(expected) if not k.startswith(USER+'/') and actual.get(k)!=expected.get(k))
    return {'version':value.get('version'),'managed':True,'source':value.get('source',{}),'local_changes':changes}

def version_key(value):return tuple(map(int,re.findall(r'\d+',value or '')))

def check(home,channel='stable'):
    local=installed_status(home);remote=remote_version(channel)
    same=(local.get('version')==remote.get('version')) if channel=='stable' else (local.get('source',{}).get('commit')==remote['commit'])
    ahead=channel=='stable' and version_key(local.get('version'))>version_key(remote['version'])
    status='AHEAD_OF_STABLE' if ahead else 'UP_TO_DATE' if same else 'UPDATE_AVAILABLE'
    if local['local_changes']:status='LOCAL_CHANGES'
    return {'status':status,'installed':local,'available':remote,'codex_home':str(home)}

def download(url,destination,limit=MAX_ARCHIVE):
    request=urllib.request.Request(url,headers={'User-Agent':'vertical-comic-skills-updater'})
    with urllib.request.urlopen(request,timeout=20) as response,Path(destination).open('xb') as output:
        size=0
        while True:
            block=response.read(1024*1024)
            if not block:break
            size+=len(block)
            if size>limit:raise ValueError('下载超过大小限制')
            output.write(block)

def unpack(archive,destination):
    destination=Path(destination)
    if destination.exists():raise ValueError('暂存解压目录必须全新')
    with zipfile.ZipFile(archive) as z:
        seen=set();top=None;total=0
        if len(z.infolist())>20000:raise ValueError('安装包文件数超限')
        for item in z.infolist():
            name=item.filename.rstrip('/');portable_relative(name);parts=name.split('/')
            if name.casefold() in seen or stat.S_ISLNK(item.external_attr>>16):raise ValueError('安装包含重复路径或符号链接')
            seen.add(name.casefold());top=top or parts[0]
            if parts[0]!=top or (len(parts)<2 and not item.is_dir()):raise ValueError('安装包须单一根目录')
            total+=item.file_size
            if total>MAX_EXPANDED:raise ValueError('安装包解压大小超限')
        if not top:raise ValueError('空安装包')
        # CRC is checked as entries are read; all paths checked before creating files.
        destination.mkdir()
        for item in z.infolist():
            target=destination/item.filename
            if item.is_dir():target.mkdir(parents=True,exist_ok=True)
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                with z.open(item) as src,target.open('xb') as dst:shutil.copyfileobj(src,dst)
    root=destination/top
    for name in ('VERSION','bundle.json','tools/sync_skills.py'):
        if not (root/name).is_file():raise ValueError('安装包缺少:'+name)
    return root

def validate_payload(root):
    """Check the declared Skill payload before executing its installer."""
    root=Path(root);value=read(root/'bundle.json')
    if value.get('policy')!='vertical_comic_bundle_v1' or set(value.get('skills',[]))!=set(SKILLS) or len(value['skills'])!=len(SKILLS):
        raise ValueError('安装包不是完整五件套')
    seen=set()
    for row in value['files']:
        name=row['path'];portable_relative(name)
        if name.split('/')[0] not in {'skills','memory'} or name.casefold() in seen:raise ValueError('安装清单路径重复或越界')
        seen.add(name.casefold());p=root/name
        if not p.is_file() or p.stat().st_size!=row['bytes'] or digest(p)!=row['sha256']:raise ValueError('安装包内容哈希失配:'+name)
    actual={p.relative_to(root).as_posix().casefold() for folder in ('skills','memory') for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='.DS_Store' and p.suffix!='.pyc'}
    if actual!=seen:raise ValueError('安装包存在未列入清单的文件')


def apply_archive(home,archive,work,*,source=None,replace_existing=False):
    root=unpack(archive,Path(work)/'extracted')
    validate_payload(root)
    version=(root/'VERSION').read_text(encoding='utf-8-sig').strip()
    if source and source.get('version') and source['version']!=version:raise ValueError('发布标签与包内版本不一致')
    source={**(source or {'channel':'offline'}),'archive_sha256':digest(archive)}
    write(root/'release-origin.json',source)
    command=[sys.executable,'-X','utf8','-B',str(root/'tools/sync_skills.py'),'--codex-home',str(home)]
    if replace_existing:command.append('--replace-existing')
    # The installer validates all bundle hashes, runtime and merged user rules before activation.
    result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
    if result.returncode:raise ValueError('更新未完成，原安装已保留或恢复：'+result.stdout+result.stderr)
    value=json.loads(result.stdout);value.update(version=version,source=source,codex_home=str(home),next='在新Codex轮次使用新版；正在运行的RV仍用原冻结快照')
    return value

def update(home,channel='stable',*,archive=None,replace_existing=False):
    if archive:
        with tempfile.TemporaryDirectory(prefix='comic-update-') as temp:return apply_archive(home,Path(archive),temp,replace_existing=replace_existing)
    state=check(home,channel)
    if state['status'] in {'UP_TO_DATE','AHEAD_OF_STABLE'}:return state
    if state['status']=='LOCAL_CHANGES' and not replace_existing:raise ValueError('LOCAL_CHANGES: '+', '.join(state['installed']['local_changes'][:8]))
    remote=state['available']
    with tempfile.TemporaryDirectory(prefix='comic-update-') as temp:
        work=Path(temp);archive=work/'download.zip'
        download(remote['url'],archive)
        if channel=='stable':
            side=work/'checksum.txt';download(remote['checksum_url'],side,limit=4096)
            tokens=side.read_text(encoding='utf-8').strip().split()
            if len(tokens)!=2 or tokens[1]!=remote['filename'] or tokens[0]!=digest(archive):raise ValueError('发布ZIP校验失败，未改变安装')
        return apply_archive(home,archive,work,source=remote,replace_existing=replace_existing)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['check','update','backups','restore'])
    parser.add_argument('--codex-home');parser.add_argument('--channel',choices=['stable','preview'],default='stable')
    parser.add_argument('--from-zip');parser.add_argument('--backup');parser.add_argument('--replace-existing',action='store_true');args=parser.parse_args();home=home_path(args.codex_home)
    try:
        if args.action=='check':result=check(home,args.channel)
        elif args.action=='update':result=update(home,args.channel,archive=args.from_zip,replace_existing=args.replace_existing)
        elif args.action=='backups':result={'status':'BACKUPS','backups':available_backups(home)}
        else:result=restore(home,args.backup,replace_existing=args.replace_existing)
        print(json.dumps(result,ensure_ascii=False));return 0
    except (OSError,ValueError,KeyError,TypeError,TimeoutError,zipfile.BadZipFile,subprocess.CalledProcessError) as exc:
        print(json.dumps({'status':'UPDATE_HOLD','error':str(exc),'codex_home':str(home),'production_rv_changed':False},ensure_ascii=False));return 1
if __name__=='__main__':configure_stdio();raise SystemExit(main())
