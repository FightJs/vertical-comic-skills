"""Native asset bridge: original attempt ledger, real resources, factual observations.

No model/image tool is invoked here. The native caller must use prepare-invoke,
then the single-use invoke-guard immediately before its actual tool call. A lost
invoke acknowledgement is unknown, never permission to invoke a second time.
"""
import copy
from pathlib import Path

import asset_runtime as runtime
from asset_format import required as format_required, review_errors
from authority_updates import authority_context, revocation_errors, state_write_lock
from codex_reference_contract import checked_file, digest, read_json, file_session, verify_read_snapshot
from image_return_io import put
from input_dependencies import fingerprint
from platform_io import atomic_json
from submission_contract import acknowledgement, registration

ACTIONS={'register-assets','asset-prepare-invoke','asset-invoke-guard','asset-capture',
         'asset-register','asset-recover','submit-asset-observations'}


def absolute_ref(path):
    path=Path(path).resolve();return {'path':str(path),'sha256':digest(path)}


def relative_ref(root,path):
    return {'path':Path(path).resolve().relative_to(root).as_posix(),'sha256':digest(path)}


def immutable(path,value):
    import json
    put(path,(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode())
    return absolute_ref(path)


class Assets:
    def __init__(self,host):
        self.host=host;self.root=host.root;self.folder=host.folder/'assets';self.folder.mkdir(exist_ok=True)
        self.coordinator=host.derivation.resources

    def handle(self,action,request):
        methods={'register-assets':self.register,'asset-prepare-invoke':self.prepare_invoke,
            'asset-invoke-guard':self.invoke_guard,'asset-capture':self.capture,
            'asset-register':self.register_return,'asset-recover':self.recover,
            'submit-asset-observations':self.observe}
        if action not in methods:raise ValueError('UNKNOWN_ASSET_ACTION')
        return methods[action](request)

    def _guard(self):
        return self.host.epoch_guard()

    def _tasks(self):
        with self.host.lock:return self.host.scheduler.status()['tasks']

    def _task(self,task_id,kind='asset_image'):
        task=self._tasks()[task_id]
        if task['kind']!=kind:raise ValueError('ASSET_TASK_KIND_MISMATCH')
        return task

    def _channel_path(self,task_id):
        return self.folder/(fingerprint(task_id)+'-channel.json')

    def _channel(self,task_id):
        return read_json(self._channel_path(task_id))

    def _row(self,job):
        key,_=registration(job);path=runtime.ledger_path(self.root)
        ledger=read_json(path) if path.exists() else {'attempts':{}}
        return key,ledger['attempts'].get(key)

    def _state(self,episode):
        if episode not in self.host.descriptor['episode_ids']:raise ValueError('ASSET_SCOPE_OUTSIDE_BATCH')
        matches=[]
        for ref in self.host.descriptor.get('states',[]):
            path=Path(ref['path'] if isinstance(ref,dict) else ref).resolve()
            if not path.is_relative_to(self.root):raise ValueError('ASSET_STATE_OUTSIDE_BATCH')
            if path.is_file():
                state=read_json(path)
                if state.get('book_id')==self.host.descriptor['book_id'] and state.get('episode_id')==episode:matches.append((path,state))
        if len(matches)!=1:raise ValueError('ASSET_CURRENT_STATE_REQUIRED')
        path,state=matches[0];root=path.parent.parent
        basis=read_json(checked_file(root,state['visual_basis']))
        if basis.get('book_id')!=state['book_id'] or basis.get('episode_id')!=episode:raise ValueError('ASSET_BASIS_SCOPE_MISMATCH')
        return path,state,root,basis

    @staticmethod
    def _basis_projection(basis,asset_id):
        return {**{k:v for k,v in basis.items() if k!='asset_tasks'},
            'asset_tasks':[r for r in basis.get('asset_tasks',[]) if r.get('asset_id')==asset_id]}

    def _target(self,spec,definition):
        _,state,root,basis=self._state(spec['episode_id'])
        original=read_json(checked_file(self.root,spec['visual_basis']))
        if self._basis_projection(original,spec['asset_id'])!=self._basis_projection(basis,spec['asset_id']):
            raise ValueError('ASSET_CURRENT_BASIS_CHANGED')
        needs=[r for r in basis.get('asset_tasks',[]) if r.get('asset_id')==spec['asset_id']]
        if len(needs)!=1:raise ValueError('ASSET_EXACT_NEED_REQUIRED')
        need=needs[0];panels=need.get('panel_ids')
        if not isinstance(panels,list) or not panels or len(set(panels))!=len(panels) or any(not isinstance(p,str) or not p for p in panels):
            raise ValueError('ASSET_EXACT_PANEL_SCOPE_REQUIRED')
        if state.get('source_snapshot'):
            source=read_json(checked_file(root,state['source_snapshot']))
            if not set(panels)<=set(source['panel_ids']):raise ValueError('ASSET_PANEL_OUTSIDE_SOURCE')
        return {'episode_id':spec['episode_id'],'asset_id':spec['asset_id'],'panel_ids':panels,
            'need':need,'definition':definition}

    def _generation_authority(self,spec):
        _,state,root,_=self._state(spec['episode_id'])
        auth=read_json(checked_file(self.root,spec['authorization']))
        with authority_context(state,root):
            errors=revocation_errors(auth,state['book_id'],state['episode_id'])
            if errors:raise ValueError(';'.join(errors))

    def _lineage_policy(self,spec):
        if spec['operation']=='generate':return
        path=runtime.ledger_path(self.root)
        rows=list(read_json(path)['attempts'].values()) if path.exists() else []
        source=spec.get('source_attempt_id');seen=set();chain=[]
        while source:
            if source in seen:raise ValueError('ASSET_ATTEMPT_LINEAGE_CYCLE')
            seen.add(source)
            matches=[r for r in rows if r['episode_id']==spec['episode_id'] and r['asset_id']==spec['asset_id'] and r['attempt_id']==source]
            if len(matches)!=1:raise ValueError('ASSET_ORIGINAL_ATTEMPT_REQUIRED')
            row=matches[0];chain.append(row);source=row.get('source_attempt_id')
        # Count the complete original-attempt family, including sibling branches.
        scoped=[r for r in rows if r['episode_id']==spec['episode_id'] and r['asset_id']==spec['asset_id']]
        indexed={r['attempt_id']:r for r in scoped}
        if len(indexed)!=len(scoped):raise ValueError('ASSET_AMBIGUOUS_ATTEMPT_LINEAGE')
        def origin(row):
            visited=set()
            while row.get('source_attempt_id'):
                if row['attempt_id'] in visited or row['source_attempt_id'] not in indexed:
                    raise ValueError('ASSET_INVALID_ATTEMPT_LINEAGE')
                visited.add(row['attempt_id']);row=indexed[row['source_attempt_id']]
            return row['attempt_id']
        family=[row for row in scoped if origin(row)==chain[-1]['attempt_id']]
        if spec['operation']=='repair':
            if sum(r['operation']=='repair' for r in family)>=1:raise ValueError('ASSET_QUALITY_REPAIR_LIMIT')
            if chain[0]['status']!='GENERATED':raise ValueError('ASSET_REPAIR_SAVED_SOURCE_REQUIRED')
        else:
            if sum(r['operation']=='retry' for r in family)>=4:raise ValueError('ASSET_NETWORK_RETRY_LIMIT')
            if chain[0]['status']!='CALL_FAILED':raise ValueError('ASSET_UNKNOWN_CANNOT_RETRY')
            evidence=read_json(checked_file(self.root,chain[0]['response_evidence']))
            if evidence.get('failure_kind')=='content_moderation':raise ValueError('ASSET_CONTENT_MODERATION_TERMINAL: '+str(evidence.get('error','')))
            if evidence.get('failure_kind')!='network' or evidence.get('no_image_confirmed') is not True or not evidence.get('error'):
                raise ValueError('ASSET_CONFIRMED_NETWORK_ERROR_REQUIRED')

    def register(self,r):
        self.host._budget('register-assets');self._guard()
        definitions=r.get('definitions')
        if not isinstance(definitions,list) or not definitions:raise ValueError('ASSET_DEFINITIONS_REQUIRED')
        groups={}
        for definition in definitions:
            job,_,spec=runtime.compile_job(self.root,definition);self._lineage_policy(spec)
            if spec['book_id']!=self.host.descriptor['book_id']:raise ValueError('ASSET_BOOK_OUTSIDE_BATCH')
            target=self._target(spec,definition)
            content_key=runtime.shared_asset_key(spec,arguments=job['arguments']) if spec.get('shared_asset') else None
            key=content_key if content_key and spec['operation']=='generate' else fingerprint([spec['book_id'],spec['episode_id'],spec['asset_id'],definition])
            group=groups.setdefault(key,{'items':[],'targets':[]})
            group['items'].append((definition,job,spec))
            scope=[target[k] for k in ('episode_id','asset_id','panel_ids')]
            if not any([t[k] for k in ('episode_id','asset_id','panel_ids')]==scope for t in group['targets']):group['targets'].append(target)
        tasks=[];all_targets=[]
        for key,group in groups.items():
            items=group['items'];shared=items[0][2].get('shared_asset')
            owner=shared['owner_episode_id'] if shared else items[0][2]['episode_id']
            candidates=[item for item in items if item[2]['episode_id']==owner]
            if not candidates:raise ValueError('ASSET_SHARED_OWNER_DEFINITION_REQUIRED')
            definition,job,spec=candidates[0];task_id='asset:'+key
            for target in group['targets']:target['review_task_id']=task_id+':review:'+fingerprint([target['episode_id'],target['asset_id'],target['panel_ids']])
            refs=[absolute_ref(checked_file(self.root,item[0])) for item in items]
            payload={'definition':definition,'targets':group['targets'],'shared_asset_key':key if shared else None,
                'submission_action':'asset-prepare-invoke','requires_native_tool':'image_gen.imagegen'}
            tasks.append({'task_id':task_id,'kind':'asset_image','lane':'image','scope':[spec['book_id'],owner],
                'input_digest':fingerprint([key,refs]),'input_refs':refs,'payload':payload})
            all_targets.extend(copy.deepcopy(group['targets']))
        with self.host.lock:
            self._guard();self.host.scheduler.register(tasks,epoch=self.host.epoch)
        self.host.wake.set()
        return {'status':'ASSETS_REGISTERED','image_task_ids':[t['task_id'] for t in tasks],'targets':all_targets,'image_calls':0,'asset_approval':'NOT_GRANTED'}

    def prepare_invoke(self,r):
        self.host._budget('asset-prepare-invoke');self._guard();task=self._task(r['task_id'])
        channel=r.get('channel') or {};evidence_ref=channel.get('evidence')
        if not evidence_ref:raise ValueError('ASSET_NATIVE_CHANNEL_REQUIRED')
        evidence=read_json(checked_file(self.root,evidence_ref))
        if (evidence.get('source_kind')!='observed_native_channel' or evidence.get('tool')!='image_gen.imagegen' or
            evidence.get('ready') is not True or not isinstance(evidence.get('source_locator'),str) or not evidence['source_locator'].strip() or
            not isinstance(channel.get('host_id'),str) or not channel['host_id'] or evidence.get('host_id')!=channel['host_id']):
            raise ValueError('ASSET_NATIVE_CHANNEL_NOT_READY')
        job,_,spec=runtime.compile_job(self.root,task['payload']['definition']);self._lineage_policy(spec)
        key,row=self._row(job)
        if row:
            return {'status':'ASSET_ALREADY_REGISTERED','job':job,'ack':acknowledgement(job,row,fresh=False,state_sha256=digest(runtime.ledger_path(self.root))),
                'attempt_status':row['status'],'image_calls':0}
        self._target(spec,task['payload']['definition']);self._generation_authority(spec)
        with self.host.lock:
            self._guard();task=self._task(task['task_id'])
            if task['status']=='READY':self.host.scheduler.claim(task['task_id'],epoch=self.host.epoch)
            elif task['status']!='LEASED':raise ValueError('ASSET_TASK_NOT_LEASED')
            permit=self.coordinator.acquire('image',str(self.root)+':'+key,disk=self.root)
            if permit['status']!='RESOURCE_GRANTED':return {**permit,'invoke_allowed':False,'image_calls':0}
            saved={'policy':'preparation_asset_channel_v1','task_id':task['task_id'],'registration_id':key,'job':job,
                'permit_token':permit['token'],'permit_owner':self.coordinator.owner,'channel':channel,'guard_used':False}
            try:
                atomic_json(self._channel_path(task['task_id']),saved)
                ack=runtime.submit(self.root,job,epoch_guard=self._guard)
            except Exception:
                # Once the attempt exists its result may be unknown, even if a callback failed.
                if self._row(job)[1] is None:self.coordinator.release(permit['token'])
                raise
            if not ack['invoke_allowed']:
                if ack['registration_id']!=key or self._row(job)[1]['status'] not in {'IN_FLIGHT','RESULT_UNKNOWN'}:
                    self.coordinator.release(permit['token'])
                return {'status':'ASSET_ALREADY_REGISTERED','job':job,'ack':ack,'image_calls':0}
            self.host.scheduler.attach_host(task['task_id'],channel['host_id'],epoch=self.host.epoch,
                operation_id=task['operation_id'],evidence=absolute_ref(checked_file(self.root,evidence_ref)))
        return {'status':'ASSET_PREPARED_NATIVE_TOOL_REQUIRED','job':job,'ack':ack,'image_calls':0,'next_action':'asset-invoke-guard'}

    def invoke_guard(self,r):
        self.host._budget('asset-invoke-guard');self._guard()
        with self.host.lock:
            self._guard();channel=self._channel(r['task_id'])
            if channel['guard_used']:return {'status':'ASSET_INVOKE_OUTCOME_UNKNOWN','invoke_allowed':False,'registration_id':channel['registration_id'],'image_calls':0}
            with file_session():
                spec=read_json(checked_file(self.root,channel['job']['submission']['definition']))
                self._target(spec,channel['job']['submission']['definition']);self._generation_authority(spec)
                runtime.final_invoke_guard(self.root,channel['job'],epoch_guard=self._guard)
            # Persist before returning permission: lost stdout cannot grant a second call.
            channel['guard_used']=True;atomic_json(self._channel_path(r['task_id']),channel)
        return {'status':'ASSET_NATIVE_INVOKE_GUARDED','invoke_allowed':True,'registration_id':channel['registration_id'],
            'job':channel['job'],'image_calls':0}

    def capture(self,r):
        channel=self._channel(r['task_id'])
        reference=runtime.capture(self.root,channel['registration_id'],r['raw_path'],request_evidence=r['request_evidence'],
            response_source_locator=r['response_source_locator'],selected_index=r.get('selected_index'),resolution=r.get('resolution'))
        return {'status':'ASSET_CAPTURED','capture_reference':reference,'registration_id':channel['registration_id'],'image_calls':0}

    def _release(self,channel,completed=False):
        # Coordinator release is idempotent; never release another process's lease.
        if channel['permit_owner']!=self.coordinator.owner:return {'status':'ASSET_RESOURCE_OTHER_OWNER'}
        return self.coordinator.release(channel['permit_token'],completed=completed,preserved=True)

    def register_return(self,r):
        channel=self._channel(r['task_id']);key=channel['registration_id']
        if r.get('capture_reference'):
            captured=read_json(checked_file(self.root,r['capture_reference']))
            if captured.get('registration_id')!=key:raise ValueError('ASSET_CAPTURE_ATTEMPT_MISMATCH')
            runtime.register_capture(self.root,r['capture_reference'],resolution=r.get('resolution'))
        else:
            outcome=r.get('outcome')
            if not isinstance(outcome,dict) or outcome.get('status') not in {'RESULT_UNKNOWN','CALL_FAILED'}:
                raise ValueError('ASSET_ACTUAL_CAPTURE_OR_OUTCOME_REQUIRED')
            runtime.save(self.root,key,outcome,resolution=r.get('resolution'))
        return self._after_registration(r['task_id'],channel)

    def recover(self,r):
        channel=self._channel(r['task_id'])
        runtime.recover(self.root,channel['registration_id'],resolution=r.get('resolution'))
        return self._after_registration(r['task_id'],channel)

    def _after_registration(self,task_id,channel):
        row=read_json(runtime.ledger_path(self.root))['attempts'][channel['registration_id']]
        if row['status']=='RESULT_UNKNOWN':
            self._guard()
            with self.host.lock:
                self.host.scheduler.reconcile({task_id:{'status':'UNKNOWN','host_id':channel['channel']['host_id'],
                    'evidence':absolute_ref(checked_file(self.root,row['response_evidence']))}},epoch=self.host.epoch)
            return {'status':'ASSET_RESULT_UNKNOWN','registration_id':channel['registration_id'],'image_calls':0}
        self._release(channel,completed=row['status']=='GENERATED')
        self._guard()
        if row['status']=='CALL_FAILED':
            task=self._task(task_id)
            proof={'policy':'preparation_host_observation_v1','task_id':task_id,'operation_id':task['operation_id'],
                'host_id':task['host_id'],'status':'FAILED_NO_IMAGE','confirmed_no_image':True,
                'original_response_evidence':row['response_evidence'],'registration_id':channel['registration_id']}
            evidence=immutable(self.folder/(channel['registration_id']+'-confirmed-failure.json'),proof)
            with self.host.lock:
                self.host.scheduler.reconcile({task_id:{'status':'BLOCKED','host_id':task['host_id'],
                    'evidence':evidence,'terminal':bool(task['host_id']),'wait_reason':'ASSET_CONFIRMED_CALL_FAILED'}},epoch=self.host.epoch)
            return {'status':'ASSET_CALL_FAILED','registration_id':channel['registration_id'],'response_evidence':row['response_evidence'],'image_calls':0}
        image=absolute_ref(checked_file(self.root,row['output']));task=self._task(task_id)
        outputs=[image,absolute_ref(checked_file(self.root,row['request_evidence'])),absolute_ref(checked_file(self.root,row['response_evidence']))]
        self.host._finish_task(task_id,outputs,{'status':'ASSET_IMAGE_SAVED','registration_id':channel['registration_id'],'image_sha256':image['sha256']})
        reviews=[]
        for target in task['payload']['targets']:
            definition=absolute_ref(checked_file(self.root,target['definition']))
            inputs=[image,definition,*outputs[1:]]
            reviews.append({'task_id':target['review_task_id'],'kind':'asset_review','lane':'model',
                'scope':[self.host.descriptor['book_id'],target['episode_id']],
                'input_digest':fingerprint(inputs),'input_refs':inputs,'dependencies':[task_id],
                'payload':{'image_task_id':task_id,'registration_id':channel['registration_id'],'image':image,'target':target,
                    'submission_action':'submit-asset-observations','actual_observer_required':True,'format_contract_required':format_required(target['need'])}})
        with self.host.lock:self.host.scheduler.register(reviews,epoch=self.host.epoch)
        self.host.wake.set()
        return {'status':'ASSET_REGISTERED','registration_id':channel['registration_id'],'review_task_ids':[t['task_id'] for t in reviews],
            'output':image,'asset_approval':'NOT_GRANTED','image_calls':0}

    def _current_targets(self,tasks):
        targets={}
        for task in tasks.values():
            if task['kind']=='asset_image':
                for target in task['payload']['targets']:
                    targets[(target['episode_id'],target['asset_id'])]=target
        return list(targets.values())

    def dependencies(self,episode_id,panel_ids):
        tasks=self._tasks();ids=set(panel_ids)
        return [target['review_task_id'] for target in self._current_targets(tasks) if target['episode_id']==episode_id and
            ids.intersection(target['panel_ids']) and target['review_task_id'] in tasks]

    def blocked_panels(self,episode_id):
        tasks=self._tasks();blocked=[]
        for target in self._current_targets(tasks):
            if target['episode_id']==episode_id and tasks.get(target['review_task_id'],{}).get('status')!='COMMITTED':
                blocked.extend(target['panel_ids'])
        return list(dict.fromkeys(blocked))

    def observe(self,r):
        task=self._task(r['task_id'],'asset_review');target=task['payload']['target'];image=task['payload']['image']
        observation=read_json(checked_file(self.root,r['observation']))
        saved=immutable(self.folder/(fingerprint([task['task_id'],r['observation']])+'-observation.json'),observation)
        self.host._budget('submit-asset-observations',preserve=True)
        required=('source_locator','reviewer','observed_at','evidence')
        if (observation.get('policy')!='asset_observation_v1' or observation.get('source_kind')!='observed_image_review' or
            any(not isinstance(observation.get(k),str) or not observation[k].strip() for k in required) or
            observation.get('status') not in {'PASS','FAIL'} or observation.get('image_sha256')!=image['sha256'] or
            any(observation.get(k)!=target[k] for k in ('episode_id','asset_id','panel_ids'))):
            raise ValueError('ASSET_OBSERVATION_SCOPE_OR_IMAGE_MISMATCH')
        self._guard()
        if task['status'] not in {'LEASED','RUNNING','RESULT_SAVED','COMMITTED'}:raise ValueError('ASSET_OBSERVATION_TASK_NOT_CLAIMED')
        if observation['status']=='FAIL':
            with self.host.lock:self.host.scheduler.record_result(task['task_id'],[saved],epoch=self.host.epoch)
            return {'status':'ASSET_REVIEW_FAILED','observation':saved,'image_calls':0}
        if format_required(target['need']):
            errors=review_errors(observation.get('format_review'),image['sha256'])
            if errors:raise ValueError(';'.join(errors))
        adoption=self._adopt(task,target,image,observation,r['adoption_authorization'],saved)
        self.host._finish_task(task['task_id'],[image,saved,adoption],{'status':'ASSET_ADOPTED','target':{k:target[k] for k in ('episode_id','asset_id','panel_ids')},'image_sha256':image['sha256']})
        self._supersede_replaced(task['task_id'],adoption)
        self.host.wake.set()
        return {'status':'ASSET_ADOPTED','observation':saved,'adoption':adoption,'image_calls':0}

    def _supersede_replaced(self,review_id,adoption):
        """Retire proven replaced work, preserving all original outputs and debt."""
        with self.host.lock:
            self._guard();tasks=self._tasks();review=tasks[review_id]
            if review['status']!='COMMITTED':raise ValueError('ASSET_REPLACEMENT_NOT_COMMITTED')
            proof=read_json(Path(adoption['path']))
            if digest(Path(adoption['path']))!=adoption['sha256'] or proof.get('operation_id')!=review['operation_id']:
                raise ValueError('ASSET_REPLACEMENT_PROOF_CHANGED')
            ledger=read_json(runtime.ledger_path(self.root))['attempts']
            current=ledger[review['payload']['registration_id']];ancestors=set();source=current.get('source_attempt_id')
            while source:
                matches=[(key,row) for key,row in ledger.items() if row['episode_id']==current['episode_id'] and
                    row['asset_id']==current['asset_id'] and row['attempt_id']==source]
                if len(matches)!=1 or matches[0][0] in ancestors:raise ValueError('ASSET_INVALID_ATTEMPT_LINEAGE')
                key,row=matches[0];ancestors.add(key);source=row.get('source_attempt_id')
            if not ancestors:return
            target=review['payload']['target']
            def scope(value):return [value[k] for k in ('episode_id','asset_id','panel_ids')]
            latest={(t['episode_id'],t['asset_id']):t for t in self._current_targets(tasks)}
            candidates=[]
            for old in tasks.values():
                if old['status'] in {'COMMITTED','SUPERSEDED','UNKNOWN'} or old.get('native_inflight'):continue
                if old['kind']=='asset_review':
                    if old['payload']['registration_id'] not in ancestors or scope(old['payload']['target'])!=scope(target):continue
                    replacements=[review]
                elif old['kind']=='asset_image':
                    path=self._channel_path(old['task_id'])
                    if not path.exists() or read_json(path)['registration_id'] not in ancestors:continue
                    original=ledger[read_json(path)['registration_id']]
                    if original['status'] not in {'GENERATED','CALL_FAILED'}:continue
                    replacements=[]
                    for original_target in old['payload']['targets']:
                        successor=latest.get((original_target['episode_id'],original_target['asset_id']))
                        replacement=tasks.get(successor['review_task_id']) if successor else None
                        if (not replacement or replacement['status']!='COMMITTED' or
                            scope(successor)!=scope(original_target) or successor['review_task_id']==original_target['review_task_id']):break
                        replacements.append(replacement)
                    else:
                        candidates.append((old,replacements))
                    continue
                else:continue
                candidates.append((old,replacements))
            for old,replacements in candidates:
                relation={'policy':'preparation_asset_replacement_v1','predecessor_task_id':old['task_id'],
                    'successor_review_task_id':review_id,'adoption':adoption,
                    'ancestor_registration_ids':sorted(ancestors),
                    'replacements':[{'task_id':t['task_id'],'business_receipt':t['business_receipt'],
                        'target':{k:t['payload']['target'][k] for k in ('episode_id','asset_id','panel_ids')}} for t in replacements]}
                evidence=immutable(self.folder/(fingerprint([old['task_id'],review['operation_id']])+'-replacement.json'),relation)
                # Reconcile deliberately protects RESULT_SAVED. Here exact committed
                # replacement proof retires that scheduling obligation, not its result.
                state=self.host.scheduler.status()
                self.host.scheduler._task_append(state,old['task_id'],{'status':'SUPERSEDED',
                    'superseded_by':review_id,'replacement_evidence':evidence,'wait_reason':'REPLACED_BY:'+review_id},self.host.epoch)

    def _adopt(self,task,target,image,observation,authorization,observation_ref):
        self._guard()
        with file_session() as snapshot:
            auth=read_json(checked_file(self.root,authorization));path,state,root,basis=self._state(target['episode_id'])
            previous=digest(path);_,_,spec=runtime.compile_job(self.root,target['definition'])
            original=read_json(checked_file(self.root,spec['visual_basis']))
            original_projection=self._basis_projection(original,target['asset_id'])
            current_projection=self._basis_projection(basis,target['asset_id'])
            if {k:v for k,v in original_projection.items() if k!='asset_tasks'}!={k:v for k,v in current_projection.items() if k!='asset_tasks'}:
                raise ValueError('ASSET_CURRENT_BASIS_CHANGED')
            if (auth.get('source_kind')!='user_message' or not auth.get('source_locator') or not auth.get('quote') or
                auth.get('book_id')!=self.host.descriptor['book_id'] or target['episode_id'] not in auth.get('episode_ids',[]) or
                target['asset_id'] not in auth.get('asset_ids',[]) or auth.get('panel_ids')!=target['panel_ids'] or
                'adopt' not in auth.get('operations',[]) or auth.get('image_sha256')!=image['sha256']):
                raise ValueError('ASSET_ADOPTION_AUTHORIZATION_REQUIRED')
            with authority_context(state,root):
                errors=revocation_errors(auth,state['book_id'],state['episode_id'])
                if errors:raise ValueError(';'.join(errors))
            rows=[row for row in basis.get('asset_tasks',[]) if row.get('asset_id')==target['asset_id']]
            if len(rows)!=1:raise ValueError('ASSET_CURRENT_TARGET_MISSING')
            row=rows[0]
            source=Path(image['path'])
            expected=copy.deepcopy(target['need'])
            expected.update(reference={'path':'.preparation-assets/image-'+image['sha256']+source.suffix,'sha256':image['sha256']},
                review=copy.deepcopy(observation),adoption_authorization=copy.deepcopy(auth))
            if observation.get('format_review') is not None:expected['format_review']=copy.deepcopy(observation['format_review'])
            if row!=target['need'] and row!=expected:raise ValueError('ASSET_CURRENT_TARGET_SCOPE_CHANGED')
            checked_image=absolute_ref(source)
            if checked_image!=image:raise ValueError('ASSET_REVIEWED_IMAGE_CHANGED')
        destination=root/'.preparation-assets'/('image-'+image['sha256']+source.suffix)
        put(destination,source.read_bytes());new_basis=copy.deepcopy(basis)
        adopted=next(row for row in new_basis['asset_tasks'] if row['asset_id']==target['asset_id'])
        adopted.update(reference=relative_ref(root,destination),review=copy.deepcopy(observation),adoption_authorization=copy.deepcopy(auth))
        if observation.get('format_review') is not None:adopted['format_review']=copy.deepcopy(observation['format_review'])
        basis_path=root/'.preparation-assets'/('basis-'+fingerprint(new_basis)+'.json');immutable(basis_path,new_basis)
        new_ref=relative_ref(root,basis_path)
        receipt_path=self.folder/(fingerprint([task['operation_id'],image,observation_ref,authorization])+'-adoption.json')
        receipt={'policy':'preparation_asset_adoption_v1','operation_id':task['operation_id'],'episode_id':target['episode_id'],
            'asset_id':target['asset_id'],'panel_ids':target['panel_ids'],'image':image,'observation':observation_ref,
            'authorization':authorization,'visual_basis':new_ref,'state_path':str(path),'asset_publication':'NOT_GRANTED'}
        with self.host.lock,state_write_lock(path):
            self._guard();verify_read_snapshot(snapshot,refresh_views=False)
            current=read_json(path)
            if digest(path)!=previous:raise ValueError('ASSET_ADOPTION_STATE_CHANGED')
            current['visual_basis']=new_ref
            atomic_json(path,current)
            immutable(receipt_path,receipt)
        return absolute_ref(receipt_path)
