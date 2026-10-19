#!/usr/bin/env python3
"""Render simple SVG station maps from JSON.

The renderer is intentionally diagrammatic. It does not claim to perform a
full 3D projection; it makes the spatial records visible and reviewable.
"""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from typing import Any

from legacy_spatial_cleanup import retired_inputs


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def point(x: float, y: float, angle: float, length: float = 55) -> tuple[float, float]:
    radians = math.radians(angle)
    return x + math.cos(radians) * length, y - math.sin(radians) * length


def arrow(x: float, y: float, angle: float, dashed: bool, color: str) -> str:
    x2, y2 = point(x, y, angle)
    dash = ' stroke-dasharray="10 8"' if dashed else ""
    return f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="4"{dash} marker-end="url(#arrow)" />'


def station_svg(state: dict[str, Any]) -> str:
    bounds = state.get("scene_bounds") or {}
    width = float(bounds.get("width", 1200))
    height = float(bounds.get("height", 800))
    margin = 80
    scale = min(1200 / width, 760 / height)
    ox, oy = margin, 130
    sx, sy = width * scale, height * scale
    def px(v: float) -> float: return ox + v * scale
    def py(v: float) -> float: return oy + v * scale
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1360" height="980" viewBox="0 0 1360 980">', '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#354052"/></marker></defs>']
    parts.append(f'<rect x="0" y="0" width="1360" height="980" fill="#f6f8fb"/>')
    parts.append(f'<text x="80" y="55" font-size="28" font-family="Arial, Microsoft YaHei" font-weight="700">{esc(state.get("state_id", "STATION"))} {esc(state.get("title", "站位状态"))}</text>')
    parts.append(f'<text x="80" y="88" font-size="16" font-family="Arial, Microsoft YaHei" fill="#5c6675">场景 {esc(state.get("scene_id", ""))} · 比例尺 {esc(state.get("scale_reference", ""))}</text>')
    parts.append(f'<rect x="{ox}" y="{oy}" width="{sx:.1f}" height="{sy:.1f}" fill="#ffffff" stroke="#283548" stroke-width="5"/>')
    for obj in state.get("objects", []):
        x, y, w, h = map(float, (obj.get("x", 0), obj.get("y", 0), obj.get("width", 40), obj.get("height", 40)))
        color = "#8ea4bd" if obj.get("kind") != "anchor" else "#d38b57"
        parts.append(f'<rect x="{px(x):.1f}" y="{py(y):.1f}" width="{w*scale:.1f}" height="{h*scale:.1f}" fill="{color}" fill-opacity="0.28" stroke="{color}" stroke-width="3"/>')
        parts.append(f'<text x="{px(x)+4:.1f}" y="{py(y)+18:.1f}" font-size="15" font-family="Arial, Microsoft YaHei" fill="#263244">{esc(obj.get("label", obj.get("id", "object")))}</text>')
    for anchor in state.get("anchors", []):
        x, y = px(float(anchor.get("x", 0))), py(float(anchor.get("y", 0)))
        parts.append(f'<path d="M{x:.1f},{y-16:.1f} L{x+14:.1f},{y+12:.1f} L{x-14:.1f},{y+12:.1f} Z" fill="#d66b5d" stroke="#8f3025" stroke-width="2"/>')
        parts.append(f'<text x="{x+18:.1f}" y="{y+5:.1f}" font-size="15" font-family="Arial, Microsoft YaHei">{esc(anchor.get("label", anchor.get("id", "anchor")))}</text>')
    for person in state.get("people", []):
        x, y = px(float(person.get("x", 0))), py(float(person.get("y", 0)))
        r = max(13, float(person.get("radius", 25)) * scale)
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="#d9e6f5" stroke="#315f8e" stroke-width="4"/>')
        parts.append(arrow(x, y, float(person.get("body_angle", 0)), False, "#315f8e"))
        parts.append(arrow(x, y, float(person.get("gaze_angle", person.get("body_angle", 0))), True, "#b05288"))
        parts.append(f'<text x="{x+r+8:.1f}" y="{y+5:.1f}" font-size="17" font-family="Arial, Microsoft YaHei">{esc(person.get("label", person.get("id", "person")))}</text>')
    for cam in state.get("cameras", []):
        x, y = px(float(cam.get("x", 0))), py(float(cam.get("y", 0)))
        parts.append(f'<rect x="{x-9:.1f}" y="{y-9:.1f}" width="18" height="18" fill="#222"/>')
        parts.append(arrow(x, y, float(cam.get("angle", 0)), False, "#111"))
        parts.append(f'<text x="{x+14:.1f}" y="{y-14:.1f}" font-size="15" font-family="Arial, Microsoft YaHei">{esc(cam.get("label", cam.get("id", "camera")))}</text>')
    parts.append('<text x="80" y="900" font-size="16" font-family="Arial, Microsoft YaHei" fill="#5c6675">实线箭头=身体朝向　虚线箭头=视线　方框=物体　△=背景锚点　■=相机</text>')
    parts.append('</svg>')
    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="渲染站位图")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    manifest_path = Path(args.manifest).resolve()
    output = Path(args.output_dir).resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if retired_inputs(data):
        raise SystemExit("停用的逐格示意输入：请先迁移为空间状态索引，未创建输出。")
    output.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for state in data.get("states", []):
        name = f"{state.get('state_id', 'state')}.svg"
        path = output / name
        path.write_text(station_svg(state), encoding="utf-8", newline='\n')
        written.append(str(path))
    print(json.dumps({"status": "PASS", "spatial_proof": False, "written": written}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    from platform_io import configure_stdio
    configure_stdio()
    raise SystemExit(main())
