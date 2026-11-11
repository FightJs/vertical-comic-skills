#!/usr/bin/env python3
"""Durable preparation scheduling; never a business approval or native tool caller.

Task dictionaries require task_id, kind, scope, input_digest and input_refs. The
optional payload is immutable input. Only dependencies block readiness;
comparison_links and prior_image_plan are descriptive. claim returns a stable
operation_id which the business layer must use for receipt lookup before replay.
All mutations require this instance's live owner token and current epoch.

Receipts are actual hashed JSON files with policy preparation_business_receipt_v1,
status COMMITTED, task_id, operation_id and the exact saved output_refs. A supplied
receipt_query(operation_id) may instead verify an existing business ledger's
receipt reference. Neither stdout nor this module grants production authority.

plan is a read-only recommendation, not admission. capacities.model is the actual
native agent capacity; capacities.coordinator is a Coordinator.status() view.
local/image reservations remain the existing Coordinator caller's responsibility.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

from platform_io import atomic_json, file_lock
from machine_resources import alive, self_identity

POLICY = 'preparation_scheduler_v1'
STATUSES = {'PENDING', 'READY', 'LEASED', 'RUNNING', 'RESULT_SAVED', 'COMMITTED',
            'BLOCKED', 'UNKNOWN', 'SUPERSEDED', 'STOPPED'}
ACTIVE = {'LEASED', 'RUNNING', 'UNKNOWN'}
RECOVERY_KINDS = {'save_result', 'capture', 'persist', 'register_result', 'recover_result', 'reconcile'}
SHARED_KINDS = {'shared_prepare', 'asset_definition', 'asset_compile', 'asset_bind', 'source_parse', 'frame_ratio_plan'}
FINISH_KINDS = {'scope_finalize', 'adopt', 'collect', 'seal', 'publish', 'handoff', 'receive'}
LOCAL_KINDS = RECOVERY_KINDS | {'derive', 'compile', 'asset_compile', 'asset_bind', 'source_parse',
    'workspace_merge', 'bind', 'scope_bind', 'scope_finalize', 'adopt', 'collect', 'seal', 'publish', 'handoff', 'receive'}
IMAGE_KINDS = {'image', 'image_request', 'asset_image', 'reference_image'}
PANEL_KINDS = {'shot_fragment', 'shot_design', 'panel_design', 'panel_review', 'panel_authoring'}


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _hash(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def verify_ref(ref):
    if not isinstance(ref, dict) or not isinstance(ref.get('path'), str) or not Path(ref['path']).is_absolute():
        raise ValueError('FILE_REF_REQUIRED: absolute path and sha256')
    h = hashlib.sha256()
    with Path(ref['path']).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): h.update(block)
    if h.hexdigest() != ref.get('sha256'): raise ValueError('FILE_HASH_CHANGED: ' + ref['path'])
    return ref


def _occupied(task):
    return task['status'] in ACTIVE or task.get('native_inflight',False)


def _fsync_directory(path):
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)


class Journal:
    """Checksum-chained JSONL source of truth; snapshots are disposable caches."""
    def __init__(self, run_root):
        self.root = Path(run_root).resolve()
        self.path = self.root/'preparation-events.jsonl'
        self.meta_path = self.root/'preparation-journal.json'
        self.snapshot_path = self.root/'preparation-snapshot.json'
        self.lock_path = self.root/'preparation-journal.lock'
        self._cache = None; self._signature = None
        self.metrics = {'disk_reads': 0, 'cache_hits': 0, 'appended_events': 0, 'tail_recoveries': 0}

    def initialize(self, scope):
        self.root.mkdir(parents=True, exist_ok=True)
        with file_lock(self.lock_path):
            if self.meta_path.exists():
                meta = json.loads(self.meta_path.read_text(encoding='utf-8'))
                if meta.get('policy') != POLICY or scope is not None and meta['scope'] != scope:
                    raise ValueError('JOURNAL_SCOPE_CONFLICT')
            else:
                atomic_json(self.meta_path, {'policy': POLICY, 'scope': scope})
                _fsync_directory(self.root)
        return self.read()

    def _read(self):
        meta = json.loads(self.meta_path.read_text(encoding='utf-8'))
        if meta.get('policy') != POLICY: raise ValueError('JOURNAL_POLICY_CHANGED')
        st = self.path.stat() if self.path.exists() else None
        signature = (st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns) if st else None
        if self._cache is not None and self._signature == signature:
            self.metrics['cache_hits'] += 1
            return self._cache
        raw = self.path.read_bytes() if st else b''
        self.metrics['disk_reads'] += 1
        events = []; ids = {}; previous = '0'*64; offset = 0
        for line in raw.splitlines(keepends=True):
            # append always writes one newline. Only its incomplete trailing
            # record can be discarded; complete corrupt records fail closed.
            if not line.endswith(b'\n'): break
            try:
                envelope = json.loads(line)
                checksum = envelope['checksum']
                body = {k:v for k,v in envelope.items() if k != 'checksum'}
                if (body['seq'] != len(events)+1 or body['previous'] != previous or
                        _hash(body) != checksum or not isinstance(body['event']['event_id'], str) or
                        not body['event']['event_id'] or body['event']['event_id'] in ids):
                    raise ValueError('checksum, sequence or event id')
                previous = checksum; event = body['event']; events.append(event); ids[event['event_id']] = event
            except (ValueError, KeyError, TypeError, UnicodeError) as exc:
                raise ValueError('JOURNAL_CORRUPT: complete record at byte ' + str(offset)) from exc
            offset += len(line)
        value = {'policy': POLICY, 'scope': meta['scope'], 'revision': len(events), 'events': events,
                 'checksum': previous, 'valid_bytes': offset, 'torn_tail_bytes': len(raw)-offset}
        self._cache = value; self._signature = signature
        return value

    def read(self):
        # Readers never truncate or refresh caches on disk.
        return deepcopy(self._read())

    def append(self, event, expected_revision):
        event = deepcopy(event)
        if not isinstance(event.get('event_id'), str) or not event['event_id'].strip():
            raise ValueError('EVENT_ID_REQUIRED')
        _bytes(event)
        with file_lock(self.lock_path):
            state = self._read()
            old = next((e for e in state['events'] if e['event_id'] == event['event_id']), None)
            if old is not None:
                if old != event: raise ValueError('EVENT_ID_CONFLICT')
                return deepcopy(state)
            if expected_revision != state['revision']: raise ValueError('STALE_REVISION')
            body = {'seq': state['revision']+1, 'previous': state['checksum'], 'event': event}
            checksum = _hash(body); encoded = _bytes({**body, 'checksum': checksum}) + b'\n'
            created = not self.path.exists()
            with self.path.open('r+b' if not created else 'w+b') as stream:
                if state['torn_tail_bytes']:
                    stream.truncate(state['valid_bytes']); self.metrics['tail_recoveries'] += 1
                stream.seek(0, os.SEEK_END); stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
            if created: _fsync_directory(self.root)
            updated = {**state, 'revision':body['seq'], 'events':state['events']+[event],
                       'checksum':checksum, 'valid_bytes':state['valid_bytes']+len(encoded), 'torn_tail_bytes':0}
            st = self.path.stat();self._signature=(st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
            self._cache=updated;self.metrics['appended_events']+=1
            # Losing this cache never loses an event; a failed cache write must
            # not turn a durable successful append into a false failed response.
            try:
                atomic_json(self.snapshot_path, {k:v for k,v in updated.items() if k != 'events'})
            except OSError: pass
            return deepcopy(updated)


class Scheduler:
    def __init__(self, run_root, *, clock=None, liveness=None, identity=None,
                 coordinator=None, receipt_query=None):
        self.root=Path(run_root).resolve();self.journal=Journal(self.root)
        self.clock=clock or time.time;self.liveness=liveness or alive
        self.identity=identity or self_identity(os.getpid())
        self.coordinator=coordinator;self.receipt_query=receipt_query
        self.token=uuid.uuid4().hex;self.epoch=None;self._state_cache=None

    def _state(self):
        journal=self.journal._read()
        if self._state_cache is not None and self._state_cache['revision']==journal['revision']:
            return deepcopy(self._state_cache)
        state={'policy':POLICY,'scope':journal['scope'],'revision':journal['revision'],'owner':None,'tasks':{},
               'receipts':{},'model':{'target':2,'last_adjust':None,'accepted_at_adjust':0,'baseline':None,'probe':None},
               'metrics':{'accepted_panels':0,'events':journal['revision'],'started_at':None,'inflight_curve':[]}}
        for event in journal['events']:
            action=event['action']; at=event.get('at')
            if state['metrics']['started_at'] is None: state['metrics']['started_at']=at
            if action=='owner':
                state['owner']=event['owner']
                for t in state['tasks'].values():
                    if _occupied(t):
                        t.update(status='UNKNOWN',wait_reason='OWNER_CHANGED_RECONCILE_REQUIRED')
            elif action=='register':
                for task in event['tasks']: state['tasks'][task['task_id']]=deepcopy(task)
            elif action=='task':
                t=state['tasks'][event['task_id']];t.update(deepcopy(event['changes']))
                if t['status']=='COMMITTED':
                    state['receipts'][t['operation_id']]=t['business_receipt']
                    if t['lane']=='model' and t['kind'] in PANEL_KINDS:
                        state['metrics']['accepted_panels']+=t.get('panel_count',1)
            elif action=='health': state['model']=event['model']
            else: raise ValueError('UNKNOWN_SCHEDULER_EVENT: '+str(action))
            if action in {'owner','task'}:
                state['metrics']['inflight_curve'].append({'at':at,**dict(Counter(t['lane'] for t in state['tasks'].values() if _occupied(t)))})
        for task in state['tasks'].values():
            missing=[dep for dep in task['dependencies'] if state['tasks'].get(dep,{}).get('status')!='COMMITTED']
            if not missing:
                task['timestamps'].setdefault('ready',max([task['created_at']]+[
                    state['tasks'][dep]['timestamps']['committed'] for dep in task['dependencies']]))
            if task['status'] in {'PENDING','READY'}:
                task.update(status='PENDING' if missing else 'READY',wait_reason='DEPENDENCIES:'+','.join(missing) if missing else None)
        state['metrics']['events']=journal['revision'];self._state_cache=deepcopy(state)
        return state

    def _owner(self, state, epoch=None):
        owner=state['owner'];chosen=self.epoch if epoch is None else epoch
        if not owner or owner['token']!=self.token or owner['epoch']!=chosen or owner['identity']!=self.identity:
            raise ValueError('STALE_OWNER')
        return owner

    def _append(self, state, action, *, event_id=None, **payload):
        event={'event_id':event_id or uuid.uuid4().hex,'action':action,'at':self.clock(),**payload}
        self.journal.append(event,state['revision']);self._state_cache=None
        return self._state()

    def start_owner(self, scope=None):
        if not self.journal.meta_path.exists():self.journal.initialize(scope)
        elif scope is not None:self.journal.initialize(scope)
        state=self._state();owner=state['owner']
        if owner and owner['token']==self.token:
            self.epoch=owner['epoch'];return self.epoch
        # A lease deadline or missing response is never proof that an owner or
        # its native image request died. Unknown liveness fails closed.
        if owner and self.liveness(owner['identity']) is not False:raise ValueError('OWNER_ALIVE_OR_UNKNOWN')
        epoch=owner['epoch']+1 if owner else 1
        self._append(state,'owner',owner={'identity':self.identity,'token':self.token,'epoch':epoch})
        self.epoch=epoch;return epoch

    def _replayed(self, event_id, method, arguments):
        if event_id is None:return False
        old=next((e for e in self.journal._read()['events'] if e['event_id']==event_id),None)
        if old is None:return False
        if old.get('request')!={'method':method,'arguments':arguments}:raise ValueError('EVENT_ID_CONFLICT')
        return True

    def register(self, tasks, *, epoch=None, event_id=None):
        tasks=list(tasks);state=self._state();self._owner(state,epoch)
        if self._replayed(event_id,'register',tasks):return deepcopy(state['tasks'])
        new=[];merged=dict(state['tasks'])
        for incoming in tasks:
            task=deepcopy(incoming)
            if any(not task.get(k) for k in ('task_id','kind','scope','input_digest','input_refs')):
                raise ValueError('TASK_INPUT_REQUIRED')
            if not isinstance(task['task_id'],str) or not isinstance(task['kind'],str) or not isinstance(task['scope'],(list,dict,str)):
                raise ValueError('TASK_INPUT_INVALID')
            for ref in task['input_refs']:verify_ref(ref)
            if not isinstance(task['input_digest'],str) or len(task['input_digest'])!=64:
                raise ValueError('INPUT_DIGEST_REQUIRED')
            task.setdefault('dependencies',[]);task.setdefault('comparison_links',[]);task.setdefault('prior_image_plan',[])
            if not isinstance(task['dependencies'],list) or any(not isinstance(d,str) for d in task['dependencies']):
                raise ValueError('DEPENDENCIES_INVALID')
            lane=task.setdefault('lane','local' if task['kind'] in LOCAL_KINDS else 'image' if task['kind'] in IMAGE_KINDS else 'model')
            if lane not in {'model','local','image'}:raise ValueError('LANE_INVALID')
            task.setdefault('operation_id','preparation:'+_hash([str(self.root),task['task_id'],task['input_digest']]))
            if not isinstance(task['operation_id'],str) or not task['operation_id']:raise ValueError('OPERATION_ID_REQUIRED')
            if 'panel_count' in task and (type(task['panel_count']) is not int or task['panel_count']<0):
                raise ValueError('PANEL_COUNT_INVALID')
            definition=deepcopy(task)
            if task['task_id'] in merged:
                if merged[task['task_id']]['definition']!=definition:raise ValueError('TASK_ID_CONFLICT')
                continue
            if any(t['operation_id']==task['operation_id'] for t in merged.values()):raise ValueError('OPERATION_ID_CONFLICT')
            task.update(definition=definition,status='PENDING',owner_epoch=None,host_id=None,native_inflight=False,output_refs=[],
                        business_receipt=None,wait_reason=None,created_at=self.clock(),timestamps={})
            merged[task['task_id']]=task;new.append(task)
        visiting=set();done=set()
        def visit(key):
            if key in visiting:raise ValueError('DEPENDENCY_CYCLE')
            if key in done:return
            visiting.add(key)
            for dep in merged[key]['dependencies']:
                if dep not in merged:raise ValueError('DEPENDENCY_MISSING: '+dep)
                visit(dep)
            visiting.remove(key);done.add(key)
        for key in merged:visit(key)
        if new:state=self._append(state,'register',event_id=event_id,tasks=new,request={'method':'register','arguments':tasks})
        return deepcopy(state['tasks'])

    def claim(self, task_id, epoch=None, *, event_id=None):
        state=self._state();self._owner(state,epoch);task=state['tasks'][task_id]
        if self._replayed(event_id,'claim',[task_id]):return task
        if task['status']!='READY':raise ValueError('TASK_NOT_READY: '+task['status'])
        for ref in task['input_refs']:verify_ref(ref)
        # CAS in _change must use the same validated revision.
        return self._task_append(state,task_id,{'status':'LEASED','wait_reason':'HOST_NEEDED' if task['lane'] in {'model','image'} else None},epoch,event_id,request={'method':'claim','arguments':[task_id]})

    def _task_append(self,state,task_id,changes,epoch=None,event_id=None,request=None):
        owner=self._owner(state,epoch)
        changes={**changes,'owner_epoch':owner['epoch'],'timestamps':{**state['tasks'][task_id]['timestamps'],
                  changes.get('status','updated').lower():self.clock()}}
        return self._append(state,'task',event_id=event_id,task_id=task_id,changes=changes,request=request)['tasks'][task_id]

    def attach_host(self, task_id, host_id, *, epoch=None, operation_id=None, evidence=None, event_id=None):
        state=self._state();self._owner(state,epoch);task=state['tasks'][task_id]
        arguments=[task_id,host_id,operation_id,evidence]
        if self._replayed(event_id,'attach_host',arguments):return task
        if not isinstance(host_id,str) or not host_id:raise ValueError('HOST_ID_REQUIRED')
        if operation_id is not None and operation_id!=task['operation_id']:raise ValueError('OPERATION_ID_CONFLICT')
        if evidence is not None:verify_ref(evidence)
        if task['host_id']==host_id and task['status']=='RUNNING':return task
        if task['status']!='LEASED' or task['host_id']:raise ValueError('HOST_ALREADY_ATTACHED_OR_NOT_LEASED')
        return self._task_append(state,task_id,{'status':'RUNNING','host_id':host_id,'native_inflight':True,'host_evidence':evidence,'wait_reason':None},epoch,event_id,request={'method':'attach_host','arguments':arguments})

    def record_result(self, task_id, output_refs, *, epoch=None, event_id=None):
        state=self._state();self._owner(state,epoch);task=state['tasks'][task_id]
        arguments=[task_id,output_refs]
        replayed=self._replayed(event_id,'record_result',arguments)
        if not output_refs:raise ValueError('OUTPUT_REFS_REQUIRED')
        for ref in output_refs:verify_ref(ref)
        if replayed:return task
        if task['status'] in {'RESULT_SAVED','COMMITTED'} and task['output_refs']==output_refs:return task
        if task['status'] not in {'LEASED','RUNNING','UNKNOWN','STOPPED'} or 'leased' not in task['timestamps']:
            raise ValueError('RESULT_NOT_EXPECTED')
        # Saved late returns are retained after takeover only via the new owner.
        return self._task_append(state,task_id,{'status':'RESULT_SAVED','native_inflight':False,'output_refs':deepcopy(output_refs),
               'wait_reason':'BUSINESS_RECEIPT_REQUIRED'},epoch,event_id,request={'method':'record_result','arguments':arguments})

    def query_receipt(self, operation_id):
        receipt=self._state()['receipts'].get(operation_id)
        if receipt:
            verify_ref(receipt);return deepcopy(receipt)
        if self.receipt_query:
            found=self.receipt_query(operation_id)
            if found:verify_ref(found)
            return found
        return None

    def commit(self, task_id, business_receipt, *, epoch=None, event_id=None):
        state=self._state();self._owner(state,epoch);task=state['tasks'][task_id]
        arguments=[task_id,business_receipt]
        replayed=self._replayed(event_id,'commit',arguments)
        verify_ref(business_receipt)
        for ref in task['output_refs']:verify_ref(ref)
        body=json.loads(Path(business_receipt['path']).read_text(encoding='utf-8-sig'))
        if (body.get('task_id')!=task_id or body.get('operation_id')!=task['operation_id'] or
                body.get('status')!='COMMITTED' or body.get('output_refs')!=task['output_refs']):
            raise ValueError('BUSINESS_RECEIPT_MISMATCH')
        if self.receipt_query:
            if self.receipt_query(task['operation_id'])!=business_receipt:raise ValueError('BUSINESS_RECEIPT_NOT_IN_LEDGER')
        elif (body.get('policy')!='preparation_business_receipt_v1' or body.get('status')!='COMMITTED' or
              body.get('output_refs')!=task['output_refs']):raise ValueError('BUSINESS_RECEIPT_MISMATCH')
        if replayed:return task
        if task['status']=='COMMITTED':
            if task['business_receipt']!=business_receipt:raise ValueError('BUSINESS_RECEIPT_CONFLICT')
            return task
        if task['status']!='RESULT_SAVED':raise ValueError('RESULT_NOT_SAVED')
        return self._task_append(state,task_id,{'status':'COMMITTED','business_receipt':deepcopy(business_receipt),'wait_reason':None},epoch,event_id,request={'method':'commit','arguments':arguments})

    def reconcile(self, observations=None, *, epoch=None, health=None):
        state=self._state();self._owner(state,epoch)
        for key,observation in (observations or {}).items():
            state=self._state();task=state['tasks'][key]
            evidence=observation.get('evidence');verify_ref(evidence)
            status=observation.get('status')
            if status not in {'READY','RUNNING','UNKNOWN','BLOCKED','SUPERSEDED','STOPPED'}:raise ValueError('HOST_STATUS_INVALID')
            if observation.get('host_id',task['host_id'])!=task['host_id']:raise ValueError('HOST_ID_CONFLICT')
            if task['status'] in {'COMMITTED','RESULT_SAVED'}:raise ValueError('SAVED_RESULT_MUST_BE_PRESERVED')
            if status=='RUNNING' and not task['host_id']:raise ValueError('HOST_ID_REQUIRED')
            if status=='READY':
                if task['status']!='BLOCKED' or task['host_id'] or 'leased' in task['timestamps']:
                    raise ValueError('UNKNOWN_OR_SUBMITTED_WORK_CANNOT_BE_RESUBMITTED')
                if any(state['tasks'][dep]['status']!='COMMITTED' for dep in task['dependencies']):
                    raise ValueError('DEPENDENCIES_NOT_COMMITTED')
                for ref in task['input_refs']:verify_ref(ref)
            changes={'status':status,'observation':deepcopy(evidence),
                    'wait_reason':observation.get('wait_reason') or ('RECONCILE_REQUIRED' if status=='UNKNOWN' else status)}
            if observation.get('terminal'):
                proof=json.loads(Path(evidence['path']).read_text(encoding='utf-8-sig'))
                if (status not in {'STOPPED','BLOCKED','SUPERSEDED'} or
                        proof.get('policy')!='preparation_host_observation_v1' or
                        proof.get('task_id')!=key or proof.get('operation_id')!=task['operation_id'] or
                        not task['host_id'] or proof.get('host_id')!=task['host_id'] or
                        proof.get('status') not in {'TERMINATED','FAILED_NO_IMAGE','COMPLETED_NO_IMAGE'} or
                        proof.get('confirmed_no_image') is not True):raise ValueError('TERMINAL_HOST_PROOF_MISMATCH')
                changes.update(native_inflight=False,native_terminal_evidence=deepcopy(evidence))
            self._task_append(state,key,changes,epoch)
        if health is not None:
            state=self._state();model=deepcopy(state['model']);now=self.clock();cap=health.get('model_capacity')
            if type(cap) is not int or cap<0:raise ValueError('ACTUAL_MODEL_CAPACITY_REQUIRED')
            target=max(1,min(model['target'],max(1,cap)));accepted=state['metrics']['accepted_panels'];previous=model['last_adjust']
            bad=any(health.get(k) for k in ('pressure','backpressure','error','throttled')) or health.get('known') is False
            if bad:
                target=max(1,target//2)
                model.update(last_adjust=now,accepted_at_adjust=accepted,probe=None,baseline=None)
            elif previous is None:
                model.update(last_adjust=now,accepted_at_adjust=accepted)
            elif now-previous>=60:
                completed=accepted-model['accepted_at_adjust'];rate=completed/max(1,now-previous)
                probe=model.get('probe')
                if probe:
                    if completed>=2 and (probe['baseline'] is None or rate>=probe['baseline']*1.05):
                        model.update(probe=None,baseline=rate,last_adjust=now,accepted_at_adjust=accepted)
                    elif now-previous>=180 or completed>=2:
                        target=min(target,probe['prior']);model.update(probe=None,last_adjust=now,accepted_at_adjust=accepted,baseline=rate)
                elif completed>0 and target<cap:
                    model.update(probe={'prior':target,'baseline':model.get('baseline')},last_adjust=now,accepted_at_adjust=accepted)
                    target+=1
                # No actual acceptance means no fabricated throughput or gain.
            model['target']=target
            self._append(state,'health',model=model,health=deepcopy(health))
        return self.status()

    def _capacities(self, capacities, state):
        capacities=capacities or {};actual=capacities.get('model',0)
        if type(actual) is not int or actual<0:raise ValueError('ACTUAL_MODEL_CAPACITY_REQUIRED')
        view=capacities.get('coordinator')
        # Never create an alternate local/image controller or mutate one during
        # status/plan. Callers can supply a fresh view from actual admission.
        if view is None and self.coordinator is not None:
            path=getattr(self.coordinator,'path',None)
            if path and Path(path).exists():
                ledger=json.loads(Path(path).read_text())
                view={'limits':ledger.get('adaptive_limits_v2',ledger.get('limits',{})),
                      'active':{kind:sum(l.get('units',1) for l in ledger.get('leases',{}).values() if l['kind']==kind) for kind in ('compile','image')}}
        view=view or {};limits=view.get('limits',{});active=view.get('active',{})
        model=min(actual,state['model']['target'])
        return {'model':max(0,model-sum(t['lane']=='model' and _occupied(t) for t in state['tasks'].values())),
                'local':max(0,limits.get('compile',0)-active.get('compile',0)),
                'image':max(0,limits.get('image',0)-active.get('image',0))}

    def plan(self, capacities=None):
        state=self._state();lanes=self._capacities(capacities,state);remaining=dict(lanes)
        ready=[t for t in state['tasks'].values() if t['status']=='READY']
        dependents=Counter(d for t in state['tasks'].values() if t['status']!='COMMITTED' for d in t['dependencies'])
        children=defaultdict(list)
        for task in state['tasks'].values():
            if task['status'] not in {'COMMITTED','SUPERSEDED','STOPPED'}:
                for dep in task['dependencies']:children[dep].append(task['task_id'])
        depths={}
        def depth(key):
            if key not in depths:depths[key]=max((1+depth(child) for child in children[key]),default=0)
            return depths[key]
        now=self.clock()
        def score(task):
            priority=100 if task['kind'] in RECOVERY_KINDS else 50 if task['kind'] in SHARED_KINDS else 25 if task['kind'] in FINISH_KINDS else 0
            return priority+min(100,(now-task['created_at'])/60)+dependents[task['task_id']]*5+depth(task['task_id'])*5+task.get('priority',0)
        def tier(task):
            base=0 if task['kind'] in RECOVERY_KINDS else 1 if task['kind'] in SHARED_KINDS or dependents[task['task_id']] else 2 if task['kind'] in FINISH_KINDS else 3
            return max(0,base-int(max(0,now-task['created_at'])/600))
        groups=defaultdict(list)
        for t in ready:
            scope=t['scope'];episode=scope[:2] if isinstance(scope,list) else scope
            groups[_hash(episode)].append(t)
        for group in groups.values():group.sort(key=lambda t:(tier(t),-score(t),t['created_at'],t['task_id']))
        selected=[];rounds=Counter()
        for task in state['tasks'].values():
            if 'leased' in task['timestamps']:
                scope=task['scope'];episode=scope[:2] if isinstance(scope,list) else scope
                rounds[_hash(episode)]+=1
        while groups:
            candidates=[(key,tasks[0]) for key,tasks in groups.items() if remaining[tasks[0]['lane']]>0]
            if not candidates:
                # A blocked lane must not hide another lane in the same episode.
                for key in list(groups):
                    groups[key]=[t for t in groups[key] if remaining[t['lane']]>0]
                    if not groups[key]:del groups[key]
                if not groups:break
                continue
            key,t=min(candidates,key=lambda pair:(tier(pair[1]),rounds[pair[0]],-score(pair[1]),pair[1]['created_at'],pair[1]['task_id']))
            selected.append(t);remaining[t['lane']]-=1;rounds[key]+=1
            groups[key].pop(0)
            if not groups[key]:del groups[key]
        return {'policy':POLICY,'revision':state['revision'],'owner_epoch':state['owner']['epoch'] if state['owner'] else None,
                'lanes':lanes,'ready':deepcopy(selected),
                'host_needed':[t['task_id'] for t in state['tasks'].values() if t['status']=='LEASED' and t['wait_reason']=='HOST_NEEDED'],
                'reconcile_required':[t['task_id'] for t in state['tasks'].values() if t['status']=='UNKNOWN'],
                'saved_results':[t['task_id'] for t in state['tasks'].values() if t['status']=='RESULT_SAVED']}

    def status(self):
        state=self._state();now=self.clock();metrics=state['metrics'];start=metrics['started_at']
        metrics['wall_seconds']=max(0,now-start) if start is not None else None
        metrics['accepted_panels_per_second']=metrics['accepted_panels']/max(1,now-start) if start is not None else None
        metrics['status_counts']=dict(Counter(t['status'] for t in state['tasks'].values()))
        metrics['journal_io']=dict(self.journal.metrics)
        metrics['dispatch_gaps']=[{'task_id':t['task_id'],'lane':t['lane'],
            'ready_at':t['timestamps']['ready'],'leased_at':t['timestamps']['leased'],
            'seconds':max(0,t['timestamps']['leased']-t['timestamps']['ready'])}
            for t in state['tasks'].values() if 'ready' in t['timestamps'] and 'leased' in t['timestamps']]
        metrics['native_inflight']={lane:sum(t['lane']==lane and t.get('native_inflight',False) for t in state['tasks'].values()) for lane in ('model','local','image')}
        metrics['service_image_seconds']=None
        return state
