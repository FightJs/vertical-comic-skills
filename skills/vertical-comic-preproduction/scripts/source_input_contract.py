"""Versioned formal source-approval view. Never a view of adopted-image evidence.

Only new opted-in source runs use it. Unknown fields/protocols, candidate reads,
immutable capture/replay and complete JSON readers retain full-file semantics.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import hashlib,json,os
from audit_cache import freeze,ReadOnlyDict,content_key
import codex_reference_contract as c

POLICY='formal_source_inputs_v1'
_STRICT=ContextVar('comic_strict_source_inputs',default=False)
# Explicit versioned schema. All non-progress fields remain dependencies, even
# where current approval readers only use a subset. Unknown fields fall back.
FIELDS=frozenset('''policy book_id episode_id input_priority_policy batch_strategy
review_policy optimization_policy state_dispatch_policy preparation_policy
semantic_audit readiness_policy frame_ratio_policy frame_ratio_plan requested_framing
execution_contract toolchain continuity_sources episode_order runtime_snapshot runtime
generation_packages timing_policy visual_evidence_policy background_policy requested_background
input_quality_policy input_semantics_policy appearance_policy frame_policy production_policy
memory_source usage_config_path requested_generation task_context approval_index execution_mode
batch_plan batch_reviews repair_authorizations episode_failure_diagnosis source_script
source_snapshot visual_basis shot_manifest gates production_authorization state_reviews holds
cancelled authority_policy authority_revision approval_revocations preparation_authorization
parallel_context runtime_pipeline_policy source_input_policy local_execution_context
execution_context runtime_execution_context source_adapter_policy context_rebind_history
half_gates half_inputs calibration_reviews active_input_scope'''.split())
PROGRESS=frozenset('panels dispatch_ledger runtime_history delivery_materials qa_revision_history reservation_requests submission_registrations runtime_operations unknown_resolutions delivery_review delivery_review_history'.split())

class SourceView(ReadOnlyDict):
    def _check(self,key):
        if key not in FIELDS:raise ValueError('SOURCE_VIEW_FIELD_UNDECLARED:'+str(key))
    def get(self,key,default=None):self._check(key);return super().get(key,default)
    def __getitem__(self,key):self._check(key);return super().__getitem__(key)
    def __contains__(self,key):self._check(key);return super().__contains__(key)

@contextmanager
def strict_reads():
    token=_STRICT.set(True)
    try:
        memo=c._valid()
        if memo is not None:
            for source in tuple(memo.get('source_views',{})):c.read_json_readonly(Path(source[1]))
        yield
    finally:_STRICT.reset(token)

def _stamp(path):
    s=path.stat();return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)

def _supported(data):
    return (isinstance(data,dict) and data.get('source_input_policy')==POLICY
            and data.get('execution_mode')=='episode_async_v1'
            and data.get('runtime_pipeline_policy')=='observed_incremental_pipeline_v1'
            and not set(data)-FIELDS-PROGRESS
            and any(r.get('path')=='source_input_contract.py' for r in (data.get('toolchain') or {}).get('files',[]) if isinstance(r,dict)))

def read(path):
    memo=c._valid();logical=os.path.abspath(path)
    if _STRICT.get() or c._READ_VIEW.get() is not None or memo is None:
        return c.read_json_readonly(Path(path))
    target=c.resolve_path(path);name=str(target)
    # Full-file reads always win; do not remove their dependencies or stamps.
    if name in memo['files']:return c.read_json_readonly(Path(path))
    token=('source_inputs',logical,(POLICY,))
    records=memo.setdefault('source_views',{})
    old=records.get(token)
    stamp=_stamp(target)
    if old is not None and old['stamp']==stamp and old['target']==name:
        c._depend(token);return old['value']
    raw=target.read_bytes()
    if _stamp(target)!=stamp or str(c.resolve_path(path))!=name:c._changed('source changed during view read')
    data=json.loads(raw.decode('utf-8-sig'))
    memo['source_input_reads']=memo.get('source_input_reads',0)+1
    memo['source_input_bytes']=memo.get('source_input_bytes',0)+len(raw)
    if not _supported(data):
        # Existing projected observations cannot quietly become full-file facts.
        if old is not None:c._changed('source view contract changed')
        return c.read_json_readonly(Path(path))
    projected={k:freeze(data[k]) for k in sorted(FIELDS) if k in data}
    value=SourceView(projected)
    fingerprint=hashlib.sha256(content_key(projected).encode('utf-8')).hexdigest()
    c._observe('source_inputs',logical,fingerprint,(POLICY,))
    if old is not None:memo['source_progress_refreshes']=memo.get('source_progress_refreshes',0)+1
    records[token]={'target':name,'stamp':stamp,'value':value}
    return value

def verify(memo,*,refresh):
    for token,record in list(memo.get('source_views',{}).items()):
        if refresh and record['target'] not in memo['files']:read(token[1])
        else:
            target=Path(token[1]).resolve()
            if str(target)!=record['target'] or _stamp(target)!=record['stamp']:
                c._changed('SOURCE_VIEW_VERSION_CHANGED: retry outside write lock')
