"""Single-writer, source-bound authoring fragments. No approval or production writes."""
import copy
from pathlib import Path
from input_dependencies import fingerprint, file_hash
from panel_source import read, write_new, validate, expand
from platform_io import atomic_json, file_lock
from codex_reference_contract import checked_file
from frame_ratio_plan import POLICY as RATIO_POLICY, plan_errors, panel_errors

POLICY='preparation_workspace_v1'
SCOPE_POLICY='preparation_scope_source_v1'


def _checked(root,ref):
    raw=Path(ref['path'])
    if not raw.is_absolute():return checked_file(root,ref)
    if not raw.is_file() or file_hash(raw)!=ref.get('sha256'):raise ValueError('WORKSPACE_REFERENCE_HASH_MISMATCH')
    return raw.resolve()


def _ratio_value(value):
    result=copy.deepcopy(value);ref=result.get('frame_ratio_plan')
    if isinstance(ref,dict) and Path(ref.get('path','')).is_absolute():
        path=_checked(Path(value['run_root']),ref)
        result['frame_ratio_plan']={**ref,'path':str(path.relative_to(Path(value['run_root'])))}
    return result


def _input_stamps(value):
    result={}
    for field in ('source_snapshot','frame_ratio_plan'):
        ref=value.get(field)
        if not ref:continue
        raw=Path(ref['path']);path=raw if raw.is_absolute() else Path(value['run_root'])/raw
        info=path.stat()
        result[field]=(str(path.resolve()),info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
    return result


def _same_inputs(value, stamps):
    if _input_stamps(value)!=stamps:raise ValueError('WORKSPACE_INPUT_CHANGED_DURING_PREPARE')


def _source(value):
    root=Path(value['run_root']);source=read(_checked(root,value['source_snapshot']))
    order=source['panel_ids']
    if not order or len(set(order))!=len(order) or value['panel_ids']!=order:
        raise ValueError('WORKSPACE_SOURCE_ORDER_CHANGED')
    errors=plan_errors(_ratio_value(value),root,source)
    if value.get('frame_ratio_policy')!=RATIO_POLICY or errors:
        raise ValueError(';'.join(errors) or 'WORKSPACE_FULL_RATIO_PLAN_REQUIRED')
    return source


def _rows(value, rows, original):
    ids=[r['panel_id'] for r in rows]
    if len(ids)!=len(set(ids)) or not set(ids)<=set(value['panel_ids']):
        raise ValueError('WORKSPACE_DUPLICATE_OR_UNKNOWN_PANEL')
    # Reuse the legacy row contract without relaxing its complete-source guard.
    partial={**value,'policy':'panel_authoring_source_v1','panel_ids':ids,'panels':rows}
    if rows:validate(partial)
    for row in rows:
        shot=expand(row['shot'],value['shared'])
        if shot.get('locked_script')!=original['locked_scripts'][row['panel_id']]:
            raise ValueError('WORKSPACE_LOCKED_SCRIPT_CHANGED:'+row['panel_id'])
        errors=panel_errors(_ratio_value(value),value['run_root'],[shot])
        if errors:raise ValueError(';'.join(errors))


def validate_scope(value):
    if value.get('policy')!=SCOPE_POLICY or value.get('status')!='WORKING_DRAFT':
        raise ValueError('WORKSPACE_INTERNAL_SCOPE_REQUIRED')
    source=_source(value);selected=value['selected_panel_ids']
    if not selected or selected!=[p for p in value['panel_ids'] if p in set(selected)]:
        raise ValueError('WORKSPACE_SCOPE_ORDER_OR_DUPLICATE')
    if [r['panel_id'] for r in value['panels']]!=selected or not set(selected)<=set(value['completed_panel_ids']):
        raise ValueError('WORKSPACE_SCOPE_PENDING_ROWS')
    _rows(value,value['panels'],source)
    return value


class Workspace:
    def __init__(self, root):
        self.root=Path(root).resolve();self.folder=self.root/'.preparation-workspace'
        self.folder.mkdir(parents=True,exist_ok=True)
        self.path=self.folder/'workspace.json';self.lock=self.folder/'writer.lock'

    def initialize(self, source_reference, book_id, episode_id, shared, shot_header, *,
                   frame_ratio_plan=None, frame_ratio_policy=RATIO_POLICY, operation_id='initialize'):
        request=copy.deepcopy({'source_snapshot':source_reference,'book_id':book_id,'episode_id':episode_id,
            'shared':shared,'shot_header':shot_header,'frame_ratio_plan':frame_ratio_plan or expand(shot_header,shared).get('frame_ratio_plan'),
            'frame_ratio_policy':frame_ratio_policy})
        if self.path.exists():
            current=read(self.path)
            if current['initialization_digest']!=fingerprint(request):raise ValueError('WORKSPACE_ALREADY_INITIALIZED_DIFFERENTLY')
            return copy.deepcopy(current)
        source=read(_checked(self.root,source_reference));ids=source['panel_ids']
        value={**request,'policy':POLICY,'status':'WORKING_DRAFT','run_root':str(self.root),
            'panel_ids':ids,'panels':[],'pending_panel_ids':ids,'row_versions':{p:0 for p in ids},
            'revision':0,'shared_version':0,'shared_versions':{k:0 for k in shared},'operations':{},'initialization_digest':fingerprint(request),
            'dispatch_authorized':False,'user_approval':'NOT_GRANTED'}
        header=expand(shot_header,shared)
        if any(header.get(k)!=value[k] for k in ('book_id','episode_id')):raise ValueError('WORKSPACE_HEADER_SCOPE_MISMATCH')
        stamps=_input_stamps(value);_source(value);_same_inputs(value,stamps)
        with file_lock(self.lock):
            if self.path.exists():
                current=read(self.path)
                if current['initialization_digest']!=value['initialization_digest']:raise ValueError('WORKSPACE_ALREADY_INITIALIZED_DIFFERENTLY')
                return copy.deepcopy(current)
            _same_inputs(value,stamps);atomic_json(self.path,value);return copy.deepcopy(value)

    def read(self):
        return read(self.path)

    def receipt(self, operation_id):
        entry=self.read()['operations'].get(operation_id)
        return copy.deepcopy(entry['receipt']) if entry else None

    def _prepare(self, value, fragment):
        original=_source(value)
        base=fragment.get('base_revision')
        if type(base) is not int or base<0 or base>value['revision']:raise ValueError('WORKSPACE_INVALID_BASE_REVISION')
        rows=fragment.get('panels')
        if not isinstance(rows,list) or not rows:raise ValueError('WORKSPACE_REAL_ROWS_REQUIRED')
        for row in rows:
            pid=row['panel_id']
            if pid not in value['row_versions'] or fragment.get('row_versions',{}).get(pid)!=value['row_versions'][pid]:
                raise ValueError('WORKSPACE_ROW_VERSION_CONFLICT:'+pid)
        for pid,version in fragment.get('consumed_rows',{}).items():
            if pid not in value['row_versions'] or value['row_versions'][pid]!=version:raise ValueError('WORKSPACE_CONSUMED_ROW_CHANGED:'+pid)
        updates=fragment.get('shared_updates',{})
        if not isinstance(updates,dict):raise ValueError('WORKSPACE_SHARED_UPDATES_OBJECT_REQUIRED')
        version=fragment.get('shared_version')
        if type(version) is not int or version<0 or version>value['shared_version']:raise ValueError('WORKSPACE_SHARED_VERSION_CONFLICT')
        consumed=fragment.get('consumed_shared')
        required=set()
        def visit(item):
            if isinstance(item,dict):
                if '$shared' in item:
                    key=item['$shared']
                    if key not in required:
                        required.add(key)
                        if key in value['shared']:visit(value['shared'][key])
                for child in item.values():visit(child)
            elif isinstance(item,list):
                for child in item:visit(child)
        visit([value['shot_header'],rows])
        if consumed is not None:
            if not isinstance(consumed,dict) or not required<=set(consumed):raise ValueError('WORKSPACE_SHARED_READSET_INCOMPLETE')
            for key,expected in consumed.items():
                if key not in value['shared']:raise ValueError('WORKSPACE_CONSUMED_SHARED_MISSING:'+key)
                actual=value['shared'][key]
                valid=(type(expected) is int and expected==value['shared_versions'][key]) or (isinstance(expected,str) and expected==fingerprint(actual)) or expected==actual
                if not valid:raise ValueError('WORKSPACE_CONSUMED_SHARED_CHANGED:'+key)
        if version!=value['shared_version'] and (consumed is None or updates):raise ValueError('WORKSPACE_SHARED_VERSION_CONFLICT')
        if updates:
            value['shared'].update(copy.deepcopy(updates));value['shared_version']+=1
            for key in updates:value['shared_versions'][key]=value['shared_versions'].get(key,-1)+1
        _rows(value,rows,original)
        by_id={r['panel_id']:r for r in value['panels']}
        for row in rows:
            by_id[row['panel_id']]=row;value['row_versions'][row['panel_id']]+=1
        value['panels']=[by_id[p] for p in value['panel_ids'] if p in by_id]
        if updates:_rows(value,value['panels'],original)
        value['pending_panel_ids']=[p for p in value['panel_ids'] if p not in by_id]
        value['revision']+=1
        return value

    def submit(self, fragment):
        fragment=copy.deepcopy(fragment);op=fragment.get('operation_id')
        if not isinstance(op,str) or not op.strip():raise ValueError('WORKSPACE_OPERATION_ID_REQUIRED')
        key=fingerprint(fragment)
        while True:
            value=read(self.path);existing=value['operations'].get(op)
            if existing:
                if existing['input_digest']!=key:raise ValueError('WORKSPACE_OPERATION_CONTENT_CONFLICT')
                return copy.deepcopy(existing['receipt'])
            revision=value['revision'];stamps=_input_stamps(value)
            prepared=self._prepare(copy.deepcopy(value),fragment)
            _same_inputs(value,stamps)
            # File/source validation stays outside the sole merge-writer lock.
            with file_lock(self.lock):
                current=read(self.path)
                if current['revision']!=revision:continue
                _same_inputs(current,stamps)
                patch=self.folder/'patches'/(fingerprint(op)+'.json');patch.parent.mkdir(exist_ok=True)
                if patch.exists():
                    if read(patch)!=fragment:raise ValueError('WORKSPACE_ORIGINAL_PATCH_CONFLICT')
                else:atomic_json(patch,fragment)
                receipt={'policy':'preparation_fragment_receipt_v1','operation_id':op,'input_digest':key,
                    'revision':prepared['revision'],'shared_version':prepared['shared_version'],
                    'panel_ids':[r['panel_id'] for r in fragment['panels']],
                    'row_versions':{r['panel_id']:prepared['row_versions'][r['panel_id']] for r in fragment['panels']},
                    'original_patch':{'path':str(patch),'sha256':file_hash(patch)},'dispatch_authorized':False}
                prepared['operations'][op]={'input_digest':key,'receipt':receipt}
                atomic_json(self.path,prepared)
                return copy.deepcopy(receipt)

    def scope(self, panel_ids):
        value=self.read();stamps=_input_stamps(value);selected=list(panel_ids)
        if not selected or len(set(selected))!=len(selected) or not set(selected)<=set(value['panel_ids']):
            raise ValueError('WORKSPACE_INVALID_SCOPE')
        selected=[p for p in value['panel_ids'] if p in set(selected)]
        result={k:copy.deepcopy(v) for k,v in value.items() if k not in {'operations','initialization_digest','pending_panel_ids','revision'}}
        result.update(policy=SCOPE_POLICY,workspace_revision=value['revision'],selected_panel_ids=selected,
            completed_panel_ids=[r['panel_id'] for r in value['panels']],
            panels=[r for r in value['panels'] if r['panel_id'] in selected])
        validate_scope(result);_same_inputs(value,stamps);return result

    def materialize(self, output):
        value=self.read();stamps=_input_stamps(value);source=_source(value)
        if value['pending_panel_ids']:raise ValueError('WORKSPACE_PENDING_ROWS')
        _rows(value,value['panels'],source)
        result={k:copy.deepcopy(value[k]) for k in ('status','book_id','episode_id','run_root','source_snapshot',
            'panel_ids','shared','shot_header','panels','frame_ratio_policy','frame_ratio_plan','dispatch_authorized','user_approval')}
        result['policy']='panel_authoring_source_v1';validate(result);_same_inputs(value,stamps);write_new(output,result);return result
