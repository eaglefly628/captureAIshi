# PG_Warehouse_v0 PCG Graph Design

> **2026-05-20 v0.4.0 演示精简版调整 (xiaoxu via 用户)**:
> v0 演示交付**只暴露 7 个 Graph Parameter** (不是本 doc 原 11 个):
> `shelf_density / alley_width_m / forklift_count / worker_count /
> room_w_m / room_l_m / seed`。**暂时砍掉** `prop_variety` /
> `pallet_load_factor` / `lighting_preset` / `ceiling_h_m`, v1.1 接。
> 默认值: `room_w_m=18 / room_l_m=28` (warehouse 演示尺度比 50x50 紧凑)。
> Mesh 全部用 `/Engine/BasicShapes/Cube` 占位 (Material Instance 区分颜色:
> shelf=灰 / forklift=黄 / pallet=棕 / box=红 / drum=蓝 / worker=绿 /
> lamp=白), 真 Megascans Industrial pack 等用户演示后 task D 替换。
> 详见 `agents/pcg/SHARED.md` v0.4.0 P0 xiaohuan 回复节。
> **本 doc §1-§9 拓扑仍 valid**, 只是 §3.5 nested pallet (依赖
> `pallet_load_factor`) / §6 lighting (依赖 `lighting_preset` /
> `ceiling_h_m`) 在 v0.4 砍掉; §1 Bounds Z 用固定值 4m 替代;
> §5 prop 分支用固定 1 SKU (cube) 替代 variety 选择。
> **关联 cheatsheet**: `pg_warehouse_build_cheatsheet.md` 已对齐 v0.4 精简版。

Audience: xiaoxu（在 UE 5.8 Editor 里把这份 spec 机械翻译成
`PG_Warehouse_v0.uasset`）+ xiaohuan 自己（落 v1 graph 时核对节点拓扑）。

**Target asset**: `apps/adore_robot/unreal_projects/AdoreRobot/Content/PCG/Warehouse/PG_Warehouse.uasset`
**Target map**: `apps/adore_robot/unreal_projects/AdoreRobot/Content/Maps/RobotDemo_PCG_v0.umap`

Source contract: `apps/adore_robot/docs/pcg_param_contract.md` §1.1 (7 warehouse
params) + §1.0 common (4 params: `room_w_m / room_l_m / ceiling_h_m /
worker_count` —— 这四个目前只在 `demo/prompts.py` + `llm/keyword.py`，
contract §1 待 xiaohuan 收编，见本 doc §10 drift note）。

UE5.8 PCG capability baseline: `apps/adore_robot/docs/ue58_pcg_notes_xiaohuan.md`。

---

## §0 全图概览

```
         [Scene Bounds Box Volume]
                   │
            ┌──────┴──────┐
            │             │
   [Get Param Data] ──> 11 个 Attribute Get 分支
            │
            ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  Stage 1  Param decoding + room rect 计算                    │
   │  Stage 2  BSP + 通道切分（alley walkway 用 Difference 减出） │
   │  Stage 3  Shelves on cell rows (+ pallets nested)            │
   │  Stage 4  Forklifts placed along alley centerlines           │
   │  Stage 5  Props (boxes/drums/clutter) scatter                │
   │  Stage 6  Lighting (Mega Lights actor switch on enum)        │
   │  Stage 7  Workers (humanoid) scatter in alleys               │
   │  Stage 8  Output collection -> HISM/ISM groups               │
   └──────────────────────────────────────────────────────────────┘
                   │
                   ▼
       Saved/MovieRenders/<variant>/ (cook stage by MRQ)
```

Instance budget: ~2500 (per `warehouse_v0.json` `target_instance_count`)，
全在 HISM 区间。**Nanite shelf/forklift/box 必须走 ISM + Nanite mesh，
不要 HISM**（cheatsheet §常见坑 #2）。

---

## §1 全参数 -> 节点接入点（11 项）

参数全部来自 `UAdoreRobotPCGParams` UCLASS（xiaoxu 写在 `AdoreRobotPCG`
plugin）。Graph 顶部一个 `Get Param Data` 节点，下面 11 个 `Attribute
Get` 分支：

| Param | 类型 | 接入 Stage / 节点 | 消费方式 |
|---|---|---|---|
| `room_w_m` | float | Stage 1 → `Bounds` (X size) | 限定 BSP volume X 跨度 |
| `room_l_m` | float | Stage 1 → `Bounds` (Y size) | 限定 BSP volume Y 跨度 |
| `ceiling_h_m` | float | Stage 1 → `Bounds` (Z size) + Stage 6 light hang height | 灯具悬挂位 = `ceiling_h_m - 0.2` |
| `shelf_density` | float (0.2-1.0) | Stage 3 → `Density Filter` (threshold = 1 - shelf_density) | 越大 -> 越多 cell 留 shelf |
| `alley_width_m` | float (1.5-4.0) | Stage 2 → `Subdivide` cell width + Difference walkway band 宽度 | 决定通道宽 |
| `forklift_count` | int (0-5) | Stage 4 → `Density Filter` (rate = count / max_count) | 沿通道分布 |
| `prop_variety` | int (1-5) | Stage 5 → `Switch / Index` 选 mesh SKU 数 | 限制散落物种类 |
| `pallet_load_factor` | float (0.0-1.0) | Stage 3.5 nested → `Density Filter` on shelf rack surface | 货架格位填充率 |
| `lighting_preset` | enum | Stage 6 → `Switch by Enum` 选 light pattern | sodium / cool_white / mixed |
| `worker_count` | int (0-8) | Stage 7 → `Density Filter` (rate = count / max_count) on alley center | humanoid 散点 |
| `seed` | int (uint32) | Stage 2/3/4/5/7 → 全部 `Self Pruning` / `Density Filter` 的 `Random Stream Seed` | 全局可复现 |

---

## §2 Stage 1 — Param decoding + Bounds

```
[Get Param Data]
  │
  ├─ Attribute Get "room_w_m"  ──┐
  ├─ Attribute Get "room_l_m"  ──┤   [Make Vector] (X=w, Y=l, Z=ceil)
  ├─ Attribute Get "ceiling_h_m" ┘            │
  │                                            ▼
  └─ ... (其他 8 个 Attribute Get 透传到后面 Stage)
                                  [Create Box Volume / Bounds Source]
                                              │
                                              ▼
                                  Stage 2 输入 (Surface 表示 floor 平面)
```

- **节点**: `Get Param Data` → 11 个 `Attribute Get` (string key 直接照
  contract §1.1 + §1.0)。`Make Vector` 组装 size。`Create Box Volume` 输出
  Stage 2 / 6 / 8 都要用的 scene bounds。
- **校验** (graph 内): 如果 `room_w_m * room_l_m < 64 m²` 警告 "too small,
  may not fit shelves"。`Print` 节点出 warning，不阻塞 generate。

---

## §3 Stage 2 — BSP + 通道切分

策略：把 floor 当作 X 方向 N 行的 strip 阵列，每行宽度 = `alley_width_m
+ shelf_rack_depth`（rack 固定 1.2m），alley 居中 0.5x。Subdivide 出
cell rows，再用 Difference 把 alley band 减掉，剩下 cell 给 shelves。

```
[Bounds (from Stage 1)] (Surface representation)
       │
       ▼
[Surface Sampler] (Looseness=0.0, Bounds 2D, Cell Size = alley_width_m + 1.2)
       │
       ▼
[Subdivide] (Axis=X, N = floor(room_w_m / cell_size))
       │
       ├─────────────────────┐
       ▼                     ▼
   [Filter "even"]      [Filter "odd"]
   = shelf rows         = alley centerline rows
       │                     │
       ▼                     ▼
   to Stage 3            to Stage 4 (forklift / worker spawn)
```

- **节点**: `Surface Sampler` + `Subdivide` (with `Even/Odd Index` filter
  via `Attribute Math` 比较 `$Index % 2`)
- alley band 默认居中宽度 = `alley_width_m`；shelf row 宽度 = cell_size -
  `alley_width_m` = 1.2m（rack depth）。
- **隐式**：row count = `floor(room_w_m / cell_size)` (Stage 1 计算，
  Stage 2 用)。

---

## §4 Stage 3 — Shelves (+ nested pallets)

```
shelf rows (from Stage 2)
       │
       ▼
[Surface Sampler] (Looseness=0.05, Cell Size = 1.6m sub-cells)
       │
       ▼
[Density Filter] (Threshold = 1.0 - shelf_density)   ← param 接入
       │
       ▼
[Self Pruning] (MinDistance = 1.4m, seed = $seed)
       │
       ▼
[Attribute Math] (Set scale = Random(0.95, 1.05, seed))
       │
       ▼
[Static Mesh Spawner] (mesh = Pick from 5 shelf SKUs by Random(seed))
       │
       │ === nested sub-graph: pallets on shelf rack ===
       ▼
[Get Spawned Actor Bounds] (per-shelf, rack surface 2 levels: 0.4m, 1.2m)
       │
       ▼
[Surface Sampler] on rack surface (Cell Size = 0.8m = pallet footprint)
       │
       ▼
[Density Filter] (Threshold = 1.0 - pallet_load_factor)   ← param 接入
       │
       ▼
[Static Mesh Spawner] (pallet mesh, 1 of 3 variants by Random(seed))
```

- **节点**: 嵌套两层 (shelf 顶层 + pallet 子层)。第二层用 `Get Spawned
  Actor Bounds` 拿到 shelf rack surface，再 sample。
- **HISM/ISM**: shelf 是 Nanite mesh -> 选 ISM。Pallet 非 Nanite -> HISM
  OK。
- **资产源**: `Quixel_Industrial` pack 的 shelf (5 SKU) + pallet (3 variants)。

---

## §5 Stage 4 — Forklifts

```
alley centerline points (from Stage 2)
       │
       ▼
[Subdivide] (along Y axis, N = forklift_count, evenly spaced)   ← param 接入
       │
       ▼
[Attribute Math] (rotate Yaw = Random(0/90/180/270 deg, seed))
       │
       ▼
[Self Pruning] (MinDistance = 4m, seed)
       │
       ▼
[Static Mesh Spawner] (Pick from 3 forklift SKUs)
```

- **节点**: 把 alley 中线点用 `Subdivide` 切成 `forklift_count` 个等距
  位置，不到一辆就 1 个，最大 5。
- **edge case**: `forklift_count == 0` → Density Filter rate=0 (
  `Density Filter` with threshold=1.0) 全过滤掉。

---

## §6 Stage 5 — Props (boxes/drums/clutter)

```
alley + cell-corner points (from Stage 2 + leftover Surface Sampler)
       │
       ▼
[Surface Sampler] (Looseness=0.7, Cell Size = 0.6m)
       │
       ▼
[Density Filter] (Threshold = 0.85, base scatter rate)
       │
       ▼
[Self Pruning] (MinDistance = 0.5m, seed)
       │
       ▼
[Switch by Index] (mesh_index = Random(0..prop_variety-1, seed))   ← param 接入
       │
       ├─> box mesh
       ├─> drum mesh
       └─> (extra SKUs up to 5)
       │
       ▼
[Static Mesh Spawner]
```

- **节点**: `Switch by Index` 限定 mesh SKU 数。`prop_variety=1` → 全是
  box; `=5` → 全 SKU 都进。
- **资产源**: `box`, `drum`, `pallet (空)`, `cardboard_stack`, `crate` (5
  种)。

---

## §7 Stage 6 — Lighting

`lighting_preset` enum 三选一，每个 preset 是一个固定的 light pattern
（位置 + intensity + color）。用 `Switch by Enum` 节点根据 param 选择
分支。

```
scene bounds (from Stage 1)
       │
       ▼
[Surface Sampler] on ceiling plane (z = ceiling_h_m - 0.2)
       │
       ▼
[Switch by Enum] (lighting_preset)        ← param 接入
       │
       ├─ "warehouse_sodium":
       │     [Subdivide] (grid 8x8) → [Spawn Actor BP_MegaLight_Sodium]
       │     intensity=8000 lm, color_temp=2200K
       │
       ├─ "cool_white":
       │     [Subdivide] (grid 10x10) → [Spawn Actor BP_MegaLight_CoolWhite]
       │     intensity=6500 lm, color_temp=5000K
       │
       └─ "mixed":
             [Subdivide] (8x8) sodium 主基底
             + [Density Filter] (rate=0.2) 散布 cool_white 高光
```

- **节点**: `Switch by Enum` 三路输出，每路独立 Subdivide + Spawn Actor。
- **资产源**: `BP_MegaLight_*` Blueprint actor（xiaoxu 在 `AdoreRobotPCG`
  plugin 里建）。Mega Lights 5.8 production-ready。
- **依赖 `ceiling_h_m`**: light 悬挂 z = `ceiling_h_m - 0.2`。

---

## §8 Stage 7 — Workers

```
alley centerline points (Stage 2, 不被 forklift 占用的)
       │
       ▼
[Difference] (减去 forklift 位置 + 1.5m buffer)
       │
       ▼
[Surface Sampler] (Looseness=0.8, Cell Size = 1.2m)
       │
       ▼
[Density Filter] (Threshold = 1.0 - worker_count / max_count)   ← param 接入
       │
       ▼
[Self Pruning] (MinDistance = 1.5m, seed)
       │
       ▼
[Attribute Math] (random Yaw + pose 选 idle/walking/inspecting)
       │
       ▼
[Spawn Actor BP_BlueCollarWorker]
```

- **节点**: 在不与 forklift 冲突的 alley 段散点。max_count = 8（contract
  §1.0 range 上限）。
- **资产源**: `BP_BlueCollarWorker` 含若干 idle/walking/inspecting 动画
  pose（xiaoxu 在 plugin 里建 actor）。
- **重要**: humanoid 不进 robot 路径——`urdf_robot.spawn_xyz` (默认
  `[25, 25, 0]`) 周围 2m 半径用 `Difference` 减掉。

---

## §9 Stage 8 — Output collection

把每个 Static Mesh Spawner / Spawn Actor 的输出聚合到一个 final
collection（PCG 自动管理 HISM/ISM 实例化），交给 MRQ cook 时一并烤进
streaming proxy。

```
[Stage 3 shelf]     ┐
[Stage 3.5 pallet]  ┤
[Stage 4 forklift]  ├──> implicit PCG Component output (HISM/ISM groups
[Stage 5 props]     ┤        per static mesh asset, auto by engine)
[Stage 6 lights]    ┤        Spawn Actors stay as individual actors
[Stage 7 workers]   ┘        in the level.
```

无显式 output node——PCG framework 自动收集所有 Spawner / Spawn Actor
的产物。

---

## §10 Drift Note — common params 收编

contract §1 当前只列三场景的 scene-specific 参数（warehouse 7 + living
7 + industrial 7 = 21）。但 xiaoxu 在 commit `d45a3af3` 给 LLM 多暴露了
4 个 **common to ALL scenes** 参数（room_w_m / room_l_m / ceiling_h_m /
worker_count），只落到了 `demo/prompts.py` 的 SYSTEM_PROMPT 和
`llm/keyword.py` RANGES，**没进 contract §1**。

本 graph design 已把这 4 个 common 参数都接进节点（§1 表里 4 行）。
**Action for xiaohuan 下轮**: contract §1 加 §1.0 "Common to all scenes"
小节，把这 4 个 params 收编成 source of truth，消掉 demo 与 contract 的
drift。当前以本 doc + `demo/prompts.py` 为事实表，contract 滞后。

---

## §11 Xiaoxu 落地 checklist (UE 5.8 Editor 里)

1. `Content/PCG/Warehouse/PG_Warehouse_v0` 新建 PCGGraph asset
2. graph 顶端挂 `UAdoreRobotPCGParams_Warehouse` UCLASS 为 OverrideParams
   (UCLASS 内 UPROPERTY EditAnywhere 名字对齐 contract §1.1 + §1.0)
3. 按本 doc §2-§9 八个 stage 拉节点；每个 stage 一个 Subgraph 收编，
   主图引用 8 个 Subgraph asset (`PG_Warehouse_Stage1`...`PG_Warehouse_Stage8`)
4. shelf / pallet / forklift / box / drum / worker / light actor 资产路径
   配在 plugin 内置 `DataAsset`，graph 引用 DataAsset 而不是 hardcoded
   path（方便换 SKU pack）
5. 跑一次 `Generate on Demand`，instance count 看 PCG profiler 是否在
   ~2500 上下
6. Nanite/translucent 抽查 (contract §5 Asset Checklist)
7. 验证 `set_shelf_density(0.9)` → re-generate 后货架确实变密；
   `set_forklift_count(3)` → 3 台叉车上线

---

## §12 后续 scene graph 扩展

`PG_LivingRoom_v0` + `PG_IndustrialCorner_v0` 沿用本 doc 的 Stage 1 + 7
+ 8 模式（room bounds 解码 / worker scatter / output collection），其余
Stage 按各自 contract §1.2 / §1.3 的 7 参数定制：

- LivingRoom: Stage 2 graph+WFC 模块化，Stage 3 sofa anchor，Stage 4 表面散物
- IndustrialCorner: Stage 2 grammar (机器 anchor)，Stage 3 工具板挂载，
  Stage 4 管道贴墙

那两份 design doc 等本 PG_Warehouse_v0 在 UE Editor 里跑通后再写
（先证 v0 可行，再 generalize 节点 pattern）。
