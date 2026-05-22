"""LLM-based warehouse layout generator.

Calls deepseek-chat (OpenAI-compatible API) to produce a JSON actor list
with EXACTLY `count` entries. Enforces count via prompt + post-validation
with up to MAX_RETRIES attempts, then slices/pads as last resort.

Usage:
    from scene_gen.layout_gen import generate_layout
    actors = generate_layout("warehouse with shelves and crates", count=40)
"""

from __future__ import annotations

import json
import logging
import os
import random

import requests

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
API_URL = "https://api.deepseek.com/chat/completions"

# Known warehouse asset classes with approximate half-extents (cm)
WAREHOUSE_CATALOG = [
    ("SM_Shelf_Large",  half_x := 90,  half_y := 30),
    ("SM_Shelf_Small",   60,  25),
    ("SM_Pallet_Wood",   60,  60),
    ("SM_Pallet_Metal",  60,  60),
    ("SM_Crate_Large",   50,  50),
    ("SM_Crate_Small",   30,  30),
    ("SM_Barrel",        25,  25),
    ("SM_Box_Large",     40,  40),
    ("SM_Box_Small",     25,  25),
    ("SM_ConveyorBelt",  150, 40),
    ("SM_Forklift",      100, 80),
]
_CATALOG_NAMES = [c[0] for c in WAREHOUSE_CATALOG]


_SYSTEM_PROMPT = """\
You are a warehouse 3D scene layout generator for Unreal Engine 5.
Generate a realistic-looking warehouse floor plan.

RULES (mandatory):
1. Output EXACTLY {count} actors -- not one more, not one fewer.
   Count your array elements carefully before responding.
2. All positions are in centimeters, floor is at Z=0.
3. Place actors inside a {area_x} x {area_y} cm bounding box centred at the origin.
4. Actors must NOT overlap. Keep at least {min_gap} cm between any two actor centres.
5. Use a mix of asset classes from this list ONLY (exact strings):
   {catalog}
6. Respond with a JSON object: {{"actors": [ ... ]}}
   Each actor: {{"class": "SM_...", "x": float, "y": float, "yaw": float, "scale": float}}
   - yaw: 0-359 degrees
   - scale: 0.8-1.4
   No other fields, no prose, no markdown fences.
"""


def _build_system(count: int, area_x: int, area_y: int, min_gap: int) -> str:
    return _SYSTEM_PROMPT.format(
        count=count,
        area_x=area_x,
        area_y=area_y,
        min_gap=min_gap,
        catalog=", ".join(_CATALOG_NAMES),
    )


# Average footprint per asset class (cm^2)
_AVG_FOOTPRINT_CM2 = 4900  # ~70x70 cm typical mixed-warehouse


def recommend_count(area_x_cm: int, area_y_cm: int, density: str = "medium") -> dict:
    """Recommend object count based on volume floor area + density preset.

    Returns: {"min": int, "recommended": int, "max": int, "area_m2": float}
    """
    area_cm2 = max(1, area_x_cm * area_y_cm)
    area_m2 = area_cm2 / 10000.0

    # Coverage ratios (footprint area / total floor area)
    ratios = {"sparse": 0.08, "medium": 0.18, "dense": 0.32}
    ratio = ratios.get(density, 0.18)

    rec = max(1, int(area_cm2 * ratio / _AVG_FOOTPRINT_CM2))
    mn = max(1, int(area_cm2 * ratios["sparse"] / _AVG_FOOTPRINT_CM2))
    mx = max(rec + 1, int(area_cm2 * ratios["dense"] / _AVG_FOOTPRINT_CM2))
    return {"min": mn, "recommended": rec, "max": mx, "area_m2": round(area_m2, 1)}


def _parse_actors(raw: str, count: int) -> list[dict]:
    """Parse LLM JSON, normalise, enforce count (slice if over, raise if under)."""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        # Try to extract first JSON object from response
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            obj = json.loads(raw[start:end])
        else:
            raise ValueError(f"LLM response is not valid JSON: {e}") from e

    actors = obj.get("actors", [])
    if not isinstance(actors, list):
        raise ValueError("'actors' field is not a list")

    # Normalise each entry
    normed = []
    for a in actors:
        if not isinstance(a, dict):
            continue
        cls = str(a.get("class", "SM_Crate_Small")).strip()
        if cls not in _CATALOG_NAMES:
            cls = "SM_Crate_Small"
        normed.append({
            "class": cls,
            "x": float(a.get("x", 0)),
            "y": float(a.get("y", 0)),
            "yaw": float(a.get("yaw", 0)) % 360,
            "scale": max(0.5, min(2.0, float(a.get("scale", 1.0)))),
        })

    if len(normed) > count:
        logger.warning("LLM returned %d actors (requested %d); truncating.", len(normed), count)
        normed = normed[:count]
    if len(normed) < count:
        raise ValueError(f"LLM returned only {len(normed)} actors (need {count})")

    return normed


def _enforce_no_overlap(actors: list[dict], min_gap: float) -> list[dict]:
    """Iteratively nudge actors apart until no pair is closer than min_gap."""
    import math as _math
    positions = [[a["x"], a["y"]] for a in actors]
    max_iter = 300
    for _ in range(max_iter):
        changed = False
        for i in range(len(positions)):
            for j in range(i + 1, len(positions)):
                dx = positions[j][0] - positions[i][0]
                dy = positions[j][1] - positions[i][1]
                dist = _math.hypot(dx, dy)
                if dist < min_gap:
                    if dist < 1e-6:
                        # Exact overlap: nudge along diagonal based on indices
                        angle = _math.pi * 2 * ((i * 17 + j * 31) % 100) / 100
                        dx, dy, dist = _math.cos(angle), _math.sin(angle), 1.0
                    push = (min_gap - dist) / 2 + 1
                    nx, ny = (dx / dist) * push, (dy / dist) * push
                    positions[i][0] -= nx
                    positions[i][1] -= ny
                    positions[j][0] += nx
                    positions[j][1] += ny
                    changed = True
        if not changed:
            break

    for a, pos in zip(actors, positions):
        a["x"] = round(pos[0], 1)
        a["y"] = round(pos[1], 1)
    return actors


def generate_layout(
    prompt: str,
    count: int = 40,
    area_x: int = 3000,
    area_y: int = 2000,
    min_gap: int = 150,
    floor_z: float = 0.0,
    centre_xy: tuple[float, float] = (0.0, 0.0),
    api_key: str | None = None,
    model: str = "deepseek-chat",
) -> list[dict]:
    """Call deepseek to generate exactly `count` warehouse actors.

    Args:
        prompt:   Natural language scene description (appended to system prompt).
        count:    Exact number of actors to generate.
        area_x/y: Floor bounding box in cm.
        min_gap:  Minimum centre-to-centre gap between any two actors (cm).
        floor_z:  Z coordinate for all actors (override LLM Z, default 0).
        api_key:  deepseek API key; falls back to DEEPSEEK_API_KEY env var.
        model:    deepseek model name.

    Returns:
        List of exactly `count` actor dicts with keys:
        class, x, y, z, yaw, scale.

    Raises:
        ValueError: if API key missing or LLM never produced correct count.
        requests.HTTPError: on network/API error.
    """
    key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise ValueError(
            "deepseek API key not set. Set DEEPSEEK_API_KEY env var or pass api_key=."
        )

    system = _build_system(count, area_x, area_y, min_gap)
    user_msg = (
        f"Scene description: {prompt}\n"
        f"Generate EXACTLY {count} actors. "
        f"Double-check: your JSON array must have len == {count}."
    )

    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        logger.info("[LAYOUT] deepseek attempt %d/%d (count=%d)", attempt, MAX_RETRIES, count)
        try:
            resp = requests.post(
                API_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_msg},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.7,
                },
                timeout=60,
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            actors = _parse_actors(raw, count)
            actors = _enforce_no_overlap(actors, min_gap)
            # Clamp into [-area/2, area/2], then shift to volume centre.
            cx, cy = centre_xy
            hx, hy = area_x / 2.0, area_y / 2.0
            for a in actors:
                a["x"] = max(-hx, min(hx, a["x"])) + cx
                a["y"] = max(-hy, min(hy, a["y"])) + cy
                a["z"] = floor_z
            logger.info("[LAYOUT] OK: %d actors generated.", len(actors))
            return actors
        except ValueError as e:
            last_err = e
            logger.warning("[LAYOUT] Attempt %d failed: %s", attempt, e)

    # Last resort: pad with random boxes if still short (shouldn't happen normally)
    if last_err and "only" in str(last_err):
        logger.error("[LAYOUT] All retries failed: %s. Padding with random actors.", last_err)
        actors = _parse_actors_lenient(last_err, count, floor_z, area_x, area_y)
        if actors:
            return actors
    raise ValueError(f"Could not generate {count} actors after {MAX_RETRIES} tries: {last_err}")


def _parse_actors_lenient(err: Exception, count: int, floor_z: float,
                           area_x: int, area_y: int) -> list[dict]:
    """Best-effort: extract actors from the error context and pad."""
    # This is only called if _parse_actors raised 'only N actors' error.
    # We can't recover the partial list from the exception, so generate
    # a simple grid-based fallback layout.
    logger.warning("[LAYOUT] Generating grid-based fallback layout.")
    cols = max(1, int((area_x / 300) ** 0.5 * 1.5))
    actors = []
    for i in range(count):
        col = i % cols
        row = i // cols
        actors.append({
            "class": random.choice(_CATALOG_NAMES[:6]),
            "x": round(-area_x / 2 + 300 * col + 150, 1),
            "y": round(-area_y / 2 + 300 * row + 150, 1),
            "z": floor_z,
            "yaw": random.randint(0, 3) * 90.0,
            "scale": round(random.uniform(0.9, 1.1), 2),
        })
    return actors
