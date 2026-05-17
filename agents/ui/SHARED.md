# UI Agent (小由) — Shared Notes

## Active TODO

- [ ] **P1: launcher 启动 captureAIshi 默认 demo 模式 (复选框)** (from 用户 via xiaoxu) -- 启动按钮旁边加个 click box "Demo 模式" (默认勾上), 勾上时 launcher spawn capture 子进程注入 `DEMOAISHI=1`. 用户表述: "captureAIshi 这个版本默认以demo 方式运行 / 或者有个 click box". 落点:
  - `apps/launcher/server.py` 的 capture card (大约 L314-L327) 在 `app-launch` 按钮上方加 `<label><input type="checkbox" id="demo-toggle-capture" checked> Demo 模式</label>` (深色 capture brand checkbox 样式自己写)
  - 前端 `launchApp('capture', btn)` JS (大约 L300+) 改成读 checkbox 状态, POST body 加 `{demo: bool}`
  - 后端 `POST /api/launch/<app>` handler (大约 L60-90 的 launch 函数, 调 `subprocess.Popen(cfg["cmd"], cwd=cfg["cwd"])`) 改成: 读 request.json 的 `demo` 字段, 如果 True 注入 env={**os.environ, "DEMOAISHI": "1", "DEMOAISHI_SCENARIO": "batman_ak"} 传给 Popen
  - `DEMOAISHI` env 机制详情见 `apps/capture/web/demo.py` is_demo_mode() + Dockerfile 第 10-11 行
  - adore_robot 暂时**不需要** demo 复选框 (adore_robot 当前整体就是 mock 状态; 等真接 UE MCP 后再加)
  - 顺便可以把启动 captureAIshi 的按钮文字改成"启动 captureAIshi · Demo" 更直观

- [ ] **P1: launcher hero/footer 写的 UE 5.6 该改 5.8** (spotted by xiaoxu, 用户报) -- `apps/launcher/server.py` 三处硬编码:
  - L305 `<div class="hero-tag">v0.3.0 · POWERED BY UNREAL ENGINE 5.6 + NVIDIA COSMOS</div>` -> `UE 5.8 Preview`
  - L338 `<div class="app-meta-item"><span class="app-meta-dot"></span>UE5.6 + PCG + Robotics Plugin</div>` -> `UE 5.8`（且 Robotics Plugin 部分需重新表述，老白派单 P0-2 已明确 Epic 5.8 无官方 Robotics Plugin，参考 `apps/adore_robot/docs/ue58_engine_notes_xiaoxu.md` §5；建议写 `UE 5.8 + PCG`，机器人字样去掉或改 `URDF kinematic posing`）
  - L363 `<span class="footer-badge">UNREAL ENGINE 5.6</span>` -> `UNREAL ENGINE 5.8`
  - 顺手扫一下整个 `apps/launcher/server.py` 是否还有 "5.6" / "UE5.6" 残留
  - 用户看到的是 hero-tag 那行 ("v0.3.0 · POWERED BY UNREAL ENGINE 5.6")，最影响外部观感

_全部清空 2026-05-13（老白 by 用户指令）— 旧 TODO 清单 + 恢复方式见 `agents/ui/ARCHIVE.md` 末尾 "Cleared 2026-05-13" 段。新方向 TODO 待老白下次重派。_

## [v0.3.0] UI 重构任务 (from lead)

目标：从"开发者工具"转型为"游戏选择 → 捕捉"的完整工作流。

### Task 5: 右栏重构 — 设置面板分离 (P0) ✓ (cascade lv2/lv3)
### Task 6: 游戏选择菜单 (P0) ✓ 字母索引 + 分组 + 全量渲染; 虚拟滚动暂缓 (<200 games)
### Task 7: 内部代码隐藏 Unity 支持 (P1) ✓ (showAllEngines Advanced toggle)

详见 `agents/ui/ARCHIVE.md` 的完整 task 描述。

## Design Guidelines
- Dark theme + CSS variable system
- Vanilla JS or Alpine.js, no React/Vue
- Desktop only, all APIs in `web_ui.py`
- Test: `python web_ui.py` → http://localhost:5000

## Changelog (latest)

### [v0.3.0] — 小由 (爱萌官网 WP-lite stack 与 demo 同 ECS)
- 新增 `wp-stack/docker-compose.yml`: MySQL 8 (tuned) + WP 6.5 (php-fpm-alpine) + Nginx, RAM 上限合计 ~550MB, 2GB ECS 余量充足
- MySQL tuning: innodb_buffer_pool_size=64M, max_connections=20, performance_schema=OFF -> 从默认 600MB 砍到 ~280MB
- 端口 8081 (demo 占 8080), `.env.example` + `.gitignore` 防泄密码
- `docs/deploy_wp.md`: 一次性部署 + 安全组 + 首次安装向导 + Astra Starter Templates 推荐 + 必装插件 + 升级/备份 + MariaDB 切换备案
- 用户决定先用 MySQL 试,瓶颈再切 MariaDB

### [v0.3.0] — 小由 (Demo Mode: 7-pose Batman + 3D progressive draw)
- `manifest.json`: total_poses 30 -> 7, pose_dwell 0.45 -> 2.0 (节奏更接近真实抓帧, 总时长 ~27s)
- `script.json` postamble 改成"逐帧 decode" 7 行, 听感像真跑 renderdoccmd
- 新增 `frames/trajectory.json`: 7 个 orbit waypoint (r=4, 略带 y 波动), 视图绕原点
- `demo.py` `DemoSession` 在 pose loop 里发布 `demo_pose` 到 `_capture_state`
- `routes/capture.py` `/api/status` 返回 `demo_pose` + `demo_total`
- `index.html` startCapture 在 demo 分支自动 `switchCenterTab('3d')` + 启 rAF 循环刷新画面
- `draw3d` 改: 已抓 waypoint 实色 + 当前 waypoint 橘色脉动 + 未抓 waypoint 半透灰 + 未来段虚线
- startPolling 拾取 `demo_pose`, demo 结束自动停 anim loop, 复位 0 显示完整路径
- 7 帧虚拟 + 3D 实时画路径 = 客户能看到"相机沿轨迹拍照"的过程

### [v0.3.0] — 小由 (Demo Mode step 4: Dockerfile + 部署 README)
- 新增 `Dockerfile` (python:3.11-slim + gunicorn 1 worker / 4 threads, 默认 DEMOAISHI=1, DEMOAISHI_SCENARIO=batman_ak, PORT=8080)
- 新增 `requirements-demo.txt` (flask + numpy + gunicorn 三件套, 不含 cv2/obsws/mss/Pillow/pywebview/requests)
- 新增 `.dockerignore` (剔 renderdoc/, 3rdparty/, output/, *.rdc/*.exr, recorders/obs_recorder.py, desktop_app.py, tests/, agents/, .claude/, docs/refCode/) -- 镜像目标 ~150MB
- `web_ui.py` `_ensure_exr_loader()` 在 demo 下跳过 (省 30s 冷启 + 80MB cv2)
- 新增 `docs/deploy_demo.md`: docker build/run 本地 + Fly.io / Render / Railway / VPS 四条部署路径 + 真帧 drop-in 流程 + 新场景模板 + curl smoke test
- 用 meta_path GuardLoader 验证 demo 全流程 import 不触 cv2/obsws/webview/mss/PIL/requests, 烤镜像深度可控

旧版 CL 见 `agents/ui/ARCHIVE.md`。
