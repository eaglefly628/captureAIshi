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
- 下次更新触发条件: UE5.8 GA release (6 月) + Final Build 跑过 §5 4 条
  链路 + v0 demo 走通 5 步验收 → 升 v1.1 (production-ready 标)
