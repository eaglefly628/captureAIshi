# Agent Context Status

Auto-updated by each agent after every response.

| Agent | Context | Last Updated | Notes |
|-------|---------|-------------|-------|
| 主程序员 | ~20% | 2026-04-18 | extract_for_review.bat 推送完成；小逆4项P0/P1 bug(cmd_queue/socket UAF/SuspendThread死锁/cam_mem_find锁)待修 |
| Opus 4.7 (lead) | ~40% | 2026-04-19 | 0fa5f42 Debug Advanced AOB 默认展开 (Windows 点不开 workaround)；给小逆在 reversing/SHARED.md 留 pytest 永久解 note (pull mainbranch 拿 pytest.ini timeout=20)。pytest 本地 sandbox 无 pytest 模块未跑通 |
| 小由 (UI) | ~30% | 2026-04-22 | v0.3.0 Task 6 字母索引 + 分组完成; Task 5/7 之前 session 已 done; 虚拟滚动暂缓 (<200 games) |
| 小萱 (Rendering) | ~78% | 2026-04-21 | CL 条目补齐 (35099b5/d62c704/a9ec4f9/919c6ea/40ec164) 推送中。下一步: Cyberpunk -vulkan 验证 + 2.12 AOB 重扫 + Hellblade build 7800612 AOB rescan |
| 小逆 (Reversing) | ~99% | 2026-04-18 | UI Phase 1 (2325ee6) + Gemini sweep + UI bug fixes (c656837): strtof locale / dead socket / g_smooth_factor atomic / UObject GC lifecycle / Advanced toggle / Lv2 capture-area removed. Deferred to NEXT SESSION: (a) __try call-chain audit, (b) Catmull-Rom centripetal, (c) UI Phase 2 = main.py trajectory-driven capture + legacy form removal, (d) RDC capture trigger wire-up per waypoint, (e) cone into trajectory JSON, (f) Commit D UE auto-discovery. 46 tests green. |
