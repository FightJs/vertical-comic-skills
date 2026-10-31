/* Evaluate once in the supported tool host. All tool/I/O bindings are injected;
   no shell image backend, implicit model call, or fabricated visual observation. */
(async function runComicBatch({manifest, run, bridge, createSource, request, transport,
  onReviewBatchReady, onProgress, finalize, options={}}) {
  if (!manifest || manifest.dispatch_mode!=='all_ready' || !Array.isArray(manifest.episodes) ||
      !manifest.episodes.length || [run,bridge,createSource,request].some(f=>typeof f!=='function'))
    throw new Error('BATCH_RUNNER_BINDINGS_REQUIRED');
  const episodes=manifest.episodes;
  if (new Set(episodes.map(e=>e.episode_id)).size!==episodes.length ||
      episodes.some(e=>!e.state || !e.episode_id || !Number.isInteger(e.panel_count) || e.panel_count<1))
    throw new Error('BATCH_EPISODE_SCOPE');
  const total=episodes.reduce((n,e)=>n+e.panel_count,0);
  let ceiling=manifest.max_inflight ?? total;
  if (!Number.isInteger(ceiling) || ceiling<1 || ceiling>total) throw new Error('BATCH_CAPACITY_INVALID');
  const resources=await request(episodes[0].state,{action:'resource-status'});
  if(resources?.policy!=='machine_resource_admission_v1'||!Number.isInteger(resources.hard?.image))throw Error('MACHINE_RESOURCE_HOST_REQUIRED');
  // Local workers are lightweight promises; the shared machine permit is checked
  // for every invocation, allowing recovery above the startup observation.
  const states=new Map(episodes.map(e=>[e.episode_id,e.state]));
  const route=async(job,payload)=>{
    const state=states.get(job.episode_id);
    if (!state || job.book_id!==manifest.book_id) throw new Error('BATCH_JOB_SCOPE');
    return request(state,payload);
  };
  const sources=[];let machineView=resources,preparingCount=0;
  const hostStartDelay=options.hostStartDelayMs ?? 2000;
  if(!Number.isInteger(hostStartDelay)||hostStartDelay<0)throw Error('HOST_START_DELAY_INVALID');
  const queue=[],waiters=[],preparationErrors=[];
  const seen=new Set(options.seenAttempts ?? []),queuedKeys=new Set();
  const reviewRevisions=new Map();
  const attemptKey=ref=>JSON.stringify([ref.episode_id,ref.panel_id,ref.attempt_id]);
  let remaining=episodes.length,outstanding=0,stopped=false,reviewPending=0;
  const capacities=new Map(), resourceWait=new Set(),localBlocks=new Map();
  let lastBlock;
  function scheduling(event={}) {
    const reasons=[];
    if(ceiling<total)reasons.push('MANIFEST_LIMIT');
    if(resourceWait.size)reasons.push('RESOURCE_PRESSURE');
    if([...capacities.values()].some(c=>c.status==='WAIT_CAPACITY_ASSIGNMENT'||c.limiting_reason==='SERVICE_OR_JOB_CAPACITY'))reasons.push('LEASE_LIMIT');
    if(!queue.length&&preparingCount)reasons.push('INPUT_NOT_READY');
    if(reviewPending)reasons.push('REVIEW_BARRIER');
    for(const source of sources){
      const blocked=JSON.stringify(source.snapshot()?.latest?.blocked_panels??[]);
      if(/WAIT_NEW_STATE_APPROVAL|state_review/.test(blocked))reasons.push('REVIEW_BARRIER');
      else if(/DEPENDENCY|predecessor/.test(blocked))reasons.push('DEPENDENCY');
      if(/user_reserved|retained_user/.test(blocked))reasons.push('USER_REVIEW');
      if(/APPROVAL|AUTHORITY/.test(blocked)&&!/WAIT_NEW_STATE_APPROVAL/.test(blocked))reasons.push('AUTHORITY_CHANGED');
    }
    reasons.push(...localBlocks.values());
    const unique=[...new Set(reasons)].sort();
    const signature=JSON.stringify(unique);const changed=signature!==lastBlock;lastBlock=signature;
    return {ready_jobs:queue.length,machine_allowed:machineView.limits?.image??null,manifest_limit:ceiling,
      tool_capacity:null,actual_in_flight:event.in_flight??null,pending_save:event.returned===undefined?null:event.returned-event.persisted,
      production_capacity:Object.fromEntries(capacities),block_reasons:unique,block_changed:changed};
  }
  function wake(){while(waiters.length)waiters.shift()();}
  async function pump(source,index){
    try {
      while(true){const ref=await source.nextPrepared();if(ref===null)break;
        const key=attemptKey(ref);if(seen.has(key)||queuedKeys.has(key))continue;queuedKeys.add(key);queue.push(ref);wake();}
      await source.completion;
    } catch(error){preparationErrors.push({episode_id:episodes[index].episode_id,error:String(error)});}
    finally {remaining--;preparingCount--;wake();}
  }
  const pumps=[];
  function startEpisode(index,panels){
    const e=episodes[index];preparingCount++;
    const source=createSource({request:p=>request(e.state,p),panels:panels??e.panels,
      workers:manifest.compile_workers ?? 'all',bufferSize:e.panel_count});
    sources.push(source);pumps.push(pump(source,index));
  }
  startEpisode(0);
  const activation=(async()=>{
    let next=1,last=Date.now();
    while(next<episodes.length&&!stopped){
      const target=Math.min(ceiling,machineView.limits?.image??machineView.hard.image);
      // An episode already supplying enough work needs no additional interpreter.
      // Start another only to fill a real shortage, with machine-wide host admission.
      if(queue.length+outstanding-resourceWait.size<target && preparingCount<(machineView.hard.host??episodes.length)
          && Date.now()-last>=hostStartDelay){startEpisode(next++);last=Date.now();}
      else await new Promise(resolve=>setTimeout(resolve,Math.max(1,Math.min(hostStartDelay,250))));
    }
    if(stopped){remaining-=episodes.length-next;wake();}
  })();
  function enqueueRetry(job){
    const index=episodes.findIndex(e=>e.episode_id===job.episode_id),e=episodes[index];
    remaining++;startEpisode(index,[job.panel_id]);
  }
  async function nextPrepared(){
    while(!queue.length){if(stopped || (!remaining && !outstanding && !reviewPending))return null;await new Promise(resolve=>waiters.push(resolve));}
    if(stopped)return null;
    outstanding++;const ref=queue.shift();queuedKeys.delete(attemptKey(ref));seen.add(attemptKey(ref));return ref;
  }
  // Host responses remain authoritative. Jobs/raw returns are bound by the existing host.
  const host={
    acquireResource:async ref=>{
      const value=await route(ref,{action:'resource-acquire',key:JSON.stringify([ref.episode_id,ref.panel_id,ref.attempt_id])});
      if(value.limits&&value.hard)machineView=value;
      if(value.production_capacity)capacities.set(ref.episode_id,value.production_capacity);
      const key=attemptKey(ref);if(value.token)resourceWait.delete(key);else resourceWait.add(key);wake();return value;
    },
    releaseResource:(job,token,details)=>route(job,{action:'resource-release',token,...details}),
    resourceReturned:(job,token,bytes)=>route(job,{action:'resource-returned',token,bytes}),
    prepare:ref=>route(ref,{action:'claim-and-register',prepared_reference:ref}),
    recordInvocation:(job,event)=>route(job,{action:'invocation-event',job,event}),
    capture:(job,packet,item)=>route(job,{action:'capture-envelope',job,packet,resource_token:item.machine_resource_token,item:{
      submitted_at:item.submitted_at,returned_at:item.returned_at,save_started_at:item.save_started_at}}),
    register:(job,capture)=>route(job,{action:'register-return',capture}),
    save:async(job,packet,item)=>{const saved=await route(job,{action:'record-envelope',job,packet,
      authorization:episodes.find(e=>e.episode_id===job.episode_id).recovery_authorization,item:{
      status:item.status,error:item.error,reason:item.reason,outcome_hint:item.outcome_hint,call_locator:transport.source_locator+' / '+job.attempt_id,
      submitted_at:item.submitted_at,returned_at:item.returned_at}});
      if(saved.recovery?.status==='NO_IMAGE_RETRY_READY')enqueueRetry(job);
      return saved;
    }
  };
  async function review(entries){
    reviewPending++;
    try {
    const byEpisode=new Map();
    for(const entry of entries){const e=entry.job.episode_id;if(!byEpisode.has(e))byEpisode.set(e,[]);byEpisode.get(e).push(entry);}
    const materials=await Promise.all([...byEpisode].map(async([episode_id,items])=>({episode_id,
      prepared:await request(states.get(episode_id),{action:'prepare-qa',panels:items.map(i=>i.job.panel_id)})})));
    if(onReviewBatchReady)await onReviewBatchReady(entries,materials);
    // Read only small incremental state. Changed observed approvals/adoptions can
    // reopen a drained source while other image requests are still running.
    for(const [episode_id] of byEpisode){
      const status=await request(states.get(episode_id),{action:'delivery-status'});
      if(status.dispatch_revision && reviewRevisions.get(episode_id)!==status.dispatch_revision){
        reviewRevisions.set(episode_id,status.dispatch_revision);
        const panels=(status.runnable??[]).filter(r=>!seen.has(attemptKey({...r,episode_id}))&&!queuedKeys.has(attemptKey({...r,episode_id}))).map(r=>r.panel_id);
        const index=episodes.findIndex(e=>e.episode_id===episode_id);
        if(panels.length){remaining++;startEpisode(index,panels);}
      }
    }
    } finally {reviewPending--;wake();}
  }
  const results=await bridge({run,jobs:[],confirmedConcurrency:ceiling,transport,host,
    options:{...options,nextPrepared,onProgress:onProgress?event=>onProgress({...event,ready_episodes:new Set(queue.map(r=>r.episode_id)).size,preparing_episodes:preparingCount,machine:machineView,scheduling:scheduling(event)}):undefined,onReviewBatchReady:review,
      onJobSettled:async(job,item,event)=>{outstanding--;resourceWait.delete(attemptKey(job));stopped ||= event.stopped;
        if(item.persistence_error)localBlocks.set(attemptKey(job),'SAVE_FAILURE');
        else if(item.outcome_hint==='RESULT_UNKNOWN')localBlocks.set(attemptKey(job),'RESULT_UNKNOWN');
        else if(item.status==='NOT_DISPATCHED')localBlocks.set(attemptKey(job),/AUTHORITY|APPROVAL/.test(item.reason??'')?'AUTHORITY_CHANGED':'HOST_ERROR');
        if(item.status==='REPAIR_DEFERRED')seen.delete(attemptKey(job));wake();
        if(options.onJobSettled)await options.onJobSettled(job,item,event);}}});
  // Successful raw returns already live in the host's durable store. Do not send
  // hundreds of base64 images back through a model-visible scheduling report.
  // A failed persistence retains its real packet for recovery.
  for(const item of results)if(item.saved_at && !item.persistence_error){
    delete item.result;delete item.bridge_packet;delete item.registration_pending;
  }
  await activation;
  await Promise.allSettled(pumps);
  const sourceStates=sources.map(s=>s.snapshot());
  const statuses=await Promise.all(episodes.map(e=>request(e.state,{action:'delivery-status'})));
  const complete=statuses.every(s=>s.status==='MATERIALS_READY');
  if (complete && typeof finalize==='function') {
    const delivery=await finalize(manifest.delivery_identity,manifest.output);
    return {status:delivery.status,delivery,results,sourceStates,preparationErrors};
  }
  if(complete)return{status:'MATERIALS_READY',results,sourceStates,statuses,preparationErrors};
  const continuation=episodes.map((e,i)=>({...e,panels:(statuses[i].runnable ?? []).filter(r=>!seen.has(attemptKey({...r,episode_id:e.episode_id}))).map(r=>r.panel_id)})).filter(e=>e.panels.length);
  // Only observed state changes (dependency adoption / authorized repair) can add work.
  // An unchanged blocked panel gets one pass per run; it cannot spin forever.
  if(!stopped && !preparationErrors.length && continuation.length && results.some(r=>r.output_saved)) {
    const next=await runComicBatch({manifest:{...manifest,episodes:continuation,max_inflight:Math.min(ceiling,continuation.reduce((n,e)=>n+e.panel_count,0))},
      run,bridge,createSource,request,transport,onReviewBatchReady,onProgress,finalize:null,options:{...options,seenAttempts:[...seen]}});
    results.push(...next.results);preparationErrors.push(...next.preparationErrors);
    const latest=await Promise.all(episodes.map(e=>request(e.state,{action:'delivery-status'})));
    if(!preparationErrors.length && latest.every(s=>s.status==='MATERIALS_READY') && typeof finalize==='function') {
      const delivery=await finalize(manifest.delivery_identity,manifest.output);return{status:delivery.status,delivery,results,sourceStates,preparationErrors};
    }
  }
  return {status:'CONTINUE_REQUIRED',results,sourceStates,statuses,preparationErrors,
    next_action:'SUBMIT_ACTUAL_OBSERVATIONS_OR_RESOLVE_SCOPED_FAILURES',image_calls:results.filter(r=>r.invocation_requested_at).length};
})
