# UI Agent (小由) — Shared Notes

## Active TODO

- [ ] **P0 (本周主线): UI 视觉重构 + PCG 模式骨架** (from 老白 2026-05-13)

  **完整规划**: `docs/ui_pcg_redesign_plan.md`（请先通读再动手；review 问题写回这条 TODO 下方）

  **总目标**：
  1. 先把现 capture UI 视觉提亮一档（Phase 0，~3 天）
  2. 再加 PCG 双模式骨架（Phase A，~1 周），后端 stub 即可
  3. Phase B/C（Unreal 启动 + 数据导出）等 ReShade AOB 跑通信号 + 老白 / unreal_pcg_robot 协同进入

  **本周内只做 Phase 0 + Phase A 的 UI 部分**（共 ~10 天工时，分两个 commit 推）。

  **Phase 0 验收清单（贴 before/after 截图过审才进 Phase A）**:
  - 提亮 `:root` CSS variables（文档 §8 Phase 0 表）
  - 全局颜色变量化（grep `#[0-9a-fA-F]{3,6}` 0 命中）
  - spacing 4px 网格统一
  - 三级 elevation tokens 应用到 panel/modal/lightbox/dropdown
  - selected state 用 accent 染色（不再中性白）
  - 现 capture 端到端跑一次确认 0 回归

  **Phase A 验收清单**:
  - Toolbar 加 `Capture | PCG` mode switch（默认 capture，记 `localStorage.uiMode`）
  - PCG 模式左栏 cascade lv1（5 槽位） + lv2（场景模板四选一） + lv3（warehouse 细节示例）
  - `web/routes/pcg.py` 8 个 stub routes 全 mock
  - `cascadePanel.js` 抽离公用 cascade 行为（capture 模式同步用，0 回归）
  - 中栏 / 右栏 / Debug Panel 不动，复用
  - capture 模式跑一次确认 0 回归

  **跨域注意**：
  - `drivers/unreal_pcg.py` / `unreal_projects/` / `adapters/` 不在你域，**别建别动**——unreal_pcg_robot 接手
  - `configs/pcg/*.json` schema 文档你跟 unreal_pcg_robot 配合，谁先到 SHARED.md 提合约谁主笔
  - 任何碰 `web/routes/capture.py / hacks.py / obs.py / trajectory.py` 的改动，先在 rendering/SHARED.md 知会小萱

  **工时预算**：Phase 0 ≤ 3 天，Phase A ≤ 5 天，加起来 ≤ 8 工日。超过的话停下来在 SHARED 报阻塞。

  **节奏 & checkpoint**：
  1. 读完文档后在本 TODO 下贴 review 问题（≥ 1 条，挑刺也行）
  2. Phase 0 第一个 commit：CSS variables 替换 + elevation tokens
  3. Phase 0 第二个 commit：颜色 / spacing audit + selected state 重做
  4. Phase 0 完成截图过审
  5. Phase A 第一个 commit：cascadePanel.js 抽离 + Toolbar mode switch
  6. Phase A 第二个 commit：PCG sidebar cascade lv1/2/3 + stub routes
  7. Phase A 完成截图过审

  **CL 签名**：xiaoyu。每个 commit 都要在本 SHARED.md 加 CL 条目（按 versioning.md 规则 ≤ 10 行）。

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

旧版 CL 见 `agents/ui/ARCHIVE.md`。
