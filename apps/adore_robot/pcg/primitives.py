"""Reusable procgen primitives: grid / scatter / cluster / wall-hug.

跨场景共用 (warehouse / living / industrial 都能调). 保持算法纯函数风格,
所有 RNG 行为通过 PCGContext 传入, 不要 import random.random() 直接用.
"""

from __future__ import annotations

from .base import PCGContext, SpawnRequest


def grid_points(
    ctx: PCGContext,
    asset_name: str,
    x_count: int,
    y_count: int,
    x_pitch: float,
    y_pitch: float,
    x_origin: float = 0.0,
    y_origin: float = 0.0,
    z: float = 0.0,
    base_yaw: float = 0.0,
    chaos_jitter_m: float = 0.2,
) -> list[SpawnRequest]:
    """规则网格散点. 例: shelf 阵列.

    每个点应用 chaos jitter + yaw jitter (按 ctx).
    """
    spawns = []
    for ix in range(x_count):
        for iy in range(y_count):
            x = x_origin + ix * x_pitch
            y = y_origin + iy * y_pitch
            dx, dy = ctx.chaos_jitter_xy(chaos_jitter_m)
            spawns.append(SpawnRequest(
                asset_name,
                x + dx,
                y + dy,
                z,
                yaw_deg=ctx.jittered_yaw(base_yaw),
            ))
    return spawns


def random_scatter(
    ctx: PCGContext,
    asset_name: str,
    count: int,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    z: float = 0.0,
    min_distance_m: float = 0.0,
    max_retries: int = 20,
    yaw_random: bool = True,
) -> list[SpawnRequest]:
    """房间内随机散点 + 可选 self-pruning (避免重叠).

    min_distance_m > 0 时, 每个新点尝试 max_retries 次找无冲突位置, 失败就放过.
    """
    spawns = []
    placed: list[tuple[float, float]] = []
    for _ in range(count):
        for _try in range(max_retries):
            x = ctx.rng.uniform(x_min, x_max)
            y = ctx.rng.uniform(y_min, y_max)
            if min_distance_m <= 0 or all(
                (x - px) ** 2 + (y - py) ** 2 >= min_distance_m ** 2
                for px, py in placed
            ):
                break
        placed.append((x, y))
        yaw = ctx.rng.uniform(0, 360) if yaw_random else ctx.jittered_yaw(0)
        spawns.append(SpawnRequest(asset_name, x, y, z, yaw))
    return spawns


def wall_hug(
    ctx: PCGContext,
    asset_name: str,
    count: int,
    room_w_m: float,
    room_l_m: float,
    inset_m: float = 0.8,
    z: float = 0.0,
) -> list[SpawnRequest]:
    """靠墙散点 (drum / 工业 prop 风格).

    随机 4 面墙之一, 距离墙 inset_m, 沿墙长方向随机位置.
    """
    spawns = []
    for _ in range(count):
        side = ctx.rng.choice(["xneg", "xpos", "yneg", "ypos"])
        if side == "xneg":
            x = -room_w_m / 2 + inset_m
            y = ctx.rng.uniform(-room_l_m / 2 + 1, room_l_m / 2 - 1)
            yaw = 90  # facing +X (away from wall)
        elif side == "xpos":
            x = room_w_m / 2 - inset_m
            y = ctx.rng.uniform(-room_l_m / 2 + 1, room_l_m / 2 - 1)
            yaw = 270
        elif side == "yneg":
            x = ctx.rng.uniform(-room_w_m / 2 + 1, room_w_m / 2 - 1)
            y = -room_l_m / 2 + inset_m
            yaw = 0
        else:  # ypos
            x = ctx.rng.uniform(-room_w_m / 2 + 1, room_w_m / 2 - 1)
            y = room_l_m / 2 - inset_m
            yaw = 180
        spawns.append(SpawnRequest(asset_name, x, y, z, yaw_deg=yaw))
    return spawns


def line_points(
    ctx: PCGContext,
    asset_name: str,
    count: int,
    x_start: float,
    y_start: float,
    x_end: float,
    y_end: float,
    z: float = 0.0,
    yaw_random_90: bool = True,
) -> list[SpawnRequest]:
    """沿直线散 N 个点 (e.g. forklift 沿 aisle).

    yaw_random_90: True = 随机 0/90/180/270 度 (整齐感)
                  False = 沿线方向
    """
    spawns = []
    for i in range(count):
        t = (i + 0.5) / count if count > 0 else 0.5
        x = x_start + (x_end - x_start) * t
        y = y_start + (y_end - y_start) * t
        yaw = ctx.rng.choice([0, 90, 180, 270]) if yaw_random_90 else 0.0
        spawns.append(SpawnRequest(asset_name, x, y, z, yaw))
    return spawns


def avoid_actors(
    ctx: PCGContext,
    candidates: list[SpawnRequest],
    blocked_positions: list[tuple[float, float]],
    min_distance_m: float = 2.0,
) -> list[SpawnRequest]:
    """过滤掉离 blocked_positions 太近的 candidates.

    e.g. worker 不能离 forklift 太近.
    """
    out = []
    for c in candidates:
        if all(
            (c.x - bx) ** 2 + (c.y - by) ** 2 >= min_distance_m ** 2
            for bx, by in blocked_positions
        ):
            out.append(c)
    return out
