# Agent Context Status

Auto-updated by each agent after every response.

| Agent | Context | Last Updated | Notes |
|-------|---------|-------------|-------|
| 主程序员 | ~20% | 2026-04-18 | extract_for_review.bat 推送完成；小逆4项P0/P1 bug(cmd_queue/socket UAF/SuspendThread死锁/cam_mem_find锁)待修 |
| 老白 (lead) | ~55% | 2026-05-13 | 收尾 RenderDoc P0 工单归档 → ARCHIVE。9.1.6 NVIDIA Inception/schema 调研暂缓。本周双线：ReShade AOB camera control 今日必跑通（派 xiaoxuan，rendering/SHARED.md P0），跑通后开 unreal_pcg_robot agent（知识库已落 .claude/agents/unreal_pcg_robot.md，SHARED 暂搁）|
| 小由 (UI) | ~30% | 2026-04-22 | v0.3.0 Task 6 字母索引 + 分组完成; Task 5/7 之前 session 已 done; 虚拟滚动暂缓 (<200 games) |
| 小萱 (Rendering) | ~60% | 2026-05-13 | 4c75689 ReShade AOB intercept (Tier-1) pushed. Next: UE5 pov_ptr path = port ue5_scan_camera.h + 4 routes (__cam_mem_find/read/on/off). Handoff note in agents/rendering/SHARED.md TODO P1. |
| 小宣6 (Rendering) | ~80% | 2026-05-13 | e009a6d ReShade Path B UE5 pov_ptr scanner pushed (auto-merge 432ddd1). Ported scan_engine/world/camera (~2913 LOC) + ue5_engine.h orchestrator rewrite + 4 __cam_mem_* routes + shutdown cleanup. Follow-up: __cam_mem_write + camera_tick_thread wiring (override flag armed but write side not wired). |
| 小逆 (Reversing) | ~45% | 2026-05-13 | Batman AK ReShade Path B 跑通 AOB；fix `reshade_grabber.py` 接 `capture_profile`：`rgb_strategy:pre_ui→FC_PreUICapture=1`、`normal_strategy 非空→FC_ExportNormal=1`、`save_frame` EXR→PNG (curve+reversed_z)。`main.py` 加 `_load_capture_profile`。peer-review 给小萱 rendering/SHARED.md P1。重启游戏后 ini 生效。 |
