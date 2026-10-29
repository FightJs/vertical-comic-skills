#!/usr/bin/env python3
"""Isolated dispatch benchmark, not live production or release evidence.

Compare the original full status/candidate algorithm without and with a read
transaction, then bounded selection. Each sample runs in a fresh process with
the same four-panel snapshot. --cli instead runs the actual dispatch CLI through
argparse, validation and receipt/ledger writes in that disposable fixture only.
--baseline-scripts selects an independently frozen old code directory for CLI
comparison; internal 'original' selection is not a frozen old implementation.
"""
import argparse
from contextlib import ExitStack, nullcontext
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts'), str(Path(__file__).parent)]
from codex_reference_contract import file_session, read_json
from _historical_fixture import evaluate
from platform_io import file_lock


def sample(state_path, mode, limit):
    from test_dispatch_preflight import original_selection
    import production_evidence as batch_workflow
    state_path = Path(state_path).resolve()
    state = read_json(state_path)
    control = Path(state['parallel_context']['control_file'])
    with ExitStack() as locks:
        for path in sorted((state_path.with_suffix('.runtime.lock'), control.with_suffix('.dispatch.lock'))):
            locks.enter_context(file_lock(path))
        started, cpu = time.perf_counter(), time.process_time()
        with patch.object(batch_workflow, 'input_errors', wraps=batch_workflow.input_errors) as calls:
            with file_session() if mode != 'original' else nullcontext() as memo:
                if mode == 'bounded':
                    report = evaluate(state, state_path.parent.parent, 'reservation_batch',
                                              {'limit': limit, 'excluded': []})
                    selected = report.get('ready_panel_ids', [])
                else:
                    selected = original_selection(state, state_path.parent.parent, limit)
        return {'selected': selected, 'seconds': round(time.perf_counter()-started,6),
                'cpu_seconds': round(time.process_time()-cpu,6), 'input_checks': calls.call_count,
                'hash_reads': memo['hash_reads'] if memo is not None else None,
                'hash_hits': memo['hash_hits'] if memo is not None else None}


def cli_benchmark(fixture, repeats, limit, baseline_scripts=None):
    """Same fixture bytes, approvals and leases; rebind only checker versions."""
    current = Path(__file__).resolve().parents[1] / 'scripts'
    versions = {'current': current}
    if baseline_scripts:
        versions = {'baseline': Path(baseline_scripts).resolve(), **versions}
    pristine = fixture.state_path.read_bytes()
    samples = {name: [] for name in versions}
    expected = None
    probe = Path(__file__).with_name('dispatch_cli_probe.py')
    try:
        for trial in range(repeats):
            names = list(versions)
            for name in names[trial % len(names):] + names[:trial % len(names)]:
                fixture.state_path.write_bytes(pristine)
                before = set(fixture.root.rglob('*.dispatch-*.json'))
                proc = subprocess.run([sys.executable, '-B', str(probe),
                                       '--scripts', str(versions[name]), '--fixture-state', str(fixture.state_path),
                                       '--limit', str(limit)], capture_output=True,
                                      text=True, encoding='utf-8', timeout=60)
                if proc.returncode:
                    raise AssertionError(proc.stdout + proc.stderr)
                row = json.loads(proc.stdout)
                if expected is None:
                    expected = row['normalized_result']
                if row['normalized_result'] != expected:
                    raise AssertionError('CLI semantic result or receipt binding differs')
                samples[name].append(row)
                # Restore the pristine isolated state before removing only the
                # packet copies created by this completed probe, now unreferenced.
                fixture.state_path.write_bytes(pristine)
                for path in set(fixture.root.rglob('*.dispatch-*.json')) - before:
                    path.unlink()
    finally:
        fixture.state_path.write_bytes(pristine)
    return {'fixture': 'synthetic_4_panels', 'scope': 'actual dispatch CLI with isolated reservation writes',
            'checker_binding_rebound_per_version': True, 'instrumentation_overhead_included': True,
            'not_production_evidence': True, 'decisions_equal': True, 'image_calls': 0,
            'baseline_scripts': str(versions['baseline']) if 'baseline' in versions else None,
            'limit': limit, 'repeats': repeats, 'samples': samples,
            'median_seconds': {name: statistics.median(r['seconds'] for r in rows)
                               for name, rows in samples.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--limit', type=int, default=1)
    parser.add_argument('--sample', choices=('original', 'cached_full', 'bounded'), help=argparse.SUPPRESS)
    parser.add_argument('--fixture-state', help=argparse.SUPPRESS)
    parser.add_argument('--cli', action='store_true', help='Measure real CLI reservation writes in the synthetic fixture')
    parser.add_argument('--baseline-scripts', help='Frozen old scripts directory, used only with --cli')
    args = parser.parse_args()
    if args.repeats < 1 or not 1 <= args.limit <= 4:
        parser.error('repeats must be positive; limit must be 1..4')
    if args.baseline_scripts and not args.cli:
        parser.error('--baseline-scripts requires --cli')
    if args.sample:
        print(json.dumps(sample(args.fixture_state, args.sample, args.limit)))
        return
    from dispatch_fixture import DispatchFixture
    fixture = DispatchFixture(slots=4)
    try:
        if args.cli:
            fixture.source.scope_task()
            fixture.flush()
            print(json.dumps(cli_benchmark(fixture, args.repeats, args.limit, args.baseline_scripts),
                             ensure_ascii=False, indent=2))
            return
        modes = ['original', 'cached_full', 'bounded']
        samples = {mode: [] for mode in modes}
        expected = None
        for trial in range(args.repeats):
            for mode in modes[trial % 3:] + modes[:trial % 3]:
                proc = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()),
                                       '--sample', mode, '--fixture-state', str(fixture.state_path),
                                       '--limit', str(args.limit)], capture_output=True,
                                      text=True, encoding='utf-8', timeout=60, check=True)
                row = json.loads(proc.stdout)
                if expected is None:
                    expected = row['selected']
                if not expected or row['selected'] != expected:
                    raise AssertionError('Selection differs or empty; benchmark rejected')
                samples[mode].append(row)
        medians = {mode: statistics.median(r['seconds'] for r in rows) for mode, rows in samples.items()}
        print(json.dumps({'fixture': 'synthetic_4_panels', 'scope': 'read-only selection under original locks',
                          'not_production_evidence': True, 'image_calls': 0, 'decisions_equal': True,
                          'limit': args.limit, 'repeats': args.repeats, 'samples': samples,
                          'median_seconds': medians,
                          'selection_speedup': round(medians['original']/medians['bounded'],3)},
                         ensure_ascii=False, indent=2))
    finally:
        fixture.close()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    main()
