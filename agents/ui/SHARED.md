# UI Agent (小由) — Shared Notes

## Active TODO

- [ ] **P1: a5f8859 越界修改 renderdoc_grabber.py** (spotted by 主程序员) — 补写 CL + 请小萱 review + 以后跨域先在 SHARED.md 提请求。
- [ ] **P2: a5f8859 缺 CL 条目** (spotted by 主程序员) — 跨域 commit 缺 CL。
- [ ] **P1: .claude/ 迁移验证** (from lead) — 验证 `.claude/agents/ui.md` 覆盖完整。
- [ ] **P2: path_player quaternion clamp 不完整** (spotted by 主程序员) — SLERP `dot = min(dot, 1.0)` 改 `np.clip(dot, -1.0, 1.0)`。
- [ ] **P2: web_ui profile name 缺验证** (spotted by 主程序员) — `/api/config/profiles/<name>` 加 `re.match(r'^[a-zA-Z0-9_-]+$', name)` 校验。

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

### [v0.3.0] — 小由 (Demo Mode step 2: Batman scenario bundle)
- 新增 `demo/scenarios/batman_ak/` 场景包: `manifest.json` (display_name / total_poses / dwell), `script.json` (preamble + pose_template + postamble Batman-flavored), `frames/.gitkeep` (用户后续填真帧), `README.md`
- `web/demo.py` 重构: `_load_scenario(name)` 从盘加载 + 缓存; 缺失时回退 in-module default; `DemoSession.__init__(scenario: dict)` 改读 manifest 的 total_poses / dwell; pose_template 走 `.format(i, n)`
- env `DEMOAISHI_SCENARIO` 选场景, 默认 `batman_ak`
- `DemoSession.start()` 自动把 `_capture_state.output_dir` 指向场景 `frames/`, 这样 `/api/sessions` + `/api/captures` 直接服务真帧, 无需额外接线
- Smoke: 场景加载 OK, 11 preamble + 5 postamble + 30 poses, log 显示 'Demo capture session starting (DEMO_MODE: Batman: Arkham Knight)', sessions 列表 active='frames'

### [v0.3.0] — 小由 (Demo Mode scaffolding, step 1)
- 新增 `web/demo.py`: `is_demo_mode()` (env `DEMOAISHI=1`) + `DemoSession` 后台脚本化时间线 + canned 响应汇总 (bridge/hacks/obs/tools/trajectory)
- 路由短路: `capture.py` (start/stop/bridge-test/defaults), `bridge.py` (scan_status/rescan), `hacks.py` (inject/apply/lock/unlock/uninstall/capture/get_capture/write/read_pose), `obs.py` (test/setup/status), `tools.py` (analyze_rdc), `trajectory.py` (play/decode)
- `/api/defaults` 多返回 `demo_mode: bool`
- UI 顶栏右侧加 `演示模式 / Demo` 渐变 ribbon, JS 在 `DOMContentLoaded` 拉 defaults 后才显
- DEMOAISHI=0 路径全程未改, regression smoke test pass (defaults.demo_mode=False, 真实路径调用如常)
- step 2 待办: 烤资产包 (`demo/scenarios/<name>/frames/`), step 3 timeline -> manifest 化, step 4 Dockerfile + 部署 README

### [v0.3.0] — 小由 (品牌化: 顶部 RenderDoc 字样改 爱萌捕捉 + overlay 简化)
- toolbar grabber 下拉 `RenderDoc` -> `爱萌捕捉` (value="renderdoc" 不变, 后端无感)
- Connection 面板 `<label>renderdoccmd</label>` -> `爱萌捕捉` (placeholder 保留技术名)
- `renderdoc/renderdoc/core/core.cpp::GetOverlayText` 简化:
  - 第一行固定 `AIMen tech Support`
  - 最近 20s 内每张 capture 显示 `AImen trigger Captured frame N`
  - 删除 driver/Frame/FPS/F12/Captures saved summary 等 RDC 原生提示
  - 跨域改动 (renderdoc/), 需小萱 review + 重新编译 renderdoc.dll 才生效

### [v0.3.0] — 小由 (Output gallery: 一组 capture 一行)
- Filter=All 时按 capture key 分组, 每行 3 格 [RGB | Depth | Normal] 对应一组 capture
- thumbSize slider 默认 2 -> 3; preview-body grid 默认 `1fr 1fr 1fr`
- 缺失帧用 placeholder 卡占位保持栏对齐
- captureCount 在分组模式下显示组数 (= capture 次数), 单类型模式下仍是文件数
- Filter=RGB/Depth/Normal 走原 flat 列表 (不分组)

### [v0.3.0] — 小由 (注入菜单 重命名 + 自动打开 + profile 自动选择)
- 顶栏按钮 "Debug" -> "注入菜单"; 面板标题同步
- `startCapture` 成功后若面板未开则 `toggleDebugPanel()` 自动打开
- `hackRefresh` 改返回 Promise; 新增 `_ensureHackProfilesLoaded` 单飞缓存 + `_applySelectedGameProfile` helper
- `selectGame` 不再只在面板已开时填 profile, 现在预取列表后回写 `selectedGame.profile_id`
- Start 流程: 选游戏 -> 点 Start -> 注入菜单 自动弹 + profile 已选中, 无需手动 "Debug + 下拉"

### [v0.3.0] — 小由 (Task 6: A-Z index + group headers)
- Game Library 增 A-Z 字母索引条 (右侧 14px 竖条, 无该字母游戏时灰显不可点)
- 按首字母分组显示, sticky 组头 (#  bucket 收非字母名)
- 去掉 `allGames.slice(0, 50)` 硬上限, 164 个游戏全展示 (naive render, 虚拟滚动暂缓)
- `renderGameList` 拆出 `_buildGameRow` helper
- 字母点击 `scrollIntoView` 平滑跳转

### [v0.3.0] — 小由 (菜单栏 + Game Command 拆分, 补录)
- 顶部 28px menubar, Help > About captureAIshi / Copyright
- Copyright 模态显示 "爱萌 / Author: lijunbai"
- Game Command 单行拆分: EXE Path / Resolution Preset (5 档) / Width+Height / Windowed / -log
- `_build_args` 后端组合 target_args, `/api/defaults` 同步默认值
- 推送状态: 由 session summary 追溯 (原记录 78a0e55, 现以 mainbranch HEAD 为准)

### [v0.3.0] — 小由 (Task 5 + Task 7)
- Settings Modal, 左栏精简, 隐藏 Unity/CE, 三级联动菜单

旧版 CL 见 `agents/ui/ARCHIVE.md`。
