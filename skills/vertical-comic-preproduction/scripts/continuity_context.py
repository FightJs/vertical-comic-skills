"""Read approved prior shots for a single-panel package; no invented prior output."""
import json
import os
from pathlib import Path
from codex_reference_contract import checked_file,read_json

POLICY='approved_shot_context_v1'
SOURCE_FILES=('source_script','source_snapshot','visual_basis','shot_manifest','visual_approval','shot_approval')

def read(path):return read_json(path)
def approval(source,key,base):
    value=source[key]
    return read(checked_file(base,value)) if isinstance(value,dict) and value.get('path') else value

def source_base(source,context_dir):
    value=Path(source['root'])
    mode=source.get('root_mode')
    if mode=='context_relative_v1':
        if value.is_absolute():raise ValueError('可移植上下文须使用相对根')
        return (Path(context_dir)/value).resolve()
    if mode is not None or not value.is_absolute():raise ValueError('来源根模式或绝对路径无效')
    return value.resolve()

def portable_context(context,context_dir):
    """Call BEFORE approval; relocation never rewrites approved context bytes."""
    return {**context,'sources':[{**s,'root':os.path.relpath(source_base(s,context_dir),Path(context_dir).resolve()),'root_mode':'context_relative_v1'} for s in context['sources']]}

def uid(episode,panel):return panel if panel.startswith(episode+'-') else episode+'-'+panel

class PriorShots(dict):
    def __init__(self,episode):super().__init__();self.episode=episode
    def get(self,key,default=None):return super().get(uid(self.episode,key) if isinstance(key,str) and key.startswith('P') else key,default)
    def __setitem__(self,key,value):super().__setitem__(uid(self.episode,key) if key.startswith('P') else key,value)

def load_context(manifest,root):
    episode=manifest.get('episode_id');previous=PriorShots(episode) if isinstance(episode,str) else {}
    if not manifest.get('continuity_context'):return previous,[]
    errors=[]
    try:
        if root is None:raise ValueError('带前格上下文的包须提供实际包根目录')
        context_path=checked_file(Path(root),manifest['continuity_context']);context=read(context_path)
        panels=manifest.get('panels',[])
        if not panels or context.get('policy')!=POLICY or context.get('book_id')!=manifest.get('book_id') or context.get('current')!={'episode_id':episode,'panel_id':panels[0]['panel_id']}:raise ValueError('上下文版本/书/当前源格不一致')
        order=context.get('episode_order',[])
        if not isinstance(order,list) or episode not in order or len(set(order))!=len(order):raise ValueError('上下文须绑定真实话序')
        from staged_workflow import approval_errors
        sources=[]
        scoped_sources=set()
        for source_index,source in enumerate(context.get('sources',[])):
            base=source_base(source,context_path.parent);source={**source,'root':str(base)};other=source['episode_id']
            if not base.is_absolute() or other not in order or order.index(other)>order.index(episode):raise ValueError('来源根或话序无效')
            files={k:checked_file(base,source[k]) for k in SOURCE_FILES[:4]}
            snap=read(files['source_snapshot']);basis=read(files['visual_basis']);shots=read(files['shot_manifest'])
            if basis.get('book_id')!=manifest['book_id'] or basis.get('episode_id')!=other or snap.get('source_sha256')!=source['source_script']['sha256']:raise ValueError('来源书话/源版本失配')
            for key in ('book_id','episode_id'):
                if shots.get(key) is not None and shots[key]!=basis[key]:raise ValueError('来源镜头归属失配')
            source_ids=[e['panel_id'] for e in context.get('entries',[]) if e.get('source')==source_index]
            errors.extend(approval_errors(approval(source,'visual_approval',base),base,[source['source_script'],source['source_snapshot'],source['visual_basis']],manifest['book_id'],other,phase='visual_basis',panel_ids=source_ids))
            from panel_readiness import candidate_source,enabled,approval_errors_for
            if enabled(shots):
                scoped_sources.add(source_index)
                if not candidate_source(source):
                    ids=[e['panel_id'] for e in context.get('entries',[]) if e.get('source')==source_index]
                    literal={k:source[k] for k in SOURCE_FILES[:4]};literal.update(book_id=manifest['book_id'],episode_id=other)
                    originals=source.get('shot_approvals',[])
                    if not isinstance(originals,list):raise ValueError('上下文批准集合须保留原证明清单')
                    originals=[read(checked_file(base,p)) if isinstance(p,dict) and p.get('path') else p for p in originals]
                    errors.extend(approval_errors_for(literal,base,'shot_design',[source['visual_basis'],source['shot_manifest']],ids,approval(source,'shot_approval',base),proofs=originals))
            elif not candidate_source(source):errors.extend(approval_errors(approval(source,'shot_approval',base),base,[source['visual_basis'],source['shot_manifest']],manifest['book_id'],other,phase='shot_design',panel_ids=source_ids))
            sources.append((source,snap,{p['panel_id']:p for p in shots.get('panels',[])}))
        positions=[]
        for entry in context.get('entries',[]):
            index=entry['source'];pid=entry['panel_id']
            if type(index) is not int or index<0 or index>=len(sources):raise ValueError('上下文来源索引无效')
            source,snap,shots=sources[index];ids=snap['panel_ids'];other=source['episode_id']
            if pid not in shots or pid not in ids or shots[pid].get('locked_script')!=snap['locked_scripts'][pid]:raise ValueError('上下文不是批准源稿的准确镜头')
            if other==episode and (panels[0]['panel_id'] not in ids or ids.index(pid)>=ids.index(panels[0]['panel_id'])):raise ValueError('不能把当前格/未来格作为前格')
            key=uid(other,pid)
            if key in previous:raise ValueError('上下文重复源格')
            from panel_readiness import candidate_source
            if not candidate_source(source) and index not in scoped_sources:
                proof=approval(source,'shot_approval',Path(source['root']))
                if proof.get('panel_ids') is not None and pid not in proof['panel_ids'] and key not in proof['panel_ids']:raise ValueError('原批准格范围不覆盖上下文')
            positions.append((order.index(other),ids.index(pid)));dict.__setitem__(previous,key,shots[pid])
        if not previous or positions!=sorted(positions):raise ValueError('前格上下文为空或乱序')
    except (OSError,ValueError,TypeError,KeyError,AttributeError,IndexError) as exc:errors.append(f'CONTINUITY_CONTEXT_HOLD:{exc}')
    return previous,errors

def binding_errors(state,root,packet,package_root):
    try:
        order=read(checked_file(Path(root),state['source_snapshot']))['panel_ids']
        pid=packet['panels'][0]['panel_id'];index=order.index(pid)
        if not packet.get('continuity_context'):
            return ['执行包缺少真实相邻前格上下文'] if state.get('execution_contract')=='comic_execution_v2' and (index>0 or state.get('episode_order',[state['episode_id']]).index(state['episode_id'])>0) else []
        context_path=checked_file(Path(package_root),packet['continuity_context']);data=read(context_path)
        if data.get('episode_order')!=state.get('episode_order',data.get('episode_order')):return ['上下文话序与本次任务不一致']
        for source in data['sources']:
            if source['episode_id']==state['episode_id']:
                same=source_base(source,context_path.parent)==Path(root).resolve() and source['source_script']==state['source_script'] and source['source_snapshot']==state['source_snapshot']
                inputs=list(state.get('half_inputs',{}).values()) or [state]
                from panel_readiness import enabled,compatible_collection
                context_ids=[e['panel_id'] for e in data['entries'] if data['sources'][e['source']]==source]
                matches=any(source['visual_basis']==s.get('visual_basis') and (source['shot_manifest']==s.get('shot_manifest') or enabled(state) and compatible_collection(root,source['shot_manifest'],s['shot_manifest'],context_ids,state['book_id'],state['episode_id'])) for s in inputs)
                if not same or not matches:return ['上下文使用了非本次冻结镜头/基准']
            elif source not in state.get('continuity_sources',[]):return ['跨话上下文未由总控冻结登记']
        last=data.get('entries',[])[-1];source=data['sources'][last['source']]
        if index>0:
            if source['episode_id']!=state['episode_id'] or last['panel_id']!=order[index-1]:return ['上下文未覆盖准确相邻前格，不能跳格规避规则']
        else:
            prior_episode=data['episode_order'][data['episode_order'].index(state['episode_id'])-1]
            prior_order=read(checked_file(source_base(source,context_path.parent),source['source_snapshot']))['panel_ids']
            if source['episode_id']!=prior_episode or last['panel_id']!=prior_order[-1]:return ['跨话上下文未覆盖上一话真实末格']
        return []
    except (OSError,ValueError,TypeError,KeyError,IndexError,StopIteration) as exc:return [f'CONTINUITY_CONTEXT_HOLD:{exc}']

def contextual_tags(manifest,root,panel):
    from panel_readiness import local_tags_manifest
    manifest=local_tags_manifest(manifest,panel)
    previous,errors=load_context(manifest,root)
    if errors:raise ValueError(';'.join(errors))
    index=next(i for i,p in enumerate(manifest.get('panels',[])) if p['panel_id']==panel['panel_id'])
    for earlier in manifest['panels'][:index]:previous[earlier['panel_id']]=earlier
    prior=next(reversed(previous.values()),None) if previous else None
    tags=['adjacent_panel_pair'] if prior else []
    if prior:
        old=prior.get('continuity_contract',{}).get('subjects',{});current=panel.get('continuity_contract',{}).get('subjects',{})
        comparable=panel.get('adjacent_face_comparison',{})
        common=set(old)&set(current)
        for person in common:
            if old[person].get('identity_visible') is not True or current[person].get('identity_visible') is not True:continue
            decision=comparable.get(person,{})
            if not isinstance(decision.get('face_comparable'),bool) or not decision.get('evidence'):raise ValueError(f'{person}:须核对相邻脸部是否可比较，不能靠漏标签跳过')
            if decision['face_comparable']:tags.append('same_character_adjacent_expression')
    return sorted(set(tags))

def rule_tags(manifest,root,panel):
    """One structural tag route; human/bed/mirror semantics still need review."""
    from rule_memory import effective_tags
    data=panel if 'memory_tags' in panel or manifest.get('memory_source') is not None else {**panel,'memory_tags':[]}
    data={k:v for k,v in data.items() if k!='operation'}
    return sorted(effective_tags(data,contextual_tags(manifest,root,panel)))

def build(state,root,pid,candidate=False):
    """Build pointers to already approved prior designs, without copying images."""
    root=Path(root).resolve();order=read(checked_file(root,state['source_snapshot']))['panel_ids'];index=order.index(pid)
    sources=list(state.get('continuity_sources',[]));episode=state['episode_id']
    from scoped_inputs import approval_for
    from scoped_inputs import full_preparation
    prepared=[('EPISODE',state)] if full_preparation(state) else list(state.get('half_inputs',{}).items())
    for bid,inputs in prepared:
        shots=read(checked_file(root,inputs['shot_manifest']))
        ids=[p['panel_id'] for p in shots['panels'] if order.index(p['panel_id'])<index]
        if not ids:continue
        gates=state.get('gates',{}) if full_preparation(state) else state.get('half_gates',{}).get(bid,{})
        def proof(phase,artifacts):
            if candidate and phase=='shot_design':
                from panel_readiness import enabled
                if enabled(state):return None
            direct=gates.get(phase)
            if direct is not None:
                isolated={k:v for k,v in state.items() if k!='approval_index'}
                if approval_for(isolated,root,phase,artifacts,ids,direct):raise ValueError('前格尚未有适用真实批准')
                return direct
            registry=read(checked_file(root,state['approval_index']))
            for entry in registry['entries']:
                if entry.get('phase')!=phase:continue
                value=read(checked_file(root,entry['approval']))
                isolated={k:v for k,v in state.items() if k!='approval_index'}
                if not approval_for(isolated,root,phase,artifacts,ids,value):return value
            raise ValueError('索引无适用前格批准')
        from panel_readiness import enabled,approval_errors_for
        source={'root':str(root),'episode_id':episode,'source_script':state['source_script'],'source_snapshot':state['source_snapshot'],**{k:inputs[k] for k in ('visual_basis','shot_manifest')},'visual_approval':proof('visual_basis',[state['source_script'],state['source_snapshot'],inputs['visual_basis']])}
        if enabled(state) and not candidate:
            originals=[gates['shot_design']] if isinstance(gates.get('shot_design'),dict) else []
            if state.get('approval_index'):
                registry=read(checked_file(root,state['approval_index']))
                for entry in registry.get('entries',[]):
                    if entry.get('phase')!='shot_design' or entry.get('book_id')!=state['book_id'] or episode not in entry.get('episode_ids',[]):continue
                    value=read(checked_file(root,entry['approval']))
                    # A restricted lookup must not widen the original scope in this context.
                    lookup=set(entry.get('panel_ids',[]));scope=set(value.get('panel_ids',[]))
                    if all(name in lookup or uid(episode,name) in lookup for name in ids if name in scope or uid(episode,name) in scope):originals.append(value)
            isolated={k:v for k,v in state.items() if k!='approval_index'}
            if approval_errors_for(isolated,root,'shot_design',[inputs['visual_basis'],inputs['shot_manifest']],ids,proofs=originals):raise ValueError('前格尚未有适用真实批准')
            source.update(shot_approval=None,shot_approvals=originals)
        else:source['shot_approval']=proof('shot_design',[inputs['visual_basis'],inputs['shot_manifest']])
        sources.append(source)
    entries=[];seen=set();episodes=state.get('episode_order',[episode])
    for s,source in enumerate(sources):
        base=Path(source['root']);snap=read(checked_file(base,source['source_snapshot']));shots=read(checked_file(base,source['shot_manifest']))
        for p in shots['panels']:
            name=p['panel_id'];other=source['episode_id'];key=uid(other,name)
            if episodes.index(other)>episodes.index(episode) or other==episode and order.index(name)>=index or key in seen:continue
            entries.append((episodes.index(other),snap['panel_ids'].index(name),{'source':s,'panel_id':name}));seen.add(key)
    value={'policy':POLICY,'book_id':state['book_id'],'current':{'episode_id':episode,'panel_id':pid},'episode_order':episodes,'sources':sources,'entries':[x[2] for x in sorted(entries,key=lambda x:x[:2])]}
    if not value['entries']:raise ValueError('无真实批准前格；源首格无需空上下文')
    return value

def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',required=True);p.add_argument('--panel',required=True);p.add_argument('--write',required=True);p.add_argument('--candidate',action='store_true');p.add_argument('--portable',action='store_true');a=p.parse_args()
    try:
        path=Path(a.state).resolve();root=path.parent.parent;value=build(read(path),root,a.panel,a.candidate);dest=Path(a.write).resolve();dest.relative_to(root)
        if a.portable:value=portable_context(value,dest.parent)
        with dest.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2)
        print(json.dumps({'status':'CANDIDATE_DESIGN_POINTERS_NOT_AUTHORIZED' if a.candidate else 'APPROVED_DESIGN_POINTERS_ONLY','path':str(dest)},ensure_ascii=False));return 0
    except (OSError,ValueError,TypeError,KeyError,IndexError) as exc:print(json.dumps({'status':'HOLD','errors':[str(exc)]},ensure_ascii=False));return 1

if __name__=='__main__':raise SystemExit(main())
