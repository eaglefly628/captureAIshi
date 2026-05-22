"""Warehouse procgen — 13 PCG-equivalent 参数全实现.

参数 contract: apps/adore_robot/docs/pcg_param_contract.md §1.0 + §1.1

Algorithm:
1. shelf_density → 推导 shelf_rows + shelves_per_row (连续 0.2-1.0 控制密度)
2. alley_width_m → row 间距
3. shelf 阵列 spawn (含 chaos 位置 jitter + rotation_jitter)
4. forklift 沿 aisle 中线散 N 个
5. pallet 贴 shelf 边
6. box room-floor 散落
7. drum 靠墙
8. worker aisle 中线 (避开 forklift)
9. lighting_preset → ceiling 灯网格 (sodium/cool/mixed)

Chaos master:
- chaos=0 → 整齐排列
- chaos=1 → 最乱 (位置 jitter + 朝向 jitter + variety 满)
"""

from __future__ import annotations

from .base import PCGContext, SpawnRequest, LayoutResult
from .primitives import (
    grid_points, random_scatter, wall_hug, line_points, avoid_actors,
)
from .lighting import spawn_ceiling_lights
from .conflict import enforce_no_overlap, enforce_budget

# 资产物理尺寸 (m) - 跟 contract §1.1 隐式参数对齐
SHELF_DEPTH_M = 1.2
SHELF_WIDTH_M = 1.6
FORKLIFT_MIN_DIST_M = 4.0
WORKER_AVOID_FORKLIFT_M = 2.0


def _derive_shelf_grid(
    shelf_density: float, room_w_m: float, room_l_m: float, alley_width_m: float
) -> tuple[int, int]:
    """shelf_density 0.2-1.0 → (rows, per_row) 推导.

    higher density → more rows + more per_row (但受 room 尺寸约束).
    """
    # 目标 row + per_row 按 density 缩放
    target_rows = max(1, int(2 + shelf_density * 6))  # 2-8 rows
    target_per_row = max(2, int(2 + shelf_density * 10))  # 2-12

    # 受 room_l_m 约束: rows 不能超过 room 能容纳的
    row_pitch = SHELF_DEPTH_M + alley_width_m
    max_rows_fit = max(1, int(room_l_m / row_pitch))
    rows = min(target_rows, max_rows_fit)

    # 受 room_w_m 约束: per_row 不能超过 room 宽能容纳的
    max_per_row_fit = max(2, int(room_w_m / SHELF_WIDTH_M))
    per_row = min(target_per_row, max_per_row_fit)

    return rows, per_row


def _compute_aisle_centerlines(
    rows: int, alley_width_m: float
) -> tuple[list[float], float, float]:
    """计算 row Y 位置 + aisle 中线 Y 位置 + row layout 总跨度.

    returns: (aisle_centerlines, y_start, total_span)
    """
    row_pitch = SHELF_DEPTH_M + alley_width_m
    total_span = rows * SHELF_DEPTH_M + (rows - 1) * alley_width_m
    y_start = -total_span / 2 + SHELF_DEPTH_M / 2

    aisle_centerlines: list[float] = []
    for r in range(rows - 1):
        y_row = y_start + r * row_pitch
        aisle_centerlines.append(y_row + SHELF_DEPTH_M / 2 + alley_width_m / 2)

    return aisle_centerlines, y_start, total_span


def generate_warehouse(
    # Tier 1: 必备 7 个 (chat 主控)
    shelf_density: float = 0.7,
    alley_width_m: float = 2.4,
    forklift_count: int = 1,
    worker_count: int = 0,
    room_w_m: float = 18.0,
    room_l_m: float = 28.0,
    seed: int = 0,
    # Tier 2: 炫酷 6 个
    pallet_count: int = 8,
    box_count: int = 5,
    drum_count: int = 3,
    lighting_preset: int = 0,  # 0=sodium / 1=cool / 2=mixed
    rotation_jitter_deg: float = 15.0,
    chaos: float = 0.3,
    # v0.4.2: user-facing object_budget (e.g. "give me 40 things").
    # Lights are not counted. Structural shelves are preserved first.
    # If None, no budget cap is enforced.
    object_budget: int | None = None,
) -> LayoutResult:
    """生成 warehouse layout, 13 参数全支持.

    返回 LayoutResult, 调用 .to_mcp_calls() 转 xiaoxu runner 用的 spawn 字典.
    """
    ctx = PCGContext(
        seed=seed,
        chaos=max(0.0, min(1.0, chaos)),
        rotation_jitter_deg=max(0.0, min(180.0, rotation_jitter_deg)),
    )
    spawns: list[SpawnRequest] = []

    # v0.4.2 budget-aware shelf scaling: if shelves alone would exceed
    # ~60% of object_budget, reduce shelf_density so the budget has room
    # for decor. Shelves are STRUCTURAL and never get dropped by
    # enforce_budget, so we must size them down up front.
    if object_budget is not None and object_budget > 0:
        tentative_rows, tentative_per_row = _derive_shelf_grid(
            shelf_density, room_w_m, room_l_m, alley_width_m
        )
        shelf_n = tentative_rows * tentative_per_row
        shelf_cap = max(4, int(object_budget * 0.6))
        if shelf_n > shelf_cap:
            # Binary-walk shelf_density down until shelves fit cap.
            for _ in range(20):
                shelf_density = max(0.2, shelf_density * 0.85)
                tr, tpr = _derive_shelf_grid(
                    shelf_density, room_w_m, room_l_m, alley_width_m
                )
                if tr * tpr <= shelf_cap:
                    break
            shelf_n = tr * tpr  # final after binary-walk

        # Decor-side rescale: aim for total approx budget. Forklift /
        # worker keep their explicit count (LLM intent like "3 forklifts").
        # Overshoot 1.4x so the conflict pass + enforce_budget trim land
        # near target rather than under it.
        decor_quota = max(0, object_budget - shelf_n - forklift_count - worker_count)
        # Overshoot scales with budget -- larger budgets eat more cross-class
        # overlap losses in the conflict pass, so we need more headroom.
        overshoot = 1.4 + min(0.6, object_budget * 0.005)
        target_decor = int(decor_quota * overshoot)
        current_decor = pallet_count + box_count + drum_count
        if current_decor > 0 and target_decor > 0:
            scale = target_decor / current_decor
            pallet_count = max(1, int(round(pallet_count * scale)))
            box_count    = max(1, int(round(box_count * scale)))
            drum_count   = max(1, int(round(drum_count * scale)))

    # 1. Shelf 阵列
    rows, per_row = _derive_shelf_grid(
        shelf_density, room_w_m, room_l_m, alley_width_m
    )
    row_pitch = SHELF_DEPTH_M + alley_width_m
    aisle_centerlines, y_start, _ = _compute_aisle_centerlines(rows, alley_width_m)
    row_x_extent = (per_row - 1) * SHELF_WIDTH_M
    x_start = -row_x_extent / 2

    for r in range(rows):
        y_row = y_start + r * row_pitch
        spawns.extend(grid_points(
            ctx,
            asset_name="shelf",
            x_count=per_row,
            y_count=1,
            x_pitch=SHELF_WIDTH_M,
            y_pitch=row_pitch,
            x_origin=x_start,
            y_origin=y_row,
            chaos_jitter_m=0.15,  # shelf 排列允许小幅 chaos
        ))

    # 2. Forklift 沿 aisle 中线
    if forklift_count > 0:
        if aisle_centerlines:
            for i in range(forklift_count):
                ay = ctx.rng.choice(aisle_centerlines)
                ax = ctx.rng.uniform(x_start, x_start + row_x_extent)
                yaw = ctx.rng.choice([0, 90, 180, 270])
                spawns.append(SpawnRequest("forklift", ax, ay, 0.0, yaw))
        else:
            # 单行 shelf, 没 aisle, forklift 放 row 前/后
            for i in range(forklift_count):
                ay = (y_start - row_pitch / 2) if i % 2 == 0 else (
                    y_start + rows * row_pitch - SHELF_DEPTH_M / 2 + row_pitch / 2
                )
                ax = ctx.rng.uniform(x_start, x_start + row_x_extent)
                yaw = ctx.rng.choice([0, 90, 180, 270])
                spawns.append(SpawnRequest("forklift", ax, ay, 0.0, yaw))

    # 3. Pallet 贴 shelf 边
    for _ in range(pallet_count):
        r = ctx.rng.randrange(max(1, rows))
        y_row = y_start + r * row_pitch
        y_p = y_row + (SHELF_DEPTH_M / 2 + 0.5) * ctx.rng.choice([-1, 1])
        x_p = ctx.rng.uniform(x_start - 0.5, x_start + row_x_extent + 0.5)
        yaw = ctx.rng.choice([0, 90])
        spawns.append(SpawnRequest("pallet", x_p, y_p, 0.0, yaw))

    # 4. Box 房间地面随机散落
    spawns.extend(random_scatter(
        ctx,
        asset_name="box",
        count=box_count,
        x_min=-room_w_m / 2 + 0.5,
        x_max=room_w_m / 2 - 0.5,
        y_min=-room_l_m / 2 + 0.5,
        y_max=room_l_m / 2 - 0.5,
        min_distance_m=0.4,
        yaw_random=True,
    ))

    # 5. Drum 靠墙
    spawns.extend(wall_hug(
        ctx,
        asset_name="drum",
        count=drum_count,
        room_w_m=room_w_m,
        room_l_m=room_l_m,
        inset_m=0.8,
    ))

    # 6. Worker 在 aisle 中线 (避开 forklift)
    if worker_count > 0 and aisle_centerlines:
        forklift_positions = [(s.x, s.y) for s in spawns if s.asset_name == "forklift"]
        worker_candidates = []
        for _ in range(worker_count):
            for _try in range(20):
                wy = ctx.rng.choice(aisle_centerlines)
                wx = ctx.rng.uniform(x_start, x_start + row_x_extent)
                if all(
                    (wx - fx) ** 2 + (wy - fy) ** 2 > WORKER_AVOID_FORKLIFT_M ** 2
                    for fx, fy in forklift_positions
                ):
                    break
            yaw = ctx.rng.choice([0, 90, 180, 270])
            worker_candidates.append(SpawnRequest("worker", wx, wy, 0.0, yaw))
        spawns.extend(worker_candidates)

    # 7. Lighting (ceiling 灯网格)
    spawns.extend(spawn_ceiling_lights(
        ctx,
        lighting_preset=lighting_preset,
        room_w_m=room_w_m,
        room_l_m=room_l_m,
        ceiling_h_m=4.0,
        grid_x=max(3, int(room_w_m / 4)),  # 每 4m 一盏灯
        grid_y=max(3, int(room_l_m / 4)),
    ))

    # 8. Global conflict pass -- drop cross-class overlaps before budget cut.
    spawns, _overlap_drop = enforce_no_overlap(spawns)

    # 9. Budget enforcement -- random trim of non-structural decor.
    spawns, _budget_drop = enforce_budget(spawns, object_budget, ctx.rng)

    return LayoutResult(spawns=spawns)


# ---------------------------------------------------------------------------
# 单参数 setter 辅助 (chat tool "set_shelf_density(0.9)" 不 regenerate 全套,
# 只是更新一个参数, 下次 generate 时生效)
# ---------------------------------------------------------------------------


def parse_lighting_preset(value: str | int) -> int:
    """LLM 可能给 "sodium" / "cool_white" / "mixed" string, 转 int.

    contract §1.1: lighting_preset 是 enum string, 但底层存 int 编码.
    """
    if isinstance(value, int):
        return max(0, min(2, value))
    if isinstance(value, str):
        v = value.strip().lower()
        mapping = {
            "warehouse_sodium": 0, "sodium": 0, "0": 0,
            "cool_white": 1, "cool": 1, "white": 1, "1": 1,
            "mixed": 2, "mix": 2, "2": 2,
        }
        return mapping.get(v, 0)
    return 0
