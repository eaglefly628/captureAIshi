# Rendering Agent (小萱) — Archive

已完成 TODO 和旧版 CL。从 SHARED.md 归档以节省 token。

---
## Archived 2026-05-13 (auto-archive: beyond top 3 CL + closed TODOs)

### Closed TODOs

- [x] **P0: RenderDoc trajectory 每 pose 触发链路断了** (spotted by 主程序员, fixed 03ce4a8 by 小萱) — `trajectory_player.py` 改 isinstance(g, ReShadeGrabber) 派发: ReShade→`__fc_capture`, 其他→`g.trigger_capture()`. `__cam_rdc_capture` 字符串从 Python 全清 (grep 0 命中). 验收 Batman/StackOBot/ReShade 三路径不回归.
- [x] **P1: 99308e9 EXR depth 没补 requirements.txt** (spotted by 小逆, fixed 1d53bf2) — `image_loader.load_depth_image` 三选一 cv2/imageio/OpenEXR 全没装的话整批 capture 的 depth 都会失败（用户报告：rgb+normal 出图但 depth 为 0）。已加 `opencv-python>=4.5.0`。下次改 file format 麻烦顺手 bump deps。
- [x] **P0: RGB 导出抓了 SwapBuffer 而不是 SceneColor** — Fixed: exportframe 现在用 SceneColor (第一个 Float ColorTarget) 作为 RGB 源，SwapBuffer 仅用于确定 viewport 分辨率。非 UE5 游戏如果没有 HDR ColorTarget 会 fallback 到 SwapBuffer。
- [x] **P1: batch export 路径缺 normalImg** — Fixed: `to_trajectory_dict()` 新增 `normal_filename` 参数，per-frame 和 batch 两条路径都填充 `normalImg`。
- [x] **P1: .claude/ 迁移验证** (from lead) — 已验证：(1) `.claude/agents/rendering.md` 完整覆盖职责、C++规则、图像知识，与旧 CLAUDE.md 一致。(2) `.claude/rules/cpp-rules.md` 和 `.claude/rules/no-sleep.md` 适用于渲染领域。(3) 小由 a5f8859 review 结果见下方 P1。
- [x] **P1: a5f8859 export_batch stderr 管道风险** (spotted by 小萱, fixed by 主程序员) — 改为 `stderr=subprocess.STDOUT`，stderr 合并到 stdout 在同一循环中读取，删除 `proc.wait()` 后的死代码 `proc.stderr.read()`。
- [x] **P1: f35632d + f4292f5 越界修改 main.py** (spotted by 主程序员) — 已确认：main.py 的 batch/per-frame 路径改动是为了集成 trajectory 输出和 batch export，属于渲染管线的输出格式变更。后续涉及 main.py 的改动会在 SHARED.md 先提跨域请求。
- [x] **P1: f35632d locals().get() 反模式** (spotted by 主程序员) — Fixed: 在 try 块前初始化 `normal_filename = ""`，删除 `locals().get()` 调用。
- [x] **P2: 5 个 commit 缺独立 CL 条目** (spotted by 主程序员) — 已补录 f35632d/f901bc8/ebe4a7d/f4292f5/8c6160e 的 CL 条目到 Changelog 段落。

### Archived CL entries (beyond top 3)

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

---

## Completed TODO

- [x] **P0: RGB 导出抓了 SwapBuffer** — Fixed: 改用 SceneColor。
- [x] **P1: batch export 缺 normalImg** — Fixed: `to_trajectory_dict()` 新增 normal_filename。
- [x] **P1: .claude/ 迁移验证** — 已验证。
- [x] **P1: export_batch stderr 管道风险** (fixed by 主程序员) — `stderr=subprocess.STDOUT`。
- [x] **P1: 越界修改 main.py** — 已确认属渲染管线变更，后续跨域先在 SHARED.md 提请求。
- [x] **P1: locals().get() 反模式** — Fixed: 初始化 `normal_filename = ""`。
- [x] **P2: 5 个 commit 缺 CL** — 已补录。

## Detailed Specs

### CameraPose 新增字段
`core/waypoint.py`: aspect, view_name, point_index, spline_mode, to_trajectory_dict(), euler_to_quaternion() (YXZ)

### Normal Buffer 导出
检测: 第一个非 SwapBuffer、viewport 匹配、3+ 组件的 ColorTarget (fmtType=12 R10G10B10A2)

### FrameGrabber 扩展
`grabbers/base.py`: FrameData(rgb, depth, normal), capture_frame_ex(), save_frame(base_name, normal)

## Changelog (v0.2.0)

### [v0.2.0] b542e7e — 小萱
- trajectory.json, Normal 导出, batch 截帧/导出, DLSS/FSR/TSR 关闭, Interactive trigger, SceneColor RGB, Fastest replay, temp 文件清理

### [v0.2.0] f35632d — normalImg 加入 trajectory
### [v0.2.0] f901bc8 — batch_export 清理代码修复
### [v0.2.0] ebe4a7d — 首帧 warm-up + Fastest replay
### [v0.2.0] f4292f5 — Normal fmtType=12 + GBuffer 诊断日志
### [v0.2.0] 8c6160e — Windows stderr 死锁修复

---

## Cleared 2026-05-13 (user requested clean slate before new PCG direction)

All Active TODO items cleared from SHARED.md. To recover full content:
  git show 039e250:agents/rendering/SHARED.md
or browse:
  https://github.com/eaglefly628/captureAIshi/blob/039e250/agents/rendering/SHARED.md

Inventory (TODO from lead -- 老白 2026-05-13, 5 items):
- [P0] (今日必跑通) ReShade AOB camera control 端到端实机验证
- [P1] 复核 ReShade depth EXR->PNG 归一化路径
- [P1] (done by 小宣6) FC_ExportNormal 半成品修复
- [P1] (done by 小宣6) ReShade Path B UE5 pov_ptr 扫描移植
- [P2] F6 in-game survey trigger hotkey
- [P2] F6 overlay 死键 — addon 没注册 keypress handler
TODO (from lead review, 1 item):
- [P2] (done) depth_curve 跨域改动
