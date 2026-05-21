# Demo v0 Simplified Contract — Spawn / Delete / Move

Audience: xiaoxu (MCP server-side wiring) + LLM prompt 维护者 + 客户演示
脚本 author。Date: 2026-05-19。

## §0 范围 (v0 demo only)

这是**第一次正式客户演示**的简化契约。**不是** PG_Warehouse 完整 PCG
参数化路线（那条在 `pcg_param_contract.md` §1 + `pg_warehouse_graph_design.md`，
等装机 + 资产到位后接力）。v0 演示只证明一件事：

> **聊天框里说话 → UE Editor 里看到改动**

为此**只需要 3 个动作**：

| Op | 用户语义示例 | LLM tool call |
|---|---|---|
| `spawn_object` | "再加一个叉车" / "中间放个货架" | spawn at given xyz + yaw |
| `delete_object` | "删掉那个箱子" / "把刚才那个叉车去掉" | destroy by actor handle |
| `modify_location` | "把叉车往左挪 2 米" / "搬到 (5, 10)" | translate to new xyz |

外加一个辅助 query（**不** 算用户动作，LLM agent loop 用）：

| Op | 用途 |
|---|---|
| `list_objects` | LLM 拿当前 actor 清单解析指代关系（"那个叉车"对应哪个 handle）|

旋转/缩放/材质替换/PCG 参数都**不进 v0**。客户问 "可以转方向吗" 答 "v1
接，今天展示 spawn/delete/move"。

---

## §1 Asset 目录 (v0)

**唯一允许的 asset_name 枚举**（LLM 拿不到的不能 spawn，否则 server
端 reject）：

| asset_name | 语义 | UE asset 路径（xiaoxu 手填）|
|---|---|---|
| `shelf` | 货架（仓库主体物件）| `/Game/Demo/SM_Shelf` (xiaoxu 填实际路径) |
| `forklift` | 叉车 | `/Game/Demo/SM_Forklift` |
| `pallet` | 木质托盘 | `/Game/Demo/SM_Pallet` |
| `box` | 纸箱 | `/Game/Demo/SM_Box` |
| `drum` | 圆桶 | `/Game/Demo/SM_Drum` |
| `worker` | 蓝领工人占位（capsule 或 mannequin）| `/Game/Demo/SM_Worker` |

**资产准备方式**（xiaoxu 手工）：
- 每条挑一个 StaticMesh，路径写进上表
- LLM 看到的是 `asset_name`，server 端做 `asset_name -> 实际 path` 映射
  （存在 `apps/adore_robot/demo/asset_registry.py` 一个 dict，xiaoxu 维护）
- v0 不挑 Nanite 还是非 Nanite，能见就行；contract §5 Asset Checklist
  待 v1 上桌

**没有**: car / human (用 worker 占位) / tree / animal / 任何不在表内的 mesh。
LLM 收到不在表内的请求 → 走 §4 失败处理。

---

## §2 Tool Schemas (Anthropic / DeepSeek 兼容, strict JSON)

### 2.1 `spawn_object`

```json
{
  "name": "spawn_object",
  "description": "Spawn a static mesh actor at a world-space location. Returns the actor_handle (string) for later reference (delete/move).",
  "input_schema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "asset_name": {
        "type": "string",
        "enum": ["shelf", "forklift", "pallet", "box", "drum", "worker"]
      },
      "x": {"type": "number", "description": "meters, scene-local X"},
      "y": {"type": "number", "description": "meters, scene-local Y"},
      "z": {"type": "number", "description": "meters, scene-local Z (typically 0 for floor)", "default": 0},
      "yaw_deg": {"type": "number", "description": "rotation around Z axis, 0 = facing +X, 90 = facing +Y", "default": 0}
    },
    "required": ["asset_name", "x", "y"]
  }
}
```

### 2.2 `delete_object`

```json
{
  "name": "delete_object",
  "description": "Destroy a spawned actor by handle. Handle was returned by spawn_object or is visible in list_objects.",
  "input_schema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "actor_handle": {"type": "string"}
    },
    "required": ["actor_handle"]
  }
}
```

### 2.3 `modify_location`

```json
{
  "name": "modify_location",
  "description": "Translate an existing actor to a new world-space location. Rotation unchanged.",
  "input_schema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "actor_handle": {"type": "string"},
      "x": {"type": "number"},
      "y": {"type": "number"},
      "z": {"type": "number", "default": 0}
    },
    "required": ["actor_handle", "x", "y"]
  }
}
```

### 2.4 `list_objects` (LLM auxiliary)

```json
{
  "name": "list_objects",
  "description": "List all demo-spawned actors currently in the level. Use this to resolve ambiguous user references like 'that forklift' or 'the box from before'.",
  "input_schema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {}
  }
}
```

**Returns** (server packs this from MCP `SceneTools.list_actors` filtered
by tag `demo_v0_spawned`)：

```json
{
  "objects": [
    {"actor_handle": "Forklift_C_1", "asset_name": "forklift", "x": 5.0, "y": 0.0, "z": 0.0, "yaw_deg": 90},
    {"actor_handle": "Shelf_C_3", "asset_name": "shelf", "x": -3.5, "y": 2.0, "z": 0.0, "yaw_deg": 0}
  ]
}
```

---

## §3 坐标系约定

- **单位: 米** (LLM / UI / 用户对话都用米; MCP server 端转 cm 进 UE)
- **原点: scene 中心**（xiaoxu 在 .umap 里放一个 BP_DemoOrigin actor，
  server 端读它的 world position 做 anchor，然后所有 `(x, y, z)` 都相对
  这个 anchor)
- **Y 轴方向**: 与 UE 一致（Y-right when looking down +Z），不做 Y-up 翻转
- **Yaw**: 度数, 0 = +X, 90 = +Y, 180 = -X, 270 = -Y
- **Z**: 默认 0 (地面)，spawn 时 z=0 已足够; modify_location 允许抬高
  但 demo 不演

Server 端转换公式（xiaoxu 填到 `apps/adore_robot/demo/coord_convert.py`）:

```
ue_location_cm = FVector(
    (anchor_x_cm) + (x_m * 100),
    (anchor_y_cm) + (y_m * 100),
    (anchor_z_cm) + (z_m * 100),
)
```

---

## §4 失败处理 (server-side validate)

| 情况 | server 行为 |
|---|---|
| `asset_name` 不在 §1 枚举 | reject tool call，告诉 LLM "asset_name X not in v0 catalog; valid: shelf/forklift/pallet/box/drum/worker" |
| `x,y` 超出 scene 边界 (±25m，可配) | clamp 到边界 + 警告 LLM "clamped to scene bounds" |
| `actor_handle` 不存在或已删 | reject + "no such actor" |
| `delete_object` 删除非 `demo_v0_spawned` tag 的 actor | reject + "actor not owned by demo session" (保护手搭的 PCG / 基础 actor 不被误删) |
| LLM 试图调表外 tool | server 不暴露表外 tool；LLM 看不到 |

**重要**: 所有 spawn 出来的 actor server 端打 tag `demo_v0_spawned`
(MCP `set_properties` 加 Tags array)，delete 时只允许带此 tag 的。这样
手搭的 PCG Volume / 灯光 / 地面不被 LLM 误删。

---

## §5 LLM Prompt 模板

### 5.1 System prompt

```
You are a 3D scene editor for a robotics training demo. The user
edits a UE5 warehouse scene by chat. You translate user intent into
tool calls.

You have FOUR tools:
- spawn_object(asset_name, x, y, z, yaw_deg) -- create a new actor
- delete_object(actor_handle) -- remove an actor
- modify_location(actor_handle, x, y, z) -- move an actor
- list_objects() -- inspect current scene state

Available assets (the ONLY valid asset_name values):
  shelf, forklift, pallet, box, drum, worker

Coordinates: meters, scene-local, origin at scene center.
Default z = 0 (floor). Yaw 0 = facing +X.

When the user refers to an existing object ("that forklift",
"the box from before"), call list_objects() first to find the
actor_handle, unless you remember it from the conversation.

If the user asks for something out of scope (rotate, scale, change
material, set PCG density, spawn a car), reply briefly: "v0 demo
only supports spawn / delete / move. {feature} is on v1 roadmap."
```

### 5.2 Few-shot examples

```
Example 1 — spawn:
  User: "在 (5, 0) 放一个叉车"
  Tool: spawn_object({"asset_name": "forklift", "x": 5, "y": 0, "z": 0, "yaw_deg": 0})

Example 2 — move (with list_objects lookup):
  User: "把那个叉车往左挪 3 米"
  Tool 1: list_objects({})
  -> {"objects": [{"actor_handle": "Forklift_C_1", "asset_name": "forklift", "x": 5, "y": 0, ...}]}
  Tool 2: modify_location({"actor_handle": "Forklift_C_1", "x": 2, "y": 0, "z": 0})

Example 3 — delete:
  User: "删掉刚才那个叉车"
  Tool: delete_object({"actor_handle": "Forklift_C_1"})
  (LLM remembers handle from previous turn; no list_objects needed.)

Example 4 — out of scope:
  User: "把货架的密度调高"
  Reply (no tool call): "v0 demo only supports spawn / delete / move.
                        PCG parameter control is on v1 roadmap."

Example 5 — out-of-catalog asset:
  User: "在中间放一辆车"
  Reply (no tool call, refuse gracefully): "v0 catalog doesn't include
                        cars. Available: shelf, forklift, pallet, box,
                        drum, worker. Use one of those, or wait for v1."

Example 6 — multi-step:
  User: "拍三个货架排成一排, 间距 2 米"
  Tool 1: spawn_object({"asset_name": "shelf", "x": -2, "y": 0, "z": 0})
  Tool 2: spawn_object({"asset_name": "shelf", "x": 0, "y": 0, "z": 0})
  Tool 3: spawn_object({"asset_name": "shelf", "x": 2, "y": 0, "z": 0})
```

---

## §6 MCP 端实现要点 (给 xiaoxu)

> ⚠️ **2026-05-20 OBSOLETE NOTE (xiaohuan)**: 本节 4 个 `import unreal`
> Python snippet 是**死路径**。xiaoxu 2026-05-19 实证 `ProgrammaticToolset`
> Python sandbox 禁 `import unreal`, allowlist 只有 `math / json / copy /
> re / datetime`。**实际实现 xiaoxu 改走原生 RPC**: 直接 tool_call
> `SceneTools.add_to_scene_from_asset` / `remove_from_scene` /
> `set_actor_folder` / `find_actors` 一个 tool 一个 RPC, 不走 Python
> sandbox 包一层。
>
> **真实实现位置**: `apps/adore_robot/main.py` `/api/chat` + `mcp_client.py`
> SceneTools 助手 (从 `auto_load_toolsets` 调用 4 个原生 tool)。
>
> **本节保留**作为历史 design ref + 演示路径选型对照 (Python sandbox
> 路线 vs 原生 RPC 路线 trade-off)。**不要按本节代码 wire**, 看
> xiaoxu 主 commit。

xiaoxu 在 `apps/adore_robot/main.py` `/api/chat` 拿到 LLM tool_call 后，
把 4 个 tool_call 各自转成一个 MCP `ProgrammaticToolset.execute_tool_script`
调用。每个 script 是个小 unreal-python 片段：

### spawn_object（参考）

```python
# Invoked via MCP execute_tool_script with arg dict
import unreal

ASSET_REGISTRY = {
    "shelf": "/Game/Demo/SM_Shelf",
    "forklift": "/Game/Demo/SM_Forklift",
    "pallet": "/Game/Demo/SM_Pallet",
    "box": "/Game/Demo/SM_Box",
    "drum": "/Game/Demo/SM_Drum",
    "worker": "/Game/Demo/SM_Worker",
}

ANCHOR = unreal.Vector(0, 0, 0)  # BP_DemoOrigin world location; read from level

def spawn_object(asset_name: str, x: float, y: float, z: float = 0.0, yaw_deg: float = 0.0) -> dict:
    mesh = unreal.load_object(None, ASSET_REGISTRY[asset_name])
    loc = unreal.Vector(ANCHOR.x + x * 100, ANCHOR.y + y * 100, ANCHOR.z + z * 100)
    rot = unreal.Rotator(0, 0, yaw_deg)
    actor = unreal.EditorActorSubsystem().spawn_actor_from_object(mesh, loc, rot)
    actor.tags = ["demo_v0_spawned", f"demo_v0_asset:{asset_name}"]
    return {"actor_handle": actor.get_name(), "asset_name": asset_name}
```

### delete_object

```python
def delete_object(actor_handle: str) -> dict:
    actors = unreal.EditorActorSubsystem().get_all_level_actors()
    for a in actors:
        if a.get_name() == actor_handle and "demo_v0_spawned" in a.tags:
            unreal.EditorActorSubsystem().destroy_actor(a)
            return {"deleted": actor_handle}
    raise ValueError(f"actor {actor_handle} not found or not owned by demo")
```

### modify_location

```python
def modify_location(actor_handle: str, x: float, y: float, z: float = 0.0) -> dict:
    actors = unreal.EditorActorSubsystem().get_all_level_actors()
    for a in actors:
        if a.get_name() == actor_handle:
            new_loc = unreal.Vector(ANCHOR.x + x * 100, ANCHOR.y + y * 100, ANCHOR.z + z * 100)
            a.set_actor_location(new_loc, sweep=False, teleport=True)
            return {"actor_handle": actor_handle, "new_xyz_m": [x, y, z]}
    raise ValueError(f"actor {actor_handle} not found")
```

### list_objects

```python
def list_objects() -> dict:
    actors = unreal.EditorActorSubsystem().get_all_level_actors()
    out = []
    for a in actors:
        if "demo_v0_spawned" not in a.tags:
            continue
        asset_name = next((t.split(":")[1] for t in a.tags if t.startswith("demo_v0_asset:")), "unknown")
        loc = a.get_actor_location()
        rot = a.get_actor_rotation()
        out.append({
            "actor_handle": a.get_name(),
            "asset_name": asset_name,
            "x": (loc.x - ANCHOR.x) / 100,
            "y": (loc.y - ANCHOR.y) / 100,
            "z": (loc.z - ANCHOR.z) / 100,
            "yaw_deg": rot.yaw,
        })
    return {"objects": out}
```

**MCP wrapping**：xiaoxu 在 `/api/chat` 接到 LLM tool_call 后，把上面
对应 function body 用 `execute_tool_script` 发到 UE，args 通过 script
template 的占位符注入。或者更稳：在 UE plugin 里挂 4 个常驻 UFUNCTION
反射出来直接调用（如果走方向 B C++ 路径），但 v0 demo 走 script 注入
更轻、迭代快。

---

## §7 UE Map 准备 (xiaoxu 手搭)

`apps/adore_robot/unreal_projects/AdoreRobot/Content/Maps/Demo_v0.umap`：

1. 空 default level + 一块 60x60m floor BSP（或地面 mesh）
2. 中心放一个 BP_DemoOrigin actor (Actor 子类含 root SceneComponent)，
   坐标原点 anchor
3. 放一个或两个基础 PCG Volume（**手搭，本期不接 OverrideParams**），
   随便摆几个 shelf/pallet 当背景，证明 PCG + 实时手 spawn 共存
4. 放一个 fixed light rig + skylight（不需要 Mega Lights 这种重的）
5. 放一个 CineCameraActor 当 viewport 默认相机，对准中心

**资产**: §1 表 6 个 mesh 各做一个 BP wrapper 或直接用 StaticMesh，
路径回填到 `asset_registry.py`。

---

## §8 验收脚本 (客户演示前对一遍)

按顺序在 chat 框输入下列 5 句，每句完都看 UE Editor viewport：

1. "中间放一个叉车" → spawn forklift at (0,0,0)
2. "在它左边 3 米放个货架" → spawn shelf at (-3, 0, 0)
3. "再放两个箱子在叉车右边" → spawn 2 boxes around (3, 0, 0)
4. "把那个叉车往后挪 2 米" → modify forklift Y -2
5. "删掉所有箱子" → list_objects + delete all where asset_name=box

预期：viewport 内每步可见。耗时 < 3s/步（MCP RPC ~330ms + UE actor
spawn ~100-300ms）。

---

## §9 与全量 PCG 路线的关系

- **v0 demo (本 doc)**: 直接 spawn/delete/move actor，不走 PCG graph
  参数化。演示**实时手编辑**能力。
- **v1+ (`pcg_param_contract.md` + `pg_warehouse_graph_design.md`)**:
  PCG Volume + `OverrideParams` + 11 参数，演示**程序化场景生成 + 参数
  化**能力。
- **不互斥**: v0 actor 摆在 v1 PCG Volume 外围/内部都行，PCG 自己生
  的实例和 demo spawn 的 actor 共存。**Tag `demo_v0_spawned` 是隔离边界**。

客户演示问 "下一步是什么" 答 "v1 加 PCG 参数化（"把货架密一点"那种），
v2 加 MRQ 渲染管线给 Cosmos Transfer 喂训练数据"。

---

## §10 整图布局生成 (v0.3 增补, 2026-05-19)

### §10.0 为什么加这层

v0 §2 的 4 个 primitive (spawn/delete/move/list) 已经够"用嘴改场景"。
但用户开局想要一句 "**给我生成一个仓库布局**" 就出来 30+ 个物件铺好——
让 LLM 串 30 个 spawn_object 既慢又不稳。**Server-side 算法布局 + 单
tool call** 是正解。

布局生成 = LLM 把"生成 + 参数"压成 1 个 tool call → server 端 Python
算 30+ 个 position → 1 个 MCP `execute_tool_script` 批量 spawn → 所有
actor 落 `demo_v0_spawned` tag，跟 primitive 同一个回收边界。

布局生成完，用户**继续用 §2 primitive 微调**（"把第三排货架往后挪 1 米" /
"删掉中间那个叉车" / "再加 2 个箱子"），不互斥。

### §10.1 三个 layout 生成器 + 1 个 clear

| Tool | 语义 | 状态 |
|---|---|---|
| `generate_warehouse_layout` | 货架阵列 + 通道 + 叉车 + 散货 | v0 全实现 (本节) |
| `generate_living_room_layout` | 沙发组 + 茶几 + 装饰 + 灯 | v0 sketch (§10.4) |
| `generate_industrial_corner_layout` | 机器 + 工具板 + 管道 + 散物 | v0 sketch (§10.5) |
| `clear_demo_objects` | 删掉所有带 `demo_v0_spawned` tag 的 actor | v0 全实现 |

### §10.2 `generate_warehouse_layout` schema

```json
{
  "name": "generate_warehouse_layout",
  "description": "Procedurally lay out a warehouse: rows of shelves separated by aisles, optional forklifts in aisles, pallets/boxes/drums scattered, optional workers. All spawned actors are tagged demo_v0_spawned and can be modified or cleared afterwards.",
  "input_schema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "room_w_m":       {"type": "number",  "minimum": 10, "maximum": 60, "default": 30, "description": "Room width along X (meters)"},
      "room_l_m":       {"type": "number",  "minimum": 10, "maximum": 60, "default": 40, "description": "Room length along Y (meters)"},
      "shelf_rows":     {"type": "integer", "minimum": 1,  "maximum": 8,  "default": 3,  "description": "Number of shelf rows along Y"},
      "shelves_per_row":{"type": "integer", "minimum": 2,  "maximum": 12, "default": 6,  "description": "Shelves placed along each row (X)"},
      "aisle_width_m":  {"type": "number",  "minimum": 2.0,"maximum": 5.0,"default": 3.0,"description": "Aisle width between shelf rows"},
      "forklift_count": {"type": "integer", "minimum": 0,  "maximum": 5,  "default": 1},
      "pallet_count":   {"type": "integer", "minimum": 0,  "maximum": 50, "default": 10},
      "box_count":      {"type": "integer", "minimum": 0,  "maximum": 30, "default": 5},
      "drum_count":     {"type": "integer", "minimum": 0,  "maximum": 20, "default": 3},
      "worker_count":   {"type": "integer", "minimum": 0,  "maximum": 8,  "default": 0},
      "seed":           {"type": "integer", "default": 0,  "description": "Random seed for reproducibility"},
      "clear_first":    {"type": "boolean", "default": true, "description": "If true, clear existing demo_v0_spawned actors before generating"}
    }
  }
}
```

**Returns**:
```json
{
  "spawned": [{"actor_handle": "Shelf_C_1", "asset_name": "shelf", "x": -8, "y": -6, "z": 0, "yaw_deg": 0}, ...],
  "total": 32,
  "by_asset": {"shelf": 18, "forklift": 1, "pallet": 10, "box": 5, "drum": 3, "worker": 0}
}
```

### §10.3 Warehouse 算法 (server-side Python, drop into MCP `execute_tool_script`)

```python
import unreal, random

ASSET_REGISTRY = {  # 同 §6
    "shelf": "/Game/Demo/SM_Shelf",
    "forklift": "/Game/Demo/SM_Forklift",
    "pallet": "/Game/Demo/SM_Pallet",
    "box": "/Game/Demo/SM_Box",
    "drum": "/Game/Demo/SM_Drum",
    "worker": "/Game/Demo/SM_Worker",
}
SHELF_DEPTH_M = 1.2   # shelf footprint depth (Y)
SHELF_WIDTH_M = 1.6   # shelf footprint width (X)

def _spawn(asset_name, x_m, y_m, z_m=0.0, yaw_deg=0.0, anchor=None):
    mesh = unreal.load_object(None, ASSET_REGISTRY[asset_name])
    loc = unreal.Vector(anchor.x + x_m*100, anchor.y + y_m*100, anchor.z + z_m*100)
    rot = unreal.Rotator(0, 0, yaw_deg)
    actor = unreal.EditorActorSubsystem().spawn_actor_from_object(mesh, loc, rot)
    actor.tags = ["demo_v0_spawned", f"demo_v0_asset:{asset_name}"]
    return actor.get_name()

def _clear_demo():
    aes = unreal.EditorActorSubsystem()
    cleared = 0
    for a in aes.get_all_level_actors():
        if "demo_v0_spawned" in a.tags:
            aes.destroy_actor(a); cleared += 1
    return cleared

def generate_warehouse_layout(
    room_w_m=30.0, room_l_m=40.0,
    shelf_rows=3, shelves_per_row=6, aisle_width_m=3.0,
    forklift_count=1, pallet_count=10, box_count=5, drum_count=3,
    worker_count=0, seed=0, clear_first=True,
):
    if clear_first:
        _clear_demo()
    rng = random.Random(seed)
    anchor = _read_demo_origin()  # 读 BP_DemoOrigin world location, 同 §6

    # 1) Shelf rows (Y 方向均匀分布; aisle 在 row 之间)
    row_pitch = SHELF_DEPTH_M + aisle_width_m
    total_span = shelf_rows * SHELF_DEPTH_M + (shelf_rows - 1) * aisle_width_m
    y_start = -total_span / 2 + SHELF_DEPTH_M / 2
    shelf_xs = []
    spawned = []
    row_x_extent = (shelves_per_row - 1) * SHELF_WIDTH_M
    x_start = -row_x_extent / 2
    aisle_centerlines = []  # for forklift / worker placement

    for r in range(shelf_rows):
        y = y_start + r * row_pitch
        for s in range(shelves_per_row):
            x = x_start + s * SHELF_WIDTH_M
            h = _spawn("shelf", x, y, 0.0, 0.0, anchor)
            spawned.append({"actor_handle": h, "asset_name": "shelf", "x": x, "y": y, "z": 0, "yaw_deg": 0})
            shelf_xs.append(x)
        if r < shelf_rows - 1:
            aisle_centerlines.append(y + SHELF_DEPTH_M/2 + aisle_width_m/2)

    # 2) Forklifts (随机 aisle，aisle 内随机 X)
    for i in range(forklift_count):
        if not aisle_centerlines:  # 只 1 row, 没 aisle, 摆 row 前/后
            ay = y_start - row_pitch/2 if i % 2 == 0 else y_start + total_span - SHELF_DEPTH_M/2 + row_pitch/2
        else:
            ay = rng.choice(aisle_centerlines)
        ax = rng.uniform(x_start, x_start + row_x_extent)
        yaw = rng.choice([0, 90, 180, 270])
        h = _spawn("forklift", ax, ay, 0.0, yaw, anchor)
        spawned.append({"actor_handle": h, "asset_name": "forklift", "x": ax, "y": ay, "z": 0, "yaw_deg": yaw})

    # 3) Pallets (vert 紧邻 shelf row 边缘 + 随机 X)
    for i in range(pallet_count):
        r = rng.randrange(shelf_rows)
        y_row = y_start + r * row_pitch
        # pallet 摆 shelf 正前方 0.8m
        y_p = y_row + (SHELF_DEPTH_M/2 + 0.5) * rng.choice([-1, 1])
        x_p = rng.uniform(x_start - 0.5, x_start + row_x_extent + 0.5)
        h = _spawn("pallet", x_p, y_p, 0.0, rng.choice([0, 90]), anchor)
        spawned.append({"actor_handle": h, "asset_name": "pallet", "x": x_p, "y": y_p, "z": 0, "yaw_deg": 0})

    # 4) Boxes (room floor 随机散落，避开 shelf bounds)
    for i in range(box_count):
        for _ in range(20):  # 最多 retry 20 次找空位
            x_b = rng.uniform(-room_w_m/2 + 0.5, room_w_m/2 - 0.5)
            y_b = rng.uniform(-room_l_m/2 + 0.5, room_l_m/2 - 0.5)
            if _is_in_aisle(y_b, aisle_centerlines, aisle_width_m):
                break
        h = _spawn("box", x_b, y_b, 0.0, rng.uniform(0, 360), anchor)
        spawned.append({"actor_handle": h, "asset_name": "box", "x": x_b, "y": y_b, "z": 0, "yaw_deg": 0})

    # 5) Drums (同 box 但密度低、靠墙偏好)
    for i in range(drum_count):
        wall_side = rng.choice(["xneg", "xpos", "yneg", "ypos"])
        if wall_side == "xneg": x_d, y_d = -room_w_m/2 + 0.8, rng.uniform(-room_l_m/2 + 1, room_l_m/2 - 1)
        elif wall_side == "xpos": x_d, y_d = room_w_m/2 - 0.8, rng.uniform(-room_l_m/2 + 1, room_l_m/2 - 1)
        elif wall_side == "yneg": x_d, y_d = rng.uniform(-room_w_m/2 + 1, room_w_m/2 - 1), -room_l_m/2 + 0.8
        else: x_d, y_d = rng.uniform(-room_w_m/2 + 1, room_w_m/2 - 1), room_l_m/2 - 0.8
        h = _spawn("drum", x_d, y_d, 0.0, 0.0, anchor)
        spawned.append({"actor_handle": h, "asset_name": "drum", "x": x_d, "y": y_d, "z": 0, "yaw_deg": 0})

    # 6) Workers (aisle 中线，与 forklift 至少 2m)
    forklift_positions = [(s["x"], s["y"]) for s in spawned if s["asset_name"] == "forklift"]
    for i in range(worker_count):
        if not aisle_centerlines: break
        for _ in range(20):
            wy = rng.choice(aisle_centerlines)
            wx = rng.uniform(x_start, x_start + row_x_extent)
            if all((wx - fx)**2 + (wy - fy)**2 > 4.0 for fx, fy in forklift_positions):
                break
        yaw = rng.choice([0, 90, 180, 270])
        h = _spawn("worker", wx, wy, 0.0, yaw, anchor)
        spawned.append({"actor_handle": h, "asset_name": "worker", "x": wx, "y": wy, "z": 0, "yaw_deg": yaw})

    by_asset = {}
    for s in spawned:
        by_asset[s["asset_name"]] = by_asset.get(s["asset_name"], 0) + 1
    return {"spawned": spawned, "total": len(spawned), "by_asset": by_asset}


def _is_in_aisle(y, centerlines, aisle_width_m):
    return any(abs(y - cy) < aisle_width_m/2 for cy in centerlines)

def _read_demo_origin():  # 同 §6
    aes = unreal.EditorActorSubsystem()
    for a in aes.get_all_level_actors():
        if a.get_class().get_name() == "BP_DemoOrigin":
            return a.get_actor_location()
    return unreal.Vector(0, 0, 0)  # fallback

def clear_demo_objects():
    n = _clear_demo()
    return {"deleted": n}
```

**Default 参数下规模**: 3 rows x 6 shelves = 18 + 1 forklift + 10 pallet
+ 5 box + 3 drum + 0 worker = **37 个 actor**。Spawn 时间 ~37 * 100ms ≈
3.7s（一次 `execute_tool_script` 同步内，单 MCP RPC ~4s 总）。

### §10.4 `generate_living_room_layout` (sketch)

```json
{
  "name": "generate_living_room_layout",
  "input_schema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "room_w_m":       {"type": "number",  "default": 5},
      "room_l_m":       {"type": "number",  "default": 7},
      "sofa_count":     {"type": "integer", "default": 1, "minimum": 1, "maximum": 2},
      "side_box_count": {"type": "integer", "default": 2, "description": "stand-in for side tables / coffee table; v0 共用 box mesh"},
      "decor_count":    {"type": "integer", "default": 3, "description": "stand-in for plants / decor; v0 共用 drum mesh"},
      "seed":           {"type": "integer", "default": 0},
      "clear_first":    {"type": "boolean", "default": true}
    }
  }
}
```

算法（简版，xiaoxu 后续扩）：
1. 沙发靠最长墙边居中（x=0 or y=room_l/2 - 1.0）
2. 茶几（用 box 占位）摆沙发正前方 1.2m
3. 边几（用 box）摆沙发两侧
4. 装饰物（用 drum 占位）随机摆角落

**v0 asset 限制**: 客厅用 worker 当人形 / box 当桌子 / drum 当装饰。
v1 接 sofa/coffee_table/lamp 实际 mesh 时只需 ASSET_REGISTRY 扩字典。

### §10.5 `generate_industrial_corner_layout` (sketch)

```json
{
  "name": "generate_industrial_corner_layout",
  "input_schema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "room_w_m":         {"type": "number",  "default": 8},
      "room_l_m":         {"type": "number",  "default": 8},
      "machine_count":    {"type": "integer", "default": 2, "maximum": 4, "description": "stand-in: forklift mesh"},
      "workbench_count":  {"type": "integer", "default": 1, "description": "stand-in: shelf mesh"},
      "crate_count":      {"type": "integer", "default": 4, "description": "box mesh"},
      "drum_count":       {"type": "integer", "default": 3},
      "seed":             {"type": "integer", "default": 0},
      "clear_first":      {"type": "boolean", "default": true}
    }
  }
}
```

算法：grammar 一档——机器贴墙，工作台中间，箱/桶散落角落。代码 pattern
同 warehouse algo §10.3，xiaoxu 抄改即可。

### §10.6 `clear_demo_objects` schema

```json
{
  "name": "clear_demo_objects",
  "description": "Destroy all actors tagged demo_v0_spawned. Static actors (PCG Volume, lights, BP_DemoOrigin, base floor) are untouched.",
  "input_schema": {"type": "object", "additionalProperties": false, "properties": {}}
}
```

Returns: `{"deleted": N}`.

### §10.7 LLM Prompt 补充

**System prompt** 在 §5.1 末尾加：

```
For bulk scene layout, you ALSO have:
- generate_warehouse_layout(...)  -- procedural warehouse fill
- generate_living_room_layout(...) -- procedural living room fill
- generate_industrial_corner_layout(...) -- procedural industrial corner fill
- clear_demo_objects()  -- wipe all demo-spawned actors

Use a layout generator when the user asks for a "whole scene" or "fill
the room" or "warehouse layout". Use the per-actor primitives (spawn /
move / delete) for fine adjustments AFTER generation.
```

**Few-shot 加 3 条**:

```
Example 7 — bulk layout:
  User: "给我生成一个仓库布局"
  Tool: generate_warehouse_layout({})  -- 全用默认
  -> {"total": 37, "by_asset": {"shelf": 18, "forklift": 1, ...}}

Example 8 — layout with params:
  User: "做个密一点的仓库, 4 排货架每排 8 个, 加 3 台叉车"
  Tool: generate_warehouse_layout({
    "shelf_rows": 4, "shelves_per_row": 8, "forklift_count": 3
  })

Example 9 — generate + fine-tune:
  User turn 1: "生成一个仓库"
  -> generate_warehouse_layout({}) -> spawned shelf_C_1...shelf_C_18, forklift_C_1, ...
  User turn 2: "把那台叉车挪到 (0, 0)"
  -> list_objects() -> find forklift handle
  -> modify_location({"actor_handle": "Forklift_C_1", "x": 0, "y": 0})
  User turn 3: "再加 5 个箱子"
  -> spawn_object * 5 with random offsets

Example 10 — clear and regenerate:
  User: "清空, 重做一个稀疏的"
  Tool 1: clear_demo_objects({})
  Tool 2: generate_warehouse_layout({"shelf_rows": 2, "shelves_per_row": 3, "pallet_count": 3})
```

### §10.8 失败处理 + Validate (server 端)

| 情况 | server 行为 |
|---|---|
| `shelf_rows * (shelf_depth + aisle_width) > room_l_m` | 警告 "rows don't fit room; reduced to N rows" + 用 N |
| `shelves_per_row * shelf_width > room_w_m` | clamp shelves_per_row |
| 任何 count 超 schema range | clamp + warn |
| Asset path 在 ASSET_REGISTRY 找不到 | reject whole layout, return `{"error": "asset X not loaded"}` |
| `clear_first=true` 但当前没 spawned actor | 跳过 clear, 直接 generate |

### §10.9 v0 vs v1 (PCG 参数化) 的关系

| 维度 | v0 layout generator (本节) | v1 PCG 参数化 (`pcg_param_contract.md`) |
|---|---|---|
| 算法位置 | Python in MCP `execute_tool_script` | PCG graph nodes in UE Editor |
| Asset 来源 | `ASSET_REGISTRY` dict (6 mesh) | Quixel/Fab 完整 SKU pack |
| 修改方式 | 重新 generate 或 §2 primitive 微调 | set OverrideParams + Generate() |
| 实时性 | 每次 generate 全量重 spawn | PCG incremental regen |
| 演示价值 | "生成完能继续聊改" 直观 | "调一个参数全场景重 sim" 震撼 |
| 工程成本 | 已有 (本 doc) | 需 UE Editor 手搭 PCGGraph + UCLASS |

**演示路线**: v0 layout 先用，把"AI 整图布局"客户感印出去。客户问"能不
能更细更专业"，下次接 v1 PCG 路线把 11 参数挂上（design doc 在
`pg_warehouse_graph_design.md` 已存档）。
