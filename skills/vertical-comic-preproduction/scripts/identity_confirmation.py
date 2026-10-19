#!/usr/bin/env python3
"""Check scoped identity/state evidence before visual production; no user approval."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

POLICY = "identity_confirmation_v1"
HOLD_CODES = {"IDENTITY_HOLD", "APPEARANCE_HOLD", "SCENE_IDENTITY_HOLD"}


def text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def evidence_valid(items: Any, root: Path) -> bool:
    if not isinstance(items, list) or not items:
        return False
    for item in items:
        if not isinstance(item, dict) or not text(item.get("path")):
            return False
        rel = Path(item["path"])
        path = (root / rel).resolve()
        if rel.is_absolute() or not path.is_relative_to(root.resolve()) or not path.is_file():
            return False
        if hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
            return False
    return True


def confirmed(record: Any, root: Path, book: str, episode: str, pid: str,
              subject: str, facets: set[str], state: str | None = None,
              source_label: str | None = None) -> bool:
    if not isinstance(record, dict):
        return False
    approval = record.get("confirmation")
    if not isinstance(approval, dict) or approval.get("status") != "CONFIRMED":
        return False
    scope = approval.get("scope")
    if not isinstance(scope, dict) or scope.get("book_id") != book or scope.get("subject_id") != subject:
        return False
    for key, value in (("episode_ids", episode), ("panel_ids", pid)):
        values = scope.get(key)
        if not isinstance(values, list) or not values or not all(text(x) for x in values):
            return False
        aliases = {value, episode + '-' + value} if key == 'panel_ids' and value.startswith('P') else {value}
        if not aliases.intersection(values) and "*" not in values:
            return False
    if state is not None and scope.get("state_id") != state:
        return False
    if source_label is not None and scope.get("source_label") != source_label:
        return False
    accepted = approval.get("facets")
    return (isinstance(accepted, list) and all(text(x) for x in accepted)
            and facets <= set(accepted) and evidence_valid(approval.get("evidence"), root))


def visible_ids(panel: dict[str, Any]) -> set[str] | None:
    people = panel.get("characters_visible")
    if not isinstance(people, list):
        return None
    result = set()
    for person in people:
        cid = person if isinstance(person, str) else (
            person.get("character_id") or person.get("subject_id") or person.get("id")
        ) if isinstance(person, dict) else None
        if not text(cid):
            return None
        result.add(cid)
    return result


def named_character(registry: dict[str, Any], cid: Any) -> bool:
    record = registry.get(cid) if text(cid) else None
    return (isinstance(record, dict) and text(record.get("canonical_name"))
            and record.get("name_kind") in ("full_name", "approved_role_name"))


def one_off(binding: dict[str, Any], book: str, episode: str, pid: str) -> bool:
    exemption = binding.get("asset_exemption")
    return (isinstance(exemption, dict) and exemption.get("status") == "ONE_OFF_ASSET_EXEMPT"
            and type(exemption.get("appearance_count")) is int and exemption["appearance_count"] == 1
            and exemption.get("book_id") == book and exemption.get("episode_id") == episode
            and exemption.get("panel_ids") == [pid] and text(exemption.get("basis")))


def execution_block(panel: dict[str, Any], registry: dict[str, Any]) -> str:
    """Compile checked bindings; never guess a name, outfit, or place."""
    lines, seen = ["身份与状态锁定"], set()
    for binding in panel.get("character_bindings", []):
        if not binding.get("on_screen") or binding["character_id"] in seen:
            continue
        cid = binding["character_id"]; seen.add(cid)
        state_id = binding["appearance_state_id"]
        character = registry["characters"][cid]
        state = registry["appearance_states"][state_id]
        refs = "单次出镜已确认外观" if binding.get("asset_exemption") else (
            f"身份参考{binding['identity_asset_alias']}；状态参考{binding['costume_asset_alias']}"
        )
        lines.append(f"{cid}（{character['canonical_name']}）；{state_id}：{state['description']}；{refs}。")
    binding = panel["scene_binding"]
    state = registry["scene_states"][binding["scene_state_id"]]
    ref = "单次出镜已确认场景" if binding.get("asset_exemption") else binding.get("asset_alias", "")
    lines.append(f"{binding['scene_id']} / {binding['scene_state_id']}：{state['canonical_name']}；{state['description']}；{ref}。")
    return "\n".join(lines)


def validate_manifest(data: Any, root: Path, *, prompt: bool = False,
                      reference_root: Path | None = None, require_execution: bool = True,
                      require_assets: bool = True) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict) or data.get("identity_policy") != POLICY:
        return ["IDENTITY_HOLD: 未执行identity_confirmation_v1；先迁移身份/状态审计，不能自动释放旧包"]
    book, episode = data.get("book_id"), data.get("episode_id")
    if not text(book) or not text(episode):
        return ["IDENTITY_HOLD: 缺少book_id或episode_id"]
    root_holds = data.get("hold_reasons") or []
    root_holds = [root_holds] if isinstance(root_holds, str) else root_holds
    if any(code in str(data.get("status", "")) or any(code in str(h) for h in root_holds) for code in HOLD_CODES):
        errors.append("IDENTITY_HOLD: 根记录仍有未解除的身份/外观/场景HOLD")
    registry = data.get("identity_registry")
    if not isinstance(registry, dict) or registry.get("book_id") != book:
        return ["IDENTITY_HOLD: 缺少同书identity_registry"]
    tables = {}
    for key in ("characters", "appearance_states", "scene_states", "assets"):
        value = registry.get(key)
        if not isinstance(value, dict):
            errors.append(f"IDENTITY_HOLD: identity_registry.{key}必须是对象")
            value = {}
        tables[key] = value
    issues = registry.get("issues")
    if not isinstance(issues, list):
        errors.append("IDENTITY_HOLD: 必须登记issues，不能用缺席表示无疑点")
    elif issues:
        for issue in issues:
            if not isinstance(issue, dict) or issue.get("status") != "RESOLVED_WITH_EVIDENCE" or not evidence_valid(issue.get("resolution_evidence"), root):
                errors.append("IDENTITY_HOLD: 当前范围仍有未解除的身份/外观/场景疑点；暂停询问")
    panels = data.get("panels") or data.get("shot_design")
    if not isinstance(panels, list) or not panels:
        return errors + ["IDENTITY_HOLD: 没有可审计格子"]
    for panel in panels:
        if not isinstance(panel, dict):
            errors.append("IDENTITY_HOLD: 格子不是对象"); continue
        pid = panel.get("panel_id", "?")
        before = len(errors)
        def fail(code: str, message: str) -> None:
            errors.append(f"{code}: {pid}: {message}")
        if not text(pid) or pid == "?":
            fail("IDENTITY_HOLD", "缺少明确panel_id，无法核对确认范围")
        holds = panel.get("hold_reasons") or []
        if isinstance(holds, str):
            holds = [holds]
        if (any(code in str(panel.get("status", "")) for code in HOLD_CODES)
                or any(any(code in str(h) for code in HOLD_CODES) or any(word in str(h) for word in ("身份不明", "称呼不明", "关系不明", "服装未确认", "样貌未确认", "场景归属不明")) for h in holds)):
            fail("IDENTITY_HOLD", "仍有未解除的hold_reasons")
        bindings = panel.get("character_bindings")
        labels = panel.get("script_character_labels")
        if not isinstance(bindings, list) or not isinstance(labels, list) or not all(text(x) for x in labels):
            fail("IDENTITY_HOLD", "须登记源称呼script_character_labels和character_bindings"); bindings = []; labels = []
        if any(not isinstance(b, dict) for b in bindings):
            fail("IDENTITY_HOLD", "character_bindings条目须为对象"); bindings = [b for b in bindings if isinstance(b, dict)]
        bound_labels = [b.get("source_label") for b in bindings if text(b.get("source_label"))]
        if set(labels or []) != set(bound_labels) or len(bound_labels) != len(set(bound_labels)):
            fail("IDENTITY_HOLD", "全部源称呼须有明确绑定；保留脚本原称呼")
        references = panel.get("reference_images")
        references = references if isinstance(references, list) else []
        planned = panel.get("planned_identity_assets")
        planned = planned if isinstance(planned, list) else []
        refs = {r.get("alias"): r for r in references if isinstance(r, dict) and text(r.get("alias"))} if prompt else {}
        def asset_check(alias: Any, subject: str, purpose: str, state_id: str | None, code: str) -> None:
            if not text(alias):
                fail(code, f"{subject}缺少{purpose}资产绑定"); return
            ref = refs.get(alias) if prompt else next((a for a in planned if isinstance(a, dict) and a.get("alias") == alias), None)
            if not isinstance(ref, dict):
                fail(code, f"{alias}未绑定实际参考图/计划资产"); return
            from reference_atlas import is_atlas, source_asset_id, verify_owner
            asset_id = source_asset_id(ref, subject, purpose)
            asset = tables["assets"].get(asset_id) if text(asset_id) else None
            if not isinstance(asset, dict):
                fail(code, f"{alias}资产不在本次审计索引"); return
            purposes = asset.get("purposes")
            derived = is_atlas(ref)
            if (asset.get("book_id") != book or asset.get("subject_id") != subject
                    or asset.get("status") != "APPROVED" or not isinstance(purposes, list) or purpose not in purposes
                    or not text(asset.get("version")) or not text(asset.get("sha256"))
                    or (state_id is not None and asset.get("state_id") != state_id)
                    or (not derived and (ref.get("sha256") != asset.get("sha256") or ref.get("version") != asset.get("version")))
                    or not confirmed(asset, root, book, episode, pid, subject, {"asset_binding"}, state_id)):
                fail(code, f"{alias}人物/场景归属、状态、版本、哈希或批准依据不匹配")
            if derived:
                for message in verify_owner(ref,asset,subject,purpose,reference_root or root):fail(code,message)
            if prompt:
                base = (reference_root or root).resolve()
                value = ref.get("path")
                file = (base / value).resolve() if text(value) else None
                if (file is None or Path(value).is_absolute() or not file.is_relative_to(base) or not file.is_file()
                        or hashlib.sha256(file.read_bytes()).hexdigest() != (ref.get('sha256') if derived else asset.get("sha256"))):
                    fail(code, f"{alias}实际参考文件与已确认资产不一致")
        on_screen, states_seen = set(), {}
        for binding in bindings:
            cid, label = binding.get("character_id"), binding.get("source_label")
            if not text(cid) or not text(label):
                fail("IDENTITY_HOLD", "角色ID或源称呼未知"); continue
            character = tables["characters"].get(cid)
            if not isinstance(character, dict) or not text(character.get("canonical_name")) or character.get("name_kind") not in {"full_name", "approved_role_name"}:
                fail("IDENTITY_HOLD", f"{label}尚未对应明确角色名称与唯一ID"); continue
            if binding.get("canonical_name") != character["canonical_name"] or not confirmed(character, root, book, episode, pid, cid, {"identity"}):
                fail("IDENTITY_HOLD", f"{label}角色名称或身份确认依据缺失/冲突")
            if label != character["canonical_name"]:
                aliases = character.get("aliases")
                alias = aliases.get(label) if isinstance(aliases, dict) else None
                if not isinstance(alias, dict) or not text(alias.get("relationship_context")) or not confirmed(alias, root, book, episode, pid, cid, {"alias", "relationship"}, source_label=label):
                    fail("IDENTITY_HOLD", f"{label}的称呼及人物关系未经当前范围确认")
                if isinstance(alias, dict):
                    targets = alias.get("target_character_ids")
                    kind = alias.get("relationship_kind")
                    if (kind not in ("kinship", "nickname", "title", "other_confirmed")
                            or not isinstance(targets, list) or any(not named_character(tables["characters"], t) for t in targets)
                            or kind == "kinship" and not targets):
                        fail("IDENTITY_HOLD", f"{label}称呼类型或关系对象未明确；亲属称呼必须有具体对象")
                    elif kind == "kinship":
                        relations = character.get("relationships")
                        related = {r.get("target_character_id") for r in relations if isinstance(r, dict) and text(r.get("target_character_id"))} if isinstance(relations, list) else set()
                        if not set(targets) <= related:
                            fail("IDENTITY_HOLD", f"{label}称呼对象与登记的人物关系不一致")
            relations = character.get("relationships")
            if not isinstance(relations, list) or any(not isinstance(r, dict) or not text(r.get("relation")) or not named_character(tables["characters"], r.get("target_character_id")) for r in relations):
                fail("IDENTITY_HOLD", f"{cid}人物关系未明确登记或关系对象未知")
            if not isinstance(binding.get("on_screen"), bool):
                fail("IDENTITY_HOLD", f"{cid}.on_screen须明确"); continue
            if not binding["on_screen"]:
                continue
            on_screen.add(cid)
            sid = binding.get("appearance_state_id"); state = tables["appearance_states"].get(sid) if text(sid) else None
            if cid in states_seen and states_seen[cid] != sid:
                fail("APPEARANCE_HOLD", f"{cid}同格外观状态互相冲突")
            states_seen[cid] = sid
            if not isinstance(state, dict) or state.get("character_id") != cid or not text(state.get("description")) or not confirmed(state, root, book, episode, pid, cid, {"appearance"}, sid):
                fail("APPEARANCE_HOLD", f"{cid}本话样貌/服装/身体状态未确认")
            if "asset_exemption" in binding and not one_off(binding, book, episode, pid):
                fail("IDENTITY_HOLD", f"{cid}单次出镜豁免范围/依据无效")
            if require_assets and not one_off(binding, book, episode, pid):
                asset_check(binding.get("identity_asset_alias"), cid, "identity", None, "IDENTITY_HOLD")
                asset_check(binding.get("costume_asset_alias"), cid, "costume_state", sid, "APPEARANCE_HOLD")
            elif require_assets and prompt:
                from reference_atlas import is_atlas
                for key,purpose,state_id in (('identity_asset_alias','identity',None),('costume_asset_alias','costume_state',sid)):
                    if is_atlas(refs.get(binding.get(key))):asset_check(binding[key],cid,purpose,state_id,'IDENTITY_HOLD')
        if visible_ids(panel) != on_screen:
            fail("IDENTITY_HOLD", "入画角色与身份绑定不一致，不能增加未知角色或漏绑人物")
        binding = panel.get("scene_binding")
        if not isinstance(binding, dict):
            fail("SCENE_IDENTITY_HOLD", "缺少场景身份/归属/状态绑定")
        else:
            scene_id, state_id = binding.get("scene_id"), binding.get("scene_state_id")
            scene = tables["scene_states"].get(state_id) if text(state_id) else None
            if (not text(scene_id) or scene_id != panel.get("scene_id") or not isinstance(scene, dict) or scene.get("scene_id") != scene_id
                    or not all(text(scene.get(k)) for k in ("canonical_name", "ownership_context", "description"))
                    or not confirmed(scene, root, book, episode, pid, scene_id, {"scene_identity", "scene_state"}, state_id)):
                fail("SCENE_IDENTITY_HOLD", "场景地点、归属、时期或状态未确认/不匹配")
            if not isinstance(binding.get("background_visible"), bool):
                fail("SCENE_IDENTITY_HOLD", "须明确background_visible")
            if "asset_exemption" in binding and not one_off(binding, book, episode, pid):
                fail("SCENE_IDENTITY_HOLD", "场景单次出镜豁免范围/依据无效")
            if require_assets and text(scene_id) and binding.get("background_visible") is not False and not one_off(binding, book, episode, pid):
                asset_check(binding.get("asset_alias"), scene_id, "scene_view", state_id, "SCENE_IDENTITY_HOLD")
        if prompt and require_execution and len(errors) == before:
            block = execution_block(panel, registry)
            if panel.get("identity_execution_block") != block or block not in str(panel.get("prompt", "")):
                fail("IDENTITY_HOLD", "身份与状态锁定块未同步写入实际提示词")
    return errors


def repair_preflight(data: Any, root: Path, reference_root: Path,
                     shot: Any = None) -> list[str]:
    """Run before creating a repaired package; repair consent is not evidence."""
    try:
        errors = validate_manifest(data, root, prompt=True, reference_root=reference_root,
                                   require_execution=False)
        if shot is not None:
            errors.extend(validate_manifest(shot, root))
            if isinstance(data, dict) and isinstance(shot, dict):
                for key in ("identity_policy", "book_id", "episode_id", "identity_registry"):
                    if data.get(key) != shot.get(key):
                        errors.append(f"IDENTITY_HOLD: 修复源包与镜头表{key}不一致")
                shot_panels = shot.get("panels") or shot.get("shot_design") or []
                by_id = {p.get("panel_id"): p for p in shot_panels if isinstance(p, dict) and text(p.get("panel_id"))}
                for panel in data.get("panels", []):
                    if not isinstance(panel, dict) or not text(panel.get("panel_id")):
                        continue
                    other = by_id.get(panel["panel_id"], {})
                    for key in ("script_character_labels", "character_bindings", "scene_binding"):
                        if panel.get(key) != other.get(key):
                            errors.append(f"IDENTITY_HOLD: {panel['panel_id']}源包与镜头表{key}不一致")
        return errors
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return [f"IDENTITY_HOLD: 修复前身份依据或绑定无法核验: {exc}"]


def main() -> int:
    parser = argparse.ArgumentParser(description="身份/外观/场景确认门禁；不授予用户批准")
    parser.add_argument("--root", required=True, help="确认依据所在本话根目录")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--prompt", action="store_true", help="检查实际参考图绑定和提示词锁定块")
    parser.add_argument("--identity-only", action="store_true", help="仅供A/B/C设计前确认身份/关系/状态；不授权提示词交付")
    args = parser.parse_args()
    if args.prompt and args.identity_only:
        parser.error("--identity-only不能与--prompt一起使用；生图包必须核验实际资产")
    try:
        data = json.loads(Path(args.manifest).read_text(encoding="utf-8-sig"))
        errors = validate_manifest(data, Path(args.root).resolve(), prompt=args.prompt,
                                   reference_root=Path(args.manifest).resolve().parent,
                                   require_assets=not args.identity_only)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors = [f"IDENTITY_HOLD: 无法读取身份审计: {exc}"]
    scope = "identity_relationship_state_only_not_production_release" if args.identity_only else "identity_evidence_and_bindings_only"
    print(json.dumps({"status": "HOLD" if errors else "PASS", "scope": scope, "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
