/* File-backed bounded relay transport; only the supported host invokes images. */
const fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto');
async function create(relay){
  const folder=path.join(os.tmpdir(),'comic-relay-'+crypto.createHash('sha256').update(relay.manifestPath+relay.digest).digest('hex'));
  await fs.mkdir(folder,{recursive:true,mode:0o700});
  const valid=id=>{if(typeof id!=='string'||!/^[a-zA-Z0-9-]+$/.test(id))throw Error('RELAY_ID_INVALID');return id;};
  async function put(file,raw){
    let handle;
    try{handle=await fs.open(file,'wx',0o600);await handle.writeFile(raw);await handle.sync();}
    catch(error){if(error.code!=='EEXIST')throw error;if(await fs.readFile(file,'utf8')!==raw)throw Error('RELAY_PAYLOAD_CHANGED');}
    finally{if(handle)await handle.close();}
  }
  const names=await fs.readdir(folder),stranded=names.filter(n=>n.endsWith('.json')).map(n=>path.join(folder,n)),recoverable=[];
  for(const file of stranded){
    try{const e=JSON.parse(await fs.readFile(file,'utf8'));
      if(relay.manifest.episodes.some(x=>x.state===e.state)&&['capture-envelope','capture-return'].includes(e.payload?.action))
        recoverable.push({id:e.id,staged_parts:0,state:e.state,job:e.payload.job});
    }catch(_){} // Partial/invalid bytes remain evidence, never a guessed result.
  }
  async function part(id,index,raw){
    valid(id);if(!Number.isInteger(index)||index<0||Buffer.byteLength(raw)>48000)throw Error('RELAY_PART_INVALID');
    await put(path.join(folder,id+'.'+index+'.part'),raw);
  }
  async function entry(ref){
    valid(ref.id);
    if(ref.staged_parts!==undefined){
      if(!Number.isInteger(ref.staged_parts)||ref.staged_parts<0)throw Error('RELAY_PARTS_INVALID');
      const file=path.join(folder,ref.id+'.json');let raw;
      try{raw=await fs.readFile(file,'utf8');}catch(error){
        if(error.code!=='ENOENT')throw error;
        const pieces=[];for(let i=0;i<ref.staged_parts;i++)pieces.push(await fs.readFile(path.join(folder,ref.id+'.'+i+'.part'),'utf8'));
        raw=pieces.join('');await put(file,raw);
      }
      const value=JSON.parse(raw);if(value.id!==ref.id)throw Error('RELAY_ENTRY_ID_CHANGED');return {value,file,parts:ref.staged_parts};
    }
    return {value:ref};
  }
  async function exchange(refs,acks,waitMs){
    for(const id of acks){
      const item=relay.requests.get(id);
      if(item?.reply){
        relay.completed=relay.completed.filter(r=>r.id!==id);
        if(item.file&&!item.reply.error){
          await fs.rm(item.file,{force:true});
          const parts=item.parts?Array.from({length:item.parts},(_,i)=>id+'.'+i+'.part'):names.filter(n=>n.startsWith(id+'.')&&n.endsWith('.part'));
          for(const n of parts)await fs.rm(path.join(folder,n),{force:true});
        }
        // Keep only the small ID tombstone: a repeated exchange cannot replay a side effect.
        item.acked=true;delete item.reply;delete item.file;
      }
    }
    for(const ref of refs){
      const refHash=crypto.createHash('sha256').update(JSON.stringify(ref)).digest('hex');
      if(relay.requests.has(ref.id)){if(relay.requests.get(ref.id).refHash!==refHash)throw Error('RELAY_REQUEST_CHANGED');continue;}
      const stored=await entry(ref),e=stored.value;
      if(!relay.manifest.episodes.some(x=>x.state===e.state))throw Error('RELAY_STATE_SCOPE');
      const record={file:stored.file,parts:stored.parts,refHash};relay.requests.set(e.id,record);
      relay.clients.request(e.state,e.payload).then(result=>{
        const p=e.payload;
        if(result?.status==='RETURN_CAPTURED'&&result.capture&&p.job){
          const {book_id,episode_id,panel_id,attempt_id}=p.job;
          relay.captured.set(JSON.stringify([e.state,result.capture]),{state:e.state,capture:result.capture,job:{book_id,episode_id,panel_id,attempt_id}});
        }
        if(p.action==='register-return'&&['SAVED','RETURN_ALREADY_SAVED','RETURN_REGISTERED','UPDATES_SAVED','UPDATES_ALREADY_SAVED'].includes(result?.status))
          relay.captured.delete(JSON.stringify([e.state,p.capture]));
        record.reply={id:e.id,result};relay.completed.push(record.reply);relay.notify();
      },error=>{record.reply={id:e.id,error:String(error)};relay.completed.push(record.reply);relay.notify();});
    }
    if(!relay.completed.length&&waitMs>0)await new Promise(resolve=>{
      let timer;const wake=()=>{clearTimeout(timer);relay.waiters.delete(wake);resolve();};
      relay.waiters.add(wake);timer=setTimeout(wake,waitMs);
    });
    return relay.completed.slice();
  }
  return {part,exchange,stranded,recoverable,folder};
}
module.exports={create};
