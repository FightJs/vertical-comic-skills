"""Audit only source-selected A-stage asset needs, not historical directories.

The author supplies actual panel scope and the need for reuse. This checks files
and routes missing inputs; it does not judge pixels, identity or human approval.
Rows live in visual_basis.asset_tasks, not a second canonical asset registry.
"""
import argparse
import hashlib
import json
from pathlib import Path


def audit(asset_root, tasks):
    root=Path(asset_root).resolve()
    if not root.is_dir() or not isinstance(tasks,list):
        raise ValueError('缺当前全面资产根目录或本批asset_tasks')
    results=[];seen=set()
    for row in tasks:
        key=row.get('asset_id');ids=row.get('panel_ids');count=row.get('visible_occurrences')
        if not key or key in seen or not row.get('episode_id') or not isinstance(ids,list) or not ids or any(not isinstance(p,str) or not p for p in ids) or len(set(ids))!=len(ids) or type(count) is not int or count<len(ids) or not row.get('source_basis'):
            raise ValueError('需求须有唯一资产ID、本话准确格号、真实出现次数与源稿依据')
        seen.add(key)
        selected=row.get('reference');verified=False;reason='未绑定本批实际参考'
        if selected is not None:
            name=selected.get('path','');p=Path(name)
            if not name or p.is_absolute() or '..' in p.parts or '\\' in name:
                raise ValueError('参考须为全面资产根内相对路径；历史绝对路径不作实际输入')
            p=root/p
            if not p.resolve().is_relative_to(root) or p.is_symlink():
                raise ValueError('实际参考越界/符号链接')
            verified=p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==selected.get('sha256')
            reason='文件与内容哈希相符，仍须实际看图及适用批准' if verified else '本次选定的必要参考缺失或哈希不符'
        if row.get('existing_asset_requires_extension') is True:
            route='supplement_view_or_state'
            reason='已有基准仍须补本批必要视角/状态；文件可读不证明目标视角齐全'
        elif verified:
            route='reuse'
        elif row.get('publication_required') is True:
            route='canonical_candidate'
        elif count==1 and row.get('inline_sufficient') is True:
            route='inline_one_off'
        else:
            route='temporary_reference'
        results.append({**row,'base_reference_verified':verified,
                        'file_status':'VERIFIED' if route=='reuse' else 'ASSET_GAP',
                        'resolution':route,'reason':reason,'approval':'NOT_GRANTED_BY_FILE_AUDIT'})
    return {'scope':'requested_asset_tasks_only','asset_tasks':results,
            'gap_panel_ids':list(dict.fromkeys(p for r in results if r['file_status']=='ASSET_GAP' for p in r['panel_ids'])),
            'image_calls':0}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--asset-root',required=True);p.add_argument('--visual-basis',required=True)
    a=p.parse_args()
    try:
        value=json.loads(Path(a.visual_basis).read_text())
        print(json.dumps(audit(a.asset_root,value.get('asset_tasks')),ensure_ascii=False));return 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'ASSET_AUDIT_HOLD','error':str(exc)},ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
