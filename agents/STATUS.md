# Agent Context Status

Auto-updated by each agent after every response.

| Agent | Context | Last Updated | Notes |
|-------|---------|-------------|-------|
| 主程序员 | ~20% | 2026-04-18 | extract_for_review.bat 推送完成；小逆4项P0/P1 bug(cmd_queue/socket UAF/SuspendThread死锁/cam_mem_find锁)待修 |
| Opus 4.7 (lead) | ~40% | 2026-04-19 | 0fa5f42 Debug Advanced AOB 默认展开 (Windows 点不开 workaround)；给小逆在 reversing/SHARED.md 留 pytest 永久解 note (pull mainbranch 拿 pytest.ini timeout=20)。pytest 本地 sandbox 无 pytest 模块未跑通 |
| 小由 (UI) | ~30% | 2026-04-22 | v0.3.0 Task 6 字母索引 + 分组完成; Task 5/7 之前 session 已 done; 虚拟滚动暂缓 (<200 games) |
| 小萱 (Rendering) | ~70% | 2026-04-22 | c80a2cb: per-game capture config (--game ID, --depth-index, --no-reverse-depth); batman_ak depth_reversed_z=false. 下一步: 用 RenderDoc 打开 batman.rdc 确认 rgb/depth/normal texture index |
| 小逆 (Reversing) | ~88% | 2026-04-22 | Batman ue3_packed_int deg->packed int32 conversion landed (game_profile + trajectory_player + tests, 35/35 non-Flask green). Next: RDC capture sync (req1: block play loop on capture done, not sleep), post-capture analyze phase (req2: run RDC output without exiting). Deferred: __try audit, Catmull-Rom centripetal, UI Phase 2, Commit D UE auto-discovery. |
