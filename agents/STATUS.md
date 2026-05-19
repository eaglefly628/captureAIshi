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
| 小幻 (PCG) | ~67% | 2026-05-15 | v0.3.2 P0 Step 1-4 + P1 from xiaoxu 6 项全 done (e484db1)；补丁 9a77993: 老白 5f1cfa2c P0 反向影响 -- 三场景 JSON 加 `robotics_backend` + `robotics_backend_compatible`，contract 加 §7 (5 节) + 重编号旧 §7→§8，写 P1 到 xiaoxu SHARED 要 batch UI 多 backend 显式表达。**注意: 已收到 v0.3.3 P1 (老白 2026-05-16 方向 B MCP, AICallable 映射表)** —— 单源 in v2 doc §2.2-§2.4，本 contract 待加 §8 两行 + 链接 + §4 Example 6 (MCP tool call 序列)。**新增 v0.3.3 P0 (xiaoxu via 用户 2026-05-17)**: 真 PG_Warehouse / PG_LivingRoom / PG_IndustrialCorner graph + sample .umap 让 PCG Volume 真 spawn 仓库物件。|
| 小虚 (UE5 Fullstack) | ~58% | 2026-05-19 | **MCP 全链路 + 客户级开机进度条**. 修掉 SSE 阻塞 bug (61e0a55): UE 5.8 返回 text/event-stream 不主动关连接, resp.read() 死等到 ~15s idle timeout -- 改为读完第一个 `data:` 事件 + 空行就 break, 单 RPC 16s -> 330ms, 4 toolset 冷启 62s -> 4.95s, 热 4.80s. 加客户级开机 overlay (66e429b): mcp_client.auto_load_toolsets 接 progress_cb; main.py 起 INIT_PROGRESS 后台线程 + /api/mcp/init GET/POST; main.jsx McpBootOverlay 每 250ms 轮询, 神经握手文案 + ◈ 旋转 + 扫描线 + 加载日志, 4 toolset 映射成 "编辑器内核 / 对象反射层 / 场景态势引擎 / 程序化沙箱". 仍等老白拍板"跳过 UPCGAdoreToolset C++" + xiaohuan 交 PG_Warehouse / PG_LivingRoom / PG_IndustrialCorner 真 graph. |
