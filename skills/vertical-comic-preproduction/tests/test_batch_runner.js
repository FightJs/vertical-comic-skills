const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const load=f=>vm.runInNewContext(fs.readFileSync(__dirname+'/../scripts/'+f,'utf8'),{setTimeout,clearTimeout,Date,Error});
const run=load('async_generation.js'),bridge=load('image_tool_bridge.js');
const canon=v=>v===null||typeof v!=='object'?JSON.stringify(v):Array.isArray(v)?'['+v.map(canon).join(',')+']':'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canon(v[k])).join(',')+'}';
const hash=v=>crypto.createHash('sha256').update(canon(v)).digest('hex');
const ref=(e,p)=>({kind:'panel',job_id:e,book_id:'B',episode_id:e,panel_id:p,attempt_id:e+p,batch_id:'EPISODE',round_id:1,prepared_input_id:'a'.repeat(64),record_digest:'b'.repeat(64)});
function prepare(r){
 const job={...r,arguments:{prompt:'synthetic',referenced_image_paths:[],transparent_background:false},dispatch_authorized:true,prepared_reference:{prepared_input_id:r.prepared_input_id,record_digest:r.record_digest}};
 job.submission={policy:'prepared_dispatch_v1',task_id:'task',input_digest:'c'.repeat(64),binding_digest:hash(job.arguments)};
 const keys=['kind','book_id','episode_id','job_id','panel_id','asset_id','batch_id','round_id','attempt_id','arguments','dispatch_receipt','submission'];
 return {job,ack:{policy:'prepared_dispatch_v1',status:'SUBMISSION_REGISTERED',invoke_allowed:true,registration_id:hash(r),scope:{task_id:'task',book_id:r.book_id,episode_id:r.episode_id,job_id:r.job_id},kind:job.kind,panel_id:r.panel_id,attempt_id:r.attempt_id,batch_id:r.batch_id,round_id:r.round_id,input_digest:job.submission.input_digest,binding_digest:job.submission.binding_digest,job_digest:hash(Object.fromEntries(keys.map(k=>[k,job[k]??null])))}};
}
const tick=()=>new Promise(r=>setTimeout(r,15));
const packet=j=>({result:{image:'synthetic '+j.attempt_id},call_locator:'synthetic://call/'+j.attempt_id,result_locator:'synthetic://result/'+j.attempt_id});

const rawBatch=load('batch_runner.js');
const batch=options=>rawBatch({...options,request:async(state,p)=>{
 if(p.action==='resource-status')return{policy:'machine_resource_admission_v1',hard:{image:1000}};
 if(p.action==='resource-acquire')return{status:'RESOURCE_GRANTED',token:p.key};
 if(p.action==='resource-returned')return{status:'RETURN_PRESSURE_RECORDED'};
 if(p.action==='resource-release')return{status:'RESOURCE_RELEASED'};
 return options.request(state,p);
}});
(async()=>{
 for(const size of [35,165]) {
  const episode={episode_id:'E1',state:'state1',panel_count:size};
  const manifest={book_id:'B',dispatch_mode:'all_ready',episodes:[episode],max_inflight:size};
  let release,calls=0,reviewed=0,closed=0;const held=new Promise(r=>release=r);
  const createSource=({request,workers})=>{assert.equal(workers,'all');let i=0;return{
   nextPrepared:async()=>i<size?ref('E1','P'+i++):null,completion:Promise.resolve(),snapshot:()=>({finished:true})}};
  const request=async(s,p)=>{
   if(p.action==='claim-and-register')return prepare(p.prepared_reference);
   if(p.action==='invocation-event')return{status:'INVOCATION_EVENT_RECORDED'};
   if(p.action==='capture-envelope')return{status:'RETURN_CAPTURED',capture:{}};
   if(p.action==='register-return')return{status:'RETURN_REGISTERED'};
   if(p.action==='prepare-qa')return{items:p.panels.map(panel_id=>({panel_id,qa_template:{path:'synthetic'}}))};
   if(p.action==='delivery-status')return{status:'MATERIALS_READY'};
   throw Error(p.action);
  };
  const executing=batch({manifest,run,bridge,createSource,request,
   transport:{kind:'concurrent_requests',source_locator:'synthetic://batch',invoke:async j=>{calls++;await held;return packet(j)}},
   onReviewBatchReady:async entries=>{reviewed+=entries.length},finalize:async()=>{closed++;return{status:'DELIVERY_FINISHED'}}});
  for(let i=0;i<100&&calls<size;i++)await tick();
  assert.equal(calls,size,'all independent requests before first return');release();const result=await executing;
  assert.equal(result.status,'DELIVERY_FINISHED');assert.equal(reviewed,size);assert.equal(closed,1);
 }
 // A slow episode compiler does not block another episode's generation and review preparation.
 let compileRelease,registrationRelease;const compileHeld=new Promise(r=>compileRelease=r),registrationHeld=new Promise(r=>registrationRelease=r);
 const events=[];
 const multi={book_id:'B',dispatch_mode:'all_ready',episodes:[{episode_id:'E1',state:'s1',panel_count:1},{episode_id:'E2',state:'s2',panel_count:1}]};
 const sourceMulti=({request})=>{let sent=false;return{nextPrepared:async()=>{if(sent)return null;sent=true;return request({action:'synthetic-prepare'})},completion:Promise.resolve(),snapshot:()=>({})}};
 const requestMulti=async(state,p)=>{
  if(p.action==='synthetic-prepare'){if(state==='s1')await compileHeld;return ref(state==='s1'?'E1':'E2','P1')}
  if(p.action==='claim-and-register')return prepare(p.prepared_reference);
  if(p.action==='invocation-event')return{status:'INVOCATION_EVENT_RECORDED'};
  if(p.action==='capture-envelope'){events.push('capture-'+state);return{status:'RETURN_CAPTURED',capture:{}}}
  if(p.action==='register-return'){events.push('register-'+state);if(state==='s1')await registrationHeld;return{status:'RETURN_REGISTERED'}}
  if(p.action==='prepare-qa'){events.push('qa-'+state);return{items:[]}}
  if(p.action==='delivery-status')return{status:'CONTINUE_REQUIRED'};
 };
 const overlapping=batch({manifest:multi,run,bridge,createSource:sourceMulti,request:requestMulti,
  transport:{kind:'concurrent_requests',source_locator:'synthetic://overlap',maxPending:1,invoke:async j=>{events.push('invoke-'+j.episode_id);return packet(j)}},options:{reviewGroupSize:3,reviewMaxWaitMs:10,hostStartDelayMs:0}});
 await tick();assert(events.includes('invoke-E2'));assert(events.includes('capture-s2'));assert(!events.includes('invoke-E1'));
 compileRelease();await tick();registrationRelease();await overlapping;assert(events.includes('qa-s2'));
 // A retry appears after preparation has reached EOF; it must run without another model turn.
 let version=0,calls=0;
 const m={book_id:'B',dispatch_mode:'all_ready',episodes:[{episode_id:'E1',state:'s',panel_count:1}]};
 const source=()=>{let sent=false;const r=ref('E1','P1');r.attempt_id+='-'+version;return{nextPrepared:async()=>{if(sent)return null;sent=true;return r},completion:Promise.resolve(),snapshot:()=>({})}};
 const request=async(s,p)=>{
  if(p.action==='claim-and-register')return prepare(p.prepared_reference);
  if(p.action==='invocation-event')return{status:'INVOCATION_EVENT_RECORDED'};
  if(p.action==='record-envelope'){version++;return{status:'FAILURE_RECORDED',recovery:{status:'NO_IMAGE_RETRY_READY'}}}
  if(p.action==='capture-envelope')return{status:'RETURN_CAPTURED',capture:{}};
  if(p.action==='register-return')return{status:'RETURN_REGISTERED'};
  if(p.action==='prepare-qa')return{items:[]};
  if(p.action==='delivery-status')return{status:'CONTINUE_REQUIRED'};
 };
 const retried=await batch({manifest:m,run,bridge,createSource:source,request,
  transport:{kind:'concurrent_requests',source_locator:'synthetic://retry',invoke:async j=>{calls++;if(calls===1)throw Error('network error');return packet(j)}}});
 assert.equal(calls,2);assert.equal(retried.results.length,2);
 // A scoped preparation rejection cannot deadlock the dynamic EOF tracker.
 const held=await batch({manifest:m,run,bridge,createSource:source,request:async(s,p)=>{
  if(p.action==='claim-and-register')throw Error('PREPARED_PACKAGE_CHANGED');return request(s,p)},
  transport:{kind:'concurrent_requests',source_locator:'synthetic://scope',invoke:async()=>{throw Error('must not invoke')}}});
 assert.equal(held.results[0].status,'NOT_DISPATCHED');
 // Runtime admission can grow above the startup telemetry without restarting.
 let grants=0,activeImages=0,dynamicCalls=0,limit=1,releaseDynamic;
 const untilReleased=new Promise(r=>releaseDynamic=r);
 const adaptiveManifest={book_id:'B',dispatch_mode:'all_ready',max_inflight:4,episodes:[{episode_id:'E1',state:'dynamic',panel_count:4}]};
 const adaptiveSource=()=>{let i=0;return{nextPrepared:async()=>i<4?ref('E1','D'+i++):null,completion:Promise.resolve(),snapshot:()=>({})}};
 const adaptive=rawBatch({manifest:adaptiveManifest,run,bridge,createSource:adaptiveSource,
  request:async(s,p)=>{
    if(p.action==='resource-status')return{policy:'machine_resource_admission_v1',hard:{image:1,host:1},limits:{image:1}};
    if(p.action==='resource-acquire')return activeImages<limit?(activeImages++,grants++,{status:'RESOURCE_GRANTED',token:p.key}):{status:'RESOURCE_WAIT',retry_after_ms:100};
    if(p.action==='resource-release'){activeImages--;return{status:'RESOURCE_RELEASED'}};
    if(p.action==='resource-returned')return{status:'RETURN_PRESSURE_RECORDED'};
    return request(s,p);
  },transport:{kind:'concurrent_requests',source_locator:'synthetic://adaptive',invoke:async j=>{dynamicCalls++;await untilReleased;return packet(j)}}});
 await tick();assert.equal(dynamicCalls,1);limit=4;
 for(let i=0;i<100&&dynamicCalls<4;i++)await tick();
 assert.equal(dynamicCalls,4,'temporary startup hard=1 did not freeze JS workers');assert.equal(grants,4);
 releaseDynamic();await adaptive;
 // A real review callback releases the dependent source before another slow image returns.
 let reviewedAnchor=false,dependentStarted=false,releaseSlow;
 const slow=new Promise(r=>releaseSlow=r),wakeEvents=[];
 const wakeManifest={book_id:'B',dispatch_mode:'all_ready',episodes:[{episode_id:'W1',state:'w1',panel_count:2},{episode_id:'W2',state:'w2',panel_count:1}]};
 const wakeRequest=async(state,p)=>{
   if(p.action==='claim-and-register')return prepare(p.prepared_reference);
   if(p.action==='invocation-event')return{status:'INVOCATION_EVENT_RECORDED'};
   if(p.action==='capture-envelope')return{status:'RETURN_CAPTURED',capture:{}};
   if(p.action==='register-return')return{status:'RETURN_REGISTERED'};
   if(p.action==='prepare-qa')return{items:[]};
   if(p.action==='delivery-status')return{status:'CONTINUE_REQUIRED',dispatch_revision:reviewedAnchor?'reviewed':'initial',runnable:state==='w1'&&reviewedAnchor?[{panel_id:'P2',attempt_id:'W1P2'}]:[]};
   if(p.action==='source-refs')return state==='w1'?(reviewedAnchor?[ref('W1','P2')]:[ref('W1','P1')]):[ref('W2','P1')];
 };
 const wakeSource=({request})=>{let refs;return{nextPrepared:async()=>{refs??=await request({action:'source-refs'});return refs.shift()??null},completion:Promise.resolve(),snapshot:()=>({})}};
 const wakeRun=batch({manifest:wakeManifest,run,bridge,request:wakeRequest,createSource:wakeSource,
   onReviewBatchReady:async entries=>{if(entries.some(e=>e.job.episode_id==='W1'&&e.job.panel_id==='P1'))reviewedAnchor=true},
   transport:{kind:'concurrent_requests',source_locator:'synthetic://wake',invoke:async j=>{wakeEvents.push(j.episode_id+j.panel_id);if(j.episode_id==='W2')await slow;if(j.panel_id==='P2')dependentStarted=true;return packet(j)}},
   options:{reviewGroupSize:3,reviewMaxWaitMs:10,hostStartDelayMs:0}});
 for(let i=0;i<40&&!dependentStarted;i++)await tick();
 const beforeRelease=dependentStarted;releaseSlow();await wakeRun;
 assert(beforeRelease,'review must reopen dependency while unrelated service request remains in flight');
 console.log('Batch runner: 35/165 full concurrent start, grouped review, automatic finalization, post-EOF retry, scoped failure PASS (synthetic only)');
})().catch(e=>{console.error(e);process.exitCode=1});
