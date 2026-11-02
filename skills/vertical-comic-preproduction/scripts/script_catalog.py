"""Inventory script files; filename hints are candidates, never semantic approval."""
import hashlib
import json
import re
from pathlib import Path
from platform_io import atomic_json

POLICY = 'script_catalog_v1'
SUPPORTED = {'.xlsx', '.json', '.md', '.txt', '.docx'}

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def workbook_hints(path):
    """Read workbook sheet titles and panel identifiers as raw evidence."""
    from openpyxl import load_workbook
    result=[]
    with Path(path).open('rb') as stream:
        workbook=load_workbook(stream,read_only=True,data_only=False)
        try:
            for sheet in workbook:
                title=sheet.title
                match=re.fullmatch(r'第\s*(\d+)\s*话',title) or re.fullmatch(r'(?i)E(\d+)',title)
                if not match:continue
                episode='E'+str(int(match.group(1))).zfill(3); panel_col=None;panels=[];panel_rows=[];columns={}
                for row_number,row in enumerate(sheet.iter_rows(values_only=True),1):
                    if panel_col is None:
                        for i,value in enumerate(row):
                            if isinstance(value,str) and value.strip()=='格号':panel_col=i;break
                        if panel_col is not None:
                            columns={str(v).strip():i for i,v in enumerate(row) if isinstance(v,str) and v.strip()}
                        continue
                    value=row[panel_col] if panel_col<len(row) else None
                    number=None
                    if isinstance(value,int) and not isinstance(value,bool) and value>0:number=value
                    elif isinstance(value,str) and re.fullmatch(r'(?:P)?\d+',value.strip(),re.I):number=int(value.strip().lstrip('Pp'))
                    if number is None:continue
                    panels.append(number);record={'panel_id':'P'+str(number).zfill(3),'source_panel':value,'row':row_number}
                    for label in ('出现角色','当前场景','当前天气','当前时间','景别','画面内容','台词','画面备注'):
                        i=columns.get(label)
                        if i is not None and i<len(row) and row[i] is not None:record[label]=str(row[i])
                    panel_rows.append(record)
                result.append({'episode_id':episode,'sheet':title,'panel_numbers':panels,'panel_evidence':panel_rows,
                               'status':'RAW_EVIDENCE_NOT_SEMANTIC_APPROVAL'})
        finally:workbook.close()
    return result

def discover(root, book, episodes, *, cache_root=None):
    root = Path(root).resolve()
    if not root.is_dir() or not book or not episodes:
        raise ValueError('SCRIPT_CATALOG_HOLD: directory, book and production episodes required')
    rows = []; parsed = {}; first_by_hash = {}; cache_hits=0; parses=0
    cache_root=Path(cache_root).resolve() if cache_root else None
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            continue
        if not path.is_file() or path.suffix.lower() not in SUPPORTED or path.name.startswith('~$'):
            continue
        rel = path.relative_to(root).as_posix()
        matches = sorted(set(re.findall(r'(?i)(?<![a-z0-9])E(\d{3,})(?!\d)', rel)))
        before=digest(path); workbook=[]; error=None
        if path.suffix.lower()=='.xlsx':
            cache_path=cache_root/(before+'.json') if cache_root else None; refresh_cache=False
            if before in parsed:
                workbook,error=parsed[before];cache_hits+=1
            elif cache_path and cache_path.is_file():
                try:
                    entry=json.loads(cache_path.read_text(encoding='utf-8-sig'))
                    payload=json.dumps(entry['workbook'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
                    if entry.get('policy')!='raw_workbook_catalog_cache_v4' or entry.get('source_sha256')!=before or entry.get('payload_sha256')!=hashlib.sha256(payload).hexdigest():raise ValueError('invalid cache')
                    workbook=entry['workbook'];cache_hits+=1
                except (OSError,ValueError,TypeError,KeyError):workbook=[]
                if not workbook:
                    try:workbook=workbook_hints(path);parses+=1;refresh_cache=True
                    except Exception as exc:error=str(exc)
                parsed[before]=(workbook,error)
            else:
                try:workbook=workbook_hints(path);parses+=1;refresh_cache=True
                except Exception as exc:error=str(exc)
                parsed[before]=(workbook,error)
            if digest(path)!=before:raise ValueError('SCRIPT_CATALOG_HOLD: source changed while scanning')
            if cache_path and workbook and not error:
                cache_root.mkdir(parents=True,exist_ok=True)
                payload=json.dumps(workbook,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
                if refresh_cache:atomic_json(cache_path,{'policy':'raw_workbook_catalog_cache_v4','source_sha256':before,'workbook':workbook,'payload_sha256':hashlib.sha256(payload).hexdigest()})
        version=re.search(r'(?i)(?:^|[_\-])(?:RV[_\-]?)?v(\d+)',path.stem)
        rows.append({'path': rel, 'sha256': before, 'episode_hints': ['E'+x for x in matches],
                     'workbook_evidence':workbook,'read_error':error,
                     'version_hint':version.group(0).strip('_-') if version else None,
                     'metadata_status': 'UNVERIFIED', 'book_hint': book if book in rel else None,
                     'duplicate_of':first_by_hash.get(before)})
        first_by_hash.setdefault(before,rel)
    grouped={}
    for row in rows:
        hints={x['episode_id'] for x in row['workbook_evidence']} | set(row['episode_hints'])
        for episode in hints:
            grouped.setdefault(episode,{})
            grouped[episode].setdefault(row['sha256'],{'sha256':row['sha256'],'paths':[],'version_hint':row['version_hint']})['paths'].append(row['path'])
    candidates={episode:{'status':'VERSION_CONFLICT' if len(versions)>1 else 'SINGLE_CANDIDATE_NOT_CONFIRMED',
                         'versions':list(versions.values())} for episode,versions in sorted(grouped.items())}
    return {'policy': POLICY, 'book_id': book, 'root': str(root),
            'production_episode_ids': list(episodes), 'files': rows,'episode_candidates':candidates,
            'selected_sources': {}, 'future_reference_episode_ids': [],
            'coverage': 'UNKNOWN', 'status': 'DISCOVERED_NOT_VERIFIED', 'metrics': {'workbook_parses':parses,'cache_reuses':cache_hits}}

def select(catalog, selections, *, evidence):
    """Bind an explicit semantic selection to file hashes, never infer latest version."""
    if catalog.get('policy') != POLICY or not evidence or not isinstance(selections, dict):
        raise ValueError('SCRIPT_CATALOG_HOLD: explicit selection and evidence required')
    root = Path(catalog['root']).resolve(); files = {r['path']: r for r in catalog['files']}
    chosen = {}
    for episode, entry in selections.items():
        if not re.fullmatch(r'E\d{3,}', episode) or not isinstance(entry, dict):
            raise ValueError('SCRIPT_CATALOG_HOLD: invalid episode selection')
        name = entry.get('path'); row = files.get(name)
        if not row or not entry.get('source_evidence') or not entry.get('version'):
            raise ValueError('SCRIPT_CATALOG_HOLD: file, version and actual source evidence required')
        observed=row.get('workbook_evidence',[])
        if observed and episode not in {x.get('episode_id') for x in observed}:
            raise ValueError('SCRIPT_CATALOG_HOLD: selected workbook does not contain episode '+episode)
        path = (root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or digest(path) != row['sha256']:
            raise ValueError('SCRIPT_CATALOG_HOLD: selected source changed')
        chosen[episode] = {'path':name, 'sha256':row['sha256'], 'version':entry['version'],
                           'source_evidence':entry['source_evidence'],**({'source_snapshot':entry['source_snapshot']} if entry.get('source_snapshot') else {})}
    missing = [e for e in catalog['production_episode_ids'] if e not in chosen]
    if missing: raise ValueError('SCRIPT_CATALOG_HOLD: production source unresolved: '+','.join(missing))
    last = max(int(e[1:]) for e in catalog['production_episode_ids'])
    future = sorted(e for e in chosen if int(e[1:]) > last)
    return {**catalog, 'selected_sources':chosen, 'future_reference_episode_ids':future,
            'selection_evidence':evidence, 'status':'SELECTED_NOT_APPROVED', 'coverage':'UNKNOWN'}

def verified_episode_panels(catalog, episode, cache=None):
    """Verify only selected source files; cached within one audit transaction."""
    cache={} if cache is None else cache
    selected=catalog.get('selected_sources',{}).get(episode)
    if not selected:raise ValueError('SOURCE_PANEL_HOLD: source episode not selected: '+episode)
    root=Path(catalog['root']).resolve();path=(root/selected['path']).resolve()
    if not path.is_relative_to(root) or not path.is_file():raise ValueError('SOURCE_PANEL_HOLD: source missing')
    key=(str(path),selected['sha256'])
    if key not in cache:
        if digest(path)!=selected['sha256']:raise ValueError('SOURCE_PANEL_HOLD: selected source changed')
        if path.suffix.lower()=='.xlsx':
            rows=workbook_hints(path)
            scopes={row['episode_id']:{'panel_ids':[r['panel_id'] for r in row['panel_evidence']]} for row in rows}
            if len(scopes)!=len(rows):raise ValueError('SOURCE_PANEL_HOLD: duplicate episode sheets')
        else:
            source=path
            snapshot=selected.get('source_snapshot')
            if snapshot:
                from codex_reference_contract import checked_file
                source=checked_file(root,snapshot)
            try:data=json.loads(source.read_text(encoding='utf-8-sig'))
            except (ValueError,UnicodeError) as exc:raise ValueError('SOURCE_PANEL_HOLD: non-XLSX source requires an extracted source snapshot') from exc
            if snapshot and data.get('source_sha256')!=selected['sha256']:raise ValueError('SOURCE_PANEL_HOLD: snapshot source mismatch')
            if data.get('book_id',catalog['book_id'])!=catalog['book_id']:raise ValueError('SOURCE_PANEL_HOLD: book mismatch')
            scopes=data.get('episodes') or {data.get('episode_id'):data}
        if digest(path)!=selected['sha256']:raise ValueError('SOURCE_PANEL_HOLD: source changed during read')
        cache[key]=scopes
    scope=cache[key].get(episode)
    ids=scope.get('panel_ids') if isinstance(scope,dict) else None
    if not isinstance(ids,list) or not ids or len(set(ids))!=len(ids) or any(not isinstance(i,str) or not re.fullmatch(r'P[0-9]{3,}',i) for i in ids):
        raise ValueError('SOURCE_PANEL_HOLD: missing or duplicate source panels: '+episode)
    return set(ids)

def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['discover','select'])
    p.add_argument('--root');p.add_argument('--cache-root');p.add_argument('--book');p.add_argument('--episodes',nargs='+');p.add_argument('--catalog');p.add_argument('--selections');p.add_argument('--evidence');p.add_argument('--output',required=True)
    a=p.parse_args()
    if a.action=='discover': result=discover(a.root,a.book,a.episodes,cache_root=a.cache_root)
    else:
        with open(a.catalog,encoding='utf-8-sig') as f: catalog=json.load(f)
        with open(a.selections,encoding='utf-8-sig') as f: selections=json.load(f)
        result=select(catalog,selections,evidence=a.evidence)
    out=Path(a.output)
    if out.exists(): raise ValueError('SCRIPT_CATALOG_HOLD: output already exists')
    out.parent.mkdir(parents=True,exist_ok=True);atomic_json(out,result)
    print(json.dumps({'status':result['status'],'path':str(out)},ensure_ascii=False))
if __name__=='__main__':
    from platform_io import configure_stdio
    configure_stdio()
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'SCRIPT_CATALOG_HOLD','error':str(exc)},ensure_ascii=False))
        raise SystemExit(1)
