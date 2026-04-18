# Agent Context Status

Auto-updated by each agent after every response.

| Agent | Context | Last Updated | Notes |
|-------|---------|-------------|-------|
| 主程序员 | ~20% | 2026-04-18 | extract_for_review.bat 推送完成；小逆4项P0/P1 bug(cmd_queue/socket UAF/SuspendThread死锁/cam_mem_find锁)待修 |
| 小由 (UI) | ~30% | 2026-04-05 | Camera Path Editor + Game Library + Per-Game Profiles done, pushed |
| 小萱 (Rendering) | — | — | — |
| 小逆 (Reversing) | ~90% | 2026-04-18 | Commits A/B/C + Opus 4.7 sweeps + UI Phase 1 (2325ee6): Bridge Debug refactor (AOB ops collapsed under Advanced), custom trajectory preset, save/load API, auto-preview on change, RDC capture flag plumbed (trigger lands in Phase 2). Library trimmed to 6 games (ee9a5db). 46 tests green. Next: UI Phase 2 = backend capture migration + legacy form removal. |
