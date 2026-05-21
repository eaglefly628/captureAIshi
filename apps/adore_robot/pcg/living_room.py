"""Living room procgen — graph + WFC 风格 (简化).

参数 contract: pcg_param_contract.md §1.2 (7 params + 4 common).

布局逻辑:
1. 沙发 (1-2 个) 靠最长墙
2. 茶几在沙发正前方 1.2m
3. 边几 (chair / clutter_small) 沙发两侧
4. 装饰 (plant / floor_lamp) 角落
5. 地毯 (rug) 沙发前方
6. 灯具 ceiling (lighting_preset 影响色温)

v0 演示 mesh 可以 fallback 到 warehouse 那一套占位 (box, drum, worker), v1 再换真 Fab 资产.
"""

from __future__ import annotations

from .base import PCGContext, SpawnRequest, LayoutResult
from .primitives import random_scatter
from .lighting import spawn_ceiling_lights


def generate_living_room(
    # 必备
    furniture_density: float = 0.55,
    decor_variety: int = 5,
    rug_present: bool = True,
    sofa_style: int = 0,  # 0=sectional, 1=loveseat, 2=chesterfield
    clutter_level: float = 0.3,
    room_w_m: float = 5.0,
    room_l_m: float = 7.0,
    seed: int = 0,
    # Tier 2
    lighting_preset: int = 0,  # 0=indoor_tungsten, 1=cool_daylight, 2=evening_warm
    chaos: float = 0.3,
) -> LayoutResult:
    """生成 living room layout (简化版).

    v0 演示用 fallback mesh: sofa→shelf, coffee_table→box, plant→drum
    v1 真 Fab MetaSofa pack 到位后, asset_registry 一行换.
    """
    ctx = PCGContext(seed=seed, chaos=max(0.0, min(1.0, chaos)))
    spawns: list[SpawnRequest] = []

    # 1. 沙发 (1-2 个) 靠最长墙
    sofa_count = 2 if sofa_style != 1 and furniture_density > 0.6 else 1
    long_wall_y = room_l_m / 2 - 0.7  # 长墙 +Y 侧
    for i in range(sofa_count):
        sx = (i - (sofa_count - 1) / 2) * 1.5
        spawns.append(SpawnRequest(
            "sofa",
            sx,
            long_wall_y,
            0.0,
            yaw_deg=180,  # 面向 -Y (房间中心)
            scale=1.2 if sofa_style == 2 else 1.0,  # chesterfield 大一些
        ))

    # 2. 茶几 in front of sofa
    spawns.append(SpawnRequest(
        "coffee_table",
        0.0,
        long_wall_y - 1.5,  # 沙发前 1.5m
        0.0,
    ))

    # 3. 边几 (chairs)
    chair_count = max(0, int(furniture_density * 4) - 2)
    for i in range(chair_count):
        cx = ctx.rng.choice([-room_w_m / 2 + 0.7, room_w_m / 2 - 0.7])
        cy = ctx.rng.uniform(-room_l_m / 2 + 1, room_l_m / 2 - 1)
        spawns.append(SpawnRequest(
            "chair",
            cx,
            cy,
            0.0,
            yaw_deg=90 if cx < 0 else 270,
        ))

    # 4. 装饰 (plant + floor_lamp 散在角落)
    decor_assets = ["plant", "floor_lamp", "table_lamp", "wall_art", "bookshelf"]
    for i in range(min(decor_variety, len(decor_assets))):
        # 角落分布
        corner = i % 4
        if corner == 0:
            x, y = -room_w_m / 2 + 0.6, -room_l_m / 2 + 0.6
        elif corner == 1:
            x, y = room_w_m / 2 - 0.6, -room_l_m / 2 + 0.6
        elif corner == 2:
            x, y = -room_w_m / 2 + 0.6, room_l_m / 2 - 0.6
        else:
            x, y = room_w_m / 2 - 0.6, room_l_m / 2 - 0.6
        spawns.append(SpawnRequest(decor_assets[i], x, y, 0.0))

    # 5. 地毯
    if rug_present:
        spawns.append(SpawnRequest(
            "rug",
            0.0,
            long_wall_y - 1.5,  # 茶几下方
            0.0,
            scale=1.5,
        ))

    # 6. Clutter (按 clutter_level 散小物)
    clutter_count = int(clutter_level * 8)
    spawns.extend(random_scatter(
        ctx,
        asset_name="clutter_small",
        count=clutter_count,
        x_min=-room_w_m / 2 + 0.3,
        x_max=room_w_m / 2 - 0.3,
        y_min=-room_l_m / 2 + 0.3,
        y_max=room_l_m / 2 - 0.3,
        min_distance_m=0.3,
    ))

    # 7. Lighting
    spawns.extend(spawn_ceiling_lights(
        ctx,
        lighting_preset=lighting_preset,
        room_w_m=room_w_m,
        room_l_m=room_l_m,
        ceiling_h_m=3.0,
        grid_x=2,
        grid_y=2,
    ))

    return LayoutResult(spawns=spawns)
