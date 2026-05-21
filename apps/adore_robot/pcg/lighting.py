"""Lighting preset → ceiling light grid spawn helpers.

lighting_preset enum:
- 0 = warehouse_sodium (黄色钠灯, 仓库经典)
- 1 = cool_white (冷白工业灯)
- 2 = mixed (sodium 主基底 + cool_white 散布)

每个 preset 输出一个 light actor list, 摆 ceiling 上.
"""

from __future__ import annotations

from .base import PCGContext, SpawnRequest

# preset 编号 → asset_name 映射 (xiaoxu asset_registry 需配对应 light BP / mesh)
LIGHT_ASSET_BY_PRESET: dict[int, str] = {
    0: "light_sodium",       # 黄色钠灯 ~2200K
    1: "light_cool_white",   # 冷白 ~6500K
    2: "light_sodium",       # mixed 主基底 sodium
}

# preset 2 (mixed) 额外撒的 accent lights
MIXED_ACCENT_ASSET = "light_cool_white"
MIXED_ACCENT_RATE = 0.2  # 20% 的位置加 accent


def spawn_ceiling_lights(
    ctx: PCGContext,
    lighting_preset: int,
    room_w_m: float,
    room_l_m: float,
    ceiling_h_m: float = 4.0,
    grid_x: int = 5,
    grid_y: int = 5,
) -> list[SpawnRequest]:
    """ceiling 平面规则网格摆灯.

    preset 0/1: 全部用对应 asset
    preset 2 (mixed): 主基底 sodium + 20% 位置加 cool_white accent
    """
    spawns: list[SpawnRequest] = []
    if lighting_preset not in LIGHT_ASSET_BY_PRESET:
        lighting_preset = 0  # fallback
    primary_asset = LIGHT_ASSET_BY_PRESET[lighting_preset]
    z = ceiling_h_m - 0.2  # 灯具悬挂在天花板下方 20cm

    for ix in range(grid_x):
        for iy in range(grid_y):
            lx = -room_w_m / 2 + (ix + 0.5) * room_w_m / grid_x
            ly = -room_l_m / 2 + (iy + 0.5) * room_l_m / grid_y
            spawns.append(SpawnRequest(primary_asset, lx, ly, z))

            # preset 2: 部分位置加 accent
            if lighting_preset == 2 and ctx.rng.random() < MIXED_ACCENT_RATE:
                # accent 在 primary 旁边偏移一点
                spawns.append(SpawnRequest(
                    MIXED_ACCENT_ASSET,
                    lx + ctx.rng.uniform(-0.5, 0.5),
                    ly + ctx.rng.uniform(-0.5, 0.5),
                    z,
                ))
    return spawns


def preset_name(lighting_preset: int) -> str:
    """LLM-friendly name for the preset (for tool call rationale)."""
    return {0: "warehouse_sodium", 1: "cool_white", 2: "mixed"}.get(
        lighting_preset, "warehouse_sodium"
    )
