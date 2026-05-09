# Reverse Engineering Agent (小逆) — Shared Notes

Current context lives here. Completed items and old CL entries move to
`agents/reversing/ARCHIVE.md`. Auto-archive rule: CL entries older than
**14 days** are moved to ARCHIVE.md on next session (see
`.claude/rules/versioning.md`).

## Active TODO

### Open items

- [ ] **P0: unicap dxgi.dll proxy 整合** — 同事找到更稳定注入方法。
  `3rdparty/unicap`（已 clone，commit `424113d`）使用 dxgi.dll proxy 注入 ReShade
  采帧，**无 CreateRemoteThread / LoadLibraryW**，不触发 anti-cheat。
  目标：作为 captureAIshi 的新 grabber 后端（`grabbers/unicap_grabber.py`），
  在现有 renderdoc 注入失败时自动 fallback。
  参考：`3rdparty/unicap/reshade-addons/99-frame_capture/` + `tools/capture/survey.py`

- [x] **P1: trajectory decode callbacks 不保存 PNG** (spotted by 小萱, fixed 9498850) —
  `export_batch` 返回 numpy arrays，调用方需调 `save_frame` 写盘。
  `trajectory_play._decode` 和 `/api/trajectory/decode._run_decode` 都直接丢弃了
  返回值，导致 rdc-step 采集后 output_dir/frames/ 为空。已在 trajectory.py 两处
  补 save_frame 循环，用 rdc_path.stem 为文件名 base。

- [ ] **P0: UpdateCamera 覆写 -- 正确解法: 渲染线程边界 hook**
  UpdateCamera() 每帧写回玩家摄像机位置，无法从外部争抢。正确解: hook
  `ULocalPlayer::GetViewPoint` (virtual, vtable-hookable). GetViewPoint 在渲染
  线程 FSceneView 构建前被调用，是数据流进渲染器的最后门。钩子直接返回
  g_cam_override_state，完全跳过 UpdateCamera 写的 POV。vtable index 因 UE 版本
  而异，需从 UE4SS PDB 数据或运行时扫描确定。

- [ ] **P0: 真实 UE5 游戏端到端验证** — StackOBot test in progress. Bridge finds
  GEngine/UWorld/LP/CameraManager. Next: rebuild DLL, run __cam_mem_find,
  confirm scan fallback finds POV.

- [ ] **P0: Path D 逆向补全** — pass 2 now scans PC+[0x100..0x800] for exact
  manager ptr. On next run, log "PC+0xXXX == Path-A manager [XVAL OK]" ->
  update k_layout_ue57.pc_pcm_start/end to that discovered offset.

- [ ] **P0 (UUU 功能复刻, from 小由 2026-04-05, 老白 confirmed)**:
  per-node FOV 支持; 播放时长控制 `__path_play <total_seconds>`;
  Loop `__path_loop 1/0`; 暂停/恢复 `__path_pause` / `__path_resume`;
  当前位置查询 `__camera_get`.

- [ ] **P1: AC 预检脚本** — 检测 EasyAntiCheat.dll / BEService.exe。

- [ ] **P2: CL 条目缺失** (spotted by 主程序员 4.7 review) — `c088120` 在
  SHARED.md 里仍是 `(pending push)`，已 push 应填实际 sha。`43ac097`
  完全无 CL 条目。按 versioning.md 规则补上。

- [ ] **P2: __try 块内 C++ 对象析构跳过** (spotted by Gemini) — `cam_patch_write`
  已清理（所有 C++ 析构全在 suspend 窗口外），只 `cam_seh_memcpy` 在 __try 里。
  **待办**: 递归审计其他 __try 站点，确保全 pure-C 叶子。

- [ ] **P2: Catmull-Rom 非均匀段距突变** (spotted by Gemini) — 当前 Uniform
  Catmull-Rom 在不均匀 duration 下产生过冲。**修复**: 升级 Centripetal，将
  chord length 或 duration 差代入切线权重。

- [ ] **P2: _detect_bridge 无重试** (spotted by 主程序员) — 加 2-3 次指数退避重试。

- [ ] **P2: 增强 Pause** — 加 UWorld::IsPaused 内存写入 fallback。

### Commit D (next major) -- UE 自动探测 (StackOBot 并轨)

- 基于 `g_cam_pov_ptr - g_camera_manager_ptr = disp32`
- 扫 `.text` 里 `movups/movsd [reg + disp32], xmm?` 指令
- 识别连续 3-4 条 (x/y/z/w for LWC 或 x/y/z/float) 自动装 multi-site
- StackOBot 端到端就自动化了，无需 CE 手工

## Architecture Reference

### Camera Control Methods
- **Bridge DLL** -- 注入 + console exec (UE4/UE5, 无反作弊)
- **External Memory** -- ReadProcessMemory (绕 user-mode AC)
- **Cheat Engine** -- 手动找 offset

### UUU / UE4SS Camera Research (结论)

- UUU 和我们一样: 背景线程 60Hz 写 POV (industry standard)
- `UpdateCamera` NOT virtual, vtable hook 不可用
- `ULocalPlayer::GetViewPoint(FMinimalViewInfo&)` IS virtual (UE4SS line 1226-1227)
  是可用 hook 点 (无竞态)，但 vtable index 计算需数完整 AActor+UPlayer+ULocalPlayer
  链 (~100+ entries)
- 当前 60Hz 写路径是正确且业界标准。Race 修复 = capture 前 timestop (g_paused)；
  UpdateCamera 停转，我们写必赢。Offline capture 无需 vtable hook。

### Bridge DLL

- `3rdparty/bridge/`: TCP 9998, GEngine string-xref scan, Exec() vtable,
  Camera path (Catmull-Rom + SLERP), timestop, HUD toggle, hotsampling
- Driver `ue5_console.py` auto-fallback bridge:9998 → UUU:1985
  (`_detect_bridge()` via `__bridge_ping`)
- GEngine scanner: 8 anchors (5 wide + 3 ASCII, UEVR-verified), 引擎通用 pattern,
  无需 per-game 数据库

### Game Profiles (configs/hacks/)

```
_schema.md           -- JSON 字段文档
batman_ak.json       -- UE3, 60B, rbx, float coord + ue3_packed_int rot
hellblade_ue4.json   -- UE4, 43B, rdi, float coord + float rot
stackobot_ue5.json   -- UE5 LWC, 3+4B split, rsi, double coord + double rot
cyberpunk2077.json   -- REDengine 4, 26B, rbx, float + quaternion
unreal_physics.json  -- UE5 stub (intercepts=[] until Commit D)
black_myth_wukong.json -- UE5 stub
```

Dropdown in Web UI debug panel. Python: `drivers/game_profile.py`
load/apply/lock/unlock/uninstall. Flask: `/api/hacks/*`.

## Changelog (latest 3)

Older entries live in `agents/reversing/ARCHIVE.md`.

### [v0.3.0] (pending) -- xiaoni -- Path B scaffold: reshade_bridge addon

- `3rdparty/reshade_bridge/src/{pattern_scan,ue5_engine,camera_path}.h` -- byte-identical copies from `3rdparty/bridge/src/` (independent vehicle).
- `3rdparty/reshade_bridge/src/bridge.cpp` -- copy + 3 minimal edits: banner; `#include <reshade.hpp>`; `DllMain` adds `reshade::{,un}register_addon` and NAME/DESCRIPTION exports.
- `3rdparty/reshade_bridge/src/CMakeLists.txt` -- builds `captureAIshi_bridge.addon`; SDK headers from `3rdparty/unicap` submodule.
- `3rdparty/reshade_bridge/README.md` -- A/B comparison table, design rationale, Phase 0/1/2 plan, Phase 1 frame-capture pointers (unicap `DepthToAddon.fx` + `frame_capture.cpp`).
- Phase 0 = scaffold only. No render-pipeline events hooked yet (Phase 1).
- Path A `3rdparty/bridge/` untouched -- zero regression risk.

### [v0.2.0] 28b09e1 -- xiaoni -- EXR probe diagnostics (run.bat install reverted in e4e8f1a)

`28b09e1` originally added `pip install -r requirements.txt` to
`run.bat` / `run_cli.bat` plus richer pip-output capture in
`_ensure_exr_loader`. The run.bat additions were reverted in
`e4e8f1a` after user pushback ("别这样做，我是做过pip install 了" --
the install path was a red herring; cv2 was already installed but
EXR support was disabled by an opencv build flag). The `_ensure_exr_
loader` diagnostics (drop `--quiet`, capture stdout/stderr, log
tail on success / exit + last 500 chars on failure,
`importlib.invalidate_caches()` between install and re-import,
probe-success log promoted DEBUG -> INFO) were kept and rebased
forward.

### [v0.2.0] f03387a -- xiaoni -- Tier 1 intercepts populated -- Apply/Capture/Play/Decode parity with Batman

Follow-up to `f6728fb`. The 6 Tier 1 stub configs are now real
profiles: intercepts[] filled from raptoravis's UUU 5.8.11/4.11.5
catalog, camera_write_profile.enabled = true, struct_base_reg + field
offsets set so the user-flow (Apply -> Capture -> Test -> Play -> auto
decode) mirrors the existing Batman path.

Pattern selection per game:

- **Hellblade II** -- shared UE5 `AOB_CAMERA_STRUCT_INTERCEPT1` SSE
  (variant 0, wildcards on the lea displacement) + AVX (variant 1,
  literal). Two intercepts so either UE5 5.3-5.4 SSE or 5.5+ AVX
  builds match.
- **Avowed** -- per-game `AOB_CAMERA_STRUCT_INTERCEPT1` (uses
  `rep movsq` to copy 9 qwords of FMinimalViewInfo + a single DWORD
  write at `[rbx+0x1538]`); shared SSE pattern as fallback.
- **Oblivion Remastered** -- shared UE5 SSE pattern (per-game keys
  in catalog are atmospheric-write hooks, not the camera struct).
- **The Quarry / The Invincible / South of Midnight** -- shared UE4
  `AOB_CAMERA_STRUCT_INTERCEPT1` SSE v0 (per-game keys are
  pause/blackbar/FOV-read quirks, not the camera write site).

`camera_write_profile` field offsets per engine layout:

- UE5 LWC (HB2 / Avowed / Oblivion R): Location FVector3d (3x double)
  at 0x00, Rotation FRotator (3x float) at 0x18, FOV float at 0x24.
  `struct_base_reg = "rdx"` (the read-source pointer in the field-
  by-field MOV block).
- UE4 (Quarry / Invincible / SoM): Location 3x float at 0x00,
  Rotation 3x float at 0x0C, FOV float at 0x18. `struct_base_reg =
  "rdx"`.

Standard layout assumed; some Obsidian / 5.5+ builds may shift FOV
by 4 bytes (padding). User Test button after Capture catches that --
edit `fov.off` if values look wrong.

`configs/game_library.json` -> 0.6.1; the 6 Tier 1 entries flipped
from `test_status: "stub"` to `"ready"` (Apply path is wired; "ok"
is reserved for after live verification).

After this commit those 6 games behave exactly like
`batman_ak.json`: dropdown -> Apply -> bridge installs camera
intercept -> Capture button reads `rdx` at hook entry -> Test pokes
verify offsets -> Play streams the trajectory + auto-decodes.

### [v0.2.0] f6728fb -- xiaoni -- Tier 1 game configs from raptoravis UUU catalog + profile delete

Two related additions in one batch:

1. **Tier 1 game profiles imported from `uuuaobcapture/`**:
   - `docs/uuuaobcapture_game_survey.md` -- full 26-game catalog
     (UE4 13 + UE5 13) plus a 4-tier injection-ease ranking. Tier 1
     (no AC + SP + Steam-current) covers Hellblade II, Avowed,
     Oblivion Remastered, The Quarry, The Invincible, South of
     Midnight.
   - `configs/hacks/{hellblade_2, avowed, oblivion_remastered,
     the_quarry, the_invincible, south_of_midnight}.json` -- all
     stub profiles in the same shape as `unreal_physics.json` /
     `black_myth_wukong.json`: process_names + engine + capture
     section (rgb_strategy, normal_strategy, depth_curve,
     depth_reversed_z) + camera_write_profile.enabled=false until
     Commit D auto-discovery resolves the MOV write site. depth_curve
     defaults to "log" for outdoor wide-range games (HB2 / Avowed /
     Oblivion / Invincible), "linear" for narrative SP (The Quarry),
     and "gamma" for the mixed indoor / dense outdoor case (South of
     Midnight).
   - `configs/game_library.json`: bumped to 0.6.0 + 6 new entries
     ahead of the existing list, each tagged `tier: 1` and
     `test_status: "stub"`. Cross-references docs survey.

2. **Right-click delete on the Bridge Debug profile dropdown**:
   - `web/routes/hacks.py`: new `DELETE /api/hacks/profile/<id>`.
     Validates slug (alnum + underscore + hyphen), resolves to
     `_HACKS_DIR / <id>.json`, refuses paths that escape the dir,
     404s on missing.
   - `web/templates/index.html`: `oncontextmenu` on
     `#hackProfileSelect` -> `hackProfileContextMenu()` shows a
     floating menu with the profile name as a header and a single
     "Delete profile..." item; click triggers a confirm() then DELETE
     fetch + `hackRefresh()` to repopulate the dropdown. Outside-click
     listeners auto-close the menu. Defensive: ignored when no profile
     is currently selected.

### [v0.2.0] be9c6c6 -- xiaoni -- Per-game `depth_curve` for outdoor wide-range PNG preview

User report: Gotham depth PNG washed out at distance -- city mid-band
indistinguishable from sky highlights, only Batman silhouette visible.

NDC depth from a perspective projection is already 1/z-like, so the
sky / city / mid-distance pixels pile into a tiny raw range while
the near-camera silhouette occupies the other end. A linear stretch
can't separate the city from the sky because the stretch operates on
already-collapsed values; the cluster has to be re-distributed
*before* percentile-and-stretch.

- `grabbers/renderdoc/image_loader._normalize_depth`: new optional
  ``curve`` param. ``"linear"`` keeps legacy behaviour. ``"log"``
  applies ``np.log(np.clip(raw, eps, 1.0))`` to the raw depth before
  computing percentiles + stretch -- preserves the monotonic ordering
  (so reversed_z polarity stays right) but exponentially clustered
  values get spread out. ``"gamma"`` is a milder ``raw ** 0.45``
  middle ground. Synthetic test (Gotham-like distribution: 50k sky +
  30k city + 1k Batman): linear gives city=239, log gives city=122,
  i.e. a real mid-gray instead of near-white.
- `image_loader.load_depth_image`: thread ``capture_profile.depth_curve``
  into ``_normalize_depth`` (default ``"linear"`` so other games are
  untouched).
- `configs/hacks/batman_ak.json`: capture section sets
  ``depth_curve: "log"`` with explanatory comment.
- `configs/hacks/_schema.md`: documented the field.

PNG depth is preview-only; raw float `.exr` is written alongside and
unaffected, so AI training reads the unmolested depth no matter
which curve is set.

This is image-pipeline territory (nominally xiaoxuan's grabbers
domain), but the change is small and self-contained -- I left a
peer-review note in `agents/rendering/SHARED.md` so xiaoxuan can
audit + bump the other configs (open-world UE5 games like AC6 and
Metro will benefit from `"log"` too).

### [v0.2.0] e4e8f1a -- xiaoni -- cv2 EXR opt-in env var (real fix)

User confirmed they ran `pip install -r requirements.txt` and
opencv-python 4.8 is installed in their system Python 3.10
site-packages, but the EXR error persisted. Real root cause: since
OpenCV 4.5 the official `opencv-python` wheel **disables EXR support
by default** (security policy after CVE-2020-15778-style EXR parser
vulnerabilities). `cv2.imread(path, cv2.IMREAD_UNCHANGED)` returns
``None`` on a `.exr` unless the process started with
`OPENCV_IO_ENABLE_OPENEXR=1` in the environment **before the first
`import cv2`**. Our error message ended with "(No module named
'OpenEXR')" because that was the LAST fallback in
`image_loader._read_exr_red` -- cv2 had silently failed first.

- `web_ui.py`, `desktop_app.py`, `main.py`: set
  `os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")` at the
  very top of the file before any other import that could pull cv2.
  All three entry points covered.
- `grabbers/renderdoc/image_loader._read_exr_red`: defensive
  setdefault inside the function for direct/library callers, plus
  a more explicit RuntimeError message when cv2.imread returns None
  so the env-var trap is visible in logs.
- `run.bat` / `run_cli.bat`: reverted the auto-`pip install`
  experiment per user pushback (no point installing into embedded
  Python when the user already installed into their system Python;
  the cv2 problem was the env var, not a missing package).

### [v0.2.0] ca62f70 -- xiaoni -- Auto-install opencv-python at startup if EXR loader missing

Follow-up to `1d53bf2`. Pinning `opencv-python` in `requirements.txt`
helps fresh bootstraps but users who already bootstrapped won't re-run
`pip install -r requirements.txt` automatically -- they keep hitting
"Cannot read EXR" mid-capture and lose depth.

- `web_ui.py`: new `_ensure_exr_loader()` startup probe. Tries
  `import cv2`, then `import imageio.v3`, then `import OpenEXR`. If
  all three are missing, logs a warning and shells out to
  `python -m pip install --quiet opencv-python>=4.5.0` with a 180s
  timeout. Re-imports cv2 to verify; logs success or a clear error
  telling the user the manual command (`<python> -m pip install -r
  requirements.txt`) on any failure.
- `web_ui.py main()`: calls `_ensure_exr_loader()` right after
  logging setup, before the Flask app starts.
- `desktop_app.py main()`: imports and calls the same helper before
  spinning up the Flask thread, so the pywebview path is also covered.

Survives pip-not-available, network timeout, and restricted-install
environments by logging an error rather than crashing -- non-depth
features keep working in degraded mode.

### [v0.2.0] 1d53bf2 -- xiaoni -- Pin opencv-python for EXR depth loading

`99308e9` (xiaoxuan) switched the C++ exportframe depth output from
normalized PNG to raw float EXR; the Python loader needs cv2 /
imageio[freeimage] / OpenEXR but `requirements.txt` shipped none of
them, so user-facing setups dropped depth on every capture (rgb +
normal landed fine, just `[RDOC] Cannot read EXR ... depth.exr`).

- `requirements.txt`: pinned `opencv-python>=4.5.0` (lightest Windows
  install of the three; `image_loader.py` falls through to imageio /
  OpenEXR if cv2 is unavailable).

Posted a P1 peer-review note in `agents/rendering/SHARED.md` so
xiaoxuan also bumps deps next time the export file format changes.

### [v0.2.0] 6c3b691 -- xiaoni -- Clean stale .rdc on grabber.setup()

Per user ask: "每次启动后清除掉以前的rdc，不然会越来越大".

- `grabbers/renderdoc_grabber.py` `setup()`: right after
  `capture_dir.mkdir()`, glob `*.rdc` / `*.rdc.cap` / `*.rdc.mp` and
  unlink each. Logs count + total MB removed. Only touches the three
  RDC capture-file extensions; other files in the dir are left alone.

### [v0.2.0] f7645a1 -- xiaoni -- Fix RDC captures landing in game install dir (relative path bug)

User found the missing .rdc files via Everything search:
`D:\SteamLibrary\steamapps\common\Batman Arkham Knight\Binaries\Win64\output\ue5_rdoc\captures\`

Root cause: `renderdoccmd capture --capture-file <capture_dir>/frame`
and `_bridge.set_capture_path(<capture_dir>/frame)` were both passing a
**relative** path (the grabber's default `capture_dir="./captures"`
or similar). RenderDoc resolves that template **inside the game
process**, whose CWD is the game's install directory (e.g. Steam's
Batman `Win64`), so every .rdc landed there instead of under our
project's `output\ue5_rdoc\captures\`.

This is also the "以前是好的" (used-to-work) regression: a past
session had us cd'ing to the project root before starting the game,
or the capture_dir was already absolute; neither holds after recent
grabber refactors (73902db) / web_ui split.

- `grabbers/renderdoc_grabber.py` `__init__`: resolve `capture_dir`
  to absolute on construction so every downstream consumer
  (renderdoccmd CLI arg, trajectory_player glob watcher, Decode
  fallback search) sees the same path regardless of process CWD.
- `grabbers/renderdoc_grabber.py` `setup()`: `_bridge.set_capture_path`
  now passes `capture_dir.resolve() / "frame"` explicitly as belt-
  and-suspenders.
- `grabbers/renderdoc/launch.py` `start_renderdoccmd_capture`:
  `--capture-file` arg built from `Path(capture_dir).resolve()` and
  logged so future regressions show the abs path in the log.

### [v0.2.0] bbcb700 -- xiaoni -- RDC capture path diagnostics + wider decode search

User report: `captures=7 rdc_files=0` — bridge fired
`__cam_rdc_capture` 7 times during rdc-step, no .rdc landed anywhere
we checked (`output\ue5_rdoc\captures`, `%TEMP%\RenderDoc`, `%TEMP%`).
Either RenderDoc's capture-file template points somewhere else
entirely, or the Present hook never wired up in this session.

Two fixes + one diagnostic:

1. Bridge command `__cam_rdc_info` (requires DLL rebuild): returns
   `"template=<path> captures=<N>\n"` so Python can see exactly where
   `RenderDoc::Inst().GetCaptureFileTemplate()` resolved to and how
   many captures completed. Paired with `__cam_rdc_set_template <path>`
   to override the template at runtime.
   (`renderdoc/renderdoc/core/bridge/console_server.h` line ~960.)

2. `drivers/trajectory_player.py`: at rdc-step start, queries
   `__cam_rdc_info` and logs the result. On older DLLs without the
   command this is a silent no-op.

3. `web/routes/trajectory.py` `/api/trajectory/decode`: falls back to
   the bridge-reported template directory first, then glob the common
   RDC save locations: `%USERPROFILE%\Documents\RenderDoc`,
   `%APPDATA%\RenderDoc`, `%LOCALAPPDATA%\RenderDoc`, CWD, plus the
   `%TEMP%\RenderDoc` / `%TEMP%` set we already had. 404 response
   now includes the `bridge_template` field so the user sees the
   authoritative path even if we can't find any .rdc there.

If the next run still reports `rdc_files=0` AND the template points
to a normal writable dir, the Present hook isn't wired (game started
without renderdoccmd launch, or injected too late). The `captures=N`
counter from `__cam_rdc_info` settles the question -- if it's 0
after our 7 triggers, RDC isn't actually capturing.

---

旧版 CL 和已完成 TODO 见 `agents/reversing/ARCHIVE.md`。
