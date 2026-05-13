# Agent Context Status

Auto-updated by each agent after every response.

| Agent | Context | Last Updated | Notes |
|-------|---------|-------------|-------|
| 主程序员 | ~20% | 2026-04-18 | extract_for_review.bat 推送完成；小逆4项P0/P1 bug(cmd_queue/socket UAF/SuspendThread死锁/cam_mem_find锁)待修 |
| 老白 (lead) | ~80% | 2026-05-13 | 用户指令清空 3 agent SHARED.md TODO 区 -> ARCHIVE.md `Cleared 2026-05-13` 段（ui 6 / rendering 6 / reversing 11 共 23 项），新方向 TODO 待重派。docs/ui_pcg_redesign_plan.md 留仓存档参考。|
| 小由 (UI) | ~30% | 2026-04-22 | v0.3.0 Task 6 字母索引 + 分组完成; Task 5/7 之前 session 已 done; 虚拟滚动暂缓 (<200 games) |
| 小萱 (Rendering) | ~60% | 2026-05-13 | 4c75689 ReShade AOB intercept (Tier-1) pushed. Next: UE5 pov_ptr path = port ue5_scan_camera.h + 4 routes (__cam_mem_find/read/on/off). Handoff note in agents/rendering/SHARED.md TODO P1. |
| 小宣6 (Rendering) | ~80% | 2026-05-13 | e009a6d ReShade Path B UE5 pov_ptr scanner pushed (auto-merge 432ddd1). Ported scan_engine/world/camera (~2913 LOC) + ue5_engine.h orchestrator rewrite + 4 __cam_mem_* routes + shutdown cleanup. Follow-up: __cam_mem_write + camera_tick_thread wiring (override flag armed but write side not wired). |
| 小逆 (Reversing) | ~55% | 2026-05-13 | Batman AK ReShade Path B: capture_profile 已接（8854614）+ 第一次自动 pre-UI survey + persist `FC_PreUISkipCount`（`.captureAIshi_skip.txt` sidecar）+ survey 后自动重启游戏让 addon 重读 ini。normal-on-disk 仍依赖 xiaoxuan 在 frame_capture.cpp 加 save 路径（rendering/SHARED.md P1）。|
