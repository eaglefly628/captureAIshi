# UE 5.8 Preview Knowledge Base (collaborative)

> **Living doc** — 把项目跑过程中**踩过的坑 / 反直觉的事 / 官方没文档化的细节**
> 滚动收录，便于下次复用 + 给新 agent 接力做 reference。
>
> Contributors: xiaohuan / xiaoxu / 老白 (anyone who discovers something can add).
> Source of truth for **specific behavior verification**; design docs (e.g.
> `ue58_pcg_notes_xiaohuan.md` / `ue58_mcp_capability_report.md`) 是 single-source
> design 文档，本 doc 是它们底下的 footnote / addendum 集合。
> Date started: 2026-05-20.

---

## §0 快速索引

| 域 | # 条目 | 类型 |
|---|---|---|
| PCG (节点 / Graph Parameters / 行为) | §1 | 15 条已确认 + 3 条 open (+ Epic ref doc 落档) |
| MCP (协议 / SSE / 反射写) | §2 | 6 条已确认 + 2 条 open |
| Python Sandbox / Programmatic Toolset | §3 | 2 条已确认 |
| AI Assistant / ToolsetRegistry | §4 | 3 条已确认 + 4 条 open (官方未文档化) |
| Editor / 启动 / Plugin | §5 | 3 条已确认 |
| Build / Cook / Package | §6 | 0 条（未触） |

每条 entry 标 `[verified]` / `[partial]` / `[open question]`。

---

## §1 PCG (Procedural Content Generation)

### 1.1 [verified] Graph Parameter 绑定到节点 UPROPERTY 的标准做法

**问题**：怎么让 LLM 改 Graph Parameter 直接影响 Surface Sampler 的 `Points Per Squared Meter`？

**答**（5.8 实证 2026-05-20，xiaohuan + 用户）：
1. **拖** Graph Parameter row 从 `Graph Parameters` panel 到 **graph canvas 空白处** → 出现一个 `Get Graph Parameter` 节点 (visual: 绿色或青色 pill 标题, 单 output pin)
2. 选中目标节点 (e.g. Surface Sampler), 节点会**自动展开 `Overrides` 折叠节** -- 内部每个 UPROPERTY 暴露为输入 pin (同类型颜色: 绿=float / 青=int / 红=bool)
3. 从 `Get Graph Parameter` 的 output pin **拖线**到目标节点的 Override input pin
4. 绑定完成, 节点 Override 那个 pin 上有线进来 → 该 UPROPERTY 由 Graph Parameter 驱动

**反直觉点**: UE 4.x 时代是 "右键 property → Bind to Variable", 5.8 PCG 走的是**显式节点连接**模型, 不是隐式绑定。

**含义**: chat "shelf 密度 0.9" → set_properties on graphInstance.parametersOverrides.parameters.shelf_density → 该值流入 Get Graph Parameter 节点 → 流入 Surface Sampler 的 Points Per Squared Meter → re-Generate 时 shelf 阵列重 sim。

### 1.2 [verified] Surface Sampler 5.8 实际字段清单 (vs. 5.7 / 5.6 cheatsheet)

来源: 用户 2026-05-20 截图。

**有的字段**:
- `Points Per Squared Meter` (Float, 主控密度)
- `Point Extents` (Vector, 每点 footprint, 默认 50/50/50 cm = 1m³ 半 extents)
- `Looseness` (Float, 0 = grid, 1 = 完全随机)
- `Unbounded` (Bool, true = 忽略 bounds 全场散)
- `Seed` (Int, 随机种子, 默认随机大数)
- `Apply Density to Points` (Bool, true 时 density attribute 写到 output points, 下游 Density Filter 用)
- `Point Steepness` (Float, density 边界硬度, 1.0 = 硬切)

**没的字段** (本 KB 之前 design doc 引过, 5.8 删了或合并):
- `Use Bounds 2D` → 5.8 默认就 2D, 不需要 toggle
- `Iteration Count` → 5.8 删了, 固定 1 次

**Debug 子节** (visual aid, 与功能无关):
- Keep Zero Density Points / Scale Method / Point Mesh / Material Override

### 1.3 [verified] PCG Graph Parameter UI 不提供 min/max range 字段

**意义**: Range / 校验是 **server-side validate 的责任** (xiaoxu `main.py` `/api/chat` 收 tool_call 后 clamp), UE PCG 不做。

参 `pcg_param_contract.md` §1 + §7.4 server validate 表。

### 1.4 [verified] PCG Graph Parameter 不支持原生 Enum 类型 (5.8 同 5.7)

**Workaround**: 用 `Integer` + 编码约定 (e.g. `lighting_preset` 0=sodium / 1=cool / 2=mixed), graph 内 `Switch by Int` 三路分支。

⚠️ 如果未来 5.x 加 `FName` Graph Parameter 类型, 可直接传 string, 不需要 int 编码。

### 1.5 [verified] Graph Parameter row 左边 pill 颜色 = 类型, 不是 expose 状态

**色码**:
- 绿色 → Float
- 青色 (cyan/teal) → Integer
- 红色 → Bool
- 粉色 → String

**含义**: 5.8 把 `Expose to Library` + `Set as Override Param` 合并/默认 enable, 添加到 Graph Parameters 后自动 expose, 不需要单独勾。**真验证 expose 成功**的方式: 把 PCG Volume 拖入 level → Details → PCG Component → 看 `Override Parameters` 节里有没有列出这 N 个参数。

### 1.6 [open question] Surface Sampler 的 `Seed` UPROPERTY 是否可以 expose 为 Override pin

**背景**: §1.1 我们绑了 `shelf_density` 到 `Points Per Squared Meter` (work)。`seed` 也想绑到 Surface Sampler 的 `Seed`, 但用户截图 `Seed` 在 Settings 节, 不确定是否会出现在 Overrides pin 列表里。

**Action**: 用户尝试拖 `seed` Graph Parameter 到 Surface Sampler, 看 Overrides 折叠节是否包含 `Seed` 行。**没出现的话**, fallback: graph 内用 `Set Property` 上游节点写入, 或者直接在 Surface Sampler default 写常量, seed 不联动 LLM (退化方案)。

### 1.7 [open question] UE 5.8 PCG 内 "Switch by Enum" 节点的实际名

**背景**: 5.7 cheatsheet 写 `Switch by Enum`, 5.8 可能改名 `Pick by Enum` / `Select by Enum`。`lighting_preset` int 0/1/2 三路分支需要这个节点。

**Action**: 右键 PCG graph canvas → 搜 `switch` 看候选, 报告。

### 1.8 [open question] PCG 内 `Self Pruning` 在 5.8 的 `Min Distance` 单位

**背景**: 5.6/5.7 是世界单位 cm。5.8 没变化? 还是改 m 了?

**Action**: 拉 Self Pruning, default `Min Distance` 看是 30 (cm) 还是 0.3 (m)。

### 1.9 [verified] PCG Density 链路约定 (Surface Sampler → Density Filter)

**Pattern** (5.6+ 标准):
```
Surface Sampler (output points with density=1.0 each)
    ↓
Density Noise (Perlin / Worley → density 变化 0-1 spatially)
    ↓
Density Filter (Lower Bound = X) → 只保留 density >= X 的点
```

**Lower Bound 数值含义**:
- `0` → 全部 pass (无过滤)
- `1` → 0 pass (除非 density=1)
- 越高越严格 → 越少 pass → 越稀疏

⚠️ **常见错误**: 把 `shelf_density` 直接绑 `Lower Bound` → 语义反了 ("shelf 密度 0.9" 应该是多 shelf, 但 Lower Bound=0.9 是少 shelf)。**正解**: 绑 `1 - shelf_density` (需要 Attribute Math 节点), 或者用 §1.1 方式直接绑 `Points Per Squared Meter` (本项目采用方案)。

### 1.10 [verified] Nanite mesh 跟 Translucent material 不兼容 (5.6+ 持续)

来源: `ue58_preview_capabilities.md` §4 + xiaoxu peer review。

**结果**: Translucent material 挂 Nanite mesh → 渲染时**完全不可见**。
**解**: 改 `Opacity Masked` (alpha test) BlendMode, 视觉等价 + Nanite 兼容。

适用: 玻璃 / 塑料半透 / 液体 / 任何 BlendMode=Translucent。

### 1.11 [verified] PCG 节点 Ctrl+C 输出 T3D 文本格式

来源: 用户 2026-05-20 PG_Warehouse build session 实证。

**现象**: 在 PCG Graph editor 选中节点 → `Ctrl+C` 不是复制 .uasset 二进制, 是输出**人类可读的 T3D 序列化文本**, 包含完整节点拓扑 + 所有 UPROPERTY 值 + pin 连接关系。

格式示例 (节选):
```
Begin Object Class=/Script/PCG.PCGNode Name="SurfaceSampler_0"
   Begin Object Class=/Script/PCG.PCGSurfaceSamplerSettings ...
     PointsPerSquaredMeter=0.500000
     Looseness=0.300000
     ...
   End Object
   CustomProperties Pin (PinId=..., PinName="PointsPerSquaredMeter",
     LinkedTo=(PCGEditorGraphGetUserParameter_1 ...))
End Object
```

**含义**:
- **协作场景**: 用户可以 `Ctrl+C` 整个 graph 状态贴给 xiaohuan, 我能解析每个节点的实际 UPROPERTY 值 + 连接, 不需要看截图猜。
- **版本控制**: 理论上 .uasset 也可以走 T3D 走 git diff (虽然 .uasset binary 也 ok)。
- **MCP 角度**: 这是 UE 编辑器内置功能, 跟 MCP 无关 -- 但 MCP 可以反过来读 PCG graph 状态走 `ObjectTools.get_properties` 拿 UPROPERTY, 走 `ObjectTools.list_properties` 拿全部 pin。

应用: PCG build session 卡壳时, 用户贴 T3D 给 xiaohuan, xiaohuan 解析后给精确指令, 不再猜哪条线断、哪个 UPROPERTY 没设。

### 1.12 [verified] UE 5.8 PCG 自动插入类型适配节点 (FilterDataByType)

来源: 用户 2026-05-20 PG_Warehouse build session T3D dump。

**现象**: 用户拉 `Get Actor Data` → 拖线 → `Surface Sampler` 输入。本以为只是单边线连接, **UE 5.8 编辑器自动在中间插了一个 `FilterDataByType` 节点**, target type = `Surface`。

**为什么**: `Get Actor Data` 的输出类型是 `Spatial Data` (含 Volume/Surface/Point 等多种), 而 `Surface Sampler` 的 `Surface` 输入 pin **只接受 Surface 类型**。5.8 编辑器检测到类型不匹配, 自动插 FilterDataByType 做类型过滤适配, 让 connection 合法。

**T3D 体现**:
```
GetActorData_0 (Out: Spatial Data)
    ↓
FilterDataByType_0 (TargetType=Surface) ← UE 自动插入
    ↓ InsideFilter (Surface Data)
SurfaceSampler_0 (Surface input)
```

**含义**:
- 用户视觉上看到一根线 A → B, 实际 graph 内部可能多了适配节点
- 不是 bug, 是 5.8 智能化的体现 (5.7 同样行为待验证)
- 看 T3D / 仔细看 graph canvas 时会看到 "凭空多出" 的节点, 别误以为是脏数据

### 1.14 [verified] Mesh 参数化的正解 = `PCGMeshSelectorByAttribute` + `Create Attribute` + `Copy Attribute`

来源: Epic 5.7 PCG Node Reference (user 拷贴 2026-05-20), 见 `agents/pcg/refs/ue58_pcg_node_reference.md` §10 + §15.

**问题**: SM Spawner 的 Mesh field 不在 Override pin 列表里 (嵌套在 MeshSelectorParameters.MeshEntries[0].Descriptor.StaticMesh)。**直接绑 Graph Param 走 Override 路径行不通**。

**官方推荐 pattern**:
- SM Spawner Mesh Selector Type = **`PCG Mesh Selector By Attribute`**
- 配置选择器读 attribute name (e.g. `"Mesh"`)
- 上游用 `Create Attribute` 节点把 Graph Parameter 值包成单属性 Attribute Set
- 用 `Copy Attribute` 节点把这个 attribute 注入每个 Point Data

Doc 原文 (Point Match and Set 描述):
> "A common use case is to select meshes to be used downstream in a Static Mesh Spawner node with the **By Attribute selector**."

完整链路见 `ue58_pcg_node_reference.md` §X "链路 2" cookbook。

### 1.15 [verified] `Create Constant` UI label = `Create Attribute` 底层节点

UE 5.8 PCG Editor 显示 "Create Constant" 但 doc 叫 "Create Attribute"。同一节点, UI vs class 名差异。
- `Type`: Attribute 数据类型
- `Output Target`: Attribute **名字** (不是路径)
- `<TypeName> Value` (e.g. `Soft Object Path Value`): Attribute 实际值, **可绑 Graph Parameter**

### 1.16 [verified] PCG Editor debug 快捷键

来源: Tech Artist's Guide (user 拷贴 2026-05-20)。

- 节点选中 + `D` → 节点位置可视化 debug, **持久**, 不像 transient debug 切节点就消失
- 节点选中 + `A` → 显示该节点的 Attributes 面板
- Debug 不显示 → 检查 graph editor bottom-left 是否选对 PCG component

### 1.17 [verified] Spatial Data / Concrete Data / Attribute Data 三类区分

- **Spatial Data**: PCG 主要处理对象, Points / Landscape / Spline / Volume 都属于
- **Concrete Data**: Spatial Data 的"具体实例"基类, 任何 Spatial Data 都能 decay 成 Points
- **Attribute Data**: **不能直接变成点**的数据 (e.g. Data Table 每列 = Attribute), 用作 lookup table

含义: `Create Attribute` 输出 Attribute Set (Attribute Data 类型), 跟 Point Data (Spatial) 不同流, 需要 `Copy Attribute` / `Match And Set` / `Add Attribute` 节点桥接。

### 1.13 [verified] Surface Sampler 的全部 Override 字段清单 (5.8 实证)

来源: 用户 2026-05-20 T3D dump 的 `CachedOverridableParams`。

```
PointsPerSquaredMeter (Double / Float)
PointExtents (FVector)
Looseness (Double / Float)
bUnbounded (Boolean)
bApplyDensityToPoints (Boolean)
PointSteepness (Double / Float)
bKeepZeroDensityPoints (Boolean)
Seed (Integer32)
```

8 个字段全部可以拖 Graph Parameter 绑定 (走节点 Overrides 折叠节, 出输入 pin)。

`bKeepZeroDensityPoints` 是 debug 用 (保留 density=0 的点供 visualizer 看, 默认 false 不输出)。

---

## §2 MCP (Model Context Protocol)

### 2.1 [verified] Handshake response `serverInfo` 三空字段是 5.8 Preview bug

来源: `ue58_mcp_validation_log.md` §1 (xiaoxu)。

`{"name":"", "title":"", "version":""}` 全空字符串, 不影响功能, 6 月 GA 后预计修。客户端不依赖此 3 字段即可。

### 2.2 [verified] MCP `protocolVersion` 是日期 string `2025-11-25`, 不是 semver

写死在 `mcp_client.py` `PROTOCOL_VERSION` 常量。后续 Epic 升级时整体 retest §5 validation log 4 条链路。

### 2.3 [verified] SSE wire 格式: UE 5.8 不主动关连接

来源: `ue58_mcp_validation_log.md` §Plan-B (xiaoxu, 修过的 bug)。

**症状**: 标准 SSE 协议是发完事件 close stream。UE 5.8 留连接, 客户端 `resp.read()` 死等到 idle timeout (~15s)。

**解**: 客户端读到第一个 `data:` 事件 + 空行就 `break`, 不等 `Connection: close`。`mcp_client.py` `_parse_sse_or_json()` 已 wrap。

**性能影响**: 单 RPC 时延 16s → 330ms, 4 toolset 冷启 62s → 4.95s。

### 2.4 [verified] HTTP socket 复用是硬性要求

来源: `ue58_mcp_validation_log.md` (xiaoxu Plan-B 8 步)。

**症状**: urllib 每次 RPC 开新 socket → UE 5.8 `HttpListener` crash with `HttpConnection.cpp:184` assertion。
**解**: 用 `http.client.HTTPConnection` 复用持久 TCP。`mcp_client.py` 已切换。

### 2.5 [verified] Tool return 值嵌套在 `result.content[0].text` 是 JSON 字符串

**双层 wrap**: 外层 `result.content[0].text` 是 JSON string, 内容里 `{"returnValue": "..."}` 这个 returnValue 也可能是 string (再 parse 一次)。

`mcp_client.py` `_unwrap()` 双层 peel。

### 2.6 [verified] `notifications/initialized` POST 不能发

UE 5.8 plugin 收到这条会反应不稳。标准 protocol 建议 init 后立即发, 但**我们客户端不发**, 直接进 tools/list / load_toolset 调用。

### 2.7 [verified] `load_toolset` 间需至少 0.5s gap

**症状**: 连续 `load_toolset` 太快 → UE 内部 toolset 注册 race condition, 后续调用可能找不到 tool。
**解**: `mcp_client.py` `auto_load_toolsets` 在每个 load 之间 sleep 0.5s。

### 2.8 [open question] MCP 反向 (UE 当 client 调外部 MCP)

`MCPClientToolset` 在架构 overview 提到, 但本项目不用 (v0 不需要 UE 内部 AI 主动调外部 LLM)。**未来 robotics 仿真**如果要 UE 内 agent 调外部决策, 走这条路。
**Status**: 不验证, 标记 out-of-scope。

### 2.9 [open question] 多 MCP client 并发连同一 UE 是否安全

e.g. web app + Cursor + Claude Desktop 同时连 `127.0.0.1:8000/mcp`。
**Status**: 演示单客户端, 不测。生产场景 (远程团队) 时再验。

---

## §3 Python Sandbox (ProgrammaticToolset)

### 3.1 [verified] Sandbox 禁 `import unreal` (重要!)

来源: xiaoxu 2026-05-19 实证。

**Allowlist**: 只允许 `math, json, copy, re, datetime`。**禁** `unreal` / `os` / `sys` / `subprocess` / 任何 IO。

**含义**: `demo_v0_simplified_contract.md` §6 的 4 个 `import unreal` Python snippet **全是死路径**。xiaoxu 改走原生 RPC: 直接 tool_call `SceneTools.add_to_scene_from_asset` / `remove_from_scene` 等, 不走 Python wrapper。

**Sandbox 仍可用之处**: 桥接调其他 toolset (e.g. `scene.find_actors(...)` / `object.set_properties(...)` 通过沙盒 inject 的 toolset 桥接 API), 但**不能** `import unreal` 直访 UE 内部 reflection。

### 3.2 [open question] Sandbox 提供的 toolset 桥接 API 完整列表

**背景**: `ProgrammaticToolset.get_execution_environment()` 应该返沙盒可用 API 全集 (含 import 白名单 + toolset 桥接全集)。
**Action**: xiaoxu 跑一次这 tool, dump 结果, 在本 KB 加 §3.3 完整 API list。**未跑**。

---

## §4 AI Assistant / ToolsetRegistry

### 4.1 [verified] 41 个 toolset 一次 `list_toolsets` 拉到

来源: `ue58_mcp_validation_log.md` §3 (xiaoxu)。详见 `ue58_mcp_capability_report.md` §2。

41 toolset 分级: Tier 1 (4 ★★★ 我们用) / Tier 2 (4 ★★ MRQ+Sequencer 备用) / Tier 3 (6 ★ 辅助) / Tier 4 (27 不相关)。

### 4.2 [verified] 4 个 ★★★ Toolset 各自的 tool 数

- `ObjectTools` — 5 tools (list_properties / get_properties / set_properties / get_class / search_subclasses)
- `SceneTools` — 12 tools (load_level / find_actors / add_to_scene_from_asset / remove_from_scene / ...)
- `ProgrammaticToolset` — 2 tools (execute_tool_script / get_execution_environment)
- `EditorAppToolset` — 17 tools (GetSelectedActors / FocusOnActors / CaptureEditorImage / SetCameraTransform / ...)

### 4.3 [verified] `ObjectTools.set_properties` 反射写嵌套 struct 工作

来源: validation log §6 Plan-B (xiaoxu)。

`graphInstance.parametersOverrides.parameters.shelf_density` 这种嵌套 4 层路径, `set_properties` 反射直达。**意味着 UPCGAdoreToolset C++ plugin 不必要** (节省 2-3 天工程)。

### 4.4 [open question, official 未文档化] `AICallable` UFUNCTION metadata 拼写 + 行为

WebSearch 实查 (xiaohuan 2026-05-19): Unreal Garden / Tom Looman / Community Wiki / Epic 4.27 docs **均无收录**。Epic 5.7+ docs 也搜不到。Epic dev.epicgames.com 整站对 sandbox 403。

**Status**: 我们不写自定义 plugin (§6 capability report 结论 drop), 此盲区无关。如果将来想写, 需要 Epic 6 月 GA 后 doc 更新或直接源码扒。

### 4.5 [open question, official 未文档化] `UToolsetRegistry::Register` 自定义 toolset 注册 API

WebSearch 无 tutorial / sample。
**Status**: 同 §4.4, drop 自定义 plugin 顺势规避。

### 4.6 [open question, official 未文档化] AI Assistant 编辑器面板 "hidden context" 数据格式

**背景**: AI Assistant 自带聊天面板每次发问会附带 (current project / selected actor / open editor 等) 隐藏 context。格式未文档化。
**Status**: 我们绕开 UE 自带面板用自家 web UI, 不需要适配这个 format。

### 4.7 [verified] AI Assistant + ToolsetRegistry + ModelContextProtocol + AllToolsets 4 plugin 全标 Experimental

UE 5.8 Preview。6 月 GA 时 Epic 是否转 Production-ready 未明示, 待观察。**不影响调用方** (Experimental 标的是注册机制 + 协议外壳, 调用 API 稳定)。

---

## §5 Editor / 启动 / Plugin

### 5.1 [verified] UE 5.8 Preview `.uproject` 双击启动有时拒载

来源: xiaoxu 2026-05-17 验证 + 老白复现。

**症状**: 双击 `.uproject` → manifest 预检 bug → 检测到 AI plugins 列表时拒载, 不弹错只是不开 Editor。
**解**: 走 VS Code Open Folder → Generate Project Files → 用 Visual Studio 打开 `.sln` → F5 启动。这条路过 UBT 不过 manifest 预检, 稳。

**影响**: 不影响演示, 影响日常装机 / 新机器配置流程。

### 5.2 [verified] 必开 plugin 4 件套 (MCP) + 2 件 (PCG)

来源: `mcp_client.py` docstring + 用户 2026-05-20 新机器配置。

**MCP 4 件套**:
- AI Assistant (Experimental → AI)
- Toolset Registry (Experimental → AI)
- Model Context Protocol (Experimental → AI)
- All Toolsets (Experimental → AI)

**PCG 2 件**:
- Procedural Content Generation Framework (主)
- PCG Geometry Script Interop (可选)

启动后 console: `ModelContextProtocol.StartServer` 起 server 在 `127.0.0.1:8000/mcp`。或 Editor Preferences 勾 `bAutoStartServer` 永久启用。

### 5.3 [verified] MCP server console 启动命令

`ModelContextProtocol.StartServer`

成功 log: `LogModelContextProtocol: Server started on 127.0.0.1:8000`。

### 5.4 [open question] UE 5.8 Final Build (6 月 GA) 与 Preview 行为 delta

**Status**: 待 6 月 GA 出后重跑 `validation_log.md` 4 条链路, 在本 KB 补 §5.4 GA 差异。

---

## §6 Build / Cook / Package

(本项目未触, 客户演示阶段不打包, MRQ render 也走 Editor 内 trigger。后续阶段填。)

---

## §7 Cross-cutting Open Questions

集中存"我们还没回答的疑问"。每条 owner + ETA。

| # | 问题 | Owner | ETA |
|---|---|---|---|
| 1 | UE 6 月 GA 后 Experimental flag 是否转 Production-ready | 观察 Epic 官方 | 6 月 |
| 2 | PCG `Switch by Enum` 5.8 实际节点名 | 用户搭 lighting_preset 分支时报告 | 本周 |
| 3 | `ProgrammaticToolset.get_execution_environment()` 完整 API list | xiaoxu 一次 dump | 本周 |
| 4 | Niagara / GAS / Behavior Tree 接 MCP 是否有意义 | 演示后评估 | v1 后 |
| 5 | MCP 多客户端并发 | 生产场景再验 | v2 后 |
| 6 | `AICallable` 官方 spec | 不查 (规避路线) | N/A |
| 7 | `UToolsetRegistry::Register` 自定义 toolset 注册 | 不查 (规避路线) | N/A |

---

## §99 Changelog

- 2026-05-20 v0.1 xiaohuan 起步: 18 entries (PCG / MCP / Python sandbox / AI Assistant / Editor / open questions)
- 后续 contributor 加 entry 时: 写明日期 + 自己 agent 名 + 哪条 §, 不要重写整 doc。

---

## §100 如何加 entry (给后来者)

1. 找到对应 § (PCG / MCP / Python / AI / Editor / Build)
2. 加 sub-entry: `### §X.Y [status] 标题`
3. status 三选一:
   - `[verified]` 实证过, 列实证来源 (commit / validation log section / 用户 session 日期)
   - `[partial]` 部分确认, 标待完善的点
   - `[open question]` 未知, 标 owner + ETA
4. 短描述 (1-2 段) + 反直觉点 + 含义 / 解 / workaround
5. 关联文档加 cross-ref (e.g. `pcg_param_contract.md §X` / `ue58_mcp_validation_log.md §Y`)
6. 不超过 30 行 / entry, 长的拆 cross-ref 到 design doc
7. 更新 §0 索引 + §7 open question 表 + §99 changelog
