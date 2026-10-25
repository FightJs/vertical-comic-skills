#!/usr/bin/env python3
"""Synthetic growing scopes/multiple approval versions; no image calls or production edits."""
import argparse,hashlib,json,subprocess,sys,tempfile,time
from pathlib import Path
from contextlib import nullcontext
ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'skills/vertical-comic-preproduction/scripts'

def probe(args):
    sys.path.insert(0,str(args.scripts))
    from continuity_context import load_context
    from codex_reference_contract import file_session
    from validation_pool import ValidationPool,session
    packets=json.loads((args.root/'packets.json').read_text(encoding='utf-8'))
    pool=ValidationPool() if args.pooled else None
    rows=[]
    with session(pool) if pool else nullcontext():
        for _ in range(3):
            started=time.perf_counter();cpu=time.process_time();results=[]
            with file_session() as memo:
                for packet in packets:
                    previous,errors=load_context(packet,args.root,readonly=True)
                    results.append({'ids':sorted(previous),'errors':errors})
            rows.append({'seconds':time.perf_counter()-started,'cpu_seconds':time.process_time()-cpu,
                'decision_sha256':hashlib.sha256(json.dumps(results,sort_keys=True).encode()).hexdigest(),
                'rejected':sum(bool(r['errors']) for r in results),
                'hash_reads':memo['hash_reads'],'hash_bytes':memo['hash_bytes'],
                'dependency_checks':memo['dependency_checks'],'audit_statistics':memo['audit_statistics'],
                'compile_calls':0})
    assert Path(sys.modules['continuity_context'].__file__).resolve().parent==args.scripts.resolve()
    return {'operations':rows,'pool':pool.statistics if pool else None}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,default=SCRIPTS)
    parser.add_argument('--scripts',type=Path,default=SCRIPTS)
    parser.add_argument('--root',type=Path);parser.add_argument('--pooled',action='store_true')
    parser.add_argument('--counts',type=int,nargs='+',default=[35,165]);args=parser.parse_args()
    if args.root:print(json.dumps(probe(args)));return
    sys.path.insert(0,str(SCRIPTS.parent/'tests'))
    from audit_fixtures import contexts
    report={'scope':'synthetic context parser, growing scopes and multi-version scoped approvals; not full receiver or image throughput',
            'image_calls':0,'decisions_equal':True,'inputs_unchanged':True,'workloads':{}}
    for count in args.counts:
        with tempfile.TemporaryDirectory(prefix='comic-proof-benchmark-') as tmp:
            root=Path(tmp);packets=contexts(root,count,multiple_proofs=True)
            (root/'packets.json').write_text(json.dumps(packets),encoding='utf-8')
            def inventory():return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
            before=inventory();values={}
            for name,scripts,pooled in [('baseline',args.baseline,False),('baseline_pool',args.baseline,True),('candidate_pool',SCRIPTS,True)]:
                command=[sys.executable,'-B',str(Path(__file__).resolve()),'--root',str(root),'--scripts',str(scripts)]
                if pooled:command.append('--pooled')
                result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=240)
                if result.returncode:raise RuntimeError(result.stdout+result.stderr)
                values[name]=json.loads(result.stdout)
            assert len({r['decision_sha256'] for v in values.values() for r in v['operations']})==1
            assert not any(r['rejected'] for v in values.values() for r in v['operations'])
            assert inventory()==before
            report['workloads'][str(count)]=values
            print('Completed '+str(count),file=sys.stderr)
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
