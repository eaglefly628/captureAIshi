"""Procedural SVG thumbnail generator (sandbox-friendly, no external assets).

Outputs SVG that mimics a multi-channel preview frame: top-down room
layout + lighting tint. Same pixel budget as a real 512x288 LDR thumb.
"""

from __future__ import annotations

import hashlib

SCENE_BG = {
    "warehouse": ("#2a2620", "#3a3225"),
    "living_room": ("#2a2528", "#3a3035"),
    "industrial_corner": ("#1f1f24", "#2c2c34"),
}

LIGHTING_TINT = {
    "warehouse_sodium": "#ffb84d",
    "cool_white": "#e4ecff",
    "mixed": "#ffd99a",
    "indoor_tungsten": "#ffcc88",
    "cool_daylight": "#dceaff",
    "evening_warm": "#ff9a55",
    "halogen_spot": "#fff0c2",
}


def _seed(scene: str, variant: str, frame: int) -> int:
    h = hashlib.md5(f"{scene}|{variant}|{frame}".encode()).hexdigest()
    return int(h[:8], 16)


def _rand(seed: int, n: int) -> list[float]:
    out: list[float] = []
    x = seed
    for _ in range(n):
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        out.append((x % 10000) / 10000.0)
    return out


def render_thumbnail_svg(
    scene_id: str,
    variant_id: str = "v0_1",
    frame: int = 1,
    pcg_params: dict | None = None,
    channel: str = "final",
) -> str:
    pcg_params = pcg_params or {}
    seed = _seed(scene_id, variant_id, frame)
    rnd = _rand(seed, 200)
    bg_a, bg_b = SCENE_BG.get(scene_id, ("#202020", "#303030"))
    tint = LIGHTING_TINT.get(
        pcg_params.get("lighting_preset", ""), "#ffcc88"
    )

    w, h = 512, 288
    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="{w}" height="{h}" preserveAspectRatio="xMidYMid slice">'
    )

    if channel == "depth":
        parts.append(f'<rect width="{w}" height="{h}" fill="#101010"/>')
    elif channel == "normal":
        parts.append(f'<rect width="{w}" height="{h}" fill="#7f7fff"/>')
    elif channel == "objectid":
        parts.append(f'<rect width="{w}" height="{h}" fill="#1a0a1a"/>')
    else:
        parts.append(
            f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0%" stop-color="{bg_a}"/>'
            f'<stop offset="100%" stop-color="{bg_b}"/>'
            f'</linearGradient></defs>'
        )
        parts.append(f'<rect width="{w}" height="{h}" fill="url(#g)"/>')
        parts.append(
            f'<radialGradient id="lt" cx="50%" cy="20%" r="60%">'
            f'<stop offset="0%" stop-color="{tint}" stop-opacity="0.45"/>'
            f'<stop offset="100%" stop-color="{tint}" stop-opacity="0"/>'
            f'</radialGradient>'
            f'<rect width="{w}" height="{h}" fill="url(#lt)"/>'
        )

    if scene_id == "warehouse":
        rows = max(2, int(pcg_params.get("shelf_density", 0.7) * 8))
        cols = max(3, int(pcg_params.get("shelf_density", 0.7) * 10))
        cell_w = (w - 60) / cols
        cell_h = (h - 80) / rows
        for r in range(rows):
            for c in range(cols):
                ji = (r * cols + c) % len(rnd)
                jitter = rnd[ji] * 4 - 2
                x = 30 + c * cell_w + jitter
                y = 40 + r * cell_h + jitter
                color = "#5a4a3a" if channel == "final" else "#a0a0a0"
                if channel == "objectid":
                    color = f"hsl({(r * cols + c) * 37 % 360}, 70%, 50%)"
                parts.append(
                    f'<rect x="{x:.1f}" y="{y:.1f}" '
                    f'width="{cell_w - 8:.1f}" height="{cell_h - 12:.1f}" '
                    f'fill="{color}" opacity="0.85"/>'
                )
        for k in range(int(pcg_params.get("forklift_count", 1))):
            fx = 80 + rnd[k * 3 + 1] * (w - 160)
            fy = 200 + rnd[k * 3 + 2] * 50
            forklift_color = "#f0b938" if channel == "final" else "#cccccc"
            if channel == "objectid":
                forklift_color = "#ff66cc"
            parts.append(
                f'<rect x="{fx:.0f}" y="{fy:.0f}" width="34" height="22" '
                f'fill="{forklift_color}" rx="3"/>'
                f'<circle cx="{fx + 6:.0f}" cy="{fy + 24:.0f}" r="4" fill="#222"/>'
                f'<circle cx="{fx + 28:.0f}" cy="{fy + 24:.0f}" r="4" fill="#222"/>'
            )
    elif scene_id == "living_room":
        density = pcg_params.get("furniture_density", 0.55)
        parts.append(
            f'<rect x="40" y="80" width="220" height="120" '
            f'fill="{"#7a5a3a" if channel == "final" else "#c0c0c0"}" rx="8"/>'
        )
        parts.append(
            f'<rect x="280" y="160" width="80" height="50" '
            f'fill="{"#4a3a2a" if channel == "final" else "#a0a0a0"}" rx="4"/>'
        )
        decor_n = int(pcg_params.get("decor_variety", 5))
        for k in range(decor_n):
            dx = 60 + rnd[k * 2] * (w - 120)
            dy = 40 + rnd[k * 2 + 1] * 30
            decor_color = "#d4a574" if channel == "final" else "#909090"
            if channel == "objectid":
                decor_color = f"hsl({k * 47 % 360}, 70%, 50%)"
            parts.append(
                f'<circle cx="{dx:.0f}" cy="{dy:.0f}" r="6" '
                f'fill="{decor_color}"/>'
            )
        if pcg_params.get("rug_present", True):
            parts.append(
                f'<ellipse cx="180" cy="220" rx="140" ry="30" '
                f'fill="{"#a04030" if channel == "final" else "#888"}" opacity="0.5"/>'
            )
    else:
        for m in range(int(pcg_params.get("machine_count", 2))):
            mx = 60 + m * 130
            my = 100
            mc = "#4a4a4a" if channel == "final" else "#bbb"
            if channel == "objectid":
                mc = f"hsl({m * 73 % 360}, 70%, 50%)"
            parts.append(
                f'<rect x="{mx}" y="{my}" width="100" height="120" '
                f'fill="{mc}" rx="4"/>'
                f'<rect x="{mx + 20}" y="{my - 20}" width="60" height="24" '
                f'fill="#666"/>'
            )
        for p in range(int(pcg_params.get("pipe_complexity", 3))):
            py = 30 + p * 10
            parts.append(
                f'<line x1="0" y1="{py}" x2="{w}" y2="{py}" '
                f'stroke="#8a6a4a" stroke-width="6"/>'
            )
        for c in range(int(pcg_params.get("crate_count", 3))):
            cx = 20 + rnd[c * 2 + 100] * (w - 60)
            cy = 230 + rnd[c * 2 + 101] * 30
            parts.append(
                f'<rect x="{cx:.0f}" y="{cy:.0f}" width="32" height="24" '
                f'fill="#8a6234" rx="2"/>'
            )

    if channel == "final":
        parts.append(
            f'<text x="14" y="22" fill="#fff" opacity="0.55" '
            f'font-family="ui-monospace,Menlo,monospace" font-size="11">'
            f'{scene_id} / {variant_id} / frame {frame:04d}</text>'
        )
    else:
        parts.append(
            f'<text x="14" y="22" fill="#fff" opacity="0.7" '
            f'font-family="ui-monospace,Menlo,monospace" font-size="11">'
            f'{channel.upper()} pass</text>'
        )

    parts.append('</svg>')
    return "".join(parts)
