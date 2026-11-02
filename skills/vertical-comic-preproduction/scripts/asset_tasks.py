"""Audit only source-selected A-stage asset needs, not historical directories.

The author supplies actual panel scope and the need for reuse. This checks files
and routes missing inputs; it does not judge pixels, identity or human approval.
Rows live in visual_basis.asset_tasks, not a second canonical asset registry.
"""
import argparse
import hashlib
import json
from pathlib import Path


def audit(asset_root, tasks, *, reuse_plan=None):
    root=Path(asset_root).resolve()
    if not root.is_dir() or not isinstance(tasks,list):
        raise ValueError('缺当前全面资产根目录或本批asset_tasks')
    planned={}
    if reuse_plan is not None:
        if reuse_plan.get('policy')!='costume_reuse_v1':raise ValueError('未知衣装复用计划')
        planned={r['requirement_id']:r for r in reuse_plan['requirements']}
        if len(planned)!=len(reuse_plan['requirements']):raise ValueError('衣装需求ID重复')
    results=[];seen=set()
    for row in tasks:
        key=row.get('asset_id');ids=row.get('panel_ids');count=row.get('visible_occurrences')
        if not key or key in seen or not row.get('episode_id') or not isinstance(ids,list) or not ids or any(not isinstance(p,str) or not p for p in ids) or len(set(ids))!=len(ids) or type(count) is not int or count<len(ids) or not row.get('source_basis'):
            raise ValueError('需求须有唯一资产ID、本话准确格号、真实出现次数与源稿依据')
        seen.add(key)
        if row.get('requirement_id'):
            item=planned.get(row['requirement_id'])
            try:
                if not item or item.get('character_id')!=row.get('character_id') or item.get('costume_id')!=row.get('costume_id') or set(item.get('panel_ids',[]))!=set(ids) or item.get('episode_id')!=row.get('episode_id'):
                    raise ValueError('衣装复用计划与当前资产任务书话格范围不一致')
                from costume_requirements import plan as recalculate
                raw=[r for r in reuse_plan['input_requirements'] if r['requirement_id']==row['requirement_id']]
                if len(raw)!=1:raise ValueError('原衣装需求缺失或重复')
                checked=recalculate(reuse_plan['book_id'],reuse_plan['production_episode_ids'],raw,reuse_plan['observations'],
                                    coverage=reuse_plan['coverage'],source_catalog=reuse_plan['source_catalog'])['requirements'][0]
                if checked!=item:raise ValueError('衣装复用结论与来源不一致')
                row={**row,'publication_required':item['publication_required'],
                     'future_count':item['future_count'],'future_coverage':item['future_coverage'],
                     'reuse_decision':item['reuse_decision']}
            except (OSError,ValueError,KeyError,TypeError) as exc:
                row={**row,'publication_required':False,'future_count':None,'future_coverage':'UNKNOWN',
                     'reuse_decision':'REUSE_HOLD','reuse_issue':str(exc)}
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
        from asset_format import contract,review_errors
        format_contract=contract(row);format_issues=[]
        if format_contract and verified:
            format_issues=review_errors(row.get('format_review'),selected.get('sha256'))
            if format_issues:
                route='review_reference_format';reason='文件已核验，但人物衣装参考的全身主图及正侧背全身三视图尚未真实观察通过'
        results.append({**row,'format_contract':format_contract,'format_issues':format_issues,
                        'ready_for_use':verified and not format_issues and route=='reuse','base_reference_verified':verified,
                        'file_status':'VERIFIED' if route=='reuse' else 'ASSET_GAP',
                        'resolution':route,'reason':reason,'approval':'NOT_GRANTED_BY_FILE_AUDIT'})
    return {'scope':'requested_asset_tasks_only','asset_tasks':results,
            'gap_panel_ids':list(dict.fromkeys(p for r in results if r['file_status']=='ASSET_GAP' for p in r['panel_ids'])),
            'image_calls':0}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--asset-root',required=True);p.add_argument('--visual-basis',required=True);p.add_argument('--reuse-plan')
    a=p.parse_args()
    try:
        value=json.loads(Path(a.visual_basis).read_text(encoding='utf-8-sig'))
        print(json.dumps(audit(a.asset_root,value.get('asset_tasks'),reuse_plan=json.loads(Path(a.reuse_plan).read_text(encoding='utf-8-sig')) if a.reuse_plan else None),ensure_ascii=False));return 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'ASSET_AUDIT_HOLD','error':str(exc)},ensure_ascii=False));return 1


if __name__=='__main__':
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
