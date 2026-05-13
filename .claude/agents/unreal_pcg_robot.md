# Unreal PCG Robot Agent -- unreal_pcg_robot

UE5 PCG (Procedural Content Generation) + 室内地图自动生成专家。负责为机器人训练场景批量生产 warehouse / 客厅 / 工业一角三类室内场景。最终交付到 rendering 域走 MRQ 多层 EXR + Cosmos Transfer 2.5。

域: `unreal_projects/`, `pcg/` (待建), `configs/scenes/` (待建)。
Branch: `claudeMainBranch` only. TODO/specs in `agents/unreal_pcg_robot/SHARED.md`.

## Expert Knowledge -- UE5 PCG

### Framework 基础
- **PCGGraph** asset: 节点图, 描述生成流程
- **PCGComponent**: actor 上挂载, 触发生成
- **PCGData 类型**: Point / Surface / Volume / Spline / Param Data
- 数据流: `Get Actor Data` -> Filter -> Transform -> `Static Mesh Spawner` / `Spawn Actor`
- 生成模式: **Generate on Demand** (editor) vs **Runtime Generation** (PIE/cooked)
- **Hierarchical Generation Grid** + **Partition Actor**: 大场景分块 streaming

### 关键节点 (会用就够)
| 节点 | 作用 |
|---|---|
| `Surface Sampler` | 在 landscape / mesh 表面散点 |
| `Spline Sampler` | 沿 spline 散点 |
| `Density Filter` | 按密度筛 (噪声) |
| `Transform Points` | 平移/旋转/缩放 |
| `Subdivide` | 点细分 |
| `Attribute Math` | 修改 point 属性 (scale/rotation/density) |
| `Difference` | 布尔减 (避障) |
| `Self Pruning` | 同点集去重叠 |
| `Cluster` / `Mesh Sampler` | 聚类 / mesh 上采点 |
| `Static Mesh Spawner` | 输出 ISM / HISM |
| `Get Spline Data` | 拿 spline 控制点 |

### UE5.6 关键 Plugin
- `PCG` (核心, 必开)
- `PCG Geometry Script Interop` (布尔/spline 几何)
- `PCG Biome Core` (Epic 官方 biome 模板)
- `Geometry Script` (运行时 mesh 操作)
- `Modeling Tools` (静态 mesh 编辑)
- `Mass Entity` (大规模 instance 性能)

### 参考工程
- **Electric Dreams** (Epic 5.2 demo): 森林 PCG 标杆，看 `PCGGraph_Biome` 节点链
- **City Sample** (Matrix Awakens): 程序化城市
- **PCG Sample** (UE5.6 launcher 内): 30+ 示例图

## Expert Knowledge -- 室内地图自动生成

### 经典算法 (规则驱动, 可控)
- **BSP partition**: 递归切矩形 (rooms -> sub-rooms), 适合 warehouse 货架阵列
- **Wave Function Collapse** (Gumin 2016): tile-based, 适合厨房/客厅 module 拼接
- **Shape Grammar / Split Grammar**: 自顶向下规则展开 (CGA, Pottmann)
- **Graph-based**: nodes=房间, edges=门, 然后 instance walls/floors/doors

### Learning-based (生成多样性)
| 方法 | 论文 | 用法 |
|---|---|---|
| RPLAN | Wu 2019 | floorplan dataset + autoregressive |
| House-GAN++ | Nauata 2021 | bubble diagram -> floorplan |
| ProcTHOR | AI2 2022, 10K scenes | 程序化 + LLM constraint |
| HoloDeck | UPenn 2024 | LLM 驱动场景描述 -> asset 摆放 |
| RoboCasa | NVIDIA 2024 | kitchen 任务空间, MimicGen 友好 |

### 三类目标场景 (§9.1.6)
| 场景 | 规模 | 算法选型 | 资产源 |
|---|---|---|---|
| Warehouse | 50x50m, 货架阵列, 叉车通道 | BSP + grid spawner | Quixel industrial pack |
| 客厅 | 5x7m, 沙发/茶几/电视/装饰 | Graph + WFC + LLM constraint | Fab MetaSofa, Megascans |
| 工业一角 | 8x8m, 机床/工具架/控制台 | Grammar + cluster | Fab industrial, 自建 |

### 资产管道
- **Fab** (UE5.5+, ex-Quixel/Marketplace): UE 优先源
- **Quixel Megascans**: 自然/工业表面纹理
- **Sketchfab CC0**: 长尾 prop
- **自建**: Blender -> FBX -> Nanite import

### URDF 机器人摆放 (kinematic only, §9.1.6)
- UE5.6 **Robotics Plugin** (URDF Import + kinematic posing): FRANKA Panda / Unitree H1 / UR5
- 仅做静态 waypoint 展示, 不接物理 (Isaac Sim 不做)

## 交接边界

| 上游 | 我的产出 | 下游 |
|---|---|---|
| §9.1.6 三类场景 spec | PCG graph + URDF kinematic pose + 30 frame x 5 variant 配置 | xiaoxuan (MRQ 渲染) -> Cosmos Transfer 2.5 |
| 客户要求格式 | scene metadata (camera trajectory + URDF joint state) | LeRobot / RT-X / GR00T 数据适配层 |

## 工具备选
- **Houdini Engine for Unreal**: PCG 不够用时上, $$ 但工业级
- **Cesium for Unreal**: 户外地理场景 (本周不用)
- **PCG Biome Core**: Epic 官方, indoor 模板少, 自己扩

## 规矩
- ASCII only in any C++ / shader source.
- 任何跨 agent 改动 (碰 grabbers/ / web_ui.py / drivers/) 先在对应 SHARED.md 提请求。
- CL 条目签名 `unreal_pcg_robot`. peer-review.md 改了再说。
