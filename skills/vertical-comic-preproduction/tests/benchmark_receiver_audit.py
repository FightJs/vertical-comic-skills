#!/usr/bin/env python3
"""Synthetic four-panel receiver benchmark; never production/release evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import test_direct_handoff as fixtures
from test_receiver_audit import decisions
import production_runtime


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats',type=int,default=3)
    args=parser.parse_args()
    if args.repeats<1:parser.error('--repeats must be positive')
    fixture=fixtures.DirectHandoffTests()
    try:
        fixture.setUp()
        ids=['P001','P002','P003','P004']
        base=[sys.executable,'-B',str(Path(production_runtime.__file__)),
              '--state',str(fixture.template/'00_输入审计/生产流程.json')]
        def run(options):
            proc=subprocess.run(base+options,capture_output=True,text=True,encoding='utf-8',timeout=30)
            if proc.returncode:raise RuntimeError(proc.stdout+proc.stderr)
            return json.loads(proc.stdout)
        timings={'separate':[],'combined':[]}
        fingerprint=None
        for trial in range(args.repeats):
            # Alternate order to avoid giving either approach all warm runs.
            outputs={}
            for mode in (('separate','combined') if trial%2==0 else ('combined','separate')):
                started=time.perf_counter()
                if mode=='separate':
                    outputs[mode]={
                        'h001':run(['--action','audit-inputs','--panels',*ids[:2]]),
                        'preparation':run(['--action','readiness']),
                        'all_inputs':run(['--action','audit-inputs','--panels',*ids])}
                else:
                    bundle=run(['--action','receiver-audit','--h001-panels',*ids[:2],'--panels',*ids])
                    outputs[mode]={key:bundle[key] for key in ('h001','preparation','all_inputs')}
                timings[mode].append(round(time.perf_counter()-started,6))
            if decisions(outputs['separate'])!=decisions(outputs['combined']):
                raise AssertionError('Gate decisions differ; benchmark rejected')
            actual=hashlib.sha256(json.dumps(decisions(outputs['combined']),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            if fingerprint is not None and fingerprint!=actual:raise AssertionError('Inputs/results changed across trials')
            fingerprint=actual
        separate_checks=sum(outputs['separate'][key]['audit_reuse_statistics']['receiver_panel_inputs']['runs'] for key in ('h001','all_inputs'))
        medians={key:statistics.median(values) for key,values in timings.items()}
        print(json.dumps({'fixture':'synthetic_4_panels_h001_2','not_release_evidence':True,
            'image_calls':0,'repeats':args.repeats,'seconds':timings,'median_seconds':medians,
            'speedup':round(medians['separate']/medians['combined'],3),
            'process_count':{'separate':3,'combined':1},
            'panel_input_checks':{'separate':separate_checks,'combined':bundle['audit_reuse_statistics']['receiver_panel_inputs']},
            'decisions_equal':True,'result_sha256':fingerprint},ensure_ascii=False,indent=2))
    finally:fixture.doCleanups()


if __name__=='__main__':main()
