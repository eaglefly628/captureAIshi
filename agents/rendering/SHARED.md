# Rendering Agent — Shared Notes

This file is used for inter-agent communication. The rendering agent writes GBuffer analysis, depth format findings, and engine-specific rendering notes here.

## [v0.1.0] Initial Findings

### UE5 Depth Export (renderdoccmd exportframe)
- Depth saved as normalized grayscale PNG (no EXR needed)
- Uses percentile-based (1st-99th) black/white point mapping via RenderDoc's TextureSave.comp
- Reversed-Z inversion: blackPoint=wpVal, whitePoint=bpVal (swapped)
- `--dump-all` flag exports all ColorTargets at viewport resolution for GBuffer analysis

### UE5 GBuffer Layout (typical)
- ColorTarget 0: SceneColor (HDR, RGBA16F)
- ColorTarget 1: GBufferA — WorldNormal (RGB10A2)
- ColorTarget 2: GBufferB — Metallic/Specular/Roughness
- ColorTarget 3: GBufferC — BaseColor
- DepthTarget: SceneDepth (D32F, reversed-Z)

---

## [v0.2.0] Trajectory Output + Normal Buffer + Camera Intrinsics

### 1. 新增 trajectory.json 输出格式

Capture 完成后，`output_dir/trajectory.json` 按以下 schema 逐帧写入：

```json
[
  {
    "Position": {"x": 818.40, "y": -126.10, "z": 20.40},
    "Rotation": {"x": -0.012, "y": -0.087, "z": -0.694, "w": 0.714},
    "fov_v": 60.0,
    "aspect": 1.7778,
    "captureImg": "20260329143818065_cone0.png",
    "depthImg": "20260329143818065_cone0_d.png",
    "normalImg": "20260329143818065_cone0_n.png",
    "viewName": "cone0",
    "pointIndex": 0,
    "splineMode": "manual"
  }
]
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `Position` | `{x, y, z}` | 相机位置（pipeline 坐标系：Y-up, 米） |
| `Rotation` | `{x, y, z, w}` | 四元数旋转（从欧拉角 pitch/yaw/roll 转换） |
| `fov_v` | float | 垂直视场角（度），CLI 通过 `--fov` 设置，默认 90 |
| `aspect` | float | 宽高比，CLI 通过 `--aspect` 设置，默认 16:9 (1.7778) |
| `captureImg` | string | RGB 图片文件名 |
| `depthImg` | string | Depth 图片文件名 |
| `normalImg` | string | Normal 法线图文件名 |
| `viewName` | string | 视角名称：`center`（无 cone）或 `cone0`, `cone1`... |
| `pointIndex` | int | 路径点索引（对应 waypoint 编号） |
| `splineMode` | string | 插值模式：`manual` 或 `catmull-rom` |

### 2. CameraPose 新增字段

`core/waypoint.py` 的 `CameraPose` 新增：
- `aspect: float` — 宽高比
- `view_name: str` — 视角名（cone0 等）
- `point_index: int` — 路径点索引
- `spline_mode: str` — 插值模式
- `to_trajectory_dict()` — 输出上述 JSON 格式
- `euler_to_quaternion()` — 欧拉角转四元数（YXZ 旋转顺序）

### 3. 文件命名规则

帧文件按 `{session_prefix}_{viewName}` 命名：
- RGB: `{session_prefix}_{viewName}.png`
- Depth: `{session_prefix}_{viewName}_d.png`
- Normal: `{session_prefix}_{viewName}_n.png`

`session_prefix` 默认为时间戳 `YYYYMMDDHHMMSSmmm`。

### 4. Normal Buffer 自动导出

`renderdoccmd exportframe` 现在自动导出 `normal.png`：
- 检测逻辑：第一个非 SwapBuffer 的、viewport 分辨率匹配的、3+ 组件的 ColorTarget
- 对应 UE5 GBufferA (WorldNormal, RGB10A2)
- Python 端 `RenderDocGrabber._replay_python_ex()` 自动加载

### 5. FrameGrabber 扩展

`grabbers/base.py` 新增：
- `FrameData` 数据类：`rgb`, `depth`, `normal` 三个 buffer
- `capture_frame_ex()` 方法：返回 `FrameData`
- `save_frame()` 新增 `base_name` 和 `normal` 参数，返回 `Dict[str, str]` 已保存文件名

### 6. CLI 新参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--fov` | 90.0 | 垂直 FOV（度） |
| `--aspect` | 1.7778 | 宽高比 |

## TODO (from lead review)

- [x] **P0: RGB 导出抓了 SwapBuffer 而不是 SceneColor** — Fixed: exportframe 现在用 SceneColor (第一个 Float ColorTarget) 作为 RGB 源，SwapBuffer 仅用于确定 viewport 分辨率。非 UE5 游戏如果没有 HDR ColorTarget 会 fallback 到 SwapBuffer。
- [x] **P1: batch export 路径缺 normalImg** — Fixed: `to_trajectory_dict()` 新增 `normal_filename` 参数，per-frame 和 batch 两条路径都填充 `normalImg`。
- [x] **P1: .claude/ 迁移验证** (from lead) — 已验证：(1) `.claude/agents/rendering.md` 完整覆盖职责、C++规则、图像知识，与旧 CLAUDE.md 一致。(2) `.claude/rules/cpp-rules.md` 和 `.claude/rules/no-sleep.md` 适用于渲染领域。(3) 小由 a5f8859 review 结果见下方 P1。
- [x] **P1: a5f8859 export_batch stderr 管道风险** (spotted by 小萱, fixed by 主程序员) — 改为 `stderr=subprocess.STDOUT`，stderr 合并到 stdout 在同一循环中读取，删除 `proc.wait()` 后的死代码 `proc.stderr.read()`。
- [x] **P1: f35632d + f4292f5 越界修改 main.py** (spotted by 主程序员) — 已确认：main.py 的 batch/per-frame 路径改动是为了集成 trajectory 输出和 batch export，属于渲染管线的输出格式变更。后续涉及 main.py 的改动会在 SHARED.md 先提跨域请求。
- [x] **P1: f35632d locals().get() 反模式** (spotted by 主程序员) — Fixed: 在 try 块前初始化 `normal_filename = ""`，删除 `locals().get()` 调用。
- [x] **P2: 5 个 commit 缺独立 CL 条目** (spotted by 主程序员) — 已补录 f35632d/f901bc8/ebe4a7d/f4292f5/8c6160e 的 CL 条目到 Changelog 段落。

### UI 同学需要注意

1. **trajectory.json 是给 AI 训练用的输出文件**，UI 可以读取它做可视化但不需要修改
2. **文件命名变了**：不再是 `rgb_000000.png`，而是 `{timestamp}_{viewName}.png`
3. **新增了 Normal 图片**：`_n.png` 后缀，RGB 格式的世界法线贴图
4. **lightbox 预览** 需要支持三种图片类型：RGB / Depth (`_d.png`) / Normal (`_n.png`)
5. **进度面板** 可以从 trajectory.json 读取 viewName 和 pointIndex 显示当前拍摄位置
6. **3D 可视化器** 可以直接用 trajectory.json 里的 Position + Rotation 画相机锥体

## Changelog

### [v0.2.0] b542e7e — 小萱
- trajectory.json 输出格式，四元数旋转，camera intrinsics (FOV/aspect)
- Normal buffer 自动导出 (R10G10B10A2, fmtType=12)
- 两阶段批量截帧/导出 (batch-export 默认开启)
- DLSS/FSR/TSR 自动关闭 (UE5 driver)
- Interactive trigger 持久连接 + warm-up
- exportframe 支持多文件批量处理
- RGB 改用 SceneColor 代替 SwapBuffer (去掉 UI overlay)
- exportframe 加 ReplayOptimisationLevel::Fastest
- 临时文件移到系统 temp 目录，不再污染 captures/

### [v0.2.0] f35632d — 小萱
- normalImg 字段加入 trajectory.json (per-frame + batch 两条路径)

### [v0.2.0] f901bc8 — 小萱
- 修复 _batch_export 清理代码被误删的问题

### [v0.2.0] ebe4a7d — 小萱
- 首帧 trigger 失败修复 (warm-up trigger)
- exportframe 加 ReplayOptimisationLevel::Fastest

### [v0.2.0] f4292f5 — 小萱
- Normal 检测改为 fmtType=12 (R10G10B10A2)，跳过 RGBA16_SNorm
- GBuffer 诊断日志

### [v0.2.0] 8c6160e — 小萱
- 修复 Windows stderr 管道死锁 (stderr=DEVNULL)

### [v0.2.0] bfe81db — 小萱
- Normal 自动检测移到 Python 侧（PIL 分析 SaveTexture 输出的 RGBA8 PNG）
- C++ 导出所有 ColorTarget 为 ct_{index}.png
- 覆盖率 + 蓝色占比启发式

## Known Issues (待下个 session 修)

### P0: Normal 自动检测帧间不稳定
p1-p3 检测正确（蓝绿色 WorldNormal），p0 选错了（彩虹圆环 debug buffer）。
原因：每帧的 texture index 可能不同，auto-detect 独立运行导致结果不一致。
修复方案：第一帧做 auto-detect，确定 best candidate 的特征签名（格式+相对位置），后续帧用同一签名匹配。或者用 `--normal-index` 锁定。

### P1: Depth 归一化帧间不一致
每帧独立做百分位 (1st-99th) 黑白点映射，场景变化导致 depth range 不同。
修复方案：第一帧计算 depth range，后续帧复用同一 range。或者用固定 near/far plane。

### P1: 无 Float SceneColor 的游戏 RGB 取自 SwapBuffer（含 UI）
部分游戏没有 RGBA16F SceneColor，fallback 到 SwapBuffer 导致 UI overlay 残留。
修复方案：需要在 RenderDoc replay 层面过滤 UI draw calls（已有 ui_hiders/renderdoc_hider.py 但未集成到 batch export 路径）。

## Backlog (v0.3.0+, 等破解流程跑通后)

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P0 | Depth 精度升级 | 8-bit PNG → 16-bit PNG 或 EXR float32，NeRF/3DGS 需要 |
| P0 | Motion Vector 导出 | UE5 Velocity buffer (RGBA16F)，光流真值 |
| P1 | Semantic Stencil 导出 | CustomDepth/Stencil，物体级分割 mask |
| P1 | 多分辨率支持 | 同路径截 1080p + 4K，超分训练对 |
| P1 | HDR SceneColor EXR | RGBA16F → EXR，tone mapping 训练 |
| P2 | 材质分解导出 | BaseColor + Metallic + Roughness 分别命名 |
| P2 | 天空 Mask | 从 depth far plane 推 sky mask |
| P2 | 多帧时序捕获 | 连续 N 帧同位置，视频去噪训练 |
| P3 | Cubemap 全景 | 6 面 90° FOV，360° 场景理解 |
| P3 | 光照变体 | 同场景切时间/天气，relighting 训练 |
