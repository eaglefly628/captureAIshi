# PCG Parameter Contract (xiaohuan)

Audience: xiaoxu (batch UI 表单 + tool input_schema 派生) + LLM (NL→delta
prompt schema 来源)。Date: 2026-05-15.

本 doc 是 **PCG graph 暴露给外部世界的所有参数 + 规则**。
xiaoxu 的 batch_scene_gen_architecture.md §2.3 + §3 直接消费这里。

---

## §1 公开参数表 (三场景)

每参数列：`name | type | range | default | 物理含义`。
所有 name 为 plain ASCII snake_case，**直接当 PCG OverrideParams key
用**（见 §2）。enum 值同样 ASCII。

### 1.1 Warehouse (`scene_id=warehouse`)

| 参数 | 类型 | 范围 | 默认 | 物理含义 |
|---|---|---|---|---|
| `shelf_density` | float | 0.2 - 1.0 | 0.7 | 货架在 BSP 切分 cell 内的填充率 |
| `alley_width_m` | float | 1.5 - 4.0 | 2.4 | 主通道（叉车通过）宽度，米 |
| `forklift_count` | int | 0 - 5 | 1 | 叉车摆放数量 |
| `prop_variety` | int | 1 - 5 | 3 | 货物种类抽取数（pallet/box/drum/...）|
| `pallet_load_factor` | float | 0.0 - 1.0 | 0.6 | 货架格位上 pallet 装载率 |
| `lighting_preset` | enum | `warehouse_sodium` / `cool_white` / `mixed` | `warehouse_sodium` | 灯光氛围 |
| `seed` | int | any (uint32 cast) | 0 | 随机种子，固定可复现 |

**校验规则**:
- `alley_width_m * 2 < size_m[0]`（场景至少能切出一条主通道+两侧货架）
- `forklift_count == 0` 时，`alley_width_m` 取下界即可（视觉差异减小）
- `shelf_density >= 0.9` 且 `pallet_load_factor >= 0.9` 时警告 "near-saturated, may exceed 5K instance budget"

**隐式参数（不暴露给 LLM）**:
- BSP 切分最小 cell 边长（固定 1.5m，避开过细货架排）
- Surface Sampler 在 cell 上点距 jitter (0.05m)
- Self Pruning 重叠阈值 (0.3m)

---

### 1.2 Living Room (`scene_id=living_room`)

| 参数 | 类型 | 范围 | 默认 | 物理含义 |
|---|---|---|---|---|
| `furniture_density` | float | 0.3 - 0.9 | 0.55 | 大件家具占地面积比 |
| `sofa_style` | enum | `sectional` / `loveseat` / `chesterfield` | `sectional` | 主沙发风格 |
| `decor_variety` | int | 2 - 8 | 5 | 装饰品种类数（lamp/plant/art/...）|
| `clutter_level` | float | 0.0 - 1.0 | 0.3 | 桌面/地面散落小物程度 |
| `rug_present` | bool | true / false | true | 地毯有/无 |
| `lighting_preset` | enum | `indoor_tungsten` / `cool_daylight` / `evening_warm` | `indoor_tungsten` | 灯光氛围 |
| `seed` | int | any (uint32 cast) | 0 | 随机种子 |

**校验规则**:
- `furniture_density >= 0.85` 且 `clutter_level >= 0.8` 时降级一个为
  上一档（房间会塞不下，物理穿模风险）
- `decor_variety > 6` 时自动开启 `rug_present=true`（视觉一致）

**隐式参数**:
- 沙发朝向贴最大墙面 (graph-WFC 约束)
- 茶几放沙发正前方 (距离 0.8-1.2m 抖动)
- TV/书架二选一靠对墙

---

### 1.3 Industrial Corner (`scene_id=industrial_corner`)

| 参数 | 类型 | 范围 | 默认 | 物理含义 |
|---|---|---|---|---|
| `machine_count` | int | 1 - 4 | 2 | 大型机器数（lathe/press/cnc/grinder）|
| `toolboard_density` | float | 0.3 - 1.0 | 0.7 | 工具板上挂物密度 |
| `pipe_complexity` | int | 1 - 5 | 3 | 顶部管道 + 墙面线缆复杂度档 |
| `oil_stain_amount` | float | 0.0 - 0.8 | 0.25 | 地面油渍/磨损贴花覆盖率 |
| `crate_count` | int | 0 - 6 | 3 | 散落工具箱/木板箱数 |
| `lighting_preset` | enum | `indoor_tungsten` / `halogen_spot` / `mixed` | `indoor_tungsten` | 灯光氛围 |
| `seed` | int | any (uint32 cast) | 0 | 随机种子 |

**校验规则**:
- `machine_count == 4` 时 `crate_count` clamp 到 ≤ 3（空间冲突）
- `pipe_complexity == 5` 时强制 `lighting_preset != halogen_spot`
  （halogen 高对比 + 密集管道阴影过暗）

**隐式参数**:
- 机器靠墙 grammar 规则（不允许中央摆放）
- 工具板挂墙高度 (1.1 - 1.6m)
- 管道 z-clearance >= 2.4m（机器人通过）

---

## §2 OverrideParams Key 命名约定

### 规则

1. **Key = 参数表中 `name` 列的字面值**。Plain ASCII snake_case，无前缀，
   无命名空间，无 GUID 映射。
2. enum 值用 string literal，**不要** int code（`"warehouse_sodium"`,
   非 `0`）。
3. bool 用 Python `True/False` 在 Python 侧、`bool` UPROPERTY 在 UE 侧。
4. **每个 scene 一份独立的参数集**（key 不跨场景复用），即使 `seed` 在
   三场景都叫 `seed` 也只是巧合。Python 端 set 时先确认 PCGComponent
   挂的是哪个 graph。

### Python 端调用（占位，等 xiaoxu 5.8 装机后回填真名）

```python
# Placeholder API — confirm method names against 5.8 PythonStub diff.
# Source: 5.7 forum threads (capabilities §1 [6], [7]).
import unreal

actor = unreal.EditorLevelLibrary.get_selected_level_actors()[0]
comp = actor.get_component_by_class(unreal.PCGComponent)

# Hypothesis A (most common in 5.7 examples):
comp.set_graph_parameter("shelf_density", 0.8)
comp.set_graph_parameter("alley_width_m", 2.4)
comp.set_graph_parameter("lighting_preset", "warehouse_sodium")
comp.set_graph_parameter("seed", 12345)
comp.generate()  # trigger regen

# Hypothesis B (if A method name doesn't exist in 5.8):
# comp.override_param("shelf_density", 0.8)  # alt naming
```

**xiaoxu 装机后第一件事**：`help(unreal.PCGComponent)` dump，把真实方法
名回填本 §2 + 删除 placeholder note。**在那之前 contract 内容仍然有效**
（key 名 + value 类型不依赖 method 名）。

### PCG graph 内读取

每个 graph 用 `Get Param Data` 节点拿 PCGComponent 的 OverrideParams，
再 split 出对应字段：

```
Get Param Data  ->  Attribute Get (shelf_density)  ->  Density Filter
                ->  Attribute Get (alley_width_m)  ->  Subdivide.cellSize
                ->  Attribute Get (lighting_preset) -> Switch (light asset)
                ->  Attribute Get (seed)           ->  Self Pruning.seed
```

**xiaoxu 需要 implement** 一个 `UAdoreRobotPCGParams` UCLASS（在
`AdoreRobotPCG` plugin），UPROPERTY EditAnywhere 对应每个公开参数。
graph 引用这个 class 作为 OverrideParams 类型。

---

## §3 资产 Pack 索引

LLM 看 §3 才不会瞎指挥（"warehouse 里加一辆汽车"被拒）。每条列出场景
能用的 mesh 类型（不是具体 asset 路径，是**语义类别**）。

### 3.1 Warehouse — `Quixel_Industrial` pack

可用 mesh 类别（**仅限**）：
- `shelf`（货架，5 种 SKU）
- `forklift`（叉车，3 款车型）
- `pallet`（木质托盘）
- `box`（纸箱，多尺寸）
- `drum`（圆桶）
- `concrete_floor` / `wall_panel`（环境，BSP 派生）
- `sodium_lamp` / `cool_lamp`（顶灯，Mega Lights actor）

**没有**：car、human、tree、furniture（沙发桌椅）、food、animal。

### 3.2 Living Room — `Fab_MetaSofa` + `Megascans_DecorPack`

可用 mesh 类别（**仅限**）：
- `sofa`（3 种 style）
- `coffee_table` / `side_table`
- `chair`（扶手椅 / 餐椅）
- `floor_lamp` / `table_lamp` / `ceiling_pendant`
- `rug`
- `plant`（盆栽，5 种）
- `bookshelf` / `tv_unit`（二选一）
- `wall_art`（挂画）
- `clutter_small`（书、马克杯、遥控器、靠垫等）

**没有**：industrial machine、forklift、shelf（仓储意义）、vehicle、人。

### 3.3 Industrial Corner — `Fab_IndustrialMachines` + `Custom_Toolboard`

可用 mesh 类别（**仅限**）：
- `machine`（lathe / press / cnc / grinder，4 款 SKU）
- `workbench`
- `toolboard`（工具墙，自带子物件 hook）
- `tool_small`（扳手、卡尺、钳子，挂工具板用）
- `pipe`（顶部管道，3 种直径）
- `cable_reel`（电缆盘）
- `crate`（木板箱）
- `conduit`（线槽）
- `fume_hood`（通风罩）

**没有**：家具、车辆、人、植物、整面货架（那是 warehouse 的）。

### 3.4 LLM 收到无法满足请求时

LLM 不要 silently 修改 spec。**必须** 在 tool call rationale 里写明：
- 哪个请求被拒绝
- 为什么（不在 asset pack）
- 给出场景内可替代项（如果有语义最近的）

例：用户要 "warehouse 加几个人"，LLM 应返回 `pcg_params` 无人相关字段
（contract 里也没有 human 参数），`rationale: "human asset not in
Quixel_Industrial pack; declined. Closest available: increase
forklift_count for occupancy hint."`

---

## §4 NL Prompt Template

xiaoxu 的 Anthropic SDK 调用（batch_scene_gen_architecture §3）走这三
段 cache-controlled system prompt。

### 4.1 System prompt 段 1 — Schema

```
You are a PCG scene parameter editor for a UE5 robotic data foundry.
The scene currently being edited is one of three types: warehouse,
living_room, industrial_corner. Each type has a fixed parameter
contract (see below). Your job is to translate user natural-language
edits into a strict JSON delta to merge into the current scene_spec.

Parameters per scene:

[paste §1 tables here, name/type/range/default/含义 verbatim]

Rules:
- Only emit keys that appear in the contract for the active scene.
- Never invent new parameter names.
- Clamp out-of-range values to nearest valid edge, and explain in
  rationale.
- enum values are case-sensitive string literals, exactly as listed.
```

### 4.2 System prompt 段 2 — Few-Shot

5 对 user_text -> delta，覆盖单参数 / 多参数 / 超 range / 资产不在 pack
/ 隐式参数禁止覆盖：

```
Example 1 — single param:
  User: "warehouse 货架密一点"
  Delta: {
    "pcg_params": {"shelf_density": 0.9},
    "rationale": "User asked for denser shelves; bumped shelf_density
                  from default 0.7 to 0.9 (max 1.0)."
  }

Example 2 — multi-param cascade:
  User: "客厅暖一点, 沙发大一些, 多放些装饰"
  Delta: {
    "pcg_params": {
      "lighting_preset": "evening_warm",
      "sofa_style": "chesterfield",
      "decor_variety": 7
    },
    "rationale": "Warm tone -> evening_warm preset; larger sofa ->
                  chesterfield; more decor -> decor_variety 7."
  }

Example 3 — out-of-range clamp:
  User: "加 100 台叉车"
  Delta: {
    "pcg_params": {"forklift_count": 5},
    "rationale": "Requested 100 forklifts; contract caps at 5.
                  Clamped to 5 (max)."
  }

Example 4 — asset not in pack:
  User: "客厅里停一辆车"
  Delta: {
    "pcg_params": {},
    "rationale": "Car not in living_room asset pack (Fab_MetaSofa /
                  Megascans_DecorPack). Declined. Closest in-pack
                  alternative: none meaningful for a car request."
  }

Example 5 — implicit param attempt (refuse):
  User: "把货架间距加大到 5 米"
  Delta: {
    "pcg_params": {"alley_width_m": 4.0},
    "rationale": "alley_width_m max is 4.0 (clamped). Note: shelf
                  cell spacing is an implicit param and is not
                  user-tunable; only alley_width_m affects spacing
                  visibly."
  }
```

### 4.3 System prompt 段 3 — Asset Index

`[paste §3 sections for active scene only — 减 token]`

### 4.4 失败处理 (LLM 必须遵守)

| 情况 | LLM 行为 |
|---|---|
| out-of-range value | clamp + rationale 说明 |
| 不在 contract 的 key | 忽略该 key，rationale 说明 "key X not in contract for scene Y" |
| 不在 asset pack 的请求 | 不修改任何 param，rationale refuse + 提替代项 |
| 隐式参数请求 | 忽略，rationale 说明 "X is implicit and not user-tunable" |
| 用户文本模糊 (e.g. "好看点") | 返回 `pcg_params: {}` + rationale "request ambiguous; please specify a parameter" |

server 端额外 validate（不只是信 LLM）：
- value 在 range 内（出 range -> 报错 reject job）
- key 在 active scene contract 内（不在 -> 报错）
- enum value 在枚举里（不在 -> 报错）

---

## §5 PCG Asset Checklist (peer review 来源汇总)

任何打算挂 PCG graph 的 mesh / material 必须过这张表：

| 检查项 | 不通过的后果 | 来源 |
|---|---|---|
| **Nanite mesh + Translucent material 不共存** | 渲染时不可见 | xiaoxu, source: capabilities §4 |
| Translucent 需求改用 opacity-masked | 视觉等价、Nanite 兼容 | 同上 |
| Mega Lights actor 优先于 spot/point | 5.8 production-ready，real-time GI 更好 | capabilities §4 |
| Substrate material slot（5.8 default） | 旧 material domain 项目迁移成本高 | capabilities §3 |
| ASCII 路径 + ASCII metadata key | 跨 OS / CI 兼容 | `apps/adore_robot/CLAUDE.md` |
| Instance count < 5K per HISM | 超出走 Mass Entity（xiaoxu 提供 setup） | `agents/pcg/refs/cheatsheet_pcg_graph.md` |

---

## §6 Thumbnail Viewpoint 约定

每场景的 scene_spec JSON 必带 `thumbnail_camera` 节，NL agent loop /
batch UI gallery 都看这个角度判断 "fit user request?"。固定的好处：
同场景跨 variant 视角一致，便于 LLM diff。

格式（米，世界坐标，Y-up RHS，落到 `configs/scenes/<scene>_v0.json`）：

```json
"thumbnail_camera": {
  "pos": [x, y, z],
  "look_at": [x, y, z],
  "fov_v_deg": 60,
  "near_far_m": [0.1, 100]
}
```

三场景具体值见对应 `<scene>_v0.json`。

---

## §7 与 xiaoxu 的接口契约（小结）

xiaoxu 那边消费本 doc 的具体点：

1. **batch UI 表单字段** ← §1 表三场景，每行一个 input。enum 出 dropdown，
   float/int 出 slider with min/max，bool 出 checkbox。
2. **Tool input_schema (Anthropic)** ← §1 表派生 `additionalProperties:
   false` strict JSON schema。
3. **Server-side validate** ← §1 range + §4.4 失败处理。
4. **NL system prompt 三段** ← §4.1/4.2/4.3。
5. **UPCGSettings UCLASS UPROPERTY 集合** ← §1 表，类型一对一。
6. **OverrideParams set 方法真名** ← xiaoxu 装 5.8 后回填 §2。

下游对齐：
- **xiaoxuan**：本 doc 不直接给他，但 §5 Substrate + Nanite + Mega
  Lights 约束影响他 MRQ 输出的 normal/depth pass 一致性。
- **老白决策点**：LLM 模型选定 (Claude 4.6 Sonnet)、UI 形态 (Web)，
  都在 batch_scene_gen_architecture §4 里已建议，本 doc 不再重复。
