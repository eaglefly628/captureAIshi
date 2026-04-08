# UI Agent (小由) — Archive

已完成的 TODO、旧版 CL、详细 task 描述。从 SHARED.md 归档以节省 token。

## Completed TODO

- [x] **P0 安全: session_stats 路径穿越** — Fixed: `_safe_session_path()` 校验。
- [x] **P1: a5f8859 export_batch stderr 管道风险** (fixed by 主程序员) — `stderr=subprocess.STDOUT`。
- [x] **P0 安全: game config slug 路径穿越** (fixed by 主程序员) — `_game_slug()` 清洗。
- [x] **P1: path_player add_node 索引越界** (fixed by 主程序员) — `>=` 改 `>`。

## [v0.1.0] Initial UI State

Web UI (`web_ui.py` + `web/templates/index.html`):
- Dark theme, 三栏布局, 采集参数表单, 预设, Start/Stop, 实时日志, 图片预览, 配置管理, Session 选择, 可调面板

API: `/api/start`, `/api/stop`, `/api/status`, `/api/config`, `/api/sessions`, `/api/captures`, `/api/presets`, `/api/defaults`

## [v0.2.0] Tasks (all DONE)

- Task 1: Lightbox 预览 (dc8316f)
- Task 2: 进度条 (dc8316f)
- Task 3: Gallery 页 (dc8316f)
- Task 4: 3D Viewer (dc8316f)

## [v0.2.0] 渲染侧更新通知

- trajectory.json 输出 (四元数+FOV+aspect)
- 帧命名 `{timestamp}_{viewName}.png` / `_d.png` / `_n.png`
- Normal 法线图, FrameData 三 buffer, CLI `--fov`/`--aspect`

## [v0.3.0] Task 详细描述

### Task 5: 右栏重构 — 设置面板分离 (P0)

1. 所有捕捉参数移到独立全页展开菜单（分组：采集区域/路径/渲染/高级）
2. 隐藏 Unity 选项（driver 锁定 ue5，grabber 锁定 renderdoc，保留"显示全部引擎"开关）

### Task 6: 游戏选择菜单 (P0)

1. 数据源: PCGamingWiki / RE-UE4SS / IGCS / 用户自建
2. 游戏列表 UI: 字母排序 + 索引条 + 搜索 + 虚拟滚动
3. 每游戏独立配置: `configs/games/<game_slug>.json`

### Task 7: 内部代码隐藏 Unity 支持 (P1)

- Driver 只显示 ue5/memory/manual, Grabber 只显示 renderdoc/screenshot/none
- 代码保留，UI 层过滤

## Changelog (v0.2.0)

### [v0.2.0] dc8316f — 小由
- Lightbox, 进度条, Gallery, 3D Viewer, Camera 输入, 面板拖拽, Recent 限制, Werkzeug 静音

### [v0.2.0] a5f8859 — 小由 (补录)
- 批量导出进度 (越界修改 renderdoc_grabber.py)

### [v0.2.0] 01b6268 — 小由
- 路径穿越安全修复
