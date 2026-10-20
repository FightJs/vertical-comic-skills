"""Self-contained regression config. Synthetic inputs; never reads a real project."""
import atexit,json,tempfile
from pathlib import Path

_TEMP=None

def config_path():
    global _TEMP
    if _TEMP is None:
        _TEMP=tempfile.TemporaryDirectory(prefix='comic-synthetic-config-');atexit.register(_TEMP.cleanup)
        root=Path(_TEMP.name);(root/'script.json').write_text('{"synthetic":true}', encoding='utf-8', newline='\n');(root/'assets').mkdir()
        file=Path(__file__).resolve()
        repo=next((p for p in file.parents if (p/'examples/comic.config.example.json').is_file()),None)
        skill=file.parents[1]
        template=repo/'examples/comic.config.example.json' if repo else skill/'assets/templates/默认使用配置.json'
        config=json.loads(template.read_text(encoding='utf-8-sig'))
        config['inputs']={'script_path':str(root/'script.json'),'asset_root':str(root/'assets'),
                          'memory_root':str(repo/'memory' if repo else skill/'assets/rule-memory')}
        config['production']={'book':'SYNTHETIC','episodes':['E021','E022','E023','E024','E025']}
        (root/'config.json').write_text(json.dumps(config), encoding='utf-8', newline='\n')
    return str(Path(_TEMP.name)/'config.json')
