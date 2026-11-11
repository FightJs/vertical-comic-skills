#!/usr/bin/env python3
"""One durable preparation owner. Native tools are work returned to the real host.

Run ``serve --run-root RV`` and exchange one JSON object per line. Every request
requires request_id/action. Child agents may atomically write *.json requests to
.preparation-host/inbox; a single watcher drains it while stdin is idle. No image
or model service is invoked here. An unmarked/frozen RV is never migrated.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import sys
import threading
import time

from input_dependencies import fingerprint,file_hash
from platform_io import atomic_json,file_lock,configure_stdio
from panel_source import read,expand
from preparation_scheduler import Scheduler,POLICY
from preparation_workspace import Workspace
from runtime_clock import require_step


def ref(path):
    path=Path(path).resolve();return {'path':str(path),'sha256':file_hash(path)}


def checked(root,value):
    from codex_reference_contract import checked_file
    raw=Path(value['path'])
    if raw.is_absolute():
        if file_hash(raw)!=value.get('sha256'):raise ValueError('FILE_HASH_CHANGED:'+str(raw))
        return raw
    return checked_file(Path(root),value)


class Host:
    def __init__(self,run_root,*,workers='all',scan_seconds=.25):
        self.root=Path(run_root).resolve();self.marker=self.root/'00_任务协调'/'preparation-host.json'
        if not self.marker.is_file() or read(self.marker).get('policy')!=POLICY:
            raise ValueError('PREPARATION_POLICY_REQUIRED: frozen runs are not migrated')
        self.descriptor=read(self.marker);self.folder=self.root/'.preparation-host';self.folder.mkdir(exist_ok=True)
        for name in ('requests','inbox','done','errors','waiting','error-history','business','episodes'): (self.folder/name).mkdir(exist_ok=True)
        self.lock=threading.RLock();self.request_lock=threading.Lock();self.wake=threading.Event();self.stop=threading.Event()
        self.scan_seconds=scan_seconds;self.futures={};self.busy=set();self.closed=False
        self.scheduler=Scheduler(self.root/'00_任务协调'/'preparation-scheduler')
        self.epoch=self.scheduler.start_owner([self.descriptor['book_id'],self.descriptor['episode_ids']])
        from panel_derivation import DerivationExecutor
        self.derivation=DerivationExecutor(workers=workers);self.derivation.__enter__()
        self.coordinator=self.derivation.resources;self.scheduler.coordinator=self.coordinator;self.assets=None
        self.native_capacities=None;self.last_health_key=None;self.last_health_check=0
        self._asset_bridge()
        self.jobs=ThreadPoolExecutor(max_workers=max(2,os.cpu_count() or 2),thread_name_prefix='preparation-local')
        self._bootstrap()
        self.thread=threading.Thread(target=self._watch,name='preparation-inbox',daemon=True);self.thread.start()

    def epoch_guard(self):
        with self.lock:
            state=self.scheduler.status();self.scheduler._owner(state,self.epoch)
        return {'owner_epoch':self.epoch,'owner_valid':True}

    def _asset_bridge(self):
        if self.assets is None:
            from preparation_assets import Assets
            self.assets=Assets(self)
        return self.assets

    def _milestone(self,action,**payload):
        value={'event_id':fingerprint([action,payload,time.time_ns()]),'action':action,'at':time.time(),'payload':payload}
        if payload.get('task_id'):value['task_id']=payload['task_id']
        path=self.folder/'milestones.jsonl'
        with file_lock(self.folder/'milestones.lock'):
            with path.open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(value,ensure_ascii=False)+'\n');stream.flush();os.fsync(stream.fileno())

    def metrics(self):
        from production_metrics import preparation_metrics
        with self.lock:events=self.scheduler.journal.read()['events']
        path=self.folder/'milestones.jsonl'
        if path.exists():events+= [json.loads(line) for line in path.read_text().splitlines() if line]
        return preparation_metrics(events)

    def _budget(self,action,preserve=False):
        return require_step(self.root,'preserve-delivery' if preserve else action,optional=False)

    def _episode_folder(self,episode):
        if episode not in self.descriptor['episode_ids']:raise ValueError('EPISODE_OUTSIDE_BATCH')
        path=self.folder/'episodes'/episode;path.mkdir(exist_ok=True);return path

    def _config_path(self,episode):return self._episode_folder(episode)/'episode.json'
    def _config(self,episode):return read(self._config_path(episode))
    def _workspace(self,episode):return Workspace(self._config(episode)['run_root'])

    def _state_path(self,episode):
        for value in self.descriptor.get('states',[]):
            path=Path(value['path'] if isinstance(value,dict) else value)
            if path.is_file() and read(path).get('episode_id')==episode:return path.resolve()
        return None

    def _task(self,task_id,kind,episode,inputs,payload=None,**extra):
        return {'task_id':task_id,'kind':kind,'scope':[self.descriptor['book_id'],episode],
            'input_digest':fingerprint(inputs),'input_refs':inputs,'payload':payload or {},'panel_count':0,**extra}

    def _source_intake(self):
        configuration=self.descriptor.get('config')
        if not configuration:return None
        config=read(configuration);source=config.get('inputs',{}).get('script_path')
        if not source:
            catalog=self.root/'脚本来源索引.json'
            return {'evidence':ref(catalog),'task_id':None} if catalog.is_file() else None
        source=Path(source).resolve();source_ref=ref(source);task_id='batch:source-parse';episode=self.descriptor['episode_ids'][0]
        task=self._task(task_id,'source_parse',episode,[source_ref],{'source':str(source),'semantic_approval':False})
        with self.lock:
            self.scheduler.register([task],epoch=self.epoch)
            status=self.scheduler.status()['tasks'][task_id]
            if status['status']=='READY':self.scheduler.claim(task_id,epoch=self.epoch)
        output=self.folder/'source-evidence.json'
        if not output.exists():
            self._budget('source-parse');metrics={}
            if source.suffix.lower() in {'.xlsx','.xlsm'}:
                from source_workbook import snapshot
                raw=snapshot(source,cache_root=self.descriptor.get('source_cache_root',self.root/'.preparation-cache'),metrics=metrics)
            elif source.suffix.lower() in {'.txt','.md','.json','.csv'}:
                raw_bytes=source.read_bytes()
                import hashlib
                if hashlib.sha256(raw_bytes).hexdigest()!=source_ref['sha256']:raise ValueError('SOURCE_CHANGED_DURING_PARSE')
                raw={'policy':'raw_text_evidence_v1','text':raw_bytes.decode('utf-8-sig'),'status':'RAW_EVIDENCE_NOT_SEMANTIC_APPROVAL'}
            else:raw={'policy':'raw_file_evidence_v1','status':'NATIVE_FORMAT_READER_NEEDED','format':source.suffix}
            if ref(source)!=source_ref:raise ValueError('SOURCE_CHANGED_DURING_PARSE')
            atomic_json(output,{'source':source_ref,'raw':raw,'metrics':metrics,'semantic_approval':False})
        self._finish_task(task_id,[ref(output)],{'status':'RAW_EVIDENCE_SAVED','semantic_approval':False})
        return {'task_id':task_id,'evidence':ref(output)}

    def _bootstrap(self):
        intake=self._source_intake()
        tasks=[]
        for episode in self.descriptor['episode_ids']:
            state=self._state_path(episode);snapshot=self._episode_folder(episode)/'bootstrap.json'
            if not snapshot.exists():atomic_json(snapshot,{'descriptor':self.descriptor,'state':read(state) if state else None})
            inputs=[ref(snapshot)]+([intake['evidence']] if intake else [])
            tasks.append(self._task(episode+':semantic','semantic_authoring',episode,inputs,
                {'action':'configure-episode','required_keys':['source_snapshot','shared','shot_header','frame_ratio_plan','scenes'],
                 'state_path':str(state) if state else None,'native_driver':'model_tool_calls_required'},
                dependencies=[intake['task_id']] if intake and intake['task_id'] else []))
        with self.lock:self.scheduler.register(tasks,epoch=self.epoch,event_id='bootstrap')

    def save_business_receipt(self,task_id,output_refs,result):
        """Domain commit first; scheduler acknowledgement can safely be replayed."""
        with self.lock:task=self.scheduler.status()['tasks'][task_id]
        path=self.folder/'business'/(fingerprint(task['operation_id'])+'.json')
        value={'policy':'preparation_business_receipt_v1','status':'COMMITTED','task_id':task_id,
            'operation_id':task['operation_id'],'output_refs':output_refs,'result':result}
        if path.exists():
            if read(path)!=value:raise ValueError('BUSINESS_OPERATION_CONTENT_CONFLICT')
        else:atomic_json(path,value)
        return ref(path)

    def _finish_task(self,task_id,outputs,result):
        receipt=self.save_business_receipt(task_id,outputs,result)
        with self.lock:
            self.scheduler.record_result(task_id,outputs,epoch=self.epoch)
            self.scheduler.commit(task_id,receipt,epoch=self.epoch)
        return receipt

    def _replay_receipts(self):
        with self.lock:
            tasks=self.scheduler.status()['tasks']
            for task in tasks.values():
                path=self.folder/'business'/(fingerprint(task['operation_id'])+'.json')
                if task['status']!='COMMITTED' and path.is_file():
                    receipt=read(path)
                    if receipt['task_id']!=task['task_id']:raise ValueError('BUSINESS_TASK_MISMATCH')
                    self.scheduler.record_result(task['task_id'],receipt['output_refs'],epoch=self.epoch)
                    self.scheduler.commit(task['task_id'],ref(path),epoch=self.epoch)

    def handle(self,request):
        """Stable request receipts also cover lost stdout responses."""
        try:
            if not isinstance(request,dict) or not isinstance(request.get('request_id'),str) or not request['request_id']:
                raise ValueError('REQUEST_ID_REQUIRED')
            path=self.folder/'requests'/(fingerprint(request['request_id'])+'.json')
            with self.request_lock:
                if path.exists():
                    old=read(path)
                    if old['request']!=request:raise ValueError('REQUEST_CONTENT_CONFLICT')
                    if request.get('action')=='asset-invoke-guard' and old['response'].get('invoke_allowed'):
                        return {'request_id':request['request_id'],'status':'ASSET_INVOKE_OUTCOME_UNKNOWN','invoke_allowed':False,
                            'saved_response':ref(path),'dispatch_authorized':False,'image_calls':0}
                    return copy.deepcopy(old['response'])
                try:response=self._action(request)
                except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
                    response={'status':'HOLD','errors':[str(exc)],'dispatch_authorized':False,'image_calls':0}
                response={'request_id':request['request_id'],**response}
                atomic_json(path,{'request':request,'response':response})
                return response
        except (OSError,ValueError,KeyError,TypeError) as exc:
            return {'request_id':request.get('request_id') if isinstance(request,dict) else None,
                'status':'HOLD','errors':[str(exc)],'dispatch_authorized':False,'image_calls':0}

    def _action(self,r):
        action=r['action']
        if action=='status':return self.status(details=r.get('details',False),after_revision=r.get('after_revision'))
        if action=='metrics':return {'status':'OBSERVED','metrics':self.metrics()}
        if action in {'register-assets','asset-prepare-invoke','asset-invoke-guard','asset-capture','asset-register','asset-recover','submit-asset-observations'}:
            result=self._asset_bridge().handle(action,r);self.wake.set();return result
        if action=='plan':
            self._replay_receipts()
            if 'capacities' in r:self.native_capacities=copy.deepcopy(r['capacities'])
            self._observe_health(force=True)
            with self.lock:
                result=self.scheduler.plan(self.native_capacities or {'model':0})
            basis_ready={}
            for task in result['ready']:
                if task['kind']=='shot_fragment' and task['scope'][1] not in basis_ready:basis_ready[task['scope'][1]]=self._basis_ready(task['scope'][1])
            result['ready']=[task for task in result['ready'] if task['kind']!='shot_fragment' or basis_ready[task['scope'][1]]]
            if self.assets is not None:
                result['ready']=[task for task in result['ready'] if not (task['kind']=='shot_fragment' and set(task['payload']['panel_ids'])&set(self.assets.blocked_panels(task['scope'][1])))]
            for task in result['ready']:self._milestone('dispatchable',task_id=task['task_id'],lane=task['lane'])
            return {**result,'host_adapter_status':'OBSERVED' if self.native_capacities is not None else 'HOST_NEEDED'}
        if action=='claim':
            self._budget('preparation-claim')
            with self.lock:task=self.scheduler.status()['tasks'][r['task_id']]
            if task['kind']=='shot_fragment' and not self._basis_ready(task['scope'][1]):raise ValueError('BASIS_REVIEW_REQUIRED')
            if self.assets is not None and task['kind']=='shot_fragment' and set(task['payload']['panel_ids'])&set(self.assets.blocked_panels(task['scope'][1])):
                raise ValueError('ASSET_REVIEW_REQUIRED')
            with self.lock:return self.scheduler.claim(r['task_id'],epoch=self.epoch)
        if action=='attach-host':
            self._budget('preparation-attach-host')
            with self.lock:return self.scheduler.attach_host(r['task_id'],r['host_id'],epoch=self.epoch,
                operation_id=r.get('operation_id'),evidence=r.get('evidence'))
        if action=='configure-episode':return self.configure(r)
        if action in {'submit-fragments','submit-observations','submit-basis-observation'}:
            # Preserve incoming child work before attempting technical admission.
            payload={k:v for k,v in r.items() if k!='request_id'}
            operation=r.get('operation_id') or r.get('fragment',{}).get('operation_id')
            if not operation:raise ValueError('OPERATION_ID_REQUIRED')
            payload['operation_id']=operation
            path=self.folder/'inbox'/(fingerprint(operation)+'.json')
            for existing in (path,self.folder/'done'/path.name,self.folder/'errors'/path.name,self.folder/'waiting'/path.name):
                if existing.exists():
                    saved=read(existing);saved=saved.get('request',saved)
                    if saved!=payload:raise ValueError('INBOX_OPERATION_CONTENT_CONFLICT')
                    return {'status':'QUEUED' if existing==path else 'ALREADY_PROCESSED','inbox':ref(existing)}
            atomic_json(path,payload);self._milestone('fragment_submitted',operation_id=operation,episode_id=r['episode_id']);self.wake.set();return {'status':'QUEUED','inbox':ref(path)}
        if action=='reconcile':
            self._replay_receipts()
            retried=self._retry_local_errors() if r.get('retry_errors',True) else []
            with self.lock:result=self.scheduler.reconcile(r.get('observations'),epoch=self.epoch,health=r.get('health'))
            self.wake.set();return {'status':'RECONCILED','scheduler':result,'retried_local_operations':retried}
        if action=='seal':return self.seal(r)
        if action=='publish':return self.publish(r)
        raise ValueError('UNKNOWN_PREPARATION_ACTION:'+str(action))

    def _retry_local_errors(self):
        retried=[]
        for path in sorted((self.folder/'errors').glob('*.json')):
            error=read(path);request=error.get('request') or {}
            if request.get('action') not in {'submit-fragments','submit-observations','submit-basis-observation'}:continue
            if error.get('exception_type') not in {'OSError','IOError','FileNotFoundError','PermissionError'} and not str(error.get('error','')).startswith(('RUNTIME_CLOCK_','RUNTIME_DELIVERY_')):continue
            atomic_json(self.folder/'inbox'/path.name,request)
            path.replace(self.folder/'error-history'/(path.stem+'-'+str(time.time_ns())+'.json'))
            retried.append(request['operation_id'])
        self.wake.set();return retried

    @staticmethod
    def _ratio_header(header,plan):
        from frame_ratio_plan import POLICY as RATIO
        header=copy.deepcopy(header);metadata={'frame_ratio_policy':RATIO,'frame_ratio_plan':plan}
        if '$shared' in header:
            header.setdefault('$overrides',{}).update(metadata)
        else:header.update(metadata)
        return header

    def configure(self,r):
        self._budget('configure-episode');episode=r['episode_id'];path=self._config_path(episode)
        required=['source_snapshot','shared','shot_header','frame_ratio_plan','scenes']
        missing=[k for k in required if k not in r]
        if missing:raise ValueError('CONFIGURATION_REQUIRED:'+','.join(missing))
        state_path=Path(r['state_path']).resolve() if r.get('state_path') else self._state_path(episode)
        allowed_paths={Path(value['path'] if isinstance(value,dict) else value).resolve() for value in self.descriptor.get('states',[])}
        if state_path and (state_path not in allowed_paths or not state_path.is_relative_to(self.root)):
            raise ValueError('STATE_PATH_OUTSIDE_DESCRIPTOR')
        if state_path and read(state_path).get('preparation_scheduler_policy')!=POLICY:
            raise ValueError('FROZEN_STATE_NOT_PREPARATION_SCHEDULER')
        root=state_path.parent.parent if state_path else self.root
        source=read(checked(root,r['source_snapshot']));ids=source['panel_ids']
        scenes=r['scenes'];scene_ids=[p for scene in scenes for p in scene['panel_ids']]
        if not scenes or scene_ids!=ids:raise ValueError('SCENES_REQUIRE_EXACT_SOURCE_ORDER')
        data={k:copy.deepcopy(r[k]) for k in required};data['shot_header']=self._ratio_header(data['shot_header'],data['frame_ratio_plan']);data.update(episode_id=episode,run_root=str(root),state_path=str(state_path) if state_path else None,
            state_updates=copy.deepcopy(r.get('state_updates',{})),source_script=r.get('source_script'),authority=r.get('authority'),reviewer=r.get('reviewer'),dependency_plan=r.get('dependency_plan'),seal=r.get('seal',{}))
        if path.exists():
            old=read(path)
            if any(old.get(k)!=v for k,v in data.items()):raise ValueError('EPISODE_CONFIGURATION_CONFLICT')
        if state_path and not (r.get('state_updates',{}).get('visual_basis') or read(state_path).get('visual_basis')):
            raise ValueError('CONFIGURATION_REQUIRED:visual_basis')
        if not path.exists():
            # Workspace validates whole-episode source and legal ratio plan, not a model declaration.
            workspace=Workspace(root);workspace.initialize(data['source_snapshot'],self.descriptor['book_id'],episode,
                data['shared'],data['shot_header'],frame_ratio_plan=data['frame_ratio_plan'])
            if state_path:
                allowed={'visual_basis','input_semantics_policy','preparation_gate_policy','frame_ratio_policy','frame_ratio_plan',
                    'identity_registry','identity_policy','memory_source','visual_evidence_policy','style_policy','style_contract',
                    'continuity_policy','input_priority_policy','asset_format_policy'}
                if set(r.get('state_updates',{}))-allowed:raise ValueError('CONFIGURE_STATE_FIELD_NOT_ALLOWED')
                from preparation_pipeline import bootstrap_state
                bootstrap_state(data,r.get('source_script'),r.get('state_updates'))
            immutable=self._episode_folder(episode)/'configuration-input.json';atomic_json(immutable,data)
            data.update(panels={},operations={},risk_queue=[],derivations=[]);atomic_json(path,data)
        immutable=self._episode_folder(episode)/'configuration-input.json'
        basis_task=self._ensure_basis_task(episode)
        tasks=[]
        for index,scene in enumerate(scenes):
            size=3 if scene.get('complex') else 6
            # Actual completed fragment durations may tune subsequent configured scenes.
            if scene.get('measured_seconds_per_panel') is not None:
                rate=scene['measured_seconds_per_panel']
                if not isinstance(rate,(int,float)) or rate<=0:raise ValueError('INVALID_MEASURED_PANEL_DURATION')
                size=max(1,int(180/rate))
            for offset in range(0,len(scene['panel_ids']),size):
                selected=scene['panel_ids'][offset:offset+size]
                tasks.append(self._task(episode+':shot:'+str(index)+':'+str(offset),'shot_fragment',episode,[ref(immutable)],
                    {'episode_id':episode,'scene_id':scene.get('scene_id',str(index)),'panel_ids':selected,
                     'target_seconds':180,'base_revision':0,'shared_version':0,'row_versions':{p:0 for p in selected},
                     'consumed_rows':{},'submission_action':'submit-fragments','inbox':str(self.folder/'inbox')},panel_count=len(selected),dependencies=([basis_task] if basis_task else [])+(self.assets.dependencies(episode,selected) if self.assets else [])))
        with self.lock:
            semantic=self.scheduler.status()['tasks'][episode+':semantic']
            if semantic['status']=='READY':self.scheduler.claim(semantic['task_id'],epoch=self.epoch)
            self._finish_task(semantic['task_id'],[ref(immutable)],{'status':'CONFIGURED','episode_id':episode})
            self.scheduler.register(tasks,epoch=self.epoch)
        return {'status':'CONFIGURED','episode_id':episode,'fragment_tasks':len(tasks),'dispatch_authorized':False}

    def _basis_inputs(self,episode):
        from input_dependencies import references
        config=self._config(episode)
        if not config.get('state_path'):return None
        raw=Path(config['state_path']).read_bytes()
        import hashlib
        state=json.loads(raw.decode('utf-8-sig'));state_sha=hashlib.sha256(raw).hexdigest();root=Path(config['run_root'])
        if not state.get('visual_basis'):return None
        basis=read(checked(root,state['visual_basis']));source=read(checked(root,state['source_snapshot']))
        required=[{'path':r['path'],'sha256':r['sha256']} for r in references([basis])]
        for item in required:checked(root,item)
        return config,state,root,source,basis,required,state_sha

    def _basis_ready(self,episode):
        from panel_readiness import approval_errors_for
        from authority_updates import authority_context
        from codex_reference_contract import file_session
        values=self._basis_inputs(episode)
        if values is None:return not bool(self._config(episode).get('state_path'))
        config,state,root,source,basis,required,state_sha=values
        with file_session(),authority_context(state,root):
            return not approval_errors_for(state,root,'visual_basis',
                [state['source_script'],state['source_snapshot'],state['visual_basis']],source['panel_ids'],state.get('gates',{}).get('visual_basis'))

    def _ensure_basis_task(self,episode):
        from panel_readiness import approval_errors_for
        from authority_updates import authority_context
        from codex_reference_contract import file_session
        values=self._basis_inputs(episode)
        if values is None:return None
        config,state,root,source,basis,required,state_sha=values
        artifacts=[state['source_script'],state['source_snapshot'],state['visual_basis']]
        with file_session(),authority_context(state,root):
            errors=approval_errors_for(state,root,'visual_basis',artifacts,source['panel_ids'],state.get('gates',{}).get('visual_basis'))
        if not errors:return None
        facts={'policy':'visual_basis_observation_requirements_v1','book_id':state['book_id'],'episode_id':episode,
            'panel_ids':source['panel_ids'],'source_script':state['source_script'],'source_snapshot':state['source_snapshot'],
            'visual_basis':state['visual_basis'],'checked_references':required,'review_performed':False}
        needed=self._episode_folder(episode)/('basis-needed-'+fingerprint(facts)+'.json')
        if not needed.exists():atomic_json(needed,facts)
        task_id=episode+':basis:'+fingerprint(facts)
        with self.lock:self.scheduler.register([self._task(task_id,'basis_observation',episode,[ref(needed)],
            {'episode_id':episode,'panel_ids':source['panel_ids'],'submission_action':'submit-basis-observation',
             'requirements':ref(needed),'native_observation_required':True})],epoch=self.epoch)
        return task_id

    def _basis_observation(self,r):
        from authority_updates import authority_context,update_approvals,revocation_errors
        from codex_reference_contract import file_session,checked_file
        from review_policy import proposal,delegated_decisions,decision_errors
        from preparation_pipeline import reference
        episode=r['episode_id'];values=self._basis_inputs(episode)
        if values is None:raise ValueError('BASIS_INPUTS_REQUIRED')
        config,state,root,source,basis,required,state_sha=values;observation=copy.deepcopy(r['observation'])
        folder=root/'.preparation-pipeline'/'basis-reviews'/fingerprint(r['operation_id']);folder.mkdir(parents=True,exist_ok=True)
        original=folder/'observation.json'
        if original.exists() and read(original)!=observation:raise ValueError('BASIS_OPERATION_CONTENT_CONFLICT')
        if not original.exists():atomic_json(original,observation)
        if (observation.get('policy')!='visual_basis_observation_v1' or observation.get('status')!='PASS'
            or observation.get('source_kind')!='observed_visual_basis_review'
            or any(not isinstance(observation.get(k),str) or not observation[k].strip() for k in ('source_locator','reviewer','observed_at','evidence'))):
            raise ValueError('ACTUAL_BASIS_OBSERVATION_REQUIRED')
        expected={'book_id':state['book_id'],'episode_id':episode,'panel_ids':source['panel_ids'],
            'source_script':state['source_script'],'source_snapshot':state['source_snapshot'],
            'visual_basis':state['visual_basis'],'checked_references':required}
        if any(observation.get(k)!=value for k,value in expected.items()):raise ValueError('BASIS_OBSERVATION_SCOPE_OR_BYTES_CHANGED')
        if not config.get('authority'):raise ValueError('BASIS_EXISTING_VISUAL_AUTHORITY_REQUIRED')
        result_path=folder/'result.json';committed_state_sha=state_sha
        if result_path.exists():
            saved=read(result_path)
            # The receipt proves the prior adoption; do not manufacture a new
            # observation or repeat authority revision writes after a crash.
            if saved['observation']!=reference(original,root):raise ValueError('BASIS_OPERATION_CONTENT_CONFLICT')
            with file_session(),authority_context(state,root):
                saved_proof=read(checked_file(root,saved['decision']))
                errors=decision_errors(saved_proof,root,state['book_id'],episode)+revocation_errors(saved_proof,state['book_id'],episode)
                if errors:raise ValueError('BASIS_AUTHORITY_HOLD:'+';'.join(errors))
            outcome=saved
        else:
            artifacts=[state['source_script'],state['source_snapshot'],state['visual_basis'],reference(original,root)]
            review=proposal(state['book_id'],episode,[{'item_id':'A','phase':'visual_basis','panel_ids':source['panel_ids'],
                'artifacts':artifacts,'summary':'Adopt the actual observed source assets and current visual basis'}],root)
            with file_session(),authority_context(state,root):
                proof=delegated_decisions(review,['A'],config['authority'],observation['reviewer'],
                    observation['evidence']+'; '+observation['source_locator']+'; observed_at='+observation['observed_at'],root)[0]
                revoked=revocation_errors(proof,state['book_id'],episode)
                if revoked:raise ValueError('BASIS_AUTHORITY_HOLD:'+';'.join(revoked))
            proof_path=folder/'decision.json'
            if proof_path.exists() and read(proof_path)!=proof:raise ValueError('BASIS_DECISION_CONTENT_CONFLICT')
            if not proof_path.exists():atomic_json(proof_path,proof)
            proof_ref=reference(proof_path,root)
            if file_hash(config['state_path'])!=state_sha:raise ValueError('STATE_CHANGED:BASIS_OBSERVATION_READSET')
            current=state;indexed=False
            if current.get('approval_index'):
                for entry in read(checked_file(root,current['approval_index']))['entries']:
                    if entry['phase']=='visual_basis' and read(checked_file(root,entry['approval']))==proof:indexed=True;break
            if not indexed:
                adopted=update_approvals(config['state_path'],state_sha,
                    register=[{'phase':'visual_basis','panel_ids':source['panel_ids'],'approval':proof_ref}])
                committed_state_sha=adopted['state_sha256']
            outcome={'status':'VISUAL_BASIS_ADOPTED','episode_id':episode,'panel_ids':source['panel_ids'],
                'observation':reference(original,root),'decision':proof_ref,'review_performed':True,
                'image_calls':0,'dispatch_authorized':False}
            atomic_json(result_path,outcome)
        if file_hash(config['state_path'])!=committed_state_sha:raise ValueError('STATE_CHANGED:BASIS_AUTHORITY_READSET')
        latest=read(config['state_path'])
        if any(latest.get(k)!=state.get(k) for k in ('book_id','episode_id','source_script','source_snapshot','visual_basis')):
            raise ValueError('STATE_CHANGED:BASIS_OBSERVATION_BINDING')
        # Close the exact native A work even if acknowledgement was interrupted.
        with self.lock:tasks=self.scheduler.status()['tasks']
        for task in tasks.values():
            if task['kind']!='basis_observation' or task['scope'][:2]!=[state['book_id'],episode]:continue
            facts=read(task['payload']['requirements']['path'])
            if any(facts.get(k)!=value for k,value in expected.items()):continue
            if task['status']=='READY':
                with self.lock:self.scheduler.claim(task['task_id'],epoch=self.epoch)
            if task['status'] in {'READY','LEASED','RUNNING','RESULT_SAVED','UNKNOWN','COMMITTED'}:
                self._finish_task(task['task_id'],[ref(result_path)],outcome)
        self.wake.set();return outcome

    def _watch(self):
        while not self.stop.is_set():
            try:
                self._replay_receipts();self._observe_health();self._resume_asset_waiters()
                for path in sorted((self.folder/'inbox').glob('*.json')):
                    with self.lock:
                        if str(path) in self.busy:continue
                        self.busy.add(str(path));future=self.jobs.submit(self._process,path);self.futures[str(path)]=future
                with self.lock:
                    for key,future in list(self.futures.items()):
                        if future.done():self.futures.pop(key);self.busy.discard(key)
            except (OSError,ValueError,RuntimeError) as exc:
                atomic_json(self.folder/'watcher-error.json',{'error':str(exc),'at':time.time()})
            self.wake.wait(self.scan_seconds);self.wake.clear()

    def _resume_asset_waiters(self):
        if self.assets is None:return
        blocked={}
        for path in (self.folder/'waiting').glob('*.json'):
            value=read(path);request=value['request'];episode=request['episode_id']
            if episode not in blocked:blocked[episode]=set(self.assets.blocked_panels(episode))
            selected={p['panel_id'] for p in request.get('fragment',{}).get('panels',[])}
            if not selected&blocked[episode] and self._basis_ready(episode):
                atomic_json(self.folder/'inbox'/path.name,request);path.unlink()

    def _process(self,path):
        request=None
        try:
            request=read(path);episode=request['episode_id'];self._budget('preparation-local')
            result=self._fragment(request) if request['action']=='submit-fragments' else self._basis_observation(request) if request['action']=='submit-basis-observation' else self._observations(request)
            atomic_json(self.folder/'done'/path.name,{'request':request,'result':result});path.unlink(missing_ok=True)
        except Exception as exc:
            if str(exc) in {'ASSET_REVIEW_REQUIRED','BASIS_REVIEW_REQUIRED'}:
                atomic_json(self.folder/'waiting'/path.name,{'request':request,'wait_reason':str(exc)})
                path.unlink(missing_ok=True);return
            # Malformed direct child output keeps its exact original bytes.
            raw_reference=None
            if request is None and path.exists():
                original=self.folder/'error-history'/(path.stem+'-'+str(time.time_ns())+'.raw')
                path.replace(original);raw_reference=ref(original)
            # Preserve original submitted content and precise original failure.
            atomic_json(self.folder/'errors'/path.name,{'request':request,'raw_reference':raw_reference,'error':str(exc),'exception_type':type(exc).__name__,'at':time.time()})
            path.unlink(missing_ok=True)
        finally:self.wake.set()

    def _fragment(self,r):
        from panel_derivation import derive,build_index,resolve_previous,effective
        from input_dependencies import affected
        from preparation_pipeline import combined_previous
        episode=r['episode_id'];folder=self._episode_folder(episode);config=self._config(episode);workspace=Workspace(config['run_root'])
        operation=r['operation_id'];task_id=episode+':derive:'+fingerprint(operation)
        with file_lock(folder/'domain.lock'):
            config=self._config(episode)
            if operation in config['operations']:
                outcome=config['operations'][operation];saved=outcome['collection']
                self._finish_task(task_id,[saved],outcome['business_result'])
                if r.get('task_id'):self._complete_fragment_task(r['task_id'],config,workspace)
                return outcome['business_result']
            if not self._basis_ready(episode):raise ValueError('BASIS_REVIEW_REQUIRED')
            if self.assets is not None and set(row['panel_id'] for row in r['fragment']['panels'])&set(self.assets.blocked_panels(episode)):
                raise ValueError('ASSET_REVIEW_REQUIRED')
            fragment=copy.deepcopy(r['fragment'])
            for row in fragment['panels']:row['packet_header']=self._ratio_header(row['packet_header'],config['frame_ratio_plan'])
            receipt=workspace.submit(fragment);current=workspace.read()
            completed=[row['panel_id'] for row in current['panels']];scope=workspace.scope(completed)
            stage=Path(config['run_root'])/'.preparation-pipeline'/'scopes'/fingerprint(operation);stage.mkdir(parents=True,exist_ok=True)
            source_path=stage/'authoring.json'
            if not source_path.exists():atomic_json(source_path,scope)
            else:scope=read(source_path)
            previous=combined_previous(config,stage/'previous.json')
        # The existing index computes precise changed inputs and dependency closure.
        index=build_index(scope,panel_ids=completed);prior,_=resolve_previous(source_path,scope,previous)
        impact=affected(prior,index);selected=impact['affected_panel_ids']
        versions={p:scope['row_versions'][p] for p in selected}
        with self.lock:
            tasks=self.scheduler.status()['tasks']
            if task_id not in tasks:
                self.scheduler.register([self._task(task_id,'derive',episode,[ref(source_path)],{'panel_ids':selected})],epoch=self.epoch)
                self.scheduler.claim(task_id,epoch=self.epoch)
        output=stage/'derived';derivation_path=output/'派生记录.json'
        rows={row['panel_id']:row for row in scope['panels']};results={};errors={}
        state=read(config['state_path']) if config.get('state_path') else None
        def collect(row):
            pid=row['panel_id']
            if row.get('pending') or row.get('error') or not row.get('artifacts'):
                errors[pid]=row.get('error','DERIVATION_DEPENDENCY_PENDING');return
            from preparation_pipeline import bind_packet
            from preparation_scope import technical_inputs,finalize_scope
            from input_dependencies import recheck
            recheck(row.get('observations',[]))
            shot=effective(scope,rows[pid])[0];manifest=row['artifacts'][0]['path'];packet=read(manifest)
            packet,shot,packet_ref,package_root=bind_packet(packet,shot,manifest,config['run_root'],
                Path(config['run_root'])/('.preparation-bound-'+fingerprint(operation)+'-'+pid+'.json'))
            inputs={}
            try:
                if state is None:raise ValueError('STATE_BINDING_REQUIRED')
                scope_shots=stage/('scope-shots-'+pid+'.json')
                atomic_json(scope_shots,{**expand(scope['shot_header'],scope['shared']),'panels':[shot],
                    'preparation_scope':{'policy':'preparation_scope_binding_v1','panel_ids':[pid]}})
                state_view={**state,'shot_manifest':{'path':scope_shots.relative_to(Path(config['run_root'])).as_posix(),'sha256':file_hash(scope_shots)}}
                inputs[pid]=technical_inputs(state_view,config['run_root'],shot,packet,package_root,dependency_plan=config.get('dependency_plan'))
            except (OSError,ValueError,KeyError,TypeError) as exc:errors[pid]=str(exc)
            result=finalize_scope(inputs,operation_id=operation+':technical:'+pid,receipt_root=folder)
            result['input_errors']={pid:errors[pid]} if pid in errors else {}
            review=result['records'].get(pid)
            panel={'package_manifest':packet_ref,'shot':shot,'derivation':row,'row_version':versions[pid],
                'inputs':inputs.get(pid),'review':review,'technical_status':'TECHNICALLY_READY' if review else
                    'NEEDS_OBSERVATION' if pid in result['targeted_panel_ids'] else 'HOLD','scope_operation':operation}
            # No long model/root wait: a fast immutable row enters the working
            # collection while other rows of this fragment are still rendering.
            with file_lock(folder/'domain.lock'):
                latest=workspace.read()
                if latest['row_versions'][pid]!=versions[pid]:raise ValueError('SCOPE_COMMIT_STALE_ROW:'+pid)
                now_scope=workspace.scope([pid])
                if fingerprint(effective(now_scope,now_scope['panels'][0]))!=fingerprint(effective(scope,rows[pid])):
                    raise ValueError('SCOPE_COMMIT_STALE_CONSUMED_SHARED:'+pid)
                current_config=self._config(episode);current_config['panels'][pid]=panel
                current_config['risk_queue']=[p for p in current_config['risk_queue'] if p!=pid]+result['targeted_panel_ids']
                atomic_json(self._config_path(episode),current_config)
            self._milestone('technically_ready' if review else 'scope_hold',panel_id=pid,operation_id=operation)
            results[pid]=result
        if derivation_path.is_file():
            derived=read(derivation_path)
            for row in derived['panels']:collect(row)
        elif selected:
            # An interrupted directory is preserved as evidence; never overwrite.
            if output.exists():output=stage/('derived-recovery-'+str(time.time_ns()));derivation_path=output/'派生记录.json'
            derived=derive(source_path,output,previous=previous,panel_ids=selected,executor=self.derivation,sink=collect)
        else:
            derived={'policy':'panel_derivation_v1','panel_ids':scope['panel_ids'],'panels':[],
                'metrics':{'compiled_panels':0,'reused_panels':0},'errors':{},'pending_panel_ids':[]}
            output.mkdir(exist_ok=True);atomic_json(derivation_path,derived)
        records={pid:review for result in results.values() for pid,review in result['records'].items()}
        targets=[p for result in results.values() for p in result['targeted_panel_ids']]
        result={'status':'SAVED_WITH_HOLDS' if errors else 'PARTIAL_READY' if targets else 'TECHNICALLY_READY',
            'records':records,'targeted_panel_ids':targets,'input_errors':errors,'review_performed':any(v.get('review_performed') for v in records.values())}
        decisions=[]
        if config.get('authority') and records:decisions=self._adopt_scope(self._config(episode),output,result,list(records))
        self._milestone('compile',compiled=derived['metrics']['compiled_panels'],reused=derived['metrics']['reused_panels'],operation_id=operation)
        outcome={'status':result['status'],'panel_ids':selected,'scope_result':result,'decisions':decisions,'derivation':ref(derivation_path)}
        collection=stage/'collection.json';atomic_json(collection,outcome);collection_ref=ref(collection)
        with file_lock(folder/'domain.lock'):
            config=self._config(episode)
            if ref(derivation_path) not in config['derivations']:config['derivations'].append(ref(derivation_path))
            # Store enough for crash-after-domain-before-ack recovery. Original
            # collection bytes are the domain receipt; no derive/finalize replay.
            config['operations'][operation]={'collection':collection_ref,'business_result':outcome,'task_id':task_id}
            atomic_json(self._config_path(episode),config)
        self._finish_task(task_id,[collection_ref],outcome)
        if targets:
            risk_path=stage/'risk-needed.json';atomic_json(risk_path,{'panel_ids':targets,'inputs':{p:self._config(episode)['panels'][p]['inputs'] for p in targets},'review_performed':False})
            with self.lock:self.scheduler.register([self._task(episode+':risk:'+fingerprint(operation),'risk_observation',episode,[ref(risk_path)],
                {'panel_ids':targets,'episode_id':episode,'submission_action':'submit-observations','source_operation':operation},dependencies=[task_id])],epoch=self.epoch)
        if r.get('task_id'):self._complete_fragment_task(r['task_id'],config,workspace)
        return outcome

    def _complete_fragment_task(self,task_id,config,workspace):
        with self.lock:task=self.scheduler.status()['tasks'][task_id]
        ids=task['payload']['panel_ids'];ready={p for p,row in config['panels'].items() if row['technical_status']=='TECHNICALLY_READY'}
        if not set(ids)<=ready:return
        path=self._episode_folder(config['episode_id'])/('model-result-'+fingerprint(task_id)+'.json')
        if not path.exists():atomic_json(path,{'panel_ids':ids,'scope_operations':{p:config['panels'][p]['scope_operation'] for p in ids}})
        self._finish_task(task_id,[ref(path)],{'status':'ACCEPTED','panel_ids':ids})
        self._tune_chunks(task,len(ids));self._observe_health(force=True)

    def _tune_chunks(self,task,accepted):
        if task['kind']!='shot_fragment' or not task.get('host_id'):return
        started=task['timestamps'].get('running')
        if started is None:return
        elapsed=time.time()-started
        if elapsed<=0:return
        marker=self._episode_folder(task['scope'][1])/('chunk-observation-'+fingerprint(task['task_id'])+'.json')
        if marker.exists():return
        target=max(1,round(180*accepted/elapsed));episode=task['scope'][1];scene=task['payload']['scene_id']
        with self.lock:
            remaining=[t for t in self.scheduler.status()['tasks'].values() if t['kind']=='shot_fragment' and t['scope'][:2]==task['scope'][:2]
                and t['payload'].get('scene_id')==scene and t['status'] in {'READY','PENDING'} and not t.get('host_id')]
            ids=[p for t in remaining for p in t['payload']['panel_ids']]
            observation={'policy':'preparation_chunk_observation_v1','completed_task_id':task['task_id'],
                'host_task_span_seconds':elapsed,'accepted_panels':accepted,'target_panel_count':target,
                'native_service_seconds':None,'repartitioned_task_ids':[t['task_id'] for t in remaining]}
            atomic_json(marker,observation)
            if not ids or all(len(t['payload']['panel_ids'])==min(target,len(ids)) for t in remaining):return
            new=[]
            for offset in range(0,len(ids),target):
                selected=ids[offset:offset+target];payload=copy.deepcopy(task['payload']);payload.update(panel_ids=selected,
                    row_versions={p:0 for p in selected},chunk_observation=ref(marker))
                new.append(self._task(episode+':adaptive:'+fingerprint([task['task_id'],offset]),'shot_fragment',episode,
                    remaining[0]['input_refs'],payload,panel_count=len(selected),dependencies=remaining[0]['dependencies']))
            # Supersede only never-claimed tasks; unknown/submitted tasks are excluded.
            self.scheduler.reconcile({t['task_id']:{'status':'SUPERSEDED','evidence':ref(marker),
                'wait_reason':'OBSERVED_HOST_LATENCY_REPARTITION'} for t in remaining},epoch=self.epoch)
            self.scheduler.register(new,epoch=self.epoch)

    def _observe_health(self,force=False):
        if not self.native_capacities or 'model' not in self.native_capacities:return
        now=time.time()
        if not force and now-self.last_health_check<2:return
        self.last_health_check=now;view=self.coordinator.status(disk=self.root)
        with self.lock:
            accepted=self.scheduler.status()['metrics']['accepted_panels']
            key=(view['sample'].get('known'),view['critical'],view['warning'],view['backlog'],accepted,self.native_capacities['model'],int(now/60))
            if key==self.last_health_key:return
            self.last_health_key=key
            self.scheduler.reconcile(epoch=self.epoch,health={'model_capacity':self.native_capacities['model'],
                'known':view['sample'].get('known',False),'pressure':view['critical'] or view['warning'],
                'backpressure':view['backlog']})

    def _adopt_scope(self,config,output,result,ids):
        from review_policy import proposal,delegated_decisions
        if not config.get('reviewer'):raise ValueError('ADOPTION_REVIEWER_REQUIRED')
        from preparation_pipeline import reference
        root=Path(config['run_root'])
        artifacts=[reference(output/'镜头派生.json',root)]+[reference(config['panels'][p]['package_manifest']['path'],root) for p in ids if p in config['panels']]
        items=[{'item_id':'B','phase':'shot_design','panel_ids':ids,'artifacts':artifacts[:1],
                'summary':'Adopt exact completed scope inputs; ordinary panels have no visual observation'},
            {'item_id':'PACKAGE','phase':'generation_package','panel_ids':ids,'artifacts':artifacts,
                'summary':'Adopt exact executable scope packages under existing delegation'}]
        review=proposal(self.descriptor['book_id'],config['episode_id'],items,config['run_root'])
        return delegated_decisions(review,['B','PACKAGE'],config['authority'],config['reviewer'],
            'Scope technical finalization; review_performed='+str(result['review_performed']),config['run_root'])

    def _observations(self,r):
        from preparation_scope import finalize_scope
        episode=r['episode_id'];folder=self._episode_folder(episode);config=self._config(episode)
        observations=r['observations'];ids=list(observations)
        inputs={pid:config['panels'][pid]['inputs'] for pid in ids}
        result=finalize_scope(inputs,observations,r.get('reviewer'),operation_id=r['operation_id'],receipt_root=folder)
        decisions=[]
        if config.get('authority'):
            for pid in result['records']:
                manifest=Path(config['panels'][pid]['derivation']['artifacts'][0]['path'])
                decisions.extend(self._adopt_scope(config,manifest.parent.parent,result,[pid]))
        result['decisions']=decisions
        with file_lock(folder/'domain.lock'):
            config=self._config(episode)
            if any(config['panels'][p]['inputs']!=inputs[p] for p in ids):raise ValueError('OBSERVATION_INPUT_CHANGED')
            for pid,review in result['records'].items():config['panels'][pid].update(review=review,technical_status='TECHNICALLY_READY')
            config['risk_queue']=[p for p in config['risk_queue'] if p not in result['records']]
            config['operations'][r['operation_id']]=result;atomic_json(self._config_path(episode),config)
        # Every now-complete assigned fragment/risk task settles automatically.
        # Unknown native calls still require reconciliation; no new native call.
        with self.lock:tasks=self.scheduler.status()['tasks']
        for task in tasks.values():
            if task['scope'][:2]==[self.descriptor['book_id'],episode] and task['kind'] in {'shot_fragment','risk_observation'} and task['status'] in {'READY','LEASED','RUNNING','RESULT_SAVED'}:
                if task['status']=='READY':
                    if task['kind']!='risk_observation' or not set(task['payload']['panel_ids'])<=set(result['records']):continue
                    with self.lock:self.scheduler.claim(task['task_id'],epoch=self.epoch)
                self._complete_fragment_task(task['task_id'],config,Workspace(config['run_root']))
        return result

    def status(self,details=True,after_revision=None):
        episodes={}
        for episode in self.descriptor['episode_ids']:
            path=self._config_path(episode)
            if not path.is_file():episodes[episode]={'status':'SEMANTIC_HOST_NEEDED'};continue
            config=read(path);workspace=Workspace(config['run_root']).read()
            episodes[episode]={'status':'WORKING_DRAFT','pending_panel_ids':workspace['pending_panel_ids'],
                'collected_panel_ids':[p for p in workspace['panel_ids'] if p in config['panels']],
                'risk_queue':config['risk_queue'],'panels':config['panels']}
        with self.lock:scheduler=self.scheduler.status();active=len(self.futures)
        revision=fingerprint([scheduler['revision'],[(episode,self._config_path(episode).stat().st_mtime_ns) for episode in self.descriptor['episode_ids'] if self._config_path(episode).exists()]])
        if after_revision==revision:return {'status':'UNCHANGED','revision':revision,'owner_epoch':self.epoch}
        if not details:
            compact={}
            for episode,value in episodes.items():
                if 'panels' not in value:compact[episode]=value;continue
                compact[episode]={k:v for k,v in value.items() if k!='panels'}
                compact[episode]['blocked_panel_ids']=[p for p,row in value['panels'].items() if row['technical_status']=='HOLD']
                compact[episode]['collected_count']=len(value['collected_panel_ids'])
                compact[episode]['record']=ref(self._config_path(episode))
            return {'status':'RUNNING','revision':revision,'owner_epoch':self.epoch,'episodes':compact,
                'active_local_jobs':active,'waiting_assets':len(list((self.folder/'waiting').glob('*.json'))),
                'scheduler':{'revision':scheduler['revision'],'model':scheduler['model'],
                    'metrics':{k:v for k,v in scheduler['metrics'].items() if k not in {'inflight_curve','dispatch_gaps'}}},
                'inbox_pending':len(list((self.folder/'inbox').glob('*.json'))),
                'inbox_errors':[str(p) for p in sorted((self.folder/'errors').glob('*.json'))],
                'dispatch_authorized':False,'image_calls':0}
        return {'status':'RUNNING','revision':revision,'owner_epoch':self.epoch,'scheduler':scheduler,'episodes':episodes,
            'active_local_jobs':active,'waiting_assets':len(list((self.folder/'waiting').glob('*.json'))),'inbox_pending':len(list((self.folder/'inbox').glob('*.json'))),
            'inbox_errors':[str(p) for p in sorted((self.folder/'errors').glob('*.json'))],
            'dispatch_authorized':False,'image_calls':0,'metrics':self.metrics()}

    def seal(self,r):
        self._budget('preparation-seal',preserve=True);episode=r['episode_id'];config=self._config(episode)
        with self.lock:
            pending=[path for path in self.futures if (Path(path).exists() and read(path).get('episode_id')==episode)]
        if pending:return {'status':'HOLD','missing_keys':[],'errors':['LOCAL_WORK_IN_PROGRESS'],'active_requests':pending}
        if self.assets is not None and self.assets.blocked_panels(episode):return {'status':'HOLD','blocked_asset_panel_ids':self.assets.blocked_panels(episode)}
        workspace=Workspace(config['run_root']);value=workspace.read();missing=value['pending_panel_ids']
        if missing:return {'status':'HOLD','missing_panel_ids':missing,'missing_keys':[],'dispatch_authorized':False}
        blocked=[p for p in value['panel_ids'] if config['panels'].get(p,{}).get('technical_status')!='TECHNICALLY_READY']
        if blocked:return {'status':'HOLD','blocked_panel_ids':blocked,'risk_queue':config['risk_queue'],'dispatch_authorized':False}
        if not config.get('state_path'):return {'status':'HOLD','missing_keys':['state_path'],'dispatch_authorized':False}
        from preparation_pipeline import seal_episode
        result=seal_episode(self,episode,config,r)
        return result

    def publish(self,r):
        self._budget('preparation-publish',preserve=True)
        required=['source_zip','contract','output'];missing=[k for k in required if not r.get(k)]
        if missing:return {'status':'HOLD','missing_keys':missing,'dispatch_authorized':False}
        from handoff_zip import publish
        return publish(r['source_zip'],r['contract'],r['output'])

    def wait_idle(self,timeout=30):
        deadline=time.monotonic()+timeout;self.wake.set()
        while time.monotonic()<deadline:
            with self.lock:active=bool(self.futures)
            if not active and not any((self.folder/'inbox').glob('*.json')):return True
            self.stop.wait(.02)
        return False

    def close(self):
        if self.closed:return
        self.closed=True;self.stop.set();self.wake.set();self.thread.join(5)
        self.jobs.shutdown(wait=True);self.derivation.__exit__(None,None,None)


def serve(run_root,istream=None,ostream=None):
    istream=istream or sys.stdin;ostream=ostream or sys.stdout
    with_host=Host(run_root)
    try:
        for line in istream:
            try:result=with_host.handle(json.loads(line))
            except (ValueError,TypeError) as exc:result={'status':'HOLD','errors':[str(exc)]}
            ostream.write(json.dumps(result,ensure_ascii=False)+'\n');ostream.flush()
    finally:with_host.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['serve']);parser.add_argument('--run-root',required=True)
    args=parser.parse_args()
    try:serve(args.run_root);return 0
    except (OSError,ValueError,KeyError) as exc:print(json.dumps({'status':'HOLD','errors':[str(exc)]},ensure_ascii=False));return 1

if __name__=='__main__':configure_stdio();raise SystemExit(main())
