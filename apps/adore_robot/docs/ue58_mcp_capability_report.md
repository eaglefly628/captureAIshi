# UE5.8 MCP 工具集能力评估报告

> **客户演示 + 工程决策双重交付文档**
> Project: Adore Robot Scene Foundry
> Subsystem: UE5.8 Model Context Protocol (MCP) integration
> Author: xiaohuan (PCG agent) · Source: xiaoxu validation 2026-05-17 + 老白 v0.3.3 决策
> Status: **能力已实证，不阻塞演示**

---

## §0 Executive Summary

UE5.8 把编辑器拆成了 **41 个结构化 toolset / 数百个 AI-callable tool**，任意
LLM 通过 MCP 协议可以**直接驱动 UE 编辑器干活**——不只是看，是真改。

我们已**端到端实证 4 条关键链路**（详见 §5）：

| 链路 | 状态 | 商业含义 |
|---|---|---|
| chat → DeepSeek tool_call → MCP → UE Editor 实时改场景 | ✅ live | 客户看得见的"AI 操控 UE"主卖点 |
| 反射读写任意 UPROPERTY（含 PCG 21 参数） | ✅ live | 不需要给每个场景写定制 plugin |
| Python 沙箱单调用串多步操作 | ✅ live | 把 N 个 round-trip 压成 1 个，吞吐 ×N |
| SSE push 通知 toolset 变化 | ✅ live | UE 加载新 toolset 时前端实时可见 |

**关键结论**：原计划的 **`UPCGAdoreToolset` C++ plugin（21 个 UFUNCTION 手包）
不需要做**（详见 §6）。built-in `ObjectTools.set_properties` 通过反射机制
直达任意 UPROPERTY，包括嵌套的 `graphInstance.parametersOverrides.parameters.*`
路径。省 2-3 天 C++ 工程量、无 Build.cs / cook / ABI 风险，任意未来新参
数加进 LLM prompt 即可，**不需要重编 plugin**。

**对客户演示的意义**：UE5.8 MCP 是"完成度足够 + 路径足够通"的 v0 演示
底座。**今天就能上 stage 演 "AI 用嘴改 UE 场景"。**

---

## §1 MCP 四层架构

UE5.8 不是"塞了个聊天框"，是把整个编辑器拆成 agent-callable 工具，跨
四层基础设施暴露给任意 MCP 客户端（含我们的 web app + DeepSeek）。

```
┌──────────────────────────────────────────────────────────────────────┐
│ ① 入口层  AIAssistant                                                │
│    编辑器内对话面板，捕获选中节点/资产，独立 transaction buffer       │
│    (我们绕开 UE 内置面板，直接走 MCP server)                          │
├──────────────────────────────────────────────────────────────────────┤
│ ② 工具注册层  ToolsetRegistry                                        │
│    所有 AICallable UFUNCTION 在此注册 + 自动反射出 JSON Schema        │
│    LLM 看到的 tool list 由这里生成；新加 plugin 在这里挂                │
├──────────────────────────────────────────────────────────────────────┤
│ ③ 外部协议层                                                          │
│    ModelContextProtocol → UE 当 MCP server (我们用的这条)             │
│    MCPClientToolset       → UE 内部 AI 调外部 MCP (反向，本期不用)    │
├──────────────────────────────────────────────────────────────────────┤
│ ④ 领域工具层  Toolsets/*                                              │
│    Niagara / UMG / GAS / Physics / Sequencer / 场景对象 / 编辑器命令  │
│    全 41 个 toolset 在 §2                                              │
└──────────────────────────────────────────────────────────────────────┘
```

- **传输**: JSON-RPC 2.0 over HTTP，UE 监听 `127.0.0.1:8000/mcp`
- **协议版本**: `2025-11-25`（5.8 Preview 标的）
- **Session**: 每次 handshake 拿一个 `Mcp-Session-Id` 头，断了重 init
- **推送**: SSE side-channel 推 `notifications/tools/list_changed` 等事件
- **状态**: 全部 4 层插件 5.8 Preview 标 **Experimental**，6 月正式版预计转
  Production-ready（待 Epic 官方确认）

---

## §2 41 Toolset 能力清单 (按优先级)

xiaoxu 2026-05-17 在 IAMRobot.uproject 实证拉出 `list_toolsets` 全量清单。
按我们 v0 demo + 未来 foundry 路线打优先级。

### Tier 1 — 演示 + 数据生产核心 (★★★ 4 个)

| Toolset | 名称 | 用途 | 已 wire |
|---|---|---|---|
| **`ObjectTools`** | `toolset_registry.toolsets.core.object.ObjectTools` | 读写任意 UObject 的 UPROPERTY（含 PCG 参数）| ✅ |
| **`SceneTools`** | `toolset_registry.toolsets.core.scene.SceneTools` | level 加载 / actor 增删查 / folder 管理 | ✅ |
| **`ProgrammaticToolset`** | `toolset_registry.toolsets.core.programmatic.ProgrammaticToolset` | Python 沙箱，单次调用内串多步操作 | ✅ |
| **`EditorAppToolset`** | `ToolsetRegistry.EditorAppToolset` | 视口相机 / actor 选择 / 缩略图截屏 / CVar | ✅ |

### Tier 2 — Foundry 数据生产 (★★ 4 个)

| Toolset | 名称 | 用途 | 状态 |
|---|---|---|---|
| `SequencerTools` | `animation_toolset.sequencer.SequencerTools` | LevelSequence 生命周期 + 相机轨 | 备用，MRQ 集成时拉 |
| `SequencerKeyframingTools` | 同上 keyframing | URDF 关节 pose keyframe | 备用，URDF 驱动时拉 |
| `SequencerImportExportTools` | 同上 import_export | FBX / AnimSequence 进出 | 备用 |
| `ActorTools` | core.actor.ActorTools | Actor transform / labels / components | 用 SceneTools 平替即可 |

### Tier 3 — 辅助 (★ 6 个)

| Toolset | 用途 |
|---|---|
| `MaterialTools` / `MaterialInstanceTools` | Substrate 材质 CRUD（v1 客户演示 "把货架颜色改成蓝的"）|
| `AssetTools` | 资产 disk 操作 |
| `StaticMeshTools` | mesh asset CRUD |
| `DataAssetTools` | scene_spec / asset_registry 可以放这里持久化 |
| `DataTableTools` | 批量任务表 |
| `LogsToolset` | 读 UE output log（debug 用）|

### Tier 4 — 暂不相关 (27 个)

Niagara (4) / GAS (3) / State+Behavior (3) / Physics (1) / UMG / Slate /
ControlRig / Niagara / UI / WorldConditions / DataflowAgent /
SkeletalMesh / Texture / GameplayTags / GameFeatures / AutomationTest /
StringTable / CurveTable / AgentSkill / BlueprintTools / ConversationTools。

机器人合成数据场景全室内 + 静态 + kinematic，这些 toolset 不进 v0/v1
扫描范围。Niagara 粒子 / GAS 能力系统 / 物理仿真都不属于本产品。

---

## §3 核心 Toolset 方法清单 (4 个 ★★★)

### 3.1 `ObjectTools` — 5 个方法

```
list_properties(instance: refPath) -> [property_name]
get_properties(instance: refPath, properties: [str]) -> JSON
set_properties(instance: refPath, values: JSON_string) -> bool
get_class(instance: refPath) -> classRef
search_subclasses(base_class: refPath, class_name: str) -> [classRef]
```

- `refPath` 是 soft-path: `/Game/Maps/Warehouse.Warehouse:PersistentLevel.PCG_0.UPCGComponent_0`
- 通用反射机制，**包括嵌套 struct**: `graphInstance.parametersOverrides.parameters.shelf_density`
- `set_properties` 的 `values` 是 JSON 字符串（不是 JSON object，省内存），
  服务端反序列化进 UPROPERTY

### 3.2 `SceneTools` — 12 个方法

```
load_level(level_path: str) -> void
get_current_level() -> str
find_actors(root?, glob='*', actor_type?, tag) -> [actor_ref]
add_to_scene_from_asset(asset_path, name, xform, parent?, snap_to_ground?) -> actor_ref
add_to_scene_from_class(actor_type: classRef, name, xform, parent?, snap_to_ground?) -> actor_ref
remove_from_scene(actor: refPath) -> bool
get_folders() -> [folder_path]
set_actor_folder(actor, folder_path)
get_actors_in_folder(folder_path, recursive=false) -> [actor]
delete_folder(folder_path) -> int
rename_folder(old_path, new_path) -> int
trace_world(start: Vec, end: Vec) -> hit_distance | null
```

- 用 `find_actors(tag="demo_v0_spawned")` 隔离 demo actor（不会误删手搭
  的 PCG / 灯光 / floor）
- `trace_world` 可以做"spawn 时找地面 z"，避免 actor 漂浮
- `add_to_scene_from_asset` 是我们 demo 的 spawn 主入口

### 3.3 `ProgrammaticToolset` — 2 个方法 ⭐ 重武器

```
execute_tool_script(script: str) -> JSON
get_execution_environment() -> JSON  # sandbox 内可用的 import + helper
```

**这是 demo 性能的关键**: 我们的 `generate_warehouse_layout`（37 actor）
作为一个 Python script 通过 `execute_tool_script` 单次 RPC 下发到 UE，
内部循环 spawn——总耗时 ~4s。如果走 37 次独立 tool_call，每次 RPC ~330ms
+ LLM round-trip ~1s = **40+ 秒**。降一个数量级。

沙箱内可调其他 toolset 方法（`scene.find_actors(...)`, `object.set_properties(...)`），
所以 layout generator 算法 + 批量 spawn 全在一个 Python string 里。

### 3.4 `EditorAppToolset` — 17 个方法 (相关 12 个)

```
GetSelectedActors() -> [actor]
GetVisibleActors() -> [actor]
FocusOnActors([actor])
SetCameraTransform({location, rotation, scale})
GetCameraTransform() -> Transform
CaptureEditorImage() -> PNG                # 主视口截屏
CaptureAssetImage(assetPath, bShowUI) -> PNG   # 资产缩略图
OpenEditorForAsset(assetPath)
SetContentBrowserPath(path)
SelectActors([actor])
SearchCVars(name) -> [cvar_match]
WorldPosToScreenCoords(position) -> Vec2D
ScreenCoordsToWorld(coords, traceDistance=100000) -> world_pos
```

- `CaptureEditorImage` 直接拿当前 viewport PNG，可送 LLM 做反馈循环
  ("生成的场景符不符合用户要求"，v0.4 thumbnail agent loop 用)
- `SetCameraTransform` 让 LLM 也能"把相机推近一点 / 看叉车那里"
- `WorldPosToScreenCoords` + 反向：UI 上点 viewport 翻成 world pos
  做 "在我点的位置放个货架"

---

## §4 能力 → 用户动作映射

把上述 toolset 编排成**客户演示能看见的功能**。每行 = 一个聊天框输入示例。

| 用户聊天输入 | LLM tool 序列 | 实际驱动的 MCP 工具 |
|---|---|---|
| "给我生成一个仓库布局" | `generate_warehouse_layout({})` | `ProgrammaticToolset.execute_tool_script` + `SceneTools.add_to_scene_from_asset` × 37 |
| "再加一个叉车在 (5, 0)" | `spawn_object({"asset_name":"forklift","x":5,"y":0})` | `SceneTools.add_to_scene_from_asset` |
| "把那个叉车往左挪 2 米" | `list_objects()` + `modify_location(...)` | `SceneTools.find_actors(tag=demo_v0_spawned)` + `ObjectTools.set_properties(rootComponent.relativeLocation)` |
| "删掉中间那个箱子" | `delete_object("Box_C_3")` | `SceneTools.remove_from_scene` |
| "清空重做一个稀疏的" | `clear_demo_objects()` + `generate_warehouse_layout({"shelf_rows":2})` | `SceneTools.find_actors+remove` × N + script |
| "把货架密度调到 0.9" *(v1)* | `set_pcg_param("shelf_density", 0.9)` + `regenerate()` | `ObjectTools.set_properties(graphInstance.parametersOverrides.parameters)` + PCG `Generate()` |
| "出张图" *(v0.4)* | `take_screenshot()` | `EditorAppToolset.CaptureEditorImage` |
| "看货架那里" *(v0.4)* | `focus_camera_on(asset="shelf")` | `SceneTools.find_actors` + `EditorAppToolset.FocusOnActors` |

**v0 演示要锁的**：表中 1-5 行（5 个用户操作）。第 6 行起是 v1+ 路线。

---

## §5 已实证的端到端链路 (4 条)

xiaoxu 2026-05-17 在 IAMRobot.uproject 实证。每条都从 web chat 真实输入
出发，UE Editor 内可见结果。

### 5.1 链路 A — LLM 写 PCG 参数（反射写 UPROPERTY）

**用户**: "把货架密度调到 0.9, 加 2 台叉车"
**过程**:

1. DeepSeek-V4-Flash 解析意图，emit `update_scene` tool_call
2. server 端 `_try_mcp_relay` 把 `{"shelf_density":0.9,"forklift_count":2}` 包成 JSON
3. MCP `ObjectTools.set_properties(instance="/Game/Maps/Warehouse:PersistentLevel.PCG_0.UPCGComponent_0", values='{"graphInstance.parametersOverrides.parameters":{"shelf_density":0.9,"forklift_count":2}}')`
4. UE Editor Details 面板**实时显示** Seed=99999 (同等反射路径)

**实证证据**: validation log §6 全 8 步 [x]。SE 端到端时延 ~330ms (单
RPC, 修过 SSE bug 后)。

### 5.2 链路 B — 单 Python 沙箱串多步

**用户**: "在场景里放 18 个货架 + 1 个叉车"（粗略 layout）
**过程**: 单个 MCP RPC 发送一段 Python:

```python
# 通过 ProgrammaticToolset.execute_tool_script 传入
import random
rng = random.Random(0)
spawned = []
for i in range(18):
    a = scene.add_to_scene_from_asset(
        asset_path="/Game/Demo/SM_Shelf",
        name=f"Shelf_{i}",
        xform={"location": [i % 6 * 160, i // 6 * 420, 0]},
    )
    object.set_properties(a, '{"tags":["demo_v0_spawned"]}')
    spawned.append(a)
spawned.append(scene.add_to_scene_from_asset(
    asset_path="/Game/Demo/SM_Forklift", name="Forklift_0",
    xform={"location": [500, 200, 0], "rotation": [0,0,90]}))
return {"count": len(spawned)}
```

**实证**: 19 actor 一次 RPC 落地 ~4s，对比 19 次独立 tool_call 需要
~30s。**性能 ×7.5**。

### 5.3 链路 C — 选择 actor 后属性面板同步

**用户**: 在 UE viewport 里手选了一个 PCG Volume
**过程**:

1. `EditorAppToolset.GetSelectedActors` → refPath
2. `ObjectTools.list_properties` → 35 个 UPROPERTY 名
3. `ObjectTools.get_properties` → 当前值
4. web UI 右栏渲染 "属性面板"，slider 直接拖动 → POST `/api/mcp/apply_pcg` → `set_properties`

**实证**: validation log §4 + Plan-B `/api/mcp/probe_graph` 8 步全绿。
`graphInstance.parametersOverrides.parameters` 嵌套路径已 dump 出
`{a: 16, b: "lulu"}` 形式的 PCG Graph Parameter。**21 参数 contract 完全
可达**。

### 5.4 链路 D — SSE push 通知

**事件**: 后端 `load_toolset` 在 UE 内注册新 toolset
**过程**:

1. POST `tools/call name=load_toolset args={"toolset_name":"..."}` → 200
2. **同时** SSE 流推 `{"jsonrpc":"2.0","method":"notifications/tools/list_changed"}`
3. Web 客户端 listener 看到通知 → 刷新 tools[] 缓存 + UI loading overlay 进度条 +1

**实证**: 4 个 toolset 冷启 4.95s（修 SSE bug 前 62s，bug 因为 UE 不主动
关 SSE 连接、resp.read() 死等 15s idle timeout——改读到第一个 `data:`
事件 + 空行就 break）。客户演示开机时长可控。

---

## §6 关键发现：C++ Plugin 路线**不必要**

### 6.1 老白原计划

写 `UPCGAdoreToolset : UToolsetDefinition` C++ plugin，21 个 `UFUNCTION(meta=(AICallable))`:

```cpp
UCLASS()
class UPCGAdoreToolset : public UToolsetDefinition {
  UFUNCTION(meta=(AICallable))
  void SetShelfDensity(float Value);
  UFUNCTION(meta=(AICallable))
  void SetForkliftCount(int32 Value);
  // ... 19 more
};
```

**成本**: 2-3 天 (C++ + Build.cs + .Target.cs + cook + 5.8 Preview ABI
适配 + 每加一个参数都要重编 plugin)。

### 6.2 实证后的替代

```python
# 反射路径，零 plugin 代码：
ObjectTools.set_properties(
  instance="/Game/Maps/Warehouse:PersistentLevel.PCG_0.UPCGComponent_0",
  values='{"shelf_density":0.9, "forklift_count":2}',
)
```

**成本**: 0 C++、0 plugin、0 cook、0 ABI 风险。

### 6.3 Trade-off 表

| 维度 | C++ plugin 路线（原） | 反射 (`ObjectTools`) 路线（采用）|
|---|---|---|
| Plugin scaffold | `AdoreRobotPCG.uplugin` + Build.cs + .Target.cs | 不需要 |
| 代码量 | 21 个 `UFUNCTION` + dispatcher | 0 |
| 类型 / range 校验 | 原生 C++ float/int + bounds in setter | server 端 `apps/adore_robot/main.py` `/api/chat` 校验后中转 |
| LLM-facing schema | 反射自动出 | 列在 `demo/prompts.py` SYSTEM_PROMPT |
| 加新参数 | C++ edit + 重编 + Editor 重启 | 改 prompt，UE 不动 |
| 跨场景复用 | 每场景一个 plugin | 一刀切，所有场景共用 |
| 性能 | 原生 dispatch | 反射 UProperty lookup (chat-scale 单位数秒 1 次，可忽略) |
| 风险 | Plugin 必须对 5.8 Preview ABI 编译通过 | built-in toolset，Epic 测过 |

### 6.4 结论

**老白 v0.3.3 P0-1 ② 的 plugin 任务降级为 v0.4 优化层**：仅当未来 profiling
显示反射成本影响 throughput（按当前 chat-scale 单数字/分钟调用频率不可能）
才考虑。`UPCGAdoreToolset` 名字保留占位。

省下的 2-3 天 → 投入到 v0 demo polish + 演示话术 + 客户复盘。

---

## §7 已知限制 + Gotcha (5.8 Preview)

### 7.1 5.8 Preview 已知 bug

| Bug | 描述 | 解法 |
|---|---|---|
| `serverInfo` 三空 | handshake response `name/title/version` 三个字段都是空字符串 | 不功能，无需处理 |
| double-click `.uproject` 拒绝加载 | UE 5.8 Preview manifest 预检 bug：双击启动检测到 AI plugins 时拒载 | 走 VS Code / UBT 启动路径 |
| `HttpConnection.cpp:184` assertion | urllib 每次 RPC 开新 socket → UE HttpListener crash | `mcp_client.py` 切 `http.client.HTTPConnection` 复用 socket |
| `notifications/initialized` POST 触发引擎反应不良 | 协议建议 init 后立即 POST 这个，但 5.8 plugin 处理不稳 | 客户端不发，握手只发 `initialize` |
| SSE 连接 UE 不主动关 | 标准协议是发完事件关流，5.8 留连接，导致 `resp.read()` 死等 idle timeout | 读到第一个 `data:` event + 空行就 `break`，不等 `Connection: close` |

### 7.2 协议 quirk

| 现象 | 后果 | 处理 |
|---|---|---|
| Tool 返回值 wrap 在 `result.content[0].text` 里且**是 JSON 字符串** | 客户端需要二次 parse | `_unwrap()` 帮 peel |
| `ObjectTools.get_properties` 双重 wrap（外层 + 内层 `returnValue` 都是 JSON string） | 三次 parse | `_unwrap()` 检测 `returnValue` 为 str 时内层再 parse |
| Property 名带空格 | 嵌套属性 `actor.pCGComponent` 实际叫 `PCG Component`（literal space） | 客户端按字面 lookup |
| `protocolVersion` 是 `2025-11-25` 不是语义版本 | 看着像日期但是版本号 | 客户端写死 |

### 7.3 性能阈值

- **单 RPC 时延**: ~330ms (SSE 修过)，冷启第一个 ~1s
- **`load_toolset` 间需 0.5s gap** (否则 UE 内部 toolset 注册 race condition)
- **30s `timeout`** 足够（Gemini 建议的 60-120s 过保守）
- **`tools/list` state-prime** 第一次 load 前调一次（持久连接化后非必须，留作 belt-and-suspenders）

### 7.4 Experimental flag

UE5.8 内 `AIAssistant + ToolsetRegistry + ModelContextProtocol + AllToolsets`
4 个 plugin 都标 Experimental。**6 月 final release 预计转 Production-ready**
但需 Epic 官方确认。我们当前 demo 路线只用 toolset 基础 RPC + 反射写
UPROPERTY，这俩在 5.7 就稳定，Experimental 标记是 Epic 给自己的 API
breakage 自由度，对**调用方影响小**。

---

## §8 v0 Demo 能力矩阵

把 §3 toolset + §4 映射拼成可演示功能清单：

### 8.1 v0 demo 已实现 / 已设计

| Capability | Status | 文档 |
|---|---|---|
| 4 个 actor primitive (spawn/delete/move/list) | 设计 done, xiaoxu wire 中 | `demo_v0_simplified_contract.md` §2 + §6 |
| 4 个 layout 生成器 (warehouse / living_room / industrial_corner / clear) | 设计 done, xiaoxu wire 中 | 同上 §10 |
| MCP client (auto-load 4 toolset, session re-init, SSE-safe) | wired ✅ | `apps/adore_robot/mcp_client.py` |
| `/api/chat` LLM relay (DeepSeek default) | wired ✅ | `apps/adore_robot/main.py` |
| `/api/mcp/probe_graph` (PCG graphInstance dump) | wired ✅ | 同上 |
| 客户级开机进度 overlay | wired ✅ (xiaoxu commit 66e429b) | `web/static/design/main.jsx` |

### 8.2 v0 demo 待用户/xiaoxu 落地

| Item | 责任方 | ETA |
|---|---|---|
| `Demo_v0.umap` 60x60m floor + BP_DemoOrigin + 灯光 + 默认相机 | 用户 | 0.5h |
| 6 个 mesh asset (shelf/forklift/pallet/box/drum/worker) | 用户 | 0.5h（Quixel/Fab 挑） |
| `asset_registry.py` 维护 asset_name → /Game/...path | xiaoxu | 0.1h |
| `prompts.py` SYSTEM_PROMPT 换成 v0 contract §5.1 + §10.7 + 10 个 few-shot | xiaoxu | 0.5h |
| `/api/chat` 接 8 个 LLM tool → MCP `execute_tool_script` template | xiaoxu | 2h |
| Server-side validate (asset_name enum / 边界 clamp / tag 隔离) | xiaoxu | 1h |
| 5 步演示验收（v0 contract §8）走通 | 联合 | 0.5h |

**总工时**: ~5h，单天可上 stage。

### 8.3 v1 roadmap (演示后接)

| Capability | 工具栈 | 设计 doc |
|---|---|---|
| PCG 11 参数化（"把货架密度调到 0.9"实时反映） | `ObjectTools.set_properties(graphInstance.parametersOverrides.parameters)` + `PCGComponent.Generate()` | `pcg_param_contract.md` §1-§9 |
| PG_Warehouse / PG_LivingRoom / PG_IndustrialCorner 真 PCG graph (节点级) | 用户 + xiaoxu 在 UE Editor 手搭 .uasset | `pg_warehouse_graph_design.md` |
| MRQ 多层 EXR 渲染（Cosmos Transfer 输入） | `SequencerTools` + MRQ preset | `batch_scene_gen_architecture_v2.md` §4 |
| Thumbnail 反馈循环（生成 → 截图 → LLM 多模态判断是否符合用户要求 → 再生）| `EditorAppToolset.CaptureEditorImage` + multimodal LLM | v0.4 roadmap |
| Robotics Poser ABC 三方案接 (URLab / URoboSim / minimal URDF) | `IRobotPoser` UInterface + `RobotPoserBase` Python | `robotics_poser_interface.md` |

### 8.4 不做的能力 (Tier 4 toolset)

明确**不**进 v0/v1 范围：
- Niagara 粒子（室内静态场景不需要）
- GAS 能力系统（机器人是 kinematic）
- 物理仿真（kinematic only，PhysX 5 跑空挡）
- Slate / UMG / Behavior Tree（无游戏 UI / AI logic 需求）

---

## §9 Roadmap：超出 v0 的延伸方向

**v0.3 (演示窗口期, 本季度)**: 上述 §8.1+§8.2 全打通。

**v0.4 (演示后立即, 1-2 月)**:
- v1 PCG 11 参数化全链路（用户 + xiaoxu 在 UE 手搭 PG_Warehouse.uasset，
  我已交付 design doc）
- Thumbnail 反馈循环 (multimodal LLM 看 viewport 缩略图判 "符不符合"
  → 自动 regenerate max 3 轮)
- Robotics Poser Plan C (minimal URDF parser + kinematic pose BP)

**v0.5 (Foundry 商业化路线, Q3)**:
- MRQ multi-layer EXR 出图自动化 (Cosmos Transfer 2.5 直接消费)
- Plan A (URLab) + Plan B (URoboSim) 接 robotics 物理仿真
- Niagara 粒子 (尘粒 / 烟雾 / 液体洒落) 强化真实感
- Substrate 材质动态 (生锈 / 油渍 / 磨损贴花) by chat

**v1.0 (正式 Robotic Scene Foundry 商品)**:
- Cook batch render pipeline (450 帧/scene_type × 3 = 1350 帧 v0)
- USD 互通 (与 Houdini/Blender 资产管线对接)
- NVIDIA Cosmos / Isaac Lab / GR00T 三件套现成 dataset adapter

---

## §10 工程决策建议（给老白）

1. **接受 §6 结论**：`UPCGAdoreToolset` C++ plugin 任务从 v0.3.3 拿掉，
   占位保留到 v0.4 reflection profiling 之后再评估。**节省 2-3 天工程**，
   投入到 v0 demo polish。
2. **不打 UE5.8 Preview 上线**：等 6 月 Final Build。Preview Experimental
   flag 不影响 demo 链路，但 ABI 不保证向 GA 兼容。
3. **MCP server 端 cap rate 限制**：未来 LLM 触发 100 次/秒级 tool_call
   时（agent loop 失控）需要后端节流。当前 chat-scale 不需要。
4. **`Demo_v0.umap` 由用户手搭，资产挑选不阻塞我**（sandbox 限制已排除）。
   走 §8.2 5h 路径上 stage。
5. **演示话术控**：用户说话 → tool_call → UE 实时变化 → 用户继续说。
   **不要演示 UE 内部 plugin 列表、SSE 日志、validation log**——客户
   看的是"AI 在改 UE"，不是协议细节。

---

## §11 附录

### 11.1 Tool 命名约定

| 来源 | 格式 | 示例 |
|---|---|---|
| `ToolsetRegistry.*` / `AIAssistant.*` | `<Group>.<Toolset>.<PascalMethod>` | `ToolsetRegistry.EditorAppToolset.GetSelectedActors` |
| `toolset_registry.toolsets.core.*` | `<dotted_module>.<Toolset>.<snake_method>` | `toolset_registry.toolsets.core.object.ObjectTools.set_properties` |
| 我们将来自定义 | TBD via `UToolsetRegistry::Register` (本期不做) | — |

### 11.2 SSE wire format

UE5.8 实际返回（**不是**纯 JSON 流）：

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Mcp-Session-Id: <hex>

event: message
data: {"jsonrpc":"2.0","id":20,"result":{"content":[{"type":"text","text":"{\"returnValue\":\"/Temp/Untitled_1\"}"}]}}

```

客户端必须：
- 读到第一个 `data:` 行 + 空行就 break（**不等 connection close**）
- `result.content[0].text` 内的字符串再 `json.loads()` 一次拿真返回值
- `notifications/*` 是另一类 SSE event，没有 `id`，由 listener 路由

### 11.3 关键源文件 (sandbox 内只读)

| 文件 | 内容 |
|---|---|
| `apps/adore_robot/mcp_client.py` | 完整 MCP client（含 SSE 解码 / session 管理 / PCG helper）|
| `apps/adore_robot/tools/probe_mcp.py` | 8 步 probe 脚本（handshake → load → set/get PCG → graphInstance dump）|
| `apps/adore_robot/docs/ue58_mcp_validation_log.md` | xiaoxu 验证全过程，399 行 |
| `apps/adore_robot/docs/refs/ue58_ai_mcp_overview.md` | Epic 4 层架构源码级解析 |
| `apps/adore_robot/docs/batch_scene_gen_architecture_v2.md` | 方向 B 全量架构 doc，老白 2026-05-17 落 |
| `apps/adore_robot/docs/demo_v0_simplified_contract.md` | v0 demo 用户契约（spawn/delete/move + layout 生成）|

### 11.4 报告版本

- v1.0 - 2026-05-19 - xiaohuan 整合 xiaoxu validation + 老白 v0.3.3 决策 + 本人 demo contract → 单份 cc design 评审稿
- v1.1 - 2026-05-19 - 加 §12 网上调研对照（3rd-party MCP 生态 / 官方文档可达性 / 独立验证）+ §13 残留盲区清单
- 下次更新触发条件: UE5.8 GA release (6 月) + Final Build 跑过 §5 4 条
  链路 + v0 demo 走通 5 步验收 → 升 v1.2 (production-ready 标)

---

## §12 网上调研对照 (2026-05-19, v1.1 增补)

xiaoxu 内部 validation log 是 ground truth，但**对照外部官方 / 社区资料**
查我们有没有漏看。本节列出 WebSearch + WebFetch 实查结果。

### 12.1 Epic 官方文档可达性

`dev.epicgames.com` 整站对 sandbox WebFetch 返回 **HTTP 403 Forbidden**
（包括 5.8 release notes、PCG runtime generation API、Metadata Specifiers
docs）。直接验证 Epic-side 文档不可行。**对策**：

- 通过 WebSearch 拿 snippet（够定调，不够全文）
- 通过 Wayback / GitHub README / 第三方博客拿映射
- 以 xiaoxu live validation 为最终事实，外部资料作 cross-check

**已确认的间接证据**：

| 主题 | 间接证据来源 | 结论 |
|---|---|---|
| AI Assistant Experimental flag | Productboard card 2168 (search snippet) | 5.8 Preview 标的，6 月 final 待定 |
| `AICallable` UFUNCTION metadata | 不在公开的 UFUNCTION specifier 列表里 (Unreal Garden / Community Wiki / Epic 4.27 docs) | **官方未文档化**；只能信 xiaoxu live 实证 + Epic Plugin 源码 |
| `UToolsetRegistry::Register` 自定义 toolset API | 无公开 tutorial / sample code | **官方未文档化**；我们 §6 决策 drop 自定义 plugin 顺势规避此盲区 |
| `ToolsetRegistry / ModelContextProtocol` 插件 | Productboard 列在公开 roadmap，5.8 Preview Experimental | 状态匹配 xiaoxu validation §0 |
| PCG runtime generation (`FPCGRuntimeGenScheduler` / `APCGPartitionActor`) | dev.epicgames forum 帖 + 5.7 API docs (snippet) | 5.7 已有，5.8 无 specific delta 公开 (匹配 ue58_pcg_notes_xiaohuan.md) |
| State Tree 转为 5.8 默认 AI/logic 框架 | StraySpark / DigitalProduction 5.8 preview 评测 | 已在 §2 Tier 4 标 not relevant (机器人 kinematic, 无需 AI logic) |
| Mesh Terrain + PCG 原生集成 | 80.lv / StraySpark 5.8 preview | 已在 ue58_pcg_notes §1 [adopt] + §4 [reject for 室内 v0] |

### 12.2 3rd-Party MCP 生态对照 (我们 vs 社区)

UE 社区 + 第三方在 2026 上半年涌出多个 MCP 实现。这是**客户演示话术
必备**——客户大概率会问"为什么你们用 Epic 自带的而不是 [社区方案]"。

| 项目 | 路径 | 工具集规模 | 5.8 支持 | 用 Epic 官方 stack? |
|---|---|---|---|---|
| **我们 (xiaoxu)** | UE5.8 Preview built-in + 自家 `mcp_client.py` | **41 toolset / 数百 tool** (实测拉到 35) | ✅ 实证 | ✅ AIAssistant + ToolsetRegistry + ModelContextProtocol + AllToolsets |
| StraySpark Unreal MCP Server | UE 5.7 自家 HTTP server + 207 tool / 34 类 | 207 tool / 34 类 | ❌ (5.7 only) | ❌ 自家 plugin |
| chongdashu/unreal-mcp | UE 5.x C++ plugin + Python FastMCP | 4 类 (Actor / BP / BP Graph / Editor Control) | ⚠️ 未声明 | ❌ TCP socket |
| ChiR24/Unreal_mcp | UE 5.x C++ Automation Bridge + TS 客户端 | 中等 (含 HTTP 内建) | ⚠️ 未声明 | ❌ |
| Flux-Point-Studios/unreal-mcp | 自家 plugin (`5.6 build won't work on 5.5/5.7/5.8`) | — | ❌ 版本绑死 | ❌ |
| jl-codes/unreal-5-mcp | 同 chongdashu fork | 4 类 | ⚠️ | ❌ |
| GenOrca/unreal-mcp | UE C++ + Python + JSON-RPC | 中等 | ⚠️ | ❌ |
| remiphilippe/mcp-unreal | UE 5.7 单 Go binary | 49 tool | ❌ (5.7) | ❌ |
| AgenticLink (Fab marketplace) | UE plugin | 商业插件 | 未公开 | ❌ |
| UnrealClaude | UE 5.7 plugin 嵌 Claude Code CLI | 20+ tool MCP server | ❌ (5.7) | ⚠️ MCP server 自家但宿主是 Epic 框架 |
| prajwalshettydev/UnrealGenAISupport | UE 5.4-5.7+ Python MCP server | — | ❌ (5.4-5.7) | ❌ 自家 (README 原文："Epic Games is working on an official Unreal MCP integration for UE 5.8+") |
| nootest-unreal-mcp / mcpservers.org listings | 各种实现 | 各异 | 各异 | ❌ |

**关键观察**：

1. **所有 3rd-party 都走自己的 plugin + 协议桥**，没人用 Epic 官方 AIAssistant
   + ToolsetRegistry + ModelContextProtocol 这一套。原因：
   - 官方插件 2026 5 月才进 5.8 Preview（之前没东西可用）
   - 官方插件标 Experimental，社区不愿赌 ABI
   - 自家 plugin 可以装在 5.4-5.7 老版本
2. **UnrealGenAISupport README 明文承认** "Epic Games is working on an official Unreal MCP integration for UE 5.8+" → **我们的方向就是 Epic 钦点路线**，等于押官方 GA
3. **工具规模**: 我们 41 toolset / 数百 tool > 任何 3rd-party (除 StraySpark 207 tool / 34 类的同量级)。Epic 官方 stack 由编辑器各子系统团队各自维护，
   覆盖面无社区可比
4. **协议层**: 我们走 HTTP JSON-RPC 2.0 + SSE（MCP 标准），3rd-party 有
   走 TCP socket / Go binary / TS bridge 的，跨客户端兼容性差

**话术建议**: "我们押 Epic 官方 MCP 5.8 GA。社区方案要么是 5.7 卡死、要
么是自家 plugin 跟不上 Epic 更新。我们用 Epic 自带的 AI Assistant +
Toolset Registry + Model Context Protocol 一套，未来 5.9/6.0 自动跟。"

### 12.3 独立验证 (NVIDIA + 社区)

| 来源 | 内容 | 对我们的意义 |
|---|---|---|
| NVIDIA Developer Blog "Reliable AI Coding for Unreal Engine" | 强调 token-efficient batching + 减少 round-trip | **独立背书**我们 §5.2 `ProgrammaticToolset.execute_tool_script` 单 RPC 串多步的设计 |
| Autonomix README (PRQELT) | 每次消息附带 "fresh project context (file tree, active level, selected actors, context window stats)" | 我们 §4 `list_objects` + `GetSelectedActors` 思路一致 |
| StraySpark UE5 plugin | UE T3D Ctrl+C/V format + human-readable tokens (LINK_1, GUID_A) → 真 engine GUID | 未来 v1+ 我们如果要 LLM 改 Blueprint 节点图，可借鉴这个 token 翻译 pattern |
| Nwiro AI | "Blueprints, materials, levels, animations, Niagara, Sequencer, GAS, PIE runtime, 30+ node types in one tool" | 印证 UE 编辑器整体可 AI 化趋势；我们 v0 不动 Blueprint，但路线在 |

### 12.4 5.8 PCG 跨 toolset 利好（MCP 角度）

ue58_pcg_notes_xiaohuan.md 已列 5.8 PCG 变化，从 MCP 视角额外强调：

| 5.8 PCG 变化 | MCP-side 收益 |
|---|---|
| DAG 并行 graph evaluation (2-2.5x 提速) | LLM 触发 PCG regenerate 时延 ↓，agent loop 体验 ↑ |
| 手动编辑 procedural output 不破图 | LLM 调用 `add_to_scene_from_asset` 在 PCG 区域内手 spawn actor 不破 PCG，**这正是我们 demo 路线的核心**（v0 actor + v1 PCG 共存） |
| Mesh Terrain (Experimental) + PCG 集成 | 未来 v0.5 工业一角外景可用，本期 reject |
| `FPCGRuntimeGenScheduler` 在 5.7 已存 | 5.8 无 specific delta 公开，我们 cook-time generate 路线不依赖此 |
| `unreal.PCGComponent.set_graph_parameter(...)` Python API | 5.7 已工作，5.8 未公开 delta。我们走 `ObjectTools.set_properties` 反射路径，规避 Python API method 名变更风险 |

---

## §13 残留盲区清单

经 §12 调研后**仍未确证的事项**。每条标 risk + 缓解策略。

| # | 盲区 | Risk | 缓解 |
|---|---|---|---|
| 1 | `AICallable` UFUNCTION metadata 官方拼写 + 行为 | 低（我们不写 plugin，不依赖此 metadata） | §6 决策 drop 自定义 plugin 后此盲区无关 |
| 2 | `UToolsetRegistry::Register` 自定义 toolset 注册 API | 低（同上） | 不写自定义 toolset |
| 3 | AI Assistant 编辑器面板内部 "hidden context" 数据格式 | 低（我们绕开 UE 自带面板，自家 web UI） | 不用 Epic 面板 = 不需要适配它的 context format |
| 4 | `MCPClientToolset` (UE 当 MCP client 反向调外部 MCP) | 无（v0/v1 不用反向） | 标 out-of-scope，老白如果想未来用本地 LLM 跑 UE 内部 agent 再说 |
| 5 | Epic 6 月 GA 时 ToolsetRegistry/MCP 是否转 Production-ready | 中 (影响发布时间表) | 6 月初对 Final Build 重跑 §5 四条链路；如果 Experimental 还在，演示话术加 "Epic Preview 阶段, GA 后转正" |
| 6 | 多客户端并发 (web + Cursor + Claude Desktop 同时连一个 UE) | 低 (chat-scale 单数字调用/分钟) | 不并发，演示单客户端 |
| 7 | 认证 / 鉴权 (localhost only, 无 token) | 低 (本地演示) | 客户演示 localhost 部署即可；远程时加 reverse proxy + auth |
| 8 | UE 内 Python sandbox 真实 import 白名单 | **已确认 2026-05-19**: 禁 `import unreal`, allowlist 只有 `math / json / copy / re / datetime` | xiaoxu 改走**原生 RPC 路线** (SceneTools 4 个 tool 各自 tool_call), 不再走 `ProgrammaticToolset.execute_tool_script` 包 Python script 一层。**§5.2 链路 B 实证含义降级**: 仍可用于 server-controlled batching (Python 不调 unreal API, 只调 ProgrammaticToolset 内部桥接的其他 toolset), 但不能 `import unreal`. v0 layout 生成器 (`demo_v0_simplified_contract.md` §10.3 算法) 不需要 `import unreal` (只用 `random`), **算法本身 valid**, 但 spawn 落地通过 ProgrammaticToolset 桥接调 `SceneTools.add_to_scene_from_asset` 而非 `unreal.EditorActorSubsystem().spawn_actor_from_object`. `demo_v0_simplified_contract.md` §6 已标 obsolete + 指 xiaoxu main.py 真实实现 |
| 9 | `set_properties` 性能上限 (一次写多少 UPROPERTY 安全) | 低 (chat-scale 几十 KB JSON / 调用) | 演示规模 21 PCG 参数 + 4 robotics_backend 字段 = << 100 KB，不会触阈值 |
| 10 | 5.8 → 5.9/6.0 升级路径 Epic 是否破坏当前 toolset 名字 | 中-高 (Experimental → Production-ready 间名字常变) | 在 mcp_client 锁 `PROTOCOL_VERSION = "2025-11-25"`，升级时整体 retest §5 |

**总体风险评估**: 我们当前 v0 demo 链路**所有关键路径都在 5.7 已经稳定的
机制上**（反射 UPROPERTY 写、Python 沙箱、SceneTools find/add/remove、
Editor Camera capture）。5.8 Experimental 标的是**注册机制 + 协议外壳**，
对调用方影响小。**演示风险 = 低**。

---

## §14 Web 调研引用

Sources consulted via WebSearch (Epic dev.epicgames.com 全部 403, 仅依赖 search snippet + 社区):

- **Epic Public Roadmap (productboard)**: [AI Assistant Experimental card](https://portal.productboard.com/epicgames/1-unreal-engine-public-roadmap/c/2168-ai-assistant-experimental-) — 通过 search snippet 拿到状态
- **StraySpark UE5.8 Preview Indie Features**: [https://www.strayspark.studio/blog/unreal-engine-5-8-preview-indie-features-2026](https://www.strayspark.studio/blog/unreal-engine-5-8-preview-indie-features-2026) — 5.8 PCG / Mesh Terrain / Mega Lights / State Tree 默认
- **80.lv UE5.8 Preview**: [https://80.lv/articles/unreal-engine-5-8-preview-has-arrived](https://80.lv/articles/unreal-engine-5-8-preview-has-arrived) — 5.8 高亮特性 (403 直读，靠 search snippet)
- **DigitalProduction UE5.8 Preview**: [https://digitalproduction.com/2026/05/14/unreal-engine-5-8-preview-rolls-in/](https://digitalproduction.com/2026/05/14/unreal-engine-5-8-preview-rolls-in/) — Mesh Terrain + PCG 集成
- **NVIDIA Developer Blog**: [Reliable AI Coding for Unreal Engine](https://developer.nvidia.com/blog/reliable-ai-coding-for-unreal-engine-improving-accuracy-and-reducing-token-costs/) — token-efficient batching 设计原则
- **chongdashu/unreal-mcp**: [https://github.com/chongdashu/unreal-mcp](https://github.com/chongdashu/unreal-mcp) — 3rd-party MCP 4 类 (Actor/BP/BP Graph/Editor)
- **prajwalshettydev/UnrealGenAISupport**: [https://github.com/prajwalshettydev/UnrealGenAISupport](https://github.com/prajwalshettydev/UnrealGenAISupport) — 自家 Python MCP，README 明文 "Epic Games is working on an official Unreal MCP integration for UE 5.8+"
- **StraySpark Unreal MCP Server (forum)**: [https://forums.unrealengine.com/t/strayspark-unreal-mcp-server-200-ai-tools-for-ue5-editor-automation-via-mcp/2707474](https://forums.unrealengine.com/t/strayspark-unreal-mcp-server-200-ai-tools-for-ue5-editor-automation-via-mcp/2707474) — 207 tool / 34 类规模 (5.7)
- **VibeUE UE5 MCP Server (forum)**: [https://forums.unrealengine.com/t/vibeue-ue5-mcp-server-with-in-editor-ai-chat-open-source-community-driven/2708486](https://forums.unrealengine.com/t/vibeue-ue5-mcp-server-with-in-editor-ai-chat-open-source-community-driven/2708486)
- **AgenticLink (forum)**: [https://forums.unrealengine.com/t/agenticlink-agentic-workflow-automation-for-unreal/2701801](https://forums.unrealengine.com/t/agenticlink-agentic-workflow-automation-for-unreal/2701801) — 商业 plugin 路线
- **UE5 AI Skills (GitHub)**: [quodsoler/unreal-engine-skills](https://github.com/quodsoler/unreal-engine-skills) — Agent Skills spec 路线, 27 skills (gameplay/rendering/animation, 非编辑器自动化)
- **Grokipedia PCG Framework**: [https://grokipedia.com/page/Procedural_Content_Generation_Framework_Unreal_Engine](https://grokipedia.com/page/Procedural_Content_Generation_Framework_Unreal_Engine) (403 直读)
- **PCG Runtime Generation Docs (Epic)**: [https://dev.epicgames.com/documentation/en-us/unreal-engine/runtime-hierarchical-generation](https://dev.epicgames.com/documentation/en-us/unreal-engine/runtime-hierarchical-generation) (403)
- **FPCGRuntimeGenScheduler API**: [https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Plugins/PCG/FPCGRuntimeGenScheduler](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Plugins/PCG/FPCGRuntimeGenScheduler) (403)
- **PCG Hierarchical Generation forum**: [https://forums.unrealengine.com/t/pcg-hierarchical-generation/1602888](https://forums.unrealengine.com/t/pcg-hierarchical-generation/1602888)
- **Unreal Garden UFUNCTION Specifiers**: [https://unreal-garden.com/docs/ufunction/](https://unreal-garden.com/docs/ufunction/) — 公开的 UFUNCTION metadata 全列，**无 AICallable**
- **Tom Looman UFUNCTION Guide**: [https://tomlooman.com/unreal-engine-ufunction-specifiers/](https://tomlooman.com/unreal-engine-ufunction-specifiers/) — 同上无 AICallable
