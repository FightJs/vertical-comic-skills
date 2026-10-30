"""Local-machine admission only. Never grants image authority or retries a call.
All episode owners share short file transactions; probes and work run outside locks.
"""
from pathlib import Path
from functools import lru_cache
from contextlib import contextmanager
import json,os,platform,re,shutil,subprocess,time,uuid
from platform_io import atomic_json,file_lock,codex_home
from runtime_clock import boot_id as _runtime_boot_id

POLICY='machine_resource_admission_v1'
KINDS=('compile','image','host')
MiB=1024**2;GiB=1024**3

@lru_cache(maxsize=1)
def boot_id():
    value=_runtime_boot_id()
    match=re.search(r'sec\s*=\s*(\d+),\s*usec\s*=\s*(\d+)',value or '')
    return 'darwin:'+':'.join(match.groups()) if match else value

def resource_home():
    # Explicit isolation for tests; production uses the same home across all Agents.
    return Path(os.environ.get('COMIC_RESOURCE_HOME',str(Path.home()/'.codex/skill-bundles/vertical-comic-skills/machine-resources'))).expanduser().resolve()

def command(args):
    return subprocess.check_output(args,text=True,stderr=subprocess.DEVNULL,timeout=1,env={**os.environ,'LC_ALL':'C','TZ':'UTC'}).strip()

def process_identity(pid):
    if os.name=='nt':
        import ctypes
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.OpenProcess.restype=ctypes.c_void_p;api.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
        api.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)];api.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=api.OpenProcess(0x1000,False,pid)
        if not handle:return None if ctypes.get_last_error()==87 else {'pid':pid,'birth':None}
        try:
            code=ctypes.c_ulong()
            if api.GetExitCodeProcess(handle,ctypes.byref(code)) and code.value!=259:return None
        finally:api.CloseHandle(handle)
        return {'pid':pid,'birth':None}
    try:
        os.kill(pid,0)
    except ProcessLookupError:return None
    except (PermissionError,OSError):return {'pid':pid,'birth':None}
    try:
        proc=Path('/proc')/str(pid)/'stat'
        birth=proc.read_text().rsplit(')',1)[1].split()[19] if proc.exists() else command(['ps','-p',str(pid),'-o','lstart='])
        return {'pid':pid,'birth':birth or None}
    except (OSError,ValueError,subprocess.SubprocessError):return {'pid':pid,'birth':None}

@lru_cache(maxsize=32)
def self_identity(pid):return process_identity(pid) or {'pid':pid,'birth':None}

def alive(identity):
    current=process_identity(identity['pid'])
    if current is None:return False
    return not (identity.get('birth') and current.get('birth') and identity['birth']!=current['birth'])

def sample_system(disk_path):
    now=time.monotonic();result={'at':now,'boot':boot_id(),'cpus':os.cpu_count() or 1,'known':False}
    try:
        if platform.system()=='Darwin':
            total=int(command(['sysctl','-n','hw.memsize']))
            raw=command(['vm_stat']);page=int(re.search(r'page size of (\d+)',raw).group(1))
            values={k.strip():int(v) for k,v in re.findall(r'^([^:\n]+):\s*(\d+)\.',raw,re.M)}
            available=sum(values.get(k,0) for k in ('Pages free','Pages inactive','Pages speculative'))*page
            try:pressure=int(command(['sysctl','-n','kern.memorystatus_vm_pressure_level']))
            except (OSError,ValueError,subprocess.SubprocessError):pressure=0
            result.update(total=total,available=available,compressed=values.get('Pages occupied by compressor',0)*page,
                          swapout=values.get('Swapouts',0)*page,pressure=pressure,known=True)
        elif Path('/proc/meminfo').exists():
            values={k:int(v)*1024 for k,v in re.findall(r'^(\w+):\s*(\d+) kB',Path('/proc/meminfo').read_text(),re.M)}
            swaps=dict(re.findall(r'^(pswpout) (\d+)',Path('/proc/vmstat').read_text(),re.M))
            result.update(total=values['MemTotal'],available=values['MemAvailable'],compressed=0,
                          swapout=int(swaps.get('pswpout',0))*os.sysconf('SC_PAGE_SIZE'),pressure=1,known=True)
        # Unsupported/failed probes remain conservative, never 'unlimited'.
    except (OSError,ValueError,KeyError,AttributeError,subprocess.SubprocessError):pass
    try:result['disk_free']=shutil.disk_usage(disk_path).free
    except OSError:result['disk_free']=None
    return result

class Coordinator:
    def __init__(self,home=None,probe=None,clock=None,liveness=None):
        self.home=Path(home) if home is not None else resource_home();self.home.mkdir(parents=True,exist_ok=True)
        self.path=self.home/'admission.json';self.probe=probe or sample_system;self.clock=clock or time.monotonic;self.liveness=liveness or alive
        self.owner=self_identity(os.getpid());self.boot=boot_id();self._live_cache={}
    def _alive(self,identity):
        if identity==self.owner:return True
        key=json.dumps(identity,sort_keys=True);now=self.clock();old=self._live_cache.get(key)
        if old and 0<=now-old[0]<2:return old[1]
        value=self.liveness(identity);self._live_cache[key]=(now,value)
        if len(self._live_cache)>256:self._live_cache={key:(now,value)}
        return value
    def _read(self):
        if not self.path.exists():return {}
        value=json.loads(self.path.read_text())
        if value.get('policy')!=POLICY:raise ValueError('MACHINE_RESOURCE_POLICY_CHANGED')
        return value
    def _sample(self,disk):
        # Serialize probes separately; never run sysctl/ps under the admission lock.
        cached=self.home/'sample.json';now=self.clock()
        try:
            old=json.loads(cached.read_text())
            if old.get('boot')==self.boot and 0<=now-old['at']<2:return old
        except (OSError,ValueError,KeyError):pass
        try:
            with file_lock(self.home/'probe.lock',timeout=0):
                value=self.probe(disk);atomic_json(cached,value);return value
        except TimeoutError:
            try:return json.loads(cached.read_text())
            except (OSError,ValueError):return {'known':False,'at':now,'boot':self.boot,'cpus':1}
    def _transaction(self,action,disk=None):
        disk=Path(disk or self.home);sample=dict(self._sample(disk));now=self.clock()
        try:sample['disk_free']=min(sample.get('disk_free') or 2**63,shutil.disk_usage(disk).free)
        except OSError:pass
        # Liveness may require a process query. Inspect outside the shared write lock.
        previous=self._read();dead={}
        for token,lease in previous.get('leases',{}).items():
            identities=[lease['owner'],*lease.get('children',[])]
            if not any(self._alive(i) for i in identities):dead[token]=lease
        with file_lock(self.home/'admission.lock',timeout=5):
            state=self._read()
            if not state or self.boot and state.get('boot')!=self.boot:
                state={'policy':POLICY,'boot':self.boot,'leases':{},'waiters':{},'limits':{'compile':2,'image':4,'host':1},
                       'worker_bytes':256*MiB,'return_bytes':64*MiB,'history':[],
                       'windows':{k:{'at':now,'done':0,'baseline':None,'cooldown':now+30,'saturated':False} for k in KINDS}}
            # Older frozen coordinators share leases but must not overwrite a
            # new controller's learned target with their legacy idle reset.
            state['limits']=state.get('adaptive_limits_v2',state['limits'])
            state['windows']=state.get('adaptive_windows_v2',state['windows'])
            # Add fields to an existing admission ledger without discarding live leases.
            state['limits'].setdefault('host',1)
            state['windows'].setdefault('host',{'at':now,'done':0,'cooldown':now+60,'saturated':False})
            for token,lease in dead.items():
                if state['leases'].get(token)==lease:state['leases'].pop(token,None)
            state['waiters']={k:v for k,v in state['waiters'].items() if now-v['at']<10}
            self._tune(state,sample,now)
            result=action(state,now)
            state['adaptive_limits_v2']=state['limits'];state['adaptive_windows_v2']=state['windows']
            atomic_json(self.path,state)
            return result
    def _tune(self,s,sample,now):
        previous=s.get('sample',{});s['sample']=sample
        total=sample.get('total',4*GiB);available=sample.get('available',GiB);reserve=max(768*MiB,total//8)
        swap_rate=max(0,sample.get('swapout',0)-previous.get('swapout',sample.get('swapout',0)))/max(1,sample.get('at',now)-previous.get('at',now))
        # Keep the last measured swap rate until a genuinely new sample arrives.
        if sample.get('at')==previous.get('at'):swap_rate=s.get('swap_rate',0)
        s['swap_rate']=swap_rate
        pending=[l for l in s['leases'].values() if l['kind']=='image' and l.get('returned_at') is not None]
        pending_bytes=sum(l.get('bytes',0) for l in pending)
        oldest=max((now-l['returned_at'] for l in pending),default=0)
        critical=sample.get('pressure')==4 or available<256*MiB or sample.get('compressed',0)>total*.65 or (sample.get('disk_free') is not None and sample['disk_free']<2*GiB)
        warning=critical or sample.get('pressure')==2 or available<reserve or sample.get('compressed',0)>total*.45 or swap_rate>16*MiB
        backlog=pending_bytes>min(512*MiB,total//12) or oldest>10
        unknown=not sample.get('known') or now-sample.get('at',now)>10
        s.update(critical=critical,warning=warning,backlog=backlog,pending_bytes=pending_bytes,oldest_capture_seconds=oldest,reserve=reserve)
        # Initial assumptions are conservative; observed peaks can tighten them.
        s['hard']={'compile':max(1,min(sample.get('cpus',1),int(total*.3/max(256*MiB,s['worker_bytes'])),61)),
                   'image':max(1,int(total*.15/max(64*MiB,s['return_bytes']))),
                   'host':max(1,min(sample.get('cpus',1),int(total*.10/(256*MiB))))}
        if unknown:s['hard']={'compile':1,'image':2,'host':1}
        for kind in KINDS:
            old=s['limits'][kind];limit=min(old,s['hard'][kind]);w=s['windows'][kind]
            active=sum(l['units'] for l in s['leases'].values() if l['kind']==kind)
            demand=(kind!='host' and active>=limit) or any(v['kind']==kind for v in s['waiters'].values())
            reason='hardware_bound'
            # Idle or a paused runner cannot produce a throughput sample. Keep
            # the learned limit; restart observation only, never reset to 2/4.
            if active or demand:w['last_busy']=now
            if not active and not demand and now-w.get('last_busy',now)>120:
                w.update(at=now,done=0,healthy_since=now,saturated=False)
                w.pop('probe',None)
            if warning or backlog or unknown:
                w['healthy_since']=None
                if now-w.get('reduced_at',-100)>=5:
                    limit=max(1,limit//2)
                    w.update(reduced_at=now,cooldown=now+60,at=now,done=0)
                    w.pop('probe',None)
                reason='telemetry_unknown' if unknown else 'capture_backlog' if backlog else 'memory_or_disk_pressure'
            else:
                if w.get('healthy_since') is None:w['healthy_since']=now
                w.setdefault('healthy_since',now)
                probe=w.get('probe')
                duration=max(1,w.get('duration_seconds',30))
                if kind=='image' and w['done']<2:duration=max(duration,max((now-l['at'] for l in s['leases'].values() if l['kind']==kind and l.get('returned_at') is None),default=0))
                # Service requests can take minutes. Never judge a trial by a
                # fixed 30s window, or count failed/no-image calls as throughput.
                window=max(60,2*duration)
                if probe and now-probe['at']>=window:
                    enough=w['done']>=min(4,max(2,probe['prior']))
                    expired=now-probe['at']>=max(180,4*duration)
                    if enough or expired:
                        rate=w['done']/max(1,now-probe['at'])
                        gain=enough and (probe['baseline'] is None or rate>=probe['baseline']*1.05)
                        if gain:
                            w.update(failures=0,cooldown=now+60)
                            reason='probe_gain'
                        else:
                            limit=min(limit,probe['prior']);failures=min(5,w.get('failures',0)+1)
                            w.update(failures=failures,cooldown=now+min(900,60*2**failures))
                            reason='probe_no_gain'
                        observed_done=w['done']
                        w.pop('probe',None);w.update(at=now,done=0,healthy_since=now)
                        s['history'].append({'at':now,'kind':kind,'from':old,'to':limit,'reason':reason,'saved_or_compiled':observed_done,'rate':rate})
                elif (not probe and demand and now>=w.get('cooldown',0)
                      and now-w['healthy_since']>=60 and limit<s['hard'][kind]):
                    elapsed=max(1,now-w['at'])
                    baseline=w['done']/elapsed if w['done']>=2 else None
                    step=1 if kind!='image' or limit<4 else max(1,(limit+3)//4)
                    w['probe']={'at':now,'prior':limit,'baseline':baseline}
                    w.update(at=now,done=0)
                    limit=min(s['hard'][kind],limit+step);reason='healthy_probe'
            s['limits'][kind]=limit
            w['limiting_reason']=reason if warning or backlog or unknown or old!=limit else ('probe_observing' if w.get('probe') else 'hardware_bound' if limit>=s['hard'][kind] else 'healthy_observation')
            if old!=limit and reason not in {'probe_gain','probe_no_gain'}:
                s['history'].append({'at':now,'kind':kind,'from':old,'to':limit,'reason':reason})
            s['history']=s['history'][-80:]
    def _view(self,s):
        return {k:s[k] for k in ('limits','hard','critical','warning','backlog','pending_bytes','oldest_capture_seconds','history')} | {
            'active':{kind:sum(l['units'] for l in s['leases'].values() if l['kind']==kind) for kind in KINDS},
            'sample':s['sample'],'policy':POLICY,
            'tuning':{k:{'reason':s['windows'][k].get('limiting_reason'),'probe':s['windows'][k].get('probe'),
                         'cooldown_until':s['windows'][k].get('cooldown')} for k in KINDS}}
    def resource_failure(self,kind,allocated,reason):
        if kind not in KINDS or type(allocated) is not int or allocated<1:raise ValueError('RESOURCE_FAILURE_INVALID')
        def change(s,now):
            old=s['limits'][kind];limit=min(old,max(1,allocated//2));s['limits'][kind]=limit
            w=s['windows'][kind];w.update(at=now,done=0,healthy_since=None,cooldown=now+60,reduced_at=now)
            w.pop('probe',None)
            s['history'].append({'at':now,'kind':kind,'from':old,'to':limit,'reason':'observed_resource_failure','detail':str(reason)[:300]})
        return self._transaction(change)

    def observe_run(self,key,segment):
        """A confirmed clock resume restarts measurements, never the task clock."""
        if segment is None:return
        def change(s,now):
            epochs=s.setdefault('run_segments',{})
            old=epochs.get(key);epochs[key]=segment
            if old is not None and old!=segment:
                for w in s['windows'].values():
                    w.update(at=now,done=0,healthy_since=now,cooldown=now+60)
                    w.pop('probe',None)
                s['history'].append({'at':now,'reason':'resume_observation_reset','run':key})
            # A bounded observation cache is not authority or production evidence.
            while len(epochs)>128:epochs.pop(next(iter(epochs)))
        return self._transaction(change)

    def status(self,disk=None):return self._transaction(lambda s,now:self._view(s),disk)
    def acquire(self,kind,key,requested=1,disk=None,estimated_bytes=0):
        if kind not in KINDS or type(requested) is not int or requested<1:raise ValueError('RESOURCE_REQUEST_INVALID')
        if type(estimated_bytes) is not int or estimated_bytes<0:raise ValueError('RESOURCE_ESTIMATE_INVALID')
        owner_key=json.dumps([self.owner,key,kind],sort_keys=True)
        def change(s,now):
            if kind=='compile':s['worker_bytes']=max(s['worker_bytes'],estimated_bytes)
            for token,l in s['leases'].items():
                if l['key']==owner_key:return {'status':'RESOURCE_GRANTED','token':token,'units':l['units'],**self._view(s)}
            s['waiters'].setdefault(owner_key,{'since':now,'kind':kind,'at':now});s['waiters'][owner_key]['at']=now
            active=sum(l['units'] for l in s['leases'].values() if l['kind']==kind)
            capacity=s['limits'][kind]-active
            if capacity<=0:s['windows'][kind]['saturated']=True
            older=any(v['kind']==kind and (v['since'],k)<(s['waiters'][owner_key]['since'],owner_key) for k,v in s['waiters'].items())
            in_flight=sum(s['return_bytes'] for l in s['leases'].values() if l['kind']=='image' and l.get('returned_at') is None)
            starting_compile=sum(l['units']*(s['worker_bytes'] if l['kind']=='compile' else 256*MiB) for l in s['leases'].values() if l['kind'] in {'compile','host'} and l['at']>=s['sample'].get('at',now)-3)
            free=s['sample'].get('available',2*GiB)-s['reserve']-in_flight-s['pending_bytes']-starting_compile
            estimate=s['worker_bytes'] if kind=='compile' else 256*MiB if kind=='host' else s['return_bytes']
            units=min(requested,capacity,max(0,int(free//max(estimate,1))))
            if s['critical'] or s['backlog'] or older or units<1:
                return {'status':'RESOURCE_WAIT','retry_after_ms':500,'reason':'PRESSURE' if s['critical'] or s['warning'] else 'CAPTURE_BACKLOG' if s['backlog'] else 'CAPACITY',**self._view(s)}
            token=uuid.uuid4().hex;s['leases'][token]={'kind':kind,'key':owner_key,'owner':self.owner,'children':[],
                                                    'units':units,'at':now,'returned_at':None,'bytes':0}
            s['waiters'].pop(owner_key,None)
            return {'status':'RESOURCE_GRANTED','token':token,'units':units,**self._view(s)}
        return self._transaction(change,disk)
    def attach_worker(self,token):
        def change(s,now):
            l=s['leases'].get(token)
            if not l or l['kind'] not in {'compile','host'}:raise ValueError('WORKER_RESOURCE_LEASE_MISSING')
            if self.owner not in l['children']:l['children'].append(self.owner)
        return self._transaction(change)
    def returned(self,token,size):
        if type(size) is not int or size<0:raise ValueError('RETURN_BYTES_INVALID')
        def change(s,now):
            l=s['leases'].get(token)
            if not l or l['owner']!=self.owner:raise ValueError('RESOURCE_LEASE_OWNER_CHANGED')
            l.update(returned_at=l['returned_at'] or now,bytes=size)
            s['return_bytes']=max(s['return_bytes'],size*2)
            return {'status':'RETURN_PRESSURE_RECORDED'}
        return self._transaction(change)
    def progress(self,token,completed=0,worker_bytes=0):
        def change(s,now):
            l=s['leases'].get(token)
            if not l or l['owner']!=self.owner:raise ValueError('RESOURCE_LEASE_OWNER_CHANGED')
            s['windows'][l['kind']]['done']+=completed
            if completed:
                w=s['windows'][l['kind']];duration=max(0,now-l.get('last_progress',l['at']))/completed
                w['duration_seconds']=duration if 'duration_seconds' not in w else .75*w['duration_seconds']+.25*duration
                l['last_progress']=now
            if l['kind']=='compile' and sum(v['units'] for v in s['leases'].values() if v['kind']=='compile')>=s['limits']['compile']:
                s['windows']['compile']['saturated']=True
            s['worker_bytes']=max(s['worker_bytes'],int(worker_bytes))
            view=self._view(s)
            return {**view,'drain':s['critical'] or s['backlog'] or view['active'][l['kind']]>s['limits'][l['kind']] or (l['kind']=='compile' and now-l['at']>=30 and (view['active']['compile']<s['limits']['compile'] or any(v['kind']=='compile' for v in s['waiters'].values())))}
        return self._transaction(change)
    def release_image_key(self,key):
        owner_key=json.dumps([self.owner,key,'image'],sort_keys=True)
        def change(s,now):
            tokens=[token for token,l in s['leases'].items() if l['key']==owner_key]
            for token in tokens:s['leases'].pop(token,None)
            return {'status':'RESOURCE_RELEASED','released':len(tokens)}
        return self._transaction(change)
    def release(self,token,completed=False,preserved=True):
        def change(s,now):
            l=s['leases'].get(token)
            if not l:return {'status':'RESOURCE_RELEASED','already_released':True}
            if l['owner']!=self.owner:raise ValueError('RESOURCE_LEASE_OWNER_CHANGED')
            if not preserved:
                l.update(returned_at=l.get('returned_at') or now,bytes=max(l.get('bytes',0),s['return_bytes']))
                return {'status':'RESOURCE_HELD_FOR_CAPTURE','token':token}
            if completed:
                w=s['windows'][l['kind']];w['done']+=1
                duration=max(0,now-l['at'])
                w['duration_seconds']=duration if 'duration_seconds' not in w else .75*w['duration_seconds']+.25*duration
            s['leases'].pop(token,None);return {'status':'RESOURCE_RELEASED'}
        return self._transaction(change)

def serve_hosts():
    # Small JSONL child of the batch bridge, not a daemon or production writer.
    # It admits heavyweight Python owners before they are spawned.
    import sys
    c=Coordinator()
    for line in sys.stdin:
        request={}
        try:
            request=json.loads(line);action=request['action']
            if action=='acquire':result=c.acquire('host',request['key'],disk=request.get('disk'))
            elif action=='release':result=c.release(request['token'])
            elif action=='progress':result=c.progress(request['token'],completed=request.get('completed',0))
            elif action=='attach':
                identity=process_identity(request['pid'])
                if identity is None:raise ValueError('HOST_EXIT_BEFORE_ATTACH')
                def attach(s,now):
                    lease=s['leases'][request['token']]
                    if lease['owner']!=c.owner:raise ValueError('HOST_OWNER_CHANGED')
                    if identity not in lease['children']:lease['children'].append(identity)
                    return {'status':'HOST_ATTACHED'}
                result=c._transaction(attach)
            else:result=c.status()
        except Exception as exc:result={'error':str(exc)}
        print(json.dumps({'request_id':request.get('request_id'),'result':result}),flush=True)

if __name__=='__main__':
    import sys
    if '--serve-host-admission' in sys.argv:serve_hosts()
    else:print(json.dumps(Coordinator().status(),ensure_ascii=False))
