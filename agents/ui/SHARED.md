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
