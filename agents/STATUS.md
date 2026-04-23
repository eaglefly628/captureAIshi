# Agent Context Status

Auto-updated by each agent after every response.

| Agent | Context | Last Updated | Notes |
|-------|---------|-------------|-------|
| 主程序员 | ~20% | 2026-04-18 | extract_for_review.bat 推送完成；小逆4项P0/P1 bug(cmd_queue/socket UAF/SuspendThread死锁/cam_mem_find锁)待修 |
| Opus 4.7 (lead) | ~40% | 2026-04-19 | 0fa5f42 Debug Advanced AOB 默认展开 (Windows 点不开 workaround)；给小逆在 reversing/SHARED.md 留 pytest 永久解 note (pull mainbranch 拿 pytest.ini timeout=20)。pytest 本地 sandbox 无 pytest 模块未跑通 |
| 小由 (UI) | ~30% | 2026-04-22 | v0.3.0 Task 6 字母索引 + 分组完成; Task 5/7 之前 session 已 done; 虚拟滚动暂缓 (<200 games) |
| 小萱 (Rendering) | ~20% | 2026-04-23 | 003a3d9: Tools menu (Analyze Capture File/Capture Config), Buffer Guide in Help, /api/tools/analyze_rdc + /api/hacks/profile/<id>/capture GET+POST. batman.rdc texture index 待用 Analyze工具确认 |
| 小逆 (Reversing) | ~95% | 2026-04-22 | afc35b5 Batman ue3_packed_int deg conversion + legacy volume/snake/cone capture pipeline removed (run_capture early-raises, CLI args + UI form fields + _build_args gone). Next session sweep: delete core/snake_path.py, cone_rotation.py, BoundingVolume, gui.py spinners, tests, preset-blob residuals. Deferred: RDC capture sync (req1), post-capture analyze phase (req2), __try audit, Catmull-Rom centripetal. |
