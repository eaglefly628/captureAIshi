# Robotic Scene Foundry — 机器人合成数据工厂战略 Pitch

**Date**: 2026-05-12 • **Status**: Draft v1 / for Claude Design PPT • **Author**: 主程序员

> **TL;DR**：CaptureAIshi 二次聚焦——从「通用 AI 训练数据中心」收窄到「具身机器人合成数据工厂」。用 UE5 + PCG 量产室内/工厂级场景，输出物理 ground truth 4D 数据，直接对接 **NVIDIA Cosmos + Isaac Lab + GR00T** 三件套。客户从散户视频生成团队收敛到具身智能与仓储自动化公司，**客单价提升 50-100×**，销售周期一个月，销售可复制性高。

---

## 1. 为什么不做 OpenWorld，专吃机器人

```
                  OpenWorld 数据                 Robotics 数据
                  ─────────────                 ─────────────
   客户类型       散：自驾/视频/游戏/通用研究    集中：具身/物流/制造
   单价定位       $0.001-0.01 / 帧             $5-50 / task variant
   客户单笔       $1k - $10k                    $50k - $500k
   销售周期       数天                          一个月（含技术验证）
   单场景客户数   1                             N（同 SKU 复用）
   数据复杂度     大场景 PCG，资产规模重         房间级 PCG，物理与交互重
   渲染压力       城市级 long take              室内多视角，单帧快 5-10×
   物理真值       视觉为主                      6-DoF pose + grasp + contact + force
   下游技术栈     视频模型五花八门               Cosmos + Isaac Lab + GR00T 收敛
   IP 风险        部分场景靠近游戏 IP            工厂/仓库/家庭室内，原创
   客户验证周期   模型训练 weeks                 真机或仿真验证 days

   →  我们押注：机器人合成数据正处供给侧空白 + 需求侧爆发的窗口期
```

**核心市场判断**：2025 年 NVIDIA 公布 Cosmos 战略后，下游需求爆发，但合成数据供给侧大家都还在搭积木。**先入者拿单**。

---

## 2. 新定位与品牌

| 项 | 旧 | 新 |
|----|----|-----|
| 中文名 | AI 训练数据中心基站 | **机器人合成数据工厂** |
| 英文名 | AI Training Data Hub | **Robotic Scene Foundry** |
| 一句话 | UE5 量产 4D 训练数据 | **UE5 量产 Cosmos / Isaac Lab 兼容的物理 ground truth 4D 数据** |
| 客户 | 通用 AI 团队 | 具身智能 / 仓储 / 制造业 |
| 上游 | 美术资产 | Fab + URDF 机器人库 + PhysX 5 |
| 下游 | 训练框架 | **NVIDIA Cosmos / Isaac Lab / GR00T** |

口号：*Natural language → photoreal factory scene → Cosmos-ready 4D + physics ground truth.*

---

## 3. NVIDIA Cosmos 对接关系

### 3.1 Cosmos 产品矩阵（截至 2025 年末）

| 产品 | 输入 | 输出 | 我们的对接点 |
|------|------|------|-----------|
| **Cosmos Predict 2.5** | image / video | 未来帧预测 | 提供训练数据 |
| **Cosmos Transfer 2.5** | depth + segmentation + normal + pose | photoreal 视频 | **MRQ 输出直接喂** |
| **Cosmos Reason 2** | video + 任务描述 | 决策推理 | 提供带标注的任务回放 |

### 3.2 关键技术匹配

Cosmos Transfer 吃的「**structured conditioning**」格式 = 我们 UE5 MRQ 多层 EXR 输出，**几乎 1:1 匹配**：

```
   我们的输出 (UE5 MRQ)              Cosmos Transfer 输入
   ──────────────────                ────────────────────
   World Depth (EXR R-ch)        →   depth conditioning
   World Normal (EXR XYZ)        →   normal conditioning
   Cryptomatte (Object IDs)      →   segmentation map
   Camera + actor pose (JSON)    →   pose / trajectory map
   Final Image (sRGB)            →   reference / ground truth
```

这不是巧合：NVIDIA 设计 Cosmos 时参考 Omniverse / Isaac Sim 的数据格式。我们用 UE5 出**比 Omniverse 更艺术化的场景**，然后吐 Cosmos-ready 数据。

### 3.3 我们 vs NVIDIA Omniverse / Isaac Sim 的差异化

| 维度 | Omniverse / Isaac Sim | **我们 (UE5)** |
|-----|---------------------|---------------|
| 场景源 | USD 原生 | UE5 (USD interop via 5.4+) |
| 艺术家生态 | 工业 / CAD 强 | **Fab + MetaHuman + Substrate，艺术化场景压倒** |
| 角色质量 | 有限 | **MetaHuman 内置，行业最强** |
| 物理 | PhysX 5 原生 | PhysX 5 嵌入（与 Isaac 同源） |
| 渲染 | RTX 实时 | **Lumen + Path Tracer + MRQ，电影级** |
| 资产量 | NVIDIA Asset Library | **Fab 全量（百万级）** |
| 数据格式 | Omniverse Replicator | **MRQ 多层 EXR + Cryptomatte（行业标准）** |

我们的卖点：**输 Omniverse 在 USD 原生这一条；赢在场景视觉质量、艺术家工具、资产库规模、电影级渲染、MetaHuman 角色**。

---

## 4. 目标技术架构

五层栈（机器人特化版）：

```
┌──────────────────────────────────────────────────────────────────────────┐
│ L5. Dataset Export & Serving                                              │
│     Cosmos-ready / Isaac-Lab-compatible 格式 + S3/OSS + 元数据索引        │
├──────────────────────────────────────────────────────────────────────────┤
│ L4. Physics-Grounded 4D Capture                                           │
│     MRQ 多层 EXR + PhysX 5 contact/force 事件 + Sequencer 确定性回放      │
├──────────────────────────────────────────────────────────────────────────┤
│ L3. Robot Control + Task Execution                                        │
│     URDF 机器人 + PhysX 5 articulation + 任务行为树 + GameplayTag 标注    │
├──────────────────────────────────────────────────────────────────────────┤
│ L2. Indoor Scene Assembly                                                 │
│     PCG (房间/工厂模板) + Fab 家具/工具 + AI 3D 杂物 + 光照预设           │
├──────────────────────────────────────────────────────────────────────────┤
│ L1. Task & Scene Spec from NL                                             │
│     LLM → JSON Spec: 场景 + 机器人 + 物体 + 任务 + variant matrix          │
└──────────────────────────────────────────────────────────────────────────┘
                                    ↓
                  NVIDIA Cosmos / Isaac Lab / GR00T
```

### 4.1 各层职责

| 层 | OpenWorld 版 (旧) | **Robotics 版 (新)** |
|---|---|---|
| L1 NL→Spec | PCG 城市参数 | **物体清单 + 任务描述 + variant matrix** |
| L2 Assembly | Megascans 城市 | **房间/工厂 PCG + Fab 家具 + AI 3D 杂物 + URDF 机器人** |
| L3 Actors | NPC + 车辆 | **URDF 机器人（articulation）+ 任务行为树** |
| L4 Capture | MRQ 长镜头 | **MRQ + PhysX 5 关节角时序 + contact / grasp / force 事件** |
| L5 Export | WebDataset | **Cosmos Transfer JSON + Isaac Lab HDF5 + custom Parquet** |

### 4.2 关键技术新点（vs OpenWorld 版）

1. **PhysX 5 集成**：UE5 内置，与 Isaac Sim 同源，物理结果可对齐
2. **URDF/USD 导入**：UE 5.5+ 内置 Robotics Plugin Suite
3. **关节状态时序导出**：每帧机器人 N-DoF 角度 + 速度 + 力矩
4. **Contact / Force ground truth**：PhysX 5 carry over，作为训练 supervision
5. **Task GameplayTag 标注**：用 Sequencer Event Track 打 task phase label（reach / grasp / lift / move / place）

---

## 5. 客户画像（具体到名字）

### 5.1 国内客户（PoC 目标）

| 客户 | 城市 | 需求 | 我们对接的痛点 |
|-----|-----|-----|---------------|
| **银河通用** | 北京 | 具身基础模型 | 通用 manipulation 数据，需多场景多任务 |
| **智元机器人** | 上海 | 人形 | 客厅/办公室/工厂 task 数据 |
| **宇树科技** | 杭州 | 四足 | 户外步行 + 室内避障 |
| **天工 / 国地中心** | 北京 | 具身创新中心 | 标准化数据集，对标行业 benchmark |
| **极智嘉 Geek+** | 北京 | 仓储机器人 | 货架 + 箱子 + 拣货 manipulation |
| **海康机器人** | 杭州 | 仓储 + 工业 | 工厂物流 + 巡检 |

### 5.2 海外客户（品牌曝光目标）

| 客户 | 国家 | 需求 |
|-----|-----|-----|
| **Skild AI** | 美国 | 通用具身基础模型 |
| **Physical Intelligence** | 美国 | 通用 manipulation |
| **Figure AI** | 美国 | 人形（与 BMW / OpenAI 合作） |
| **Agility Robotics** | 美国 | Digit 双足物流 |
| **1X** | 挪威 | 人形 NEO |

### 5.3 客户洞察

每家头部具身公司目前用 $10M-$100M 规模采集真机数据。**合成数据成本是真机的 1/100**，且能覆盖危险/罕见场景。我们价值定位：**让客户单位预算的训练 task coverage 提升 10-100×**。

---

## 6. 工具选型矩阵（机器人特化）

| 管线阶段 | 选型 | 成熟度 | 与机器人相关性 |
|---------|------|--------|----------------|
| NL → Task Spec | LLM + 自研 schema | **DIY** | 核心 IP |
| 室内 PCG | UE 5.6+ PCG + 自研 biome | Production | 房间/工厂模板需新做 |
| 资产库 | Fab + AI 3D (Tripo3D, Meshy) | Production | 家具/工具/杂物 |
| 机器人模型 | URDF (FRANKA, UR5, Boston Dynamics) | Production | 学术 + 工业标准 |
| 物理引擎 | UE 内置 PhysX 5 | Production | 与 Isaac Sim 同源 |
| 角色控制 | UE Articulation + Mover 2.0 | Production | 关节驱动 |
| 任务行为 | Behavior Tree + State Tree | Production | reach/grasp/place |
| 4D 捕捉 | MRQ 多层 EXR + Cryptomatte | **Production** | 行业标准 |
| 物理事件捕捉 | PhysX 5 callback + Python pass | DIY | 自研 |
| 数据集打包 | 自研 + WebDataset / HDF5 | DIY | Cosmos / Isaac 兼容 |
| Cosmos 对接 | Cosmos Transfer 2.5 API | Beta | v2 里程碑 |
| Isaac Lab 对接 | Isaac Lab Python API | Production | v1 必做 |

**关键发现**：80% 工具已成熟。**核心自研集中在 (1) NL→Spec、(2) 物理事件标注 pass、(3) Cosmos / Isaac 数据集 adapter**。

---

## 7. 分阶段路线图

### 总览：约 5 个月，4 个里程碑

| Phase | 主题 | 工期 | 关键产出 |
|-------|------|------|---------|
| **0. 旧线收尾** | RenderDoc trajectory P0 + UI 整合 | 1 周 | Game Capture 模式稳定 |
| **1. Spike + MVP** | FRANKA + 仓库一角 + pick-place 端到端 | 4 周 | 单 task 100 variant 出 4D 数据 |
| **2. 规模化** | 多场景模板 + 多机器人 + variant matrix | 8 周 | 5 类场景 × 10 类 task |
| **3. Cosmos / Isaac 商业化** | 数据集 adapter + 客户 PoC | 6 周 | 对外可演示 + 第一笔订单 |

### Phase 0 — 旧线收尾（1 周）

- P0: 修 RenderDoc `__cam_rdc_capture` 链路（已派 xiaoxuan，1-2h）
- UI `injection_mode` 下拉（1.5h）
- Batman / StackOBot 回归验证（2h）
- 冻结 Game Capture 模式，转维护态

### Phase 1 — Spike + MVP（4 周）

**目标**：仓库一角 + FRANKA Panda 抓箱子 → 端到端出 Cosmos-ready 数据

**Week 1 — 静态场景 + 机器人导入**
- UE 5.6 + Robotics Plugin Suite + PhysX 5
- 3m × 3m 仓库一角（货架 × 2 + 工作台 + 光照）
- FRANKA Panda URDF 导入 + Articulation 物理验证
- 3 类箱子（红/绿/蓝，3 种尺寸）

**Week 2 — 任务执行 + Sequencer 编排**
- 行为树：approach → grasp → lift → carry → place
- 任务参数化：起始 pose / 目标 pose / 物体类别
- Sequencer Event Track 打 task phase label
- 多机位：first-person (gripper cam) + side cam + top-down

**Week 3 — 物理标注 + 4D 输出**
- PhysX 5 contact event Python callback
- 关节角度时序 export（每帧 7-DoF）
- Cryptomatte → semantic class mapping
- 训练就绪 JSON 整合

**Week 4 — variant 扫描 + UI**
- 一个 spec → 100 个 variant（光照 × 起始 pose × 物体类别）
- captureAIshi 加 "AI Map Capture (Robotics)" tab
- 批产引擎跑 100 task variants × 30 frames = 3000 帧

**MVP 验收**：客户给一句"FRANKA 从货架第二层抓红盒到工作台"，我们一小时内交付 100 variant × 30 frames × 3 视角 = 9000 张带物理 ground truth 的 4D 数据。

### Phase 2 — 规模化（8 周）

| 周 | 内容 |
|---|------|
| 1-2 | 场景模板：仓库 / 厨房 / 客厅 / 办公室 / 工厂 |
| 3-4 | 机器人扩展：UR5 / Boston Dynamics Spot / 自定义 URDF 导入向导 |
| 5-6 | Task 库：pick-place / handover / pour / wipe / open-drawer / push-button |
| 7-8 | 批产引擎：variant matrix（场景 × 任务 × 机器人 × 光照 × 物体），分布式调度 |

### Phase 3 — Cosmos / Isaac 商业化（6 周）

| 周 | 内容 |
|---|------|
| 1-2 | Cosmos Transfer 2.5 集成：MRQ 输出 → Cosmos → photoreal 视频 |
| 3-4 | Isaac Lab HDF5 adapter：直接出 Isaac Lab 训练就绪格式 |
| 5-6 | 客户 PoC：银河 / 智元 / 极智嘉 二选一签 PoC，跑出第一份 deliverable |

---

## 8. 商业模型

### 8.1 定价单位

| 单位 | 含义 | 价格区间 |
|------|------|---------|
| Task SKU | 单个抓取/操作任务（如「从货架抓箱」）| $50k-$500k / 项目 |
| Variant | 单 task 的一个 variant（光照/起始 pose 等）| $5-$50 / variant |
| Scene Template | 可复用的场景模板（如「3m×3m 仓库」）| $20k 一次性 + $1 / 使用 |
| API 调用 | 按帧计费（量大客户） | $0.001-$0.01 / 帧 |

### 8.2 收入构成

```
   Phase 3 末预期 (Q4 2026):
   ┌────────────────────────────────────────────┐
   │  PoC 项目 (3 客户 × $100k)        $300k     │
   │  Scene Template 授权 (5 × $20k)   $100k     │
   │  Variant 增量销售                  $50k     │
   │  ─────────────────────────────────────────  │
   │  季度总额                          $450k    │
   └────────────────────────────────────────────┘
```

### 8.3 客户复用性（关键卖点）

同一份「仓库 + FRANKA + pick-place」task SKU 可同时卖给：
- 银河通用（通用具身）
- 智元（人形手臂版）
- 极智嘉（仓储专用）
- 海康（工业版）

每家客户拿到的是同一基础数据 + 各自定制 variant。**单 SKU 卖 4 次，毛利 75%+。**

---

## 9. 7 项关键决策（已锁定 2026-05-12）

| # | 决策 | **最终方案** | 关键含义 |
|---|------|--------------|---------|
| 1 | 首发垂直 | **通用人形机器人** | 目标市场是 Skild / Figure / 1X / 银河 / 智元 / 智源等。Phase 1 spike 仍用 FRANKA 单臂做 manipulation 验证，作为人形上肢的简化代理 |
| 2 | Phase 1 机器人本体 | **FRANKA Panda 7-DoF** | 学术标杆，Isaac Lab 默认支持。Phase 2 起加 UR5 + 自定义 URDF + 客户人形 |
| 3 | 物理引擎 | **嵌入 NVIDIA PhysX 5 SDK** | 与 Isaac Sim 同源，下游验证省力。Phase 1 Week 1 加 C++ 集成工作（约 3-5 天） |
| 4 | Cosmos 集成时机 | **Phase 3 接入** | Phase 1/2 先专心做 UE → Cosmos-ready 4D 数据格式，不调 Cosmos API。Phase 3 视客户 PoC 需求上 |
| 5 | 核心 IP 三大重心 | **物理标注准确性 + LLM→Spec 提示工程 + 资产库自动化** | 走"深度技术"路线（NOT SaaS UX）。意味着研发为主，论文 + 开源 + 标杆数据集为壁垒形式 |
| 6 | NVIDIA 关系 | **先加 Inception → 谈联合 GTM** | 本周提交 Inception 申请；Phase 2 跑出 PoC 后启动联合发布对话 |
| 7 | 国内外节奏 | **国内海外并行** | Phase 3 同时跑两条 GTM。意味着所有外发素材双语化，Phase 2 起补 EN 案例研究 |

### 9.1 决策组合的深层含义

| 信号 | 含义 |
|------|------|
| 通用人形 + 嵌 PhysX 5 SDK | 不做轻量级 SaaS，做**工程深度产品**，对标 Parallel Domain 而非 Datagen |
| 核心 IP 选物理 + LLM + 资产，**未选 SaaS 工作流** | 公司定位是"研发驱动技术供应商"，**不是产品化 SaaS**。客户接入更多通过 API + 数据集授权而非 web UI 自助 |
| 并行国内外 | 团队需配置：国内销售 + 海外学术营销（NeurIPS / CoRL / ICRA 投稿 + Skild/Figure 触达）|
| Inception → 联合 GTM | NVIDIA 是"放大器"而非"渠道"。我们独立运营，但用 NVIDIA 品牌力做 PR 与流量 |

### 9.1.5 决策修订（2026-05-12 第二批，覆盖原 §9）

第一批决策后追加 4 项，**部分覆盖原决策**：

| # | 原决策 | **修订后** | 影响 |
|---|--------|------------|------|
| 4. Cosmos 时机 | Phase 3 接入 | **🔴 Phase 1 立刻接** | MVP 必须包 Cosmos Transfer photoreal 输出。技术风险 + GPU 成本前置。Inception 申请必须本周提 |
| Phase 1 场景 | 单仓库（隐含）| **🔴 多场景同推** | 工时翻倍至少。需同时立 3 类模板（仓储 / 人形家居 / 工业）做缩水版 spike |
| 物理引擎 | 嵌 PhysX 5 SDK in UE | **🔴 UE + Isaac Sim 双轨** | UE 做场景+视觉，Isaac Sim 做机器人物理，USD 互通。架构层次大幅扩展 |
| 机器人资产 | （未定）| **自带 URDF 优先** | 工程简，FRANKA Panda + Unitree H1 + UR5 公开 URDF 入手 |

#### 修订带来的架构变化

```
┌──────────────────────────────────────────────────────────────────────────┐
│  ★ 新双轨架构 (修订后)                                                     │
│                                                                            │
│  ┌─────────────────────┐         USD              ┌──────────────────────┐ │
│  │   UE5 (场景层)       │  ◄──────────────────►   │   Isaac Sim (物理层)  │ │
│  │   PCG + Fab + 资产   │   双向同步              │   PhysX 5 + 机器人    │ │
│  │   MetaHuman + 光照   │                          │   articulation        │ │
│  │   MRQ 多层 EXR        │                          │   接触 / 力 / 关节   │ │
│  └─────────────────────┘                          └──────────────────────┘ │
│              ↓                                              ↓               │
│   RGB / Depth / Normal / Cryptomatte           contact / force / pose       │
│              ↓                                              ↓               │
│              └───────────┬──────────────────────────────────┘               │
│                          ▼                                                  │
│              ┌──────────────────────┐                                       │
│              │  NVIDIA Cosmos       │                                       │
│              │  Transfer 2.5        │   ← Phase 1 立刻接                    │
│              │  (photoreal video)   │                                       │
│              └──────────────────────┘                                       │
└──────────────────────────────────────────────────────────────────────────┘
```

#### Phase 1 工时重估（4 周 → 8-10 周）

| 周 | 内容 |
|---|------|
| 1 | NVIDIA Inception 申请 + Isaac Sim 环境搭建 + UE 5.6 + Robotics Plugin |
| 2 | UE 三类场景 PCG 缩水模板（warehouse / 客厅 / 工业一角）|
| 3 | FRANKA Panda 在 Isaac Sim 跑 manipulation + USD 导出场景到 UE |
| 4 | UE ↔ Isaac Sim USD 同步管线 + Sequencer 编排联动 |
| 5 | MRQ 多层 EXR + Isaac Sim 物理事件时序合并写出 |
| 6 | Cosmos Transfer 2.5 API 接入，从 4D 数据生成 photoreal 视频 |
| 7 | 三场景各 30 frames × 5 variants 端到端跑通 |
| 8-10 | 调试 + 客户 demo 包装 + buffer |

**风险点**：USD 双向同步管线（UE ↔ Isaac Sim）是已知工程黑洞，NVIDIA Omniverse 跑了 4 年还没完全打磨平。预留 2-3 周 buffer。

#### 修订后的工作排序

```
本周必做（无依赖）：
  □ 提 NVIDIA Inception 申请（Cosmos GPU 资源 + 技术对接，2-4 周批准期）
  □ 装 Isaac Sim 5.0 + UE 5.6 + Robotics Plugin
  □ 拉 FRANKA Panda + Unitree H1 + UR5 三套 URDF
  □ 派 spike agent 验证 UE ↔ Isaac Sim USD 互通最简 demo
  □ 修 RenderDoc P0（已派 xiaoxuan）

不再做（修订）：
  ✗ UE 内嵌 PhysX 5 SDK（替换为 Isaac Sim 走全物理）
  ✗ Phase 3 才接 Cosmos（前移到 Phase 1）
  ✗ 单场景仓库 spike（改多场景同推）
```

#### 风险升级提示

修订后的 Phase 1 配置是**最大野心版**：
- 双轨架构（UE + Isaac Sim）= NVIDIA Omniverse 体系内的"专业级"做法
- 即刻接 Cosmos = 商业故事最强
- 多场景 = 客户面最广

代价：
- **Phase 1 工时翻倍**（4 周 → 8-10 周）
- **3 个外部依赖前置**（Inception 审批、Isaac Sim 学习曲线、Cosmos API 配额）
- **Plan B**：若 NVIDIA Inception 2 周内未批 / USD 双轨调通超过 4 周，回退到「Phase 1 MVP 单场景 + 单端 UE PhysX 5」，Cosmos 推迟到 Phase 2 末

---

### 9.1.6 业务边界收敛（2026-05-12 第三批，最终 scope）

**核心定调：我们是「UE 里跑机器人训练场景的 PCG 工厂 + 下游训练数据格式适配器」。我们不做机器人训练本身。**

这是对 §9.1.5 双轨架构的进一步收敛，避开训练侧的深坑。

#### 在做 / 不在做

| | **在做** | **不在做** |
|---|---------|------------|
| UE5 + PCG 场景批量生产 | ✓ 核心 | |
| MRQ 多层 EXR / Cryptomatte 导出 | ✓ 核心 | |
| Cosmos Transfer 2.5 photoreal 渲染 | ✓ 核心（Phase 1 接） | |
| 下游训练标准格式适配（LeRobot dataset / RT-X TFDS / Isaac GR00T schema / robomimic HDF5）| ✓ 加深对齐 | |
| 机器人 URDF 在 UE 内作运动学摆放（waypoint + 关节角度静态展示） | ✓ 够用 | |
| **Isaac Sim 物理仿真双轨** | | ✗ **从 §9.1.5 移除** |
| 机器人策略训练 / RL / 模仿学习 | | ✗ 客户自己跑 |
| 机器人控制栈 / ROS bag 输出 | | ✗ 不碰 |
| 接触 / 力 / 关节动力学求解 | | ✗ 不碰 |

#### 简化后的架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│  最终架构 (post-9.1.6)                                                     │
│                                                                            │
│   UE5 + PCG + Fab + MetaHuman + Sequencer                                  │
│            │                                                                │
│            ├── 机器人 URDF (kinematic only, 摆姿势用)                       │
│            │                                                                │
│            ▼                                                                │
│   MRQ 多层 EXR (RGB / Depth / Normal / Cryptomatte / motion vector)        │
│            │                                                                │
│            ├──► Cosmos Transfer 2.5 ──► photoreal video                    │
│            │                                                                │
│            ▼                                                                │
│   数据适配层 (我们的差异化)                                                 │
│   ├── LeRobot dataset (parquet + videos)                                   │
│   ├── RT-X TFDS schema                                                     │
│   ├── NVIDIA Isaac GR00T data schema                                       │
│   └── robomimic HDF5                                                       │
│            │                                                                │
│            ▼                                                                │
│   交付给客户 → 客户在自己的训练平台跑训练 (不归我们)                        │
└──────────────────────────────────────────────────────────────────────────┘
```

#### 价值主张更新

> 「世界模型 / 具身策略团队需要海量、可控、多样化、photoreal 的训练场景。我们用 UE5 PCG 工业管线 + Cosmos 渲染，按你要的下游数据格式（LeRobot / RT-X / GR00T / robomimic）直接交付数据集。你专注训模型，我们专注出数据。」

#### Phase 1 工时回缩（10w → 6w）

| 周 | 内容 |
|---|------|
| 1 | NVIDIA Inception 申请 + UE 5.6 + Robotics Plugin + Cosmos API 接入 |
| 2 | 三类场景 PCG 缩水模板（warehouse / 客厅 / 工业一角） |
| 3 | URDF kinematic posing（FRANKA Panda + Unitree H1 + UR5 静态摆放） |
| 4 | MRQ 多层 EXR 批量出图 + Cosmos Transfer photoreal video 端到端 |
| 5 | **数据适配器（核心差异化）**：LeRobot dataset + RT-X TFDS 二选一先打通 |
| 6 | 三场景各 30 frames × 5 variants 完整数据集 + 客户 demo 包装 |

Isaac Sim 暂不接，省 3-4 周工时和一条学习曲线。客户要物理仿真自己跑 Isaac Sim / MuJoCo / SAPIEN。

#### 修订后的本周必做

```
本周必做：
  □ 提 NVIDIA Inception（Cosmos GPU + Robotics Plugin 资源）
  □ UE 5.6 + Robotics Plugin（仅 URDF import + kinematic posing 用）
  □ 拉 FRANKA / H1 / UR5 URDF
  □ 调研三套下游数据格式 spec：LeRobot (HuggingFace) / RT-X (TFDS) / GR00T (NVIDIA)
  □ 找 2-3 个真客户聊「你们要什么格式」(Physical Intelligence / 1X / 银河通用 / NVIDIA Isaac team)
  □ 修 RenderDoc P0 (xiaoxuan)

不再做（再次收敛）：
  ✗ Isaac Sim 双轨物理仿真
  ✗ 任何训练侧实现（policy / RL / imitation learning）
  ✗ 机器人控制栈 / ROS / 实时仿真闭环
```

#### 风险也跟着降级

| 原风险 | 状态 |
|--------|------|
| Isaac Sim 学习曲线 | ✓ 消除 |
| UE ↔ Isaac Sim USD 双轨打通（Omniverse 黑洞）| ✓ 消除 |
| 训练侧坑无底洞 | ✓ 消除（不做） |
| **新风险：客户要的数据格式我们没覆盖** | ⚠ 缓解办法：本周做格式调研 + 客户访谈 |
| Cosmos GPU 配额 | 留存（Inception 审批） |

---

### 9.2 国产化备选：华为 Ascend + MindSpore 路线（宣讲用 Option）

**动机**：国内具身公司（银河 / 智元 / 宇树 / 智源 / 国地中心）面临两个现实约束 ——
1. **信创合规**：央国企客户与"具身国家队"明确要求训练算力国产化
2. **美国出口管制**：H100 / B100 在中国受限，Cosmos / Isaac Lab 直接落地中国云有壁垒

**我们的应对**：单一 NVIDIA 路线对中国市场是风险，**双轨设计可同时通吃 NVIDIA + 华为生态**。

#### 华为对标矩阵

| 层 | NVIDIA 方案 | **华为方案** | 我们的对接 |
|---|------------|-------------|----------|
| 训练算力 | H100 / B100 / GB200 | **Ascend 910B / 910C / 384 超节点** | 数据格式无关，两边都吃 |
| 训练框架 | PyTorch + CUDA | **MindSpore + CANN** | 输出 MindSpore data loader |
| 推理芯片 | Jetson / Drive | **Atlas 200 / 300 系列** | 数据集复用 |
| 仿真栈 | Cosmos + Isaac Lab + GR00T | **盘古具身大模型 + 华为云 ModelArts** | 提供 Pangu-Embodied 兼容格式 |
| 云平台 | Omniverse Cloud + DGX Cloud | **华为云 ModelArts + Atlas 集群** | 部署 docker 镜像双发 |
| 机器人 SDK | Isaac ROS | **OpenHarmony 机器人套件 / KaihongOS** | URDF 标准导出双轨 |

#### 数据格式天然兼容性（关键卖点）

我们的 4D 输出**完全是数值张量**（depth EXR、normal EXR、Cryptomatte segmentation、pose JSON）—— **不绑定任何 GPU 厂商或框架**。下游想用 PyTorch+CUDA 还是 MindSpore+CANN 都可以读。**这是我们与 NVIDIA Replicator 的核心差异**（Replicator 输出与 Omniverse / CUDA 深绑定）。

#### 工程工作量增量（小）

| 项 | 工时 | 何时做 |
|----|------|--------|
| MindSpore Dataset 适配层（封装我们的 4D EXR + JSON）| 3 天 | Phase 3 商业化阶段 |
| Pangu-Embodied 输入格式 adapter（与 Cosmos Transfer 对偶）| 5 天 | Phase 3，若有客户需求 |
| 华为云 ModelArts 部署 docker 镜像 | 2 天 | Phase 3 |
| 测试 Ascend 910B 跑通整套训练 demo | 5-10 天（含硬件协调）| 与第一个国央企客户 PoC 合并做 |

**总增量约 15-20 天**，但解锁的市场（央国企 + 国家队具身基础设施项目）规模远大于此。

#### 销售/宣讲口径

PPT 中提及的话术建议：

> *"我们的合成数据栈与训练框架无关 —— NVIDIA Cosmos + Isaac Lab 用户拿到的是 PyTorch/CUDA 格式；华为 Ascend + MindSpore 用户拿到的是 MindSpore + CANN 格式。客户不需要为算力选型妥协数据来源，也不需要为信创要求改换数据供应商。"*

#### 华为合作策略（与 NVIDIA Inception 并行）

| 阶段 | 动作 |
|------|------|
| Phase 1 | 内部技术准备：保持数据格式 framework-agnostic（默认做到）|
| Phase 2 | 加入华为云开发者生态 / 联系华为昇腾 ISV 合作伙伴计划 |
| Phase 3 | 与央国企客户（中车 / 国家电网 / 中石化等具身落地）做 PoC，借势进入华为推荐供应商目录 |
| Phase 4 | 申请加入"具身智能国家科技重大专项"配套工具链供应商 |

**风险点**：MindSpore + CANN 生态文档与 NVIDIA 比有差距，适配过程会踩坑。预留 buffer。

#### 决策建议

**"NVIDIA 主推 + 华为对标做选项"** —— Phase 1/2 不投资华为，但**全程保证不做单一栈绑定**；Phase 3 视客户来源决定是否启动 5-15 天的 Huawei 适配工作。**单笔央国企订单即可回本**。

---

## 10. 本周可启动（无依赖前置项）

四件事并行：

1. **修 P0**（已派 xiaoxuan）— 1-2h
2. **装 UE 5.6 + Robotics Plugin Suite** — 1 天
3. **拉 FRANKA Panda URDF + 1 货架 + 3 箱子资产**（Fab 找现成） — 2-3h
4. **派一个 agent 跑 spike**：上面三件凑 30 秒抓取动画 → MRQ 出 1 帧 4D + 关节角 + 接触事件 — 3 天

**Spike 验收**：能出一帧合格 4D + 物理数据，证明管线无大坑。Phase 1 顺势接 4 周到 MVP。

---

## 11. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| UE PhysX 5 与 Isaac Sim 物理参数不能精确对齐 | 数据无法直接用 | 嵌 NVIDIA PhysX 5 SDK 而非 UE 自带，确保同 ABI |
| MRQ 渲染慢拖累批产速度 | 成本 | 用 Lumen 默认（非 Path Tracer），云 GPU 按需启 |
| URDF 导入 UE5 工具链不成熟 | 阻断 Phase 1 | Phase 1 Week 1 第一时间验证；如果不行回退到手工 Pawn + Articulation |
| Cosmos 数据格式持续变化 | adapter 反复改 | adapter 抽接口层，每月跟踪 NVIDIA release notes |
| 客户「真机数据 vs 合成数据」之争 | 销售周期长 | 提供 sim2real gap 度量工具 + 第三方 benchmark 数据 |
| NVIDIA 自己推竞品（Omniverse Replicator） | 商业冲击 | 差异化在艺术家生态 + 场景质量，把 Omniverse 也当下游 |
| 客户要求私有部署 | SaaS 模型受限 | Phase 3 提供本地 docker + license 双轨制 |

---

## 12. PPT 关键视觉点（给 Claude Design 的提示）

建议的核心 visual 页面（按 PPT 流程）：

| Slide | 主题 | 视觉建议 |
|-------|------|---------|
| 1 | 战略转型 | 旧 logo → 新 logo（Game Capture → Robotic Scene Foundry） |
| 2 | 为什么聚焦机器人 | §1 对比表大图 |
| 3 | NVIDIA Cosmos 关系图 | §3.1 产品矩阵 + §3.2 1:1 匹配图 |
| 4 | 5 层架构 | §4 架构图（高对比色块） |
| 5 | 客户画像 | §5 logo wall（银河 / 智元 / Skild / Figure 等） |
| 6 | Phase 路线图 | §7 甘特图（4 个阶段、5 个月） |
| 7 | 商业模型 | §8.2 收入构成饼图 + §8.3 SKU 复用图 |
| 8 | 决策点 | §9 7 项决策清单（带我的倾向） |
| 9 | 本周行动 | §10 四件并行项的时间线 |
| 10 | 差异化 | §3.3 vs NVIDIA Omniverse 对比 |
| 11 | 风险 | §11 表格 |
| 12 | 一句话愿景 | 「Natural language → photoreal factory → Cosmos-ready 4D + physics ground truth」 |

---

## 13. 术语对照（PPT 用）

| 中文 | 英文 / 缩写 | 一句话定义 |
|------|------------|-----------|
| 具身智能 | Embodied AI | AI 与物理世界交互的智能形态，机器人是主载体 |
| 合成数据 | Synthetic Data | 仿真生成的训练数据，区别于真机采集 |
| 物理真值 | Physics Ground Truth | 物理引擎计算的精确数据（接触/力/关节角） |
| 关节自由度 | DoF (Degrees of Freedom) | 机器人关节数，FRANKA 7-DoF，人形 30+ DoF |
| 机器人描述格式 | URDF | Unified Robot Description Format，机器人本体定义标准 |
| 场景描述格式 | USD | Universal Scene Description，皮克斯发起的 3D 场景标准 |
| 任务编排 | Task Scheduling | 把抓取拆解为 reach/grasp/lift/place 子任务 |
| 世界基础模型 | World Foundation Model | NVIDIA Cosmos 等，输入条件 → 视频/未来帧 |
| 真到虚差距 | Sim2Real Gap | 仿真训练 vs 真实部署的性能差异 |
| 影片渲染队列 | MRQ (Movie Render Queue) | UE 内置高质量批产渲染工具 |
| 程序化内容生成 | PCG | UE 5.6+ 节点图驱动的场景生成框架 |
| 物理引擎 | PhysX 5 | NVIDIA 物理引擎，与 Isaac Sim 同源，UE 内置 |
| 神经网络引擎 | NNE | UE 内置 ONNX 推理引擎 |
| 标志性人物 | MetaHuman | Epic 高保真数字人系统 |

---

## 14. 与上一版 OpenWorld 路线图的关系

`docs/ai_data_center_roadmap.md`（v1）保留作为「通用方向参考」，但**主线收窄到本文档（Robotics 专用版）**。

差异：
- 上一版「自驾 / 视频生成 / 通用」目标 → 本版「具身机器人」
- 上一版「城市夜景生成」spike → 本版「仓库 + FRANKA」spike
- 上一版 6 个月路线图 → 本版 5 个月路线图（场景更小，迭代更快）
- 上一版「Cosmos 是 v2 可选」→ 本版「Cosmos / Isaac Lab 是核心下游」

**两版共用**：UE5 + PCG + MRQ 技术栈、captureAIshi UI 框架、80% 后端复用、Phase 0 旧线收尾。

---

**附录 A**：调研引用源见 `docs/ai_data_center_roadmap.md` 附录 A（NVIDIA Cosmos、Isaac、PCG、MRQ、Fab 等 32 条 URL）

**附录 B**：FRANKA Panda 资源
- 官方 URDF：https://github.com/frankaemika/franka_description
- UE5 导入指南：UE 5.5+ Robotics Plugin Suite 自带向导
- Isaac Lab FRANKA 配置：作为 Phase 1 物理对齐参考
