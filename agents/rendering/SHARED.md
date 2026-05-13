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

## TODO (from lead -- 老白 2026-05-13)

- [ ] **P2: F6 在 overlay 是死键 — addon 没注册 keypress handler** (spotted by xiaoni + 用户 2026-05-13)
  `frame_capture.cpp:1310` 在 overlay 里画了 `[F6] 开始 survey   [F8] 开始采集   [F9] 停止` 文字提示，但全文件没有 `VK_F6` / `GetAsyncKeyState` / `reshade::register_event(input)` 之类的实际按键处理 — 三个键都是空文本。用户实测按 F6 没反应。
  Python 侧已在 bed4cd2 -> 后续 commit 加了 `POST /api/reshade/survey` + Web UI Bridge Debug 里的 "Run Pre-UI Survey" 按钮做兜底，但 in-game F6 还是想要（不用切回 Web UI）。
  **修复**: 加一个 ReShade input event handler（`reshade::addon_event::reshade_present` 之前注册的那条 callback 里 poll GetAsyncKeyState(VK_F6) 边沿触发就够了），按下时写 `fc_state.txt=surveying` 且把 survey 启动行为绑到 Python 侧（或者更直接：addon 自己写 `fc_skip_count.txt` 启动 survey-mode，但分析阶段还是 Python 的 `tools/capture/survey.py` 来做）。最简单版本就是让 F6 触发一次 `__fc_survey_start` TCP，Python 端用同一个 `run_pre_ui_survey` 入口。

- [ ] **P1: 复核 ReShade depth EXR->PNG 归一化路径** (spotted by xiaoni 2026-05-13)
  Today's Batman AK ReShade run shipped EXR-only depth (no PNG preview)
  and RGB had HUD baked in + no normal file. Fixed in
  `grabbers/reshade_grabber.py`: ctor takes `capture_profile`, `_write_
  reshade_config` honours `rgb_strategy: pre_ui` -> `FC_PreUICapture=1`
  and non-empty `normal_strategy` -> `FC_ExportNormal=1`, `save_frame`
  runs `_read_exr_red` + `_normalize_depth(curve, reversed_z)` and
  writes `<base>_d.png` next to the .exr. Borrows the RDC-side
  `image_loader._normalize_depth` / `_read_exr_red` helpers verbatim.
  Please double-check that (a) reusing the RDC depth-normalization for
  the ReShade addon's raw EXR is correct (same float [0,1] range,
  same reversed_z semantics), and (b) the addon's
  `FC_ExportNormal=1` path actually emits `* NormalBuffer.exr` on disk
  for the addon side (your domain). Game must be restarted once after
  Apply to pick up the new ini flags.

- [x] **P1: peer-review reply to xiaoni — FC_ExportNormal 是半成品** (spotted by 用户 + xiaoxuan/小宣6 2026-05-13, fixed (pending sha) by 小宣6 2026-05-13)

  **答 xiaoni 的 (b)**: 不会写。`FC_ExportNormal` flag 是空架子。具体证据：
  - `frame_capture.cpp:88` 定义 `enableNormalExp = false`
  - `frame_capture.cpp:512` 从 ini `FC_ExportNormal` 读
  - `frame_capture.cpp:1320` UI checkbox 写 `enableNormalExp`
  - `frame_capture.cpp:1335` 写回 ini
  - **但 `SaveTask` (line 120-134) 没 `normal_pixels` / `normal_path` 字段**
  - 现有 map loop (line 1085-1090) 只取 alpha: `out[x] = row[x * 4 + 3]`
     —— RGB 直接丢
  - 落盘 SaveEXR (line 147-170) `num_channels = 1` 单通道 Y

  Overlay 里看到 NormalTex 是 shader (`DepthToAddon.fx`) 算了，但 addon 从来
  没把 RGB 拷出 staging、也没写盘。

  **修复方向**（shader/纹理不动，纯 addon 侧改）：
  1. `SaveTask` 加 `normal_path` + `std::vector<float> normal_pixels`（w*h*3 float）
  2. 现有 map loop 顺手把 `row[x*4+0..2]` 写进 `normal_pixels`（同一个 map 调用、
     零额外 GPU→CPU 拷贝）
  3. 仿照 `SaveEXR()` 写 3-channel RGB EXR helper（或扩 SaveEXR 加
     `num_channels` 参数），按 `enableNormalExp` flag 决定是否调
  4. 文件名 `NormalBuffer.exr`（`reshade_grabber.py` 已按这名字 poll triplet）

  **顺手清理**: `SaveTask::depth_pixels` 的 doc comment (line 126
  `// RGBA32F, depth_w*depth_h*4, no padding`) stale — 实际 resize 到 `w*h*1`
  (line 1079), 改成 `// scalar Y32F, depth_w*depth_h, no padding`.

  **关于 xiaoni 的 (a)**: RDC `image_loader._normalize_depth` 复用是否安全 ——
  ReShade EXR 是 raw float scalar（无 percentile pre-normalize），跟 RDC
  reversed-Z float depth 同 range/semantics，复用 OK。reversed_z 旗是 per-game
  的 (`capture_profile`)，逻辑相同。

  **工时**: 1-1.5h (SaveTask + map loop + 3-channel SaveEXR + 烟测).
  Path A (RDC) 的 normal 走 `normal.png` (RGBA8) 不冲突。

- [ ] **P0 (今日必跑通): ReShade AOB camera control 端到端实机验证** (from 老白 2026-05-13)

  **指令**: 今天必须跑通 ReShade Path B 的 AOB 路径，**做到和 RenderDoc Path A 路线功能一致**——即用 ReShade dxgi.dll 注入目标游戏后，能锁相机、走 trajectory、出 RGB+Depth+Normal 三件套。

  **代码现状（已具备）**:
  - C++ side: `3rdparty/reshade/source/captureAIshi/bridge.cpp` 8 条 `__cam_intercept_*` + 2 条 `__cam_mem_poke/peek` 路由（`4c75689` 已推）
  - C++ side: `camera_intercept.h` 649 行 ported from RDC（NOP/PASS/CAPTURE + jmp trampoline）
  - Python side: `drivers/game_profile.py` 全套 helper（`apply_profile` / `lock_camera` / `unlock_camera` / `capture_all` / `get_captured_addr` / `mem_poke`）
  - Configs: `configs/hacks/batman_ak.json`（UE3, 3 intercepts, AOB 完整）+ 8 款 Tier-1 UE5 配置
  - Frame capture: `frame_capture.cpp` 嵌入 ReShade core (`cd631a4`)；`grabbers/reshade_grabber.py` 14 unit tests 通过 (`41d7e26`)
  - Deploy: `scripts/deploy_reshade.py --game-dir <dir>` 拷 dxgi.dll + addon + shader + 写 sidecar

  **今天必做的 5 步 (Batman AK 作为 canonical 目标)**:

  1. **Build ReShade dxgi.dll on Windows** — `cd 3rdparty/reshade && msbuild ReShade.sln /p:Configuration=Release /p:Platform=x64`。预期编译错误（`cd631a4` CL 自己写了"expect a couple iterations"）：FormatEnum symbol clash / `/utf-8` mismatch / winsock 双 include / stb_image_resize 重复定义 — 一个一个 fix。
  2. **Deploy**: `python scripts/deploy_reshade.py --game-dir <Batman AK 目录> --output-dir <捕获输出>`。验证 `dxgi.dll`、`fc_output_dir.txt` sidecar 在游戏目录。
  3. **启游戏 + bridge 连接**: 起 Batman AK，ReShade overlay 应显示 "captureAIshi Bridge"。`telnet 127.0.0.1 9998` 测 `__bridge_ping` 回 `pong`。
  4. **AOB 端到端**:
     ```
     __cam_intercept_uninstall                    # clean slate
     __cam_intercept_install_aob 33 1 cam_xyz_literal | 89 83 74 05 ... (从 batman_ak.json 抄)
     __cam_intercept_list                          # 看 site 装上没
     __cam_intercept_capture                       # 切 CAPTURE 模式
     # 游戏里动一下相机让 hook 命中
     __cam_intercept_get_capture 0                 # 拿到 rbx 值 (PlayerCameraManager+0x?)
     __cam_intercept_nop                           # 锁住游戏写
     __cam_mem_poke <rbx_hex> 574 f32 1000.0       # 写 X 坐标 +1000 单位 (Batman UE3 cm scale)
     ```
     **验收**: viewport 里相机平移可见。看不见 = 真没跑通。
  5. **跟 Python driver 接上**: `python -c "from drivers.game_profile import apply_profile, lock_camera, capture_all, get_captured_addr, mem_poke; apply_profile('batman_ak'); ..."`。期待和手敲 TCP 命令等价。

  **不收 (本周仅 AOB 路径)**:
  - UE5 pov_ptr scanner (`ue5_scan_camera.h` 移植) → 推迟到下周
  - Tier-2/3 游戏 → 推迟
  - HUD toggle / timestop → 不动

  **失败模式排查清单 (按概率)**:
  - dxgi.dll build 失败 → 看 link error，多半是 stb / tinyexr 重复符号或 ws2_32 没 link
  - dxgi.dll inject 失败 (ReShade overlay 不出) → 游戏目录有 Steam DRM `__Installer\` 拦 LoadLibrary → 试 `ReShade Loader` mode 或换 Vulkan loader
  - `__cam_intercept_install_aob` 报 `pattern not found` → AOB 字节漂了 (游戏更新过) → 用 `__cam_intercept_install_aob ... wildcard` 备选；CE 复扫
  - `__cam_intercept_get_capture 0` 返 `slot empty` → CAPTURE 模式装上后游戏代码没命中 → 移动相机让 UpdateCamera 跑
  - `__cam_mem_poke` 不动 camera → rbx 不是 PlayerCameraManager 基址 → 比对 RDC Path A 拿到的 rbx 值
  - 命令字符串拼错 → `grep -n __cam_intercept bridge.cpp drivers/game_profile.py` 对一遍

  **验收 (今天结单条件)**:
  - 实机 Batman AK + ReShade dxgi.dll: 5 步全过，viewport 相机能被 Python 控制
  - `agents/rendering/SHARED.md` 加 CL 条目（含 sha 或 pending sha）签 xiaoxuan
  - 如果实机有阻塞（build error 解不掉、AOB 找不到、游戏 inject 失败），把 stuck 点完整贴回 SHARED.md，老白来调度
  - 不需要 Tier-2 游戏验证；Batman AK 一款跑通就结

  **工时**: 一个工作日内必须有结果 (跑通或贴明确阻塞)

  **背景**: 用户要求"reshader 跑通 renderdoc 路线一致"。RenderDoc Path A 在 03ce4a8 已 fix per-pose capture chain，trajectory 端到端通了。今天的目标是 ReShade Path B 达到同样状态。如果今天跑通，下周才轮到 PCG / unreal_pcg_robot agent 启动；跑不通则继续 hold。

- [x] **P1: ReShade Path B — UE5 pov_ptr 扫描 + mem_find/read/on/off 路由** (handoff from 小萱 2026-05-13, done by 小宣6 2026-05-13)

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

- [ ] **P2: F6 in-game trigger for survey capture** (handoff to 小宣6 from 用户 2026-05-13)

  痛点：当前要触发一次 capture 必须 Alt+Tab 切回 Web UI 点按钮 —— 全屏游戏下打断沉浸 + 切回时机不可控。

  方向：
  1. `bridge.cpp`（已有 hotkey 钩子框架的话）或 `frame_capture.cpp` 的
     每帧 hook 里加 `GetAsyncKeyState(VK_F6)` **边沿触发**（记上一帧的
     按下状态，仅在 released->pressed 转换点触发，避免连发）
  2. 触发后调 `__fc_survey_start` 内部入口（已有 TCP 命令；本地直接调
     函数即可，不用走 socket round-trip）
  3. Hotkey 应可配（ini key `FC_TriggerHotkey`，默认 `VK_F6=0x75`）；
     UI checkbox "Enable In-Game Hotkey" gate 一下
  4. 跟现有 frame_capture / fc_survey 流不冲突 —— 是新的触发源，不
     改 capture pipeline 本身

  **风险**：
  - GetAsyncKeyState 在不获焦窗口也会返回真，可能误触发 —— 加
     `GetForegroundWindow() == g_game_hwnd` 做 gate
  - 某些游戏吃所有键盘（DirectInput exclusive）—— 用 RegisterHotKey 而非
     GetAsyncKeyState 反而更稳，因为是 Win32 message queue 注入

  **工时**: 1-2h（含两种实现方式择一 + UI checkbox + ini key + 烟测）

## TODO (from lead review)

- [x] **P2: depth_curve 跨域改动** (spotted by 小逆, reviewed by 小萱 2026-05-12) — 用户报告 Batman PNG 远景 city 段塌成 near-white。我在 `image_loader._normalize_depth` 加了 `depth_curve` 参数（"linear" / "gamma" / "log"），`batman_ak.json` 默认 "log"。代码在你域 (grabbers/) 里，麻烦 review 一下：(1) curve 实现是否合理（log on raw before percentile，保留 monotonic 极性）；(2) 其他 outdoor 配置（ac6 / metro_exodus / black_myth_wukong）也建议默认 "log"；(3) 字段已加到 `_schema.md`。

### UI 同学需要注意

1. **trajectory.json 是给 AI 训练用的输出文件**，UI 可以读取它做可视化但不需要修改
2. **文件命名变了**：不再是 `rgb_000000.png`，而是 `{timestamp}_{viewName}.png`
3. **新增了 Normal 图片**：`_n.png` 后缀，RGB 格式的世界法线贴图
4. **lightbox 预览** 需要支持三种图片类型：RGB / Depth (`_d.png`) / Normal (`_n.png`)
5. **进度面板** 可以从 trajectory.json 读取 viewName 和 pointIndex 显示当前拍摄位置
6. **3D 可视化器** 可以直接用 trajectory.json 里的 Position + Rotation 画相机锥体

## Changelog

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
