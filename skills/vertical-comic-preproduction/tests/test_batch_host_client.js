const fs=require('node:fs'),assert=require('node:assert/strict'),{EventEmitter}=require('node:events');
const create=eval(fs.readFileSync(__dirname+'/../scripts/batch_host_client.js','utf8'));
function fixture(){
 const child=new EventEmitter();child.pid=123;child.stdout=new EventEmitter();child.stderr=new EventEmitter();
 child.stdout.setEncoding=child.stderr.setEncoding=()=>{};
 const sent=[];child.stdin={write:(line,callback)=>{sent.push(JSON.parse(line));callback();},end:()=>queueMicrotask(()=>child.emit('exit',0,null))};
 const client=create({spawn:()=>child,python:'synthetic',episodes:[{state:'state',generation_host:'host',panel_count:35}],admission:async()=>({status:'RESOURCE_GRANTED',token:'synthetic'})});
 const reply=r=>child.stdout.emit('data',JSON.stringify({request_id:r.request_id,result:{status:'SAVED'}})+'\n');
 return{child,sent,client,reply};
}
(async()=>{
 const {client,sent,reply}=fixture();
 const captures=Array.from({length:35},()=>client.request('state',{action:'capture-envelope',packet:{result:'synthetic'}}));
 await new Promise(r=>setTimeout(r,0));
 assert.equal(sent.length,8,'only bounded captures enter the pipe');
 const control=client.request('state',{action:'delivery-status'});await new Promise(r=>setTimeout(r,0));assert.equal(sent[8].action,'delivery-status');
 reply(sent[8]);await control;
 let i=0;while(i<sent.length){const r=sent[i++];if(r.action==='capture-envelope')reply(r);}
 assert.equal((await Promise.all(captures)).length,35);assert.equal(sent.length,36);
 assert.equal(client.snapshot().pending,0);await client.close();assert.equal(client.snapshot().alive,false);
 const dead=fixture();const rejected=Array.from({length:20},()=>dead.client.request('state',{action:'capture-envelope'}).catch(e=>e.message));
 await new Promise(r=>setTimeout(r,0));
 dead.child.emit('exit',1,null);assert((await Promise.all(rejected)).every(x=>x.includes('HOST_EXIT')));await dead.client.close();
 console.log('Capture burst 35: 8 pipe slots, control bypass, all 35 saved; dead host rejects queued captures PASS');
})().catch(e=>{console.error(e);process.exitCode=1});

// Independent lazy owners share hardware permits; idle ones yield their host,
// while an outstanding image lease keeps its exact owner alive.
(async()=>{
 const live=new Set(),children=[],requests=[];let cap=1;
 const spawn=(python,args)=>{
  const child=new EventEmitter();child.pid=1000+children.length;children.push(child);
  child.stdout=new EventEmitter();child.stderr=new EventEmitter();child.stdout.setEncoding=child.stderr.setEncoding=()=>{};
  child.stdin={write:(line,cb)=>{const p=JSON.parse(line);requests.push(p);
   queueMicrotask(()=>child.stdout.emit('data',JSON.stringify({request_id:p.request_id,result:p.action==='resource-acquire'?{status:'RESOURCE_GRANTED',token:'image-lease'}:p.action==='ready-inputs'?{status:'PASS',jobs:[],preparation_complete:true}:{status:'PASS'}})+'\n'));cb();},
   end:()=>queueMicrotask(()=>child.emit('exit',0,null))};return child;
 };
 const admission=async p=>{
  if(p.action==='acquire'){if(live.size>=cap)return{status:'RESOURCE_WAIT',retry_after_ms:100};live.add(p.key);return{status:'RESOURCE_GRANTED',token:p.key};}
  if(p.action==='release')live.delete(p.token);return{status:'PASS'};
 };
 const episodes=['E1','E2','E3'].map(episode_id=>({episode_id,state:episode_id,generation_host:'generation_host.py',panel_count:4}));
 const client=create({spawn,python:'synthetic',episodes,admission});assert.equal(children.length,0);
 await client.request('E1',{action:'prepare-inputs'});
 let secondDone=false;const second=client.request('E2',{action:'delivery-status'}).then(()=>secondDone=true);
 await new Promise(r=>setTimeout(r,20));assert.equal(children.length,1);assert(!secondDone);
 assert.equal(client.snapshot().active_hosts,1,'finished prepare remains pinned until its ready queue drains');
 await client.request('E1',{action:'resource-acquire'});await client.request('E1',{action:'ready-inputs'});
 cap=2;await second;assert.equal(children.length,2);
 await client.request('E3',{action:'delivery-status'});assert.equal(children.length,3);assert.equal(client.snapshot().active_hosts,2);
 assert.equal(client.snapshot().pids[0],1000,'pinned E1 was not evicted');await client.close();assert.equal(live.size,0);
 console.log('Lazy host admission / recovery / idle eviction / pinned owner PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
