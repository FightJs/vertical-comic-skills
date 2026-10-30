/* Node-side JSONL relay. One state writer per episode; capture admission stays
   here so a burst of returns cannot block the host's control-message reader. */
((factory)=>{if(typeof module!=='undefined')module.exports=factory;return factory;})(function createComicHostClients({spawn,python,episodes,onDiagnostic=()=>{},captureCapacity=8,admission}) {
  if(typeof spawn!=='function'||!python||!Array.isArray(episodes)||!Number.isInteger(captureCapacity)||captureCapacity<1||captureCapacity>8)
    throw new Error('HOST_CLIENT_CONFIGURATION');
  const clients=new Map(),opening=new Map(),specs=new Map(),users=new Map(),idleTimers=new Map();let serial=0,closed=false;
  for(const e of episodes){if(specs.has(e.state))throw Error('DUPLICATE_STATE_OWNER');specs.set(e.state,e);}
  let broker,brokerSerial=0,brokerBuffer='',brokerDead=false;const brokerPending=new Map();
  function resource(payload){
    if(admission)return admission(payload);
    if(brokerDead)return Promise.reject(Error('HOST_ADMISSION_EXIT'));
    if(!broker){
      const script=episodes[0].generation_host.replace(/generation_host\.py$/,'machine_resources.py');
      broker=spawn(python,['-B',script,'--serve-host-admission'],{stdio:['pipe','pipe','pipe']});
      broker.stdout.setEncoding('utf8');broker.stderr.setEncoding('utf8');
      const fail=error=>{brokerDead=true;for(const p of brokerPending.values())p.reject(error);brokerPending.clear();};
      broker.stdout.on('data',chunk=>{
        brokerBuffer+=chunk;let n;
        while((n=brokerBuffer.indexOf('\n'))>=0){
          const line=brokerBuffer.slice(0,n);brokerBuffer=brokerBuffer.slice(n+1);
          try{const r=JSON.parse(line),p=brokerPending.get(r.request_id);if(!p)continue;
            brokerPending.delete(r.request_id);r.result.error?p.reject(Error(r.result.error)):p.resolve(r.result);
          }catch(error){fail(error);}
        }
      });
      broker.stderr.on('data',message=>onDiagnostic({source:'host-admission',message}));
      broker.on('error',fail);broker.on('exit',()=>fail(Error('HOST_ADMISSION_EXIT')));
    }
    return new Promise((resolve,reject)=>{
      const request_id=++brokerSerial;brokerPending.set(request_id,{resolve,reject});
      broker.stdin.write(JSON.stringify({...payload,request_id})+'\n',error=>{if(error){brokerPending.delete(request_id);reject(error);}});
    });
  }
  async function retire(state,c){
    if(c.retirement)return c.retirement;
    if(!c.exited()&&(c.queued()||c.pinned()||users.get(state)))return false;
    c.retirement=(async()=>{
      if(!c.exited())c.child.stdin.end();await c.exitPromise;
      if(clients.get(state)===c)clients.delete(state);
      await resource({action:'release',token:c.token});return true;
    })();return c.retirement;
  }
  let activation=Promise.resolve();
  async function ensure(state){
    if(clients.has(state)){const c=clients.get(state);if(c.retirement){await c.retirement;return ensure(state);}
      if(c.exited()){await retire(state,c);return ensure(state);}return c;}
    if(opening.has(state))return opening.get(state);
    const e=specs.get(state);if(!e)throw Error('UNKNOWN_EPISODE_OWNER');
    const task=(async()=>{
      // Serialize only host admission. Existing hosts keep receiving/capturing.
      const previous=activation;let unlock;activation=new Promise(r=>unlock=r);await previous;
      try{while(!closed){
        const permit=await resource({action:'acquire',key:state,disk:e.state.replace(/[^/]+$/,'')});
        if(permit.status==='RESOURCE_GRANTED'){
          const c=open(e,permit.token);clients.set(state,c);
          await resource({action:'attach',token:permit.token,pid:c.child.pid});return c;
        }
        if(permit.status!=='RESOURCE_WAIT')throw Error('HOST_ADMISSION_RECEIPT_REQUIRED');
        // Reuse occupied hosts. Only evict an idle owner, never an owner holding
        // a prepare, a return, or a real image invocation/unknown result.
        let retired=false;
        for(const [name,c] of clients){if(await retire(name,c)){retired=true;break;}}
        if(!retired)await new Promise(r=>setTimeout(r,Math.max(100,permit.retry_after_ms??500)));
      }throw Error('HOST_CLIENT_CLOSED');}finally{unlock();}
    })();opening.set(state,task);try{return await task;}finally{opening.delete(state);}
  }
  const captures=new Set(['capture-return','capture-envelope']);
  function open(e,token){
    const child=spawn(python,['-X','utf8','-B',e.generation_host,'serve','--state',e.state],{stdio:['pipe','pipe','pipe']});
    const pending=new Map(),captureQueue=[],pins=new Set(),completedCaptures=new Set();let buffer='',ended=false,activeCaptures=0,exited=false,sourceOpen=false;let exitResolve;
    const exitPromise=new Promise(resolve=>{exitResolve=resolve;});
    const fail=error=>{ended=true;for(const p of pending.values())p.reject(error);pending.clear();
      for(const p of captureQueue)p.reject(error);captureQueue.length=0;};
    function send(entry){
      const {payload,resolve,reject}=entry,request_id='batch-'+(++serial),capture=captures.has(payload.action);
      if(capture)activeCaptures++;
      if(payload.action==='prepare-inputs')sourceOpen=true;
      pending.set(request_id,{resolve,reject,capture,payload});
      child.stdin.write(JSON.stringify({...payload,state:e.state,request_id})+'\n',error=>{
        if(error)settle(request_id,error);
      });
    }
    function drain(){while(!ended && !closed && activeCaptures<captureCapacity && captureQueue.length)send(captureQueue.shift());}
    function settle(id,error,value){
      const p=pending.get(id);if(!p)return false;pending.delete(id);
      if(p.capture)activeCaptures--;
      if(p.payload.action==='ready-inputs'&&(error||value?.preparation_complete&&value.jobs?.length===0))sourceOpen=false;
      if(!error){
        if(p.payload.action==='resource-acquire'&&value?.status==='RESOURCE_GRANTED')pins.add(value.token);
        if(p.payload.action==='resource-release'&&value?.status==='RESOURCE_RELEASED')pins.delete(p.payload.token);
        if(value?.status==='RETURN_CAPTURED'){
          if(p.payload.resource_token)pins.delete(p.payload.resource_token);
          const key=JSON.stringify(value.capture);
          if(!completedCaptures.has(key)){completedCaptures.add(key);resource({action:'progress',token,completed:1}).catch(onDiagnostic);}
        }
      }
      error?p.reject(error):p.resolve(value);drain();return true;
    }
    child.stdout.setEncoding('utf8');child.stderr.setEncoding('utf8');
    child.stdout.on('data',chunk=>{
      buffer+=chunk;let n;
      while((n=buffer.indexOf('\n'))>=0){
        const line=buffer.slice(0,n);buffer=buffer.slice(n+1);if(!line.trim())continue;
        try{const result=JSON.parse(line),value=result.result;
          const error=value?.status==='HOLD' && value.error ? new Error(value.error):null;
          if(!settle(result.request_id,error,value))onDiagnostic({episode_id:e.episode_id,error:'UNMATCHED_HOST_RESPONSE'});
        }catch(error){fail(error);}
      }
    });
    child.stderr.on('data',message=>onDiagnostic({episode_id:e.episode_id,message}));
    child.on('error',error=>{fail(error);if(!child.pid){exited=true;exitResolve();}});
    child.on('exit',(code,signal)=>{exited=true;fail(new Error('HOST_EXIT:'+code+':'+signal));exitResolve();});
    return {child,token,exitPromise,pinned:()=>pins.size+(sourceOpen?1:0),exited:()=>exited,alive:()=>!ended,queued:()=>pending.size+captureQueue.length,request:payload=>new Promise((resolve,reject)=>{
      if(ended||closed){reject(new Error('HOST_TERMINATED_RECONCILE_FIRST'));return;}
      const entry={payload,resolve,reject};
      if(captures.has(payload.action) && activeCaptures>=captureCapacity){
        // Jobs hold their invocation slot until durable capture; queued payloads
        // retain the original object, not another serialized image copy.
        if(captureQueue.length>=(e.panel_count ?? 1)){reject(new Error('CAPTURE_QUEUE_FULL_RETAIN_RETURN'));return;}
        captureQueue.push(entry);
      }else send(entry);
    })};
  }
  return {request:async(state,payload)=>{
    clearTimeout(idleTimers.get(state));idleTimers.delete(state);
    users.set(state,(users.get(state)??0)+1);
    try{const c=await ensure(state);return await c.request(payload);}
    finally{
      users.set(state,users.get(state)-1);
      if(!closed&&!users.get(state)){
        const timer=setTimeout(()=>{const c=clients.get(state);if(c&&!closed)retire(state,c).catch(onDiagnostic);},30000);
        timer.unref?.();idleTimers.set(state,timer);
      }
    }
  },snapshot:()=>({alive:!closed&&[...clients.values()].every(c=>c.alive()),
    pids:[...clients.values()].map(c=>c.child.pid),active_hosts:clients.size,waiting_hosts:opening.size,episode_count:episodes.length,pending:[...users.values()].reduce((n,v)=>n+v,0)}),
  close:async()=>{
    if(opening.size||[...users.values()].some(n=>n>0)||[...clients.values()].some(c=>c.queued()))throw new Error('HOST_BUSY_DRAIN_FIRST');
    if(!closed){closed=true;for(const timer of idleTimers.values())clearTimeout(timer);idleTimers.clear();for(const c of clients.values())if(!c.exited())c.child.stdin.end();}
    let timer;
    try{await Promise.race([Promise.all([...clients.values()].map(c=>c.exitPromise)),
      new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('HOST_CLOSE_PENDING')),5000)})]);}
    finally{clearTimeout(timer);}
    for(const c of clients.values())await resource({action:'release',token:c.token});
    if(broker&&!brokerDead)broker.stdin.end();
  }};
})
