"""Content-bound prepared inputs; no service authority or capacity in this store."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from contextvars import Context
import copy, errno, hashlib, json, os, pickle, tempfile, threading, time
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime, timezone
from codex_reference_contract import read_json, checked_file, digest, file_session, export_read_set
from submission_contract import fingerprint
from platform_io import atomic_json

POLICY='prepared_input_v1'
DISPATCH='prepared_dispatch_v1'
_PROGRESS={'panels','dispatch_ledger','submission_registrations','runtime_operations','reservation_requests',
           'batch_reviews','delivery_review','state_reviews','cross_episode_review','runtime_execution_context',
           'parallel_context','watchdog','runtime_import','repair_authorizations','episode_diagnoses',
           'authority_revision','no_image_recoveries','unknown_resolutions','holds','qa_revision_history','delivery_materials','delivery_review_history'}
_STORES={}
_STORE_LOCK=threading.RLock()


def state_basis(state):
    # Unknown fields remain input-affecting, never silently exempted.
    return fingerprint({k:v for k,v in state.items() if k not in _PROGRESS})


def stamp(path):
    st=Path(path).stat()
    return (str(Path(path).resolve()),st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)


def proof(memo, state_path):
    value=export_read_set(memo)
    # PreparedStore explicitly replays projected source observations below.
    # Other read-set consumers retain their original strict policy.
    from codex_reference_contract import _READ_VIEW
    if memo.get('source_views') and _READ_VIEW.get() is None:value['reusable']=True
    value['files']=[r for r in value['files'] if Path(r['path']).resolve()!=Path(state_path).resolve() and Path(r['path']).name not in {'runtime-clock.json','clock-session.json'}]
    return value


_WORKER_POOL=None
_WORKER_INPUTS=None
_WORKER_SHARED=None

def _initialize_prepare_worker(snapshot_path,expected_digest,resource_home=None,resource_token=None):
    """One batch snapshot per spawned interpreter, rather than per panel."""
    global _WORKER_INPUTS, _WORKER_POOL, _WORKER_SHARED
    if resource_token:
        from machine_resources import Coordinator
        Coordinator(home=resource_home).attach_worker(resource_token)
    raw=Path(snapshot_path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_digest:raise ValueError('PREPARE_SNAPSHOT_CHANGED')
    # Only our private, digest-verified parent snapshot is deserialized here.
    # Preserve aliases/types from the previous multiprocessing pickle contract.
    payload=pickle.loads(raw)
    _WORKER_SHARED=payload[7] if len(payload)>7 else {}
    _WORKER_INPUTS=pickle.dumps(payload[:7],protocol=pickle.HIGHEST_PROTOCOL)
    _WORKER_POOL=None

def _prepare_panel(pid):
    """Process worker: isolated interpreter/cache, no state writes or service calls."""
    global _WORKER_POOL
    from validation_pool import ValidationPool,session
    from authority_updates import authority_context
    from source_input_contract import strict_reads
    from runtime_pipeline import budget
    from production_evidence import input_errors
    from production_runtime import package_review_errors
    from codex_reference_contract import validate_panel
    from handoff_delivery import local_execution_view
    # Preserve per-task object isolation using the cached bytes. In-process
    # unpickling avoids Python deepcopy walks and repeats no parent IPC/file I/O.
    state,original,root,batch,shots,basis,records=pickle.loads(_WORKER_INPUTS)
    record,shot=records[pid],shots[pid]
    root=Path(root)
    if _WORKER_POOL is None:_WORKER_POOL=ValidationPool()
    with budget(root/'00_输入审计/生产流程.json',enabled=True),session(_WORKER_POOL),authority_context(state,root),file_session() as memo:
        from codex_reference_contract import verify_read_snapshot
        for key,items in (_WORKER_SHARED or {}).items():
            values=copy.deepcopy(items)
            if key=='derived':
                from audit_cache import freeze
                values={k:(freeze(v[0]),v[1]) for k,v in values.items()}
            memo[key].update(values)
        verify_read_snapshot(memo)
        # Preparation has no dispatch authority even when an owner is already assigned.
        input_view={k:v for k,v in state.items() if k!='parallel_context'}
        errors=input_errors(input_view,root,record,shot,basis,records,candidate=True,preparation_only=True)
        errors.extend(package_review_errors(original,root,batch,record))
        path=checked_file(root,record['package_manifest']);packet=read_json(path)
        if packet.get('round_context')!={'batch_id':batch['batch_id'],'round_id':record['round_id'],'attempt_id':record['attempt_id']}:
            errors.append('PREPARED_ROUND_CONTEXT_CHANGED')
        if record['round_id']==1 and packet['panels'][0].get('operation')=='repair':errors.append('FIRST_ROUND_REPAIR_NOT_ALLOWED')
        if record['round_id']==2:
            auth=read_json(checked_file(root,original['repair_authorizations'][pid]))
            if record['status']!='REPAIR_AUTHORIZED' or packet['panels'][0].get('operation')!='repair' or any(c not in packet['panels'][0].get('prompt','') for c in auth['repair_constraints']):
                errors.append('PREPARED_REPAIR_AUTHORITY_CHANGED')
        technical,submission=validate_panel(packet['panels'][0],path.parent);errors.extend(technical)
        from visual_evidence import production_background_errors
        errors.extend(production_background_errors(packet['panels'][0],(submission or {}).get('arguments',{}).get('prompt')))
        data=None
        if not errors and submission is not None:
            bound,binding=local_execution_view(state,root,packet,path.parent)
            from production_runtime import package_signature_from_submission
            data={'packet':bound,'binding':binding,'submission':submission,
                  'package_signature':package_signature_from_submission(packet,path.parent,submission)}
        reads=proof(memo,root/'00_输入审计/生产流程.json')
    from machine_resources import MiB
    try:
        import resource,sys
        peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
    except (ImportError,AttributeError):peak=256*MiB
    return pid,record,data,reads,{'panel_id':pid,'status':'HOLD' if errors or data is None else 'PASS','errors':errors,'worker_peak_bytes':peak}


def worker_count(requested,total):
    if requested!='all' and (type(requested) is not int or requested<1):raise ValueError('workers must be all or positive integer')
    count=min(total,total if requested=='all' else requested)
    return min(count,61) if os.name=='nt' else count


def resource_error(exc):
    return (isinstance(exc,MemoryError) or isinstance(exc,OSError) and exc.errno in {errno.ENOMEM,errno.EAGAIN,errno.EMFILE,errno.ENFILE}
            or isinstance(exc,RuntimeError) and "can't start new thread" in str(exc))


def parallel_checks(selection,eligible,original,state,root,batch,shots,basis,records,sink,workers):
    from codex_reference_contract import _FILE_SESSION, verify_read_snapshot
    common=proof(_FILE_SESSION.get(),Path(root)/'00_输入审计/生产流程.json')
    verify_read_snapshot(_FILE_SESSION.get())
    reports=[];todo=[]
    for pid in selection:
        if pid in eligible:todo.append(pid)
        else:reports.append({'panel_id':pid,'status':'HOLD','errors':['DEPENDENCY_OR_SCOPE_NOT_READY']})
    count=worker_count(workers,len(todo))
    started=time.monotonic();first_ready=None;peak=0;fallbacks=[];actual_workers=0;resource_wait=0
    from machine_resources import Coordinator
    resources=Coordinator()
    from runtime_clock import require_running
    clock=require_running(Path(root)/'00_输入审计/生产流程.json')
    if clock:resources.observe_run(str(Path(root)),clock.get('active_segment'))
    resource_key=str(Path(root).resolve())+' / '+str(threading.get_ident())
    import multiprocessing
    snapshot_bytes=0
    if count:
        with tempfile.TemporaryDirectory(prefix='comic-compile-') as folder:
            memo=_FILE_SESSION.get();names={r['path'] for r in common['files']}
            shared={key:{k:v for k,v in memo.get(key,{}).items() if
                (k[0] if key=='json' else v if key=='paths' else k) in names}
                for key in ('files','bytes','json','paths')}
            # Carry only facts whose complete dependency closure is in this immutable snapshot.
            def transferable(deps):
                return all(isinstance(d,str) and memo['paths'].get(d,d) in names for d in deps)
            shared['derived']={k:copy.deepcopy(v) for k,v in memo.get('derived',{}).items() if transferable(v[1])}
            shared['validations']={k:v for k,v in memo.get('validations',{}).items() if transferable(memo['validation_dependencies'][k])}
            shared['validation_dependencies']={k:memo['validation_dependencies'][k] for k in shared['validations']}
            raw=pickle.dumps((state,original,str(root),batch,shots,basis,records,shared),protocol=pickle.HIGHEST_PROTOCOL)
            snapshot=Path(folder)/'inputs.pickle';snapshot.write_bytes(raw);snapshot_bytes=len(raw)
            snapshot_digest=hashlib.sha256(raw).hexdigest()
            remaining=list(todo);done=set();effective=count
            while remaining:
                waiting_at=time.monotonic()
                while True:
                    permit=resources.acquire('compile',resource_key,min(effective,len(remaining)),disk=root,estimated_bytes=128*1024**2+4*snapshot_bytes)
                    if permit['status']=='RESOURCE_GRANTED':break
                    # Check the existing active runtime budget while waiting; no
                    # new clock and no child process exists before admission.
                    from runtime_clock import require_step
                    require_step(Path(root)/'00_输入审计/生产流程.json','prepare-inputs')
                    time.sleep(permit['retry_after_ms']/1000)
                resource_wait+=time.monotonic()-waiting_at
                allocated=permit['units'];actual_workers=max(actual_workers,allocated)
                pending={};retry=[];resource_failure=None;draining=False;resource_resize=False
                try:
                    with ProcessPoolExecutor(max_workers=allocated,mp_context=multiprocessing.get_context('spawn'),
                            initializer=_initialize_prepare_worker,initargs=(str(snapshot),snapshot_digest,str(resources.home),permit['token'])) as pool:
                        waiting=list(remaining)
                        def fill():
                            nonlocal peak
                            while waiting and not draining and len(pending)<allocated:
                                pid=waiting.pop(0)
                                try:pending[pool.submit(_prepare_panel,pid)]=pid
                                except BaseException:
                                    waiting.insert(0,pid);raise
                            peak=max(peak,len(pending))
                        fill()
                        while pending:
                            completed,_=wait(pending,timeout=1,return_when=FIRST_COMPLETED)
                            pressure=resources.progress(permit['token'])
                            if pressure['drain']:
                                draining=True;resource_resize=True
                            for future in completed:
                                expected=pending.pop(future)
                                try:
                                    pid,row,data,reads,report=future.result()
                                    if pid!=expected:raise ValueError('PREPARED_WORKER_PANEL_MISMATCH')
                                    if data is not None and sink:
                                        sink(pid,row,data,common,reads)
                                        if first_ready is None:first_ready=time.monotonic()-started
                                    reports.append(report);done.add(pid)
                                    resources.progress(permit['token'],completed=1,worker_bytes=report.get('worker_peak_bytes',0))
                                except (MemoryError,BrokenProcessPool,OSError) as exc:
                                    if not resource_error(exc):raise
                                    retry.append(expected);resource_failure=exc
                                except (ValueError,KeyError,TypeError) as exc:
                                    reports.append({'panel_id':expected,'status':'HOLD','errors':[str(exc)]});done.add(expected)
                            if resource_failure:
                                # Drain successful in-flight work before rebuilding a smaller pool.
                                continue
                            fill()
                        remaining=[pid for pid in todo if pid not in done]
                except (MemoryError,BrokenProcessPool,OSError,RuntimeError) as exc:
                    if not resource_error(exc):raise
                    resource_failure=exc
                    # Futures that succeeded during executor shutdown are preserved.
                    for future,expected in pending.items():
                        if future.done() and not future.cancelled() and future.exception() is None:
                            pid,row,data,reads,report=future.result()
                            if data is not None and sink:sink(pid,row,data,common,reads)
                            reports.append(report);done.add(pid)
                    remaining=[pid for pid in todo if pid not in done]
                finally:
                    resources.release(permit['token']) # Pool has drained/exited before its memory permit is returned.
                if remaining:
                    if not resource_failure:
                        if resource_resize:continue
                        raise RuntimeError('PREPARE_UNACCOUNTED_TASKS')
                    if allocated==1:raise resource_failure
                    fallbacks.append({'from':allocated,'to':max(1,allocated//2),'reason':str(resource_failure)})
                    resources.resource_failure('compile',allocated,str(resource_failure))
                    # The fallback is temporary shared feedback, never a permanent
                    # smaller workers request. Healthy admission may probe upward.
                    effective=count
    byid={r['panel_id']:r for r in reports};reports=[byid[p] for p in selection]
    ready=[r['panel_id'] for r in reports if r['status']=='PASS']
    return {'status':'READY' if len(ready)==len(selection) and ready else 'PARTIAL_READY' if ready else 'HOLD',
            'ready_panel_ids':ready,'reports':reports,'image_calls':0,'dispatch_authorized':False,
            'compilation':{'workers':actual_workers,'requested_workers':count,'machine_resource_policy':'machine_resource_admission_v1','resource_wait_seconds':resource_wait,'submitted':len(todo),'peak_pending':peak,
                'first_published_seconds':first_ready,'elapsed_seconds':time.monotonic()-started,
                'task_payload':'panel_id','shared_snapshot_per_worker':True,
                'snapshot_bytes':snapshot_bytes,'snapshot_transport':'private_local_file',
                'resource_fallbacks':fallbacks,'shared_verified_files':len(common['files'])}}


class PreparedStore:
    def __init__(self,state_path):
        self.path=Path(state_path).resolve();self.root=self.path.parent.parent
        self.folder=self.path.parent/'prepared_inputs';self.lock=threading.RLock()
        self.changed=threading.Condition(self.lock);self.revision=0
        self.entries={};self.verified={};self.directory_guards={};self.ready={};self.preparing=False;self.preparation_started=False;self.preparation_error=None;self.last_reports=[];self.scanned={};self.refreshed={}
        self.source_guards={}
        self.statistics={'prepared':0,'reused':0,'hash_bytes':0,'hash_reads':0,'record_reads':0,'scope_refreshes':0}

    def notify_change(self):
        with self.changed:
            self.revision+=1;self.changed.notify_all()

    def wait_for_change(self,revision,timeout):
        if type(revision) is not int or revision<0 or not isinstance(timeout,(int,float)) or not 0<timeout<=2:
            raise ValueError('PREPARED_WAIT_INVALID')
        with self.changed:
            self.changed.wait_for(lambda:self.revision!=revision,timeout=timeout)
            return {'status':'PREPARED_CHANGE','revision':self.revision,'changed':self.revision!=revision}

    def verify_files(self,reads):
        # Restart rehashes all content once; live reuse checks inode/change stamps.
        # Every referenced file is content-bound; no serialized PASS is trusted.
        if reads.get('policy')!='receiver_read_set_v1' or not reads.get('reusable'):
            raise ValueError('PREPARED_READ_SET_NOT_REUSABLE')
        for item in reads['files']:
            path=Path(item['path']);current=stamp(path);key=(str(path),item['sha256'])
            with self.lock:known=self.verified.get(key)
            if known!=current:
                actual=digest(path)
                if actual!=item['sha256'] or stamp(path)!=current:raise ValueError('PREPARED_INPUT_CHANGED:'+str(path))
                with self.lock:
                    self.verified[key]=current;self.statistics['hash_reads']+=1;self.statistics['hash_bytes']+=current[3]
        # Recheck non-directory path identities and absence, never walk the package.
        # Directory observations are input-dependent and rechecked on preparation.
        from codex_reference_contract import recheck_dependencies, _observe
        with file_session():
            for kind,path,options,value in reads['observations']:
                if kind=='directory':
                    guard_key=fingerprint([path,options,value])
                    with self.lock:guards=self.directory_guards.get(guard_key)
                    if guards is not None and all(stamp(p)==s for p,s in guards.items()):continue
                    # The directory query membership may invalidate a proof.
                    from codex_reference_contract import scan_directory, _FILE_SESSION
                    recursive,suffixes,parts,names,extensions,paths=options
                    scan_directory(path,recursive=recursive,suffixes=tuple(suffixes),excluded_parts=tuple(parts),excluded_names=tuple(names),excluded_suffixes=tuple(extensions),excluded_paths=tuple(paths))
                    key=(kind,path,(recursive,tuple(suffixes),tuple(parts),tuple(names),tuple(extensions),tuple(paths)))
                    if json.dumps(_FILE_SESSION.get()['observations'][key],sort_keys=True)!=json.dumps(value,sort_keys=True):raise ValueError('PREPARED_DIRECTORY_CHANGED')
                    dirs=[Path(path)] + ([p for p in Path(path).rglob('*') if p.is_dir()] if recursive else [])
                    with self.lock:self.directory_guards[guard_key]={str(p):stamp(p) for p in dirs}
                elif kind=='source_inputs':
                    token=(kind,path,tuple(options));_observe(kind,path,value,tuple(options));recheck_dependencies([token])
                    with self.lock:self.source_guards[(path,tuple(options),value)]=stamp(path)
                else:
                    token=(kind,path,tuple(options));_observe(kind,path,value,tuple(options));recheck_dependencies([token])

    def put(self,state,pid,row,data,common,reads):
        arguments=data['submission']['arguments']
        semantic={**arguments,'referenced_image_paths':[digest(Path(p)) for p in arguments.get('referenced_image_paths',[])]}
        panel=data['packet']['panels'][0]
        semantic['output_spec']=panel.get('output_spec')
        identity={'policy':POLICY,'book_id':state['book_id'],'episode_id':state['episode_id'],'panel_id':pid,
                  'source_panel_id':row.get('source_panel_id'),'semantic_input_digest':fingerprint(semantic),
                  'compiler_digest':fingerprint(state.get('toolchain')),'package_manifest':row['package_manifest']}
        key=fingerprint({k:v for k,v in identity.items() if k!='package_manifest'})
        value={**identity,'prepared_input_id':key,'state_basis':state_basis(state),'arguments':arguments,
               'attempt_id':row['attempt_id'],'round_id':row['round_id'],
               'ready_at':datetime.now(timezone.utc).isoformat(),
               'packet':data['packet'],'binding':data['binding'],'submission_plan':data['submission'],
               'dependencies':{p:next(r for r in state['panels'] if r['panel_id']==p).get('output') for p in panel.get('generation_dependencies',[])},
               'common_reads':common,'panel_reads':reads,'dispatch_authorized':False,
               'scheduling_rows':[{k:p.get(k) for k in ('panel_id','generation_dependencies','visual_state_keys')}
                    for p in read_json(checked_file(self.root,state['shot_manifest']))['panels']]}
        from prepared_scope import POLICY as SCOPE, shared_basis, snapshot
        value.update(scope_policy=SCOPE, shared_basis=shared_basis(state),
                     scope_snapshot=snapshot(state,self.root,pid), package_signature=data['package_signature'])
        # Content-address the complete proof too: source/review revisions never overwrite old evidence.
        value['record_digest']=fingerprint(value)
        name=self.folder/(value['record_digest']+'.json');self.folder.mkdir(parents=True,exist_ok=True)
        atomic_json(name,value)
        self.verify_files(common);self.verify_files(reads)
        with self.lock:
            self.entries[value['record_digest']]=value;self.ready[pid]=value['record_digest'];self.statistics['prepared']+=1
            self.notify_change()
        return self.ref(value)

    def ref(self,value):
        return {'policy':DISPATCH,'prepared_input_id':value['prepared_input_id'],'record_digest':value['record_digest'],
                'panel_id':value['panel_id'],'book_id':value['book_id'],'episode_id':value['episode_id'],
                'job_id':value['episode_id'],'attempt_id':value['attempt_id'],'batch_id':'EPISODE','round_id':value['round_id'],'kind':'panel',
                **({'ready_at':value['ready_at']} if value.get('ready_at') else {})}

    def get(self,reference,state=None, *, check_inputs=True, check_state=True):
        key=reference['record_digest']
        if len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise ValueError('PREPARED_REFERENCE_INVALID')
        with self.lock:value=self.entries.get(key)
        if value is None:
            value=read_json(self.folder/(key+'.json'))
            if value.get('record_digest')!=key or fingerprint({k:v for k,v in value.items() if k!='record_digest'})!=key:raise ValueError('PREPARED_RECORD_CHANGED')
        if value['prepared_input_id']!=reference['prepared_input_id']:raise ValueError('PREPARED_ID_CHANGED')
        if check_inputs:
            self.verify_files(value['common_reads']);self.verify_files(value['panel_reads'])
        if not check_state:return copy.deepcopy(value)
        state=state or read_json(self.path)
        guard = None
        if value['state_basis']!=state_basis(state):
            from prepared_scope import POLICY as SCOPE, refresh
            if value.get('scope_policy') != SCOPE:
                raise ValueError('PREPARED_AUTHORITY_OR_INPUT_CHANGED: prepare affected inputs again')
            token=(key,state_basis(state))
            with self.lock:guard=self.refreshed.get(token)
            if guard is None:
                with file_session() as memo:
                    scheduling=refresh(state,self.root,value)
                    reads=proof(memo,self.path)
                self.verify_files(reads)
                guard={'state_basis':token[1],'reads':reads,'scheduling_rows':scheduling}
                with self.lock:
                    self.refreshed[token]=guard;self.statistics['scope_refreshes']+=1
            else:self.verify_files(guard['reads'])
        row=next(r for r in state['panels'] if r['panel_id']==value['panel_id'])
        if any(row.get(k)!=value.get(k) for k in ('attempt_id','round_id')):raise ValueError('PREPARED_ATTEMPT_CHANGED')
        if row['status'] in {'PENDING','REPAIR_AUTHORIZED'} and row['package_manifest']!=value['package_manifest']:raise ValueError('PREPARED_PACKAGE_CHANGED')
        for pid,output in value['dependencies'].items():
            actual=next(r for r in state['panels'] if r['panel_id']==pid)
            if actual.get('output')!=output or actual['status'] not in {'VISUAL_PASS','USER_ACCEPTED'}:raise ValueError('PREPARED_DEPENDENCY_CHANGED:'+pid)
        with self.lock:self.entries[key]=value
        result=copy.deepcopy(value)
        if guard is not None:result['_current_guard']=copy.deepcopy(guard)
        return result

    def assert_unchanged(self,value):
        # Short-lock stamps only. Hashing/compiling already completed outside the lock.
        for reads in (value['common_reads'],value['panel_reads'],value.get('_current_guard',{}).get('reads',{'files':[]})):
            for item in reads['files']:
                key=(item['path'],item['sha256'])
                if self.verified.get(key)!=stamp(item['path']):raise ValueError('PREPARED_INPUT_CHANGED_BEFORE_COMMIT')
            for kind,path,options,value in reads.get('observations',[]):
                if kind=='source_inputs' and self.source_guards.get((path,tuple(options),value))!=stamp(path):
                    raise ValueError('PREPARED_SOURCE_CHANGED_BEFORE_COMMIT')

    def rebind_retry(self,reference,state):
        """Bind a proven no-image technical retry to unchanged compiled content."""
        value=self.get(reference,check_state=False)
        self.verify_files(value['common_reads']);self.verify_files(value['panel_reads'])
        row=next(r for r in state['panels'] if r['panel_id']==value['panel_id'])
        if row.get('status') not in {'PENDING','REPAIR_AUTHORIZED'} or row.get('round_id')!=value['round_id']:
            raise ValueError('PREPARED_RETRY_NOT_READY')
        history=row.get('no_image_history',[])
        if not history or history[-1].get('new_attempt_id')!=row['attempt_id']:
            raise ValueError('PREPARED_RETRY_PROOF_MISSING')
        original=history[-1].get('original_attempt',{})
        if original.get('attempt_id')!=value['attempt_id'] or original.get('package_manifest')!=value['package_manifest']:
            raise ValueError('PREPARED_RETRY_SOURCE_CHANGED')
        from no_image_recovery import history_errors
        errors=history_errors(state,self.root,row)
        if errors:raise ValueError(';'.join(errors))
        old_path=checked_file(self.root,value['package_manifest']);new_path=checked_file(self.root,row['package_manifest'])
        if old_path.parent!=new_path.parent:raise ValueError('PREPARED_RETRY_ROOT_CHANGED')
        old=read_json(old_path);new=read_json(new_path)
        def content(packet):
            packet=copy.deepcopy(packet);packet.pop('dispatch_receipt',None);packet.pop('dispatch_source_package',None)
            packet.get('round_context',{}).pop('attempt_id',None)
            packet['panels'][0].pop('generation_execution',None)
            return packet
        if content(old)!=content(new):raise ValueError('PREPARED_RETRY_CONTENT_CHANGED')
        from prepared_scope import refresh
        with file_session() as memo:
            scheduling=refresh(state,self.root,value)
            reads=proof(memo,self.path)
        self.verify_files(reads)
        bound=copy.deepcopy(value);bound['attempt_id']=row['attempt_id'];bound['package_manifest']=copy.deepcopy(row['package_manifest'])
        bound['packet']['round_context']=copy.deepcopy(new['round_context'])
        bound['packet']['panels'][0]['generation_execution']=copy.deepcopy(new['panels'][0]['generation_execution'])
        bound['scheduling_rows']=scheduling;bound['state_basis']=state_basis(state)
        bound['panel_reads']=copy.deepcopy(bound['panel_reads'])
        bound['panel_reads']['files'].append({'path':str(new_path),'sha256':row['package_manifest']['sha256']})
        # Current authority reads are part of the new immutable proof.
        bound['common_reads']=copy.deepcopy(bound['common_reads'])
        for field in ('files','observations'):
            bound['common_reads'][field].extend(r for r in reads[field] if r not in bound['common_reads'][field])
        bound.pop('record_digest',None);bound['record_digest']=fingerprint(bound)
        self.folder.mkdir(parents=True,exist_ok=True);atomic_json(self.folder/(bound['record_digest']+'.json'),bound)
        self.verify_files(bound['common_reads']);self.verify_files(bound['panel_reads'])
        with self.lock:
            self.entries[bound['record_digest']]=bound;self.ready[row['panel_id']]=bound['record_digest'];self.notify_change()
        return self.ref(bound)

    def prepare(self,panel_ids=None,workers='all'):
        # Announce preparation before cache discovery, which can itself be slow.
        # A previous completed batch must not make a new batch look finished.
        with self.lock:
            if self.preparing:raise ValueError('PREPARATION_ALREADY_RUNNING')
            self.preparing=True;self.preparation_started=True;self.preparation_error=None;self.last_reports=[];self.notify_change()
        try:return self._prepare(panel_ids,workers)
        except Exception as exc:
            with self.lock:self.preparation_error=str(exc)
            raise
        finally:
            with self.lock:self.preparing=False;self.notify_change()

    def _prepare(self,panel_ids=None,workers='all'):
        from scoped_episode_workflow import _evaluate_episode
        from panel_readiness import review_context
        from authority_updates import authority_context
        from source_input_contract import strict_reads
        from validation_pool import ValidationPool,session
        state=read_json(self.path)
        if state.get('execution_mode')!='episode_async_v1' or state.get('dispatch_consistency'):raise ValueError('PREPARED_SCOPE_UNSUPPORTED')
        ids=panel_ids or [r['panel_id'] for r in state['panels'] if r['status'] in {'PENDING','REPAIR_AUTHORIZED'}]
        if not isinstance(ids,list) or len(set(ids))!=len(ids):raise ValueError('PREPARED_PANEL_IDS_INVALID')
        reusable=[];pending=[];invalidations=[]
        # Cold start reads immutable records once. A live worker does not
        # reparse every historical proof on every scoped preparation call.
        if self.folder.exists():
            for path in sorted(self.folder.glob('*.json')):
                before=stamp(path)
                if self.scanned.get(str(path))==before:continue
                try:
                    v=read_json(path);self.statistics['record_reads']+=1
                    if stamp(path)!=before:raise ValueError('PREPARED_RECORD_CHANGED_DURING_READ')
                    if v['panel_id'] in ids:
                        try:self.get(self.ref(v),state);self.ready[v['panel_id']]=v['record_digest']
                        except ValueError as exc:
                            if str(exc)!='PREPARED_ATTEMPT_CHANGED':raise
                            self.rebind_retry(self.ref(v),state)
                        self.scanned[str(path)]=before
                except (OSError,ValueError,KeyError,TypeError,StopIteration) as exc:
                    invalidations.append({'record':path.name,'reason':str(exc)})
        for pid in ids:
            try:
                with self.lock:key=self.ready[pid];v=self.entries[key]
                self.get(self.ref(v),state);reusable.append(pid)
            except (OSError,ValueError,KeyError,TypeError,StopIteration) as exc:
                pending.append(pid)
                invalidations.append({'panel_id':pid,'reason':str(exc) if not isinstance(exc,KeyError) else 'NO_REUSABLE_PREPARED_INPUT'})
        started=time.monotonic()
        if pending:
            with session(ValidationPool()),authority_context(state,self.root),file_session():
                with review_context(state,self.root,False):
                    report=_evaluate_episode(state,self.root,'prepare_batch',pending,
                        prepared_sink=lambda pid,row,data,common,reads:self.put(state,pid,row,data,common,reads),workers=workers)
        else:report={'status':'READY','ready_panel_ids':[],'reports':[]}
        ready=reusable+report.get('ready_panel_ids',[])
        with self.lock:
            refs=[self.ref(self.entries[self.ready[p]]) for p in ids if p in ready]
            self.statistics['reused']+=len(reusable)
            self.last_reports=report.get('reports',[])
        return {**report,'status':'READY' if len(refs)==len(ids) and ids else 'PARTIAL_READY' if refs else 'HOLD',
                'invalidations':invalidations,'jobs':refs,'ready_panel_ids':[r['panel_id'] for r in refs],'reused_panel_ids':reusable,
                'prepare_seconds':time.monotonic()-started,'statistics':dict(self.statistics),'image_calls':0,'dispatch_authorized':False}


def store(state_path):
    key=str(Path(state_path).resolve())
    with _STORE_LOCK:
        if key not in _STORES:_STORES[key]=PreparedStore(key)
        return _STORES[key]
