/* Host lifecycle and terminal wiring only. Synthetic transport, no service. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const start=eval(fs.readFileSync(__dirname+'/../scripts/batch_bootstrap.js','utf8'));
const manifest={test_id:Date.now(),book_id:'B',episodes:[{episode_id:'E',state:'/state',frozen_scripts:'/scripts'}]};
let manifestText=JSON.stringify(manifest),reads=0,spawns=0,closes=0,continueBatch=true,block;
const job={attempt_id:'A',arguments:{prompt:'SYNTHETIC'}};
const fakeSources={
 'batch_host_client.js':`(()=>{testSpawn();let alive=true;return{snapshot:()=>({alive,pids:[123],pending:0}),request:async(state,payload)=>testServer(payload),close:async()=>{alive=false;testClose();}}})`,
 'batch_runner.js':`(async({transport,request})=>{await testBlock();var p=await transport.invoke(testJob);testPacket(p);await request('/state',{});await testRunExtra(request);return{status:testContinue()?'CONTINUE_REQUIRED':'MATERIALS_READY'};})`,
 'async_generation.js':'(()=>{})','image_tool_bridge.js':'(()=>{})','prepared_input_source.js':'(()=>{})'
};
let lastPacket,extra=async()=>{},failRegistration=false,replays=0,echoCalls=0,loseReply=false;
const server=async p=>{
 if(p.action==='large-echo'){echoCalls++;assert.equal(p.data,'测试😀'.repeat(50000));return{status:'PASS'};}
 if(p.action==='capture-envelope')return{status:'RETURN_CAPTURED',capture:{path:'saved.json',sha256:'saved'}};
 if(p.action==='register-return'){replays++;if(failRegistration){failRegistration=false;throw Error('synthetic registration failure')}return{status:'RETURN_REGISTERED'};}
 if(p.action==='prepare-qa')return{items:[]};return{status:'PASS'};
};
// Runner source executes in this lexical context, matching the bootstrap binding.
global.testRunExtra=request=>extra(request);global.testJob=job;global.testPacket=p=>{lastPacket=p};global.testContinue=()=>continueBatch;global.testBlock=()=>block;
const context=vm.createContext({Map,Set,JSON,Promise,setTimeout,clearTimeout,
 testServer:server,testSpawn:()=>spawns++,testClose:()=>closes++,__import:async name=>name==='node:fs/promises'?{
  realpath:async()=>'/manifest',readFile:async p=>{if(p==='/manifest')return manifestText;reads++;return fakeSources[p.split('/').pop()];}
 }:name==='node:child_process'?{}:name.endsWith('/batch_host_client.js')?{default:()=>{spawns++;let alive=true;return{snapshot:()=>({alive,pids:[123],pending:0}),request:async(s,p)=>server(p),close:async()=>{alive=false;closes++;}}}}:name.endsWith('/batch_relay.js')?import('../scripts/batch_relay.js'):import(name)},{codeGeneration:{strings:false,wasm:false}});
let toolCalls=0,chain=Promise.resolve();
function node({code}){assert(Buffer.byteLength(code)<64000,'bounded tool program');toolCalls++;const t=chain.then(async()=>{
 let value;context.nodeRepl={write:v=>{value=v}};
 await vm.runInContext('(async()=>{'+code.replace(/\bvar /g,'').replace(/await import\(/g,'await __import(')+'})()',context);
 if(loseReply&&code.includes('relay.io.exchange(')){loseReply=false;throw Error('synthetic lost reply after execution');}
 return{content:[{type:'text',text:value}]};
});chain=t.catch(()=>{});return t;}
(async()=>{
 const terminal={attempt_id:'A',registration_id:'R',no_image_confirmed:true,outcome:'FAILED_NO_OUTPUT',evidence:'actual fixture'};
 const envelope={result:{isError:true,error:'network'},terminal,call_locator:'test://call',result_locator:'test://return'};
 const args={manifestPath:'/manifest',node,sourceLocator:'test',invokeEnvelope:async()=>envelope};
 const first=await start(args);assert.equal(first.host_reused,false);assert.strictEqual(lastPacket,envelope);
 assert.equal(spawns,1);assert.equal(closes,0);assert.equal(first.relay_metrics.empty,0);
 const second=await start({...args,relayKey:first.relayKey,invokeEnvelope:async()=>{const error=Error('network');error.toolEnvelope=envelope;throw error;}});
 assert.equal(second.host_reused,true);assert.strictEqual(lastPacket.terminal,terminal);assert.equal(spawns,1);assert.equal(reads,5);
 manifestText=JSON.stringify({...manifest,changed:true});await assert.rejects(start(args),/MANIFEST_CHANGED/);manifestText=JSON.stringify(manifest);
 let release;block=new Promise(r=>release=r);const active=start(args);
 while(!context.comicBatchRelays.values().next().value.busy)await new Promise(r=>setTimeout(r,1));
 await assert.rejects(start(args),/BATCH_ALREADY_RUNNING/);release();await active;block=undefined;
 await assert.rejects(start({...args,invokeEnvelope:async()=>{throw Error('ordinary timeout')}}),/ordinary timeout/);
 assert.equal(closes,0,'error keeps the host, not a fabricated no-image retry');
 extra=async request=>{
   const cap=await request('/state',{action:'capture-envelope',job:{book_id:'B',episode_id:'E',panel_id:'P1',attempt_id:'A'}});
   failRegistration=true;try{await request('/state',{action:'register-return',capture:cap.capture})}catch(_){}
 };
 await start(args);assert.equal(context.comicBatchRelays.values().next().value.captured.size,1);
 extra=async()=>{};const recovered=await start(args);assert.equal(recovered.replayResults.length,1);
 assert.equal(recovered.replayResults[0].status,'RETURN_REGISTERED');assert.equal(replays,2);
 assert.equal(context.comicBatchRelays.values().next().value.captured.size,0);
 extra=async request=>{await request('/state',{action:'large-echo',data:'测试😀'.repeat(50000)});};
 loseReply=true;const large=await start(args);assert.equal(echoCalls,1);assert(large.relay_metrics.upload_calls>1);assert.equal(large.relay_metrics.replayed_exchanges,1);
 extra=async()=>{};
 continueBatch=false;const last=await start(args);assert.equal(last.host_reused,true);assert.equal(closes,1);assert.equal(context.comicBatchRelays.size,0);
 continueBatch=true;await start(args);assert.equal(spawns,2);await start({manifestPath:'/manifest',node,closeOnly:true});assert.equal(closes,2);
 assert.equal(context.comicBatchRelays.size,0);
 console.log(JSON.stringify({status:'PASS',source_reads_across_resume:reads,first_empty_polls:first.relay_metrics.empty,spawns,closes,tool_calls:toolCalls}));
})().catch(e=>{console.error(e);process.exitCode=1});
