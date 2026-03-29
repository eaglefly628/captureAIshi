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

Priority order. Work on the branch `claude/max-traffic-sharing-8hWo3`.

### Task 1: Image preview lightbox (P0)
Clicking a thumbnail should open a full-size overlay with:
- Full resolution image display
- Left/right arrow navigation between captures
- RGB and depth side-by-side view (match rgb_XXXXXX with depth_XXXXXX)
- Close on Escape or click outside
- Keep it vanilla JS, no frameworks

### Task 2: Capture progress bar (P0)
During capture, show:
- Progress bar: `pose 3/20` with percentage
- Elapsed time and estimated remaining
- Current pose info (position, rotation)
- Parse these from the log lines or add a `/api/progress` endpoint

### Task 3: Session gallery page (P1)
Replace the simple thumbnail list with a proper gallery:
- Grid layout with adjustable thumbnail size
- Filter by type (RGB only, Depth only, All)
- Sort by name or capture time
- Total count and disk size summary
- "Open in Explorer" button (shell link to output directory)

### Task 4: 3D waypoint visualizer (P2)
Simple 3D canvas showing:
- Waypoint positions as dots connected by path lines
- Camera frustum cones at each waypoint
- Capture volume bounding box
- Use vanilla WebGL or lightweight Three.js
- Interactive: rotate/zoom the view
- This is aspirational — only if Tasks 1-3 are done

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
