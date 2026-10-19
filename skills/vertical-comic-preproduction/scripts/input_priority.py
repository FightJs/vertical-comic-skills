"""Shared input-priority contract for new panel packages and scoped repairs.

This checks recorded decisions and executable text, not the visual truth of an
image or the authenticity of an approval. Legacy packages opt in explicitly.
"""

from __future__ import annotations

from typing import Any


POLICY = "physical_scene_priority_v1"
EXECUTION_BLOCK = (
    "物理与场景约束：人物关节、重心、支撑、接触、透视和遮挡必须成立；"
    "门窗、墙体、家具、固定物件的存在、数量、形状及真实空间位置以已批准场景依据为准，换机位不挪动场景。"
    "人物身份、当前衣装、指定表情、动作、作用对象、结果及已批准画风必须同时保留。"
    "脚本中的镜头或构图描述若与上述约束冲突，仅执行本格有依据且获批的画面适配；"
    "不得补造家具、扭曲人体、解除真实遮挡或自行改写剧情。"
)


def resolution_block(value: Any) -> str:
    """Only an approved, evidence-linked visual solution may enter the prompt."""
    if not isinstance(value, dict) or value.get("status") != "APPROVED":
        return ""
    solution = value.get("approved_visual_solution")
    return f"本格已批准画面适配：{solution}。" if isinstance(solution, str) and solution.strip() else ""


def resolution_errors(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, dict):
        return ["visual_resolution必须是对象"]
    if value.get("status") != "APPROVED":
        return ["VISUAL_CONFLICT_HOLD：visual_resolution未获批准"]
    return [f"visual_resolution缺少{key}" for key in
            ("issue", "scene_evidence", "approved_visual_solution", "approval_evidence")
            if not isinstance(value.get(key), str) or not value[key].strip()]
