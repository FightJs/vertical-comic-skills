"""Deterministic CSV projections of adopted-version reviews, never new visual QA."""
import csv
import io
from production_decisions import LABELS

POLICY = 'adopted_issue_csv_v1'
OVERVIEW = '图片问题总览.csv'
DETAILS = '问题明细.csv'
OVERVIEW_FIELDS = ('话号','格号','图片路径','采用版本','交付结论','遗留问题数量','最高优先级','问题摘要','处理建议')
DETAIL_FIELDS = ('话号','格号','图片路径','采用版本','问题编号','问题类别','具体位置','当前问题','正确目标','优先级','处理情况','确认情况')
PRIORITY = {1:'高',2:'普通',3:'低'}
CATEGORY = {1:'①重大',2:'②规则/物理/配饰',3:'③可留人工'}


def encode(fields, rows):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator='\r\n')
    writer.writeheader()
    for row in rows:
        # Open as text in spreadsheet apps; source wording remains in bound JSON.
        safe = {k: ("'"+str(v) if str(v).startswith(('=','+','-','@','\t','\r')) else v) for k,v in row.items()}
        writer.writerow(safe)
    return output.getvalue().encode('utf-8-sig')


def render(indexes, *, episode_prefix=False):
    overview=[];details=[];seen=set()
    for index in indexes:
        eid=index['episode_id']
        for row in index['panels']:
            pid=row['panel_id'];key=(eid,pid)
            if key in seen:raise ValueError('DELIVERY_CSV_HOLD:重复格号')
            seen.add(key)
            image=row.get('delivered_image') or {};path=image.get('path','')
            if episode_prefix and path:path=eid+'/'+path
            common={'话号':eid,'格号':pid,'图片路径':path,'采用版本':row.get('attempt_id','')}
            issues=row['issues']
            categories=[i['category'] for i in issues]
            incomplete=row.get('incomplete_reasons',[])
            overview.append({**common,'交付结论':LABELS[row['outcome']],
                '遗留问题数量':len(issues),'最高优先级':PRIORITY[min(categories)] if categories else '',
                '问题摘要':'；'.join(('未核实：' if i['certainty']=='unverified' else '')+i['problem'] for i in issues) if issues else ('未完成：'+'；'.join(incomplete) if row['outcome'] in {'INCOMPLETE','NETWORK_FAILED','CONTENT_REFUSED'} else '未发现已确认遗留问题'),
                '处理建议':'；'.join(dict.fromkeys(i['handling'] for i in issues)) if issues else ('；'.join(incomplete) if incomplete else '按交付结论使用')})
            if row['outcome']=='CONTENT_REFUSED':
                details.append((1,{**common,'问题编号':pid+'-content-refused','问题类别':'内容审核拒绝缺图',
                    '具体位置':'整格','当前问题':'；'.join(incomplete),'正确目标':'本格图片未生成',
                    '优先级':'高','处理情况':'未继续重试；按授权保留缺格交付',
                    '确认情况':'图像服务返回内容审核拒绝'}))
            if row['outcome']=='NETWORK_FAILED':
                details.append((1,{**common,'问题编号':pid+'-network-missing','问题类别':'调用失败缺图',
                    '具体位置':'整格','当前问题':'；'.join(incomplete),'正确目标':'本格图片未生成',
                    '优先级':'高','处理情况':'已停止自动重试；按授权保留缺格交付',
                    '确认情况':'工具返回网络错误；服务端根因未证实'}))
            for issue in issues:
                details.append((issue['category'],{**common,'问题编号':issue['id'],
                    '问题类别':CATEGORY[issue['category']],'具体位置':issue['location'],
                    '当前问题':issue['problem'],'正确目标':issue['target'],
                    '优先级':PRIORITY[issue['category']],'处理情况':issue['handling'],
                    '确认情况':'已确认' if issue['certainty']=='confirmed' else '未核实疑点，请勿据此直接改图'}))
    return {OVERVIEW:encode(OVERVIEW_FIELDS,overview),DETAILS:encode(DETAIL_FIELDS,[r for _,r in sorted(details,key=lambda x:x[0])])}
