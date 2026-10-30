/* Evaluate beside async_generation.js in the supported tool host. Inject the
   actual channels and JSONL host client; this module never invents a tool API. */
(async function runImageToolBridge({run, jobs, confirmedConcurrency, transport, host, options = {}}) {
  if (typeof run !== 'function' || !Array.isArray(jobs) || !Number.isInteger(confirmedConcurrency) || confirmedConcurrency < 1)
    throw new Error('BRIDGE_RUN_JOBS_CAPACITY_REQUIRED');
  if (!transport?.source_locator) throw new Error('BRIDGE_EXECUTOR_SOURCE_REQUIRED');
  const concurrent=transport.kind==='concurrent_requests';
  if (concurrent && (typeof transport.invoke!=='function' || transport.maxPending !== undefined &&
      (!Number.isInteger(transport.maxPending) || transport.maxPending<1))) throw new Error('BRIDGE_ASYNC_TRANSPORT_INVALID');
  const requestLimit=concurrent ? Math.min(confirmedConcurrency,transport.maxPending ?? confirmedConcurrency) : 0;
  // These are client request slots on ONE asynchronous tool, not physical rendering channels.
  const channels=concurrent ? Array.from({length:requestLimit},(_,i)=>({id:'request-slot-'+i,invoke:transport.invoke})) : transport?.channels;
  if (!Array.isArray(channels) || !channels.length || channels.some(c=>!c.id || typeof c.invoke!=='function') || new Set(channels.map(c=>c.id)).size!==channels.length)
    throw new Error('BRIDGE_ACTUAL_CHANNELS_REQUIRED');
  for (const key of ['prepare', 'recordInvocation', 'save'])
    if (typeof host?.[key] !== 'function') throw new Error('BRIDGE_HOST_'+key+'_REQUIRED');
  const free=[...channels], waiters=[];
  const active=new Set();
  function acquireLocal() {
    if (free.length) {const c=free.shift();active.add(c.id);return Promise.resolve(c);}
    return new Promise(resolve=>waiters.push(resolve));
  }
  function releaseLocal(c) {
    if (!active.delete(c.id)) throw new Error('BRIDGE_CHANNEL_RELEASE_CONFLICT');
    if (waiters.length) {active.add(c.id);waiters.shift()(c);} else free.push(c);
  }
  let admissionTail=Promise.resolve();
  async function acquire(job,isStopped=()=>false){
    const channel=await acquireLocal();
    try{
      if(typeof host.acquireResource==='function'){
        // One capacity waiter per runner, not one polling loop per panel.
        // Successful grants pass the baton immediately, retaining full service overlap.
        const previous=admissionTail;let unlock;
        admissionTail=new Promise(resolve=>{unlock=resolve;});
        await previous;
        try{while(!isStopped()){
          const permit=await host.acquireResource(job);
          if(permit?.status==='RESOURCE_GRANTED'){channel.resourceLease=permit.token;return channel;}
          if(permit?.status!=='RESOURCE_WAIT')throw Error('MACHINE_RESOURCE_RECEIPT_REQUIRED');
          await new Promise(resolve=>setTimeout(resolve,Math.min(2000,Math.max(100,permit.retry_after_ms??500))));
        }
        releaseLocal(channel);return null;
        }finally{unlock();}
      }
      return channel;
    }catch(error){releaseLocal(channel);throw error;}
  }
  async function release(channel,job,item){
    try{
      if(channel.resourceLease && typeof host.releaseResource==='function'){
        await host.releaseResource(job,channel.resourceLease,{
          preserved:!item?.invocation_requested_at||!!item?.saved_at,
          completed:false});
        delete channel.resourceLease;
      }
    }finally{releaseLocal(channel);}
  }
  function retainedBytes(value,seen=new Set()){
    if(typeof value==='string')return value.length*2;
    if(!value||typeof value!=='object'||seen.has(value))return 16;
    seen.add(value);return 64+Object.entries(value).reduce((n,[k,v])=>n+k.length*2+retainedBytes(v,seen),0);
  }
  // The adapter owns local channels; service quota remains checked by the host.
  // One pending tool Promise per channel. No whole-episode request prequeue.
  const packets=new Map();
  const key=j=>JSON.stringify([j.book_id,j.episode_id,j.panel_id,j.attempt_id]);
  return await run(jobs, Math.min(confirmedConcurrency,channels.length), async (job,channel,item) => {
    item.machine_resource_token=channel.resourceLease;
    const packet=await channel.invoke(job);
    // Preserve even malformed envelopes for host-side reconciliation. Never
    // replace a successful raw result with a fabricated failure or lost output.
    packets.set(key(job),packet);
    item.bridge_packet=packet; // Preserve raw output/locators if durable save fails.
    if(channel.resourceLease && typeof host.resourceReturned==='function'){
      // Preserve and save the return even if telemetry fails; never turn that
      // failure into a reason to generate another image.
      try{await host.resourceReturned(job,channel.resourceLease,retainedBytes(packet));}
      catch(error){item.resource_telemetry_error=String(error);}
    }
    if (packet?.native_started_at && packet?.call_locator) item.native_started_at=packet.native_started_at;
    if (packet?.native_completed_at && packet?.result_locator) item.native_completed_at=packet.native_completed_at;
    if (packet?.result?.isError === true || packet?.result?.error) {
      const actual=packet.result.error ?? packet.result.content ?? packet.result;
      throw new Error(typeof actual==='string'?actual:JSON.stringify(actual));
    }
    return packet?.result;
  }, async (job,item) => {
    const packet=packets.get(key(job));
    if (item.status==='FULFILLED' && item.result !== undefined && typeof host.capture==='function' && typeof host.register==='function') {
      const captured=await host.capture(job,packet,item);
      if (captured?.status!=='RETURN_CAPTURED' || !captured.capture) throw new Error('BRIDGE_DURABLE_CAPTURE_RECEIPT_REQUIRED');
      packets.delete(key(job));
      // Raw originals are now durable. Do not retain all base64 responses until
      // the episode ends; this small marker preserves existing review scheduling.
      item.result={persisted_return:true};delete item.bridge_packet;
      item.output_saved=false;
      item.registration_pending=Promise.resolve().then(()=>host.register(job,captured.capture,item)).then(saved=>{
        if (!saved || !['SAVED','UPDATES_SAVED','UPDATES_ALREADY_SAVED','RETURN_ALREADY_SAVED','RETURN_REGISTERED'].includes(saved.status)) throw new Error('BRIDGE_REGISTRATION_RECEIPT_REQUIRED');
        item.output_saved=true;return saved;
      });
      return;
    }
    const saved=await host.save(job,packet,item);
    if (!saved || !['SAVED','RETURN_ALREADY_SAVED','FAILURE_RECORDED','UNKNOWN_RECORDED'].includes(saved.status))
      throw new Error('BRIDGE_DURABLE_SAVE_RECEIPT_REQUIRED');
    if (['FAILURE_RECORDED','UNKNOWN_RECORDED'].includes(saved.status)) item.output_saved=false;
    item.confirmed_no_output = saved.status === 'FAILURE_RECORDED';
    packets.delete(key(job));
  }, {
    ...options, protocol:'prepared_dispatch_v1', continueIndependent:true,
    concurrentCapture:typeof host.capture==='function' && typeof host.register==='function',
    requestWarningMs:options.requestWarningMs ?? 300000,
    requestEscalationMs:options.requestEscalationMs ?? 600000,
    acquireInvocation:acquire, releaseInvocation:release,
    onPrepareInvoke:ref=>host.prepare(ref),
    onInvocationRequested:async (job,item) => {
      const ack=await host.recordInvocation(job, {kind:'REQUESTED',at:new Date().toISOString(),
        source_kind:'observed_executor_outcome',source_locator:transport.source_locator});
      if (ack?.status!=='INVOCATION_EVENT_RECORDED') throw new Error('BRIDGE_INVOCATION_RECEIPT_REQUIRED');
    },
    onLongRequest:async (job,item,level,event) => {
      // Check, collect and continue independent work. A slow request retains its
      // actual Promise, attempt and remote permit. There is no timeout retry.
      if (typeof transport.checkStatus==='function') await transport.checkStatus(job,{level,...event});
      if (typeof host.collectAvailable==='function') await host.collectAvailable({exclude_attempt_id:job.attempt_id});
      if (typeof options.onLongRequest==='function') await options.onLongRequest(job,item,level,event);
    }
  });
})
