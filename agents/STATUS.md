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
| 小幻 (PCG) | ~30% | 2026-05-19 | v0.3.3 用户路线简化 done: `apps/adore_robot/docs/demo_v0_simplified_contract.md` (9 节) -- v0 demo 砍到 3 actor 动作 (spawn/delete/modify_location) + 1 query (list_objects), 6 mesh 资产目录, 4 tool strict JSON schema, MCP unreal-python 实现 snippet (xiaoxu 复制即用), LLM system prompt + 6 few-shot, UE map 准备清单, 5 步演示验收脚本. 用户自己建 .umap + asset, 我 sandbox 限制不再是阻塞. v1 PG_Warehouse 11-param 路线档存 `pg_warehouse_graph_design.md` 等演示后接. 等 xiaoxu wire `/api/chat` 4 tool 转 MCP. |
| 小虚 (UE5 Fullstack) | ~58% | 2026-05-19 | **MCP 全链路 + 客户级开机进度条**. 修掉 SSE 阻塞 bug (61e0a55): UE 5.8 返回 text/event-stream 不主动关连接, resp.read() 死等到 ~15s idle timeout -- 改为读完第一个 `data:` 事件 + 空行就 break, 单 RPC 16s -> 330ms, 4 toolset 冷启 62s -> 4.95s, 热 4.80s. 加客户级开机 overlay (66e429b): mcp_client.auto_load_toolsets 接 progress_cb; main.py 起 INIT_PROGRESS 后台线程 + /api/mcp/init GET/POST; main.jsx McpBootOverlay 每 250ms 轮询, 神经握手文案 + ◈ 旋转 + 扫描线 + 加载日志, 4 toolset 映射成 "编辑器内核 / 对象反射层 / 场景态势引擎 / 程序化沙箱". 仍等老白拍板"跳过 UPCGAdoreToolset C++" + xiaohuan 交 PG_Warehouse / PG_LivingRoom / PG_IndustrialCorner 真 graph. |
