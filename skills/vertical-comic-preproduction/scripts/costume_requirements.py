"""Compute reuse from explicitly observed script facts; never infer identity or pixels."""
import re

POLICY='costume_reuse_v1'

def plan(book_id, production_episodes, requirements, observations, *, coverage, source_catalog):
    if not book_id or not production_episodes or not isinstance(requirements,list) or not isinstance(observations,list):
        raise ValueError('COSTUME_HOLD: book, scope and observations required')
    if (not isinstance(source_catalog,dict) or source_catalog.get('policy')!='script_catalog_v1' or
        source_catalog.get('status')!='SELECTED_NOT_APPROVED' or source_catalog.get('book_id')!=book_id or
        source_catalog.get('production_episode_ids')!=production_episodes):
        raise ValueError('COSTUME_HOLD: selected source catalog scope required')
    selected=source_catalog.get('selected_sources',{})
    from script_catalog import digest, verified_episode_panels
    from pathlib import Path
    source_root=Path(source_catalog['root']).resolve(); verified_sources={}; panel_cache={}
    def number(value):
        if not isinstance(value,str) or not re.fullmatch(r'E\d{3,}',value):raise ValueError('COSTUME_HOLD: invalid episode')
        return int(value[1:])
    last=max(map(number,production_episodes)); output=[]; seen_requirements=set()
    for req in requirements:
        rid=req.get('requirement_id'); character=req.get('character_id'); costume=req.get('costume_id')
        if not rid or rid in seen_requirements or not character or not costume or not req.get('source_basis') or not req.get('panel_ids'):
            raise ValueError('COSTUME_HOLD: unique requirement and current source scope required')
        current_episode=req.get('episode_id')
        if not current_episode:
            if len(production_episodes)!=1:raise ValueError('COSTUME_HOLD: requirement episode required for batch source panels')
            current_episode=production_episodes[0]
        if current_episode not in production_episodes:raise ValueError('COSTUME_HOLD: requirement episode outside production')
        actual_ids=verified_episode_panels(source_catalog,current_episode,panel_cache)
        if any(p not in actual_ids for p in req['panel_ids']):raise ValueError('COSTUME_HOLD: current source panel not found')
        seen_requirements.add(rid); matches={}; uncertain=[]
        for row in observations:
            if row.get('character_id')!=character or number(row.get('episode_id'))<=last:continue
            if row.get('costume_id')!=costume and row.get('match')!='UNCERTAIN':continue
            if row.get('match')=='UNCERTAIN':
                uncertain.append(row);continue
            if row.get('match')!='CONFIRMED' or row.get('visible') is not True:continue
            if not row.get('panel_id') or not row.get('source_sha256') or not row.get('evidence'):
                raise ValueError('COSTUME_HOLD: confirmed observation lacks source evidence')
            if row['episode_id'] not in source_catalog.get('future_reference_episode_ids',[]):
                raise ValueError('COSTUME_HOLD: observation outside selected future reference scope')
            if row['panel_id'] not in verified_episode_panels(source_catalog,row['episode_id'],panel_cache):
                raise ValueError('COSTUME_HOLD: future source panel not found')
            source=selected.get(row['episode_id'])
            if not source or source.get('sha256')!=row['source_sha256']:
                raise ValueError('COSTUME_HOLD: observation is not bound to selected source')
            path=(source_root/source['path']).resolve()
            if path not in verified_sources:
                verified_sources[path]=path.is_relative_to(source_root) and path.is_file() and digest(path)==source['sha256']
            if not verified_sources[path]:
                raise ValueError('COSTUME_HOLD: selected source missing or changed')
            key=(row['episode_id'],row['panel_id'],character,costume)
            if key in matches and matches[key]['source_sha256']!=row['source_sha256']:
                raise ValueError('COSTUME_HOLD: conflicting selected script versions')
            matches[key]=row
        count=len(matches)
        output.append({**req,'episode_id':current_episode,'future_occurrences':list(matches.values()),'future_count':count,
                       'future_coverage':coverage,'uncertain_occurrences':uncertain,
                       'reuse_decision':'PUBLISH_AFTER_REVIEW' if count>=2 else 'BATCH_REFERENCE_FUTURE_UNKNOWN',
                       'publication_required':count>=2,'visual_review':'NOT_PERFORMED'})
    return {'policy':POLICY,'book_id':book_id,'production_episode_ids':production_episodes,
            'source_catalog':source_catalog,'input_requirements':requirements,'observations':observations,'coverage':coverage,
            'requirements':output,'image_calls':0}

def verify(result):
    actual=plan(result['book_id'],result['production_episode_ids'],result['input_requirements'],result['observations'],coverage=result['coverage'],source_catalog=result['source_catalog'])
    if actual!=result:raise ValueError('COSTUME_HOLD: reuse plan changed')
    return actual

def main():
    import argparse,json
    from pathlib import Path
    from platform_io import atomic_json
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    data=json.loads(Path(a.input).read_text(encoding='utf-8-sig'))
    result=plan(data['book_id'],data['production_episode_ids'],data['requirements'],data['observations'],coverage=data.get('coverage','UNKNOWN'),source_catalog=data['source_catalog'])
    out=Path(a.output)
    if out.exists():raise ValueError('COSTUME_HOLD: output exists')
    atomic_json(out,result);print(json.dumps({'status':'PLANNED_NOT_APPROVED','output':str(out)},ensure_ascii=False))
if __name__=='__main__':
    from platform_io import configure_stdio
    configure_stdio()
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,TypeError) as exc:
        import json
        print(json.dumps({'status':'COSTUME_HOLD','error':str(exc)},ensure_ascii=False))
        raise SystemExit(1)
