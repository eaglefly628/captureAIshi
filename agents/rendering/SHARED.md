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

## Active TODO

_全部清空 2026-05-13（老白 by 用户指令）— 旧 TODO 清单 + 恢复方式见 `agents/rendering/ARCHIVE.md` 末尾 "Cleared 2026-05-13" 段。新方向 TODO 待老白下次重派。_

### UI 同学需要注意

1. **trajectory.json 是给 AI 训练用的输出文件**，UI 可以读取它做可视化但不需要修改
2. **文件命名变了**：不再是 `rgb_000000.png`，而是 `{timestamp}_{viewName}.png`
3. **新增了 Normal 图片**：`_n.png` 后缀，RGB 格式的世界法线贴图
4. **lightbox 预览** 需要支持三种图片类型：RGB / Depth (`_d.png`) / Normal (`_n.png`)
5. **进度面板** 可以从 trajectory.json 读取 viewName 和 pointIndex 显示当前拍摄位置
6. **3D 可视化器** 可以直接用 trajectory.json 里的 Position + Rotation 画相机锥体

## Changelog

### [v0.3.1] (pending sha) — 老白 (lead)
- refactor(root): vendor `renderdoc/` -> `3rdparty/renderdoc/` (overlay tree at `renderdoc/core/bridge/` moves with it -- xiaoni's camera_intercept/console_server/ue5_*.h stay intact)
- feat(root): `main.py` at repo root forwards to `apps/launcher/server.py` via runpy
- fix(grabbers/renderdoc/paths.py): repo_root via `parents[4]`, search candidates rewritten to `3rdparty/renderdoc/x64/{Development,Release}/...` -- the post-monorepo apps/capture/.. fallback was broken
- fix(renderdoc_ext/build.sh): vendor probe `../../3rdparty/renderdoc/renderdoc/api/app/renderdoc_app.h`, cmake `-DRENDERDOC_SOURCE_DIR=$(pwd)/../../../3rdparty/renderdoc` (from build/ cwd); dropped fake `git submodule update --init renderdoc` (was never a real submodule)
- fix(renderdoc_ext/CMakeLists.txt): `RENDERDOC_SOURCE_DIR` -> `../../../3rdparty/renderdoc`, include base -> `../../../3rdparty` so `#include "renderdoc/renderdoc/api/..."` still resolves
- fix(extract_for_review.bat): `renderdoc\renderdoc\core\bridge\` -> `..\..\3rdparty\renderdoc\renderdoc\core\bridge\` (run from apps/capture/)
- fix(.gitignore + captureAIshi.code-workspace): build-artifact patterns and file/search exclude `renderdoc/` -> `3rdparty/renderdoc/`
- docs(CLAUDE.md): repo-layout block + 启动入口 line updated to reflect new tree
- v0.3.1 patch -- internal path refactor, no inter-agent contract change

### [v0.3.0] (pending sha) — 小宣6
- feat: F6 in-game trigger fires pre-UI survey -- no Alt+Tab needed
  - addon (frame_capture.cpp on_reshade_present): runtime->is_key_pressed(0x75)
    edge-trigger -> write <game_dir>/fc_survey_request.txt sentinel
  - grabber: daemon watcher thread polls sentinel every 250ms, consumes it,
    calls run_pre_ui_survey() under a non-blocking lock (double-press during
    survey is ignored, not stacked)
  - sentinel is cleared on setup() (stale leftovers do not auto-fire)
  - teardown() joins the watcher thread before game shutdown
  - feat: Web UI survey button reuses Focus Delay knob for Alt+Tab grace
    (POST /api/reshade/survey accepts `delay` 0-30s)

### [v0.3.0] (pending sha) — 小宣6
- fix: preserve FC_EnableCapture across grabber.setup() calls
  - was hard-coded =0 every session; user toggle in ReShade overlay never stuck
  - now reads existing ini before write; defaults 0 only on first install
  - unblocks: empty output_dir, survey "probe frame not received" cascade

### [v0.3.0] (pending sha) — 小宣6
- fix: NormalBuffer.exr -> <base>_n.png preview in ReShade grabber
  - image_loader.py: new `_read_exr_rgb` (cv2/imageio/OpenEXR fallback, BGR->RGB)
  - reshade_grabber.py save_frame: mirror the depth EXR->PNG block; normal
    is already [0, 1] (shader does `* 0.5 + 0.5`), so just `*255` -> uint8
  - filename `<base>_n.png` matches the trajectory.json `normalImg` convention
  - addresses 用户 "EXR 我们程序显示不出来" (lightbox/gallery is uint8 only)

### [v0.3.0] (pending sha) — 小宣6
- fix: frame_capture.cpp FC_ExportNormal -- wire end-to-end
  - SaveTask: add normal_path + normal_pixels (RGB32F interleaved, w*h*3)
  - new SaveEXRRGB helper (deinterleave -> planar B/G/R, ZIP compressed)
  - two depth-harvest loops (line ~1085 + ~1194): same map pass extracts RGB
    into normal_pixels when enableNormalExp is true (zero extra GPU->CPU)
  - save_worker_fn: writes NormalBuffer.exr alongside DepthBuffer.exr
  - fixed stale SaveTask::depth_pixels doc comment (RGBA32F -> scalar Y32F)

### [v0.3.0] (pending sha) — 小宣6
- feat: ReShade Path B UE5 pov_ptr scanner — parity with RDC mem_find/read/on/off
  - ue5_scan_engine.h (1230 LOC), ue5_scan_world.h (379), ue5_scan_camera.h (1304): verbatim port from RDC
  - ue5_engine.h: orchestrator rewrite; remove duplicate find_gengine_via_*, add globals/typedefs (g_world_ptr, FExecExecFn, GUOBJARRAY consts, UEVersionLayout x4, g_guobjectarray, etc.), add seh_read_ptr/seh_read_u32_ok, keep slim exec/HUD/timestop/free-cam/hotsample helpers
  - bridge.cpp: 4 new routes (__cam_mem_find/read/on/off); find lazily bootstraps find_guobjectarray since ReShade startup has no gate sequence
  - bridge.cpp shutdown(): disarm g_camera_override before tick thread stop

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
