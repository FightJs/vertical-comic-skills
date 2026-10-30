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
(async()=>{
 let release;const slow=new Promise(r=>release=r),registered=[],saved=[],calls=[];
 const jobs=[ref('E1','P1'),ref('E1','P2'),ref('E2','P1'),ref('E2','P2')];
 const host={prepare:r=>{registered.push(r.attempt_id);return prepare(r)},recordInvocation:async()=>({status:'INVOCATION_EVENT_RECORDED'}),save:async(j,p)=>{assert(p.call_locator);saved.push(j.attempt_id);return{status:'SAVED'}}};
 const executing=bridge({run,jobs,confirmedConcurrency:132,transport:{source_locator:'synthetic://executor',channels:[{id:'one',invoke:async j=>{calls.push(j.attempt_id);await slow;return packet(j)}}]},host});
 await tick();assert.equal(registered.length,1,'no whole episode pre-registration');release();await executing;
 assert.deepEqual(calls,['E1P1','E2P1','E1P2','E2P2'],'episode fairness');
 let finish;const stuck=new Promise(r=>finish=r);saved.length=0;let warnings=0;
 const active=bridge({run,jobs,confirmedConcurrency:2,transport:{source_locator:'synthetic://executor',channels:[{id:'a',invoke:async j=>{if(j.attempt_id==='E1P1')await stuck;return packet(j)}},{id:'b',invoke:async j=>packet(j)}],checkStatus:async()=>warnings++},host,options:{requestWarningMs:3,requestEscalationMs:8}});
 await tick();assert(saved.includes('E2P1'));assert(saved.includes('E1P2'));assert(!saved.includes('E1P1'));assert(warnings>=1);finish();await active;
 // A slow registration no longer holds the only real invocation channel.
 let unblock;const blocked=new Promise(r=>unblock=r);let invoked=0;
 const fastHost={...host,capture:async(j)=>({status:'RETURN_CAPTURED',capture:{path:j.attempt_id}}),
   register:async(j)=>{if(j.attempt_id==='E1P1')await blocked;return {status:'UPDATES_SAVED'}}};
 const pipeline=bridge({run,jobs:[ref('E1','P1'),ref('E1','P2')],confirmedConcurrency:1,
   transport:{source_locator:'synthetic://executor',channels:[{id:'one',invoke:async j=>{invoked++;return packet(j)}}]},host:fastHost});
 await tick();assert.equal(invoked,2,'second call begins while first registration is blocked');
 unblock();const piped=await pipeline;assert(piped.every(x=>x.output_saved));
 assert(piped.every(x=>x.result.persisted_return && !x.bridge_packet),'durable returns must not retain all raw images');
 // One machine permit shared by multiple local request slots. Local backpressure
 // must precede registration; a reduction must not cancel already invoked work.
 let permits=0,peakPermits=0,machineCalls=0;const granted=new Set();
 const adaptiveHost={...fastHost,acquireResource:async job=>{
   if(permits>=1)return{status:'RESOURCE_WAIT',retry_after_ms:100};
   const token=job.attempt_id;permits++;peakPermits=Math.max(peakPermits,permits);granted.add(token);
   return{status:'RESOURCE_GRANTED',token};
 },releaseResource:async(job,token)=>{assert(granted.delete(token));permits--;return{status:'RESOURCE_RELEASED'}},
 resourceReturned:async(job,token,bytes)=>{assert(granted.has(token));assert(bytes>0);},
 register:async()=>({status:'RETURN_REGISTERED'})};
 const limited=await bridge({run,jobs,confirmedConcurrency:4,
 transport:{kind:'concurrent_requests',source_locator:'synthetic://machine',invoke:async j=>{
   assert(granted.has(j.attempt_id));machineCalls++;await tick();return packet(j);
 }},host:adaptiveHost});
 assert.equal(machineCalls,4);assert.equal(peakPermits,1);assert.equal(permits,0);assert(limited.every(x=>x.output_saved));
 let countIndependent=0;
 const isolated=await bridge({run,jobs:[ref('E1','P1'),ref('E1','P2')],confirmedConcurrency:1,
   transport:{source_locator:'synthetic://executor',channels:[{id:'one',invoke:async j=>{countIndependent++;return packet(j)}}]},
   host:{...fastHost,register:async j=>{if(j.panel_id==='P1')throw new Error('panel registration fault');return {status:'UPDATES_SAVED'}}}});
 assert.equal(countIndependent,2);assert(isolated[0].registration_error);assert(isolated[1].output_saved);
 let realCalls=0;
 const scoped=await bridge({run,jobs:[ref('E1','P1'),ref('E2','P1')],confirmedConcurrency:1,transport:{source_locator:'synthetic://executor',channels:[{id:'a',invoke:async j=>{realCalls++;return packet(j)}}]},host:{...host,prepare:r=>{if(r.episode_id==='E1')throw new Error('PREPARED_PACKAGE_CHANGED');return prepare(r)}}});
 assert.equal(realCalls,1);assert.equal(scoped[0].status,'NOT_DISPATCHED');assert(scoped[1].saved_at);
 const failed=await bridge({run,jobs:[ref('E1','P1')],confirmedConcurrency:1,transport:{source_locator:'synthetic://executor',channels:[{id:'a',invoke:async j=>packet(j)}]},host:{...host,save:async()=>{throw new Error('disk failed')}}});
 assert(failed[0].persistence_error);assert(failed[0].bridge_packet.result.image);
 // Settled network errors are per-panel; unknown returns retain the service circuit.
 for (const settled of [true,false]) {
   let invoked=0;
   const batch=Array.from({length:6},(_,i)=>ref('E1','N'+i));
   await bridge({run,jobs:batch,confirmedConcurrency:1,
     transport:{source_locator:'synthetic://network',channels:[{id:'n',invoke:async()=>{
       invoked++;throw new Error('image generation failed: network error: error sending request');
     }}]},host:{...host,save:async()=>({status:settled?'FAILURE_RECORDED':'UNKNOWN_RECORDED'})}});
   assert.equal(invoked,settled?6:3,'only formally settled failures continue independent work');
 }
 for (const size of [35,165]) {
   const batch=Array.from({length:size},(_,i)=>ref('E'+Math.floor(i/(size/5)),'P'+i));
   const trace=[];let busy=0,peak=0,count=0;
   const channels=Array.from({length:3},(_,i)=>({id:'lane'+i,invoke:async j=>{
     busy++;peak=Math.max(peak,busy);await Promise.resolve();busy--;return packet(j);
   }}));
   const completed=await bridge({run,jobs:batch,confirmedConcurrency:132,transport:{source_locator:'synthetic://sample',channels},
     host:{...host,prepare:r=>{trace.push(r.episode_id);return prepare(r)},save:async()=>{count++;return{status:'SAVED'}}}});
   assert.equal(count,size);assert.equal(completed.length,size);assert(peak<=3);
   assert.equal(new Set(trace.slice(0,5)).size,5,'all ready episodes receive early turns');
 }
 console.log('Bridge: bounded registration, fair episodes, independent returns, long-call observation, scoped failure and raw preservation PASS; synthetic only');
})().catch(e=>{console.error(e);process.exitCode=1});
