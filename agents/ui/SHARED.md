# UI Agent (小由) — Shared Notes

## Current State (v0.1.0)

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

## Tasks from Lead (2026-03-29)

Priority order. Work on the branch `claude/max-traffic-sharing-8hWo3-1Zpm7`.

### Task 1: Image preview lightbox (P0) — DONE (dc8316f)
Clicking a thumbnail opens a full-size overlay with left/right navigation, RGB/depth/normal side-by-side, close on Escape.

### Task 2: Capture progress bar (P0) — DONE (dc8316f)
Progress bar with pose count, percentage, elapsed/remaining time.

### Task 3: Session gallery page (P1) — DONE (dc8316f)
Grid layout with adjustable thumbnails, type filter, sort, count/size summary.

### Task 4: 3D waypoint visualizer (P2) — DONE (dc8316f)
3D canvas with waypoints, path lines, camera frustums, rotate/zoom.

## 2026-03-29 渲染侧更新通知 (from rendering agent)

**详情见 `agents/rendering/SHARED.md` 的 "2026-03-29 Update" 部分。**

关键影响：
1. 输出新增 `trajectory.json`（相机参数，四元数旋转+FOV+aspect）
2. 帧文件命名改为 `{timestamp}_{viewName}.png` / `_d.png` / `_n.png`
3. 新增 Normal 法线图 (`_n.png`)，lightbox 预览需要支持三种图
4. `FrameData` 现在包含 rgb + depth + normal 三个 buffer
5. CLI 新增 `--fov` 和 `--aspect` 参数，UI 表单需要加对应输入框

## Design Guidelines
- Keep the existing dark theme and CSS variable system
- No heavy frameworks (React, Vue, etc.) — vanilla JS or Alpine.js max
- Mobile-responsive is NOT required (desktop tool)
- All new API endpoints go in `web_ui.py`
- Test by running `python web_ui.py` and opening http://localhost:5000
