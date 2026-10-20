"""Read-only context benchmark, NOT a production rehearsal or release proof.

Run in fresh processes with --scripts pointing to each implementation. Default
fixtures exercise 35/165 cumulative panels; --state reads an existing run without
rewriting it. No image calls, approvals, snapshot bypass, or production writes.
"""
import argparse
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scripts', type=Path, default=Path(__file__).resolve().parents[1]/'scripts')
    parser.add_argument('--count', type=int, choices=(35, 165), default=35)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--panels', nargs='*')
    parser.add_argument('--repeat', type=int, default=1)
    args = parser.parse_args()
    sys.path.insert(0, str(args.scripts.resolve()))
    from continuity_context import load_context
    from codex_reference_contract import file_session
    with tempfile.TemporaryDirectory(prefix='comic-context-benchmark-') as temp:
        if args.state:
            state_path = args.state.resolve()
            root = state_path.parent.parent
            state = json.loads(state_path.read_text(encoding='utf-8-sig'))
            packets = []
            for row in state['panels']:
                if args.panels and row['panel_id'] not in args.panels:continue
                path = (root/row['package_manifest']['path']).resolve()
                packets.append((json.loads(path.read_text(encoding='utf-8-sig')), path.parent))
        else:
            from audit_fixtures import contexts
            root = Path(temp)
            packets = [(p, root) for p in contexts(root, args.count)]
        elapsed, cpu, fingerprints, errors = [], [], [], []
        with file_session() as memo:
            for _ in range(args.repeat):
                start, cpu_start = time.perf_counter(), time.process_time()
                values = []
                for packet, base in packets:
                    previous, problems = load_context(packet, base)
                    values.append([previous, problems])
                    errors.extend(problems)
                elapsed.append(time.perf_counter()-start)
                cpu.append(time.process_time()-cpu_start)
                fingerprints.append(hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode()).hexdigest())
        print(json.dumps({'benchmark': 'context_only_not_rehearsal', 'panels': len(packets),
                          'elapsed_seconds': elapsed, 'cpu_seconds': cpu,
                          'result_sha256': fingerprints, 'errors': errors, 'image_calls': 0,
                          'audit_statistics': memo.get('audit_statistics', {}),
                          'hash_reads': memo['hash_reads'], 'hash_hits': memo['hash_hits']}, ensure_ascii=False))
        return 1 if errors else 0


if __name__ == '__main__':raise SystemExit(main())
