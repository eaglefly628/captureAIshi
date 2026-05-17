# Agent Context Status

Auto-updated by each agent after every response.

| Agent | Context | Last Updated | Notes |
|-------|---------|-------------|-------|
| 主程序员 | ~20% | 2026-04-18 | extract_for_review.bat 推送完成；小逆4项P0/P1 bug(cmd_queue/socket UAF/SuspendThread死锁/cam_mem_find锁)待修 |
| 老白 (lead) | ~60% | 2026-05-17 | v0.3.3 第一刀（替 xiaoxu 交付 P0 doc + 公共 LLM factory + MCP plumbing peer review）: `apps/adore_robot/llm/` 5 文件 7 provider 抽象 (deepseek 默认), `mcp_client.py` _rpc 加 _retry budget, `docs/batch_scene_gen_architecture_v2.md` 取代 v1, `docs/robotics_poser_interface.md` ABC 三接口化 + Plan C 先实现. xiaoxu 接力: plugin .h 落地 + robotics/ skeleton + UE5.8 plugin verify. |
| 小由 (UI) | ~30% | 2026-04-22 | v0.3.0 Task 6 字母索引 + 分组完成; Task 5/7 之前 session 已 done; 虚拟滚动暂缓 (<200 games) |
| 小萱 (Rendering) | ~60% | 2026-05-13 | 4c75689 ReShade AOB intercept (Tier-1) pushed. Next: UE5 pov_ptr path = port ue5_scan_camera.h + 4 routes (__cam_mem_find/read/on/off). Handoff note in agents/rendering/SHARED.md TODO P1. |
| 小宣6 (Rendering) | ~80% | 2026-05-13 | e009a6d ReShade Path B UE5 pov_ptr scanner pushed (auto-merge 432ddd1). Ported scan_engine/world/camera (~2913 LOC) + ue5_engine.h orchestrator rewrite + 4 __cam_mem_* routes + shutdown cleanup. Follow-up: __cam_mem_write + camera_tick_thread wiring (override flag armed but write side not wired). |
| 小逆 (Reversing) | ~55% | 2026-05-13 | Batman AK ReShade Path B: capture_profile 已接（8854614）+ 第一次自动 pre-UI survey + persist `FC_PreUISkipCount`（`.captureAIshi_skip.txt` sidecar）+ survey 后自动重启游戏让 addon 重读 ini。normal-on-disk 仍依赖 xiaoxuan 在 frame_capture.cpp 加 save 路径（rendering/SHARED.md P1）。|
| 小幻 (PCG) | ~55% | 2026-05-15 | v0.3.2 P0 Step 1-4 + P1 from xiaoxu 6 项全 done: `apps/adore_robot/docs/ue58_pcg_notes_xiaohuan.md` + `pcg_param_contract.md` (三场景参数表 + override key + 5 few-shot + asset pack 索引 + Asset Checklist) + 三场景 `<scene>_v0.json` (含 thumbnail_camera + pcg_params 默认值)。单点依赖: xiaoxu 装 5.8 后回填 PCGComponent Python method 真名 (contract §2 placeholder)。|
| 小虚 (UE5 Fullstack) | ~50% | 2026-05-15 | v0.3.2 P0 已 push (cfdb7c4 在 claudeMainBranch): 2 doc + P1 to 小幻。回填 unreal/SHARED.md CL SHA (原 `(pending push)` -> `cfdb7c4`)。Robotics Plugin 红字 + Plan A/B/C 仍待老白选。peer review: 扫了 pcg/rendering/reversing/ui SHARED, 暂无跨域 bug 需要回挂。|
