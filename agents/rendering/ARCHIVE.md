# Rendering Agent (小萱) — Archive

已完成 TODO 和旧版 CL。从 SHARED.md 归档以节省 token。

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
