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

## 9. 7 项关键决策点（需你拍板）

| # | 决策 | 选项 | 我的倾向 |
|---|------|------|---------|
| 1 | **首发垂直** | 仓储 / 通用人形 / 工业制造 / 家居 | **仓储**（资产简、客户钱多、任务清晰） |
| 2 | **机器人本体** | 通用 6-DoF / FRANKA Panda / UR5 / 客户自带 | **FRANKA**（学术标杆，Isaac Lab 默认支持） |
| 3 | **物理引擎** | UE PhysX 5 / UE Chaos / 嵌 PhysX SDK / Mujoco | **嵌 PhysX 5 SDK**（与 Isaac Sim 同源） |
| 4 | **Cosmos 集成时机** | Phase 1 通 / Phase 3 接 / 不接 | **Phase 3**（GPU 成本高，先验客户用例） |
| 5 | **核心 IP 重心** | LLM→场景 / 物理标注 / 资产自动化 / SaaS 工作流 | **物理标注 + SaaS 工作流**（壁垒 + 售卖载体） |
| 6 | **NVIDIA 关系** | 纯产品对接 / Inception 加入 / 联合 GTM / 啥也不做 | **Inception → 联合 GTM**（免费 GPU + PR 资源） |
| 7 | **国内外节奏** | 先国内 / 先海外 / 并行 | **先国内**（语言地理客户决策快） |

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
