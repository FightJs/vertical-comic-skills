#!/usr/bin/env python3
"""Stage/condition routing for portable comic rules; no image or approval generation."""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from codex_reference_contract import checked_file

POLICY = "triggered_rules_v1"
LOADING_POLICY = "stage_baseline_loading_v1"
LOAD_POLICIES = {"stage_baseline", "on_match"}
STAGES = {"input_audit", "visual_assets", "shot_design", "generation", "image_review"}
_ROUTING = ContextVar('comic_rule_routing', default=None)


@contextmanager
def routing_session(enabled=True):
    """Reuse parsing/matching within one gate; bytes and body hashes stay checked."""
    if not enabled or _ROUTING.get() is not None:
        yield _ROUTING.get();return
    memo={'indexes':{},'matches':{},'index_hits':0,'index_parses':0,'selection_hits':0,'selections':0}
    token=_ROUTING.set(memo)
    try:yield memo
    finally:_ROUTING.reset(token)


def routing_statistics():
    memo=_ROUTING.get()
    return {k:memo[k] for k in ('index_hits','index_parses','selection_hits','selections')} if memo else {}


def effective_tags(panel, context_tags=()):
    tags=panel.get('memory_tags')
    if not strings(tags):raise ValueError('启用记忆后须填写memory_tags（无适用标签时为空数组）')
    result=set(tags)|set(context_tags)
    scene=panel.get('scene_binding');scene=scene if isinstance(scene,dict) else {}
    if (panel.get('characters_visible') or scene.get('background_visible') is True
            or panel.get('background_anchors_visible') or panel.get('props_visible') or panel.get('key_props_visible')):
        result.add('visual_subjects_present')
    if panel.get('operation')=='repair':result.add('image_repair')
    return result


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def signature(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def strings(value):
    return isinstance(value, list) and all(isinstance(s, str) and s.strip() for s in value)


def source_index(source):
    if not isinstance(source, dict) or source.get("policy") != POLICY:
        raise ValueError("记忆来源须声明triggered_rules_v1")
    loading = source.get("loading_policy")
    if "loading_policy" in source and loading != LOADING_POLICY:
        raise ValueError("未知记忆读取合同；旧触发模式应不含loading_policy")
    root = Path(source.get("root", ""))
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("规则记忆root须为存在的绝对目录")
    root = root.resolve()
    if source.get('runtime_snapshot'):
        from runtime_snapshot import verify
        frozen = verify(source['runtime_snapshot'])
        if source != frozen['memory_source']:
            raise ValueError('SNAPSHOT_HOLD: 不得把冻结规则来源换成安装库或新索引')
    name = Path(source.get("index", "记忆索引.json"))
    index_path = (root / name).resolve()
    if name.is_absolute() or not index_path.is_relative_to(root):
        raise ValueError("记忆索引不得越出规则库")
    raw=index_path.read_bytes()
    if source.get("index_sha256") is not None and source["index_sha256"]!=hashlib.sha256(raw).hexdigest():
        raise ValueError("规则索引内容不等于批准的可移植版本")
    cache_key=(str(index_path),hashlib.sha256(raw).hexdigest(),loading)
    memo=_ROUTING.get()
    if memo is not None and cache_key in memo['indexes']:
        memo['index_hits']+=1
        return root,copy.deepcopy(memo['indexes'][cache_key])
    data=json.loads(raw.decode('utf-8-sig'))
    if data.get("policy") != POLICY or not isinstance(data.get("rules"), list):
        raise ValueError("记忆索引版本/规则清单无效")
    if ("loading_policy" in data and data["loading_policy"] != LOADING_POLICY
            or data.get("loading_policy") != loading):
        raise ValueError("记忆来源与索引读取合同不一致；须显式绑定，不能静默升级或降级")
    ids = set()
    for rule in data["rules"]:
        rid = rule.get("id")
        if not isinstance(rid, str) or not rid or rid in ids:
            raise ValueError("记忆ID为空或重复")
        ids.add(rid)
        if loading == LOADING_POLICY:
            if not isinstance(rule.get("load_policy"), str) or rule["load_policy"] not in LOAD_POLICIES:
                raise ValueError(f"{rid}:load_policy须为stage_baseline或on_match")
        elif "load_policy" in rule:
            raise ValueError(f"{rid}:旧触发合同不接受load_policy；须显式升级读取合同")
        if rule.get("scope") != "cross_work" or any(k in rule for k in ("book_id", "book_ids", "episode_id", "episode_ids", "panel_ids", "character_ids")):
            raise ValueError(f"{rid}:规则库只收跨话跨作品规则，不收特定书话人物信息")
        admission = rule.get("admission", {})
        if admission.get("portable") is not True or admission.get("contains_story_facts") is not False or not admission.get("rationale"):
            raise ValueError(f"{rid}:缺少通用性入库审查")
        if rule.get("status") not in {"active", "candidate", "disabled"}:
            raise ValueError(f"{rid}:规则状态无效")
        stages = rule.get("stages")
        if not strings(stages) or not stages or not set(stages) <= STAGES or rule.get("primary_stage") not in stages:
            raise ValueError(f"{rid}:责任/触发阶段无效")
        trigger = rule.get("trigger", {})
        if not strings(trigger.get("any_tags")) or not strings(trigger.get("any_visual_terms")) or not (trigger["any_tags"] or trigger["any_visual_terms"]):
            raise ValueError(f"{rid}:缺少明确触发条件")
        if not isinstance(rule.get("version"), str) or not rule["version"]:
            raise ValueError(f"{rid}:缺少版本")
        for stage in stages:
            req = rule.get("requirements", {}).get(stage)
            if not isinstance(req, dict) or not strings(req.get("checks")) or not strings(req.get("artifacts")) or type(req.get("prompt_constraints")) is not bool:
                raise ValueError(f"{rid}:{stage}:执行要求无效")
        ref = rule.get("file", {})
        if not isinstance(ref.get("path"), str) or not re.fullmatch(r"[0-9a-f]{64}", str(ref.get("sha256", ""))):
            raise ValueError(f"{rid}:正文引用无效")
        path = Path(ref["path"])
        if path.is_absolute() or not (root / path).resolve().is_relative_to(root):
            raise ValueError(f"{rid}:正文越出规则库")
    if memo is not None:
        memo['indexes'][cache_key]=copy.deepcopy(data);memo['index_parses']+=1
    return root, data


def select(source, stage, panel, context_tags=()):
    if source is None:
        return []
    if stage not in STAGES:
        raise ValueError("未知记忆触发阶段")
    root, index = source_index(source)
    tags=effective_tags(panel,context_tags)
    # Dialogue/inner voice never enter lexical visual matching.
    visual = {"event": panel.get("locked_script", {}).get("event_text", ""),
              "framing": panel.get("framing", {}), "characters": panel.get("characters_visible", []),
              "anchors": panel.get("background_anchors_visible", []), "occlusion": panel.get("occlusion_relations", "")}
    text = json.dumps(visual, ensure_ascii=False).casefold()
    memo=_ROUTING.get()
    cache_key=(str(root),signature(index),stage,signature({'tags':sorted(tags),'visual':visual}))
    if memo is not None and cache_key in memo['matches']:
        memo['selection_hits']+=1
        return copy.deepcopy(memo['matches'][cache_key])
    matched = []
    for rule in index["rules"]:
        if rule["status"] != "active" or stage not in rule["stages"]:
            continue
        tagged = sorted(tags.intersection(rule["trigger"]["any_tags"]))
        terms = [t for t in rule["trigger"]["any_visual_terms"] if t.casefold() in text]
        if tagged or terms:
            matched.append({"rule": rule, "rule_signature": signature(rule),
                            "matched_tags": tagged, "matched_terms": terms})
    if memo is not None:
        memo['matches'][cache_key]=copy.deepcopy(matched);memo['selections']+=1
    return matched


def loading_selection(source, stage, panel=None, context_tags=()):
    """Read stage baselines plus actual hits; execution matching stays in select()."""
    if stage not in STAGES:
        raise ValueError("未知记忆读取阶段")
    if source is None:
        return []
    _, index = source_index(source)
    selected = {}
    if source.get("loading_policy") == LOADING_POLICY:
        for rule in index["rules"]:
            if rule["status"] == "active" and stage in rule["stages"] and rule["load_policy"] == "stage_baseline":
                selected[rule["id"]] = {"rule": rule, "rule_signature": signature(rule),
                    "matched_tags": [], "matched_terms": [], "read_reasons": ["stage_baseline"]}
    if panel is not None:
        for match in select(source, stage, panel, context_tags):
            rid = match["rule"]["id"]
            reasons = selected[rid]["read_reasons"] if rid in selected else []
            selected[rid] = {**match, "read_reasons": [*reasons, "matched_condition"]}
    return list(selected.values())


def trigger_review(source, stage, panel, context_tags=()):
    """Unreviewed coverage for an existing semantic audit; never reads all bodies."""
    matches=select(source,stage,panel,context_tags)
    result={'matched_rules':[{'memory_id':m['rule']['id'],'rule_signature':m['rule_signature']} for m in matches]}
    if source is not None:
        _,index=source_index(source)
        human=any(r['status']=='active' and stage in r['stages'] and 'human_figure_visible' in r['trigger']['any_tags'] for r in index['rules'])
        if human and panel.get('characters_visible'):
            result['human_figure_visible']={'decision':'UNREVIEWED','evidence':''}
    return result


def trigger_review_errors(source, stage, panel, review, context_tags=()):
    if source is None:return []
    if not isinstance(review,dict):return ['MEMORY_HOLD:规则覆盖记录须为对象']
    expected=trigger_review(source,stage,panel,context_tags);errors=[]
    if review.get('matched_rules')!=expected['matched_rules']:
        errors.append('MEMORY_HOLD:语义审计缺少准确命中规则/当前版本清单')
    if 'human_figure_visible' in expected:
        decision=review.get('human_figure_visible',{})
        if not isinstance(decision,dict):decision={}
        tagged='human_figure_visible' in effective_tags(panel,context_tags)
        if decision.get('decision') not in {'APPLIES','NOT_APPLICABLE'} or not isinstance(decision.get('evidence'),str) or not decision['evidence'].strip():
            errors.append('MEMORY_HOLD:可见角色须明确人体规则适用性及可见范围依据')
        elif (decision['decision']=='APPLIES')!=tagged:
            errors.append('MEMORY_HOLD:人体适用性与冻结语义标签不一致，不能靠漏标签跳过')
    return errors


def inspection_plan(panel, item, source_manifest_sha256):
    """Group original QA targets for one observation; never merges their verdicts."""
    names={'action_contact':'人体动作与接触','space_props':'场景、道具与遮挡',
           'identity_costume':'身份与衣装','style':'批准画风','camera_crop':'镜头、裁切与规格',
           'adjacent':'真实相邻连续性','specific':'专项规则'}
    groups={k:[] for k in names}
    dimensions={'identity':'identity_costume','costume':'identity_costume','action_interaction':'action_contact',
                'background_space':'space_props','framing':'camera_crop'}
    for key,group in dimensions.items():
        if key in item.get('dimension_review',{}):groups[group].append({'record':'dimension_review','check':key})
    if 'style_review' in item:groups['style'].append({'record':'style_review'})
    for field,group in (('no_extra_offscreen_characters','identity_costume'),('background_view_match','space_props'),
                        ('camera_match','camera_crop'),('shot_scale_match','camera_crop'),('body_crop_match','camera_crop'),
                        ('required_visible_information_preserved','camera_crop')):
        if field in item:groups[group].append({'record':field})
    if panel.get('composition_reference',{}).get('mode') in {'CREATE','REUSE'}:
        groups['camera_crop'].append({'record':'composition_match'})
    rule_groups={'MEM-001':'action_contact','MEM-002':'action_contact','MEM-003':'space_props',
                 'MEM-004':'specific','MEM-005':'space_props','MEM-006':'action_contact',
                 'MEM-007':'adjacent','MEM-008':'space_props','MEM-009':'space_props','MEM-010':'camera_crop'}
    # These keys only order the display; they do not define or equate criteria.
    check_groups={'character_consistency':'identity_costume','camera_background_validity':'camera_crop',
                  'adjacent_state_continuity':'adjacent','camera_visibility':'camera_crop'}
    for app in item.get('memory_review',[]):
        for field in ('checks','alternative_checks'):
            for key in app.get(field,{}):
                group=check_groups.get(key,rule_groups.get(app['memory_id'],'specific'))
                groups[group].append({'record':'memory_review','memory_id':app['memory_id'],
                    'field':field,'check':key,'rule_signature':app['rule_signature']})
    visual_groups={'space':'space_props','presence':'adjacent','contact':'action_contact',
                   'hand':'action_contact','accessory':'identity_costume','clarity':'specific'}
    for check in panel.get('visual_evidence',{}).get('checks',[]):
        groups[visual_groups[check['kind']]].append({'record':'visual_evidence_review',
            'check':check['id'],'expected':check['expected'],
            'original_pixels_required':check['kind'] in {'hand','accessory','contact','clarity'}})
    return {'policy':'single_observation_v1','status':'UNREVIEWED','panel_id':panel['panel_id'],
            'image_sha256':item.get('image_sha256'),'source_manifest_sha256':source_manifest_sha256,
            'viewing_sequence':['全图：逐人物数可见手/腕/袖口并追溯归属，核对承托、目光和在场实体',
                '原尺寸：再看指掌接触、遮挡边界、露出眼部、首饰和清晰度；缩略总览不能证明这些细节',
                '连续图：对照同场景前序及能证明床侧/路沿/站位的较早原图；不可见处不猜错，也不填已核实PASS'],
            'groups':[{'group':key,'title':names[key],'targets':targets} for key,targets in groups.items() if targets],
            'acceptance':'ORIGINAL_QA_FIELDS_ONLY'}


def load_selected(source, matches, cache, run_id, worker_id, reload=False):
    """Return bodies only once per actor/run/version. Cache never means visual PASS."""
    if any(not isinstance(v, str) or not v.strip() for v in (run_id, worker_id)):
        raise ValueError("读取缓存须有真实run_id和worker_id")
    root, index = source_index(source)
    current = {rule["id"]: rule for rule in index["rules"]}
    owner = {"root": str(root), "run_id": run_id, "worker_id": worker_id}
    if source.get("loading_policy"):
        owner.update(index=source.get("index", "记忆索引.json"), loading_policy=source["loading_policy"])
    cached = cache if isinstance(cache, dict) and cache.get("owner") == owner else {"owner": owner, "loaded": {}}
    cached.setdefault("loaded", {})
    if not isinstance(cached["loaded"], dict):
        raise ValueError("读取缓存loaded须为对象")
    result = []
    for match in matches:
        rule = match["rule"]
        if (rule != current.get(rule["id"]) or rule["status"] != "active"
                or match["rule_signature"] != signature(rule)):
            raise ValueError(f"{rule['id']}:读取选择已过期，须重新匹配当前索引")
        path = checked_file(root, rule["file"])
        token = match["rule_signature"]
        item = {"memory_id": rule["id"], "version": rule["version"], "rule_signature": token, "path": str(path)}
        if "read_reasons" in match:
            item["read_reasons"] = match["read_reasons"]
        if not reload and cached["loaded"].get(rule["id"]) == token:
            item["status"] = "CACHED_IN_THIS_RUN"
        else:
            item.update(status="READ_REQUIRED", body=path.read_text(encoding="utf-8"))
            cached["loaded"][rule["id"]] = token
        result.append(item)
    return result, cached


def review_template(source, panel, image_sha256, context_tags=(),artifact_root=None,scope=None):
    result=[{"memory_id": m["rule"]["id"], "rule_version": m["rule"]["version"],
             "rule_sha256": m["rule"]["file"]["sha256"], "rule_signature": m["rule_signature"],
             "decision": "UNREVIEWED", "reviewer": "", "evidence": "", "image_sha256": image_sha256,
             "checks": {k: {"status": "UNREVIEWED", "evidence": ""} for k in m["rule"]["requirements"]["image_review"]["checks"]},
             "artifacts": [], "prompt_constraints": []}
            for m in select(source, "image_review", panel,context_tags)]
    if panel.get('rule_exceptions'):
        from rule_exception import applicable
        if artifact_root is None:raise ValueError('规则例外模板须有真实包根/范围')
        for item,match in zip(result,select(source,'image_review',panel,context_tags)):
            exception=applicable(panel,artifact_root,match['rule'],'image_review',scope)
            if exception:
                for key in exception[1]:item['checks'][key].update(expected_status='USER_EXCEPTION',exception=exception[0])
                item['alternative_checks']={k:{'status':'UNREVIEWED','evidence':''} for k in exception[2]}
    return result


def application_errors(source, stage, panel, artifact_root, applications=None, image_sha256=None,context_tags=(),scope=None):
    if source is None:
        return []
    try:
        root, _ = source_index(source)
        matches = select(source, stage, panel,context_tags)
        apps = applications if applications is not None else panel.get("memory_applications", {}).get(stage, [])
        if not isinstance(apps, list):
            return ["记忆执行记录须为数组"]
        errors = []
        for match in matches:
            rule, token = match["rule"], match["rule_signature"]
            rid = rule["id"]
            checked_file(root, rule["file"])
            found = [a for a in apps if a.get("memory_id") == rid]
            if len(found) != 1:
                errors.append(f"MEMORY_HOLD:{rid}:缺少或重复执行记录")
                continue
            app = found[0]
            if app.get("rule_signature") != token or app.get("rule_sha256") != rule["file"]["sha256"] or app.get("rule_version") != rule["version"]:
                errors.append(f"MEMORY_HOLD:{rid}:规则版本变更，须重读并复核受影响项")
            if not isinstance(app.get("evidence"), str) or not app["evidence"].strip() or not isinstance(app.get("reviewer"), str) or not app["reviewer"].strip():
                errors.append(f"MEMORY_HOLD:{rid}:缺少实际执行者和可观察依据")
            if stage == "image_review" and app.get("image_sha256") != image_sha256:
                errors.append(f"MEMORY_HOLD:{rid}:记忆验收不是当前返回图")
            if app.get("decision") == "NOT_APPLICABLE":
                if match["matched_tags"] or not isinstance(app.get("reason"), str) or not app["reason"].strip():
                    errors.append(f"MEMORY_HOLD:{rid}:只有关键词误召回可说明原因排除；语义标签命中不能免除")
                continue
            if app.get("decision") != "APPLIED":
                errors.append(f"MEMORY_HOLD:{rid}:尚未执行并检查")
                continue
            req = rule["requirements"][stage]
            from rule_exception import applicable
            exception=applicable(panel,artifact_root,rule,stage,scope)
            waived=set(exception[1]) if exception else set()
            for key in req["checks"]:
                check = app.get("checks", {}).get(key, {})
                if key in waived:
                    if check.get('status')!='USER_EXCEPTION' or check.get('exception')!=exception[0] or not check.get('evidence'):errors.append(f'MEMORY_HOLD:{rid}:{key}未记录原范围例外')
                    continue
                if check.get("status") != "PASS" or not isinstance(check.get("evidence"), str) or not check["evidence"].strip():
                    errors.append(f"MEMORY_HOLD:{rid}:{key}未实际核对")
            if exception:
                for key in exception[2]:
                    check=app.get('alternative_checks',{}).get(key,{})
                    if check.get('status')!='PASS' or not check.get('evidence'):errors.append(f'MEMORY_HOLD:{rid}:{key}替代判据未实际核对')
            for kind in req["artifacts"]:
                artifacts = [a for a in app.get("artifacts", []) if a.get("kind") == kind]
                if not artifacts:
                    errors.append(f"MEMORY_HOLD:{rid}:缺少{kind}")
                for artifact in artifacts:
                    file = checked_file(Path(artifact_root), artifact.get("file"))
                    if artifact.get("reviewed") is not True or not artifact.get("evidence"):
                        errors.append(f"MEMORY_HOLD:{rid}:辅助图未目视核对")
                    if kind == "spatial_diagram":
                        if file.suffix.lower() == ".svg":
                            if ET.parse(file).getroot().tag.split("}")[-1] != "svg":
                                errors.append(f"MEMORY_HOLD:{rid}:不是SVG站位图")
                        else:
                            from PIL import Image
                            with Image.open(file) as im:
                                im.verify()
            if req["prompt_constraints"]:
                lines = app.get("prompt_constraints")
                if not strings(lines) or not lines or any(line not in panel.get("prompt", "") for line in lines):
                    errors.append(f"MEMORY_HOLD:{rid}:空间/保留约束未进入实际提示词")
        return errors
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ET.ParseError) as exc:
        return [f"MEMORY_HOLD:{exc}"]


def same_source_identity(a,b):
    if a==b:return True
    if not isinstance(a,dict) or not isinstance(b,dict):return False
    token=a.get('index_sha256')
    if not isinstance(token,str) or not re.fullmatch(r'[0-9a-f]{64}',token) or token!=b.get('index_sha256'):return False
    return {k:v for k,v in a.items() if k not in {'root','runtime_snapshot'}}=={k:v for k,v in b.items() if k not in {'root','runtime_snapshot'}}

def binding_errors(state, shots=None, packet=None):
    source = state.get("memory_source")
    errors = []
    for name, obj in (("镜头", shots), ("执行包", packet)):
        if obj is not None and not same_source_identity(obj.get("memory_source"),source):
            errors.append(f"MEMORY_HOLD:{name}与本话的记忆来源不一致，不能删字段跳过")
    if source is not None:
        try:
            source_index(source)
        except (OSError, ValueError, TypeError, KeyError, AttributeError, ET.ParseError) as exc:
            errors.append(f"MEMORY_HOLD:{exc}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="通用规则库绝对路径")
    parser.add_argument("--index", default="记忆索引.json")
    parser.add_argument("--loading-policy", choices=(LOADING_POLICY,), help="新库须显式绑定此读取合同；旧库省略")
    parser.add_argument("--stage", choices=sorted(STAGES))
    parser.add_argument("--panel", help="单格JSON，直接包含locked_script/memory_tags等字段")
    parser.add_argument('--manifest',help='冻结镜头/执行包；新合同用实际前格派生规则标签')
    parser.add_argument('--panel-id',help='manifest中的当前源执行格号')
    parser.add_argument("--mode", choices=("select", "load", "load-stage", "check", "validate-library"), default="select")
    parser.add_argument("--artifact-root", help="check时辅助图引用的根目录")
    parser.add_argument("--cache", help="load缓存路径，按agent/run隔离；不是规则库文件")
    parser.add_argument("--run-id")
    parser.add_argument("--worker-id")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    source = {"policy": POLICY, "root": str(Path(args.root).resolve()), "index": args.index}
    if args.loading_policy:
        source["loading_policy"] = args.loading_policy
    try:
        root, index = source_index(source)
        if args.mode == "validate-library":
            indexed = set()
            for rule in index["rules"]:
                file = checked_file(root, rule["file"])
                indexed.add(file)
                body = file.read_text(encoding="utf-8")
                if re.search(r"\b[EP]\d{3}\b|第[0-9一二三四五六七八九十]+话|《[^》]+》", body):
                    raise ValueError(f"{rule['id']}:发现疑似作品/话格特定信息，须人工通用性审查")
            unindexed = [p.relative_to(root).as_posix() for p in (root / "规则").rglob("*.md") if p.resolve() not in indexed]
            if unindexed:
                raise ValueError("规则目录存在未登记正文:" + ",".join(unindexed))
            result = {"status": "PASS", "rules": len(index["rules"]), "loading_policy": index.get("loading_policy"), "semantic_portability": "REQUIRES_HUMAN_REVIEW"}
        else:
            if args.panel and args.manifest:
                raise ValueError("panel与manifest只能选择一个")
            stage_only = args.mode == "load-stage"
            if stage_only and (args.panel or args.manifest or args.panel_id):
                raise ValueError("load-stage只读阶段基准，不接收单格输入")
            if not args.stage:
                raise ValueError("读取/检查须指定stage")
            if args.panel_id and not args.manifest:
                raise ValueError("panel-id须配套manifest")
            if not stage_only and not (args.panel or args.manifest and args.panel_id):
                raise ValueError("select/load/check须指定stage和panel")
            manifest=read(args.manifest) if args.manifest else None
            if manifest is not None and manifest.get("memory_source") != source:
                raise ValueError("记忆来源/读取合同与冻结manifest不一致")
            panel=next(p for p in manifest['panels'] if p['panel_id']==args.panel_id) if manifest is not None else read(args.panel) if args.panel else None
            context_tags=[]
            if manifest is not None and manifest.get('execution_contract')=='comic_execution_v2':
                from continuity_context import rule_tags
                context_tags=rule_tags(manifest,Path(args.manifest).resolve().parent,panel)
            matches = select(source, args.stage, panel,context_tags) if panel is not None else []
            if args.mode in {"load", "load-stage"}:
                if not args.cache or not args.run_id or not args.worker_id:
                    raise ValueError("load须指定cache/run-id/worker-id")
                cache_file = Path(args.cache).resolve()
                if any(cache_file == Path(p).resolve() for p in (args.manifest, args.panel) if p):
                    raise ValueError("缓存不得覆盖单格输入")
                if cache_file.is_relative_to(root):
                    raise ValueError("运行缓存不得写入通用规则库")
                cache = read(cache_file) if cache_file.exists() else {}
                to_read = loading_selection(source, args.stage, panel, context_tags)
                bodies, cache = load_selected(source, to_read, cache, args.run_id, args.worker_id, args.reload)
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                temp = cache_file.with_name(cache_file.name + ".tmp")
                temp.write_text(json.dumps(cache, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline='\n')
                temp.replace(cache_file)
                result = {"status": "LOADED_NOT_APPROVED", "stage": args.stage, "loading_policy": source.get("loading_policy"),
                          "matched_for_execution": [{"memory_id": m["rule"]["id"], "rule_signature": m["rule_signature"]} for m in matches],
                          "memories": bodies}
            elif args.mode == "check":
                if not args.artifact_root:
                    raise ValueError("check须指定artifact-root")
                errors = application_errors(source, args.stage, panel, Path(args.artifact_root), image_sha256=panel.get("image_sha256"),context_tags=context_tags,scope=manifest)
                result = {"status": "HOLD" if errors else "PASS", "errors": errors}
            else:
                result = {"status": "SELECTED_NOT_READ", "matches": matches}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result["status"] == "HOLD" else 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError, StopIteration, ET.ParseError) as exc:
        print(json.dumps({"status": "HOLD", "errors": [str(exc)]}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
