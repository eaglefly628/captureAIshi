# PG_Warehouse Build Cheatsheet (single-page reference)

> Audience: 用户 在 UE5.8 Editor 内搭 `PG_Warehouse.uasset` (任务 A) 时随手翻。
> 配套全 spec: `pg_warehouse_graph_design.md` (290 行). 本页 = 速查精简版.
> Date: 2026-05-19, **v0.4.0 精简版更新 2026-05-20**.
>
> ⚠️ **v0.4.0 演示交付只暴露 7 个 Graph Parameter** (xiaoxu 派 P0):
> `shelf_density / alley_width_m / forklift_count / worker_count /
> room_w_m / room_l_m / seed`. 下面 11-param 表中第 4 / 5 / 6 / 10 行
> (prop_variety / pallet_load_factor / lighting_preset / ceiling_h_m)
> **本期不暴露**, 接 v1.1. graph 内可用固定常量替代。
> Default `room_w_m=18` / `room_l_m=28` (warehouse 演示尺度);
> ceiling 固定 4m, lighting 固定 sodium 预设。

---

## ★ 11 Graph Parameter (UAdoreRobotPCGParams 类内 UPROPERTY)

7 个 warehouse-only (contract §1.1) + 4 个 common (contract §1.0). 这些是
**精确名字 + UE 类型**, 后面 LLM / asset_registry / MCP set_properties 一字
不差靠它们对齐. 不要任何拼写偏差.

| # | Graph Param 名 | UE 类型 | 默认 | 范围 | 接入 Stage | v0.4 暴露? |
|---|---|---|---|---|---|---|
| 1 | `shelf_density` | `float` | 0.7 | 0.2-1.0 | §3 Shelf → `Density Filter` (threshold = 1 - shelf_density) | ✅ |
| 2 | `alley_width_m` | `float` | 2.4 | 1.5-4.0 | §2 BSP → Subdivide cell width + walkway band | ✅ |
| 3 | `forklift_count` | `int32` | 1 | 0-5 | §4 Forklift → `Density Filter` rate | ✅ |
| 4 | `prop_variety` | `int32` | 3 | 1-5 | §5 Props → `Switch by Index` mesh count | ❌ v1.1 (用常量 3) |
| 5 | `pallet_load_factor` | `float` | 0.6 | 0.0-1.0 | §3.5 nested → rack surface `Density Filter` | ❌ v1.1 (砍 §3.5) |
| 6 | `lighting_preset` | `FName` (or enum) | `"warehouse_sodium"` | sodium/cool_white/mixed | §6 Lighting → `Switch by Enum` | ❌ v1.1 (固定 sodium) |
| 7 | `seed` | `int32` | 0 | **0-9999** (v0.4) | 全 Stage 的 `Self Pruning` / `Density Filter` 的 `Random Stream Seed` | ✅ |
| 8 | `room_w_m` | `float` | **18** (v0.4) | 8-40 | §1 Bounds X | ✅ |
| 9 | `room_l_m` | `float` | **28** (v0.4) | 8-60 | §1 Bounds Y | ✅ |
| 10 | `ceiling_h_m` | `float` | 4 | 3-9 | §1 Bounds Z + §6 light hang = `ceiling_h_m - 0.2` | ❌ v1.1 (固定 4m) |
| 11 | `worker_count` | `int32` | 0 | 0-8 | §7 Worker → `Density Filter` rate | ✅ |

⚠️ **`lighting_preset` 类型选择**:
- 简单走 `FName`: graph 内 `Compare String` 三路分支
- 严谨走 `enum`: 需在 plugin 内定义 `UENUM EAdoreLightingWarehouse { WarehouseSodium / CoolWhite / Mixed }` 后引用. v0 演示用 FName 即可, 不阻塞.

---

## ★ 8 Stage 节点拓扑速查

每 Stage 一行核心节点链. 详细 wiring 看 design doc 同名 §.

| Stage | 核心节点链 |
|---|---|
| §1 Param decode | `Get Param Data` → 11 个 `Attribute Get` → `Make Vector` (room_w/l/ceil_h) → `Create Box Volume` (Stage 2 / 6 / 8 用) |
| §2 BSP+aisle | `Bounds (Surface)` → `Surface Sampler` (Cell Size = alley_width_m + 1.2) → `Subdivide` X 轴 → `Even/Odd Filter` 切 shelf row / alley row |
| §3 Shelf | shelf row → `Surface Sampler` (1.6m sub-cell) → `Density Filter` (threshold = 1 - shelf_density) → `Self Pruning` (1.4m) → `Attribute Math` (scale Random) → `Static Mesh Spawner` (5 SKU) |
| §3.5 Pallet nested | `Get Spawned Actor Bounds` (rack 0.4m + 1.2m levels) → `Surface Sampler` (0.8m) → `Density Filter` (1 - pallet_load_factor) → `SM Spawner` (3 variants) |
| §4 Forklift | alley centerline → `Subdivide` Y (N=forklift_count) → `Attribute Math` (Yaw Random 4-direction) → `Self Pruning` (4m) → `SM Spawner` (3 SKU) |
| §5 Props | room floor leftover → `Surface Sampler` (0.6m, Looseness 0.7) → `Density Filter` (0.85) → `Self Pruning` (0.5m) → `Switch by Index` (mesh_index = Random(0..prop_variety-1)) → `SM Spawner` |
| §6 Lighting | ceiling plane (z = ceiling_h_m - 0.2) → `Surface Sampler` → `Switch by Enum` (lighting_preset) → 3 分支各自 `Subdivide` (8x8 / 10x10) + `Spawn Actor BP_MegaLight_*` |
| §7 Worker | alley centerline - forklift_buffer → `Surface Sampler` (1.2m, Looseness 0.8) → `Density Filter` (1 - worker_count/8) → `Self Pruning` (1.5m) → `Spawn Actor BP_BlueCollarWorker` |
| §8 Output | 隐式收集所有 Spawner / Spawn Actor 产物 (PCG framework 自动 HISM/ISM 实例化) |

---

## ★ 关键坑 (cheatsheet `常见坑` + xiaoxuan peer review)

| 坑 | 解 |
|---|---|
| **HISM 跟 Nanite 互斥** | Nanite shelf/forklift 走 **ISM**, 非 Nanite (pallet/box/drum) 走 HISM. `Static Mesh Spawner` 上 toggle `Use Instance Mesh Mode` 切换 |
| **Translucent material 不挂 Nanite mesh** | 渲染时不可见. Glass/liquid 改用 `Opacity Masked` (alpha test) BlendMode |
| **`Generate on Demand` 不刷新** | Actor outliner 右键 → "Force Regenerate"; Python: `PCGComponent.Generate(true)` |
| **Get Param Data 节点空白** | Graph 必须挂 `UAdoreRobotPCGParams_Warehouse` UCLASS 作 OverrideParams (`PCG Settings` panel → `Graph Parameters` 配 UCLASS 引用) |
| **Surface Sampler 不出点** | 检查 `Use Bounds 2D=true` + 输入是 Surface 表示而非 Volume |
| **Self Pruning 全删** | `Min Distance` 太大. shelf 用 1.4m, pallet 用 0.4m, prop 用 0.5m |
| **Switch by Enum 在 UE5.8 PCG 节点名 5.7 略不同** | 5.8 实际叫 `Switch by Enum (Selector)` 或 `Pick by Enum`. 装机后 `right-click in graph` → 搜 `switch` 确认实际名 |

---

## ★ 7 步落地 checklist (从 0 到能 `set_properties` 写)

1. `Content/PCG/Warehouse/PG_Warehouse_v0` 新建 PCGGraph asset
2. graph 顶端挂 `UAdoreRobotPCGParams_Warehouse` UCLASS 为 OverrideParams (xiaoxu 在 `AdoreRobotPCG` plugin 内 UCLASS 定义 11 个 UPROPERTY EditAnywhere)
3. 按 §1-§8 八个 stage 拉节点 (建议每 stage 一个 Subgraph asset: `PG_Warehouse_Stage1...8`, 主图引用 8 个 subgraph)
4. shelf / pallet / forklift / box / drum / worker / light actor 资产路径配在 plugin `UDataAsset` (方便 C 任务换 Fab pack)
5. `Generate on Demand` 跑一次, PCG profiler 看 instance ~2500 上下
6. Nanite/translucent 抽查 (contract §5 Asset Checklist)
7. 验证: 在 chat 输 "shelf 密度 0.9" → 看货架变密; "加 2 台叉车" → 看 2 个叉车上线

---

## ★ 验证套路 (Step 7 详细)

在 `apps/adore_robot/main.py` `/api/chat` 输:

```
"shelf_density 调到 0.9"
```

期望背后:
- LLM (DeepSeek) emit `update_scene({"shelf_density": 0.9})` tool_call
- server 端 `_try_mcp_relay` → MCP `ObjectTools.set_properties(graphInstance.parametersOverrides.parameters, '{"shelf_density":0.9}')`
- PCG `Generate(true)` 重 sim
- UE viewport 看到 shelf 变密

如果没反应, 按顺序 debug:
1. `/api/mcp/status` 看 4 toolset 是否 loaded
2. `/api/mcp/probe_graph` dump 当前 `graphInstance.parametersOverrides.parameters` keys -- 是否含 `shelf_density`
3. 浏览器 dev console 看 `update_scene` tool_call payload 真值
4. UE Editor Output Log 看 `PCG Component Generate` 触发日志

---

## ★ 参考路径

- 完整 design doc (290 行): `apps/adore_robot/docs/pg_warehouse_graph_design.md`
- Contract (参数语义/range/校验源头): `apps/adore_robot/docs/pcg_param_contract.md` §1.0 + §1.1
- MCP 能力报告: `apps/adore_robot/docs/ue58_mcp_capability_report.md`
- Demo v0 契约 (spawn/delete/move + layout 生成): `apps/adore_robot/docs/demo_v0_simplified_contract.md`
- PCG 节点速查: `agents/pcg/refs/cheatsheet_pcg_graph.md`
