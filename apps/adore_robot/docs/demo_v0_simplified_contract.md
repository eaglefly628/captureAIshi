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
