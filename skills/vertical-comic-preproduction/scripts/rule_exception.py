"""Scoped user exceptions to portable rules; original source and core image QA stay locked."""
from pathlib import Path
import json
from codex_reference_contract import checked_file

POLICY='scoped_rule_exception_v1'

def locked_hash(panel):
    import hashlib
    return hashlib.sha256(json.dumps(panel['locked_script'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def applicable(panel,root,rule,stage,scope):
    found=[]
    for ref in panel.get('rule_exceptions',[]):
        value=json.loads(checked_file(Path(root),ref).read_text())
        if value.get('rule_id')!=rule['id'] or stage not in value.get('stages',[]):continue
        if scope is None:raise ValueError('规则例外缺少真实书话上下文')
        pid=panel['panel_id'];global_id=scope['episode_id']+'-'+pid if pid.startswith('P') else pid
        if value.get('book_id')!=scope['book_id'] or scope['episode_id'] not in value.get('episode_ids',[]) or not ({pid,global_id}&set(value.get('panel_ids',[]))):continue
        from rule_memory import signature
        if value.get('policy')!=POLICY or value.get('rule_signature')!=signature(rule) or value.get('status')!='APPROVED' or value.get('source_kind')!='user_message' or not value.get('source_locator') or not value.get('quote'):raise ValueError('例外没有当前规则版本/真实用户范围批准')
        if value.get('locked_script_sha256')!=locked_hash(panel):raise ValueError('例外未绑定当前格准确源原文')
        base=Path(value.get('evidence_root',''))
        if not base.is_absolute() or not value.get('artifacts'):raise ValueError('例外缺少真实源依据')
        for item in value['artifacts']:checked_file(base,item)
        waived=value.get('waived_checks',{}).get(stage,[]);alternatives=value.get('alternative_checks',{}).get(stage,[])
        if not isinstance(waived,list) or not waived or not set(waived)<=set(rule['requirements'][stage]['checks']) or not isinstance(alternatives,list) or not alternatives:raise ValueError('例外须明确被替换检查和替代判据')
        if not all(isinstance(x,str) and x.strip() for x in alternatives):raise ValueError('例外替代判据为空')
        found.append((ref,waived,alternatives))
    if len(found)>1:raise ValueError('同格同规则例外重复/冲突')
    return found[0] if found else None
