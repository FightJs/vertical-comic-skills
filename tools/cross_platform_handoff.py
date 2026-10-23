"""CI-only synthetic handoff exchange across independent operating systems.

Never read real project inputs or use real user approvals. Reuse lifecycle test
fixtures to exercise frozen compiler, formal ZIP release, bind and rehearsal.
"""
from pathlib import Path
import argparse
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'skills/vertical-comic-preproduction/scripts'),
                str(ROOT / 'skills/vertical-comic-preproduction/tests')]
from platform_io import configure_stdio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('produce', 'consume'))
    parser.add_argument('--path', required=True, type=Path)
    parser.add_argument('--episode-scope', action='store_true', help='Exercise the new full-episode handoff format')
    args = parser.parse_args()
    if args.action == 'produce':
        from test_direct_handoff import DirectHandoffTests
        case = DirectHandoffTests('test_direct_bound_run_real_full_episode_gates_and_conditional_release')
        try:
            case.setUp()
            if args.episode_scope:
                from handoff_scope import EPISODE_POLICY,EPISODE_WINDOW
                case.index.update(policy=EPISODE_POLICY,production_window_policy=EPISODE_WINDOW)
                for episode in case.index['episodes']:
                    episode.pop('halves')
                    for row in episode['panels']: row['classification']='READY'
                case.save()
            case.test_direct_bound_run_real_full_episode_gates_and_conditional_release()
            args.path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(case.base / '正式交接包.zip', args.path)
        finally:
            case.doCleanups()
        print(json.dumps({'status': 'SYNTHETIC_EXCHANGE_READY', 'image_calls': 0}))
    else:
        import tempfile
        from comic_start import receive
        from handoff_zip import extract
        with tempfile.TemporaryDirectory(prefix='comic-跨机接包-') as tmp:
            result = receive(args.path, output=Path(tmp) / '本地运行')
            if result['status'] != 'READY_FOR_PRODUCTION_ROUTING':
                raise ValueError(json.dumps(result, ensure_ascii=False))
            originals=extract(args.path,Path(tmp)/'提前解压')['root']
            directory=receive(package_root=originals,output=Path(tmp)/'目录接包')
            if directory['status'] != 'READY_FOR_PRODUCTION_ROUTING':
                raise ValueError(json.dumps(directory,ensure_ascii=False))
            print(json.dumps({'status': result['status'], 'image_calls': result['image_calls'],
                              'extracted_directory':directory['status'],'archive_crc':directory['reception']['archive_crc']}))


if __name__ == '__main__':
    configure_stdio()
    main()
