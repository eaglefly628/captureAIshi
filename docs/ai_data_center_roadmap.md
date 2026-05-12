# captureAIshi 战略转型路线图：AI 训练数据中心基站

**Date**: 2026-05-12  •  **Status**: Draft v1 / for PPT input  •  **Author**: 主程序员

> **TL;DR**：从"破解三 A 游戏取数据"转向"用虚幻引擎自建可控数据工厂"。AI 训练数据来源转为我们完全掌控的 UE5 场景，由 PCG + 自然语言驱动生成，通过 Movie Render Queue 输出 frame-perfect 的 4D 数据（RGB / Depth / Normal / Camera 轨迹 / 角色轨迹 / Action 标注）。captureAIshi 由"采集工具"演化为"数据中心基站"。

---

## 1. 战略动机 (Why pivot)

### 1.1 现状的天花板
- **法律风险**：破解发售三 A 游戏触碰 EULA / DMCA / 反作弊检测红线
- **覆盖率难推**：每款游戏都要逆向、配 offset、写 driver；规模化困难
- **数据质量不可控**：HUD 遮挡、压缩格式、深度精度损失、无 ground-truth action 标签
- **断供风险**：游戏更新一次，逆向工作可能归零（Hellblade II 已经卡在这一步）

### 1.2 转型后的优势
- **法务清白**：使用 Epic 官方授权管线（Fab / MetaHuman / Substrate / PCG）
- **数据完整性**：MRQ 直出 multi-layer EXR，Depth/Normal/Cryptomatte 全部 native 精度
- **可重复性**：Sequencer + 固定 seed = 像素级可复现
- **可扩展性**：一次场景模板 → 跑批 N 个变体（光照、天气、角色姿态、轨迹）
- **数据卖给谁的故事更顺**：与 NVIDIA Cosmos / Isaac / 自动驾驶 sim 这条产业链对齐

### 1.3 不放弃的部分
- 现有的"破解三 A 游戏 + RenderDoc + bridge"管线**继续维护**，作为：
  - 真实游戏画风的"风格参考池"
  - 部分客户专项需求（特定游戏的画质对标）
  - 反作弊研究的副产物
- 两套管线**共用 captureAIshi UI 框架**，UI 上是两个并列的入口（"Game Capture" + "AI Map Capture"）

---

## 2. 愿景：AI 训练数据中心基站 (Vision)

```
┌────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│             AI 训练数据中心基站  (Data Center Base Station)               │
│                                                                          │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐│
│   │  自然语言     │→ │  AI 场景     │→ │  可控演员    │→ │  4D 数据导出  ││
│   │  + 业务输入   │  │  生成 (PCG+  │  │  + 轨迹规划  │  │  (MRQ + 标注) ││
│   │              │  │  LLM 编排)   │  │              │  │              ││
│   └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘│
│                                                                          │
│              ▲                                                ▼          │
│      客户需求描述                                       下游 AI 训练       │
│   "城市夜景, 行人追逐"                              (NVIDIA Cosmos /      │
│                                                  自驾仿真 / 视频生成)     │
└────────────────────────────────────────────────────────────────────────┘
```

**核心叙事**：客户用一句话描述要的场景与行为，我们的基站在 1 小时内产出 N 万张带 ground-truth 的 4D 训练数据。

---

## 3. 目标技术架构 (Target Architecture)

五层垂直栈：

```
┌──────────────────────────────────────────────────────────────────────────┐
│ L5. Dataset Export & Serving                                              │
│     训练就绪打包 (WebDataset / Parquet) + 元数据索引 + S3/OSS              │
├──────────────────────────────────────────────────────────────────────────┤
│ L4. Frame-Perfect 4D Capture                                              │
│     Movie Render Queue 多层 EXR + Sequencer 确定性回放 + 轨迹/Action 写出 │
├──────────────────────────────────────────────────────────────────────────┤
│ L3. Controllable Actors & Trajectories                                    │
│     Mover 2.0 + Motion Matching + 自定义角色 Pawn + Behavior Tree         │
│     可选: Convai / Inworld LLM-driven NPC                                 │
├──────────────────────────────────────────────────────────────────────────┤
│ L2. Scene Assembly                                                        │
│     PCG Graph (UE 5.6+) + PCG Biome + World Partition                     │
│     资产源: Fab / Megascans / MetaHuman / Tripo3D / Meshy / 3D-GS         │
├──────────────────────────────────────────────────────────────────────────┤
│ L1. Natural Language → Scene Spec                                         │
│     LLM (Claude / GPT) → JSON Spec → PCG 参数覆盖 + Spawn List            │
│     可选预处理: Holodeck 2.0 / Promethean AI (prop dressing)              │
└──────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌──────────────────────────────────────────────────────────────────────────┐
│              captureAIshi UI (Web Flask + pywebview)                       │
│  ┌──────────────────────────┐   ┌──────────────────────────┐              │
│  │  Game Capture (legacy)   │   │  AI Map Capture (NEW)    │              │
│  │  RenderDoc + bridge      │   │  UE Editor + MRQ + LLM   │              │
│  └──────────────────────────┘   └──────────────────────────┘              │
└──────────────────────────────────────────────────────────────────────────┘
```

### 3.1 各层职责细化

#### **L1 — 自然语言 → 场景规范**
**输入**：用户文本 + 业务参数（密度、时间段、相机数、轨迹要求…）
**输出**：`scene_spec.json`，结构如：
```json
{
  "biome": "urban_night",
  "pcg_graph": "/Game/Maps/CityBlock.PCGGraph_CityBlock",
  "pcg_overrides": {
    "BuildingDensity": 0.7, "TrafficLightProbability": 0.3,
    "FoliageType": "deciduous", "Weather": "rain_light"
  },
  "actors": [
    {"class": "BP_Pedestrian", "count": 30, "behavior": "wander", "tags": ["civilian"]},
    {"class": "BP_Pursuer",   "count": 1,  "behavior": "chase_target"},
    {"class": "BP_Target",    "count": 1,  "behavior": "flee_random"}
  ],
  "camera_rigs": [
    {"type": "third_person_track", "target": "BP_Target", "distance": 5.0},
    {"type": "top_down_static", "altitude": 50}
  ],
  "duration_sec": 30, "fps": 30,
  "seed": 42, "variants": 10
}
```
**LLM 调用模板**：Claude 4.7 Opus，prompt 含 PCG 可调参数清单 + 已有 actor 类清单 + 输出 JSON schema。验证：JSON schema validator + UE Python 跑一次预检（找不到资产则报错回 LLM 重试）。

#### **L2 — 场景组装**
- **PCG Graph**（UE 5.6+，production）— 节点图驱动建筑/植被/路网生成，参数从 L1 注入
- **PCG Biome Core**（UE 5.4+）— 地形+植被组合规则
- **World Partition + Data Layers** — 流式加载，支持大世界
- **Houdini Engine for Unreal** — 重型程序化资产（城市、地形）的可选补充
- **资产源**：
  - Fab (Megascans 已收费、MetaHuman 内置、海量第三方)
  - AI 3D 生成 (Tripo3D / Meshy / TRELLIS) 补缺口
  - 3D Gaussian Splatting (Volinga / NanoGS) 真实场景重建

#### **L3 — 可控演员与轨迹**
- **Mover 2.0**（UE 5.6+） + **Motion Matching**（UE 5.4+）— 角色运动，annotated GameplayTags 作为 action 标签
- **Behavior Tree / State Tree** — 高层 AI 决策（wander / pursue / flee）
- **Smart Objects + Mass AI** — 大规模 NPC 行为
- **MetaHuman Animator** — 面部表情 + 音频驱动唇形
- 可选 LLM-driven actor: Convai / Inworld（产线就绪 Fab 插件）— 用于复杂对话/反应场景

#### **L4 — Frame-Perfect 4D 捕捉**
- **Movie Render Queue**（MRQ）— UE 内置，输出多层 EXR：
  - Final Image (sRGB)
  - World Depth (R-channel, world units)
  - World Normal (XYZ)
  - Motion Vectors
  - Object IDs (Cryptomatte) → 语义分割
  - Custom Stencil / BaseColor / 任意 G-buffer
- **Sequencer + Take Recorder** — 确定性回放，`-FixedSeed` + 固定 timestep
- **Path Tracer** 模式（可选） — 光线追踪 ground truth，分钟级/帧
- **Cinematic Camera Tracks** — 多机位、轨道、跟焦、镜头切换全部 keyframe 化
- **Python 后处理 pass**：MRQ 出帧后跑 Python 脚本，把 EXR + Sequencer 评估出的 actor pose / camera pose / GameplayTag 拼成训练就绪格式

#### **L5 — 数据集导出与服务**
- **打包格式**：
  - WebDataset（tar shards）— PyTorch DataLoader 友好
  - Parquet（元数据索引）— Spark / DuckDB 查询
  - Per-frame manifest JSON — 帧级别 ground-truth
- **元数据索引字段**：scene_spec hash / seed / camera_id / frame_idx / actor_poses / gameplay_tags / weather / lighting / 渲染 preset
- **存储**：S3 兼容 (Minio / Cloudflare R2 / 阿里云 OSS)
- **可选下游接口**：
  - NVIDIA Cosmos Transfer 2.5 — depth/seg/traj 作为条件输入，photoreal 视频输出
  - 训练框架适配器（PyTorch / JAX / Megatron-LM）

---

## 4. 工具选型矩阵 (Tool Maturity Matrix)

| 管线阶段 | 选型 | 成熟度 | 备注 |
|---------|------|--------|------|
| NL → Scene Layout | LLM 自研 prompt + Holodeck 2.0 参考算法 | **DIY / Research** | 无开箱即用，需自建 |
| NL → 演员行为 | Convai 或 Inworld (Fab 插件) | Production | 商业方案，按用量计费 |
| 程序化场景填充 | PCG + PCG Biome Core (UE 5.6) | **Production** | Epic 一方，免费 |
| 重型程序化资产 | Houdini Engine for Unreal | Production | SideFX 一方，免费 |
| 资产源 — 策展 | Fab (Megascans / MetaHuman / Marketplace) | Production | 部分付费 |
| 资产源 — AI 生成 | Tripo3D / Meshy / TRELLIS / Rodin | Beta | 质量参差，需筛选 |
| 角色 / 动捕 | MetaHuman Creator + Animator (UE 5.6 内置) | Production | 免费用于任何引擎 |
| 物理材质 | Substrate (UE 5.7 正式) | Production | UE 一方，免费 |
| 确定性回放 | Sequencer + Take Recorder | Production | UE 一方，免费 |
| 4D 真值捕捉 | Movie Render Queue (EXR + Cryptomatte) | **Production** | UE 一方，免费 |
| Headless 批产 | UnrealEditor commandlet + Python | Production | UE 一方，免费 |
| LLM↔UE 编排 | UnrealGenAISupport (社区) 作起点 | **Beta / DIY** | 起点，需深度定制 |
| Photoreal 后处理 | NVIDIA Cosmos Transfer 2.5 | Beta | 可选 v2 里程碑 |
| 3D Gaussian Splatting | Volinga Pro / NanoGS / Luma | Production / Beta | 真实场景导入 |

**关键发现**：80% 的产线已有成熟工具，**最重大的自研工作集中在 L1 (NL → Scene Spec)** 和 **L5 (训练就绪数据集打包)**。

---

## 5. Build vs Buy/Integrate

### 5.1 我们自建（DIY）
1. **L1 LLM → PCG 参数翻译器**（核心 IP）
   - Prompt 工程 + 输出 schema 验证 + UE 端预检反馈环
2. **L4 确定性 4D 数据写出 pass**
   - Python 脚本，MRQ 出帧后绑定 Sequencer 评估出的所有 actor pose、camera pose、GameplayTag → 训练就绪 JSON
3. **L3 Action-Label UI**
   - Sequencer Event Track 作为标注时间轴，UI 提供可视化打标签界面
4. **Object-ID → 语义类映射**
   - 每项目一份 YAML，导出 pass 关联 Cryptomatte ID
5. **captureAIshi "AI Map Capture" 入口 Tab**
   - 镜像现有 Game Capture 流程；项目选择器、Sequencer 选择器、MRQ preset、批量数、seed 扫描

### 5.2 我们集成（Buy / Plug-in）
- PCG (Epic, 免费)
- Movie Render Queue (Epic, 免费)
- MetaHuman + Animator (Epic, 免费)
- Fab 资产订阅（按需付费）
- Houdini Engine (SideFX, 免费插件)
- UnrealGenAISupport (社区开源, 起点)
- Convai / Inworld（如需 LLM-NPC，按用量计费）

### 5.3 我们继承（Reuse from captureAIshi）
- Flask + pywebview 桌面 GUI 框架
- 配置系统（`configs/`）+ session 输出目录结构
- 3D 轨迹可视化（Three.js 在 web 前端，可复用作 camera path 预览）
- OBS / 视频录制管线（可选作 reference video）
- 飞书通知工具（任务完成通知）

---

## 6. captureAIshi UI 与架构整合

### 6.1 顶层导航：两个并列入口

```
┌─ captureAIshi ─────────────────────────────────────────────────────┐
│                                                                       │
│   [ Game Capture ]   [ AI Map Capture ]   [ Settings ]   [ Logs ]   │
│        legacy             new                                       │
│                                                                       │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│   Game Capture:   Connection / Trajectory / Bridge / OBS / Gallery   │
│                                                                       │
│   AI Map Capture: Project / Scene Spec / Capture Plan / Batch / Logs │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

### 6.2 AI Map Capture 主界面分区

| 分区 | 字段 |
|------|------|
| **Project** | `.uproject` 路径、UE 版本检测、PCG 插件状态、MRQ 插件状态 |
| **Scene Spec** | 自由文本输入（"城市夜景, 行人追逐"）→ LLM 生成 → JSON 预览 + 手动编辑 |
| **Asset Sources** | Fab 凭证、本地 Megascans 库、AI 3D 生成 API key (Tripo / Meshy) |
| **Actors & Behaviors** | 可选 actor 类、行为模板（wander / chase / flee）、Convai/Inworld 启用 |
| **Capture Plan** | MRQ preset、render passes 勾选、camera rigs、duration、fps、variants 数、seed 列表 |
| **Batch** | 启动按钮、进度（M/N 场景）、单场景耗时统计、失败重试 |
| **Output** | session dir、format (WebDataset / Parquet)、上传目标 (S3 / OSS) |

### 6.3 共享基础设施

| 模块 | 现状 | AI Map Capture 复用方式 |
|------|------|------------------------|
| `web_ui.py` Flask | OK | 新增 `/api/ai_map/*` 路由组 |
| `configs/` | OK | 新增 `configs/ai_map_sessions/` |
| `output/<session>/` | OK | 复用结构，加 `scene_spec.json` 入口 |
| `utils/feishu_notify` | OK | 批产完成发通知 |
| Three.js 轨迹可视化 | OK | 复用作 camera rig 预览 |
| `drivers/` | RenderDoc/bridge 专用 | **不复用**；AI Map 模式直接 Python 调 UE Editor |

### 6.4 后端模块新增

```
captureAIshi/
├── web_ui.py
├── ai_map/                          ★ 新模块
│   ├── __init__.py
│   ├── llm_orchestrator.py          ← L1: NL → scene_spec.json
│   ├── ue_bridge.py                 ← 跟 UE Editor Python 通信
│   ├── scene_validator.py           ← scene_spec.json schema + 资产预检
│   ├── mrq_runner.py                ← 派 UnrealEditor-Cmd 跑 MRQ batch
│   ├── dataset_writer.py            ← L5: MRQ 出帧 → WebDataset/Parquet
│   └── prompts/
│       ├── nl_to_spec.md
│       └── pcg_parameter_catalog.md
├── ue_plugins/                      ★ 新（如果做 UE 插件）
│   └── CaptureAIshiBridge/
│       ├── Source/
│       │   └── ...                  ← UE 插件 C++，暴露 Python API
│       └── Content/
│           └── PCGGraphs/
│               └── ...              ← 标准化 PCG graph 库
└── unreal_projects/                 ★ 新（标准模板项目）
    └── DataFactory_Template/
        └── DataFactory_Template.uproject
```

---

## 7. 分阶段路线图 (Phased Roadmap)

### 阶段总览：约 6 个月，5 个 milestone

| Phase | 主题 | 工期 | 关键产出 |
|-------|------|------|---------|
| **0. 收尾旧线** | 修 RenderDoc trajectory + UI 整合 | 1 周 | Game Capture 模式稳定，停止新增功能 |
| **1. 技术 spike** | 端到端最小 demo：手写 spec → MRQ → 1 帧 4D | 3 周 | 跑通一帧，验证管线无大坑 |
| **2. AI Map MVP** | LLM 编排 + 一个 PCG biome + 1 类 actor | 6 周 | 单场景 100 帧批产可用 |
| **3. 规模化** | World Partition / 大世界 / 资产管理 / 多机位 | 8 周 | 大规模批产、变体扫描 |
| **4. 商业化** | Cosmos 后处理 / S3 上传 / 客户 SaaS 界面 | 8 周 | 对外可演示版本 |

### Phase 0 — 旧线收尾（1 周）

P0 阻断项（来自 unicap × bridge review）：
- 实现 `__cam_rdc_capture` handler 或回退方案（2-4h）
- UI 加 `injection_mode` 下拉 + `create_grabber()` 工厂（1.5h）
- `trajectory_player.py` 用 `isinstance` 替换字符串 type 检测（0.5h）
- Batman / StackOBot 回归验证（2h）

收尾后**冻结 Game Capture 模式**，只接 P0 bug fix。

### Phase 1 — 端到端 Spike（3 周）

目标：证明"UE Editor + MRQ + Python 编排"管线没有不可逾越的坑。

**Week 1 — UE 项目模板**
- 装 UE 5.6 + Python plugin + MRQ + PCG + PCG Biome
- 创建 `DataFactory_Template.uproject`
- 配一个最小 PCG graph（生成 100 棵树 + 10 个 cube 角色）
- Sequencer 配 30 秒、相机环绕
- 手工跑一次 MRQ，确认出 EXR (Color / Depth / Normal / Cryptomatte)

**Week 2 — Python 后处理**
- `ai_map/dataset_writer.py` v0：读 MRQ EXR + Sequencer JSON dump → 写训练就绪 JSON
- 用 `OpenEXR` Python 库读多层 EXR
- 验证 Object ID → 我们的 actor 列表对得上
- 写 `manifest.json`：每帧 camera pose / actor poses / gameplay tags

**Week 3 — 命令行批产**
- `ai_map/mrq_runner.py` v0：`subprocess.Popen([UnrealEditor-Cmd.exe, ..., -run=MovieSceneCapture])`
- 一次跑 3 个 variant（不同 seed），全部出图
- captureAIshi UI 加 "AI Map Capture" tab 骨架，按钮调 mrq_runner

**Spike 验收**：UI 点一下，5 分钟后 output/ 出现 30s × 3 variants 的 4D 数据。

### Phase 2 — AI Map MVP（6 周）

目标：自然语言 + 单 biome 完整闭环。

| 周 | 内容 |
|---|------|
| 1 | LLM orchestrator：prompt 工程 + scene_spec schema + 验证回环 |
| 2 | PCG biome v1：城市夜景模板（建筑、路灯、车辆静态摆放） |
| 3 | Actor 模板：BP_Pedestrian（wander）+ BP_Pursuer（chase）+ BP_Target（flee）+ GameplayTag 标注 |
| 4 | UI 完善：scene_spec 文本框 + JSON 预览 + 手动编辑 + 资产预检反馈 |
| 5 | 多机位 camera rig：third-person、top-down、cinematic track |
| 6 | 整合测试：从"城市夜景, 行人追逐"一句话到 100 帧出数据 |

**MVP 验收**：客户给一句话，我们一小时内交付 100 帧带完整 ground-truth 的训练数据。

### Phase 3 — 规模化（8 周）

| 周 | 内容 |
|---|------|
| 1-2 | World Partition 大世界 + 流式 PCG，公里级场景 |
| 3-4 | 资产管理：Fab 同步、本地索引、AI 3D 生成 fallback |
| 5-6 | 批产引擎：variant matrix（天气 × 时段 × 角色密度 × 相机），并行任务调度 |
| 7-8 | 分布式跑批：多机 UE 集群，统一任务调度（Celery / Ray） |

**验收**：单任务 10k 帧、跨 100 个 variant、24 小时内完成。

### Phase 4 — 商业化（8 周）

| 周 | 内容 |
|---|------|
| 1-2 | NVIDIA Cosmos Transfer 集成：MRQ 输出 → Cosmos → photoreal 视频 |
| 3-4 | S3 / OSS 上传 + 客户专属 bucket + 元数据索引 (Parquet) |
| 5-6 | 客户 SaaS 界面：项目管理、配额、计费、API key |
| 7-8 | 数据集 marketplace：常用模板（自驾、零售、安防）打包售卖 |

---

## 8. 风险与缓解 (Risks & Mitigations)

| 风险 | 影响 | 缓解 |
|------|------|------|
| LLM 生成 scene_spec 总有边缘 case 出错 | L1 不稳定 | Schema 严格校验 + UE 预检反馈 + LLM 自动重试 + 人工 review 兜底 |
| MRQ 大场景渲染慢（path tracer 分钟/帧） | 算力成本 | 默认 raster 模式，path tracer 只在客户要求时开 |
| Fab Megascans 2025 起收费 | 资产成本 | 评估订阅 vs AI 3D 生成成本曲线，混合使用 |
| UE 5.6/5.7 升级破坏管线 | 维护成本 | 锁版本，CI 跑 smoke test，半年评估升级 |
| Verse 还没出 UEFN | 不能用 Verse | 全栈 Blueprint + Python，未来 Verse 出了再迁移 |
| Python 只能在 Editor 用，不能 runtime | 影响打包版能力 | 不打包，永远在 Editor 模式跑（headless commandlet） |
| 客户要求"和某游戏一样的画风" | 风格匹配难 | 保留 Game Capture 模式做风格参考池 |
| UnrealGenAISupport 社区维护风险 | 单点依赖 | 抽接口层，底层可换 |
| 自研 prompt → schema 不通用 | 客户场景多样 | 分领域 prompt template (自驾/零售/安防/游戏) |
| MetaHuman EULA 限制商用 | 法务 | 已确认 EULA 允许任何引擎 + 商用，但建议年度法务复审 |

---

## 9. 产业对标与差异化定位

| 玩家 | 引擎 | 主打场景 | 定位 |
|------|------|---------|------|
| **NVIDIA Cosmos** | 自研 | 通用 world model | 下游消费者，吃我们这种数据 |
| **NVIDIA Isaac Sim** | Omniverse/USD | 机器人 | 我们的对手，但聚焦机器人 |
| **CARLA UE5** | UE 5.5 fork | 自动驾驶开源 sim | 开源，但只做自驾 |
| **ProcTHOR** | Unity (AI2-THOR) | 室内场景 benchmark | 学术，规模小 |
| **Parallel Domain** | 自研 | 自驾合成数据 | 商业对手，估值高 |
| **Datagen / Synthesis AI** | 自研 | 人脸 / 室内 | 商业对手，垂直领域 |
| **captureAIshi (我们)** | **UE 5.6+** | **通用 4D 训练数据** | **差异化**：UE 生态 + AI-native UI + 中文市场 |

**我们的差异化**：
1. **UE 生态**：Fab / MetaHuman / Substrate / PCG 直用，画质起点比 Unity-based 玩家高
2. **AI-native 流程**：自然语言驱动是头部玩家也还在 demo 阶段的能力
3. **从破解工具进化**：拥有真实游戏画风参考池，做风格匹配有先发优势
4. **中文市场**：国内自驾/具身智能/视频生成大模型团队是天然客户
5. **完整 4D**：不只是图像，是 RGB + Depth + Normal + 相机/角色轨迹 + Action 标签

---

## 10. 待定决策 (Open Decisions)

需要你拍板的：

1. **UE 版本锁定**：5.6（稳定）vs 5.7（新功能多但刚出）vs 跟踪 5.x 最新
2. **是否做 UE 插件**：自建 `CaptureAIshiBridge` C++ 插件 vs 纯 Python 脚本
3. **LLM 选型**：Claude 4.7 Opus（推荐，推理能力强）vs GPT-5 vs 开源（DeepSeek/Qwen，可本地化）vs 多模型路由
4. **资产策略**：Fab 订阅全包 vs 按项目购买 vs AI 3D 生成为主
5. **Photoreal 后处理**：v1 就接 Cosmos vs v2 再说
6. **目标客户**：先做自驾 / 具身智能 / 视频生成 / 通用？影响 phase 2 biome 选择
7. **部署形态**：客户本地装 UE + captureAIshi vs SaaS 云渲染 vs 混合
8. **定价模型**：按帧数 / 按场景模板 / 订阅 / API 调用次数

---

## 11. 立即行动项 (Next Actions)

待你批准本路线图后立即可启动：

1. **Phase 0 收尾**（本周内可完成）
   - 修 RenderDoc `__cam_rdc_capture` 缺口
   - UI 加 `injection_mode` 下拉
   - 回归 Batman / StackOBot
2. **Phase 1 准备**
   - 装 UE 5.6 + 必需插件，建模板 `.uproject`
   - 派一个 agent 写 `ai_map/llm_orchestrator.py` 的 prompt 工程 spike
   - 调研 NVIDIA Cosmos Transfer 2.5 的输入 schema（决定 L4 输出格式时要参考）
3. **同步给 Cloud Design**
   - 把本文档转为 PPT 大纲（§1 战略动机 → §2 愿景 → §3 架构 → §7 路线图 → §9 对标）
   - 关键 visual：§2 愿景图、§3 五层架构图、§7 阶段甘特图、§9 对标矩阵

---

## 12. 附录：术语对照（PPT 用）

| 中文 | 英文 / 缩写 | 一句话定义 |
|------|------------|-----------|
| 程序化内容生成 | PCG (Procedural Content Generation) | 节点图驱动的程序化场景生成框架 |
| 影片渲染队列 | MRQ (Movie Render Queue) | UE 内置的多层、确定性、高质量渲染输出工具 |
| 4D 数据 | 4D Data | RGB + Depth + Normal + Camera 轨迹 + 角色轨迹 + Action 时序数据 |
| 真值数据 | Ground Truth | 像素级精确的标注数据，用于监督学习 |
| 演员 | Actor (UE 术语) | 场景中任何可操控的实体，玩家、NPC、道具均是 |
| 序列编辑器 | Sequencer | UE 的电影级时间轴编辑器，确定性回放的基础 |
| 角色控制器 | Mover 2.0 | UE 5.6+ 的下一代角色运动框架 |
| 动作匹配 | Motion Matching | UE 5.4+ 的动画选择算法，从动作库选最匹配的片段 |
| 虚幻人 | MetaHuman | Epic 的逼真人物角色系统 |
| 世界分区 | World Partition | UE 的大世界流式加载方案 |
| 美术集市 | Fab | Epic 2024 统一资产市场（取代 UE Marketplace + Quixel） |
| 高质量扫描 | Megascans | Quixel 的高精度真实世界扫描资产库 |
| 神经网络引擎 | NNE (Neural Network Engine) | UE 内置的 ONNX 推理引擎 |
| 高斯泼溅 | 3DGS (3D Gaussian Splatting) | 用高斯分布表示的新型 3D 重建技术 |
| Cosmos | NVIDIA Cosmos | NVIDIA 的世界基础模型，吃 depth/normal/seg 输出 photoreal 视频 |

---

**附录 A：调研引用源**（共 32 条 URL，原始调研报告见 `agents/research/ue_ai_capabilities_2026-05-12.md`，待落盘）

**附录 B：术语决定**：本文 "AI Map Capture" / "AI 定制化地图 Capture" 为 captureAIshi 新模式正式名称（用户语料）；英文 "Data Factory Mode" 备选。
