"""Check the same interpreter that will install and run the bundle."""
from pathlib import Path
import runpy
import sys

if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    scripts = Path(__file__).resolve().parents[1] / 'skills/vertical-comic-preproduction/scripts'
    sys.path.insert(0, str(scripts))
    runpy.run_path(str(scripts / 'runtime_environment.py'), run_name='__main__')
