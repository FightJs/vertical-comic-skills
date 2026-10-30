const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const run=vm.runInNewContext(fs.readFileSync(__dirname+'/../scripts/async_generation.js','utf8'),{setTimeout,clearTimeout,Date,Error});
const canon=v=>v===null||typeof v!=='object'?JSON.stringify(v):Array.isArray(v)?'['+v.map(canon).join(',')+']':'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canon(v[k])).join(',')+'}';
const hash=v=>crypto.createHash('sha256').update(canon(v)).digest('hex');
const ref=i=>({kind:'panel',job_id:'E'+i,book_id:'B',episode_id:'E'+i,panel_id:'P'+i,attempt_id:'A'+i,batch_id:'EPISODE',round_id:1,prepared_input_id:'a'.repeat(64),record_digest:'b'.repeat(64)});
function prepare(r) {
 const job={...r,arguments:{prompt:'测试😀',referenced_image_paths:['/synthetic.png'],transparent_background:false},status:'NOT_RUN',candidate_only:false,input_audit_only:false,dispatch_authorized:true,dispatch_receipt:{permit_id:'permit'+r.panel_id},prepared_reference:{prepared_input_id:r.prepared_input_id,record_digest:r.record_digest}};
 job.submission={policy:'prepared_dispatch_v1',task_id:'task',input_digest:'c'.repeat(64),binding_digest:hash(job.arguments),authority_revision:0};
 const keys=['kind','book_id','episode_id','job_id','panel_id','asset_id','batch_id','round_id','attempt_id','arguments','dispatch_receipt','submission'];
 const ack={policy:'prepared_dispatch_v1',status:'SUBMISSION_REGISTERED',invoke_allowed:true,registration_id:hash(r),scope:{task_id:'task',book_id:r.book_id,episode_id:r.episode_id,job_id:r.job_id},kind:job.kind,panel_id:r.panel_id,attempt_id:r.attempt_id,batch_id:r.batch_id,round_id:r.round_id,permit_id:job.dispatch_receipt.permit_id,input_digest:job.submission.input_digest,binding_digest:job.submission.binding_digest,job_digest:hash(Object.fromEntries(keys.map(k=>[k,job[k]??null])))};
 return {job,ack};
}
(async()=>{
 let calls=0,saved=[];
 const opts={protocol:'prepared_dispatch_v1',onPrepareInvoke:async r=>prepare(r)};
 const result=await run([ref(1),ref(2)],2,async j=>{calls++;assert(j.dispatch_receipt);return{}},async j=>saved.push(j),opts);
 assert.equal(calls,2);assert.equal(saved.length,2);assert(result.every(r=>r.saved_at));
 calls=0;
 await run([ref(1)],1,async()=>{calls++;},async()=>{}, {...opts,onPrepareInvoke:r=>{const a=prepare(r);a.job.arguments.prompt='tampered';return a;}});
 assert.equal(calls,0);
 let i=0;calls=0;
 await run([],2,async()=>{calls++;return{}},async()=>{}, {...opts,nextPrepared:async()=>++i<=3?ref(i):null});
 assert.equal(calls,3);
 let release;const delayed=new Promise(r=>release=r),order=[];
 const executing=run([ref(1),ref(2)],2,async()=>({}),async j=>{if(j.panel_id==='P1')await delayed;order.push(j.panel_id)},opts);
 await new Promise(r=>setTimeout(r,15));assert.deepEqual(order,['P2']);release();await executing;
 let claims=0;calls=0;const invoked=[];
 const waited=await run([ref(1),ref(2)],2,async j=>{calls++;invoked.push(j.panel_id);return{}},async()=>{},
   {...opts,capacityPollMs:100,onPrepareInvoke:r=>r.panel_id==='P1' && ++claims<3?{status:'CAPACITY_FULL'}:prepare(r)});
 assert.equal(calls,2);assert.equal(claims,3);assert.deepEqual(invoked,['P2','P1']);
 assert(waited.every(x=>x.saved_at),'capacity waiting must retain the original static task');
 let pausedChecks=0;calls=0;
 await run([ref(1)],1,async()=>{calls++;return{}},async()=>{},
   {...opts,capacityPollMs:100,onPrepareInvoke:()=>{if(++pausedChecks===1)return{status:'CAPACITY_FULL'};throw new Error('PAUSED');}});
 assert.equal(calls,0,'waiting does not bypass a later pause');
 const createSource=vm.runInNewContext(fs.readFileSync(__dirname+'/../scripts/prepared_input_source.js','utf8'),{setTimeout});
 let finishPreparation,preparationDone=false;
 const preparing=new Promise(r=>finishPreparation=r);const available=[{...ref(1),record_digest:'1'.repeat(64)}];
 const source=createSource({bufferSize:2,pollMs:100,request:async req=>{
   if(req.action==='prepare-inputs'){await preparing;preparationDone=true;return{status:'READY'};}
   return{jobs:available.filter(r=>!req.exclude_record_digests.includes(r.record_digest)).slice(0,req.limit),preparation_complete:preparationDone};
 }});
 calls=0;
 const streamed=await run([],2,async()=>{
   calls++;
   if(calls===1){assert.equal(preparationDone,false);available.push({...ref(2),record_digest:'2'.repeat(64)});finishPreparation();}
   return{};
 },async()=>{}, {...opts,nextPrepared:source.nextPrepared});
 await source.completion;assert.equal(calls,2);assert(streamed.every(x=>x.saved_at));
 console.log('Prepared callback, exact argument hash, stream and independent save lanes PASS (synthetic only)');
})().catch(e=>{console.error(e);process.exitCode=1;});
