# PCG Tech Artist's Guide (摘要 + 关键 insight)

> Source: Epic Dev Community "A Tech Artist's Guide to PCG" (Epic 工程师 Tech Artist 撰)
> 用户拷贴 2026-05-20
> 配套: `ue58_pcg_node_reference.md` (Epic 节点全 ref)
> 用途: 概念框架 + 最佳实践 + 不是 how-to 但讲 "why" 和 "what to do"
> URL (sandbox 不可达): https://dev.epicgames.com/community/learning/knowledge-base/KP2D/unreal-engine-a-tech-artists-guide-to-pcg

---

## §0 总观点：PCG 不是 forest tool

PCG 是**通用空间数据处理框架** (Spatial Data) 用来辅助你 augment workflow。Epic 用 Electric Dreams demo 误导了第一印象。实际用例覆盖:

- **场景生成**: 森林 / 仓库 / 室内布局 (我们 v0.4 仓库就是这条)
- **建筑细节化**: 程序化走廊 / 房间 / 工业内部
- **微散布**: 不需要 mainlevel actor 的细节
- **路径生成**: spline 路径 + 程序化布局
- **网格生成**: 几何驱动级别工具
- **天体环境**: 行星环 (Cassini Sample 用 PCG 生成土星环)
- **Runtime**: 不仅 editor, 也能跑 runtime / cook 提前 bake

设计假设: PCG 会进入大部分 UE 项目, 团队要会用。

---

## §1 基础概念框架

### Spatial Data vs Concrete Data vs Attribute Data

- **Spatial Data**: PCG 主要处理对象。常以 **Points** 形式表示。Landscape / Spline / Volume / Points 都是 Spatial Data。
- **Concrete Data**: Spatial Data 的"具体实例"。本质是 Spatial Data 的基类, 任何 Spatial Data 都能 decay 成 Points。
- **Attribute Data**: **不能转为具体点**的数据 (e.g. 一张 Data Table, 列 = Attribute)。用作"查找表"。**关键**: 不是 Spatial Data 子集!

### Concrete Data 怎么来 (root nodes)

- `Get Landscape Data` (Landscape)
- `Get Spline Data` (Spline)
- `Get Water Spline Data` (Water plugin)
- `Get Actor Data` (任意 actor, by class 或 tag) ← 我们 v0.4 用这个 (Self anchor PCG Volume)

### Actor Tag 隐藏功能

任意 actor 可以打**任意 string tag**, PCG 用 `Get Actor Data (by Tag)` 选。
- e.g. `"RemovePCG"` tag → PCG 知道这些 actor 区域需要剔除
- e.g. `"KeepVertical"` tag → 树不跟随地形法线 (避免歪树)
- e.g. `"Clutter"` tag → 随机过滤掉一些 asset

**对我们启发**: BP_DemoOrigin / PCG_Warehouse 都打 tag, MCP `SceneTools.find_actors(tag=)` 已用这套机制。

---

## §2 调试小技巧 (高频用)

| 快捷键 | 行为 |
|---|---|
| `D` (节点选中时) | 节点位置可视化 Debug. **持久**, 不像 transient debug 那样切节点就消失. **5.8 起所有用户必学** |
| `A` (节点选中时) | 显示该节点的 Attributes 面板 |
| Bottom-left PCG component selector | Debug 不显示时, 检查这里有没有选对 component |

### Sample Level 学习路径

PCG Content Plugin 自带 sample, 路径:

- `/PCG/SampleContent/SimpleForest/SimpleForest` — **从这开始**
- `/PCG/SampleContent/HiGenForest/HiGenForest` — Hierarchical Generation 实例
- `/PCG/SampleContent/Grammar/GrammarSample` — Grammar 规则示例
- `/PCG/SampleContent/FlatnessDetection/FlatnessDetectionLevel` — 平面性检测

**对我们启发**: 用户可以在 Editor 里打开这些 sample level 看现成 graph, 比看文档直观。**特别是 `SimpleForest`** 演示完后给客户做 polish 参考。

---

## §3 Workflow 三种模式

### Volume Based (默认, 我们 v0.4 用的)
拖 PCG asset 到 scene → 自动生成 PCG Volume → 定义生成区域。

### Component Based
PCG System 作为 Component 挂在 actor 上, **逻辑跟 actor 艺术分离**。
- 用例: 办公桌 actor + PCG component → 每张桌子上随机散布物件
- 对我们启发: v1 工业机械 = 一个 actor + 挂 PCG component 自动放置周边物件

### Activate From Other PCG Systems (高级)
PCG graph Output node 缓存输出。另一个 PCG graph 通过 `Get PCG Component Data` 读上游输出。
- 用例: macro PCG 收集多个 sub-biome 输出后融合
- **对我们启发**: 未来三场景 (warehouse / living_room / industrial_corner) macro 调度可以走这条
- 警告: Biome Core plugin 这套很复杂, 先掌握基础再碰

---

## §4 Level Instance 当 PCG 资产源 (高级 workflow)

不只是放 mesh, 可以放 **Level Instance** (一组预制 mesh 组合)。
- PCG → PCG Data Asset → 描述 Level Instance 的组件 + tag → spawn 时按这个组合放
- 比单 mesh 更"artist-driven" 但同时保留程序化变化
- **Actor Tag Data** 可被 PCG 读取 (e.g. `KeepVertical` / `Clutter`)
- Cassini Sample 的 KitBuilding PCG graph 演示了 PCG 自己生成 Data Asset

**对我们启发**:
- v1.5 真 Megascans 到位后, **直接 spawn 货架 mesh** vs **spawn 货架 + 货物 Level Instance** 两条路
- Level Instance 更高级但 artist polish 必须先做
- v0 demo 不必, 先 cube → v1 单 mesh → v1.5 Level Instance

---

## §5 Hierarchical Generation (HiGen, **未来不要错过**)

PCG 默认静态生成 (cache 所有点)。HiGen = **动态按距离生成**, 玩家走近才生 sub-grid 数据。

- `Grid Size` 节点指定 sub-grid 网格尺寸 (后置于某些节点后)
- 大物体 (树) → grid 3200
- 小物体 (草 / 花) → grid 800
- 启用条件: World Partition 开 + PCG graph 启用 Use Hierarchical Generation

**对我们启发**:
- v0.4 / v1 我们 room 30x30m 单 grid 足够, **不需要 HiGen**
- v2+ 如果展示 200x200m+ 大场景再开
- 演示话术: "v2 路线规模化时启用 HiGen, 800m 内详细 grid + 3200m 远 grid 分层 cache"

Example: `/PCG/SampleContent/HiGenForest/HiGenForest.HiGenForest`

---

## §6 Big Callouts (关键功能)

### 6.1 Projection / World Trace ★★★
- 用 `World Ray Hit Query` 或 `Projection` 把 points 投到其他数据上 (Landscape / mesh 表面)
- 不投 → mesh 浮空; 投 → 贴地
- 我们 v0.4 演示用 Surface Sampler 在 PCG Volume bound 内采样, **Surface 来自 Volume 本身**, 暂不需要单独 Projection。室外大场景必须用。

### 6.2 Custom PCG Nodes
- 三种自定义: Blueprint / C++ / PCG Subgraph
- v0/v1 不写 (老白 v0.3.3 决策: 不写 C++ Plugin, 走反射 ObjectTools)
- Subgraph 是合并复用利器, 8 个 stage 可以拆 8 个 Subgraph asset

### 6.3 Custom HLSL ★★
- Custom HLSL node = GPU 写自定义 shader 做点处理
- 复杂数学 / 循环 / 大规模处理 → GPU 比 CPU 快很多
- v3+ 数据规模化时考虑

### 6.4 Loops & Recursive Graphs ★★★
- **Loop**: 数据分片 → 子图每片处理 → 合并
- **Recursive**: graph 调自己 (while-loop 概念)
  - e.g. 植物递归生长: 大植物周围撒小植物, 小植物再撒更小, 直到 N 层
- v1+ 可考虑: 货架 → 货架上撒 pallet → pallet 上撒 box → recursive 派生

### 6.5 Grammar ★★ (Cassini Sample 用)
- 不用复杂节点, 用 **grammar 规则**: "每扇门两侧需要墙" / "底层 tag=GroundLevel, 顶层 tag=Roof"
- Sample: `/PCG/SampleContent/Grammar/GrammarSample.GrammarSample`
- Cassini Sample 生成空间站房间 + 走廊
- **对我们启发**: v2 仓库 / 客厅 / 工业一角的复杂 grammar 规则可以走这条 (e.g. shelf 之间必须有 aisle / forklift 不能停在通道中央)

### 6.6 Gather Node (5.5/5.6 有用, 5.6+ 自动)
- 让某节点等所有 dependency 完才执行
- 例: PCG-placed rock 已经 spawn 完, 才允许在 rock 上撒 PCG-placed ferns
- **5.6+ 节点本身加了 dependency 输入**, Gather 不那么必要
- 我们 v0.4 暂时不需要

### 6.7 Disregard Points on Irregular Surface (subgraph 示例)
- 多点共面性测试, 移除"挂在边缘"的 mesh
- 内部用 Union, **5.5 之前不显示顺序**, 5.6 修
- Sample: `FlatnessDetection`

### 6.8 Match and Set Attributes ★★★★ (我们最关心的)

> "let's you sample data from one attribute in a data set, find it in another data set, and then apply that data to the point"

具体用例 (官方原文):
> "save out the dimensions of a building tile type, give each point a random tile type, then look up the related tile information, and apply it based on the tile type string identifier"

特性:
- 支持"找最接近的 attribute"匹配 (nearest neighbor on float)
- 支持权重 (Match Weight Attribute)
- 数组随机分配 (no-match fallback)

**对我们启发**: 这正是 v1 多 mesh 类型时 (shelf/forklift/pallet/box/drum/worker) 的主架构:
- Data Table: rows = asset 类型, columns = asset_type / mesh_path / footprint_size / etc.
- Points 上有 `asset_type` attribute (从 Spatial Noise / Cluster / Density Filter 派生)
- Match And Set 节点把 mesh_path 从 Data Table 复制到 Points
- SM Spawner ByAttribute (attribute = "Mesh") spawn

**v0.4 单 mesh 时不必, 直接 Create Attribute (shelf_mesh) + Copy Attribute 即可。**

### 6.9 Isolines (高级)
- 从 Landscape 提取等高线 → 输出 point 或 spline
- v3+ 自然 / 地理场景

### 6.10 Custom Spline Metadata
- Water Plugin 的 Water Spline 自带 Custom Data (流速 / 河深 / 河宽 / Audio Volume)
- 项目可定制 Custom Spline Metadata, PCG 通过 plugin interop 读
- v2+ 我们的 robot navigation spline 可以加 Custom Data (e.g. priority / clearance / restricted_zone)

### 6.11 Pathfinding (新节点)
- 读 series of points → 之间生成 spline
- v2+ robot navigation 可以用

---

## §7 性能 (★★★ 演示前必懂)

### Static Mesh Spawner ≠ Static Mesh Actor
- SM Spawner **不创建 actor**, 而是 populate **ISM component** (Instanced Static Mesh)
- 运行时性能 ≈ painting foliage (非常便宜)
- **巨大区别**: 1000 个 cube actor 会卡, 1000 个 ISM instance 流畅

### 性能 checklist (我们演示前 review)

| Check | 影响 |
|---|---|
| **Collision** | 有 collision 比无 collision 重很多。v0.4 演示不需要 collision (cube placeholder), **关掉** |
| **GPU spawning** | 比 CPU 快, **但没 collision + 不进 Ray Traced scene**. v0.4 演示可考虑 |
| **Precache** for HiGen | HiGen 启用时, precache tagged data 减 runtime 开销. v0.4 不用 HiGen |

### Profiler 用法

`Window` 菜单 → **PCG Profiling tab** → 每个节点处理时间 → 找瓶颈
- 不显示就检查 bottom-left 选 PCG component

**对我们启发**: 演示前**在 RobotDemo2 跑一次 profile**, 确保 1 秒 generate 完, 客户聊"shelf 密度 0.9" 体验流畅。

---

## §8 资源进阶路径

### Epic 内置 Sample (装机就有)
1. `SimpleForest` ★ 入门
2. `HiGenForest` ★★ HiGen
3. `Grammar` ★★ 复杂规则
4. `FlatnessDetection` 平面性

### Epic 项目 Sample
- **Electric Dreams** (5.2 demo): 第一代 PCG, 现在算"老办法"
- **Cassini Sample**: 现代实现, 包括 KitBuilding (Level Instance + PCG Data Asset), Grammar (空间站房间), 行星环
- 推荐顺序: 先内置 sample → 再 Cassini → 最后 Electric Dreams (反向)

### Epic 工程师内容
- **Adrien Logut** (Epic Engineer) 出 PCG content, demo best practices
- 推荐看他的 introductory series

### 对我们演示后接力时的优先看清单
1. 当前 `SimpleForest` sample (5 分钟搞懂 Spatial Data + Surface Sampler + SM Spawner)
2. Cassini KitBuilding (理解 Level Instance + Match And Set 高级用法)
3. PCG Profiling tab (确认我们 graph 不卡)
4. Grammar sample (v2 我们要 architectural 规则时回看)

---

## §9 跟我们 v0.4 项目的直接映射

| Tech Artist Guide 概念 | 我们 v0.4 用法 | 对应 file |
|---|---|---|
| `Get Actor Data` (Self) → Spatial Data root | PG_Warehouse graph 第一个节点 | `pg_warehouse_graph_design.md` §2 |
| Surface Sampler on PCG Volume | shelf 阵列采样 | 同上 |
| Static Mesh Spawner (ISM) | shelf / forklift / etc. spawn | 同上 |
| Mesh Selector By Attribute (5.8 doc 确认存在) | v0.4 多 mesh 类型分流路径 | `ue58_pcg_node_reference.md` §15 |
| Match And Set Attributes (v1+) | 多 asset 类型从 Data Table 选 mesh | 同上 §10 |
| Actor Tag (PCG_Warehouse / demo_v0_spawned) | MCP find_actors 隔离边界 | `demo_v0_simplified_contract.md` §1 |
| PCG Profiling tab | 演示前确认性能 | 待跑 |
| `D` / `A` debug shortcut | 现场 troubleshoot | KB §1.x 加 entry |
| HiGen (高级, 不用) | v2+ 大场景规模化 | 不做 |
| Custom HLSL / BP Element (高级, 不用) | v3+ 自定义算法 | 不做 |
| Recursive Graphs (高级, 不用) | v2+ 递归布局 (e.g. 货架上 pallet 上 box) | 不做 |

---

## §10 Action Items for v0.4 演示前 (review by xiaohuan)

- [ ] Editor 内打开 `/PCG/SampleContent/SimpleForest/SimpleForest`, 看 5.8 实际 sample graph 节点连法 (验证我们的 PG_Warehouse 拓扑跟 sample 一致)
- [ ] 学会 `D` debug + `A` attribute panel 快捷键 → 卡壳时立刻自查
- [ ] **演示前**跑 `Window → PCG Profiling tab`, 确认 PG_Warehouse generate < 1s
- [ ] 演示前确认 SM Spawner 用的是 ISM (默认就是) + collision off (cube 不需要)
- [ ] **演示话术加 1 句** "PCG SM Spawner 内部走 ISM, 1000 个 cube spawn 跟 1000 个 grass 一样便宜, 大场景规模化用 HiGen 分层"
