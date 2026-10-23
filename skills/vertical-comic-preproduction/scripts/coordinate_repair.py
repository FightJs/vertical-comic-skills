"""Optional coordinate-guided local edits; validates records, never pixels or permission."""
from __future__ import annotations
import math

POLICY = 'coordinate_edit_v1'
METHOD = 'coordinate_local_edit'

def text(v):
    return isinstance(v, str) and bool(v.strip())

def spec(panel):
    focus = panel.get('repair_focus')
    return focus.get('coordinate_edit') if isinstance(focus, dict) else None

def point(v):
    return (isinstance(v, list) and len(v) == 2 and
            all(type(n) in (int, float) and math.isfinite(n) and 0 <= n <= 100 for n in v))

def box(v):
    return (isinstance(v, list) and len(v) == 4 and point(v[:2]) and point(v[2:])
            and v[0] < v[2] and v[1] < v[3])

def decision_errors(d):
    if d.get('method_key') != METHOD:
        return []
    from spatial_contract import decision_errors as spatial_errors
    errors = spatial_errors(d)
    if d.get('policy') != 'first_batch_production_v1' or d.get('action') != 'local_edit':
        errors.append('坐标方法只用于新生产合同的local_edit，不改旧路线或自动重生')
    issues = d.get('issues', [])
    targets = set(d.get('fix_now', []) + d.get('opportunistic', []))
    if not isinstance(issues, list) or not targets:
        return errors + ['坐标方法缺已登记问题及准确修复目标']
    for issue in issues:
        if not isinstance(issue, dict):
            errors.append('坐标问题须为对象'); continue
        scope = issue.get('repair_scope')
        if scope not in {'local_structure', 'global_space', 'uncertain'}:
            errors.append('坐标决定须沿原QA给每个问题标明局部/整体空间/未确定范围')
        if scope == 'global_space' or issue.get('kind') in {'overall_structure', 'scene_identity', 'camera', 'scene_reference'}:
            errors.append('整体空间问题不能拆框进入坐标返修，须先另行处理')
        if issue.get('id') in targets and (scope != 'local_structure' or issue.get('certainty') != 'confirmed'):
            errors.append('坐标修复目标须是已确认的局部结构问题')
    assessment = d.get('coordinate_assessment', {})
    if not isinstance(assessment, dict):
        return errors + ['缺坐标适用性依据']
    if any(not text(assessment.get(k)) for k in ('evidence', 'target_basis', 'input_evidence')):
        errors.append('缺现有观察、批准目标或相关输入检查依据')
    if assessment.get('input_status') not in {'no_conflict_signal', 'resolved'}:
        errors.append('输入冲突疑点未解决，不能只追加坐标继续调用')
    if assessment.get('input_status') == 'resolved' and not text(assessment.get('resolution_evidence')):
        errors.append('输入疑点已解决须引用准确修订/复核依据')
    return errors

def errors(panel, actual_prompt=None, actual_size=None):
    c = spec(panel)
    if c is None:
        return []
    out = []
    if not isinstance(c, dict):
        return ['COORDINATE_HOLD:coordinate_edit须为对象']
    if (panel.get('operation') != 'repair' or panel.get('repair_method', 'local_edit') != 'local_edit'
            or panel.get('visual_evidence_policy') != 'visual_evidence_v1'):
        out.append('坐标方法须为绑定真实底图的局部返修')
    if c.get('policy') != POLICY or c.get('coordinate_system') != 'percent_top_left':
        out.append('坐标策略或坐标系错误')
    source = panel.get('repair_source', {})
    if not text(c.get('source_image_sha256')) or c.get('source_image_sha256') != source.get('image_sha256'):
        out.append('坐标未绑定当前所选底图哈希')
    size = c.get('source_size')
    size_ok = isinstance(size, list) and len(size) == 2 and all(type(n) is int and n > 0 for n in size)
    if not size_ok or actual_size is not None and list(actual_size) != size:
        out.append('坐标底图尺寸与实际原图不符')
    targets = c.get('issue_ids')
    if not isinstance(targets, list) or not targets or any(not text(x) for x in targets) or len(targets) != len(set(targets)):
        out.append('坐标须绑定唯一的问题ID列表'); targets = []
    regions = c.get('edit_regions')
    if not isinstance(regions, list) or not regions:
        out.append('缺具体编辑区域'); regions = []
    region_ids = []
    covered = set()
    for r in regions:
        if not isinstance(r, dict):
            out.append('编辑区域须为对象'); continue
        region_ids.append(r.get('id'))
        if any(not text(r.get(k)) for k in ('id', 'object', 'instruction')) or r.get('issue_id') not in targets or not box(r.get('box')):
            out.append('编辑区域缺对象/目标/有效百分比框')
        if text(r.get('issue_id')): covered.add(r['issue_id'])
    if any(not text(x) for x in region_ids) or len(region_ids) != len(set(x for x in region_ids if isinstance(x, str))):
        out.append('编辑区域ID须唯一')
    if set(targets) != covered:
        out.append('编辑区域未准确覆盖全部本轮问题')
    anchors = c.get('anchors', [])
    if not isinstance(anchors, list):
        out.append('锚点须为列表'); anchors = []
    anchor_ids = []
    for a in anchors:
        if not isinstance(a, dict):
            out.append('锚点须为对象'); continue
        anchor_ids.append(a.get('id'))
        points = a.get('points'); kind = a.get('kind')
        count_ok = isinstance(points, list) and ((kind == 'point' and len(points) == 1) or (kind == 'line' and len(points) == 2) or (kind == 'plane' and len(points) >= 3))
        if (not text(a.get('id')) or a.get('region_id') not in region_ids or not text(a.get('purpose')) or not count_ok or not all(point(p) for p in points)):
            out.append('锚点缺区域/用途，或点线面坐标无效')
        elif len({tuple(p) for p in points}) != len(points):
            out.append('线段/平面锚点不能重合')
    if len(anchor_ids) != len(set(x for x in anchor_ids if isinstance(x, str))):
        out.append('锚点ID须唯一')
    structure = panel.get('repair_focus', {}).get('structural_change', {})
    if not isinstance(structure, dict) or any(not text(structure.get(k)) for k in ('remove', 'replace', 'connect')):
        out.append('坐标返修须说明删除、替换与连接；无旧结构时如实说明')
    expected = c.get('expected_observations')
    if (not isinstance(expected, dict) or not expected or any(not text(k) or not text(v) for k,v in expected.items())):
        out.append('缺可观察的修复目标')
    protected = source.get('preservation_regions', {})
    if size_ok and isinstance(protected, dict):
        for r in regions:
            if not isinstance(r, dict) or not box(r.get('box')): continue
            a = r['box']
            for name,b in protected.items():
                if not isinstance(b,list) or len(b)!=4 or any(type(n) is not int for n in b):continue
                p = [b[0]*100/size[0], b[1]*100/size[1], b[2]*100/size[0], b[3]*100/size[1]]
                if max(a[0],p[0]) < min(a[2],p[2]) and max(a[1],p[1]) < min(a[3],p[3]):
                    resolutions = r.get('preservation_overlap', {})
                    if not isinstance(resolutions,dict) or not text(resolutions.get(name)):
                        out.append('编辑区与保护区重叠须说明对象优先级及允许过渡:'+str(name))
    if not out and actual_prompt is not None and execution_block(panel) not in actual_prompt:
        out.append('实际提示词缺完整当前坐标指令；改坐标或底图后须重编译')
    return ['COORDINATE_HOLD:'+x for x in out]

def execution_block(panel):
    c = spec(panel)
    if c is None: return ''
    problems = errors(panel)
    if problems: raise ValueError(';'.join(problems))
    aliases = [r.get('alias') for r in panel.get('reference_images', []) if r.get('sha256') == c['source_image_sha256']]
    if len(aliases) != 1 or not text(aliases[0]):
        raise ValueError('COORDINATE_HOLD:底图须唯一且有真实输入别名')
    lines = ['【坐标引导局部返修】', f'编辑底图为{aliases[0]}；坐标以该底图左上(0%,0%)、右下(100%,100%)为准，x向右、y向下。']
    for r in c['edit_regions']:
        lines.append(f"编辑区域{r['id']}，对象：{r['object']}，百分比框xyxy={r['box']}；{r['instruction']}")
        for name,value in r.get('preservation_overlap', {}).items():
            lines.append(f'与保护对象{name}重叠时：{value}')
    for a in c.get('anchors', []):
        lines.append(f"区域{a['region_id']}的{a['kind']}锚点{a['id']}，百分比坐标={a['points']}；{a['purpose']}")
    structure = panel['repair_focus']['structural_change']
    lines += [structure[k] for k in ('remove','replace','connect')]
    lines += ['保留：'+v for v in panel.get('repair_source', {}).get('preserved_features', [])]
    lines += ['修复后应可见：'+v for v in c['expected_observations'].values()]
    lines += ['保留批准机位、画幅与真实遮挡；局部物体允许自然出画，不为完整展示弯折。坐标仅为定位引导，不绘制数字、框线或辅助线。']
    return '\n'.join(lines)

def binding_errors(decision, panel):
    c = spec(panel)
    selected = decision.get('method_key') == METHOD
    if not selected and c is None: return []
    if not selected or not isinstance(c, dict):
        return ['COORDINATE_HOLD:实际坐标方法与生产决定不一致']
    out = decision_errors(decision) + errors(panel, panel.get('prompt', ''))
    if out: return out
    if set(c.get('issue_ids', [])) != set(decision.get('fix_now', []) + decision.get('opportunistic', [])):
        out.append('COORDINATE_HOLD:坐标目标与本轮批准修复问题不一致')
    return out

def review_errors(panel, comparison, require_pass=True):
    c = spec(panel)
    if c is None: return []
    expected = c.get('expected_observations', {}) if isinstance(c, dict) else {}
    observations = comparison.get('coordinate_observations', {})
    verdicts = {'PASS'} if require_pass else {'PASS','FAIL','UNREVIEWED','HOLD'}
    if (not isinstance(observations, dict) or set(observations) != set(expected) or
            any(not isinstance(v,dict) or v.get('status') not in verdicts or not text(v.get('observed')) for v in observations.values())):
        return ['坐标返修缺逐目标实图观察；位置改善不代表结构/趾数全部通过']
    return []
