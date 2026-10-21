#!/usr/bin/env python3
"""Paired read-only benchmarks: cumulative contexts and actual semantic CLI.

No production authorization, service calls or live-run writes. All comparisons
use the same synthetic files; counters include probe overhead. SHA256 counters
cover actual buffers returned by Path.read_bytes (not arbitrary content keys).
"""
import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from unittest.mock import patch


def probe(scripts, state):
    sys.path.insert(0, str(Path(scripts).resolve()))
    import input_semantics
    counters = {'json_parses': 0, 'file_hashes': 0, 'hash_bytes': 0, 'path_resolves': 0}
    buffers = {}
    actual_bytes, actual_hash = Path.read_bytes, hashlib.sha256
    actual_json, actual_resolve = json.loads, Path.resolve
    def read_bytes(path):
        value = actual_bytes(path); buffers[id(value)] = value
        return value
    def sha256(value=b'', **kwargs):
        if id(value) in buffers and buffers[id(value)] is value:
            counters['file_hashes'] += 1; counters['hash_bytes'] += len(value)
        return actual_hash(value, **kwargs)
    def loads(*args, **kwargs):
        counters['json_parses'] += 1; return actual_json(*args, **kwargs)
    def resolve(*args, **kwargs):
        counters['path_resolves'] += 1; return actual_resolve(*args, **kwargs)
    output = io.StringIO(); started, cpu = time.perf_counter(), time.process_time()
    with patch.object(sys, 'argv', ['input_semantics.py', '--state', str(state)]), \
            patch.object(Path, 'read_bytes', read_bytes), patch.object(hashlib, 'sha256', sha256), \
            patch.object(json, 'loads', loads), patch.object(Path, 'resolve', resolve), redirect_stdout(output):
        code = input_semantics.main()
    elapsed, cpu = time.perf_counter()-started, time.process_time()-cpu
    report = json.loads(output.getvalue())
    if code or report.get('dispatch_authorized') is not False or report.get('image_calls') != 0:
        raise ValueError('Synthetic semantic CLI failed: '+str(report))
    return {'seconds': elapsed, 'cpu_seconds': cpu, 'counts': counters, 'report': report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-scripts', type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--probe-scripts', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--fixture-state', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.probe_scripts:
        print(json.dumps(probe(args.probe_scripts, args.fixture_state), ensure_ascii=False)); return
    if not args.baseline_scripts or args.repeats < 1: parser.error('baseline and positive repeats required')
    tests = Path(__file__).resolve().parent
    sys.path[:0] = [str(tests.parent/'scripts'), str(tests)]
    import test_input_semantics as fixtures
    fixture = fixtures.RealInputBinding('test_real_final_input_binds_without_mutating_files')
    fixture.setUp()
    try:
        state = fixture.root/'00_输入审计/benchmark-state.json'
        state.write_text(json.dumps(fixture.state), encoding='utf-8')
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in fixture.root.rglob('*') if p.is_file()}
        versions = {'baseline': args.baseline_scripts.resolve(), 'current': tests.parent/'scripts'}
        samples = {mode: {name: [] for name in versions} for mode in ('contexts_35','contexts_165','semantic_cli')}
        expected = {}
        for trial in range(args.repeats):
            names = list(versions)
            for name in names[trial % 2:] + names[:trial % 2]:
                for mode in samples:
                    if mode == 'semantic_cli':
                        cmd = [sys.executable, '-B', str(Path(__file__).resolve()), '--probe-scripts', str(versions[name]), '--fixture-state', str(state)]
                    else:
                        cmd = [sys.executable, '-B', str(tests/'benchmark_preflight.py'), '--scripts', str(versions[name]), '--count', mode.split('_')[-1]]
                    proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=90)
                    if proc.returncode: raise AssertionError(proc.stdout+proc.stderr)
                    row = json.loads(proc.stdout)
                    identity = row['report'] if mode == 'semantic_cli' else row['result_sha256']
                    if mode not in expected: expected[mode] = identity
                    if identity != expected[mode]: raise AssertionError('Different semantic result: '+mode)
                    samples[mode][name].append(row)
        if before != {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in fixture.root.rglob('*') if p.is_file()}:
            raise AssertionError('Read-only fixture changed')
        medians = {mode: {name: statistics.median(r['seconds'] if mode == 'semantic_cli' else r['elapsed_seconds'][0] for r in rows)
                         for name, rows in versions.items()} for mode, versions in samples.items()}
        print(json.dumps({'scope': 'synthetic read-only contexts and actual semantic CLI; not end-to-end production',
            'image_calls': 0, 'decisions_equal': True, 'fixture_unchanged': True,
            'hash_counter': 'sha256_on_Path_read_bytes_buffers', 'repeats': args.repeats,
            'median_seconds': medians, 'samples': samples}, ensure_ascii=False, indent=2))
    finally: fixture.doCleanups()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    main()
