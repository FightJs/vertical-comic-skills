#!/usr/bin/env python3
"""Isolated real-package replay with synthetic returns; never invokes image services.

Use --package and a new --output directory. Proprietary fixtures stay local.
Synthetic images are deliberately unreviewed; this is not a production package.
"""
import argparse,base64,hashlib,io,json,statistics,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/vertical-comic-preproduction/scripts'))

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--package',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path);parser.add_argument('--restored',type=Path)
    args=parser.parse_args();base=args.output.resolve();base.mkdir(parents=True,exist_ok=False)
    from handoff_transport import restore
    from handoff_delivery import bind
    from runtime_snapshot import create
    from runtime_import import apply_import,plan_import
    from platform_io import atomic_json
    from codex_reference_contract import digest,read_json
    from slot_leases import allocate,POLICY
    report={'scope':'isolated actual package; synthetic unreviewed images; no service','image_calls':0,'timings':{},'episodes':[]}
    before=digest(args.package)
    def measure(name,fn):
        started=time.monotonic();value=fn();report['timings'][name]=time.monotonic()-started
        print(name,round(report['timings'][name],3),flush=True);return value
    original=args.restored or Path(measure('restore',lambda:restore(args.package,base/'restored'))['root'])
    bound=measure('bind',lambda:bind(original,base/'run'));snapshot=create(base/'executor')
    index=read_json(bound['run_index']);states=[]
    for e in index['episodes']:
        path=Path(bound['run_root'])/e['state'];apply_import(path,plan_import(path,snapshot));states.append(path)
    control_path=base/'synthetic-control.json';jobs=[]
    for path in states:
        state=read_json(path);eid=state['episode_id'];state['parallel_context']={'control_file':str(control_path),'job_id':eid,'worker_id':'synthetic-'+eid,'epoch':1}
        state['runtime']['dispatch_policy']=POLICY
        # Isolated fixture only; never copy this synthetic grant into a production run.
        state['production_authorization']={'status':'APPROVED','source_kind':'user_message','source_locator':'synthetic://test-only/no-real-user',
            'quote':'SYNTHETIC TEST DATA ONLY; no real service call authorized','book_id':state['book_id'],'episode_id':eid,
            'panel_ids':[r['panel_id'] for r in state['panels']],'artifacts':[state['source_script']]}
        atomic_json(path,state)
        jobs.append({'job_id':eid,'worker_id':'synthetic-'+eid,'episode_id':eid,'root':str(path.parent.parent),'status':'RUNNING',
                     'max_inflight':1,'active_batch_id':'EPISODE','frozen_inputs':{k:state[k] for k in ('source_script','source_snapshot','visual_basis','shot_manifest')}})
    state=read_json(states[0]);basis=state['visual_basis'];root=states[0].parent.parent
    control={'policy':'parallel_episodes_v1','version':1,'book_id':state['book_id'],'epoch':1,'cancelled':False,'holds':[],
             'max_workers':len(jobs),'max_inflight':len(jobs),'shared_files':[{'path':str(root/basis['path']),'sha256':basis['sha256'],'role':'style_basis'}],
             'permits':[],'jobs':jobs}
    atomic_json(control_path,control);allocate(control_path,digest(control_path),{j['job_id']:1 for j in jobs})
    from PIL import Image
    stream=io.BytesIO();Image.new('RGB',(90,160),'white').save(stream,format='PNG')
    raw=base/'SYNTHETIC_UNREVIEWED_RETURN.json';atomic_json(raw,{'image_url':'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode()})
    host=Path(snapshot['path']).parent/'skills/vertical-comic-preproduction/scripts/generation_host.py'
    hashes={};claim_times=[];save_times=[]
    for path in states:
        state=read_json(path);eid=state['episode_id'];root=path.parent.parent
        proc=subprocess.Popen([sys.executable,'-B',str(host),'serve','--state',str(path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(base/(eid+'-stderr.txt')).open('w'),text=True)
        serial=0
        def request(action,**kw):
            nonlocal serial
            serial+=1;started=time.monotonic();proc.stdin.write(json.dumps({'request_id':str(serial),'action':action,**kw})+'\n');proc.stdin.flush()
            line=proc.stdout.readline()
            if not line:raise RuntimeError('host exited: '+eid)
            result=json.loads(line);assert result['request_id']==str(serial),result
            value=result['result']
            if value.get('error'):raise RuntimeError(str(value))
            return value,time.monotonic()-started
        try:
            prepared,seconds=request('prepare-inputs');assert len(prepared.get('jobs',[]))==len(state['panels']),prepared
            atomic_json(base/(eid+'-prepare.json'),prepared)
            expected={}
            for reference in state['generation_packages']['EPISODE']:
                for item in read_json(root/reference['path'])['inputs']:expected[item['panel_id']]=item
            count=0;references=0
            for ref in prepared['jobs']:
                claim,elapsed=request('claim-and-register',prepared_reference=ref);claim_times.append(elapsed)
                assert claim['ack']['invoke_allowed'];job=claim['job'];item=expected[job['panel_id']]
                assert job['arguments']['prompt']==item['prompt'] and job['arguments']['transparent_background']==item['transparent_background']
                actual=[]
                for filename in job['arguments'].get('referenced_image_paths',[]):
                    if filename not in hashes:hashes[filename]=digest(Path(filename))
                    actual.append(hashes[filename])
                assert actual==[r['sha256'] for r in item['references']];references+=len(actual)
                jp=base/(eid+'-final-job.json');atomic_json(jp,job)
                result,elapsed=request('save-return',job=str(jp),raw=str(raw),call_locator='synthetic://replay/no-service/'+job['panel_id'],result_locator='synthetic://fixture/white-png')
                assert result.get('visual_review')=='UNREVIEWED';save_times.append(elapsed);count+=1
            after=read_json(path);assert all(r['status']=='GENERATED' and not r.get('qa_report') for r in after['panels'])
            report['episodes'].append({'episode_id':eid,'prepared':count,'references_equal':references,'prepare_seconds':seconds,'synthetic_returns_saved':count,'visual_review':'NOT_PERFORMED'})
            print(eid,count,round(seconds,3),'seconds preparation',flush=True)
        finally:
            proc.stdin.close();proc.wait(timeout=30)
        atomic_json(base/'report.json',report)
    def summary(values):
        values=sorted(values);return {'count':len(values),'p50_seconds':statistics.median(values),'p95_seconds':values[min(len(values)-1,int(len(values)*.95))],'max_seconds':max(values),'sum_not_wall_seconds':sum(values)}
    assert digest(args.package)==before
    report.update(package_sha256=before,original_zip_unchanged=True,claim=summary(claim_times),save=summary(save_times),all_inputs_equal=True,not_a_production_delivery=True)
    atomic_json(base/'report.json',report)
    print(json.dumps({'claim':report['claim'],'save':report['save']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
