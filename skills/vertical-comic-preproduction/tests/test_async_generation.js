const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../scripts/async_generation.js'), 'utf8');
// functions.exec exposes timeout timers, not interval timers.
const rawRun = require('node:vm').runInNewContext(source, {setTimeout,clearTimeout,Date,Error});

// Unit-only registration adapter. Boundary integration tests use real Python writers.
const crypto = require('node:crypto');
const fixtureJob = j => ({...j,kind:j.kind??'panel',book_id:j.book_id??'BOOK',episode_id:j.episode_id??'E001',
  arguments:j.arguments??{},submission:j.submission??{policy:'durable_image_submission_v1',task_id:'SYNTHETIC',input_digest:'a'.repeat(64)}});
const fixtureAck = j => ({policy:'durable_image_submission_v1',status:'SUBMISSION_REGISTERED',invoke_allowed:true,
 registration_id:crypto.createHash('sha256').update(JSON.stringify([j.job_id,j.panel_id,j.asset_id,j.attempt_id])).digest('hex'),
 scope:{task_id:j.submission.task_id,book_id:j.book_id,episode_id:j.episode_id,job_id:j.job_id},
 kind:j.kind,panel_id:j.panel_id,asset_id:j.asset_id,batch_id:j.batch_id,round_id:j.round_id,attempt_id:j.attempt_id,
 input_digest:j.submission.input_digest,permit_id:j.dispatch_receipt?.permit_id});
const run = (jobs,limit,invoke,onResult,options={}) => rawRun(jobs.map(fixtureJob),limit,invoke,onResult,
 {onBeforeInvoke:async j=>fixtureAck(j),...options});

const jobs = n => Array.from({length:n},(_,i)=>({job_id:'TEST',panel_id:`P${i+1}`,batch_id:'H001',round_id:1,attempt_id:`A${i+1}`}));
const sleep = ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 let active=0, peak=0, saving=0, savePeak=0, saved=[];
 const result = await run(jobs(18),18,async j=>{active++;peak=Math.max(peak,active);await sleep(20+(18-Number(j.panel_id.slice(1))));active--;return j.attempt_id},async(j,r)=>{saving++;savePeak=Math.max(savePeak,saving);await sleep(1);saved.push(r.panel_id);saving--});
 assert.equal(peak,18);assert.equal(savePeak,1);assert.equal(saved.length,18);
 assert.deepEqual(result.map(r=>r.panel_id),jobs(18).map(j=>j.panel_id));
 assert.equal(result[0].result,'A1');assert.notEqual(saved[0],'P1');
 active=0;peak=0;
 await run(jobs(15),3,async()=>{active++;peak=Math.max(peak,active);await sleep(2);active--;return {}},async()=>{});assert.equal(peak,3);
 const failed=await run(jobs(4),4,async j=>{if(j.panel_id==='P2')throw Error('fake rejection');return j.panel_id},async()=>{});
 assert.equal(failed.length,4);assert.equal(failed[1].status,'REJECTED');assert.equal(failed[3].status,'FULFILLED');
 await assert.rejects(()=>run([jobs(1)[0],jobs(1)[0]],2,async()=>{},async()=>{}));
 let invoked=0;
 const candidateOnly=jobs(1);candidateOnly[0].candidate_only=true;
 await assert.rejects(()=>run(candidateOnly,1,async()=>{invoked++},async()=>{}),/CANDIDATE_HOLD/);
 assert.equal(invoked,0);
 const overBudget=jobs(1);overBudget[0].arguments={referenced_image_paths:['/1','/2','/3','/4','/5','/6']};
 await assert.rejects(()=>run(overBudget,1,async()=>{invoked++},async()=>{}),/REFERENCE_LIMIT_HOLD/);assert.equal(invoked,0);
 const duplicateRefs=jobs(1);duplicateRefs[0].arguments={referenced_image_paths:['/same','/same']};
 await assert.rejects(()=>run(duplicateRefs,1,async()=>{invoked++},async()=>{}),/REFERENCE_DUPLICATE_HOLD/);assert.equal(invoked,0);
 const withinBudget=jobs(1);withinBudget[0].arguments={referenced_image_paths:['/1','/2','/3','/4','/5']};
 await run(withinBudget,1,async()=>{invoked++},async()=>{});assert.equal(invoked,1);
 const stopped=await run(jobs(10),2,async()=>{await sleep(2);return {}},async()=>{throw Error('fake persistence failure')});
 assert(stopped.some(r=>r.persistence_error));assert(stopped.some(r=>r.status==='NOT_DISPATCHED'));
 assert.equal(stopped.filter(r=>r.submitted_at).length,2);
 let readyBeforeAll=false, completed=0;
 await run(jobs(2),2,async j=>{await sleep(j.panel_id==='P1'?3:30);completed++;return j.panel_id},async()=>{}, {onReviewReady:async(j)=>{if(j.panel_id==='P1')readyBeforeAll=completed<2;await sleep(2)}});
 assert(readyBeforeAll);
 let started=0;
 await run(jobs(3),1,async()=>{started++;await sleep(1);return {}},async()=>{}, {onReviewReady:async()=>{await sleep(20);assert.equal(started,3)}});
 const signalFailure=await run(jobs(1),1,async()=>({}),async()=>{}, {onReviewReady:()=>{throw Error('fake review notification')}});
 assert(signalFailure[0].review_signal_error);assert.equal(signalFailure[0].status,'FULFILLED');
 const raw=Error('error decoding response body '+ 'x'.repeat(9000),{cause:Error('nested transport cause')});raw.code='DECODE';raw.status=502;raw.request_id='SYNTHETIC-ONLY';raw.body={details:'complete body'};
 const unknown=await run(jobs(1),1,async()=>{throw raw},async()=>{});
 assert.equal(unknown[0].outcome_hint,'RESULT_UNKNOWN');assert.equal(unknown[0].error.message,raw.message);assert.equal(unknown[0].error.body.details,'complete body');assert.equal(unknown[0].error.cause.message,'nested transport cause');assert.equal(unknown[0].error.request_id,'SYNTHETIC-ONLY');
 let circuitCalls=0;
 const circuit=await run(jobs(8),1,async()=>{circuitCalls++;throw Error('connection failed')},async()=>{});
 assert.equal(circuitCalls,3);assert.equal(circuit.filter(x=>x.status==='NOT_DISPATCHED').length,5);assert.equal(circuit[2].dispatch_stop_reason,'SERVICE_ERROR_CIRCUIT');
 const assets=await run([{kind:'asset',job_id:'ASSET',asset_id:'NEW-VIEW',attempt_id:'A1'}],1,async()=>({isError:true,content:[{type:'text',text:'error sending request'}]}),async()=>{});
 assert.equal(assets[0].asset_id,'NEW-VIEW');assert.equal(assets[0].transport_status,'FULFILLED');assert.equal(assets[0].status,'REJECTED');assert.equal(assets[0].outcome_hint,'RESULT_UNKNOWN');assert.equal(assets[0].result.isError,true);
 let emptySignals=0;
 const empty=await run(jobs(1),1,async()=>undefined,async()=>{}, {onReviewReady:()=>{emptySignals++}});
 assert.equal(empty[0].outcome_hint,'NO_RESULT_CAPTURED');assert.equal(emptySignals,0);
 assert.equal(stopped[0].persistence_error_detail.message,'fake persistence failure');
 const batches=[];
 const grouped=await run(jobs(9),9,async()=>{await sleep(2);return {}},async()=>{},
   {onReviewBatchReady:entries=>{batches.push(entries.map(e=>e.job.panel_id))},reviewGroupSize:4});
 assert.deepEqual(batches.map(b=>b.length),[4,4,1]);
 assert(grouped.every(r=>r.saved_at && r.returned_at && r.submitted_at));
 let priorityBeforeEnd=false, priorityEnded=0;
 const priority=jobs(2);priority[0].review_priority=true;
 await run(priority,2,async j=>{await sleep(j.panel_id==='P1'?1:20);priorityEnded++;return {}},async()=>{},
   {onReviewBatchReady:entries=>{if(entries[0].job.panel_id==='P1')priorityBeforeEnd=priorityEnded<2}});
 assert(priorityBeforeEnd);
 let timerBeforeEnd=false, timerEnded=0;
 await run(jobs(2),2,async j=>{await sleep(j.panel_id==='P1'?1:20);timerEnded++;return {}},async()=>{},
   {reviewMaxWaitMs:2,onReviewBatchReady:entries=>{if(entries[0].job.panel_id==='P1')timerBeforeEnd=timerEnded<2}});
 assert(timerBeforeEnd);
 const groupSignalFailure=await run(jobs(3),3,async()=>({}),async()=>{},
   {onReviewBatchReady:()=>{throw Error('fake grouped notification')}});
 assert(groupSignalFailure.every(r=>r.review_signal_error && r.status==='FULFILLED'));
 const longSignals=[];
 const slow=await run(jobs(2),2,async j=>{await sleep(j.panel_id==='P1'?24:2);return j.panel_id},async()=>{},
   {requestWarningMs:5,requestEscalationMs:12,onLongRequest:(j,item,level,meta)=>{longSignals.push([j.panel_id,level,item.attempt_id,meta.event_id])}});
 assert.deepEqual(longSignals.map(x=>x.slice(0,2)),[['P1','T1'],['P1','T2']]);
 assert.equal(longSignals[1][3],'request:P1:A1:T2');
 assert(slow.every(x=>x.status==='FULFILLED' && x.saved_at));
 let heldResolve;
 const held=new Promise(resolve=>{heldResolve=resolve});
 const stillRunning=run(jobs(1),1,async()=>held,async()=>{},
   {requestWarningMs:3,requestEscalationMs:7,onLongRequest:()=>{}});
 await sleep(11);
 heldResolve({ok:true});
 assert.equal((await stillRunning)[0].result.ok,true);
 await assert.rejects(()=>run(jobs(1),1,async()=>{},async()=>{},
   {requestWarningMs:10,requestEscalationMs:10}),/watchdog thresholds/);
 let metadataWriters=0, metadataPeak=0, timed=0;
 const timedJobs=jobs(4);timedJobs.forEach(j=>{j.ready_at='2026-01-01T00:00:00Z'});
 await run(timedJobs,4,async()=>({}),async()=>{}, {onPersisted:async(j,item)=>{
   metadataWriters++;metadataPeak=Math.max(metadataPeak,metadataWriters);
   assert(item.saved_at && item.save_started_at && item.returned_at && item.ready_at);
   assert(Date.parse(item.returned_at)<=Date.parse(item.save_started_at));
   assert(Date.parse(item.save_started_at)<=Date.parse(item.saved_at));
   await sleep(1);timed++;metadataWriters--;
 }});
 assert.equal(timed,4);assert.equal(metadataPeak,1);
 const metadataFailure=await run(jobs(3),1,async()=>({}),async()=>{}, {onPersisted:()=>{throw Error('metadata persistence failure')}});
 assert(metadataFailure[0].persistence_error);assert.equal(metadataFailure[1].status,'NOT_DISPATCHED');
 // Candidate input refresh uses the real persistence lane, with no image retry.
 const boundJobs=n=>jobs(n).map(j=>({...j,book_id:'BOOK',episode_id:'E001'}));
 const ack={status:'BOUND_NOT_DISPATCHABLE',dispatch_authorized:false,
   scope:{book_id:'BOOK',episode_id:'E001'},head_sha256:'a'.repeat(64),
   state_sha256:'b'.repeat(64),control_sha256:'c'.repeat(64)};
 const phases=new Map();let writers=0,writerPeak=0;
 const lane=async(fn)=>{writers++;writerPeak=Math.max(writerPeak,writers);try{await Promise.resolve();fn()}finally{writers--}};
 const refreshed=await run(boundJobs(3),3,async()=>({}),
   async j=>lane(()=>phases.set(j.panel_id,'saved')),
   {onPersisted:async j=>lane(()=>{assert.equal(phases.get(j.panel_id),'saved');phases.set(j.panel_id,'timed')}),
    onInputHeadRefresh:async(j,item)=>{let value;await lane(()=>{
      assert.equal(phases.get(j.panel_id),'timed');assert(item.saved_at);value=ack;
    });return value}});
 assert.equal(writerPeak,1);assert(refreshed.every(r=>r.input_read_head===ack));
 let refreshCalls=0,saveCalls=0,reviewCalls=0,headInvocations=0;
 let secondRelease,secondStarted;
 const secondRunning=new Promise(resolve=>{secondStarted=resolve});
 const secondResult=new Promise(resolve=>{secondRelease=resolve});
 const refreshFailure=await run(boundJobs(4),2,async j=>{
   headInvocations++;if(j.panel_id==='P2'){secondStarted();return secondResult}return {};
 },async()=>{saveCalls++},{onInputHeadRefresh:async()=>{
   refreshCalls++;await secondRunning;secondRelease({});throw Error('synthetic head CAS conflict');
 },onReviewReady:()=>{reviewCalls++}});
 assert.equal(headInvocations,2);assert.equal(saveCalls,2);assert.equal(refreshCalls,2);assert.equal(reviewCalls,2);
 assert(refreshFailure.slice(0,2).every(r=>r.saved_at && r.input_head_refresh_error && r.status==='FULFILLED'));
 assert(refreshFailure.slice(2).every(r=>r.status==='NOT_DISPATCHED'));
 assert.deepEqual(refreshFailure.slice(0,2).map(r=>r.attempt_id),['A1','A2']);
 for(const badAck of [undefined,{...ack,dispatch_authorized:true},{...ack,scope:{book_id:'OTHER',episode_id:'E001'}},
                      {...ack,state_sha256:'invalid'}]){
   let calls=0;
   const rejected=await run(boundJobs(2),1,async()=>{calls++;return {}},async()=>{}, {onInputHeadRefresh:()=>badAck});
   assert.equal(calls,1);assert(rejected[0].saved_at && rejected[0].input_head_refresh_error);
   assert.equal(rejected[1].status,'NOT_DISPATCHED');
 }
 let preflightInvocations=0;
 await assert.rejects(()=>rawRun(jobs(1).map(j=>({...j,submission:{policy:'durable_image_submission_v1',task_id:'S',input_digest:'a'.repeat(64)}})),1,async()=>{preflightInvocations++},async()=>{},
   {onInputHeadRefresh:()=>ack}),/SUBMISSION_HOLD|INPUT_HEAD_SCOPE_HOLD/);
 assert.equal(preflightInvocations,0);
 let assetRefreshes=0;
 await run([{kind:'asset',job_id:'ASSET',asset_id:'VIEW',attempt_id:'A1'}],1,async()=>({}),async()=>{},
   {onInputHeadRefresh:()=>{assetRefreshes++;return ack}});
 assert.equal(assetRefreshes,0);
 const managedJobs=boundJobs(2).map((j,i)=>({...j,managed_submission_required:true,dispatch_receipt:{permit_id:'R'+i}}));
 const submitAck=j=>fixtureAck(j);
 let managedInvoked=0;
 await assert.rejects(()=>rawRun(managedJobs.map(fixtureJob),1,async()=>{managedInvoked++},async()=>{}),/durable onBeforeInvoke/);
 assert.equal(managedInvoked,0);
 const submitOrder=[];
 await run(managedJobs,1,async j=>{submitOrder.push('invoke-'+j.panel_id);managedInvoked++;return {}},async()=>{},
   {onBeforeInvoke:async j=>{submitOrder.push('registered-'+j.panel_id);return submitAck(j)}});
 assert.deepEqual(submitOrder,['registered-P1','invoke-P1','registered-P2','invoke-P2']);
 for(const wrong of [j=>({...submitAck(j),invoke_allowed:false,status:'ALREADY_REGISTERED'}),
                      j=>({...submitAck(j),permit_id:'old'}),j=>({...submitAck(j),attempt_id:'old'})]){
   let calls=0,saves=0;
   const blocked=await run(managedJobs,1,async()=>{calls++},async()=>{saves++},{onBeforeInvoke:wrong});
   assert.equal(calls,0);assert.equal(saves,0);assert.equal(blocked[0].outcome_hint,'CHECK_SUBMISSION_REGISTRATION');
   assert(blocked.every(r=>r.status==='NOT_DISPATCHED'));
 }
 // Progress timers yield observations while original image promises remain alive.
 let progressCalls=0, originalInvokes=0, originalSaves=0, notifications=0;
 const ticks=[];
 const progressResults=await run(jobs(3),3,async j=>{
   originalInvokes++;await sleep(45);return j.attempt_id;
 },async()=>{originalSaves++}, {progressIntervalMs:8,serviceProgressIntervalMs:12,progressPollMs:2,
   onProgress:async event=>{notifications++;ticks.push(event);await sleep(1);progressCalls++}});
 assert(notifications>=3);assert.equal(originalInvokes,3);assert.equal(originalSaves,3);
 assert(ticks.some(e=>e.in_flight===3 && e.returned===0 && e.wait_kind==='SERVICE'));
 assert(ticks.every(e=>e.not_watchdog_progress===true));
 assert(ticks.at(-1).finished);assert.equal(ticks.at(-1).persisted,3);
 assert(progressResults.every(r=>r.status==='FULFILLED'));
 const after=notifications;await sleep(20);assert.equal(notifications,after); // Timer disposed.
 const failedDisplay=await run(jobs(2),2,async()=>({}),async()=>{},
   {onProgress:()=>{throw Error('display unavailable')}});
 assert(failedDisplay.every(r=>r.status==='FULFILLED' && r.saved_at && r.progress_signal_errors.length));
 let invalidProgressCalls=0;
 await assert.rejects(()=>run(jobs(1),1,async()=>{invalidProgressCalls++},async()=>{},
   {progressPollMs:60001}),/progress intervals/);
 assert.equal(invalidProgressCalls,0);

 for (const kind of ['panel','repair','asset']) {
   const original=fixtureJob(kind==='asset'?{kind,job_id:'ASSET',asset_id:'X',attempt_id:'A1'}:{...jobs(1)[0],kind});
   let touches=0;
   await assert.rejects(()=>rawRun([original],1,async()=>{touches++},async()=>{}),/durable onBeforeInvoke/);
   const blocked=await rawRun([original],1,async()=>{touches++},async()=>{},
     {onBeforeInvoke:async()=>{throw Error('RUNTIME_CLOCK_PAUSED')}});
   assert.equal(touches,0);assert.equal(blocked[0].status,'NOT_DISPATCHED');
   for(const mutate of [a=>({...a,input_digest:'b'.repeat(64)}),a=>({...a,kind:'wrong'}),
       a=>({...a,scope:{...a.scope,task_id:'other'}}),a=>({...a,invoke_allowed:false})]) {
     await rawRun([original],1,async()=>{touches++},async()=>{}, {onBeforeInvoke:async j=>mutate(fixtureAck(j))});
   }
   assert.equal(touches,0);
 }
 for(const flag of ['candidate_only','input_audit_only']) {
   await assert.rejects(()=>rawRun([{...fixtureJob(jobs(1)[0]),[flag]:true}],1,async()=>{},async()=>{},
      {onBeforeInvoke:fixtureAck}),/CANDIDATE_HOLD/);
 }
 const mutable=fixtureJob({...jobs(1)[0],arguments:{prompt:'checked'}});let actualPrompt;
 await rawRun([mutable],1,async j=>{actualPrompt=j.arguments.prompt},async()=>{},
   {onBeforeInvoke:async j=>{mutable.arguments.prompt='changed externally';j.arguments.prompt='changed callback';return fixtureAck(j)}});
 assert.equal(actualPrompt,'checked');
 console.log('Async generation concurrency, durable timing, asset/repair routing, full error preservation, unknown outcome, service circuit and review notification tests PASS; fake backend only.');
})().catch(e=>{console.error(e);process.exitCode=1});
