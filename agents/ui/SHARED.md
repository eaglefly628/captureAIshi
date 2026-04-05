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

## [v0.3.0] UI 重构任务 (from lead)

目标：从"开发者工具"转型为"游戏选择 → 捕捉"的完整工作流。当前只支持 UE5 游戏，Unity 支持在代码中保留但 UI 上隐藏。

### Task 5: 右栏重构 — 设置面板分离 (P0)

当前右栏塞了太多设置项（volume、spacing、cone、driver、grabber 等），需要拆分：

1. **把所有捕捉参数设置移到一个独立的全页展开菜单**
   - 点击"设置"按钮/图标 → 展开一个覆盖整个右栏（或 modal）的设置页面
   - 分组展示：采集区域（volume）、路径参数（spacing/cone）、渲染参数（FOV/aspect/resolution）、高级（driver/grabber 选择）
   - 收起后右栏恢复正常布局
2. **隐藏 Unity 相关选项**
   - Driver 下拉里隐藏 `unity` 和 `cheatengine` 选项（代码保留，UI 不显示）
   - 默认 driver 锁定为 `ue5`，grabber 锁定为 `renderdoc`
   - 保留一个"显示全部引擎"的开关在设置高级区，方便将来启用

### Task 6: 游戏选择菜单 (P0)

新增"游戏库"面板，替换当前右栏的主要功能：

1. **游戏清单数据源**
   - UUU 是闭源的，不能直接拉取。改用以下数据源：
     - **PCGamingWiki** — 有 UE 引擎版本和 DRM/反作弊标记
     - **RE-UE4SS 兼容列表** — GitHub 开源，标注了哪些游戏可注入
     - **IGCS 支持列表** — GitHub 开源 (FransBouma/InjectableGenericCameraSystem)，26+ 游戏
     - **用户自建** — 手动添加游戏 + exe 路径
   - 后端 API: `GET /api/games` — 返回游戏列表（名称、引擎版本、兼容状态）
   - 本地缓存到 `configs/game_library.json`，支持手动刷新

2. **游戏列表 UI**
   - 左侧（或右栏内）显示游戏列表
   - **按字母排序**，带字母索引条（A-Z 快速跳转）
   - **分页/虚拟滚动** — UUU 支持几百款游戏，不能一次性全渲染
   - **搜索框** — 实时过滤，按游戏名模糊匹配
   - 每个游戏项显示：名称、引擎版本（UE4/UE5）、兼容状态图标
   - 选中游戏高亮，右侧显示该游戏详情

3. **每游戏独立配置**
   - 选中游戏后，加载该游戏专属的捕捉配置（volume、spacing、resolution 等）
   - 配置存盘路径：`configs/games/<game_slug>.json`
   - 新游戏首次选中时，从默认模板创建配置
   - 切换游戏自动保存当前游戏配置 + 加载新游戏配置
   - API: `GET/POST /api/games/<game_slug>/config`

### Task 7: 内部代码隐藏 Unity 支持 (P1)

- `web_ui.py` 的 `/api/defaults` 返回的 driver/grabber 列表过滤掉 Unity 相关选项
- 前端 driver 下拉只显示: `ue5`, `memory`, `manual`
- 前端 grabber 下拉只显示: `renderdoc`, `screenshot`, `none`
- **不要删除 Unity 相关的后端代码或 driver 文件**，只在 UI 层过滤

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
- [ ] **P1: a5f8859 export_batch stderr 管道风险** (spotted by 小萱) — `renderdoc_grabber.py` 的 `export_batch` 用 `Popen(stderr=subprocess.PIPE)` 但在 stdout readline 循环后才读 stderr。如果 C++ 进程 stderr 输出填满 4KB 管道缓冲区，进程阻塞 → stdout 无 EOF → readline 死锁 → timeout 检查永远不执行。修复：`stderr=subprocess.DEVNULL` 或 `stderr=subprocess.STDOUT`。参考：8c6160e 同样的 bug 在 interactive trigger 里已修过。

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

### [v0.3.0] — 小由
- **Camera Path Editor**: 新增 `core/path_player.py` 路径数据模型 + Catmull-Rom/SLERP 插值引擎
- **Path CRUD API**: `/api/paths` 列表、`/api/path` 增删改查、`/api/path/<id>/node` 节点管理、`/api/path/<id>/interpolate` 插值预览
- **3D 路径编辑器**: 3D Viewer 内交互式节点添加/选择/拖拽/编辑/删除，Catmull-Rom 曲线实时预览
- **Path Controls UI**: 路径选择器 + 节点列表 + 属性编辑器 (位置/旋转/FOV/Duration)
- **Game Library UI**: 游戏库搜索/过滤 (UE4/UE5)，per-game profile 保存/加载 (`configs/games/<slug>.json`)
- **Per-Game Profile API**: `/api/games` 游戏列表 + 搜索，`/api/games/<slug>/config` GET/POST 独立配置
- 存储: `configs/camera_paths.json` (路径数据)，`configs/games/<slug>.json` (游戏配置)

### [v0.3.0] — 小由 (Task 5 + Task 7)
- **Settings Modal**: 所有捕捉参数 (Volume/Path/Cone/Rendering/Connection/Streaming/Output) 从左栏移到右滑设置面板
- **左栏精简**: 只保留 Game Library、Presets、Saved Configs、Recent
- **Toolbar Settings 按钮**: 点击打开/关闭设置面板，Escape 关闭
- **隐藏 Unity/CE 选项**: Driver 下拉只显示 Manual + UE5，Unity/CE 代码保留
- **Show All Engines 开关**: Settings > Advanced 里的 toggle，启用后恢复 Unity + CE 选项
- 设置面板分组: Capture Area / Path / Cone Rotation / Rendering / Connection / Streaming / Output / Advanced
