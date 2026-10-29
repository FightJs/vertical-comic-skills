"""Create a narrow host adapter copy; never alter a frozen runtime or its identity."""
from pathlib import Path
import hashlib, json, shutil, importlib.util

HOST=Path(__file__).resolve().parent

def prepare(state_path, request):
    from codex_reference_contract import read_json, checked_file, digest
    from runtime_snapshot import verify
    from platform_io import atomic_json
    path=Path(state_path).resolve();root=path.parent.parent;state=read_json(path)
    verified=verify(state['runtime_snapshot'])
    evidence=read_json(checked_file(root,request['evidence']))
    auth=read_json(checked_file(root,request['authorization']))
    if 'compatibility_execution' not in auth.get('operations',[]):
        raise ValueError('COMPATIBILITY_AUTHORIZATION_REQUIRED: use existing explicit user instruction')
    code=hashlib.sha256(json.dumps([state['runtime_snapshot'],request],sort_keys=True).encode()).hexdigest()
    folder=path.parent/'recovery_execution'/code;folder.mkdir(parents=True,exist_ok=True)
    files=[]
    for name in ('no_image_recovery.py','slot_leases.py'):
        source=HOST/name;target=folder/name;expected=digest(source)
        if not target.exists():
            # Publish complete, immutable content before the manifest becomes visible.
            raw=source.read_bytes()
            import os,tempfile
            with tempfile.NamedTemporaryFile(dir=folder,delete=False) as stream:
                temp=Path(stream.name);stream.write(raw)
            try:
                try:os.link(temp,target)
                except FileExistsError:pass
            finally:temp.unlink(missing_ok=True)
        if digest(target)!=expected:raise ValueError('RECOVERY_ADAPTER_BYTES_CHANGED')
        files.append({'path':name,'sha256':expected})
    manifest={'policy':'frozen_no_image_adapter_v1','state_path':str(path),
              'original_runtime_snapshot':state['runtime_snapshot'],'frozen_scripts':verified['scripts'],
              'request':request,'files':files,'scope':[request['panel_id']],
              'frozen_tools_replaced':False,'quality_round_reset':False,'image_calls':0}
    mp=folder/'adapter.json'
    if mp.exists():
        if read_json(mp)!=manifest:raise ValueError('RECOVERY_ADAPTER_CONFLICT')
    else:atomic_json(mp,manifest)
    return {'path':str(mp),'sha256':digest(mp)}

def load(adapter_ref, state_path, request):
    from codex_reference_contract import read_json,digest
    from runtime_snapshot import verify
    mp=Path(adapter_ref['path']).resolve()
    if digest(mp)!=adapter_ref['sha256']:raise ValueError('RECOVERY_ADAPTER_HASH_CHANGED')
    manifest=read_json(mp);state=read_json(Path(state_path))
    if (manifest.get('policy')!='frozen_no_image_adapter_v1' or manifest.get('state_path')!=str(Path(state_path).resolve()) or
        manifest.get('request')!=request or manifest.get('original_runtime_snapshot')!=state['runtime_snapshot']):
        raise ValueError('RECOVERY_ADAPTER_SCOPE_CHANGED')
    verify(state['runtime_snapshot'])
    for ref in manifest['files']:
        if ref['path'] not in {'no_image_recovery.py','slot_leases.py'} or digest(mp.parent/ref['path'])!=ref['sha256']:
            raise ValueError('RECOVERY_ADAPTER_BYTES_CHANGED')
    spec=importlib.util.spec_from_file_location('_frozen_no_image_adapter',mp.parent/'no_image_recovery.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module
