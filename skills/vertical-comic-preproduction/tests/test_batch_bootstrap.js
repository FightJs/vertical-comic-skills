const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const start=eval(fs.readFileSync(__dirname+'/../scripts/batch_bootstrap.js','utf8'));
const context=vm.createContext({Map,JSON,Promise,setTimeout,clearTimeout,__import:name=>import(name)},{codeGeneration:{strings:false,wasm:false}});
let chain=Promise.resolve();
function node({code}){
 assert(Buffer.byteLength(code)<64000,'large data must not enter one tool program');
 const task=chain.then(async()=>{
   let value;context.nodeRepl={write:v=>{value=v}};
   await vm.runInContext('(async()=>{'+code.replace(/\bvar /g,'').replace(/await import\(/g,'await __import(')+'})()',context);
   return{content:[{type:'text',text:value}]};
 });chain=task.catch(()=>{});return task;
}
(async()=>{
 let calls=0,reviews=0;const observationsByEpisode={};
 const raw=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
 const result=await start({manifestPath:process.argv[2],node,sourceLocator:'synthetic://bootstrap',
  invokeEnvelope:async(args,job)=>{assert(args.prompt);calls++;return{result:raw,call_locator:'synthetic://call/'+job.attempt_id,result_locator:'synthetic://return/'+job.attempt_id}},
  onReviewBatchReady:async(entries,materials)=>{reviews+=entries.length;assert(materials[0].prepared.items[0].review_ticket);
    for(const m of materials){observationsByEpisode[m.episode_id] ??= [];for(const item of m.prepared.items)
      observationsByEpisode[m.episode_id].push({review_ticket:item.review_ticket,observation:{
        reviewer:'SYNTHETIC',reason:'SYNTHETIC fixture observation',verdict:'PASS',adopt:true,
        light_observations:{checks:{identity:{status:'PASS',observed:'SYNTHETIC fixture identity'},story_readability:{status:'PASS',observed:'SYNTHETIC fixture readability'}},issues:[]}}});}
  }});
 assert.equal(result.host_reused,false);assert.equal(result.status,'CONTINUE_REQUIRED');assert.equal(calls,4);assert.equal(reviews,4);
 assert(!result.results.some(r=>r.persistence_error||r.registration_error||r.submission_error));
 const resumed=await start({manifestPath:process.argv[2],node,sourceLocator:'synthetic://bootstrap-resume',observationsByEpisode,invokeImage:async()=>{throw Error('must reuse original images')}});
 assert.equal(resumed.host_reused,true);assert.deepEqual(resumed.host_pids,result.host_pids);
 assert.equal(context.comicBatchRelays.size,0);
 assert.equal(resumed.status,'MATERIALS_READY',JSON.stringify(resumed.observationResults));
 console.log(JSON.stringify({first:result.relay_metrics,resumed:resumed.relay_metrics,host_reused:resumed.host_reused,pids:resumed.host_pids}));
 console.log('Official bootstrap -> persistent JSONL hosts -> real compile/capture/register/QA materials PASS; synthetic images, no service calls');
})().catch(async error=>{console.error(error);try{await start({manifestPath:process.argv[2],node,closeOnly:true})}catch(_){}process.exitCode=1});
