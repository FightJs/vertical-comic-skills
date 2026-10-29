"""Content-bound prepared inputs; no service authority or capacity in this store."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextvars import Context
import copy, json, threading, time
from codex_reference_contract import read_json, checked_file, digest, file_session, export_read_set
from submission_contract import fingerprint
from platform_io import atomic_json

POLICY='prepared_input_v1'
DISPATCH='prepared_dispatch_v1'
_PROGRESS={'panels','dispatch_ledger','submission_registrations','runtime_operations','reservation_requests',
           'batch_reviews','delivery_review','state_reviews','cross_episode_review','runtime_execution_context',
           'parallel_context','watchdog','runtime_import','repair_authorizations','episode_diagnoses',
           'no_image_recoveries','unknown_resolutions','holds','qa_revision_history','delivery_materials','delivery_review_history'}
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
    value['files']=[r for r in value['files'] if Path(r['path']).resolve()!=Path(state_path).resolve() and Path(r['path']).name not in {'runtime-clock.json','clock-session.json'}]
    return value


_WORKER_POOL=None

def _prepare_panel(task):
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
    pid,state,original,root,batch,record,shot,basis,records=task
    root=Path(root)
    if _WORKER_POOL is None:_WORKER_POOL=ValidationPool()
    with budget(root/'00_输入审计/生产流程.json',enabled=True),session(_WORKER_POOL),strict_reads(),authority_context(state,root),file_session() as memo:
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
        data=None
        if not errors and submission is not None:
            bound,binding=local_execution_view(state,root,packet,path.parent)
            data={'packet':bound,'binding':binding,'submission':submission}
        reads=proof(memo,root/'00_输入审计/生产流程.json')
    return pid,record,data,reads,{'panel_id':pid,'status':'HOLD' if errors or data is None else 'PASS','errors':errors}


def parallel_checks(selection,eligible,original,state,root,batch,shots,basis,records,sink,workers):
    from codex_reference_contract import _FILE_SESSION, verify_read_snapshot
    common=proof(_FILE_SESSION.get(),Path(root)/'00_输入审计/生产流程.json')
    verify_read_snapshot(_FILE_SESSION.get())
    reports=[]
    # Spawn keeps each frozen interpreter independent; no fork of the live state writer.
    import multiprocessing
    with ProcessPoolExecutor(max_workers=max(1,min(int(workers),8)),mp_context=multiprocessing.get_context('spawn')) as pool:
        pending={}
        for pid in selection:
            if pid not in eligible:
                reports.append({'panel_id':pid,'status':'HOLD','errors':['DEPENDENCY_OR_SCOPE_NOT_READY']});continue
            task=(pid,state,original,str(root),batch,records[pid],shots[pid],basis,records)
            pending[pool.submit(_prepare_panel,task)]=pid
        for future in as_completed(pending):
            try:
                pid,row,data,reads,report=future.result()
                if data is not None and sink:sink(pid,row,data,common,reads)
                reports.append(report)
            except (OSError,ValueError,KeyError,TypeError) as exc:
                reports.append({'panel_id':pending[future],'status':'HOLD','errors':[str(exc)]})
    byid={r['panel_id']:r for r in reports};reports=[byid[p] for p in selection]
    ready=[r['panel_id'] for r in reports if r['status']=='PASS']
    return {'status':'READY' if len(ready)==len(selection) and ready else 'PARTIAL_READY' if ready else 'HOLD',
            'ready_panel_ids':ready,'reports':reports,'image_calls':0,'dispatch_authorized':False}


class PreparedStore:
    def __init__(self,state_path):
        self.path=Path(state_path).resolve();self.root=self.path.parent.parent
        self.folder=self.path.parent/'prepared_inputs';self.lock=threading.RLock()
        self.entries={};self.verified={};self.directory_guards={};self.ready={};self.preparing=False
        self.statistics={'prepared':0,'reused':0,'hash_bytes':0,'hash_reads':0}

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
               'packet':data['packet'],'binding':data['binding'],'submission_plan':data['submission'],
               'dependencies':{p:next(r for r in state['panels'] if r['panel_id']==p).get('output') for p in panel.get('generation_dependencies',[])},
               'common_reads':common,'panel_reads':reads,'dispatch_authorized':False,
               'scheduling_rows':[{k:p.get(k) for k in ('panel_id','generation_dependencies','visual_state_keys')}
                    for p in read_json(checked_file(self.root,state['shot_manifest']))['panels']]}
        # Content-address the complete proof too: source/review revisions never overwrite old evidence.
        value['record_digest']=fingerprint(value)
        name=self.folder/(value['record_digest']+'.json');self.folder.mkdir(parents=True,exist_ok=True)
        atomic_json(name,value)
        self.verify_files(common);self.verify_files(reads)
        with self.lock:
            self.entries[value['record_digest']]=value;self.ready[pid]=value['record_digest'];self.statistics['prepared']+=1
        return self.ref(value)

    def ref(self,value):
        return {'policy':DISPATCH,'prepared_input_id':value['prepared_input_id'],'record_digest':value['record_digest'],
                'panel_id':value['panel_id'],'book_id':value['book_id'],'episode_id':value['episode_id'],
                'job_id':value['episode_id'],'attempt_id':value['attempt_id'],'batch_id':'EPISODE','round_id':value['round_id'],'kind':'panel'}

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
        if value['state_basis']!=state_basis(state):raise ValueError('PREPARED_AUTHORITY_OR_INPUT_CHANGED: prepare affected inputs again')
        row=next(r for r in state['panels'] if r['panel_id']==value['panel_id'])
        if any(row.get(k)!=value.get(k) for k in ('attempt_id','round_id')):raise ValueError('PREPARED_ATTEMPT_CHANGED')
        if row['status'] in {'PENDING','REPAIR_AUTHORIZED'} and row['package_manifest']!=value['package_manifest']:raise ValueError('PREPARED_PACKAGE_CHANGED')
        for pid,output in value['dependencies'].items():
            actual=next(r for r in state['panels'] if r['panel_id']==pid)
            if actual.get('output')!=output or actual['status'] not in {'VISUAL_PASS','USER_ACCEPTED'}:raise ValueError('PREPARED_DEPENDENCY_CHANGED:'+pid)
        with self.lock:self.entries[key]=value
        return copy.deepcopy(value)

    def assert_unchanged(self,value):
        # Short-lock stamps only. Hashing/compiling already completed outside the lock.
        for reads in (value['common_reads'],value['panel_reads']):
            for item in reads['files']:
                key=(item['path'],item['sha256'])
                if self.verified.get(key)!=stamp(item['path']):raise ValueError('PREPARED_INPUT_CHANGED_BEFORE_COMMIT')

    def prepare(self,panel_ids=None,workers=4):
        from scoped_episode_workflow import _evaluate_episode
        from panel_readiness import review_context
        from authority_updates import authority_context
        from source_input_contract import strict_reads
        from validation_pool import ValidationPool,session
        state=read_json(self.path)
        if state.get('execution_mode')!='episode_async_v1' or state.get('dispatch_consistency'):raise ValueError('PREPARED_SCOPE_UNSUPPORTED')
        ids=panel_ids or [r['panel_id'] for r in state['panels'] if r['status'] in {'PENDING','REPAIR_AUTHORIZED'}]
        if not isinstance(ids,list) or len(set(ids))!=len(ids):raise ValueError('PREPARED_PANEL_IDS_INVALID')
        reusable=[];pending=[]
        # Restore index from immutable records; always verify content before reuse.
        if self.folder.exists():
            for path in self.folder.glob('*.json'):
                try:
                    v=read_json(path)
                    if v['panel_id'] in ids and v['state_basis']==state_basis(state):
                        self.get(self.ref(v),state);self.ready[v['panel_id']]=v['record_digest']
                except (OSError,ValueError,KeyError,TypeError,StopIteration):continue
        for pid in ids:
            try:
                with self.lock:key=self.ready[pid];v=self.entries[key]
                self.get(self.ref(v),state);reusable.append(pid)
            except (OSError,ValueError,KeyError,TypeError,StopIteration):pending.append(pid)
        self.preparing=True;started=time.monotonic()
        try:
            if pending:
                with strict_reads(),session(ValidationPool()),authority_context(state,self.root),file_session():
                    with review_context(state,self.root,False):
                        report=_evaluate_episode(state,self.root,'prepare_batch',pending,
                            prepared_sink=lambda pid,row,data,common,reads:self.put(state,pid,row,data,common,reads),workers=workers)
            else:report={'status':'READY','ready_panel_ids':[],'reports':[]}
            ready=reusable+report.get('ready_panel_ids',[])
            with self.lock:
                refs=[self.ref(self.entries[self.ready[p]]) for p in ids if p in ready]
                self.statistics['reused']+=len(reusable)
            return {**report,'status':'READY' if len(refs)==len(ids) and ids else 'PARTIAL_READY' if refs else 'HOLD',
                    'jobs':refs,'ready_panel_ids':[r['panel_id'] for r in refs],'reused_panel_ids':reusable,
                    'prepare_seconds':time.monotonic()-started,'statistics':dict(self.statistics),'image_calls':0,'dispatch_authorized':False}
        finally:self.preparing=False


def store(state_path):
    key=str(Path(state_path).resolve())
    with _STORE_LOCK:
        if key not in _STORES:_STORES[key]=PreparedStore(key)
        return _STORES[key]
