"""Shared source, attempt and output evidence. No legacy scheduling or review loop."""
from pathlib import Path
from codex_reference_contract import resolve_path,read_json,checked_file,digest,execution_errors,validate_panel
from style_contract import POLICY as STYLE_POLICY,validate_style,output_spec_errors
from staged_workflow import POLICY,DONE,approval_errors,basis_errors,qa_errors
from rule_memory import application_errors as memory_errors,binding_errors as memory_binding_errors
MODE='episode_async_v1'
TERMINAL={'VISUAL_PASS','USER_ACCEPTED','VISUAL_FAIL','CALL_FAILED','RESULT_UNKNOWN','CANCELLED'}
PASS={'VISUAL_PASS','USER_ACCEPTED'}
SNAPSHOT_KEYS=('panel_id','source_panel_id','attempt_id','round_id','status','package_manifest','shot_subset','qa_report','output','failure_diagnosis','call_evidence')
SHOT_FIELDS = ("locked_script", "framing", "frame_ratio", "camera_view_signature",
               "character_bindings", "scene_binding", "continuity_contract", "visual_state_keys",
               "generation_dependencies", "design_dependencies", "requires_state_review", "memory_tags", "state_review_policy", "adjacent_face_comparison", "calibration_anchor", "rule_exceptions", "source_panel_id", "visual_resolution", "frame_ratio_reason", "visual_evidence_policy", "visual_evidence", "semantic_facts", "subject_visibility")

def read(path): return read_json(path)


def snapshot(record): return {k: record[k] for k in SNAPSHOT_KEYS if k in record}


def settings(state):
    review = state.get('review_policy', {})
    if type(review.get('systemic_failure_count_gt')) is not int or type(review.get('max_auto_correction_rounds')) is not int or review.get('systemic_failure_count_gt') != 5 or review.get('max_auto_correction_rounds') != 1:
        raise ValueError('生产合同须保留准确诊断阈值与最多一轮自动修正')
    return review


def attempt_errors(state, root, item):
    from no_image_recovery import history_errors
    errors = history_errors(state, root, item)
    pid = item.get('panel_id')
    if not isinstance(item.get('attempt_id'), str) or not item['attempt_id'].strip() or type(item.get('round_id')) is not int or item['round_id'] not in (1, 2):
        return [f'{pid}:缺少准确尝试编号/轮次']
    if item.get('status') not in TERMINAL: return [f'{pid}:尚未完成请求与逐格审查']
    if item['status'] in {'CALL_FAILED', 'RESULT_UNKNOWN', 'CANCELLED'}:
        log = read(checked_file(root, item.get('call_evidence')))
        if log.get('attempt_id') != item['attempt_id'] or log.get('status') != item['status'] or not log.get('source_locator') or not log.get('evidence'):
            errors.append(f'{pid}:调用异常/取消记录与本轮尝试不一致')
        return errors
    manifest_path = checked_file(root, item.get('package_manifest'))
    packet = read(manifest_path)
    panels = packet.get('panels', [])
    if state.get('execution_contract')=='comic_execution_v2':
        source=read(checked_file(root,state['source_snapshot']));mapping={x['panel_id']:x['source_panel_id'] for x in source['id_mapping']['pairs']}
        if item.get('source_panel_id')!=mapping.get(pid) or not panels or panels[0].get('source_panel_id')!=mapping.get(pid):errors.append('SOURCE_ID_HOLD:历史尝试原格号与准确冻结映射不一致')
    if len(panels) != 1 or panels[0].get('panel_id') != pid or packet.get('execution_mode') != state.get('execution_mode', MODE) or packet.get('book_id') != state['book_id'] or packet.get('episode_id') != state['episode_id']:
        return [f'{pid}:轮次执行包格号/书话/模式不一致']
    if type(packet.get('round_context', {}).get('round_id')) is not int or packet.get('round_context') != {'batch_id': item.get('batch_id', packet.get('round_context', {}).get('batch_id')), 'round_id': item['round_id'], 'attempt_id': item['attempt_id']}:
        errors.append(f'{pid}:执行包与尝试轮次不一致')
    output = checked_file(root, item.get('output'))
    report = read(checked_file(root, item.get('qa_report')))
    items = report.get('panels', [])
    if report.get('source_manifest_sha256') != digest(manifest_path) or len(items) != 1 or items[0].get('panel_id') != pid or items[0].get('image_sha256') != digest(output):
        return errors + [f'{pid}:逐格QA不是当前执行包及返回图']
    if panels[0].get('generation_execution', {}).get('attempt_id') != item['attempt_id']:
        errors.append(f'{pid}:轮次记录与实际调用attempt_id不一致')
    if 'parallel_context' in state:
        from production_evidence import dispatch_errors
        errors.extend(dispatch_errors(state, root, packet, pid, digest(output)))
    from light_review import enabled as light_enabled, evidence_errors as light_errors
    if light_enabled(state):
        return errors + light_errors(root, item, require_pass=item['status'] in PASS)
    if item['status'] in PASS:
        from staged_workflow import qa_errors
        errors.extend(qa_errors(root, item))
    else:
        from visual_evidence import review_errors as visual_review_errors
        actual_size = None
        if panels[0].get("visual_evidence_policy"):
            from PIL import Image
            from codex_reference_contract import physical_file
            with Image.open(physical_file(output)) as opened: actual_size = opened.size
        errors.extend(visual_review_errors(panels[0], items[0], require_pass=False, image_size=actual_size))
        diagnosis = item.get('failure_diagnosis', {})
        if not diagnosis.get('reviewer') or not diagnosis.get('evidence') or not diagnosis.get('layer'):
            errors.append(f'{pid}:失败缺少实际看图者/依据/最早失败层')
        from continuity_contract import dimension_template
        from style_contract import review_template as style_template
        expected_dimensions = dimension_template(panels[0])
        actual_dimensions = items[0].get('dimension_review', {})
        if set(actual_dimensions) != set(expected_dimensions):
            errors.append(f'{pid}:失败图仍须完整五维与画风自审')
        for key, expected_review in expected_dimensions.items():
            actual = actual_dimensions.get(key, {})
            applicability = (expected_review.get('expected') or {}).get('applicability')
            if actual.get('expected') != expected_review.get('expected') or (applicability == 'REQUIRED' and (actual.get('status') not in {'PASS', 'FAIL'} or not actual.get('reviewer') or not actual.get('evidence'))) or (applicability != 'REQUIRED' and actual.get('status') != applicability):
                errors.append(f'{pid}:{key}未审或修改了批准适用范围')
        style = items[0].get('style_review', {})
        expected_style = style_template(panels[0])
        if style.get('status') not in {'PASS', 'FAIL'} or not style.get('reviewer') or not style.get('evidence') or any(style.get(k) != expected_style[k] for k in ('reference_files', 'traits')):
            errors.append(f'{pid}:失败图画风未按原样例实际核对')
        reviews = [*items[0].get('dimension_review', {}).values(), items[0].get('style_review', {})]
        if not any(isinstance(r, dict) and r.get('status') == 'FAIL' and r.get('reviewer') and r.get('evidence') for r in reviews):
            errors.append(f'{pid}:未在真实六项QA中记录失败项，不能虚增失败张数')
        preflight, submission = validate_panel(panels[0], manifest_path.parent, enforce_input_budget=False)
        errors.extend(preflight)
        execution = panels[0].get('generation_execution', {})
        if execution.get('status') != 'COMPLETED' or execution.get('attempt_id') != item['attempt_id'] or submission is None:
            errors.append(f'{pid}:缺少本尝试真实生图完成证据')
        else:
            errors.extend(execution_errors(execution, submission, manifest_path.parent, pid))
            res = read(checked_file(manifest_path.parent, execution['response_evidence']))
            if not any(r.get('sha256') == digest(output) for r in res.get('outputs', [])):
                errors.append(f'{pid}:失败图不是本次调用实际返回')
    return errors


def repair_route_errors(state, diagnosis, panel_ids):
    if not state.get('runtime'):return []
    routes=diagnosis.get('repair_routes',{})
    errors=[]
    if set(routes)!=set(panel_ids):errors.append('每个失败格须明确最早失败层、修正路线及保留约束')
    for pid in panel_ids:
        route=routes.get(pid,{})
        if route.get('route')!='targeted_image_repair' or route.get('earliest_layer')!='generation_execution' or not route.get('evidence') or not isinstance(route.get('preserve_constraints'),list) or not route['preserve_constraints']:
            errors.append(f'{pid}:输入/基准/镜头/提示词问题应返回对应阶段；仅执行失败可自动定向修图')
    return errors


def write_contact_sheet(root, batch, records, destination):
    """Actual selected window images in source order; review aid only, no PASS."""
    from PIL import Image, ImageDraw
    dest = Path(destination).resolve(); dest.relative_to(Path(root).resolve())
    tiles = []
    for pid in batch['panel_ids']:
        path = checked_file(root, records[pid].get('output'))
        from codex_reference_contract import physical_file
        with Image.open(physical_file(path)) as opened:
            thumb = opened.convert('RGB'); thumb.thumbnail((360, 480))
        tile = Image.new('RGB', (380, 520), 'white')
        tile.paste(thumb, ((380-thumb.width)//2, 30)); ImageDraw.Draw(tile).text((10,8), pid, fill='black'); tiles.append(tile)
    columns = min(5, len(tiles)); rows = (len(tiles)+columns-1)//columns
    sheet = Image.new('RGB', (380*columns,520*rows), '#dddddd')
    for i,tile in enumerate(tiles): sheet.paste(tile, ((i%columns)*380,(i//columns)*520))
    with dest.open('xb') as output: sheet.save(output, format='JPEG', quality=95)
    return {'status':'UNREVIEWED_CONTACT_SHEET_CREATED','path':str(dest),'panel_ids':batch['panel_ids']}


def dependency_basis(root, package_path, packet, shot, basis, records, state=None):
    """Bind image-dependent shots to the exact checked predecessor image bytes."""
    deps = shot["generation_dependencies"]
    bound = packet.get("dependency_outputs", {})
    if not isinstance(bound, dict) or set(bound) != set(deps):
        raise ValueError("dependency_outputs须准确覆盖镜头的前格实图依赖")
    panel = packet["panels"][0]
    extra = []
    for pid in deps:
        record = records[pid]
        if record.get("status") not in DONE:
            raise ValueError(f"{pid}:前格实图尚未验收")
        checked_file(root, record.get("output"))
        checked_file(package_path.parent, bound[pid])
        if bound[pid]["sha256"] != record["output"]["sha256"]:
            raise ValueError(f"{pid}:前格图片换版，依赖调用及检查已失效")
        aliases = {r["alias"] for r in panel.get("reference_images", []) if r.get("sha256") == bound[pid]["sha256"]}
        bindings = [b for b in panel.get("reference_bindings", []) if b.get("alias") in aliases]
        if not aliases or not bindings or any(b.get("purpose") not in {"pose_interaction", "scene_view", "framing", "spatial_layout", "prop_state"} for b in bindings):
            raise ValueError(f"{pid}:前格实图须实际传入且只作动作/空间/构图/道具依据，不能替代身份衣装画风")
        extra.append(bound[pid])
    effective={**basis, "reference_files": [*basis["reference_files"], *extra]}
    if packet.get('calibration_repair'):
        if state is None:raise ValueError('校准编辑目标须有原生产状态，不可单独绕过来源核验')
        from calibration_repair import source_basis
        effective=source_basis(state,root,package_path,packet,effective)
    from visual_evidence import repair_basis
    return repair_basis(state,root,panel,effective,records)


def dispatch_errors(state, root, packet, pid, output_sha256=None):
    if "parallel_context" not in state:
        return ["并行执行回执不能删除上下文后按独立任务使用"] if "dispatch_receipt" in packet else []
    from parallel_dispatch import receipt_errors
    if state.get("execution_mode") in {"half_episode_async_v1", "episode_async_v1"}:
        receipt = packet.get("dispatch_receipt", {})
        context = packet.get("round_context", {})
        if any(receipt.get(k) != context.get(k) for k in ("batch_id", "round_id", "attempt_id")):
            return ["执行包round_context与实际调度回执不一致"]
    return receipt_errors(state["parallel_context"], root, state["book_id"], state["episode_id"],
                          pid, packet.get("dispatch_receipt"), output_sha256)


def completed_errors(state, root, record, shot, basis, records, *, require_pass=True):
    from light_review import enabled as light_enabled
    light = light_enabled(state)
    if require_pass:
        errors = qa_errors(root, record)
    else:
        from production_evidence import attempt_errors
        errors = attempt_errors(state, root, record)
        packet_path = checked_file(root, record['package_manifest'])
        packet = read(packet_path); panel = packet['panels'][0]
        qa = read(checked_file(root, record['qa_report'])); item = qa['panels'][0]
        tags = []
        if state.get('execution_contract') == 'comic_execution_v2':
            from continuity_context import rule_tags
            tags = rule_tags(packet, packet_path.parent, panel)
        from rule_memory import application_errors
        if not light: errors.extend(application_errors(packet.get('memory_source'), 'image_review', panel,
            packet_path.parent, applications=item.get('memory_review', []),
            image_sha256=record['output']['sha256'], context_tags=tags, scope=packet, require_pass=False))
    packet = read(checked_file(root, record.get("package_manifest")))
    from panel_readiness import binding_errors as readiness_binding
    errors.extend(readiness_binding(state,packet))
    if state.get('preparation_policy')=='episode_preparation_v1' and packet.get('preparation_policy')!=state['preparation_policy']:
        errors.append('验收包未绑定获批全话准备模式')
    from frame_ratio_plan import binding_errors as ratio_binding_errors
    errors.extend(ratio_binding_errors(state,packet))
    if state.get('execution_contract') and packet.get('execution_contract')!=state['execution_contract']:errors.append('执行包缺少本次完整执行合同；不能使用本话临时检查器降级')
    from continuity_context import binding_errors as prior_binding_errors
    errors.extend(prior_binding_errors(state,root,packet,checked_file(root,record['package_manifest']).parent))
    if state.get("optimization_policy") in {"scoped_half_review_v1", "scoped_episode_review_v1"} and packet.get("optimization_policy") != state["optimization_policy"]:
        errors.append("优化执行包缺少相同策略，不能退回旧输入合同")
    errors.extend(memory_binding_errors(state, packet=packet))
    tags=[]
    if state.get('execution_contract')=='comic_execution_v2':
        from continuity_context import rule_tags
        shot_path=checked_file(root,state['shot_manifest'])
        tags=rule_tags(read(shot_path),shot_path.parent,shot)
    errors.extend(memory_errors(state.get("memory_source"), "shot_design", shot, root,context_tags=tags,scope=state))
    if packet.get("book_id") != state["book_id"] or packet.get("episode_id") != state["episode_id"]:
        errors.append("验收包本书/本话不一致")
    if packet.get("execution_mode") != state.get("execution_mode", MODE) or len(packet.get("panels", [])) != 1:
        return errors + ["验收包执行模式不一致或非单格包"]
    panel = packet["panels"][0]
    if panel.get('repair_method') == 'regenerate' and state.get('production_policy') != 'first_batch_production_v1':
        errors.append('旧运行不支持新重生决定；不允许补字段绕过')
    from visual_evidence import binding_errors as visual_binding, packet_errors as visual_packet_errors
    errors.extend(visual_binding(state, packet))
    errors.extend(visual_packet_errors(state, shot, panel, basis))
    from visual_evidence import repair_binding_errors
    errors.extend(repair_binding_errors(panel, record))
    if state.get('execution_mode') == 'episode_async_v1':
        from image_risk_guards import packet_errors as risk_packet_errors
        errors.extend(risk_packet_errors(shot,panel))
    from repair_input_guard import repair_errors as repair_input_errors
    errors.extend(repair_input_errors(panel, require_focus=state.get('execution_mode') == 'episode_async_v1'))
    if state.get('execution_contract')=='comic_execution_v2' and panel.get('source_panel_id')!=record.get('source_panel_id'):errors.append('SOURCE_ID_HOLD:验收包原格号与准确源映射不一致')
    effective_basis = dependency_basis(root, checked_file(root, record["package_manifest"]), packet, shot, basis, records,state)
    errors.extend(basis_errors(panel, effective_basis))
    if state.get("visual_evidence_policy") and require_pass and not light:
        from visual_evidence import comparison_errors
        qa = read(checked_file(root, record["qa_report"]))
        item = next((q for q in qa.get("panels", []) if q.get("panel_id") == record["panel_id"]), {})
        errors.extend(comparison_errors(panel, item, records, root))
    errors.extend(dispatch_errors(state, root, packet, record["panel_id"], record["output"]["sha256"]))
    for key in SHOT_FIELDS:
        if panel.get(key) != shot.get(key):
            errors.append(f"{record['panel_id']}:{key}与获批镜头不一致")
    return errors


def input_errors(state, root, record, shot, basis, records, *, candidate=False, dispatch_audit=False, preparation_only=False):
    """Full existing single-panel preflight; batching does not weaken inputs."""
    book, episode, pid = state["book_id"], state["episode_id"], record["panel_id"]
    authorization = state.get("production_authorization")
    if preparation_only and not (candidate or dispatch_audit):
        return ['PREPARATION_AUTHORITY_HOLD:前期授权只允许只读候选或接包审计']
    preparation_role = preparation_only and 'preparation_authorization' in state and not state.get('production_authorization')
    if preparation_role:
        if state.get('parallel_context'):
            return ['PREPARATION_AUTHORITY_HOLD:前期授权不得用于线上调度上下文']
        from task_context import preparation_errors
        errors = preparation_errors(state, root, [pid])
    else:
        errors = approval_errors(authorization, root, [state["source_script"]], book, episode)
        if isinstance(authorization, dict) and (authorization.get('policy') == 'preparation_authorization_v1' or authorization.get('phase') == 'preparation'):
            errors.append('PREPARATION_AUTHORITY_HOLD:前期记录不能用作正文生产授权')
        if pid not in (authorization or {}).get("panel_ids", []) and episode+'-'+pid not in (authorization or {}).get('panel_ids',[]):
            errors.append("当前格不在已授权生产范围")
    manifest_path = checked_file(root, record.get("package_manifest"))
    packet = read(manifest_path)
    if preparation_role and packet.get('dispatch_receipt'):
        errors.append('PREPARATION_AUTHORITY_HOLD:前期授权不得用于已领取回执')
    from panel_readiness import binding_errors as readiness_binding
    errors.extend(readiness_binding(state,packet))
    if state.get('preparation_policy')=='episode_preparation_v1' and packet.get('preparation_policy')!=state['preparation_policy']:
        errors.append('执行包未绑定获批全话准备模式')
    from frame_ratio_plan import binding_errors as ratio_binding_errors
    errors.extend(ratio_binding_errors(state,packet))
    if state.get("input_priority_policy") and packet.get("input_priority_policy") != state["input_priority_policy"]:
        errors.append("执行包input_priority_policy与本话冻结合同不一致")
    if state.get('execution_contract') and packet.get('execution_contract')!=state['execution_contract']:errors.append('执行包缺少本次完整执行合同；不能使用本话临时检查器降级')
    from continuity_context import binding_errors as prior_binding_errors
    errors.extend(prior_binding_errors(state,root,packet,manifest_path.parent))
    subset_path = checked_file(root, record.get("shot_subset"))
    subset = read(subset_path)
    if state.get("input_priority_policy") and subset.get("input_priority_policy") != state["input_priority_policy"]:
        errors.append("镜头选集input_priority_policy与本话冻结合同不一致")
    if state.get('execution_contract')=='comic_execution_v2':
        errors.extend(prior_binding_errors(state,root,subset,subset_path.parent))
        a=packet.get('continuity_context');b=subset.get('continuity_context')
        if bool(a)!=bool(b) or a and read(checked_file(manifest_path.parent,a))!=read(checked_file(subset_path.parent,b)):errors.append('镜头选集与执行包须携带相同真实前格上下文')
    if packet.get("book_id") != book or packet.get("episode_id") != episode:
        errors.append("执行包本书/本话不一致")
    if subset.get("panels") != [shot]:
        errors.append("单格镜头快照不是获批全话记录的准确选集")
    if packet.get("execution_mode") != state.get("execution_mode", MODE) or packet.get("style_policy") != STYLE_POLICY or packet.get("workflow_policy") != POLICY or len(packet.get("panels", [])) != 1:
        return errors + ["每次请求须为当前模式的单格执行包，保留阶段/画风合同"]
    panel = packet["panels"][0]
    if panel.get('repair_method') == 'regenerate' and state.get('production_policy') != 'first_batch_production_v1':
        errors.append('旧运行不支持新重生决定；不允许补字段绕过')
    from visual_evidence import binding_errors as visual_binding, packet_errors as visual_packet_errors
    errors.extend(visual_binding(state, packet))
    errors.extend(visual_packet_errors(state, shot, panel, basis))
    from visual_evidence import repair_binding_errors
    errors.extend(repair_binding_errors(panel, record))
    if state.get('execution_mode') == 'episode_async_v1':
        from image_risk_guards import packet_errors as risk_packet_errors
        errors.extend(risk_packet_errors(shot,panel))
    from repair_input_guard import repair_errors as repair_input_errors
    errors.extend(repair_input_errors(panel, require_focus=state.get('execution_mode') == 'episode_async_v1'))
    if state.get('execution_contract'):
        source=read(checked_file(root,state['source_snapshot']))
        original=next(p['source_panel_id'] for p in source['id_mapping']['pairs'] if p['panel_id']==pid)
        if record.get('source_panel_id')!=original or panel.get('source_panel_id')!=original:errors.append('源编号映射未原样传入进度/执行包')
    if state.get("optimization_policy") in {"scoped_half_review_v1", "scoped_episode_review_v1"} and packet.get("optimization_policy") != state["optimization_policy"]:
        errors.append("优化执行包缺少相同策略，不能退回旧输入合同")
    errors.extend(memory_binding_errors(state, packet=packet))
    tags=[];generation_tags=[]
    if state.get('execution_contract')=='comic_execution_v2':
        from continuity_context import rule_tags
        shot_path=checked_file(root,state['shot_manifest'])
        tags=rule_tags(read(shot_path),shot_path.parent,shot)
        generation_tags=rule_tags(packet,manifest_path.parent,panel)
        if tags!=generation_tags:errors.append('镜头与执行包的前格规则触发不一致')
    errors.extend(memory_errors(state.get("memory_source"), "shot_design", shot, root,context_tags=tags,scope=state))
    errors.extend(memory_errors(state.get("memory_source"), "generation", panel, manifest_path.parent,context_tags=generation_tags,scope=state))
    if state.get("memory_source") and record.get("status") == "REPAIR_AUTHORIZED" and panel.get("operation") != "repair":
        errors.append("MEMORY_HOLD:返修执行包必须声明operation=repair")
    if panel.get("panel_id") != pid or any(panel.get(k) != shot.get(k) for k in SHOT_FIELDS):
        errors.append("执行格号/画面/依赖与批准镜头不一致")
    from input_semantics import panel_errors as final_input_errors
    errors.extend(final_input_errors(state, root, shot, packet, manifest_path.parent))
    effective_basis = dependency_basis(root, manifest_path, packet, shot, basis, records,state)
    errors.extend(basis_errors(panel, effective_basis))
    if dispatch_audit and (candidate or state.get('parallel_context') or packet.get('dispatch_receipt')):
        errors.append('接包输入审计不能带candidate或线上调度上下文/回执')
    if not candidate and not dispatch_audit:
        errors.extend(dispatch_errors(state, root, packet, pid))
    from validate_preproduction import Gate
    errors.extend(Gate(root, expected_panel_ids=[pid]).run(subset_path, manifest_path)["errors"])
    errors.extend(validate_style(panel, manifest_path.parent))
    errors.extend(output_spec_errors(panel))
    if panel.get("generation_execution", {}).get("status") != "NOT_RUN":
        errors.append("仅NOT_RUN的新尝试允许调用；已有结果先验收或另建返修版本")
    return errors


def cross_episode_errors(context, *, first_batch=False):
    """Bind the coordinator's visual comparison to all current episode outputs."""
    control_path = resolve_path(Path(context['control_file']))
    control = read(control_path)
    jobs = control["jobs"]
    if len(jobs) <= 1:
        return []
    ref = control.get("cross_episode_review")
    if not ref:
        return ["多话交付缺少跨话实际图片复核报告"]
    report = read(checked_file(control_path.parent, ref))
    errors = []
    if report.get("policy") != "cross_episode_review_v1" or report.get("book_id") != control["book_id"] or report.get("epoch") != control["epoch"] or report.get("shared_files") != control["shared_files"]:
        errors.append("跨话复核的本书/epoch/共用基准版本不一致")
    if report.get("status") not in ({"PASS", "FAIL"} if first_batch else {"PASS"}) or not isinstance(report.get("reviewer"), str) or not report["reviewer"].strip() or not isinstance(report.get("evidence"), str) or not report["evidence"].strip():
        errors.append("跨话比较尚未实际看图通过并记录审查者与依据")
    expected = []
    for job in jobs:
        episode_root = resolve_path(Path(job['root']))
        name = Path(job.get("state_file", "00_输入审计/生产流程.json"))
        state_path = resolve_path(episode_root / name)
        if name.is_absolute() or not state_path.is_relative_to(episode_root):
            raise ValueError("跨话状态路径越界")
        other = read(state_path)
        if other.get("book_id") != control["book_id"] or other.get("episode_id") != job["episode_id"] or other.get("execution_mode") not in {MODE, "half_episode_async_v1", "episode_async_v1"} or other.get("cancelled") or other.get("holds"):
            errors.append(f"{job['episode_id']}:本书/话/模式无效或已暂停取消")
        scoped = other.get("optimization_policy") in {"scoped_half_review_v1", "scoped_episode_review_v1"}
        from scoped_inputs import full_preparation
        whole = scoped and full_preparation(other)
        for key in (("source_script", "source_snapshot") if scoped and not whole else ("source_script", "source_snapshot", "visual_basis", "shot_manifest")):
            if other.get(key) != job["frozen_inputs"].get(key):
                errors.append(f"{job['episode_id']}:{key}已换版")
            checked_file(episode_root, other.get(key))
        if scoped and not first_batch:
            if not whole and job.get("frozen_halves") != other.get("half_inputs"):
                errors.append(f"{job['episode_id']}:最终半话冻结输入版本不一致")
            if whole and job.get('frozen_halves'):
                errors.append(f"{job['episode_id']}:全话准备不使用半话冻结资产/镜头")
            if other.get('execution_mode') == 'episode_async_v1':
                from scoped_episode_workflow import evaluate_episode as evaluate_scoped
            else:
                raise ValueError('HISTORICAL_REPORT_REQUIRES_IMPORT: no legacy scheduler')
            verified = evaluate_scoped(other,episode_root,'scope_complete')
            if verified.get('next_action')!='READY_FOR_CROSS_REVIEW': errors.extend([f"{job['episode_id']}:半话放行不完整",*verified.get('errors',[])])
        source = read(checked_file(episode_root, other["source_snapshot"]))
        records = other.get("panels", [])
        if first_batch:
            from production_decisions import selected, enabled
            if not enabled(other):
                errors.append(f"{job['episode_id']}:未声明第一批生产合同")
            try:
                records = [selected(episode_root, r)[0] for r in records]
            except (ValueError, KeyError, TypeError, OSError) as exc:
                errors.append(str(exc)); continue
        if not records or [r.get("panel_id") for r in records] != source.get("panel_ids") or any(r.get("status") not in (DONE | {"VISUAL_FAIL"} if first_batch else DONE) for r in records):
            errors.append(f"{job['episode_id']}:尚非完整已检查源格清单")
        for r in records:
            checked_file(episode_root, r.get("output"))
            checked_file(episode_root, r.get("qa_report"))
            if first_batch:
                from production_evidence import attempt_errors
                errors.extend(attempt_errors(other, episode_root, r))
            else:
                errors.extend(f"{job['episode_id']}:{r['panel_id']}:{e}" for e in qa_errors(episode_root, r))
        expected.append({"job_id": job["job_id"], "episode_id": job["episode_id"],
                         **({"half_inputs": other["half_inputs"]} if scoped and not whole else {"visual_basis": other["visual_basis"], "shot_manifest": other["shot_manifest"]}),
                         "outputs": [r["output"] for r in records], "qa_reports": [r["qa_report"] for r in records]})
    if report.get("episodes") != expected:
        errors.append("跨话复核未准确覆盖全部话及当前源序图片/QA版本")
    return errors

def batch_review_errors(state, root, batch, records, previous):
    ref = state.get("batch_reviews", {}).get(batch["batch_id"])
    if not ref:
        return ["缺少本批逐图对照及连续性审查报告"]
    report = read(checked_file(root, ref))
    expected = {"policy": "batch_review_v1", "book_id": state["book_id"],
                "episode_id": state["episode_id"], "batch_id": batch["batch_id"],
                "panel_ids": batch["panel_ids"], "visual_basis": state["visual_basis"],
                "shot_manifest": state["shot_manifest"],
                "outputs": [r["output"] for r in records],
                "previous_outputs": [r["output"] for r in previous]}
    errors = [f"批次审查版本或范围不一致:{k}" for k, v in expected.items() if report.get(k) != v]
    if report.get("status") != "PASS" or not isinstance(report.get("reviewer"), str) or not report["reviewer"].strip() or not isinstance(report.get("evidence"), str) or not report["evidence"].strip():
        errors.append("批次连续性尚未实际检查通过并记录审查者/观察依据")
    for item in [report.get("visual_basis"), report.get("shot_manifest"), *report.get("outputs", []), *report.get("previous_outputs", [])]:
        checked_file(root, item)
    return errors
