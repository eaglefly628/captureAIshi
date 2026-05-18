# UE5 Fullstack Agent (小虚) — Shared Notes

## Active TODO

### [v0.3.2] P0 batch scene gen 调研 + 架构 (from 老白, 2026-05-15)

**任务大三段**：UE5.8 调研 → 批量造场景 UI 架构 → 自然语言 + Python 驱动 PCG。
**本轮只做调研 + 设计，不写生产代码。产出三份 design doc，落到 `apps/adore_robot/docs/`。**

#### Step 1: 摸 UE5.8 Preview 底（引擎侧）
- [x] 先读 `apps/adore_robot/docs/ue58_preview_capabilities.md`（老白这边已有 research subagent 在拉，落 commit 前如不存在，自己用 WebSearch + WebFetch 补：Epic 官方 5.8 preview release notes、Roadmap、dev community forum）
- [x] 重点关注以下子项，整理成你自己的精读笔记 `apps/adore_robot/docs/ue58_engine_notes_xiaoxu.md`:
  - **Python Editor Scripting** (`unreal.py`): 5.8 新增 API、`unreal.PCGGraph` / `unreal.PCGComponent` / `unreal.MoviePipelineQueue` 能否程序化触发 generate + render
  - **MRQ**: 命令行 (`-MoviePipelineConfig=...`) 参数、新 render pass、headless 跑通的最小命令
  - **Robotics Plugin** (5.8 是否升级到 Production-ready)、URDF 解析能力、joint state I/O
  - **Substrate** 状态（5.8 是否默认开）
  - **PCG runtime generation** 进度（决定我们是 editor-only 烤还是 runtime 现生）
  - **USD** 5.8 改动（PCG → USD 导出是否可行，未来跨工具链关键）

#### Step 2: 批量造场景 UI 架构
- [x] 产出设计文档 `apps/adore_robot/docs/batch_scene_gen_architecture.md`，包含：
  - **UI 形态选型**：三选一并说理由
    - 选项 A: Web UI（Flask + vanilla JS，挂 `apps/adore_robot/web/templates/index.html`，跑在端口 5001）
    - 选项 B: UE5 Editor Utility Widget（不离开编辑器，但远程批量不便）
    - 选项 C: CLI only（最简单，但用户摸不到）
  - **后端管线**：UI → POST `/api/scene/generate` (scene_spec JSON) → `apps/adore_robot/main.py` 扩展 → spawn `UnrealEditor-Cmd.exe` + Python commandlet → 触发 PCG generate + MRQ render → 回写 EXR 路径
  - **scene_spec JSON schema**：参考 `agents/pcg/refs/scene_specs.md`，跟 xiaohuan 对齐
  - **任务队列**：批量需要排队 + 并发上限（同时一个 UE Editor 实例）+ 失败重试
  - **进度回传**：UE 子进程 stdout → 后端 SSE / WebSocket → 前端进度条
  - **存储**：每个 scene/variant 一个目录 `Saved/MovieRenders/<scene>/<variant>/`，metadata 写 `manifest.json`

#### Step 3: 自然语言 + Python 驱动 PCG 出图
- [x] 在同一份 `batch_scene_gen_architecture.md` 续写 §3，sketch 出 NL → PCG 链路：
  - **总体思路**：用户文本（"warehouse 50x50 货架密一点，加一台叉车"）→ LLM（Claude API or 本地）→ 结构化 scene_spec delta JSON → Python commandlet apply 到 PCG component params → trigger generate
  - **Prompt 模板**：LLM 该看什么？候选 context：(a) scene_spec schema、(b) 当前 PCG graph 暴露的 param 清单、(c) 资产 pack 索引
  - **结构化输出契约**：Claude tool use / JSON mode 强制返回严格 schema 的 delta JSON（建议直接走 Anthropic SDK，参考 `.claude/skills/claude-api`）
  - **Python 落地**：`unreal.py` API 接收 delta，找到 PCG component，set params，call `Generate(true)`
  - **PCG graph 那边要暴露什么参数**：这是 xiaohuan 的活，你列需求清单写到 `agents/pcg/SHARED.md` TODO 里给他
  - **反馈循环**：generate 完抓一张缩略图回 LLM，让它判断 "是否符合要求"，不符合就再生 delta（agent loop）

#### Step 4: 落地依赖清单
- [x] `batch_scene_gen_architecture.md` 末尾列：
  - 我（xiaoxu）这边阻塞的事（环境、plugin、UE 版本）
  - 依赖 xiaohuan 的事（用 P1 形式写到 `agents/pcg/SHARED.md`）
  - 依赖老白决策的事（LLM 供应商、UI 选型、是否上 Houdini Engine 等）

#### Verification
- [x] 两份 doc 在 PR 里 (`ue58_engine_notes_xiaoxu.md` + `batch_scene_gen_architecture.md`)。原 brief 说"三份"，但 Step 2/3 合并到一份 architecture doc（§1 UI / §2 后端管线 / §3 NL→PCG / §4 依赖），已在 brief 段 1 明确"产出三份 design doc"中 Step 3 是 architecture doc 续写 §3 -> 实际产出 = 两份文件、四节内容，与原意一致。
- [x] CL 条目 ≤ 10 行，遵守 `.claude/rules/versioning.md`
- [x] 不动 capture 域、不动 PCG graph 节点（那是 xiaohuan）

#### Open (本期不做，下个 session 接力)

- [ ] **P0 (老白 await confirm, 2026-05-17): v0.3.3 UPCGAdoreToolset C++ plugin 可能不需要了**
  xiaoxu 当天实机验通 UE5.8 MCP 后**重大发现**: 5.8 内置 `ObjectTools` 已经能
  `set_properties(pcg_component, '{"shelf_density":0.9,"forklift_count":2}')`
  改 PCG Component 任意 UPROPERTY override; 内置 `ProgrammaticToolset.execute_tool_script`
  能跑 Python 沙盒一次串完 `find_actors -> set_properties -> Generate -> capture_image`,
  把 LLM 的 N 个 round trip 压成 1 个. **完整验证日志 + 41 toolset inventory +
  35 工具 schema + 架构 trade-off 表** 在 `apps/adore_robot/docs/ue58_mcp_validation_log.md`.
  实证: `get_current_level` 返回 `/Temp/Untitled_1` 全链路通; `ProgrammaticToolset`
  load 成功 + SSE `notifications/tools/list_changed` 正确推送.
  - **拟变更**: v2 §2.5 plugin skeleton + 21 UFUNCTION wrap **跳过**, 改用
    `ObjectTools` + `ProgrammaticToolset` + `apps/adore_robot/main.py` server-side
    validate (拿 demo/prompts.py contract 做 range/enum 校验, 比 UE 端 native
    bounds 灵活, 新参数 prompt edit 即可, 不用重编 plugin)
  - **保留**: v2 §2.2 21-param mapping 表 -- 它现在变成 LLM prompt 的参数 contract
    清单 / server-side validate 的 ground truth, **不**变成 C++ 函数签名
  - 省: ~2-3 天 C++ + Build.cs + cook + 5.8 Preview ABI 适配
  - **请老白回 yes / no / 折中** (如保留 plugin skeleton 但不写 21 UFUNCTION,
    给 v0.4 留 reflection-cost 优化口)
  - 在他拍板前 xiaoxu 不动 C++ plugin 分支, 只继续 ObjectTools 路径的 server
    端 wiring (改 `apps/adore_robot/main.py` `/api/chat` 在 LLM 出 update_scene
    tool_call 后转 MCP `execute_tool_script` Python 一次性下发)

- [x] **P0 (老白 2026-05-16 决策, v0.3.3): 架构方向 B -- 全面拥抱 UE5.8 MCP** **[done by 老白 2026-05-17]** -- 老白 直接出了 `apps/adore_robot/docs/batch_scene_gen_architecture_v2.md` (~410 行, 7 节) 顶替, v1 已加 SUPERSEDED 头. v2 §2.2 全表是 `UPCGAdoreToolset` 方法 1:1 映射 (warehouse/living_room/industrial 21 + orchestration 6 + 5 个 UENUM literal 列表). LLM provider 抽象在 `apps/adore_robot/llm/` (factory + base + openai_compat + anthropic_adapter), 7 个 provider, deepseek 默认. **xiaoxu 接力即可开工**: §1.3 Plan B-1 验证 + §2.5 plugin skeleton + 1 个 trivial UFUNCTION smoke. -- ref `apps/adore_robot/docs/refs/ue58_ai_mcp_overview.md`。你原 `batch_scene_gen_architecture.md` 的 Flask + subprocess + commandlet 路线**主体作废**，下面这套替代：
  - **UE = MCP Server**: 装 `AIAssistant` + `ToolsetRegistry` + `ModelContextProtocol` + `AllToolsets` plugins，`bAutoStartServer=true`，监听 `http://localhost:8000/mcp`。
  - **写 `UPCGAdoreToolset : UToolsetDefinition`**（plugin 路径 `apps/adore_robot/unreal_projects/AdoreRobot/Plugins/AdoreRobotPCG/`），把 xiaohuan `pcg_param_contract.md` §1 的每个公开参数包成 `UFUNCTION(meta=(AICallable))` 方法，函数名对齐 contract key（snake_case）。例: `void SetShelfDensity(float Value)`、`void SetForkliftCount(int32 Value)`、`void TriggerGenerate()`、`void TriggerMRQRender(FString PresetName)`、`FString GetThumbnailPath()`。反射自动出 JSON Schema，零手写。
  - **批量 headless render 路径**: 先**实证 MCP 能否驱动 commandlet/unattended cooking** -- 这是 ref doc 没明说的。两条 fallback：
    - Plan B-1: Editor 进程长驻 + MCP 跑批量（一次启动多个 job 序列调用），可行就用
    - Plan B-2: 批量保留 subprocess + commandlet（不通过 MCP），交互探索走 MCP -- 退化成方向 C 混合架构
    实证结果回写 `batch_scene_gen_architecture_v2.md` §1。
  - **LLM provider 抽象**（与方向 B 联动，老白同步决策）: 默认 **DeepSeek-V3.2**（OpenAI 兼容，tool calling 稳，比 Claude Sonnet 4.6 便宜约 10x），同时支持 Anthropic / Qwen3-Max / GLM-4.6 切换。写 `apps/adore_robot/llm/factory.py`：`make_llm_client(provider: Literal["deepseek","anthropic","qwen","glm","kimi","doubao"]) -> BaseClient`。所有 client 暴露统一 `chat_with_tools(...)` 接口。多模态（thumbnail 反馈循环 v0.4）默认 **Qwen-VL-Max**。
  - **重写 `batch_scene_gen_architecture_v2.md`** 取代 v1，结构：§0 决策摘要（方向 B + DeepSeek 默认）/ §1 MCP 拓扑 + Plan B-1/B-2 实证结果 / §2 `UPCGAdoreToolset` 方法清单（1:1 派生自 xiaohuan contract）/ §3 LLM provider 抽象 + few-shot 复用 / §4 Web UI 退化为 thin shell（仅展示 job/thumbnail，所有 PCG 操作走 MCP）/ §5 依赖清单更新。
  - **不删 v1 doc**，保留对照；在 v1 头部加一行 `> SUPERSEDED by batch_scene_gen_architecture_v2.md (老白 2026-05-16 决策方向 B)`。
  - **xiaohuan 那边请求**: 在 `agents/pcg/SHARED.md` 加 P1，让他出"contract param -> AICallable method 名"映射表，你照表写 UFUNCTION 签名。

- [x] **P0 (老白 2026-05-15 决策): Robotics Poser 接口抽象 -- ABC 三方案都要接** **[doc done by 老白 2026-05-17 `docs/robotics_poser_interface.md` ~330 行]** -- §0 Plan D (Epic 官方) 占位待 xiaoxu UE5.8 plugin manager verify; §1 `IRobotPoserInterface` UInterface + 7 method + `FRobotHandle/FJointLimits` USTRUCT + `EAdoreRoboticsBackend` UENUM; §2 Python `RobotPoserBase` + factory + 3 adapter docstring shell (minimal/urlab/urobosim); §3 老白拍 Plan C (Minimal) 先实现, A/B/D 留接口零代码; §4 deferred 列表; §5 边界 + 失败模式. xiaoxu 接力: §0 verify, §1.2 .h 落地到 `Plugins/AdoreRobotPCG/Source/AdoreRobotPCG/Public/RobotPoserInterface.h`, `apps/adore_robot/robotics/` 5 文件 skeleton, `RobotPoser_Minimal` 第一刀. -- 你原本想锁 Plan C，老白拍：**A/B/C 都做接口支持，调通可以延后**。本期落地要求：
  - 写 `docs/robotics_poser_interface.md`，定义两层抽象：
    1. **UE5 侧 `IRobotPoser` 接口** (C++ `UInterface` 或纯 BP interface)，方法清单至少含：`LoadURDF(path) -> RobotHandle`、`GetJointNames(handle) -> [name]`、`GetJointLimits(handle, name) -> (lo, hi)`、`SetJointState(handle, {name: angle})`、`GetLinkTransform(handle, link_name) -> FTransform`、`SpawnInLevel(handle, world_transform) -> AActor*`、`DestroyHandle(handle)`。
    2. **Python 侧 `RobotPoserBase` 抽象** (`apps/adore_robot/robotics/base.py`)，方法对齐 UE 侧，由 `unreal.py` bridge 调具体 implementation。Python 侧多一个 factory: `make_poser(backend: Literal["urlab","urobosim","minimal"]) -> RobotPoserBase`。
  - 三个 concrete adapter **都建空壳类 + docstring 说明映射策略**（本期不实现）：
    - `RobotPoser_URLab` (wraps URLab plugin's API)
    - `RobotPoser_URoboSim` (wraps URoboSim's classes)
    - `RobotPoser_Minimal` (自撸 URDF parser + kinematic posing BP)
  - `RobotHandle` 不绑死任何 plugin native 类型，用 `int` ID 或 `FGuid`，三 backend 各自维护 ID → 内部对象映射。三方案之间能 hot-swap，scene_spec JSON 加 `robotics_backend` 字段选 backend。
  - 调通顺序老白这边的想法：C 最小代价先跑 demo → A 物理仿真补 → B 兜底。但**接口定下来三个都不许漏方法**，否则后期切 backend 要返工。
  - 装完 UE5.8 Preview 第一件事仍是 Plugin Manager 搜 "Robot/URDF/Articulation" 实证有无官方，结果回写 `docs/robotics_poser_interface.md` §0；如果官方真出现了，加 Plan D 接口包一层。
- [ ] **P1 (from xiaohuan, 老白 2026-05-15 user directive): batch UI 必须清晰表达多 backend 支持** -- 老白原话："要在 UI 界面能清晰表达出我们的多个接口支持样子"。配合 P0 Robotics Poser 接口抽象，UI 端硬性要求：
  1. **每个 scene 表单都有 backend selector**，三 backend (`minimal` / `urlab` / `urobosim`) 全部显式列出（radio 或 segmented control，不允许藏 dropdown 也不允许只显示当前选中那个）
  2. **每个 backend 选项后挂 status badge**：`wired` (调通) / `stub` (空壳，本期 docstring only) / `experimental` (URLab/URoboSim 第三方未验) -- 让用户一眼看到"支持但未实现"和"已可用"的区别
  3. **`/api/scenes` 响应增加 `robotics_backends_available` 字段**，结构 `[{id, status, description, doc_ref}]`，来源 `docs/robotics_poser_interface.md` 或 hardcoded list；前端从此 endpoint 派生 selector，不写死
  4. **默认选 `minimal`**（老白意见：C 最小代价先跑 demo），但 UI 不要 disable 其他两个，stub 状态下点选要允许（server 端 validate 时返回 "backend stub, falling back to minimal + reason"，不直接 reject）
  5. **NL chat 入口不暴露 backend 切换** -- 这是开发期 manual 选择，LLM 不动 `robotics_backend` 键 (见 `pcg_param_contract.md` §7.2)
  6. **scene_spec JSON 已加字段** -- 三场景 `<scene>_v0.json` 现有 `robotics_backend: "minimal"` + `robotics_backend_compatible: ["minimal","urlab","urobosim"]`（commit e484db1 + 本轮补丁，无需你这边再加）
  7. UI 形态层面，参考 `batch_scene_gen_architecture.md` §1 选 A (Web UI)，backend selector 是 scene 表单的一个区块（建议放最顶头，跟 scene type 并列），不混进 `pcg_params` 区块（语义不同）

  契约文档 cross-ref: `apps/adore_robot/docs/pcg_param_contract.md` §7 (Robotics Backend 字段 schema + validate 规则)。
- [ ] **P1: UE5.8 Preview 装机 + `unreal.py` stub diff (5.7 vs 5.8)** -- 见 engine notes §1 / §11 操作序列。是 v0.3.3 实现窗口的前置门。
- [ ] **P1: MRQ_MultiPassEXR.uasset 在 5.8 Preview 重存 + commandlet 最小命令实证** -- 见 engine notes §2。
- [ ] **P2: Mega Lights + Lumen Medium A/B test plan** -- 见 engine notes §4。

## Boundary & Handoff

- **接 xiaohuan**: PCG graph asset + scene metadata + URDF joint state CSV/JSON
- **给 xiaohuan**: 如果他需要的功能内置节点搞不定，写 custom `UPCGSettings` 子类
- **给 xiaoxuan**: cooked package + MRQ preset，下游用 MRQ 渲染多层 EXR

## Reference 速查

详见 `agents/unreal/refs/`:
- `cheatsheet_mrq.md` -- MRQ multi-pass EXR 配置 + deterministic CVars
- `cheatsheet_custom_pcg_node.md` -- UPCGSettings 子类样板

外部参考（按需 WebFetch）：
- UE5.8 release notes / preview blog（subagent 调研产物 `docs/ue58_preview_capabilities.md`）
- Python Editor Scripting API: https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/
- MRQ CLI 文档: https://dev.epicgames.com/documentation/en-us/unreal-engine/cinematic-rendering-from-the-command-line-in-unreal-engine
- Anthropic SDK Python: 见 `.claude/skills/claude-api`

## Changelog

### [v0.3.3-dev] (pending push) -- xiaoxu (客户演示 demo, 适配老白 v0.3.3 LLM 接口)
- apps/adore_robot/llm/keyword.py: offline 关键词 fallback 适配老白 BaseLLMClient (Message/ToolDef/ChatResponse 接口), 加进 factory 作 'keyword' provider 不需 API key
- apps/adore_robot/demo/{prompts,runner,thumbnail}.py: NL system prompt (派生自 xiaohuan contract §1/§3/§4 + 5 few-shot) + update_scene ToolDef + SSE 假批量进度 + 4-channel SVG thumbnail (final/normal/depth/objectid)
- apps/adore_robot/web/templates/demo.html + static/{style.css, app.js, scene3d.js}: 三栏客户演示 UI (场景选择+参数 / Three.js 3D 俯视 + 批量 gallery / NL chat), 沿用老白橙色 brand, Three.js r158 via CDN
- apps/adore_robot/main.py: 加 demo 路由 `/` + dev MCP bridge 保留 `/dev`; 端点 /api/chat /api/scenes /api/demo/{submit,jobs,stream,thumbnail}; 适配老白 chat_with_tools(messages, tools, tool_choice, system) 接口
- 全链路验通: curl /api/chat keyword 模式正确派生 (货架密 + 加 2 台叉车 + 冷光 -> 3 个 param); /api/demo/submit 入队 SSE; SVG thumbnail 渲染
- 跑法: `pip install flask && python apps/adore_robot/main.py` -> http://localhost:5001; 设 DEEPSEEK_API_KEY 或 ANTHROPIC_API_KEY 启真 LLM, 否则 keyword fallback

### [v0.3.3] becd41b -- 老白
- apps/adore_robot/mcp_client.py: `_rpc` 加 `_retry` budget, 防 404 -> reinit -> 再 404 死循环 (peer review xiaoxu 的 04e3aac MCP plumbing)
- apps/adore_robot/llm/{__init__,base,openai_compat,anthropic_adapter,factory}.py: stdlib urllib 多 provider 抽象, 7 个 provider (deepseek 默认 + qwen/qwen-vl/glm/kimi/doubao/anthropic), 统一 `chat_with_tools(messages, tools, tool_choice, system, ...)` 接口, Anthropic 默认开 prompt cache
- apps/adore_robot/docs/batch_scene_gen_architecture_v2.md: 方向 B 完整设计 7 节 (决策摘要 / MCP 拓扑 + Plan B-1/B-2 / UPCGAdoreToolset 方法清单 21+6 / LLM factory 集成 / Web UI thin shell / 依赖清单 / 实施顺序 + 开放问题)
- apps/adore_robot/docs/batch_scene_gen_architecture.md: 头加 SUPERSEDED 块, v1 保留对照参考
- apps/adore_robot/docs/robotics_poser_interface.md: A/B/C/D 全接口化设计 (UE C++ IRobotPoserInterface + Python RobotPoserBase + 4 backend tag + scene_spec.robotics_backend 字段); 老白拍 Plan C 先实现, A/B 留 docstring shell, D 待 verify
- agents/STATUS.md: 老白行更新 ~60% / 2026-05-17 + xiaoxu 接力清单
- agents/unreal/SHARED.md: 标 P0 方向B + P0 Robotics Poser 全 done; 后续 xiaoxu 接力是 plugin .h 落地 + robotics/ skeleton + Plan B-1 验证

### [v0.3.2.1] af8b310 -- xiaoxu
- agents/unreal/SHARED.md: 回填 v0.3.2 CL SHA (`(pending push)` -> `cfdb7c4`) 满足 versioning 规则
- agents/STATUS.md: xiaoxu 行更新 ~50% + 标 P1 已 push + peer review 结论

### [v0.3.2] cfdb7c4 -- xiaoxu
- docs/ue58_engine_notes_xiaoxu.md: 11 节引擎侧精读 (Python/MRQ/Substrate/Lumen/Robotics/USD/PCG交接面/WP/LLM/其他/采纳前置)
- docs/batch_scene_gen_architecture.md: §1 UI 选 Web (Flask 5001) + §2 后端管线 + scene_spec schema + 子进程协议 + §3 NL→PCG (Claude SDK tool use + prompt caching) + §4 依赖清单
- agents/unreal/SHARED.md: 标 Step 1-4 done; 加 P0 Robotics Plugin 红字 + Plan A/B/C 给老白
- agents/pcg/SHARED.md: P1 (from xiaoxu) -- 公开参数表 + override key + few-shot prompt + asset 索引 + thumbnail viewpoint + Nanite translucent 约束
