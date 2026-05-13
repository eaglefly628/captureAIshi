# Agent Context Status

Auto-updated by each agent after every response.

| Agent | Context | Last Updated | Notes |
|-------|---------|-------------|-------|
| 主程序员 | ~20% | 2026-04-18 | extract_for_review.bat 推送完成；小逆4项P0/P1 bug(cmd_queue/socket UAF/SuspendThread死锁/cam_mem_find锁)待修 |
| Opus 4.7 (lead) | ~40% | 2026-04-19 | 0fa5f42 Debug Advanced AOB 默认展开 (Windows 点不开 workaround)；给小逆在 reversing/SHARED.md 留 pytest 永久解 note (pull mainbranch 拿 pytest.ini timeout=20)。pytest 本地 sandbox 无 pytest 模块未跑通 |
| 小由 (UI) | ~30% | 2026-04-22 | v0.3.0 Task 6 字母索引 + 分组完成; Task 5/7 之前 session 已 done; 虚拟滚动暂缓 (<200 games) |
| 小萱 (Rendering) | ~55% | 2026-05-13 | ReShade AOB injection implemented: pattern_scan.h+scan_main_module_nth, new camera_intercept.h, bridge.cpp+8 routes (install_aob/nop/pass/list/uninstall/capture/get_capture/poke/peek) + shutdown cleanup. Parity with RDC Path A. |
| 小逆 (Reversing) | ~5% | 2026-04-27 | 接力 session 起步 @ f22fd64. Briefing 收到: HB2 实测待用户反馈 (P0). 6 款 Tier-1 配置 (hellblade_2/avowed/oblivion_remastered/the_quarry/the_invincible/south_of_midnight) intercepts+camera_write_profile 全填好, 未真机验. 待 HB2 日志回来调 hellblade_2.json AOB/偏移/depth_curve, 然后推 Tier-2. |
