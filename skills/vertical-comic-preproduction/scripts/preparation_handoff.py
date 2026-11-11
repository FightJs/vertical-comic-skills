"""Assemble adopted preparation states through the original portable handoff gates.

Copies only an explicit transitive file read set. Never rewrites approved business
bytes, grants approval, resets history, or invokes an image service.
"""
import copy
import json
from pathlib import Path
import shutil
import tempfile

from input_dependencies import file_hash, fingerprint
from panel_source import read
from platform_io import atomic_json, portable_relative, skill_entry_key
import handoff_zip as handoff
from handoff_scope import EPISODE_POLICY, EPISODE_WINDOW
from handoff_delivery import TEMPLATE, DIRECT, copy_assembly_plan, formal_context_errors, closure


class MissingInput(ValueError):
    def __init__(self, key, reason):
        super().__init__(reason);self.key=key


def _missing(rows):
    return {'status':'MISSING_INPUTS','package_root':None,'index':None,
        'missing_keys':list(dict.fromkeys(r['key'] for r in rows)),'missing':rows,
        'image_calls':0,'approval_created':False,'dispatch_authorized':False}


def _resolve(base, ref):
    if not isinstance(ref,dict) or not isinstance(ref.get('path'),str) or not ref.get('sha256'):
        raise ValueError('Missing exact path/SHA256 reference')
    raw=Path(ref['path']);path=raw if raw.is_absolute() else Path(base)/raw
    if path.is_symlink() or not path.is_file() or file_hash(path)!=ref['sha256']:
        raise ValueError('Referenced file missing or changed: '+str(path))
    return path.resolve()


class _Closure:
    def __init__(self, run_root, stage):
        self.run_root=run_root;self.stage=stage;self.selected={};self.dependencies={};self.visiting=set();self.tool_inventories=set();self.parsed=set()

    def target(self, source):
        source=Path(source).resolve()
        if not source.is_relative_to(self.run_root):
            raise ValueError('Portable execution dependency lies outside run_root: '+str(source))
        return 'template/'+source.relative_to(self.run_root).as_posix()

    def add(self, source, destination=None, *, base=None, expected=None, parse=True, historical=False):
        source=Path(source)
        if source.is_symlink():raise ValueError('Symbolic links are not portable evidence: '+str(source))
        source=source.resolve();destination=destination or self.target(source);portable_relative(destination)
        if not source.is_file():raise ValueError('Missing dependency: '+str(source))
        sha=file_hash(source)
        if expected is not None and sha!=expected:raise ValueError('Dependency bytes changed: '+str(source))
        if destination in self.selected:
            if self.selected[destination]['sha256']!=sha:raise ValueError('Assembly destination content conflict: '+destination)
            if parse and source.suffix.lower()=='.json' and (destination,historical) not in self.parsed:
                self.parsed.add((destination,historical))
                self._walk(read(source),Path(base or source.parent),source,destination,historical=historical)
            return {'path':destination,'sha256':sha}
        output=self.stage/destination;output.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,output)
        if file_hash(output)!=sha or file_hash(source)!=sha:raise ValueError('Dependency changed during copy: '+str(source))
        self.selected[destination]={'source':source,'sha256':sha,'bytes':output.stat().st_size}
        self.dependencies[destination]=[]
        if parse and source.suffix.lower()=='.json':
            self.parsed.add((destination,historical))
            value=read(source);self._walk(value,Path(base or source.parent),source,destination,historical=historical)
        return {'path':destination,'sha256':sha}

    def _walk(self, value, base, document, owner, *, historical=False):
        if isinstance(value,list):
            for child in value:self._walk(child,base,document,owner,historical=historical)
            return
        if not isinstance(value,dict):return
        # Runtime roots are relocated by the established bind operation. Their
        # exact files are copied separately from the verified runtime inventory.
        if isinstance(value.get('path'),str) and isinstance(value.get('sha256'),str):
            raw=Path(value['path']);candidates=[raw] if raw.is_absolute() else [document.parent/raw,base/raw]
            path=next((p for p in candidates if p.is_file() and file_hash(p)==value['sha256']),None)
            if path is None:raise ValueError('Unresolved exact reference in '+str(document)+': '+value['path'])
            if raw.is_absolute() and not historical:
                raise ValueError('Approved execution reference in '+str(document)+' requires existing portable binding: '+value['path'])
            if not path.resolve().is_relative_to(self.run_root):
                if not historical:raise ValueError('External dependency needs existing portable binding: '+str(path))
                destination='traceability/external/'+value['sha256']+path.suffix
            else:destination=self.target(path)
            ref=self.add(path,destination,base=base,expected=value['sha256'],historical=historical)
            self.dependencies[owner].append(ref['path'])
        for path_key,hash_key in (('source_file','source_sha256'),('event_path','sha256')):
            if isinstance(value.get(path_key),str) and isinstance(value.get(hash_key),str):
                self._walk({'path':value[path_key],'sha256':value[hash_key]},base,document,owner,historical=historical)
        if value.get('policy')=='scoped_rule_exception_v1':
            from rule_exception import evidence_base
            if value.get('evidence_root_mode')!='exception_relative_v1' and not historical:
                raise ValueError('Approved rule exception needs its existing portable evidence binding')
            self._walk(value.get('artifacts',[]),evidence_base(value,document),document,owner,historical=historical)
            return
        if value.get('policy')=='local_execution_context_v1':
            directory=Path(value['clock_directory'])
            for name in ('runtime-clock.json','clock-policy-amendment.json','clock-session.json'):
                path=directory/name
                if path.is_file():
                    destination=self.target(path) if path.resolve().is_relative_to(self.run_root) else 'traceability/clock/'+file_hash(path)+'-'+name
                    ref=self.add(path,destination,base=directory,parse=False);self.dependencies[owner].append(ref['path'])
        if not historical and isinstance(value.get('panel_id'),str) and isinstance(value.get('prompt'),str) and isinstance(value.get('reference_images'),list):
            details=value.get('panel_json_file',value['panel_id']+'/提示词.json')
            raw=Path(details)
            if raw.is_absolute():raise ValueError('Panel JSON path requires portable binding: '+details)
            path=next((p for p in [base/raw,document.parent/raw] if p.is_file()),None)
            if path is None:raise ValueError('Required existing panel_json_file missing: '+details)
            ref=self.add(path,base=base);self.dependencies[owner].append(ref['path'])
        if value.get('policy')=='approved_shot_context_v1':
            from continuity_context import source_base
            for source in value.get('sources',[]):
                if source.get('root_mode')!='context_relative_v1':
                    raise ValueError('Approved continuity context requires portable_context before approval')
                self._walk(source,source_base(source,document.parent),document,owner,historical=historical)
            for key,child in value.items():
                if key!='sources':self._walk(child,base,document,owner,historical=historical)
            return
        from input_semantics import POLICIES as SEMANTIC_POLICIES
        retained_input=(value.get('input_semantics_policy') in SEMANTIC_POLICIES
            and all(isinstance(value.get(k),str) and value[k] for k in ('book_id','episode_id','panel_id','shot_signature','visual_basis_sha256','prompt'))
            and isinstance(value.get('references'),list))
        if retained_input and 'tool_files' in value:
            if fingerprint(value['tool_files']) not in self.tool_inventories:
                raise ValueError('Retained semantic input tool_files do not match a verified frozen runtime inventory')
        for key,child in value.items():
            if key=='tool_files' and retained_input:continue
            if key in {'toolchain','runtime_snapshot','memory_source'}:continue
            if key in {'prompt_file','negative_prompt_file','panel_json_file'} and isinstance(child,str):
                raw=Path(child)
                if raw.is_absolute() and not historical:raise ValueError('Prompt path is not portable: '+child)
                candidates=[raw] if raw.is_absolute() else [base/raw,document.parent/raw]
                path=next((p for p in candidates if p.is_file()),None)
                if path is None:raise ValueError('Prompt file missing: '+child)
                destination=None if path.resolve().is_relative_to(self.run_root) else 'traceability/external/'+file_hash(path)+path.suffix
                ref=self.add(path,destination,base=base,parse=False,historical=historical);self.dependencies[owner].append(ref['path'])
            elif key not in {'path','sha256'}:
                self._walk(child,base,document,owner,historical=historical or key in {'preparation_scope_history','runtime_import','_preparation_scope','reused_from','runtime_execution_context'})

    def verify(self):
        for item in self.selected.values():
            if file_hash(item['source'])!=item['sha256']:raise ValueError('Source changed before assembly commit: '+str(item['source']))


def _runtime(state, config, collector, episode):
    from runtime_snapshot import create,verify
    from execution_contract import toolchain
    supplied=config.get('runtime_manifest') or state.get('runtime_snapshot')
    if supplied:
        path=_resolve(collector.run_root,supplied)
        frozen=verify({'path':str(path),'sha256':file_hash(path)})
        name='runtime/'+file_hash(path)[:16]
        root=path.parent
        for row in frozen['data']['files']:
            collector.add(root/row['path'],name+'/'+row['path'],expected=row['sha256'],parse=False)
        result=collector.add(path,name+'/manifest.json',parse=False)
    else:
        old=state.get('toolchain') or {};scripts=Path(old.get('root',''))
        if not scripts.is_absolute() or not scripts.is_dir():raise MissingInput(episode+'.runtime_manifest','No verified runtime snapshot or existing toolchain root')
        name='runtime/current';destination=collector.stage/name
        ref=create(destination,skills_root=scripts.parents[1],memory_source=state.get('memory_source'))
        frozen=verify(ref);result={'path':name+'/manifest.json','sha256':file_hash(destination/'manifest.json')}
    current=toolchain(frozen['scripts']);old=state.get('toolchain') or {}
    keys=('policy','release','files')
    if any(old.get(k)!=current.get(k) for k in keys) or {skill_entry_key(r['path']):r['sha256'] for r in old.get('skill_entries',[])}!={skill_entry_key(r['path']):r['sha256'] for r in current.get('skill_entries',[])}:
        raise MissingInput(episode+'.runtime_manifest','Adopted state toolchain bytes differ from the supplied frozen runtime')
    old_memory={k:v for k,v in (state.get('memory_source') or {}).items() if k not in {'root','runtime_snapshot'}}
    new_memory={k:v for k,v in (frozen['memory_source'] or {}).items() if k not in {'root','runtime_snapshot'}}
    if old_memory!=new_memory:raise MissingInput(episode+'.runtime_manifest','Frozen rule content does not match adopted state')
    collector.tool_inventories.add(fingerprint(current['files']))
    return result


def _episode_settings(config, episode):
    return {**config,**config.get('episodes',{}).get(episode,{})}


def _history(state, state_path, source_ids, settings):
    """A deterministic ledger reconciliation is not a human or image observation."""
    from task_context import ORIGIN_FILE,UNSENT,state_errors
    eid=state['episode_id'];root=state_path.parent.parent;context=state.get('task_context')
    explicit=settings.get('panel_handoff',{})
    if eid in explicit:explicit=explicit[eid]
    if context is not None:
        issues=state_errors(state,root)
        if issues:raise MissingInput(eid+'.task_origin',';'.join(issues))
    elif not explicit:
        raise MissingInput(eid+'.task_origin','Zero calls require the original task origin or explicit original history reconciliation')
    records={r['panel_id']:r for r in state['panels']};result={}
    for pid in source_ids:
        record=records[pid];retained=record.get('attempt_history',[])
        if not isinstance(retained,list):raise MissingInput(eid+'.'+pid+'.history','Original attempt history is invalid')
        calls=[r for r in [*retained,record] if r.get('status') not in UNSENT or any(r.get(k) for k in ('call_evidence','output','submitted_at'))]
        dispatch=[r for r in state.get('dispatch_ledger',[]) if r.get('panel_id')==pid and r.get('status') in {'IN_FLIGHT','RESULT_UNKNOWN','COMPLETED'}]
        if pid in explicit:
            result[pid]=copy.deepcopy(explicit[pid]);continue
        if calls or dispatch:
            raise MissingInput(eid+'.'+pid+'.history','Existing calls/outputs require the retained original attempt reconciliation and explicit reuse/design decisions; PENDING is not zero-call evidence')
        if context is None:raise MissingInput(eid+'.'+pid+'.history','No original task evidence establishes zero body submissions')
        result[pid]={'classification':'READY','history':{'status':'NEVER_SUBMITTED','task_id':context['task_id'],
            'reviewer':'preparation_handoff.py: technical ledger reconciliation',
            'conclusion':'Original task origin, exact persisted panel/attempt records and dispatch ledger contain zero submitted body calls for this task.',
            'attempts':[],'auto_corrections_used':0,'remaining_auto_corrections':1}}
    return result


def _assembled(destination, config, *, reused=False, count=None):
    return {'status':'ASSEMBLED_CANDIDATE_NOT_APPROVED','path':str(destination),'package_root':str(destination),
        'index':{'path':str(destination/handoff.INDEX),'sha256':file_hash(destination/handoff.INDEX)},
        'files':count,'assembly_reused':reused,'missing_keys':[],'missing':[],
        'authorization_requirements':[] if config.get('export_authorization') else ['export_authorization'],
        'dispatch_authorized':False,'image_calls':0,'approval_created':False}


def _request_digest(run_root, states, config):
    return fingerprint({'run_root':str(run_root),'states':[str(Path(p).resolve()) for p in states],
        'config':{k:config.get(k) for k in ('operation_id','package_id','runtime_manifest','dependency_plan','panel_handoff','episodes')}})


def _replay(destination, run_root, states, config):
    """A saved exact operation can recover without re-reading unavailable sources."""
    try:
        receipt=read(destination/'装配回执.json')
        if receipt.get('request_digest')!=_request_digest(run_root,states,config):raise ValueError('Existing candidate belongs to a different exact assembly operation')
        for name,sha in receipt['state_inputs']:
            path=Path(name)
            if path.exists() and (not path.is_file() or file_hash(path)!=sha):raise ValueError('Adopted state changed since the saved assembly: '+name)
        actual=[r for r in handoff.files(destination) if r['path']!='装配回执.json']
        if actual!=receipt['files']:raise ValueError('Existing assembly bytes or membership changed')
        index=handoff.audit_index(destination)
        issues=closure(destination,index,verify_runtime=False)+formal_context_errors(destination,index)
        if issues:raise ValueError(';'.join(issues))
        return _assembled(destination,config,reused=True,count=len(actual)+1)
    except (OSError,ValueError,TypeError,KeyError) as exc:
        return _missing([{'key':'assembly_destination','reason':str(exc)}])


def build_package(run_root, states, config):
    """Return an actual v2 candidate root, or exact missing facts; never release it.

    states are absolute persisted state paths. Config accepts assembly_destination,
    package_id, runtime_manifest, dependency_plan and per-episode panel_handoff.
    Existing approved relative bytes must already have their portable binding.
    """
    run_root=Path(run_root).resolve();config=copy.deepcopy(config or {});missing=[];loaded=[]
    if not isinstance(states,(list,tuple)) or not states:return _missing([{'key':'states','reason':'Need persisted adopted episode state paths'}])
    destination=Path(config.get('assembly_destination',run_root/'.preparation-handoff'/'package')).resolve()
    if destination.exists():return _replay(destination,run_root,states,config)
    for item in states:
        try:
            path=Path(item).resolve();state=read(path);eid=state['episode_id'];root=path.parent.parent
            if path.parent.parent==path.parent or not path.is_relative_to(run_root):raise ValueError('State must be run_root-contained and live in episode/audit/state.json')
            settings=_episode_settings(config,eid)
            for key in ('book_id','source_snapshot','source_script','visual_basis','shot_manifest','semantic_audit','approval_index','toolchain'):
                if not state.get(key):missing.append({'key':eid+'.'+key,'reason':'Missing original adopted state field'})
            if any(r['key'].startswith(eid+'.') for r in missing):continue
            source=read(_resolve(root,state['source_snapshot']));ids=source['panel_ids']
            if [r['panel_id'] for r in state['panels']]!=ids:raise ValueError('State panel rows differ from full canonical source')
            if not state.get('generation_packages',{}).get('EPISODE'):
                missing.append({'key':eid+'.generation_packages.EPISODE','reason':'Missing adopted final generation packages'});continue
            history=_history(state,path,ids,settings)
            loaded.append((path,state,ids,history,settings))
        except MissingInput as exc:missing.append({'key':exc.key,'reason':str(exc)})
        except (OSError,ValueError,TypeError,KeyError) as exc:missing.append({'key':str(item)+'.inputs','reason':str(exc)})
    if missing:return _missing(missing)
    books={s['book_id'] for _,s,_,_,_ in loaded};contexts=[s.get('task_context') for _,s,_,_,_ in loaded]
    if len(books)!=1 or any(c!=contexts[0] for c in contexts):return _missing([{'key':'task_context','reason':'All supplied episode states must preserve one exact book/task context'}])
    book=next(iter(books));package_id=config.get('package_id') or 'PREPARATION_'+fingerprint([[s['episode_id'],file_hash(p)] for p,s,_,_,_ in loaded])[:16]
    destination=Path(config.get('assembly_destination',run_root/'.preparation-handoff'/'package')).resolve()
    identity=fingerprint({'states':[[str(p),file_hash(p)] for p,_,_,_,_ in loaded],
        'config':{k:config.get(k) for k in ('package_id','runtime_manifest','dependency_plan','panel_handoff','episodes')}})
    try:
        with tempfile.TemporaryDirectory(prefix='comic-handoff-assembly-') as temporary:
            stage=Path(temporary)/'package';stage.mkdir();collector=_Closure(run_root,stage);episodes=[]
            for state_path,state,ids,histories,settings in loaded:
                eid=state['episode_id'];root=state_path.parent.parent
                runtime_ref=_runtime(state,settings,collector,eid)
                state_ref=collector.add(state_path,base=root)
                source_ref=collector.add(_resolve(root,state['source_snapshot']),base=root,expected=state['source_snapshot']['sha256'])
                original_origin=root/'00_输入审计'/'任务来源.json'
                origin_ref=collector.add(original_origin,base=root) if state.get('task_context') else None
                proof={'policy':'preparation_handoff_history_v1','episode_id':eid,'task_context':state.get('task_context'),
                    'state':state_ref,'task_origin':origin_ref,'panel_ids':ids,
                    'panels':[{'panel_id':r['panel_id'],'status':r.get('status'),'attempt_history':r.get('attempt_history',[]),
                        'attempt_id':r.get('attempt_id'),'submitted_at':r.get('submitted_at'),'call_evidence':r.get('call_evidence')} for r in state['panels']],
                    'dispatch_ledger':state.get('dispatch_ledger',[]),'image_calls':0,'visual_review':'NOT_PERFORMED'}
                evidence=stage/'traceability'/eid/'history-reconciliation.json';evidence.parent.mkdir(parents=True,exist_ok=True);atomic_json(evidence,proof)
                evidence_ref={'path':evidence.relative_to(stage).as_posix(),'sha256':file_hash(evidence)}
                def promote(ref):
                    path=_resolve(root,ref);return collector.add(path,base=root,expected=ref['sha256'])
                def promote_row(value):
                    if isinstance(value,list):return [promote_row(v) for v in value]
                    if not isinstance(value,dict):return value
                    if isinstance(value.get('path'),str) and value.get('sha256'):
                        return {**value,**promote(value)}
                    return {k:promote_row(v) for k,v in value.items()}
                panels=[];shots={r['panel_id']:r for r in read(_resolve(root,state['shot_manifest']))['panels']}
                plan_ref=settings.get('dependency_plan')
                if not plan_ref:
                    for ref in state['generation_packages']['EPISODE']:
                        package=read(_resolve(root,ref))
                        if package.get('dependency_completion_plan'):plan_ref=package['dependency_completion_plan']
                for pid in ids:
                    panel={'panel_id':pid,**promote_row(histories[pid])};history=panel['history']
                    if not history.get('evidence'):history['evidence']=[state_ref,evidence_ref]+([origin_ref] if origin_ref else [])
                    dependencies=shots[pid].get('generation_dependencies',[])
                    if dependencies and panel['classification']=='READY':
                        if not plan_ref:raise MissingInput(eid+'.dependency_plan','Real prior-image dependencies require the adopted completion plan')
                        panel.update(classification='WAIT_DEPENDENCY',blockers=[{'reason':'Prior body image is not yet available: '+','.join(dependencies),'owner':'production','resolution':'Complete the approved dependency plan with actual returned prior images'}],
                            production_dependency={'kind':'prior_image','episode_id':eid,'panel_id':dependencies[0],'dependency_panel_ids':dependencies,'completion_plan':promote(plan_ref)})
                    panels.append(panel)
                relative_root=root.relative_to(run_root).as_posix()
                template_base='template' if relative_root=='.' else 'template/'+relative_root
                template=stage/'templates'/eid/'run-template.json';template.parent.mkdir(parents=True,exist_ok=True)
                atomic_json(template,{'policy':TEMPLATE,'episode_id':eid,'root':template_base,
                    'state_file':state_path.relative_to(root).as_posix(),'files':handoff.files(stage/template_base)})
                binding=stage/'templates'/eid/'path-binding-plan.md';binding.write_text('Apply handoff_delivery.bind: relocate only the verified frozen runtime, rule roots and execution clock. Preserve approved business files and attempt budgets byte-for-byte.\n',encoding='utf-8')
                episode={'episode_id':eid,'panel_ids':ids,'source_snapshot':source_ref,'production_source_snapshot':source_ref,
                    'runtime_manifest':runtime_ref,'approval_evidence':promote(state['approval_index']),
                    'path_binding_plan':{'path':binding.relative_to(stage).as_posix(),'sha256':file_hash(binding)},
                    'run_template':{'path':template.relative_to(stage).as_posix(),'sha256':file_hash(template)},'panels':panels,
                    'generation_review_packages':[promote(ref) for ref in state['generation_packages']['EPISODE']]}
                for key in ('source_script','visual_basis','shot_manifest','semantic_audit'):
                    episode[key]=promote(state[key])
                for key in ('input_semantics_policy','asset_format_policy'):
                    if state.get(key) is not None:episode[key]=state[key]
                episodes.append(episode)
            index={'policy':EPISODE_POLICY,'production_window_policy':EPISODE_WINDOW,'delivery_policy':DIRECT,
                'package_id':package_id,'book_id':book,'episodes':episodes}
            if contexts[0] is not None:index['task_context']=contexts[0]
            atomic_json(stage/handoff.INDEX,index)
            (stage/'交接说明.md').write_text('Full source-ordered preparation handoff. Original approvals, source text, executable inputs, task history and correction budgets are retained. This candidate needs the applicable original export authorization before formal delivery.\n',encoding='utf-8')
            (stage/'接包生产执行要求.md').write_text('Use comic_start.receive on the released self-contained package. The existing frozen gates and production decision routing remain authoritative. No image calls or user approvals are implied by assembly.\n',encoding='utf-8')
            issues=closure(stage,index)+formal_context_errors(stage,index)
            if issues:raise MissingInput('formal_context',';'.join(issues))
            collector.verify()
            atomic_json(stage/'装配回执.json',{'policy':'preparation_handoff_receipt_v1','input_digest':identity,'request_digest':_request_digest(run_root,states,config),'files':handoff.files(stage),
                'state_inputs':[[str(p),file_hash(p)] for p,_,_,_,_ in loaded],'approval_created':False,'image_calls':0})
            rows=handoff.files(stage)
            plan={'policy':'explicit_handoff_assembly_v1','unresolved_paths':[],
                'reviewer':'preparation_handoff.py: deterministic reference closure',
                'evidence':'Exact source hashes, retained origin/ledger reconciliation, original closure and formal-context validators; no visual observation or approval performed.',
                'required_paths':[r['path'] for r in rows],
                'dependencies':{name:sorted(set(targets)) for name,targets in collector.dependencies.items()},
                'files':[{**row,'reason':'execution','evidence':'Explicit adopted-state transitive closure or required portable handoff contract'} for row in rows]}
            copied=copy_assembly_plan(stage,destination,plan)
        return _assembled(destination,config,count=copied['files'])
    except MissingInput as exc:return _missing([{'key':exc.key,'reason':str(exc)}])
    except (OSError,ValueError,TypeError,KeyError) as exc:return _missing([{'key':'assembly_closure','reason':str(exc)}])
