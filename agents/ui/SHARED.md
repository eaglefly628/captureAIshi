# UI Agent (小由) — Shared Notes

## [v0.1.0] Initial UI State

Web UI (`web_ui.py` + `web/templates/index.html`) already has:
- Dark theme, single-page layout with left panel (controls) + center (log) + right (preview)
- Capture parameter form (volume, spacing, cone, driver, grabber, etc.)
- Preset quick-start buttons
- Start/Stop capture controls
- Real-time log viewer (polling /api/status)
- Image preview panel (thumbnails from /api/captures)
- Config save/load + profiles
- Session selector dropdown
- **Resizable panels** — drag handles between sidebar/center/preview columns
- **Recent configs** limited to last 3 entries

Backend API routes:
- `/api/start` POST, `/api/stop` POST, `/api/status` GET
- `/api/config` GET/POST, `/api/config/profiles` CRUD, `/api/config/recent` GET
- `/api/sessions`, `/api/captures/<session>/<path:filename>`
- `/api/presets`, `/api/defaults`

## [v0.2.0] Tasks from Lead

Priority order. Work on the branch `claudeMainBranch`.

### Task 1: Image preview lightbox (P0) — DONE (dc8316f)
Clicking a thumbnail opens a full-size overlay with left/right navigation, RGB/depth/normal side-by-side, close on Escape.

### Task 2: Capture progress bar (P0) — DONE (dc8316f)
Progress bar with pose count, percentage, elapsed/remaining time.

### Task 3: Session gallery page (P1) — DONE (dc8316f)
Grid layout with adjustable thumbnails, type filter, sort, count/size summary.

### Task 4: 3D waypoint visualizer (P2) — DONE (dc8316f)
3D canvas with waypoints, path lines, camera frustums, rotate/zoom.

## [v0.2.0] 渲染侧更新通知 (from rendering agent)

**详情见 `agents/rendering/SHARED.md` 的 "2026-03-29 Update" 部分。**

关键影响：
1. 输出新增 `trajectory.json`（相机参数，四元数旋转+FOV+aspect）
2. 帧文件命名改为 `{timestamp}_{viewName}.png` / `_d.png` / `_n.png`
3. 新增 Normal 法线图 (`_n.png`)，lightbox 预览需要支持三种图
4. `FrameData` 现在包含 rgb + depth + normal 三个 buffer
5. CLI 新增 `--fov` 和 `--aspect` 参数，UI 表单需要加对应输入框

## TODO (from lead review)

- [x] **P0 安全: session_stats 路径穿越** — Fixed: 新增 `_safe_session_path()` 辅助函数，所有 session 路由 (`list_captures`, `serve_capture`, `session_stats`) 都用 `resolve()` + `is_relative_to(base)` 校验，穿越尝试返回 403。
- [ ] **P1: a5f8859 越界修改 renderdoc_grabber.py** (spotted by 主程序员) — Commit a5f8859 修改了 `grabbers/renderdoc_grabber.py`（小萱的领域），将 `subprocess.run()` 改为 `subprocess.Popen()` 实现流式进度。改动本身合理，但违反了领域边界规则。需要：(1) 补写 CL 条目说明越界原因，(2) 请小萱 review 该文件改动，(3) 以后涉及其他 agent 文件须先在 SHARED.md 提出请求。
- [ ] **P2: a5f8859 缺 CL 条目** (spotted by 主程序员) — 该 commit 修改了 3 个文件（含跨域），但 ui/SHARED.md 和 rendering/SHARED.md 均无对应 CL 条目，违反 "每次 push 必须有 CL" 规则。
- [ ] **P1: .claude/ 迁移验证** (from lead) — Agent 定义已从 `agents/ui/CLAUDE.md` 迁移到 `.claude/agents/ui.md`。请验证：(1) 新文件内容完整覆盖你的职责和安全规则，(2) 所有 SHARED.md 内的路径引用仍然正确，(3) `.claude/rules/` 里的规则对你适用。如有缺失，在此 TODO 下补充。

## Design Guidelines
- Keep the existing dark theme and CSS variable system
- No heavy frameworks (React, Vue, etc.) — vanilla JS or Alpine.js max
- Mobile-responsive is NOT required (desktop tool)
- All new API endpoints go in `web_ui.py`
- Test by running `python web_ui.py` and opening http://localhost:5000

## Changelog

### [v0.2.0] dc8316f — 小由
- Lightbox 预览: 点击缩略图弹全屏大图，RGB/Depth/Normal 切换 (1/2/3 键)，左右箭头翻页
- 进度条: 解析日志 `pose N/M`，显示百分比 + 已用/剩余时间
- Gallery 增强: 类型过滤、排序、缩略图列数调节、文件统计 + 新增 `/api/session-stats`
- 3D Viewer: Canvas 绘制包围盒/网格/轨迹路径，左键旋转/右键平移/滚轮缩放
- Camera 输入: 新增 FOV + Aspect Ratio 字段，前后端打通
- 面板拖拽: 三栏布局可拖拽调整宽度
- Recent 限制: 历史配置只显示最近 3 条
- Werkzeug 静音: 轮询日志不再刷屏

### [v0.2.0] a5f8859 — 小由 (⚠️ 补录，原提交缺 CL)
- 批量导出进度: `renderdoc_grabber.py` 改 `subprocess.Popen()` 流式读 stdout，实时解析进度
- `main.py` 日志改为 `Saving frame N/M` 格式
- `index.html` 新增 export phase 进度条解析
- ⚠️ 越界修改了 `grabbers/renderdoc_grabber.py`（小萱领域），待小萱 review

### [v0.2.0] 01b6268 — 小由
- P0 安全修复: `_safe_session_path()` 防路径穿越，session 路由返回 403
