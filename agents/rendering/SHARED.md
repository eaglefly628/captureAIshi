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

## TODO (Handoff — 2026-05-13)

- [ ] **P1: ReShade Path B — UE5 pov_ptr 扫描 + mem_find/read/on/off 路由** (handoff from 小萱 2026-05-13)

  **背景**: 这个 session 已经完成 ReShade 桥的 **Tier-1 (AOB intercept)** 移植，commit `4c75689`:
  - `pattern_scan.h` 加了 `scan_main_module_nth`
  - 新建 `3rdparty/reshade/source/captureAIshi/camera_intercept.h` (RDC 同名文件的直接拷贝)
  - `bridge.cpp` 加了 `ascii_strtod`、`#include "camera_intercept.h"`、8 条新路由 (install_aob / nop / pass / list / uninstall / capture / get_capture / poke / peek) + shutdown 时调 `cam_intercept_uninstall_all()`

  **下一步是 UE5 path**: IGCS-GITC 类游戏 (Batman AK / AC6 / Metro / Cyberpunk DX12 vulkan 等) 走 AOB 路径 OK，但 UE5 原生游戏 (StackOBot / Hellblade 2 / Avowed / Oblivion Remastered / The Quarry / Invincible / South of Midnight) 走的是 **UE5 pov_ptr scanner** 路径——直接通过 GEngine 找 PlayerController → LocalPlayer → ViewportClient → MinimalViewInfo 链拿到 camera 内存地址，不需要 AOB。

  **要做的事**:

  1. **移植 `ue5_scan_camera.h`** (RDC 路径 1304 行 → ReShade 路径)
     - 源: `renderdoc/renderdoc/core/bridge/ue5_scan_camera.h`
     - 目标: `3rdparty/reshade/source/captureAIshi/ue5_scan_camera.h`
     - 依赖: 已有 `ue5_engine.h` (ReShade 这边已经有了，看 bridge.cpp:78)
     - 可能需要调整: include 顺序、`extern void bridge_log` 声明 (跟 camera_intercept.h 一样)

  2. **bridge.cpp 加 4 条路由** (参考 `console_server.h` 对应分支)
     - `__cam_mem_find` — 启动 UE5 pov_ptr 扫描线程
     - `__cam_mem_read <addr_hex>` — 读 MinimalViewInfo (XYZ + pitch/yaw/roll + FOV)
     - `__cam_mem_on` / `__cam_mem_off` — 启用/禁用扫描器后台 ticker
     - 在 `console_server.h` 里 grep `__cam_mem_` 看现有实现，全部抄过来

  3. **bridge.cpp `#include "ue5_scan_camera.h"`** 加到 `#include "camera_intercept.h"` 后面

  4. **shutdown cleanup**: 看 `ue5_scan_camera.h` 是否有自己的 thread + state 需要 stop，仿照 `cam_intercept_uninstall_all()` 模式调用

  **验收**:
  - Batman AK + ReShade dxgi.dll: 现有 AOB 流程不回归 (`__cam_intercept_install_aob` → `__cam_intercept_capture` → `__cam_mem_poke` → `__fc_capture`)
  - StackOBot + ReShade dxgi.dll: `__cam_mem_find` 能找到 pov_ptr，`__cam_mem_read <pov_ptr>` 返回正常 XYZ+rotation+FOV
  - Hellblade 2 / Avowed 等 UE5.3+ 游戏验证（让小逆配合实测）

  **工时估计**: 2-3h (1304 行的 ue5_scan_camera.h 是纯 Win32+pattern_scan 实现，依赖少，能直接抄；主要时间在 4 条路由 wiring + 实测调试)

  **风险点**:
  - `ue5_scan_camera.h` 可能内部包含 `ue5_scan_engine.h` 或 `ue5_scan_world.h`，先读头看看 (ReShade 这边没有这两个文件)
  - 如果有依赖，要么补移植，要么裁剪掉非 camera 相关的部分

  **推送流程 (新 session 必读)**:
  - 不要直推 `claudeMainBranch`，sandbox 代理会 403
  - 推到 sandbox 分配的 session 分支 (本 session 是 `claude/merge-shared-v0.2.0-SBQG5`，新 session 会换一个名字)
  - GitHub Actions 自动合并 workflow (`.github/workflows/auto-merge-claude.yml`) 会在 ~10s 内把 `claude/**` push fast-forward 到 `claudeMainBranch`
  - 验证: `git fetch origin claudeMainBranch && git log --oneline -1 origin/claudeMainBranch` 应等于你刚 push 的 SHA
  - 如果 stop hook 报 "unpushed commit on claudeMainBranch"，先 fetch 一次，等 10s 让 CI 跑完再判断
  - 完整说明见 `CLAUDE.md` "Branch Policy" section
  - 命令模板:
    ```bash
    git checkout claudeMainBranch && git pull origin claudeMainBranch
    # 干活, 提交
    git push -u origin HEAD:claude/<sandbox-assigned-branch>
    # CI 自动合并到 claudeMainBranch
    ```

## TODO (from lead review)

- [x] **P0: RenderDoc trajectory 每 pose 触发链路断了** (spotted by 主程序员, fixed 03ce4a8 by 小萱) — `drivers/trajectory_player.py:707-718` 在每个 capture pose 处发 TCP `__cam_rdc_capture` 到 bridge，**但 bridge / addon / Python 全栈都没有这个命令的 handler**。grep 结果：
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

- [x] **P2: depth_curve 跨域改动** (spotted by 小逆, reviewed by 小萱 2026-05-12) — 用户报告 Batman PNG 远景 city 段塌成 near-white。我在 `image_loader._normalize_depth` 加了 `depth_curve` 参数（"linear" / "gamma" / "log"），`batman_ak.json` 默认 "log"。代码在你域 (grabbers/) 里，麻烦 review 一下：(1) curve 实现是否合理（log on raw before percentile，保留 monotonic 极性）；(2) 其他 outdoor 配置（ac6 / metro_exodus / black_myth_wukong）也建议默认 "log"；(3) 字段已加到 `_schema.md`。

### UI 同学需要注意

1. **trajectory.json 是给 AI 训练用的输出文件**，UI 可以读取它做可视化但不需要修改
2. **文件命名变了**：不再是 `rgb_000000.png`，而是 `{timestamp}_{viewName}.png`
3. **新增了 Normal 图片**：`_n.png` 后缀，RGB 格式的世界法线贴图
4. **lightbox 预览** 需要支持三种图片类型：RGB / Depth (`_d.png`) / Normal (`_n.png`)
5. **进度面板** 可以从 trajectory.json 读取 viewName 和 pointIndex 显示当前拍摄位置
6. **3D 可视化器** 可以直接用 trajectory.json 里的 Position + Rotation 画相机锥体

## Changelog

### [v0.3.0] (pending sha) — 小萱
- feat: ReShade Path B camera AOB intercept — parity with RDC Path A
  - pattern_scan.h: add scan_main_module_nth (1-based Nth match)
  - NEW camera_intercept.h (ReShade copy of RDC camera_intercept.h)
  - bridge.cpp: include camera_intercept.h; add ascii_strtod
  - bridge.cpp: 8 new routes: install_aob, nop, pass, list, uninstall, capture, get_capture, poke/peek
  - bridge.cpp shutdown(): cam_intercept_uninstall_all() before thread stop

### [v0.2.0] 03ce4a8 — 小萱
- P0 fix: trajectory_player RDC capture chain (dispatches to grabber.trigger_capture())
  - isinstance(g, ReShadeGrabber) → TCP __fc_capture; else → g.trigger_capture() direct
  - Removed __cam_rdc_capture string from all Python/trajectory code (0 hits in *.py)
  - Note: console_server.h handler remains as low-level fallback (not removed)
  - Reviewed P2 depth_curve: log monotonicity + polarity correct for standard-Z

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

旧版 CL 见 `agents/rendering/ARCHIVE.md`。

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
