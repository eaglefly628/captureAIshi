"""Cross-asset overlap pass + budget enforcement.

`pcg/primitives.py::random_scatter` already does self-pruning *within one
asset class*, but nothing guards against cross-class overlap (a pallet
spawned next to a drum, a box on top of a forklift). This module runs
once at the end of `generate_warehouse` (or any layout fn) to:

  1. Drop non-structural spawns that fall within another spawn's
     footprint radius.
  2. Trim total spawns down to an explicit budget if one was given,
     preserving structural categories first.

Footprint radii are in meters and treated as 2D circles centered on the
SpawnRequest (x, y). Cheap O(N*M) check -- fine for our regime
(N < 300 actors), no need for KD-tree.
"""

from __future__ import annotations

import random
from .base import SpawnRequest

# half-footprint radius in meters per asset_name. Conservative -- err
# toward larger so we don't visibly clip meshes together. Tune as real
# meshes land.
FOOTPRINT_R_M: dict[str, float] = {
    "shelf":     1.0,   # 1.6m x 1.2m -> ~1m radius
    "forklift":  1.2,
    "pallet":    0.65,
    "box":       0.35,
    "drum":      0.35,
    "worker":    0.4,
    "crate":     0.45,
    # Living room
    "sofa":         1.2,
    "coffee_table": 0.6,
    "side_table":   0.4,
    "chair":        0.45,
    "floor_lamp":   0.3,
    "table_lamp":   0.2,
    "rug":          1.5,
    "plant":        0.35,
    "bookshelf":    0.6,
    "tv_unit":      0.8,
    # Industrial
    "machine":     1.0,
    "workbench":   0.9,
    "toolboard":   0.4,
    "tool_small":  0.2,
    "pipe":        0.3,
    "cable_reel":  0.5,
    "fume_hood":   0.8,
}
DEFAULT_FOOTPRINT_R_M = 0.4

# Categories that anchor the layout -- never dropped by either pass.
STRUCTURAL_ASSETS: frozenset[str] = frozenset({"shelf", "sofa", "bookshelf", "tv_unit", "machine", "workbench"})

# Ceiling decor -- not counted toward object_budget (they fill the
# room atmospherically but the user's "40 objects" doesn't mean lights).
CEILING_ASSETS: tuple[str, ...] = (
    "light_sodium", "light_cool_white", "light_mixed",
    "ceiling_pendant",
)


def _footprint(asset_name: str) -> float:
    return FOOTPRINT_R_M.get(asset_name, DEFAULT_FOOTPRINT_R_M)


def _is_ceiling(asset_name: str) -> bool:
    return asset_name in CEILING_ASSETS or asset_name.startswith("light_")


def enforce_no_overlap(spawns: list[SpawnRequest]) -> tuple[list[SpawnRequest], int]:
    """Drop non-structural spawns whose footprint overlaps an earlier one.

    Order of survival:
      1. Structural assets are accepted first (never dropped, never block
         each other -- they came from grid logic which already placed them
         cleanly).
      2. Ceiling/light assets always accepted (different vertical plane).
      3. Floor decor (pallet/box/drum/worker/...) accepted in original
         order, skipped if overlapping any accepted spawn.

    Returns (kept_spawns, dropped_count).
    """
    structural = [s for s in spawns if s.asset_name in STRUCTURAL_ASSETS]
    ceiling = [s for s in spawns if _is_ceiling(s.asset_name)]
    floor = [
        s for s in spawns
        if s.asset_name not in STRUCTURAL_ASSETS and not _is_ceiling(s.asset_name)
    ]

    accepted: list[SpawnRequest] = list(structural)
    accepted_xy_r: list[tuple[float, float, float]] = [
        (s.x, s.y, _footprint(s.asset_name)) for s in structural
    ]
    dropped = 0
    for s in floor:
        r = _footprint(s.asset_name)
        clash = False
        for ax, ay, ar in accepted_xy_r:
            dx, dy = s.x - ax, s.y - ay
            min_d = (r + ar) * 0.7  # softening -- mesh footprints are tighter than the conservative radii
            if dx * dx + dy * dy < min_d * min_d:
                clash = True
                break
        if clash:
            dropped += 1
            continue
        accepted.append(s)
        accepted_xy_r.append((s.x, s.y, r))

    return accepted + ceiling, dropped


def enforce_budget(
    spawns: list[SpawnRequest], budget: int | None, rng: random.Random
) -> tuple[list[SpawnRequest], int]:
    """Trim spawns to <= budget total. Lights excluded from budget count.

    Always keeps structural assets. Drops non-structural floor decor
    randomly (rng-seeded) until under budget.

    Returns (trimmed_spawns, dropped_count). If budget is None, no-op.
    """
    if budget is None or budget <= 0:
        return spawns, 0
    structural = [s for s in spawns if s.asset_name in STRUCTURAL_ASSETS]
    ceiling = [s for s in spawns if _is_ceiling(s.asset_name)]
    floor = [
        s for s in spawns
        if s.asset_name not in STRUCTURAL_ASSETS and not _is_ceiling(s.asset_name)
    ]
    countable_n = len(structural) + len(floor)
    if countable_n <= budget:
        return spawns, 0

    floor_budget = max(0, budget - len(structural))
    if len(floor) > floor_budget:
        kept_floor = list(floor)
        rng.shuffle(kept_floor)
        dropped = len(kept_floor) - floor_budget
        kept_floor = kept_floor[:floor_budget]
    else:
        kept_floor = floor
        dropped = 0
    return structural + kept_floor + ceiling, dropped


def recommend_object_budget(
    room_w_m: float, room_l_m: float, density: str = "medium"
) -> dict:
    """Suggest object_budget given room footprint + density preset.

    Returns: {"min", "recommended", "max", "area_m2"}.
    """
    area_m2 = max(1.0, room_w_m * room_l_m)
    # Floor-decor density (objects per m^2). Structural shelves usually
    # dominate the budget so the ratios are intentionally conservative.
    ratios = {"sparse": 0.15, "medium": 0.30, "dense": 0.55}
    r = ratios.get(density, 0.30)
    rec = max(4, int(area_m2 * r))
    return {
        "min": max(2, int(area_m2 * ratios["sparse"])),
        "recommended": rec,
        "max": max(rec + 2, int(area_m2 * ratios["dense"])),
        "area_m2": round(area_m2, 1),
    }
