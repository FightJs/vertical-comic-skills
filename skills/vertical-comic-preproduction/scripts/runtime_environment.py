"""Diagnose the selected Python without creating a production RV or calling tools."""
from pathlib import Path
import importlib
import json
import platform
import sys
import tempfile
from platform_io import atomic_json, file_lock, configure_stdio

CORE = ('comic_start', 'usage_config', 'init_preproduction', 'production_runtime',
        'episode_dispatch_queue', 'slot_leases', 'worker_watchdog', 'runtime_snapshot',
        'handoff_zip', 'handoff_delivery', 'make_generation_qa', 'repair_input_guard',
        'repair_prompt_package', 'repair_prompt_package_v2', 'rule_contributions',
        'update_skills', 'installation_state')


def check(*, probe_root=None, require_svg=False):
    errors = []
    dependencies = {}
    if sys.version_info < (3, 12):
        errors.append('Python 3.12+ required')
    for name, minimum, upper in (('PIL', (10, 0), (13, 0)), ('yaml', (6, 0), (7, 0)),
                                 ('openpyxl', (3, 1), (4, 0))):
        try:
            module = importlib.import_module(name)
            dependencies[name] = getattr(module, '__version__', 'available')
            import re
            numbers = re.findall(r'\d+', dependencies[name])
            version = tuple(int(n) for n in (numbers + ['0'])[:2])
            if not minimum <= version < upper:
                errors.append(f'{name}: unsupported version {dependencies[name]}')
        except (ImportError, OSError) as exc:
            errors.append(f'{name}: {exc}')
    for name in CORE:
        try:
            importlib.import_module(name)
        except Exception as exc:
            errors.append(f'{name}: {type(exc).__name__}: {exc}')
    try:
        with tempfile.TemporaryDirectory(prefix='comic-环境-', dir=probe_root) as tmp:
            path = Path(tmp) / '中文 state.json'
            with file_lock(Path(tmp) / 'state.lock', timeout=1):
                atomic_json(path, {'中文': '可读写', 'phase': 1})
                atomic_json(path, {'中文': '可读写', 'phase': 2})
                if json.loads(path.read_text(encoding='utf-8')) != {'中文': '可读写', 'phase': 2}:
                    raise ValueError('UTF-8 roundtrip failed')
            from PIL import Image
            image = Path(tmp) / '参考 图片.png'
            Image.new('RGB', (2, 2)).save(image)
            with Image.open(image) as im:
                im.load()
            image.rename(Path(tmp) / '可移动.png')
    except Exception as exc:
        errors.append(f'filesystem/image probe: {type(exc).__name__}: {exc}')
    svg = 'NOT_CHECKED_OPTIONAL'
    if require_svg:
        try:
            import cairosvg
            cairosvg.svg2png(bytestring=b'<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"/>')
            svg = 'AVAILABLE'
        except Exception as exc:
            svg = 'UNAVAILABLE'
            errors.append(f'SVG rasterizer (CairoSVG/native Cairo): {exc}')
    return {'status': 'PASS' if not errors else 'ENVIRONMENT_HOLD',
            'python': sys.executable, 'python_version': platform.python_version(),
            'platform': platform.platform(), 'dependencies': dependencies,
            'svg': svg, 'errors': errors, 'image_calls': 0,
            'requirements': str(Path(__file__).resolve().parents[1] / 'assets/templates/runtime-requirements.txt'),
            'scope': 'local runtime only; image-service access and visual QA are not tested'}


def require_ready(**kwargs):
    result = check(**kwargs)
    if result['errors']:
        raise ValueError('ENVIRONMENT_HOLD: ' + '; '.join(result['errors']) +
                         f'; selected Python: {sys.executable}')
    return result


if __name__ == '__main__':
    import argparse
    configure_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe-root', type=Path)
    parser.add_argument('--require-svg', action='store_true')
    args = parser.parse_args()
    result = check(probe_root=args.probe_root, require_svg=args.require_svg)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(int(result['status'] != 'PASS'))
