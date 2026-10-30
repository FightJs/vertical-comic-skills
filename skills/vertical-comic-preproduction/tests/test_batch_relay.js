const assert=require('node:assert/strict'),fs=require('node:fs/promises'),{create}=require('../scripts/batch_relay.js');
function fixture(manifestPath,request){
 const relay={manifestPath,digest:'synthetic',manifest:{episodes:[{state:'state'}]},requests:new Map(),completed:[],captured:new Map(),waiters:new Set(),clients:{request}};
 relay.notify=()=>{for(const wake of relay.waiters)wake();relay.waiters.clear();};return relay;
}
(async()=>{
 const identity='synthetic-relay-'+Date.now()+'-'+Math.random();let captures=0;
 const original={id:'original-1',state:'state',payload:{action:'capture-envelope',job:{book_id:'B',episode_id:'E',panel_id:'P',attempt_id:'A'},packet:{result:{data:'a'.repeat(180000)},call_locator:'synthetic://call',result_locator:'synthetic://return'}}};
 const first=fixture(identity,async()=>{captures++;throw Error('synthetic capture interruption')});const io=await create(first);
 try{
  const raw=JSON.stringify(original);let parts=0;
  for(let i=0;i<raw.length;i+=30000){await io.part(original.id,parts++,raw.slice(i,i+30000));}
  const ref={id:original.id,staged_parts:parts};
  const failed=await io.exchange([ref],[],10);assert(failed[0].error.includes('interruption'));
  await io.exchange([],['original-1'],0);
  assert((await fs.readdir(io.folder)).some(n=>n.endsWith('.json')),'failed raw envelope stays durable');
  const fresh=fixture(identity,async(state,p)=>{captures++;assert.deepEqual(p,original.payload);return{status:'RETURN_CAPTURED',capture:{path:'captured.json',sha256:'actual-test-digest'}}});
  const restored=await create(fresh);assert.equal(restored.recoverable.length,1);
  const replay={id:original.id,staged_parts:0};const done=await restored.exchange([replay],[],10);
  assert.equal(done[0].result.status,'RETURN_CAPTURED');assert.equal(fresh.captured.size,1);
  assert.deepEqual(await restored.exchange([replay],[],0),done,'lost reply reads the same result');assert.equal(captures,2,'replay persists bytes only; no duplicate capture in an epoch');
  await restored.exchange([],['original-1'],0);
  assert.equal((await fs.readdir(io.folder)).length,0,'successful receipt permits staging cleanup');
  await assert.rejects(restored.exchange([{id:original.id,state:'state',payload:{action:'changed'}}],[],0),/REQUEST_CHANGED/);
  console.log('Large envelope durable restart / original identity / response replay / cleanup PASS; image calls=0');
 }finally{await fs.rm(io.folder,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1});
