"""Bind real checker versions and scoped semantic review; bulk preflight reuses QA once."""
from codex_reference_contract import resolve_path, scan_directory, is_file
import argparse,json
from pathlib import Path
from codex_reference_contract import checked_file,digest,read_json

POLICY='comic_execution_v2'
AUDIT='semantic_audit_v1'
CHECKS=('identity_resolution','reference_selection','per_subject_actions','space_and_visibility','rule_triggers','script_rule_conflicts')
def semantic_checks(state):
    return CHECKS + (('framing_feasibility',) if state.get('runtime',{}).get('question_policy')=='grouped_review_v1' or state.get('input_quality_policy')=='execution_quality_v1' else ())
SKILLS=('vertical-comic-preproduction','vertical-comic-visual-assets','vertical-comic-shot-design','vertical-comic-panel-generation','vertical-comic-image-review')

def toolchain(base=None):
    base=resolve_path(Path(base)) if base is not None else resolve_path(Path(__file__)).parent
    members=scan_directory(base,suffixes=('.py','.js'))
    if is_file(base/'runtime_capabilities.json'):members.append(base/'runtime_capabilities.json')
    files=[{'path':p.relative_to(base).as_posix(),'sha256':digest(p)} for p in sorted(members)]
    entries=[{'path':str(base.parent.parent/name/'SKILL.md'),'sha256':digest(base.parent.parent/name/'SKILL.md')} for name in SKILLS]
    return {'policy':'comic_toolchain_v1','release':POLICY,'root':str(base),'files':files,'skill_entries':entries}

def state_errors(state,root):
    try:
        from dispatch_publication import require_legacy
        require_legacy(state)
        from authority_updates import state_errors as authority_errors
        if state.get('source_input_policy') not in (None,'formal_source_inputs_v1'):
            raise ValueError('未知来源输入校验协议')
        if state.get('runtime_pipeline_policy') not in (None,'observed_incremental_pipeline_v1'):
            raise ValueError('未知增量流水线合同，不能降级')
        from stage_deadlines import enabled as speed_enabled
        speed_enabled(state)
        from light_review import enabled as light_enabled
        if light_enabled(state) and state.get('execution_mode') != 'episode_async_v1':
            raise ValueError('Light review requires a new whole-episode runtime')
        errors = authority_errors(state)
        if errors: return errors
        from production_decisions import enabled as production_enabled
        if production_enabled(state) and state.get('execution_mode') != 'episode_async_v1':
            raise ValueError('新生产决策仅用于新整话运行，不热迁移旧模式')
        from input_semantics import enabled as semantics_enabled
        semantics_enabled(state)
        from visual_evidence import binding_errors as visual_binding_errors
        visual_errors = visual_binding_errors(state)
        if visual_errors: raise ValueError(";".join(visual_errors))
        from panel_readiness import POLICY as READINESS
        if state.get('readiness_policy') not in (None,READINESS):raise ValueError('未知逐格准备策略')
        if state.get('readiness_policy')==READINESS and state.get('preparation_policy')!='episode_preparation_v1':raise ValueError('逐格准备只用于全话准备及半话生产')
        from scoped_inputs import PREPARATION,STATE_DISPATCH,EPISODE_MODE,EPISODE_POLICY
        valid_modes={('half_episode_async_v1','scoped_half_review_v1'),(EPISODE_MODE,EPISODE_POLICY)}
        mode_pair=(state.get('execution_mode'),state.get('optimization_policy'))
        if state.get('execution_mode')==EPISODE_MODE and (mode_pair!=(EPISODE_MODE,EPISODE_POLICY) or
                state.get('preparation_policy')!=PREPARATION or state.get('readiness_policy')!=READINESS or
                state.get('execution_contract')!=POLICY or state.get('runtime',{}).get('policy')!='incremental_runtime_v2'):
            raise ValueError('整话模式须完整绑定全话准备、逐格就绪、v2执行和runtime合同')
        if state.get('execution_mode')==EPISODE_MODE and state.get('calibration_reviews'):
            raise ValueError('整话模式使用episode_repair_v1，旧半话校准记录须显式迁移')
        if state.get('state_dispatch_policy') not in (None,STATE_DISPATCH):raise ValueError('未知新状态提交策略，不能静默降级')
        if state.get('state_dispatch_policy')==STATE_DISPATCH and (state.get('preparation_policy')!=PREPARATION or mode_pair not in valid_modes or state.get('execution_contract')!=POLICY or state.get('readiness_policy')!=READINESS):
            raise ValueError('普通新状态并发须配套全话准备、逐格就绪及完整执行合同')
        if state.get('preparation_policy') not in (None, PREPARATION):
            raise ValueError('未知前期准备策略，不能静默降级')
        if state.get('preparation_policy') == PREPARATION and mode_pair not in valid_modes:
            raise ValueError('全话准备须配套明确的半话或整话生产合同')
        runtime_policy='incremental_runtime_v2' if state.get('execution_mode')==EPISODE_MODE else 'incremental_runtime_v1'
        if state.get('preparation_policy') == PREPARATION and (state.get('execution_contract')!=POLICY or state.get('runtime',{}).get('policy')!=runtime_policy):
            raise ValueError('全话准备须使用完整执行合同与增量runtime，不能跳过全话语义核对')
        if state.get('runtime') is not None:
            from production_runtime import settings
            settings(state['runtime'])
            if mode_pair not in valid_modes:
                raise ValueError('增量runtime须配套明确生产模式，不静默降级')
        if state.get('execution_contract') is None:return []
        if state['execution_contract']!=POLICY or mode_pair not in valid_modes:raise ValueError('完整执行合同与生产模式不可混用/降级')
        if state.get('runtime',{}).get('snapshot_policy')=='batch_snapshot_v1' and not state.get('runtime_snapshot'):
            raise ValueError('SNAPSHOT_HOLD: 新策略缺少本批运行快照，不退回安装版本')
        if state.get('runtime_snapshot'):
            from runtime_snapshot import verify
            frozen=verify(state['runtime_snapshot'],executing_script=__file__)
            if state.get('memory_source') != frozen['memory_source']:
                raise ValueError('SNAPSHOT_HOLD: 规则来源未绑定本批快照')
        if state.get('toolchain')!=toolchain():raise ValueError('实际检查器/Skill版本与运行冻结记录不一致；使用共享入口，旧RV显式迁移')
        if state.get('source_snapshot'):
            from source_adapter import verify
            source=read_json(checked_file(Path(root),state['source_snapshot']));errors=verify(source,root,state['episode_id'])
            mapping={x['panel_id']:x['source_panel_id'] for x in source.get('id_mapping',{}).get('pairs',[])}
            errors.extend(f"SOURCE_ID_HOLD:{p.get('panel_id')}:进度原格号与冻结映射不一致" for p in state.get('panels',[]) if p.get('panel_id') not in mapping or p.get('source_panel_id')!=mapping[p['panel_id']])
            from frame_ratio_plan import plan_errors
            errors.extend(plan_errors(state,root,source))
            return errors
        return []
    except (OSError,ValueError,TypeError,KeyError) as exc:return [f'EXECUTION_CONTRACT_HOLD:{exc}']

def extra_basis_refs(state):
    from frame_ratio_plan import enabled
    return [*([state['semantic_audit']] if state.get('execution_contract')==POLICY else []),*([state['frame_ratio_plan']] if enabled(state) else [])]

def semantic_errors(state,root,batch,blocked=()):
    if state.get('execution_contract')!=POLICY:return []
    try:
        from scoped_inputs import full_preparation
        whole=full_preparation(state)
        ref=state.get('semantic_audit') if whole else state.get('half_inputs',{}).get(batch['batch_id'],{}).get('semantic_audit')
        data=read_json(checked_file(Path(root),ref))
        panel_ids=read_json(checked_file(Path(root),state['source_snapshot']))['panel_ids'] if whole else batch['panel_ids']
        expected={'policy':AUDIT,'book_id':state['book_id'],'episode_id':state['episode_id'],'source_snapshot':state['source_snapshot'],'visual_basis':state['visual_basis'],'shot_manifest':state['shot_manifest'],'panel_ids':panel_ids}
        if any(data.get(k)!=v for k,v in expected.items()):raise ValueError('语义核对范围/版本失配')
        if [p.get('panel_id') for p in data.get('panels',[])]!=panel_ids:raise ValueError('语义核对缺格/乱序')
        errors=[]
        from continuity_context import binding_errors as prior_binding, rule_tags
        from rule_memory import trigger_review_errors
        shot_path=checked_file(Path(root),state['shot_manifest']);shots=read_json(shot_path)
        from panel_readiness import enabled
        if not enabled(state):errors.extend(prior_binding(state,root,shots,shot_path.parent))
        from visual_evidence import shot_collection_errors
        basis = read_json(checked_file(Path(root),state['visual_basis']))
        errors.extend(shot_collection_errors(state,basis,shots,blocked))
        by_id={p['panel_id']:p for p in shots['panels']};tags={}
        for panel in shots['panels']:
            if panel['panel_id'] not in blocked:tags[panel['panel_id']]=rule_tags(shots,shot_path.parent,panel)
        for p in data['panels']:
            if p['panel_id'] in blocked:continue
            if p.get('status')!='REVIEWED' or not p.get('reviewer') or not p.get('evidence'):errors.append(f"{p['panel_id']}:尚未实际语义核对")
            for key in semantic_checks(state):
                c=p.get('checks',{}).get(key,{})
                if c.get('status')!='PASS' or not c.get('evidence'):errors.append(f"{p['panel_id']}:{key}缺少具体核对依据")
            if 'framing_feasibility' in semantic_checks(state):
                from visual_evidence import feasibility_errors
                errors.extend(feasibility_errors(by_id[p['panel_id']],p.get('checks',{}).get('framing_feasibility',{})))
            errors.extend(f"{p['panel_id']}:{e}" for e in trigger_review_errors(state.get('memory_source'),'shot_design',by_id[p['panel_id']],p.get('checks',{}).get('rule_triggers',{}),tags[p['panel_id']]))
        return errors
    except (OSError,ValueError,TypeError,KeyError,AttributeError,IndexError,StopIteration) as exc:return [f'SEMANTIC_AUDIT_HOLD:{exc}']

def semantic_template(state,root,bid):
    from panel_readiness import review_context
    from codex_reference_contract import file_session
    with file_session(), review_context(state,root,True):
        return _semantic_template(state,root,bid)


def _semantic_template(state,root,bid):
    from scoped_inputs import half_view
    from scoped_inputs import full_preparation
    if full_preparation(state):
        if bid not in (None,'EPISODE'):raise ValueError('全话准备只写一次EPISODE语义核对')
        ids=read_json(checked_file(Path(root),state['source_snapshot']))['panel_ids']
    else:
        state=half_view(state,bid);plan=read_json(checked_file(Path(root),state['batch_plan']));batch=next(b for b in plan['batches'] if b['batch_id']==bid)
        ids=batch['panel_ids']
    value={'policy':AUDIT,'book_id':state['book_id'],'episode_id':state['episode_id'],**{k:state[k] for k in ('source_snapshot','visual_basis','shot_manifest')},'panel_ids':ids,'panels':[{'panel_id':pid,'status':'UNREVIEWED','reviewer':'','evidence':'','checks':{k:{'status':'UNREVIEWED','evidence':''} for k in semantic_checks(state)}} for pid in ids]}
    if 'framing_feasibility' in semantic_checks(state):
        from visual_evidence import feasibility_questions
        shots=read_json(checked_file(Path(root),state['shot_manifest']))
        by_id={p['panel_id']:p for p in shots['panels']}
        for row in value['panels']:row['checks']['framing_feasibility']['expected']=feasibility_questions(by_id[row['panel_id']])
    if state.get('memory_source') is not None:
        from continuity_context import rule_tags
        from rule_memory import trigger_review
        path=checked_file(Path(root),state['shot_manifest']);shots=read_json(path);by_id={p['panel_id']:p for p in shots['panels']}
        for row in value['panels']:
            panel=by_id[row['panel_id']];row['checks']['rule_triggers'].update(trigger_review(state['memory_source'],'shot_design',panel,rule_tags(shots,path.parent,panel)))
    return value

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',required=True);p.add_argument('--panels',nargs='*');p.add_argument('--batch-preflight',action='store_true');p.add_argument('--write-semantic');p.add_argument('--batch');a=p.parse_args()
    try:
        path=resolve_path(Path(a.state));root=path.parent.parent;state=read_json(path);errors=state_errors(state,root)
        if errors:raise ValueError(';'.join(errors))
        if a.write_semantic:
            if not a.batch and state.get('preparation_policy')!='episode_preparation_v1':raise ValueError('旧模式语义核对模板须指定真实半话batch')
            value=semantic_template(state,root,a.batch);dest=resolve_path(Path(a.write_semantic));dest.relative_to(root)
            with dest.open('x',encoding='utf-8', newline='\n') as f:json.dump(value,f,ensure_ascii=False,indent=2)
            print(json.dumps({'status':'UNREVIEWED_SEMANTIC_TEMPLATE','path':str(dest)},ensure_ascii=False));return 0
        from staged_workflow import evaluate, preflight_many
        from review_reuse import session
        with session(True) as memo:
            status=preflight_many(state,root,a.panels) if a.batch_preflight else evaluate(state,root)
            reports=status.get('reports',[])
            ready=[r['panel_id'] for r in reports if r['status']=='PASS']
            value={'status':'READY' if reports and len(ready)==len(reports) else 'PARTIAL_READY' if ready else status['status'],'scope':'READ_ONLY_ACTUAL_GATES','file_reuse_statistics':status.get('file_reuse_statistics',{}),'next_action':status['next_action'],'ready_panel_ids':ready,'reports':reports,'toolchain_release':state.get('execution_contract'),'qa_reuse_statistics':{'hits':memo['hits'],'validated':memo['misses']},'user_approval':'NOT_GRANTED'}
            from rule_memory import routing_statistics
            value['rule_routing_reuse_statistics']=routing_statistics()
        print(json.dumps(value,ensure_ascii=False));return 0 if ready or status['status']=='PASS' else 1
    except (OSError,ValueError,TypeError,KeyError,StopIteration) as exc:print(json.dumps({'status':'HOLD','errors':[str(exc)]},ensure_ascii=False));return 1

if __name__=='__main__':
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
