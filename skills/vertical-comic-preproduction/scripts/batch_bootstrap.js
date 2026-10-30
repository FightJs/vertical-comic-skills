/* Official tool-host bootstrap. Node owns persistent per-episode hosts; real
   image calls remain in the supported tool binding, never in a shell backend. */
(async function startComicBatch({manifestPath,node,invokeImage,invokeEnvelope,sourceLocator,maxPending,
  onReviewBatchReady,onProgress,observationsByEpisode={},pollMs=100,relayKey,closeOnly=false}) {
  if(typeof node!=='function'||!manifestPath||(!closeOnly &&
      (typeof invokeImage!=='function'&&typeof invokeEnvelope!=='function'||!sourceLocator)))
    throw Error('ACTUAL_HOST_BINDINGS_REQUIRED');
  if(!Number.isInteger(pollMs)||pollMs<100||pollMs>30000)throw Error('RELAY_POLL_INVALID');
  function decode(reply){
    if(reply.isError)throw Error(JSON.stringify(reply));
    if(reply.content){const value=reply.content.filter(c=>c.type==='text').map(c=>c.text).join('\n');return JSON.parse(value);}
    return reply;
  }
  const initial=decode(await node({code:`
    var comicFs=await import('node:fs/promises');
    var comicCp=await import('node:child_process');
    var comicCrypto=await import('node:crypto');
    var comicPath=await comicFs.realpath(${JSON.stringify(manifestPath)});
    var comicManifestBytes=await comicFs.readFile(comicPath,'utf8');
    var comicManifest=JSON.parse(comicManifestBytes);
    var comicDigest=comicCrypto.createHash('sha256').update(comicManifestBytes).digest('hex');
    globalThis.comicBatchRelays ??= new Map();
    var comicKey=${JSON.stringify(relayKey ?? null)};
    var comicRelay=comicKey ? globalThis.comicBatchRelays.get(comicKey) :
      [...globalThis.comicBatchRelays.values()].find(r=>r.manifestPath===comicPath);
    if(comicKey&&!comicRelay)throw Error('RELAY_MISSING_RECONCILE_FIRST');
    if(comicRelay&&(comicRelay.manifestPath!==comicPath||comicRelay.digest!==comicDigest))throw Error('RELAY_MANIFEST_CHANGED');
    if(comicRelay?.busy)throw Error('BATCH_ALREADY_RUNNING');
    if(${JSON.stringify(closeOnly)}) {
      if(comicRelay){await comicRelay.clients.close();globalThis.comicBatchRelays.delete(comicRelay.key);}
      nodeRepl.write(JSON.stringify({status:'HOSTS_CLOSED'}));
    }else{
      var comicReused=!!comicRelay;
      if(comicRelay&&!comicRelay.clients.snapshot().alive){
        // Only after the previous children actually exit can the new owner
        // start. Its normal startup replays durable returns and reconciles state.
        await comicRelay.clients.close();globalThis.comicBatchRelays.delete(comicRelay.key);comicRelay=null;comicReused=false;
      }
      if(!comicRelay){
        var comicStates=new Set(comicManifest.episodes.map(e=>e.state));
        if([...globalThis.comicBatchRelays.values()].some(r=>r.manifest.episodes.some(e=>comicStates.has(e.state))))
          throw Error('STATE_OWNER_ALREADY_EXISTS');
        var comicSources={};
        for(var comicName of ['batch_host_client.js','async_generation.js','image_tool_bridge.js','prepared_input_source.js','batch_runner.js'])
          comicSources[comicName]=await comicFs.readFile(comicManifest.episodes[0].frozen_scripts+'/'+comicName,'utf8');
        comicKey='comic-'+Date.now()+'-'+Math.random().toString(16).slice(2);
        comicRelay={key:comicKey,manifestPath:comicPath,digest:comicDigest,manifest:comicManifest,sources:comicSources,
          clients:(await import((await import('node:url')).pathToFileURL(comicManifest.episodes[0].frozen_scripts+'/batch_host_client.js').href)).default({spawn:comicCp.spawn,python:comicManifest.python,episodes:comicManifest.episodes}),
          completed:[],requests:new Map(),reviews:[],captured:new Map(),serial:0,waiters:new Set(),busy:false};
        comicRelay.notify=((target)=>()=>{for(const wake of target.waiters)wake();target.waiters.clear();})(comicRelay);
        comicRelay.io=await (await import((await import('node:url')).pathToFileURL(comicManifest.episodes[0].frozen_scripts+'/batch_relay.js').href)).default.create(comicRelay);
        globalThis.comicBatchRelays.set(comicKey,comicRelay);
      }
      if(comicRelay.clients.snapshot().pending)throw Error('RELAY_PENDING_RECONCILE_FIRST');
      comicRelay.busy=true;
      nodeRepl.write(JSON.stringify({manifest:comicRelay.manifest,sources:comicRelay.sources,key:comicRelay.key,
        reused:comicReused,hosts:comicRelay.clients.snapshot(),serial:comicRelay.serial,pendingCaptures:[...comicRelay.captured.values()],strandedRequests:comicRelay.io.stranded,recoverableEnvelopes:comicRelay.io.recoverable}));
    }
  `,title:closeOnly?'关闭条漫空闲宿主':'连接条漫常驻宿主'}));
  if(closeOnly)return initial;
  const key=initial.key;let serial=initial.serial,running=false,emptyPolls=0;
  const outbound=[],pending=new Map(),acks=[],staged=new Map();
  const relayMetrics={calls:0,empty:0,upload_calls:0,replayed_exchanges:0,orphan_replies:0};
  const codeBytes=s=>unescape(encodeURIComponent(s)).length;
  // Small metadata takes the normal fast path. Large envelopes are staged as
  // bounded data chunks, never a multi-megabyte executable tool argument.
  async function stage(entry){
    if(entry.staged_parts!==undefined)return entry;
    if(staged.has(entry.id))return staged.get(entry.id);
    const raw=JSON.stringify(entry);
    if(codeBytes(JSON.stringify(raw))<40000)return entry;
    let offset=0,index=0;
    while(offset<raw.length){
      let size=Math.min(32000,raw.length-offset),part=raw.slice(offset,offset+size);
      while(codeBytes(JSON.stringify(part))>40000){size=Math.floor(size/2);part=raw.slice(offset,offset+size);}
      if(/[\uD800-\uDBFF]$/.test(part)){part=part.slice(0,-1);size--;}
      for(let retry=0;;retry++){try{await node({code:`
        await globalThis.comicBatchRelays.get(${JSON.stringify(key)}).io.part(${JSON.stringify(entry.id)},${index},${JSON.stringify(part)});
        nodeRepl.write(JSON.stringify({status:'RELAY_CHUNK_SAVED'}));
      `,title:'分块保全工具返回',timeout_ms:30000});break;}catch(error){if(retry>=2)throw error;}}
      relayMetrics.upload_calls++;offset+=size;index++;
    }
    const ref={id:entry.id,staged_parts:index};staged.set(entry.id,ref);return ref;
  }
  async function exchange(entries,ack,waitMs){
    // A lost tool response may already have executed. Stable IDs and acknowledgements
    // make retrying this transport operation safe; it never retries an image call.
    for(let retry=0;;retry++){
      try{return decode(await node({code:`
        var relay=globalThis.comicBatchRelays.get(${JSON.stringify(key)});
        nodeRepl.write(JSON.stringify(await relay.io.exchange(${JSON.stringify(entries)},${JSON.stringify(ack)},${waitMs})));
      `,title:'等待并批量接收执行结果',timeout_ms:30000}));}
      catch(error){if(retry>=2)throw error;relayMetrics.replayed_exchanges++;}
    }
  }
  async function flush(){
    if(running)return;running=true;
    try{
      while(pending.size){
        const sending=[];let bytes=0;
        // Bound the complete tool code, not just each individual payload.
        while(outbound.length){
          const entry=outbound[0],prepared=await stage(entry),size=codeBytes(JSON.stringify(prepared));
          if(sending.length&&bytes+size>44000)break;
          outbound.shift();sending.push(prepared);bytes+=size;
        }
        const ack=acks.splice(0),waitMs=Math.min(pollMs*2**Math.min(emptyPolls,4),1000);
        const replies=await exchange(sending,ack,waitMs);
        relayMetrics.calls++;if(!replies.length)relayMetrics.empty++;
        emptyPolls=replies.length?0:emptyPolls+1;
        for(const reply of replies){
          acks.push(reply.id);const waiter=pending.get(reply.id);
          if(!waiter){relayMetrics.orphan_replies++;continue;}
          pending.delete(reply.id);reply.error?waiter.reject(Error(reply.error)):waiter.resolve(reply.result);
        }
      }
      if(acks.length)await exchange([],acks.splice(0),0);
    }catch(error){for(const waiter of pending.values())waiter.reject(error);pending.clear();outbound.length=0;}
    finally{running=false;if(pending.size)Promise.resolve().then(flush);}
  }
  const epoch=Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
  const request=(state,payload)=>new Promise((resolve,reject)=>{
    const id=epoch+'-'+(++serial);pending.set(id,{resolve,reject});outbound.push({id,state,payload});Promise.resolve().then(flush);
  });
  const requestStaged=entry=>new Promise((resolve,reject)=>{
    pending.set(entry.id,{resolve,reject});outbound.push({id:entry.id,staged_parts:0});Promise.resolve().then(flush);
  });
  const sources=initial.sources,manifest=initial.manifest;
  const transport={kind:'concurrent_requests',source_locator:sourceLocator,...(maxPending!==undefined?{maxPending}:{}),
    invoke:async job=>{
      if(typeof invokeEnvelope==='function'){
        // The actual adapter supplies locators and observed terminal evidence.
        // Do not manufacture a no-image terminal from an exception or timeout.
        try{return await invokeEnvelope(job.arguments,job);}
        catch(error){if(error?.toolEnvelope && typeof error.toolEnvelope==='object')return error.toolEnvelope;throw error;}
      }
      try{
        const result=await invokeImage(job.arguments,job);
        return {result,call_locator:sourceLocator+' / '+job.attempt_id,result_locator:sourceLocator+' / return / '+job.attempt_id};
      }catch(error){if(error?.toolEnvelope && typeof error.toolEnvelope==='object')return error.toolEnvelope;throw error;}
    }};
  const finalize=async(identity,output)=>decode(await node({code:`
    var comicUtil=await import('node:util');
    var comicDone=await comicUtil.promisify(comicCp.execFile)(${JSON.stringify(manifest.python)},
      ['-B',${JSON.stringify(manifest.episodes[0].frozen_scripts+'/lean_delivery.py')},'--identity',${JSON.stringify(identity)},'--output',${JSON.stringify(output)}],
      {maxBuffer:8*1024*1024});
    nodeRepl.write(comicDone.stdout.trim());
  `,title:'生成图片和 CSV 成品包'}));
  async function publishReview(entries,materials){
    await node({code:`
      globalThis.comicBatchRelays.get(${JSON.stringify(key)}).reviews.push(...${JSON.stringify(materials)});
      nodeRepl.write(JSON.stringify({status:'REVIEW_QUEUE_READY'}));
    `,title:'增量准备实际图片审核'});
    if(onReviewBatchReady)await onReviewBatchReady(entries,materials,{relayKey:key});
  }
  let finished=false;
  try{
    const recoveredEnvelopes=[],envelopeRecoveryErrors=[];
    for(const entry of initial.recoverableEnvelopes??[]){
      try{const cap=await requestStaged(entry);if(cap.status!=='RETURN_CAPTURED')throw Error('RELAY_CAPTURE_RECEIPT_REQUIRED');
        recoveredEnvelopes.push({state:entry.state,job:entry.job,capture:cap.capture});
      }catch(error){envelopeRecoveryErrors.push({id:entry.id,error:String(error)});}
    }
    const replayResults=await Promise.all([...(initial.pendingCaptures ?? []),...recoveredEnvelopes].map(async entry=>{
      try{
        const result=await request(entry.state,{action:'register-return',capture:entry.capture});
        const prepared=await request(entry.state,{action:'prepare-qa',panels:[entry.job.panel_id]});
        await publishReview([{job:entry.job,output_saved:true}],[{episode_id:entry.job.episode_id,prepared}]);
        return {panel_id:entry.job.panel_id,...result};
      }catch(error){return{panel_id:entry.job.panel_id,status:'RETURN_REGISTRATION_PENDING',error:String(error)};}
    }));
    const episodeById=new Map(manifest.episodes.map(e=>[e.episode_id,e]));
    const observationResults=await Promise.all(Object.entries(observationsByEpisode).map(async([episode_id,observations])=>{
      const e=episodeById.get(episode_id);if(!e || !Array.isArray(observations))throw Error('OBSERVATION_EPISODE_SCOPE');
      return {episode_id,...await request(e.state,{action:'review-submit-batch',observations})};
    }));
    const result=await eval(sources['batch_runner.js'])({manifest,request,transport,finalize:manifest.finalize_delivery===false?null:finalize,
      run:eval(sources['async_generation.js']),bridge:eval(sources['image_tool_bridge.js']),
      createSource:eval(sources['prepared_input_source.js']),onProgress,
      onReviewBatchReady:publishReview});
    finished=result.status==='MATERIALS_READY'||!!result.delivery;
    const hostSnapshot=decode(await node({code:`nodeRepl.write(JSON.stringify(globalThis.comicBatchRelays.get(${JSON.stringify(key)}).clients.snapshot()));`,title:'读取实际并发与宿主状态'}));
    return {...result,relayKey:key,manifestPath,observationResults,
      host_reused:initial.reused,host_pids:hostSnapshot.pids,host_snapshot:hostSnapshot,relay_metrics:relayMetrics,replayResults,envelopeRecoveryErrors,strandedRequests:initial.strandedRequests};
  }finally{
    await node({code:`
      var relay=globalThis.comicBatchRelays.get(${JSON.stringify(key)});
      relay.busy=false;
      if(${finished}){await relay.clients.close();globalThis.comicBatchRelays.delete(relay.key);}
      nodeRepl.write(JSON.stringify({status:${JSON.stringify(finished?'HOSTS_CLOSED':'HOSTS_RETAINED')}}));
    `,title:finished?'关闭已完成的执行宿主':'保留宿主供审核续跑'});
  }
})
