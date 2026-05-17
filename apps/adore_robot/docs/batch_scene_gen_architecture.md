# Batch Scene Generation Architecture (xiaoxu)

> **SUPERSEDED by `batch_scene_gen_architecture_v2.md`** (老白 2026-05-16 决策方向 B = 全面拥抱 UE5.8 MCP).
> v1 的 Flask + subprocess + commandlet + Anthropic SDK 直调链路主体作废。
> 保留本文档作对照参考：Web UI 形态选型 (§1)、scene_spec JSON schema (§2.3)、
> 任务队列设计 (§2)、prompt 缓存策略 (§3.Anthropic SDK 段) 仍可参考。
> 新的拓扑：UE = MCP Server (:8000/mcp), `UPCGAdoreToolset:UToolsetDefinition`
> 反射出工具, LLM provider 抽象 (apps/adore_robot/llm/factory.py) 默认 DeepSeek-V3.2。
> Web UI 退化为 thin shell (仅展示 job/thumbnail, 所有 PCG 操作经 MCP)。

---

Audience: 老白审 + xiaohuan 对齐 + xiaoxuan 知会下游。Author: xiaoxu, 2026-05-15.

目标: 三类室内场景 x 5 variant x 30 frame = 450 帧 multi-layer EXR，由 web UI 或自然语言驱动 PCG generate + MRQ render。本文是**设计**，不是实现。

---

## §1 UI 形态选型

### 三选一对比

| 选项 | 形态 | 优点 | 缺点 | 是否推荐 |
|---|---|---|---|---|
| **A** | Web UI (Flask + vanilla JS, port 5001) | 已有 `apps/adore_robot/main.py` stub 占位；和 captureAIshi 同 stack 复用前端模板；批量任务远程触发；NL 聊天框天然适配；老白/同事浏览器开即可 | 渲染预览受 web 限（缩略图够用，4K EXR preview 要单独 endpoint） | **是 (Recommended)** |
| B | UE5 Editor Utility Widget (Blutility) | 不离开编辑器；直接读 PCG Component；UPROPERTY-driven UI 写得快 | 远程批量不便；NL chat 嵌入难；同事必须装 5.8 + 工程才能用；headless commandlet 路径不通 | 否 |
| C | CLI only | 最简单；CI / 脚本好接 | 用户摸不到、无 NL 入口、无 progress 视觉反馈 | 否 (只做兜底入口) |

### 选 A 的最终理由

1. **复用既有脚手架**: `apps/adore_robot/main.py` 已经是 Flask launcher subprocess，加 route 就行；前端有 `web/templates/index.html` placeholder。
2. **NL 入口零摩擦**: 浏览器聊天框 -> POST `/api/nl/generate` -> Claude API -> delta JSON。Editor Utility Widget 嵌 chat 是反人类。
3. **远程触发**: 同事跑 UE 渲染节点，老白浏览器开 `http://<节点ip>:5001` 提交任务，进度回传 SSE。
4. **C 作为兜底**: 同样的后端管线暴露 `python -m apps.adore_robot.cli generate --scene warehouse --variant v0_1 --params shelf_density=0.8`，CI 接它。Web UI 是 CLI 的 thin wrapper。

---

## §2 后端管线

### 拓扑图

```
+---------------+        +------------------+        +------------------------+
|  Browser UI   | -----> |  Flask (5001)    | -----> |  Job Queue (in-proc)   |
|  vanilla JS   |  HTTP  |  apps/adore_robot|        |  list + asyncio.Lock   |
|  SSE listener | <----- |  main.py         | <----- |                        |
+---------------+        +--------+---------+        +-----------+------------+
                                  |                              |
                                  | spawn (subprocess.Popen)     |
                                  v                              v
                         +--------+----------------------------------+
                         | UnrealEditor-Cmd.exe -run=PythonScript    |
                         |   apply scene_spec -> PCG.Generate()      |
                         |   -> MRQ render -> EXR sequence           |
                         |   stdout -> Flask -> SSE -> Browser       |
                         +-------------------------------------------+
                                  |
                                  v
                         Saved/MovieRenders/<scene>/<variant>/frame_NNNN.exr
                         + manifest.json (xiaoxu writes)
```

### Endpoint 清单 (Flask routes，全在 `apps/adore_robot/main.py`)

| Method | Path | 入参 | 出参 | 说明 |
|---|---|---|---|---|
| GET  | `/`                         | -                                | HTML                    | UI 入口 |
| GET  | `/api/scenes`               | -                                | `[{scene_id, schema}]`  | 列出三场景 + 公开参数 schema（从 xiaohuan 的 `pcg_param_contract.md` 派生） |
| POST | `/api/scene/generate`       | `scene_spec` (见 §2.3)           | `{job_id}`              | 入队一个 generate+render 任务 |
| GET  | `/api/jobs`                 | -                                | `[{job_id, status, eta}]` | 当前队列 |
| GET  | `/api/jobs/<id>/stream`     | -                                | SSE event stream        | 实时进度: `pcg_done`, `mrq_frame N/M`, `done`, `error` |
| GET  | `/api/jobs/<id>/manifest`   | -                                | manifest.json           | 完成后产物列表 |
| GET  | `/api/jobs/<id>/thumbnail`  | -                                | PNG                     | 第 0 帧 LDR 缩略图（NL agent loop 用） |
| POST | `/api/nl/generate`          | `{text, base_spec}`              | `{spec_delta, rationale}` | LLM 把自然语言变成 scene_spec delta（见 §3） |
| POST | `/api/jobs/<id>/cancel`     | -                                | `{cancelled: bool}`     | 终止子进程（SIGTERM -> 5s -> SIGKILL） |

### scene_spec JSON schema（草稿，与 xiaohuan 对齐后定稿）

```json
{
  "scene_id": "warehouse",
  "variant_id": "v0_1",
  "pcg_params": {
    "shelf_density": 0.7,
    "alley_width_m": 2.4,
    "forklift_count": 1,
    "prop_variety": 3,
    "lighting_preset": "warehouse_sodium",
    "seed": 12345
  },
  "camera": {
    "trajectory": "orbit",
    "frame_count": 30,
    "fov_v": 60.0,
    "aspect": 1.7778,
    "height_m": 1.4,
    "radius_m": 6.0
  },
  "mrq_preset": "/Game/Cinematics/MRQ_MultiPassEXR.MRQ_MultiPassEXR",
  "output_dir": "Saved/MovieRenders/warehouse/v0_1"
}
```

约束:
- `pcg_params` 的 key/value 必须严格匹配 xiaohuan 的 `pcg_param_contract.md` schema（出 `400 invalid_param` 才返回）。
- `variant_id` 命名: `vMM_NN`（MM = 主版，NN = 同主版下的变种号，server 自动分配）。
- `output_dir` 由后端拼，前端不允许指定（防路径穿透）。

### 任务队列

- **并发上限 = 1**: 单 UE Editor 实例（license + GPU 限）。queue 是 `collections.deque` + `asyncio.Lock` 保护。
- **失败重试**: 最多 3 次，指数退避 5s / 20s / 60s。重试前重新读 spec（不缓存）。3 次失败后标 `failed` 不阻塞 queue 下一条。
- **超时**: 单任务硬上限 30 分钟（一个 variant 30 帧 multi-pass EXR 1080p 经验上限约 15 分钟），超时 SIGTERM -> 5s -> SIGKILL。
- **持久化**: 内存 in-proc + WAL 落 `apps/adore_robot/jobs.jsonl`（崩了重启读回未完成）。本期不上 Redis / RabbitMQ。

### 子进程协议

UE 子进程 spawn 命令（伪代码）:

```python
cmd = [
    UE_BIN / "UnrealEditor-Cmd.exe",
    PROJECT / "AdoreRobot.uproject",
    "-run=PythonScript",
    "-PythonScript=Saved/adore_jobs/job_<id>.py",
    "-stdout", "-FullStdOutLogOutput", "-unattended",
    "-nopause",
]
```

`job_<id>.py` 模板（由 Flask 渲染再写文件，scene_spec 内嵌）:

```python
import unreal, json, sys
spec = json.loads(r"""<embedded scene_spec>""")
# 1) 加载 PCG actor / set OverrideParams
# 2) PCGComponent.Generate(force=True) 同步等完
# 3) 加载 LevelSequence + MRQ preset, 注入 camera trajectory
# 4) MoviePipelineQueueSubsystem 提交 + 等完
# 5) print("DONE") sys.stdout.flush()
```

子进程 stdout 协议（行级）:

```
PROGRESS pcg_start
PROGRESS pcg_done elapsed=4.2
PROGRESS mrq_frame 1/30
PROGRESS mrq_frame 2/30
...
PROGRESS mrq_done elapsed=412.8
DONE manifest=Saved/MovieRenders/warehouse/v0_1/manifest.json
```

Flask reader pump 把这些行解析后推到 SSE。出现 `ERROR <msg>` 立即标 job failed。

### 存储与 manifest

每 variant 输出目录:

```
Saved/MovieRenders/warehouse/v0_1/
├── frame_0001.exr           # multi-layer (FinalImage / WorldNormal / SceneDepth / ObjectId / GBufferA)
├── frame_0002.exr
├── ...
├── frame_0030.exr
├── thumbnail.png            # frame_0001 LDR tonemap, 512x288, NL loop 用
└── manifest.json
```

`manifest.json` schema:

```json
{
  "scene_id": "warehouse",
  "variant_id": "v0_1",
  "ue_version": "5.8.0-preview",
  "pcg_params": { "...": "..." },
  "camera": { "...": "..." },
  "frames": [
    {"index": 1, "path": "frame_0001.exr", "ts_render_ms": 14821, "camera_pose": {"pos": [..], "rot_quat": [..]}},
    ...
  ],
  "channels": ["FinalImage", "WorldNormal", "SceneDepth", "ObjectId", "GBufferA"],
  "render_time_total_s": 412.8,
  "exit_code": 0
}
```

下游 xiaoxuan 拿这个 manifest 喂 Cosmos Transfer 2.5。

---

## §3 自然语言 + Python 驱动 PCG

### 链路

```
user text "warehouse 50x50, 货架密一点, 加一台叉车"
   |
   v
POST /api/nl/generate {text, base_spec}
   |
   v
Flask: load PCG param contract (from xiaohuan's pcg_param_contract.md)
   |
   v
Anthropic SDK (claude-sonnet-4-6 默认, opus-4-7 fallback)
   - System: param schema + few-shot + asset pack index
   - Tool: scene_spec_delta (strict JSON schema)
   - User: base_spec + 用户文本
   |
   v
LLM tool call -> JSON delta {"pcg_params": {"shelf_density": 0.9, "forklift_count": 2}}
   |
   v
Server validate (in-range + key in contract) -> merge -> /api/scene/generate
   |
   v
job finishes -> thumbnail.png
   |
   v
(optional) feedback loop:
   POST back to LLM with thumbnail + "fit user request?"
   if no -> 新 delta -> 再 generate (max 3 轮)
   if yes -> return job_id to user
```

### Anthropic SDK 集成要点

按 `.claude/skills/claude-api` 规则:

```python
import anthropic
client = anthropic.Anthropic()

resp = client.messages.create(
    model="claude-sonnet-4-6",   # NL->delta 不需要 opus
    max_tokens=1024,
    system=[
        {"type": "text", "text": SCHEMA_PROMPT, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": FEW_SHOT,     "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": ASSET_INDEX,  "cache_control": {"type": "ephemeral"}},
    ],
    tools=[SCENE_SPEC_DELTA_TOOL],
    tool_choice={"type": "tool", "name": "scene_spec_delta"},  # 强制 tool call
    messages=[
        {"role": "user", "content": f"current spec:\n{json.dumps(base_spec)}\n\nrequest:\n{text}"},
    ],
)
delta = resp.content[0].input   # tool input = strict JSON
```

**prompt 缓存**: SCHEMA_PROMPT + FEW_SHOT + ASSET_INDEX 共三段都标 `cache_control` ephemeral，连续多轮调整时命中率高（同一 session 同一 schema）。

**Tool schema** (server 维护)：

```json
{
  "name": "scene_spec_delta",
  "description": "Output a delta to apply on top of current scene_spec",
  "input_schema": {
    "type": "object",
    "properties": {
      "pcg_params": {"type": "object", "additionalProperties": false, "properties": { "...派生自 xiaohuan contract..." }},
      "camera": {"type": "object", "properties": {"trajectory": {"enum": ["orbit", "grid", "random"]}, "frame_count": {"type": "integer"}}},
      "rationale": {"type": "string"}
    },
    "required": ["pcg_params", "rationale"]
  }
}
```

强制 `tool_choice={"type": "tool", "name": "scene_spec_delta"}` 让 LLM 必须出工具调用，杜绝散文回复。

### Prompt 内容（xiaoxu 提需求，xiaohuan 落具体内容到 `pcg_param_contract.md` §4）

- **System prompt 段 1 (schema)**: 三场景每个参数的物理含义、单位、range、典型组合。来源: xiaohuan 的参数表。
- **System prompt 段 2 (few-shot)**: 3-5 个用户文本 -> delta 对，覆盖单参数调整、多参数级联、超 range 的 graceful degrade、要求不在 contract 中的功能时如何 refuse。
- **System prompt 段 3 (asset index)**: 各场景 asset pack 含什么 mesh（warehouse 有 shelf/forklift/pallet/box/drum，没有 car），让 LLM 不要瞎指挥。

具体 prompt 字句由 xiaohuan 起草（他懂参数语义），我这边只负责装载 + 调 API + validate。**这是给小幻的 P1**（见 §4 依赖清单）。

### 反馈循环 (Agent loop, 可选，本期不强制实现)

```
generate done -> thumbnail.png -> 第二轮 LLM 调用:
    multimodal input: thumbnail + 原始 request
    问 LLM: "does this fit the user's request? if not, propose new delta"
    LLM 返回 {fit: bool, new_delta?: ..., reasoning}
    if not fit -> 自动 generate 下一版 (max 3 轮)
    if fit -> 标 job 完成
```

风险: 每轮多花一次 LLM call + 一次 UE render（~15 分钟）。本期**不上自动循环**，留 manual loop（用户看缩略图，自己点"再来一版"）。Agent loop 进 v0.4 roadmap。

---

## §4 依赖 / 阻塞清单

### xiaoxu 自身阻塞

| 项 | 阻塞内容 | 怎么解 |
|---|---|---|
| UE5.8 Preview 装机 | 没装机就没法验 Robotics Plugin / Python stub diff / MRQ preset 迁移 | 老白给一台 Win + RTX workstation 访问权限 |
| Robotics Plugin 决策 | §5 未决前，URDF kinematic posing 不能开工 | 见 `ue58_engine_notes_xiaoxu.md` §5 Plan A/B/C，需老白点头 |
| `unreal.py` PCG override API 真名 | 没确认 method 名字前 NL→PCG 代码写不下去 | 装机后 `help(unreal.PCGComponent)` dump |
| Sequencer commandlet trigger 方式 | `-run=PythonScript` vs `-game -MoviePipelineConfig=...` 哪条路 5.8 实际通 | 装机后实证最小命令 |
| UE Editor license commandlet 模式 | headless 跑 commandlet 需要 license server / offline cert | 老白确认 license 模式 |

### 依赖 xiaohuan（已写到 `agents/pcg/SHARED.md` P1，见本 commit）

| 项 | 我要的东西 | 给我什么形式 |
|---|---|---|
| 公开参数表 | 三场景每个 PCG graph 暴露的参数（name / type / range / default / 物理含义） | `pcg_param_contract.md` §1 表 |
| OverrideParams key 命名 | Python 端 set 时用的 string key 或 GUID 约定 | 同上 doc 一段说明 |
| Few-shot prompt 内容 | NL prompt 段 2 的 user-text -> delta 示例 (3-5 对) | `pcg_param_contract.md` §4 |
| 资产 pack 索引 | 每场景能用的 mesh 类型清单（warehouse: shelf/forklift/...） | 同上 doc 末尾 |
| Thumbnail viewpoint | 每场景固定一个 "第 0 帧" 相机位（让 LLM 反馈循环看一致角度） | `configs/scenes/<scene>_v0.json` 加一节 `thumbnail_camera` |
| Nanite + translucent 约束 | PCG asset 不要在 Nanite mesh 上用 translucent material | 写到 xiaohuan 的 asset checklist |

### 依赖老白决策

| 项 | 选项 | 推荐 |
|---|---|---|
| Robotics Plugin 路线 | A: URLab / B: URoboSim / C: 自撸 minimal URDF parser | C（理由见 engine notes §5），但需老白拍板 |
| LLM 供应商 | Anthropic Claude (4.7 Opus / 4.6 Sonnet) / OpenAI / 本地 | Claude 4.6 Sonnet（NL→delta 任务不重，prompt caching 省钱） |
| UI 选型 | A Web / B Editor Utility / C CLI | A Web（理由见 §1） |
| Houdini Engine 集成 | 上 / 不上 | 不上（5.8 USD 5.7-baseline，跨 DCC 需求小，等需要再上） |
| Lumen Medium Quality | 启用 / 不启用 | 启用前 A/B 测 SSIM（见 engine notes §4），结果出来再定 |
| Mega Lights | 启用 / 不启用 | 启用（5.8 production-ready，warehouse 50-200 fixture 利好） |
| Job 持久化 | in-proc JSONL / Redis / DB | in-proc JSONL（450 帧规模够，加复杂度不值） |
| Agent loop (NL 自动重试 max 3 轮) | 本期上 / v0.4 再说 | v0.4（每轮 +15min 渲染，本期 manual loop 够用） |

### 不依赖任何人的事 (我可以马上开始，但本期不写代码)

- MRQ preset uasset 设计稿（哪些 pass / 哪些 CVar）-- 已经在 `cheatsheet_mrq.md`，定稿 OK。
- `verify_exr_channels.py` 设计 -- 已有片段，cook 完跑校验。
- Flask 路由骨架 + SSE pump 设计 -- 本文 §2 是设计稿。
- scene_spec JSON schema -- 本文 §2.3 草稿。

---

## §5 下一步 (xiaoxu 这边，按老白点头后)

1. 拿到 UE5.8 Preview workstation -> Plugin Manager 实证 Robotics + Python stub dump（engine notes §1 / §5 待办）。
2. 老白对 §4 决策表拍板。
3. 等 xiaohuan 的 `pcg_param_contract.md` 落地 -> 然后开始写 `apps/adore_robot/main.py` 路由 + `job_<id>.py` 模板（v0.3.3 实现窗口）。
4. 第一个 end-to-end 跑通: warehouse_v0_1，30 帧 multi-pass EXR 出图。

本期 (v0.3.2) 不写生产代码，doc + 决策 + 阻塞清单到此。
