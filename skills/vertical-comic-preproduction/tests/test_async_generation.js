const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const run = eval(fs.readFileSync(path.join(__dirname, '../scripts/async_generation.js'), 'utf8'));
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
 console.log('Async generation concurrency, durable timing, asset/repair routing, full error preservation, unknown outcome, service circuit and review notification tests PASS; fake backend only.');
})().catch(e=>{console.error(e);process.exitCode=1});
