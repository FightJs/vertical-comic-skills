const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const create=vm.runInNewContext(fs.readFileSync(__dirname+'/../scripts/prepared_input_source.js','utf8'),{setTimeout});
const ref=n=>({panel_id:'P'+n,attempt_id:'A'+n,record_digest:'digest'+n,prepared_input_id:'input'+n});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
  assert.throws(()=>create({request:async()=>({}),workers:0}),/CONFIGURATION_INVALID/);
  let release,finished=false,ready=[],reads=0,starts=0;
  const pending=new Promise(r=>release=r);
  const source=create({bufferSize:2,pollMs:100,panels:['P1','P2','P3'],request:async req=>{
    assert.deepEqual(Array.from(req.panels),['P1','P2','P3']);
    if(req.action==='prepare-inputs'){assert.equal(req.workers,'all');starts++;await pending;finished=true;return{status:'READY'};}
    reads++;return{jobs:ready.filter(r=>!req.exclude_record_digests.includes(r.record_digest)).slice(0,req.limit),preparing:!finished,preparation_complete:finished};
  }});
  let firstDone=false;
  const first=source.nextPrepared().then(r=>{firstDone=true;return r;});
  await sleep(20);assert.equal(firstDone,false,'temporary empty queue is not EOF');
  ready.push(ref(1));assert.equal((await first).panel_id,'P1');
  assert.equal(finished,false,'first input delivered before whole preparation finishes');
  ready.push(ref(2),ref(3));release();await source.completion;
  const rest=await Promise.all([source.nextPrepared(),source.nextPrepared(),source.nextPrepared()]);
  assert.deepEqual(rest.map(r=>r?.panel_id??null),['P2','P3',null]);
  assert.equal(starts,1);assert(source.snapshot().peakBuffered<=2);assert(reads<8);
  const bad=create({pollMs:100,request:async req=>{
    if(req.action==='prepare-inputs')throw new Error('synthetic compile fault');
    return{jobs:[],preparation_complete:false};
  }});
  await bad.completion;await assert.rejects(bad.nextPrepared(),/synthetic compile fault/);
  const blocked=create({request:async req=>req.action==='prepare-inputs'?{status:'HOLD',reports:[{panel_id:'P9',status:'HOLD'}]}:
    {jobs:[],preparation_complete:true,blocked_panels:[{panel_id:'P9',status:'HOLD'}]}});
  await blocked.completion;assert.equal(await blocked.nextPrepared(),null);
  assert.equal(blocked.snapshot().latest.blocked_panels.length,1,'EOF retains blocked scope');
  let publish,compileDone,notifications=0,notifiedReads=0,hasImage=false,done=false;
  const finish=new Promise(r=>compileDone=r);
  const eventSource=create({pollMs:100,request:async req=>{
    if(req.action==='prepare-inputs'){await finish;done=true;return{status:'READY'};}
    if(req.action==='wait-prepared-change'){notifications++;await new Promise(r=>publish=r);return{changed:true};}
    notifiedReads++;return{jobs:hasImage&&!req.exclude_record_digests.includes('digest8')?[ref(8)]:[],revision:hasImage?1:0,preparation_complete:done};
  }});
  const eventReady=eventSource.nextPrepared();while(!publish)await sleep(1);
  await sleep(150);assert.equal(notifiedReads,1,'no state polling while waiting for publication');
  hasImage=true;publish();assert.equal((await eventReady).panel_id,'P8');
  compileDone();await eventSource.completion;assert.equal(await eventSource.nextPrepared(),null);assert.equal(notifications,1);
  console.log('Prepared source: early delivery, temporary empty, bounded reads/buffer, scope, errors and blocked scope PASS (synthetic only)');
})().catch(e=>{console.error(e);process.exitCode=1;});
