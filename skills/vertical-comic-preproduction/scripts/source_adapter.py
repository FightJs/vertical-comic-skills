"""One immutable source-ID mapping; never renumber or rewrite original script content."""
import argparse,json,re
from pathlib import Path
from codex_reference_contract import checked_file,digest

POLICY='source_id_map_v1'

def adapted(source,episode,origin):
    order=source.get('panel_ids',[]);locked=source.get('locked_scripts',{})
    if not order or len(set(order))!=len(order) or set(locked)!=set(order):raise ValueError('源格序/原文缺失或重复')
    pairs=[]
    for name in order:
        match=re.fullmatch(r'(?:(E\d+)-)?(P\d{3})',name)
        if not match or match[1] not in (None,episode):raise ValueError('源编号不属于本话或不能无损映射')
        pairs.append({'source_panel_id':name,'panel_id':match[2]})
    ids=[p['panel_id'] for p in pairs]
    if len(set(ids))!=len(ids):raise ValueError('执行编号冲突，不能自动改源格号')
    return {**source,'panel_ids':ids,'locked_scripts':{p['panel_id']:locked[p['source_panel_id']] for p in pairs},
            'id_mapping':{'policy':POLICY,'episode_id':episode,'source_snapshot':origin,'pairs':pairs}}

def verify(source,root,episode):
    mapping=source.get('id_mapping')
    if mapping is None:return ['SOURCE_ID_HOLD:新合同须先冻结源编号映射']
    try:
        if mapping.get('policy')!=POLICY or mapping.get('episode_id')!=episode:raise ValueError('编号映射版本/话号不一致')
        original=json.loads(checked_file(Path(root),mapping['source_snapshot']).read_text())
        if source!=adapted(original,episode,mapping['source_snapshot']):raise ValueError('派生快照与源格序/原文字段不一致')
        return []
    except (OSError,ValueError,TypeError,KeyError) as exc:return [f'SOURCE_ID_HOLD:{exc}']

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True);p.add_argument('--source-snapshot',required=True);p.add_argument('--episode',required=True);p.add_argument('--write',required=True);a=p.parse_args()
    try:
        root=Path(a.root).resolve();source=Path(a.source_snapshot).resolve();source.relative_to(root)
        ref={'path':str(source.relative_to(root)),'sha256':digest(source)}
        value=adapted(json.loads(source.read_text()),a.episode,ref);dest=Path(a.write).resolve();dest.relative_to(root)
        with dest.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2)
        print(json.dumps({'status':'DERIVED_SOURCE_ONLY','path':str(dest),'panels':len(value['panel_ids'])},ensure_ascii=False));return 0
    except (OSError,ValueError,TypeError,KeyError) as exc:print(json.dumps({'status':'HOLD','errors':[str(exc)]},ensure_ascii=False));return 1

if __name__=='__main__':raise SystemExit(main())
