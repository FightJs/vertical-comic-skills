"""Scoped user exceptions to portable rules; original source and core image QA stay locked."""
from codex_reference_contract import read_json
from pathlib import Path
import json
from codex_reference_contract import checked_file

POLICY='scoped_rule_exception_v1'

def locked_hash(panel):
    import hashlib
    return hashlib.sha256(json.dumps(panel['locked_script'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def evidence_base(value, exception_path):
    base = Path(value.get('evidence_root', ''))
    mode = value.get('evidence_root_mode')
    if mode == 'exception_relative_v1':
        if base.is_absolute() or '..' in base.parts or not value.get('evidence_root'):
            raise ValueError('可移植例外的依据须位于例外文件目录内')
        from codex_reference_contract import resolve_path
        parent = resolve_path(Path(exception_path).parent)
        result = resolve_path(parent / base)
        if not result.is_relative_to(parent):raise ValueError('规则例外依据目录逃逸')
        return result
    if mode is not None or not base.is_absolute():
        raise ValueError('例外缺少明确依据根；旧绝对路径不自动改写')
    return base


def applicable(panel,root,rule,stage,scope):
    found=[]
    for ref in panel.get('rule_exceptions',[]):
        exception_path=checked_file(Path(root), ref)
        value=read_json(exception_path)
        if value.get('rule_id')!=rule['id'] or stage not in value.get('stages',[]):continue
        if scope is None:raise ValueError('规则例外缺少真实书话上下文')
        pid=panel['panel_id'];global_id=scope['episode_id']+'-'+pid if pid.startswith('P') else pid
        if value.get('book_id')!=scope['book_id'] or scope['episode_id'] not in value.get('episode_ids',[]) or not ({pid,global_id}&set(value.get('panel_ids',[]))):continue
        from rule_memory import signature
        if value.get('policy')!=POLICY or value.get('rule_signature')!=signature(rule) or value.get('status')!='APPROVED' or value.get('source_kind')!='user_message' or not value.get('source_locator') or not value.get('quote'):raise ValueError('例外没有当前规则版本/真实用户范围批准')
        if value.get('locked_script_sha256')!=locked_hash(panel):raise ValueError('例外未绑定当前格准确源原文')
        base=evidence_base(value,exception_path)
        if not value.get('artifacts'):raise ValueError('例外缺少真实源依据')
        for item in value['artifacts']:checked_file(base,item)
        waived=value.get('waived_checks',{}).get(stage,[]);alternatives=value.get('alternative_checks',{}).get(stage,[])
        if not isinstance(waived,list) or not waived or not set(waived)<=set(rule['requirements'][stage]['checks']) or not isinstance(alternatives,list) or not alternatives:raise ValueError('例外须明确被替换检查和替代判据')
        if not all(isinstance(x,str) and x.strip() for x in alternatives):raise ValueError('例外替代判据为空')
        found.append((ref,waived,alternatives))
    if len(found)>1:raise ValueError('同格同规则例外重复/冲突')
    return found[0] if found else None
