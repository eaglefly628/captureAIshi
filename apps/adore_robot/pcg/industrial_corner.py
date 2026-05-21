"""Industrial corner procgen — grammar 风格 (简化).

参数 contract: pcg_param_contract.md §1.3 (7 params + 4 common).

布局逻辑 (grammar 规则):
1. 大型机器 (machine_count, 1-4) 靠墙
2. 工作台居中
3. 工具板挂在墙面 (toolboard_density 控密度)
4. 顶部管道沿天花板走 (pipe_complexity 控复杂度)
5. 散落 crate / drum 在角落 / 地面
6. 地面油渍贴花 (oil_stain_amount, 视觉效果, 实际是 decal mesh)

v0 演示 mesh fallback: machine→forklift, workbench→shelf, crate→box.
v1 真 Fab IndustrialMachines pack 到位后换.
"""

from __future__ import annotations

from .base import PCGContext, SpawnRequest, LayoutResult
from .primitives import wall_hug, random_scatter
from .lighting import spawn_ceiling_lights


def generate_industrial_corner(
    # 必备
    machine_count: int = 2,
    toolboard_density: float = 0.7,
    pipe_complexity: int = 3,
    oil_stain_amount: float = 0.25,
    crate_count: int = 3,
    room_w_m: float = 8.0,
    room_l_m: float = 8.0,
    seed: int = 0,
    # Tier 2
    lighting_preset: int = 0,  # 0=indoor_tungsten, 1=halogen_spot, 2=mixed
    chaos: float = 0.3,
) -> LayoutResult:
    """生成 industrial corner layout (简化版)."""
    ctx = PCGContext(seed=seed, chaos=max(0.0, min(1.0, chaos)))
    spawns: list[SpawnRequest] = []

    # 1. 大型机器靠墙
    machine_count = max(0, min(4, machine_count))
    for i in range(machine_count):
        # 4 面墙之一, 距墙 1.0m
        side = i % 4
        if side == 0:
            mx, my, yaw = -room_w_m / 2 + 1.0, ctx.rng.uniform(-room_l_m / 4, room_l_m / 4), 90
        elif side == 1:
            mx, my, yaw = room_w_m / 2 - 1.0, ctx.rng.uniform(-room_l_m / 4, room_l_m / 4), 270
        elif side == 2:
            mx, my, yaw = ctx.rng.uniform(-room_w_m / 4, room_w_m / 4), -room_l_m / 2 + 1.0, 0
        else:
            mx, my, yaw = ctx.rng.uniform(-room_w_m / 4, room_w_m / 4), room_l_m / 2 - 1.0, 180
        spawns.append(SpawnRequest("machine", mx, my, 0.0, yaw))

    # 2. 工作台 居中
    spawns.append(SpawnRequest("workbench", 0.0, 0.0, 0.0))

    # 3. 工具板 挂墙 (toolboard_density 控数量)
    toolboard_count = max(1, int(toolboard_density * 4))
    spawns.extend(wall_hug(
        ctx,
        asset_name="toolboard",
        count=toolboard_count,
        room_w_m=room_w_m,
        room_l_m=room_l_m,
        inset_m=0.3,
        z=1.5,  # 挂墙 1.5m 高
    ))

    # 4. 顶部管道 (pipe_complexity 控数量)
    pipe_count = max(1, pipe_complexity * 2)
    for i in range(pipe_count):
        # 管道沿 X 或 Y 方向
        axis = ctx.rng.choice(["x", "y"])
        if axis == "x":
            py = ctx.rng.uniform(-room_l_m / 2 + 0.5, room_l_m / 2 - 0.5)
            spawns.append(SpawnRequest(
                "pipe", 0.0, py, 3.5, yaw_deg=0, scale=room_w_m / 3.0
            ))
        else:
            px = ctx.rng.uniform(-room_w_m / 2 + 0.5, room_w_m / 2 - 0.5)
            spawns.append(SpawnRequest(
                "pipe", px, 0.0, 3.5, yaw_deg=90, scale=room_l_m / 3.0
            ))

    # 5. 散落 crate
    spawns.extend(random_scatter(
        ctx,
        asset_name="crate",
        count=crate_count,
        x_min=-room_w_m / 2 + 0.8,
        x_max=room_w_m / 2 - 0.8,
        y_min=-room_l_m / 2 + 0.8,
        y_max=room_l_m / 2 - 0.8,
        min_distance_m=0.6,
    ))

    # 6. Cable reel + conduit 散布
    cable_count = max(0, int(pipe_complexity * 0.8))
    spawns.extend(random_scatter(
        ctx,
        asset_name="cable_reel",
        count=cable_count,
        x_min=-room_w_m / 2 + 0.5,
        x_max=room_w_m / 2 - 0.5,
        y_min=-room_l_m / 2 + 0.5,
        y_max=room_l_m / 2 - 0.5,
        min_distance_m=1.0,
    ))

    # 7. 油渍 decal (作为 spawn actor, 大 area 平铺)
    stain_count = max(0, int(oil_stain_amount * 10))
    spawns.extend(random_scatter(
        ctx,
        asset_name="oil_stain_decal",
        count=stain_count,
        x_min=-room_w_m / 2 + 0.5,
        x_max=room_w_m / 2 - 0.5,
        y_min=-room_l_m / 2 + 0.5,
        y_max=room_l_m / 2 - 0.5,
        min_distance_m=0.8,
    ))

    # 8. Lighting (halogen / tungsten)
    spawns.extend(spawn_ceiling_lights(
        ctx,
        lighting_preset=lighting_preset,
        room_w_m=room_w_m,
        room_l_m=room_l_m,
        ceiling_h_m=4.0,
        grid_x=3,
        grid_y=3,
    ))

    return LayoutResult(spawns=spawns)
