"""Shared data types for procgen layouts.

SpawnRequest: 单个物件的 spawn 指令 (asset_name + 位置 + 朝向 + scale).
LayoutResult: 一次 generate 的全部 spawn 列表 + 统计.
PCGContext: 共享上下文 (seed/chaos/jitter), 控制确定性 + 随机性.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class SpawnRequest:
    """A single object spawn instruction.

    asset_name: 'shelf' / 'forklift' / 'pallet' / 'box' / 'drum' / 'worker' /
                'light_sodium' / 'light_cool_white' / 'light_mixed' /
                living/industrial 场景的 'sofa' / 'machine' 等
    x, y, z: 米, scene-local (相对 BP_DemoOrigin), Y-up RHS
    yaw_deg: 度数, 0=+X, 90=+Y
    scale: 等比 scale 倍数 (默认 1.0)
    """

    asset_name: str
    x: float
    y: float
    z: float = 0.0
    yaw_deg: float = 0.0
    scale: float = 1.0


@dataclass
class PCGContext:
    """Shared run context: seed-driven RNG + chaos/jitter knobs.

    任何算法应该用 self.rng 而不是 random.random(), 保证 seed 可复现。
    """

    seed: int = 0
    chaos: float = 0.3
    rotation_jitter_deg: float = 15.0
    rng: random.Random = field(init=False)

    def __post_init__(self):
        self.rng = random.Random(self.seed)

    def jittered_yaw(self, base_yaw: float = 0.0) -> float:
        """Apply rotation_jitter_deg around base_yaw.

        rotation_jitter_deg = 0 → 返 base_yaw (整齐)
        rotation_jitter_deg = 180 → 完全乱转
        """
        if self.rotation_jitter_deg <= 0:
            return base_yaw
        return base_yaw + self.rng.uniform(
            -self.rotation_jitter_deg, self.rotation_jitter_deg
        )

    def chaos_jitter_xy(self, amount: float = 0.2) -> tuple[float, float]:
        """Per-point position chaos jitter.

        chaos = 0 → (0, 0) 无 jitter
        chaos = 1 → 最大 amount 米的位移
        """
        if self.chaos <= 0:
            return (0.0, 0.0)
        return (
            self.rng.uniform(-self.chaos * amount, self.chaos * amount),
            self.rng.uniform(-self.chaos * amount, self.chaos * amount),
        )


@dataclass
class LayoutResult:
    """Output of one generate run.

    spawns: 所有 SpawnRequest, 按生成顺序
    total: 总数 (自动计算)
    by_asset: {asset_name: count} (自动计算)
    """

    spawns: list[SpawnRequest]
    total: int = field(init=False)
    by_asset: dict[str, int] = field(init=False)

    def __post_init__(self):
        self.total = len(self.spawns)
        self.by_asset = {}
        for s in self.spawns:
            self.by_asset[s.asset_name] = self.by_asset.get(s.asset_name, 0) + 1

    def to_mcp_calls(self, anchor_x_cm: float = 0, anchor_y_cm: float = 0,
                     anchor_z_cm: float = 0) -> list[dict]:
        """Convert to xiaoxu-runner-compatible MCP spawn call dicts.

        anchor_*_cm: BP_DemoOrigin world position (cm), spawn 坐标会加这个偏移.
        """
        calls = []
        for s in self.spawns:
            calls.append({
                "tool": "spawn_object",
                "args": {
                    "asset_name": s.asset_name,
                    # 米 → cm 转换
                    "x": anchor_x_cm + s.x * 100,
                    "y": anchor_y_cm + s.y * 100,
                    "z": anchor_z_cm + s.z * 100,
                    "yaw_deg": s.yaw_deg,
                    "scale": s.scale,
                },
            })
        return calls
