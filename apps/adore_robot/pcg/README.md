# adore_robot.pcg — App-side Procedural Content Generation

UE PCG 框架在我们 app 端的等价物。chat → DeepSeek tool_call → 本模块输出
SpawnRequest 列表 → xiaoxu runner 通过 MCP SceneTools 落地 UE 场景。

## Why not UE PCG?

UE 5.8 PCG 我们调试 1 天卡在 Surface vs Volume 数据流, 5.8 Preview 文档碎片化。
App 端 Python 算法**等价 95% 能力**, 调试更直接, 控制全栈, 跨 UE 版本零风险。

完整对比见 `apps/adore_robot/docs/pcg_app_vs_engine_evaluation.md` (xiaohuan 2026-05-22)。

## 架构

```
pcg/
├── __init__.py         # 统一 export
├── base.py             # SpawnRequest / LayoutResult / PCGContext
├── primitives.py       # 复用算法 (grid / scatter / wall_hug / line / avoid)
├── lighting.py         # lighting_preset enum → ceiling 灯网格
├── warehouse.py        # warehouse 13 参数 layout (主用)
├── living_room.py      # living_room 简化版 (v0 mesh fallback)
├── industrial_corner.py # industrial_corner 简化版
└── README.md           # 本文件
```

## Quick start

```python
from apps.adore_robot.pcg import generate_warehouse

result = generate_warehouse(
    shelf_density=0.9,
    forklift_count=3,
    worker_count=2,
    room_w_m=20.0,
    room_l_m=30.0,
    seed=42,
    lighting_preset=2,  # mixed
    chaos=0.5,
    rotation_jitter_deg=20,
)

print(f"Total: {result.total}, by asset: {result.by_asset}")

# 转 xiaoxu runner spawn 字典列表
calls = result.to_mcp_calls(anchor_x_cm=0, anchor_y_cm=0)
for call in calls:
    # call = {"tool": "spawn_object", "args": {"asset_name": ..., "x": cm, ...}}
    mcp_client.execute_tool(call["tool"], call["args"])
```

## 13 PCG 等价参数 (warehouse)

跟 `apps/adore_robot/docs/pcg_param_contract.md` §1.0 + §1.1 一致。

### Tier 1: 必备 7 个 (chat 主控)

| 参数 | 类型 | 范围 | 默认 | chat 演示 |
|---|---|---|---|---|
| `shelf_density` | float | 0.2-1.0 | 0.7 | "shelf 密度 0.9" |
| `alley_width_m` | float | 1.5-4.0 | 2.4 | "通道留 3 米" |
| `forklift_count` | int | 0-5 | 1 | "加 3 台叉车" |
| `worker_count` | int | 0-8 | 0 | "加 2 个工人" |
| `room_w_m` | float | 8-40 | 18 | "房间宽 25 米" |
| `room_l_m` | float | 8-60 | 28 | "房间长 35 米" |
| `seed` | int | 0-9999 | 0 | "seed 换 42" |

### Tier 2: 炫酷 6 个

| 参数 | 类型 | 范围 | 默认 | chat 演示 |
|---|---|---|---|---|
| `pallet_count` | int | 0-50 | 8 | "10 个木托盘" |
| `box_count` | int | 0-30 | 5 | "撒 15 个箱子" |
| `drum_count` | int | 0-20 | 3 | "靠墙加 5 个桶" |
| `lighting_preset` | int | 0/1/2 | 0 | "切冷色调" "混光" |
| `rotation_jitter_deg` | float | 0-180 | 15 | "全部歪一点" "排整齐" |
| `chaos` | float | 0.0-1.0 | 0.3 | "更乱一点" "干净点" |

## Lighting preset (warehouse)

| preset | 名字 | 视觉 |
|---|---|---|
| 0 | warehouse_sodium | 钠灯黄 ~2200K |
| 1 | cool_white | 冷白 ~6500K |
| 2 | mixed | sodium 主基底 + 20% cool 散布 |

asset_name 输出: `light_sodium` / `light_cool_white` (mixed 时混合)。
xiaoxu asset_registry 需要 map 这两个 asset_name 到具体 UE Light Blueprint。

## 跟 xiaoxu runner 集成

xiaoxu 的 `apps/adore_robot/demo/runner.py` 现有 `dispatch_warehouse` 调用本模块:

```python
# demo/runner.py 改成调本模块
from apps.adore_robot.pcg import generate_warehouse

def dispatch_warehouse(args: dict) -> dict:
    result = generate_warehouse(**args)
    calls = result.to_mcp_calls(
        anchor_x_cm=demo_origin_x,
        anchor_y_cm=demo_origin_y,
    )
    spawned = []
    for call in calls:
        h = mcp_client.spawn_object(**call["args"])
        spawned.append(h)
    return {"spawned": spawned, "total": result.total, "by_asset": result.by_asset}
```

P1 给 xiaoxu 在 `agents/unreal/SHARED.md` 落了任务。

## 跟 PCG contract 的关系

| 文件 | 角色 |
|---|---|
| `apps/adore_robot/docs/pcg_param_contract.md` | 参数 contract (语义 / range / 校验) |
| `apps/adore_robot/pcg/` (本模块) | **算法实现**, contract 落地 |
| `apps/adore_robot/demo/demo_tools.py` | LLM tool schema (派生自 contract) |
| `apps/adore_robot/demo/prompts.py` | LLM system prompt + few-shot |
| `apps/adore_robot/demo/runner.py` | tool_call dispatcher (xiaoxu) |

## 测试 (无 UE 也能跑)

```bash
cd captureAIshi
python -c "
from apps.adore_robot.pcg import generate_warehouse
r = generate_warehouse(shelf_density=0.9, forklift_count=3, seed=42)
print(f'Spawned {r.total} objects:')
for k, v in r.by_asset.items():
    print(f'  {k}: {v}')
print(f'First 5 positions:')
for s in r.spawns[:5]:
    print(f'  {s.asset_name} @ ({s.x:.1f}, {s.y:.1f}, {s.z:.1f}) yaw={s.yaw_deg:.0f}')
"
```

## 设计原则

1. **纯函数**: 同 seed → 同 output, 没全局状态
2. **不直接调 MCP**: 输出 SpawnRequest list, 调用方决定怎么 spawn
3. **米单位**: 所有坐标米, 转 cm 在 `to_mcp_calls()` 边界
4. **chaos master 控制**: chaos=0 整齐, chaos=1 最乱
5. **room 约束**: 算法自适应 room_w/l_m, 不溢出

## 后续 v0.4+ 扩展

- [ ] Match-and-set 风格 mesh variation (跟 contract §1 各场景 prop_variety 对齐)
- [ ] Hierarchical density layers (近处密远处疏)
- [ ] 真 Megascans 资产到位后, asset_registry.py 单行换 mesh
- [ ] MRQ 集成 (foundry 路线): SpawnRequest → ObjectId tag → Cosmos Transfer 训练数据
