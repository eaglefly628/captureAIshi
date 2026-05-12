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

- [ ] **P0: RenderDoc trajectory 每 pose 触发链路断了** (spotted by 主程序员, 2026-05-12) — `drivers/trajectory_player.py:707-718` 在每个 capture pose 处发 TCP `__cam_rdc_capture` 到 bridge，**但 bridge / addon / Python 全栈都没有这个命令的 handler**。grep 结果：
  ```
  3rdparty/reshade/source/captureAIshi/bridge.cpp  ← 仅一行注释引用，无 route 分支
  3rdparty/reshade/source/captureAIshi/embed_api.h ← 仅注释提及
  drivers/ue5_console.py                            ← 0 命中
  ```
  Player 发完命令 → bridge 静默丢弃 → `.rdc` 文件永远不出现 → trajectory 全部回归（Batman / StackOBot 当前都跑不通）。这条线是你 9d2b8ba0 "feat(trajectory): pick capture cmd by grabber type" 引入的，但只对 ReShade 侧 `__fc_capture` 做了 wiring，RDC 侧没补。
  
  **修复方向（自己拍方案，三选一）**：
  
  (A) **Python 侧直调 grabber**（推荐，零 C++ 改动）— 把 `trajectory_player.py:707-718` 的 TCP 发送替换为 `_ws.get_active_grabber().trigger_capture()`。`RenderDocGrabber.trigger_capture()` 已存在 (`grabbers/renderdoc_grabber.py:195-229`)，链路全：native bridge → renderdoccmd triggercapture --interactive → Python API → SendInput keypress。一次性解决。ReShade 路径不变（继续 `__fc_capture`）。
  
  (B) **Bridge addon 加 `__cam_rdc_capture` handler** — 在 `3rdparty/reshade/source/captureAIshi/bridge.cpp` 的 router 里加分支，调 in-proc RenderDoc API 的 `TriggerCapture()`。问题：RDC 路径用的是 `renderdoc_grabber.py` 走 renderdoccmd CLI / 外部 RDC.dll，addon 上下文里没有 in-proc RenderDoc handle 可用。**不推荐**。
  
  (C) **退回批量模式** — 干脆禁掉 trajectory 的 per-pose 触发，回到老的 `renderdoccmd capture` 一帧一文件批跑。回归大，**不推荐**。
  
  **推荐 A**。`isinstance` 取代字符串比对：
  ```python
  from grabbers.reshade_grabber import ReShadeGrabber  # 已存在
  if isinstance(g, ReShadeGrabber):
      session.send("__fc_capture")
  else:
      g.trigger_capture()   # 含 RDC / 任何未来 grabber
  ```
  
  **验收**：
  1. Batman + RDC grabber 跑 trajectory：所有 capture pose 都产 `.rdc` 文件（之前是 0 个）
  2. StackOBot + RDC grabber 跑 trajectory：同上
  3. ReShade grabber + 任意游戏跑 trajectory：行为不回归（继续走 `__fc_capture`）
  4. `grep -rn "__cam_rdc_capture" --include="*.py" --include="*.cpp"` 应 0 命中（彻底删干净，包括 comments）
  
  **顺手清理**（属同一 PR）：
  - `drivers/trajectory_player.py:612, 690, 704-706` 三处 `__cam_rdc_capture` comment 全删
  - `3rdparty/reshade/source/captureAIshi/embed_api.h:42-44` 把 `mirroring RenderDoc's __cam_rdc_capture flow` 改成 `mirroring grabber.trigger_capture() flow`
  - `3rdparty/reshade/source/captureAIshi/bridge.cpp:273` 注释同上
  
  **工时估计**：1-2h（含 Batman/StackOBot 端到端回归）
  
  **背景**：完整 review 报告见 ad-hoc, 这是 review 列的 #1 收尾项。#2 (UI `injection_mode` 下拉 + `create_grabber()` 工厂) 和 #3 (字符串 type 检测) 一起做完更省心，但 P0 最小修复只要 A 方案那一段。

- [ ] **P2: depth_curve 跨域改动** (spotted by 小逆, fixed in pending push) — 用户报告 Batman PNG 远景 city 段塌成 near-white。我在 `image_loader._normalize_depth` 加了 `depth_curve` 参数（"linear" / "gamma" / "log"），`batman_ak.json` 默认 "log"。代码在你域 (grabbers/) 里，麻烦 review 一下：(1) curve 实现是否合理（log on raw before percentile，保留 monotonic 极性）；(2) 其他 outdoor 配置（ac6 / metro_exodus / black_myth_wukong）也建议默认 "log"；(3) 字段已加到 `_schema.md`。

- [x] **P1: 99308e9 EXR depth 没补 requirements.txt** (spotted by 小逆, fixed 1d53bf2) — `image_loader.load_depth_image` 三选一 cv2/imageio/OpenEXR 全没装的话整批 capture 的 depth 都会失败（用户报告：rgb+normal 出图但 depth 为 0）。已加 `opencv-python>=4.5.0`。下次改 file format 麻烦顺手 bump deps。

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

### [v0.2.0] 99308e9 — 小萱
- feat: strategy-based GBuffer detection replaces unstable texture indices
  - C++: remove --rgb-index/--normal-index/--no-reverse-depth/--depth-range
  - C++: add --rgb-strategy (float_scene_color|unorm_pre_ui|swap_buffer|auto)
  - C++: add --normal-strategy (r10g10b10a2_unique|r10g10b10a2_slot1|auto)
  - C++: depth export switched to raw float EXR (FileType::EXR, no normalization)
    → Python _normalize_depth() does per-frame 1-99th percentile (no batch contamination)
  - Python: capture_export_args() updated to emit new strategy flags
  - batman_ak.json: capture section rewritten with rgb_strategy/normal_strategy/_note fields
  - _schema.md: documented new strategy fields, marked old index fields as removed
  - Root cause: indices are creation-order based, change every frame even same session
    (observed SceneColor at indices 68,37,39,59,303,336,150 across 7 consecutive captures)

### [v0.2.0] c80a2cb — 小萱
- feat: per-game texture index config + UE3 depth support
  - C++: `--depth-index N` (pin depth texture) + `--no-reverse-depth` (UE3 standard-Z)
  - `game_profile.py` Profile 加 `capture` dict
  - `renderdoc_grabber.py` `_capture_export_args()` 从 capture_profile 拼 CLI flags
  - `main.py` `--game ID` 加载 game profile，传 capture_profile 给 grabber
  - `batman_ak.json` 加 `capture` section (depth_reversed_z=false, indices=-1 待填)
  - `_schema.md` 文档更新

### [v0.2.0] 75ce117 — 小萱
- P0 fix: Normal 检测改用 R10G10B10A2 格式过滤 + pipeline state 扫描 MRT slot 1
  - 放弃像素启发式（帧间不稳定、彩虹 debug buffer 干扰）
  - 唯一匹配直接用，多个候选时扫描前 500 个 draw call 查 RT slot 1
  - 直接导出 normal.png，Python ct_*.png fallback 仅对非 UE5 游戏触发
- P1 fix: Depth 归一化改用第一帧 range 全批复用，消除帧间漂移

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

### [v0.2.0] 35099b5 — 小萱
- Cyberpunk 2077 配置 note 更新：定位 DX12 下 RenderDoc overlay/triggercapture 无效的根本原因
- `CRenderNode::Present::DoInternal` 绕过 DXGI SwapChain::Present hook，无 frame boundary 信号
- 记录 workaround：启动加 `-vulkan` 使用标准 `vkQueuePresentKHR` 进入 RenderDoc 捕获路径
- Crash 本身已修（NVAPI+DXR+SM passthrough），剩下是 Present hook 可见性问题
- 2.12 AOB 重扫需等 -vulkan 模式验证通过后再执行

### [v0.2.0] d62c704 — 小萱
- 新增 Armored Core 6 config (`configs/hacks/armored_core_6.json`)
  - UE5 engine, IGCS-GITC 路径，3 个 intercept (address capture + matrix write + FOV)
  - 4x4 rotation matrix @ +0x10/+0x20/+0x30，XYZ @ +0x40，FOV @ +0x58
- 新增 Metro Exodus config (`configs/hacks/metro_exodus.json`)
  - 4A Engine with RTXGI (Enhanced Ed.)，5 个 intercept 覆盖所有冗余 camera write site
  - 4x3 matrix @ +0x10 (stride=4)，XYZ @ +0x00
  - camera_write_profile 最初 enabled=false，等 rotation_matrix 桥接支持

### [v0.2.0] a9ec4f9 — 小萱
- `drivers/game_profile.py` 增加 rotation_matrix 桥接
  - `_euler_deg_to_matrix` / `_matrix_to_euler_deg` helpers (ZYX, row-major)
  - `read_camera_pose` / `write_camera` 自动检测 profile 中的 `rotation_matrix` 块
  - 按 row0/row1/row2 offset + stride 读写 3x3 矩阵
- AC6 和 Metro Exodus 的 `camera_write_profile` 打开 enabled=true

### [v0.2.0] 919c6ea — 小萱
- 修 rotation matrix euler 约定：原 ZYX 不匹配两款游戏内存存储
- 对比 refCode `Camera.cpp`：
  - AC6 (IGCS-GITC)：`Qz(-roll)·Qx(-pitch)·Qy(yaw)` → `M = Mz(-r)·Mx(-p)·My(y)` (DX LH row-vector)
    - 分解：`pitch = asin(m[2][1])`，`yaw = atan2(-m[2][0], m[2][2])`，`roll = atan2(m[0][1], m[1][1])`
  - Metro (4A cryengine-specific)：`Qx(-roll)·Qz(-pitch)·Qy(yaw)` → `M = Mx(-r)·Mz(-p)·My(y)`
    - 分解：`pitch = asin(m[0][1])`，`yaw = atan2(m[0][2], m[0][0])`，`roll = atan2(-m[2][1], m[1][1])`
- 新增 `rotation_convention: "ac6"|"metro"` 字段，`game_profile.py` 按约定派发
- build / decompose 互为代数逆（代码审查通过）
- `configs/hacks/_schema.md` 同步补 rotation_matrix 文档段

### [v0.2.0] 40ec164 — 小萱
- STATUS.md 更新：标记 rotation_convention fix 完成，Cyberpunk DX12 下一步 `-vulkan` 验证

## Known Issues

### P1: 无 Float SceneColor 的游戏 RGB 含 UI
部分游戏没有 RGBA16F SceneColor，fallback 到 SwapBuffer 导致 UI overlay 残留。
修复：需要在 RenderDoc replay 层面过滤 UI draw calls（`ui_hiders/renderdoc_hider.py` 未集成到 batch export 路径）。

### P1: RGB 太暗（tone mapping）
SceneColor 是 linear-space HDR (RGBA16F)，直接存 PNG 会很暗。
选项：(a) Reinhard/ACES tone map；(b) 改取 Post-Process 后 LDR buffer；(c) 输出 EXR 让训练侧处理。

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
