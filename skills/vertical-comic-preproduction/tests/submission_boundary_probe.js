// Isolated boundary probe: the only invoke is a counting synthetic replacement.
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),vm=require('node:vm');
const c=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const run=vm.runInNewContext(fs.readFileSync(path.join(c.scripts,'async_generation.js'),'utf8'),{setTimeout,clearTimeout,Date,Error});
let touches=0,saves=0;
const options=c.omitCallback?{}:{onBeforeInvoke:async job=>{
  const jobPath=path.join(path.dirname(process.argv[2]),'actual-job.json');
  fs.writeFileSync(jobPath,JSON.stringify(job));
  let argv;
  if(c.protocol==='asset')argv=[path.join(c.scripts,'asset_runtime.py'),'submit','--run-root',c.root,'--job',jobPath];
  else if(c.protocol==='managed'){
    const arg=path.join(path.dirname(process.argv[2]),'submit-arguments.json');fs.writeFileSync(arg,JSON.stringify({job}));
    argv=[path.join(c.scripts,'managed_dispatch.py'),'--state',c.state,'--action','submit','--arguments',arg];
  }else argv=[path.join(c.scripts,'production_runtime.py'),'--state',c.state,'--action','submit','--job',jobPath];
  const p=cp.spawnSync(c.python,['-X','utf8','-B',...argv],{encoding:'utf8'});
  if(p.status!==0)throw Error(p.stdout+' '+p.stderr);
  return JSON.parse(p.stdout);
}};
(async()=>{
 try{
  const result=await run([c.job],1,async()=>{touches++;return {synthetic:true}},async()=>{saves++},options);
  process.stdout.write(JSON.stringify({touches,saves,result,real_requests:0}));
 }catch(e){process.stdout.write(JSON.stringify({touches,saves,error:String(e),real_requests:0}));}
})().catch(e=>{console.error(e);process.exitCode=1});
