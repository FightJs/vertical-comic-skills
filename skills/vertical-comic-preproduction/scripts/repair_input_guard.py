#!/usr/bin/env python3
"""Reject contradictory repair-image references before an image call."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from continuity_contract import TRANSFERS

TRANSFER_FIELDS = set().union(*TRANSFERS.values())
STALE_PROCESS_TEXT = ('待人工批准', '当前禁止调用', '本次唯一第二轮', 'manual_budget_remaining')
CONTACT_FIELDS = ('actor', 'target', 'actor_limb', 'target_part', 'visible_path', 'forbidden_reverse')


def _failed_image_aliases(panel):
    aliases = set()
    references = panel.get('reference_images', [])
    for ref in references if isinstance(references, list) else []:
        if not isinstance(ref, dict):
            continue
        alias = ref.get('alias')
        role = ref.get('role', '')
        if isinstance(alias, str) and ('REPAIR_TARGET' in alias.upper() or
                                       isinstance(role, str) and role in {'repair_target', 'edit_target', 'failed_image'}):
            aliases.add(alias)
    return aliases


def repair_errors(panel, *, actual_prompt=None, require_focus=True):
    if panel.get('operation') != 'repair':
        return []
    errors = []
    from visual_evidence import repair_source_errors
    from appearance_lock import repair_errors as appearance_repair_errors
    errors.extend(repair_source_errors(panel))
    errors.extend(appearance_repair_errors(panel,actual_prompt))
    if panel.get('background_policy'):
        from visual_evidence import framing_errors
        errors.extend(framing_errors(panel, prompt=True))
    declared_prompt = panel.get('prompt', '')
    prompt = declared_prompt if actual_prompt is None else actual_prompt
    if not isinstance(prompt, str) or not prompt.strip():
        return ['REPAIR_INPUT_HOLD:返修缺少实际绘图提示词']
    if actual_prompt is not None and prompt != declared_prompt:
        errors.append('REPAIR_INPUT_HOLD:实际提交提示词与逐格JSON不一致，须重新编译并校验最终文本')
    for phrase in STALE_PROCESS_TEXT:
        if phrase in prompt:
            errors.append(f'REPAIR_INPUT_HOLD:绘图提示词混入流程状态「{phrase}」')

    aliases = _failed_image_aliases(panel)
    focus = panel.get('repair_focus')
    if not aliases and focus is None:
        return errors
    if not isinstance(focus, dict):
        return errors + (['REPAIR_INPUT_HOLD:携带失败图时须声明repair_focus'] if require_focus else [])
    failed = focus.get('failed_transfers')
    if (not isinstance(failed, list) or not failed or
            any(not isinstance(item, str) or item not in TRANSFER_FIELDS for item in failed) or
            len(failed) != len(set(failed))):
        return errors + ['REPAIR_INPUT_HOLD:repair_focus.failed_transfers须列出本次必须纠正的具体迁移要素']
    failed_set = set(failed)
    structure=focus.get('structural_change')
    if structure is not None:
        if (not isinstance(structure,dict) or any(not isinstance(structure.get(k),str)
                or not structure[k].strip() for k in ('remove','replace','connect'))):
            errors.append('REPAIR_INPUT_HOLD:肢体改姿须同时说明旧结构移除、新结构和连接路径')
        elif any(structure[k] not in prompt for k in ('remove','replace','connect')):
            errors.append('REPAIR_INPUT_HOLD:实际提示词未完整落实旧肢体清理和新连接')
    bindings = panel.get('reference_bindings', [])
    if not isinstance(bindings, list):
        bindings = []
    for alias in aliases:
        uses = [binding for binding in bindings if isinstance(binding, dict) and binding.get('alias') == alias]
        if not uses:
            errors.append(f'REPAIR_INPUT_HOLD:{alias}缺少失败图用途绑定')
        for binding in uses:
            raw_allowed = binding.get('allowed_transfer', [])
            raw_forbidden = binding.get('forbidden_transfer', [])
            if (not isinstance(raw_allowed, list) or not isinstance(raw_forbidden, list) or
                    any(not isinstance(item, str) for item in [*raw_allowed, *raw_forbidden])):
                errors.append(f'REPAIR_INPUT_HOLD:{alias}迁移用途列表无效')
                continue
            allowed = set(raw_allowed)
            forbidden = set(raw_forbidden)
            overlap = sorted(allowed & failed_set)
            if overlap:
                errors.append(f'REPAIR_INPUT_HOLD:{alias}允许继承本次待修正要素:{",".join(overlap)}')
            missing = sorted(failed_set - forbidden)
            if missing:
                errors.append(f'REPAIR_INPUT_HOLD:{alias}未明确禁止继承失败要素:{",".join(missing)}')

    if 'contact' in failed_set:
        contact = focus.get('action_contact')
        if not isinstance(contact, dict) or any(not isinstance(contact.get(key), str) or
                                                not contact[key].strip() for key in CONTACT_FIELDS):
            errors.append('REPAIR_INPUT_HOLD:接触关系返修须逐项声明主动者、对象、双方部位、可见路径和反向误画')
        else:
            for key in CONTACT_FIELDS:
                if contact[key] not in prompt:
                    errors.append(f'REPAIR_INPUT_HOLD:实际提示词缺少action_contact.{key}')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', required=True, help='单格生图包或逐格JSON路径')
    parser.add_argument('--prompt-file', help='旧RV人工调用时实际提交的最终prompt文件')
    args = parser.parse_args()
    packet = json.loads(Path(args.packet).read_text(encoding='utf-8'))
    panels = packet.get('panels', []) if isinstance(packet, dict) and 'panels' in packet else [packet]
    actual_prompt = Path(args.prompt_file).read_text(encoding='utf-8') if args.prompt_file else None
    errors = (['REPAIR_INPUT_HOLD:须为单格包'] if not isinstance(panels, list) or len(panels) != 1
              else repair_errors(panels[0], actual_prompt=actual_prompt))
    print(json.dumps({'status': 'HOLD' if errors else 'PASS', 'errors': errors}, ensure_ascii=False, indent=2))
    raise SystemExit(1 if errors else 0)


if __name__ == '__main__':
    from platform_io import configure_stdio
    configure_stdio()
    main()
