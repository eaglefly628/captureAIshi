# captureAIshi -- 项目分析与开发路线图

> 版本: v0.2.0 | 日期: 2026-04-05 | 作者: captureAIshi 开发团队

---

## 目录

1. [项目定位](#1-项目定位)
2. [市场对标分析: captureAIshi vs UUU](#2-市场对标分析)
3. [技术架构现状](#3-技术架构现状)
4. [核心技术难点](#4-核心技术难点)
5. [竞争优势与护城河](#5-竞争优势与护城河)
6. [开发路线图](#6-开发路线图)
7. [团队与分工](#7-团队与分工)
8. [风险评估](#8-风险评估)

---

## 1. 项目定位

### 一句话

**captureAIshi 是面向 AI 训练数据生产的游戏场景自动化采集工具。**

### 核心思路

利用已发行的 3A 游戏作为"免费的 3D 数据源"，通过 RenderDoc 注入 + 自定义相机控制，从游戏中批量提取高质量的 RGB 图像、深度图、法线图及精确相机参数，为 3D 重建 (NeRF/3DGS)、深度估计、视觉导航等 AI 任务提供训练数据。

### 与现有工具的根本区别

```
UUU (Universal Unreal Unlocker)
  = 游戏摄影师的相机工具
  = 手动操作, 单张精修, 面向人类欣赏

captureAIshi
  = AI 训练数据工厂
  = 自动化批量采集, GBuffer 真值导出, 面向机器学习
```

---

## 2. 市场对标分析

### 2.1 UUU 概况

| 项目 | 详情 |
|------|------|
| 作者 | Frans "Otis_Inf" Bouma |
| 用户量 | ~31,900 Patreon 会员 |
| 月收入 | ~$23,500/月 |
| 定价 | $6.50/月 (Patreon) |
| 支持游戏 | UE4: 300-400+ 款, UE5: 持续增长 |
| 开源状态 | **闭源** (IGCS 开源, BSD-2) |
| 注入方式 | AOB 扫描自动定位引擎结构 |

### 2.2 功能对比矩阵

#### 相机与场景控制

| 功能 | UUU | captureAIshi | 对比 |
|------|:---:|:------------:|------|
| 6DOF 自由相机 | :white_check_mark: | :white_check_mark: | Bridge DLL ToggleDebugCamera |
| 相机路径/Dolly | :white_check_mark: | :white_check_mark: | Catmull-Rom + SLERP |
| 时间暂停 | :white_check_mark: | :white_check_mark: | `__timestop` 命令 |
| 游戏速度控制 | :white_check_mark: | :white_check_mark: | `__cam_speed` 命令 |
| HUD 隐藏 | :white_check_mark: | :white_check_mark: | 双方案: 控制台 + RenderDoc 过滤 |
| Hotsampling (分辨率) | :white_check_mark: | :white_check_mark: | `__hotsample` 命令 |
| FOV 控制 | :white_check_mark: | :white_check_mark: | 全链路支持 |
| 控制台命令解锁 | :white_check_mark: | :white_check_mark: | GEngine->Exec() 直通 |
| Actor 操控 (移动/隐藏) | :white_check_mark: Patreon | :x: | 未实现 |
| 灯光创建/控制 | :white_check_mark: Patreon | :x: | 未实现 |
| DoF/后处理艺术控制 | :white_check_mark: | :x: | **不需要** (AI 数据不做艺术后处理) |

#### AI 数据采集 (captureAIshi 独有)

| 功能 | UUU | captureAIshi | 说明 |
|------|:---:|:------------:|------|
| **RGB 图像导出** | :camera: 截图 | :white_check_mark: SceneColor | 无 UI overlay 的纯场景图像 |
| **深度图导出** | :x: | :white_check_mark: D32F | 逆向 Z, 百分位归一化 |
| **法线图导出** | :x: | :white_check_mark: RGB10A2 | 世界空间法线 |
| **相机内参导出** | :x: | :white_check_mark: | FOV, aspect, trajectory.json |
| **相机外参导出** | :x: | :white_check_mark: | 四元数旋转 + 位置 |
| **自动路径规划** | :x: | :white_check_mark: | Snake path + 锥体旋转采样 |
| **批量自动采集** | :x: | :white_check_mark: | 定义区域 -> 一键采集 |
| **数据集元数据** | :x: | :white_check_mark: | trajectory.json (NeRF 兼容) |

#### 游戏兼容性

| 指标 | UUU | captureAIshi |
|------|:---:|:------------:|
| 支持游戏数量 | **600+** | **1** (测试阶段) |
| 引擎覆盖 | UE4 + UE5 | UE5 为主 (UE4/Unity 代码保留) |
| 反作弊绕过 | 不支持 | 不支持 (单机游戏) |
| 自动识别游戏 | AOB 通用扫描 | 字符串 xref 扫描 |

### 2.3 关键结论

1. **相机控制功能已基本对齐 UUU** -- 核心功能 (相机/路径/时停/HUD/分辨率) 均已实现
2. **GBuffer 导出是 UUU 永远不会做的事** -- 这是我们的核心差异化
3. **游戏兼容性是最大差距** -- UUU 600+ vs 我们 1 款，需要快速扩展
4. **UUU 面向摄影师, 我们面向 AI** -- 用户群和需求完全不同，不是直接竞争

---

## 3. 技术架构现状

### 3.1 系统架构

```
+-----------------------------------------------------------+
|                    captureAIshi Pipeline                    |
+-----------------------------------------------------------+
|                                                             |
|  [Web UI]  pywebview + Flask                               |
|     |                                                       |
|  [Core]  路径规划 (Snake/Grid/Cone/Catmull-Rom)            |
|     |                                                       |
|  [Drivers]  相机控制适配层                                   |
|     |-- UE5 Console (Bridge DLL TCP)                       |
|     |-- External Memory (ReadProcessMemory)                |
|     |-- CheatEngine (Lua socket / JSON file)               |
|     +-- Manual (调试用)                                     |
|     |                                                       |
|  [Grabbers]  帧捕获                                         |
|     |-- RenderDoc (GBuffer: RGB + Depth + Normal)          |
|     +-- Screenshot (fallback, RGB only)                    |
|     |                                                       |
|  [Bridge DLL]  注入游戏进程                                  |
|     |-- GEngine 自动扫描 (字符串 xref)                      |
|     |-- 控制台命令执行 (vtable 调用)                         |
|     |-- 相机路径引擎 (60Hz tick, Catmull-Rom + SLERP)       |
|     +-- TCP Server (端口 9998)                              |
|                                                             |
+-----------------------------------------------------------+
|  输出: RGB.png + Depth.png + Normal.png + trajectory.json  |
+-----------------------------------------------------------+
```

### 3.2 采集工作流

```
1. 选择游戏 + 加载配置
2. renderdoccmd 启动游戏 (自动注入 RenderDoc)
3. Bridge DLL 注入 (相机控制)
4. 定义采集区域 (volume min/max)
5. 自动生成路径 (snake path + cone rotation)
6. 逐帧: 设置相机位姿 -> 等待 LOD/纹理加载 -> 触发 RenderDoc 捕获
7. 批量导出 .rdc -> RGB + Depth + Normal PNG
8. 输出 trajectory.json (含内参外参)
```

### 3.3 代码规模

| 模块 | 行数 | 文件数 | 负责人 |
|------|------|--------|--------|
| Core (路径生成) | ~800 | 4 | - |
| Drivers (相机控制) | ~1,200 | 6 | 小逆 |
| Grabbers (帧捕获) | ~600 | 3 | 小萱 |
| Web UI | ~1,800 | 2 | 小由 |
| Bridge DLL (C++) | ~1,700 | 6 | 小逆 |
| Utils/Main | ~600 | 3 | - |
| **合计** | **~6,700** | **24** | |

---

## 4. 核心技术难点

### 难点 1: 游戏兼容性数据库 (难度: :star::star::star::star:)

**问题**: UUU 用了数年时间积累 600+ 游戏的兼容性。我们目前只验证了 1 款。

**技术细节**:
- 每款游戏的 GEngine 内存地址不同 (ASLR)
- 不同 UE 版本 vtable 布局不同 (UE 4.15 vs 4.27 vs 5.x)
- 有些游戏 strip 了调试字符串, 导致 xref 扫描失败
- 有些游戏魔改了 PlayerController, debug camera 不工作

**解决方案**:
- 我们的字符串 xref 方法比 AOB 更通用 (不依赖特定字节序列)
- 参考开源 RE-UE4SS 的 AOB pattern 库作为补充
- 建立自动扫描 + 验证 + 缓存机制
- 短期目标: 先覆盖 Top 50 热门 UE5 游戏

### 难点 2: RenderDoc + Bridge DLL 共存 (难度: :star::star::star:)

**问题**: 两个 DLL 同时注入同一个游戏进程。

**技术细节**:
- RenderDoc hooks 图形 API (D3D11/D3D12)
- Bridge DLL hooks 引擎层 (GEngine)
- 两者都用 CreateRemoteThread 注入
- RenderDoc capture 时可能暂停渲染线程

**当前状态**: 在 EagleWalkLJB 上共存正常，需要更多游戏验证。

**风险**: AAA 游戏的自定义渲染管线可能导致 RenderDoc 抓不到有效 GBuffer。

### 难点 3: GBuffer 鲁棒检测 (难度: :star::star::star::star:)

**问题**: 不同游戏的 GBuffer 布局不同。

**技术细节**:
- 标准 UE5 Deferred: SceneColor (RGBA16F) + GBufferA (Normal, RGB10A2) + SceneDepth (D32F)
- Forward rendering 游戏没有 GBuffer
- Nanite 可能改变 depth 格式
- DLSS/FSR 上采样后 buffer 分辨率不一致
- Lumen GI 可能增加额外 render target

**解决方案**:
- 当前: 按格式 + 分辨率匹配 (Float ColorTarget = SceneColor)
- 计划: 自动 GBuffer 分类器 (分析 texture 统计特征)
- 每游戏缓存 GBuffer layout profile

### 难点 4: 大规模自动采集的可靠性 (难度: :star::star::star:)

**问题**: 一次采集可能数千帧, 需要长时间稳定运行。

**技术细节**:
- 游戏可能崩溃 (内存泄漏、长时间运行不稳定)
- LOD/纹理未加载完成就拍摄 -> 低质量帧
- 相机移到地图外 -> 黑帧
- .rdc 文件每帧 100MB+, 磁盘空间消耗大

**解决方案**:
- 断点续采 (记录进度, 崩溃后恢复)
- 帧质量验证 (检测黑帧、模糊帧、LOD 不足)
- 增量采集 (跳过已完成区域)

---

## 5. 竞争优势与护城河

### 5.1 UUU 永远不会做的事

| 能力 | 原因 |
|------|------|
| GBuffer 导出 (Depth/Normal) | UUU 是用户工具, 不碰渲染数据 |
| 批量自动采集 | 摄影师只需要拍一张 |
| trajectory.json 元数据 | 摄影不需要相机内参外参 |
| 数据集级别质量控制 | 不是 UUU 的使用场景 |
| Material ID / Stencil 导出 | 需要 RenderDoc 深度集成 |

### 5.2 技术壁垒

1. **RenderDoc 深度集成** -- 我们 fork 了 RenderDoc, 在 renderdoccmd 中加了自定义导出命令, 并将 Bridge console server 嵌入 renderdoc.dll 本体。这种级别的集成不是简单的"调用 API"能实现的。

2. **双注入架构** -- 同时注入 RenderDoc (图形层) + Bridge DLL (引擎层), 实现控制 + 采集一体化。据我们所知, 目前没有其他工具做到这一点。

3. **AI 导向的输出格式** -- trajectory.json 直接兼容 NeRF/3DGS 训练流水线, 不需要额外转换。

---

## 6. 开发路线图

### Phase 1: 真实游戏验证 (v0.2.1) -- 当前阶段

**目标**: 在至少 3 款真实 UE5 游戏上跑通全流程

| 任务 | 优先级 | 预期产出 |
|------|--------|---------|
| 找到合适的免费 UE5 测试游戏 | P0 | 测试目标确定 |
| 验证 RenderDoc + Bridge 共存 | P0 | 兼容性报告 |
| 验证 GBuffer 检测 (RGB/Depth/Normal) | P0 | 输出样例数据 |
| 修复兼容性问题 | P0 | bug fix |
| 产出第一个真实数据集样本 | P0 | demo 数据 |

**验收标准**: 在 3 款游戏上成功导出 RGB + Depth + Normal + trajectory.json

---

### Phase 2: UI 重构 + 游戏库 (v0.3.0)

**目标**: 从开发者工具进化为可用产品

| 任务 | 负责人 | 优先级 | 说明 |
|------|--------|--------|------|
| 设置面板分离 | 小由 | P0 | 参数设置移到独立展开菜单 |
| 游戏选择面板 | 小由 | P0 | 从 IGCS/RE-UE4SS/PCGamingWiki 拉取游戏列表, 搜索+分页+字母排序 |
| 每游戏独立配置 | 小由 | P0 | `configs/games/<slug>.json` 存盘 |
| 隐藏 Unity 选项 | 小由 | P1 | UI 层过滤, 代码保留 |
| Bridge 自动注入 | 小逆 | P0 | 集成到 main.py, 用户无需手动注入 |

**验收标准**: 选游戏 -> 一键启动 -> 自动采集 -> 查看结果, 全流程无需命令行

---

### Phase 3: 功能增强 + 兼容性扩展 (v0.4.0)

**目标**: 支持 30+ 款游戏, 数据质量可靠

| 任务 | 负责人 | 优先级 | 说明 |
|------|--------|--------|------|
| GBuffer 自动分类器 | 小萱 | P0 | 不依赖硬编码 ColorTarget 索引 |
| 帧质量验证 | 小萱 | P1 | 检测黑帧/模糊帧/LOD 未加载 |
| 断点续采 | 小萱 | P1 | 崩溃恢复, 增量采集 |
| AOB pattern 辅助扫描 | 小逆 | P0 | 参考 RE-UE4SS, 补充字符串 xref |
| 游戏兼容性测试 (30 款) | 小逆 | P0 | 建立兼容性数据库 |
| Actor 操控 (隐藏/移动) | 小逆 | P2 | 清理遮挡物, 提升数据质量 |
| 数据集浏览器 | 小由 | P1 | 预览/标注/统计/导出 |

**验收标准**: 30+ 游戏验证通过, 数据集质量评分系统上线

---

### Phase 4: 规模化 + 高级功能 (v0.5.0)

**目标**: 生产级数据采集平台

| 任务 | 说明 |
|------|------|
| Material ID / Stencil buffer 导出 | 语义分割真值数据 |
| 多分辨率采集策略 | 根据训练需求选择 |
| 多游戏批量调度 | 自动切换游戏连续采集 |
| 社区兼容性贡献 | 用户上传 offset profile |
| 数据集管理平台 | 统一管理多游戏多 session 数据 |
| 自动 NavMesh 提取 | 根据游戏地形自动规划采集路径 |
| 云端采集调度 | 多台机器并行采集 |

---

### 路线图时间线 (预估)

```
2026 Q2          Q3              Q4              2027 Q1
  |               |               |               |
  v0.2.1          v0.3.0          v0.4.0          v0.5.0
  真实游戏验证     UI重构+游戏库    30+游戏兼容      规模化平台
  |               |               |               |
  3款游戏验证      产品化UI         GBuffer分类器     Material ID
  Bridge共存验证   游戏选择面板      帧质量验证        多游戏调度
  样本数据集       一键采集流程      断点续采          社区贡献
                  Bridge自动注入    AOB补充扫描       云端调度
```

---

## 7. 团队与分工

| 角色 | 代号 | 负责领域 | 核心技能 |
|------|------|---------|---------|
| 主程序员 | Lead | 架构设计, Code Review, 版本控制 | 全栈 |
| UI 工程师 | 小由 | Web UI, 用户交互, 数据可视化 | Flask + JS + pywebview |
| 渲染工程师 | 小萱 | RenderDoc, GBuffer, 图像处理 | C++ (MSVC) + Python |
| 逆向工程师 | 小逆 | Bridge DLL, 游戏注入, 内存分析 | C++ + 逆向工程 + UE5 内部结构 |

### 协作机制

- **代码评审**: 竞争性 peer review, 每次提交必须有 changelog
- **通信**: 通过 `agents/*/SHARED.md` 异步通信
- **版本控制**: 主程序员负责版本号, 全员在 `claudeMainBranch` 开发
- **领域边界**: 严格的文件归属, 跨域修改需申请

---

## 8. 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 大量游戏不兼容 Bridge 注入 | 高 | 高 | 多种注入方式 (bridge/memory/CE), AOB 补充 |
| RenderDoc 在某些游戏上抓不到有效 GBuffer | 中 | 高 | GBuffer 自动分类器, fallback 到 screenshot |
| 反作弊阻止注入 | 高 | 中 | 只做单机游戏, 提供 ExternalMemory 驱动 |
| RDC 文件过大, 磁盘不足 | 中 | 中 | 流式导出, 及时清理临时文件 |
| 游戏长时间运行崩溃 | 中 | 中 | 断点续采, 进度保存 |
| UE 大版本更新破坏兼容性 | 低 | 高 | 模块化引擎适配层 |

---

## 附录: 关键参考项目

| 项目 | 说明 | 链接 |
|------|------|------|
| UUU | 闭源, 游戏摄影工具, $23.5K/月收入 | opm.fransbouma.com |
| IGCS | 开源 (BSD-2), 26+ 游戏相机系统 | github.com/FransBouma/InjectableGenericCameraSystem |
| RE-UE4SS | 开源, UE4/5 Lua 脚本注入 + AOB 扫描 | github.com/UE4SS-RE/RE-UE4SS |
| RenderDoc | 开源, GPU 帧调试工具 | github.com/baldurk/renderdoc |
| PCGamingWiki | 游戏技术数据库 (引擎/DRM/反作弊) | pcgamingwiki.com |
