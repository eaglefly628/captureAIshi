# Reverse Engineering Agent (小逆) — Shared Notes

Current context lives here. Completed items and old CL entries move to
`agents/reversing/ARCHIVE.md`. Auto-archive rule: CL entries older than
**14 days** are moved to ARCHIVE.md on next session (see
`.claude/rules/versioning.md`).

## Active TODO

### Open items

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

### [v0.2.0] (pending push) -- xiaoni -- run.bat auto pip install + EXR probe diagnostics

User report after `ca62f70`: still hits "Cannot read EXR ... No
module named 'OpenEXR'". Probable cause: app wasn't restarted after
the auto-install commit landed, OR the pip install inside the
embedded-Python `_ensure_exr_loader` failed silently with output
swallowed by `--quiet`.

Two complementary fixes so the user genuinely cannot get a stale-deps
state:

- `run.bat` / `run_cli.bat`: now run
  `python -m pip install -q -r requirements.txt
   --disable-pip-version-check --no-warn-script-location` on every
  launch. Pip is a no-op for already-satisfied deps so cost is ~1-2s
  on subsequent runs but new entries (opencv-python, future deps)
  always land without the user re-bootstrapping.
- `web_ui._ensure_exr_loader`: drop `--quiet`, capture pip's
  stdout/stderr, log the tail of stdout on success ("Successfully
  installed cv2-..."), and on failure log exit code + last 500 chars
  of stdout/stderr so the user can see exactly why pip refused.
  `importlib.invalidate_caches()` between install and re-import in
  case Python's finder cached a "module not found" before install.
  Probe-success log promoted from DEBUG to INFO so the user can
  confirm at a glance which loader is active.

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

### [v0.2.0] f82f461 -- xiaoni -- Fix capture marker orientation in 3D preview

User screenshot: on an orbit with `look_at_center=True`, the FOV
pyramid markers pointed in wildly inconsistent directions -- some
outward, some up/down, none reliably toward the orbit center.

Root cause in `draw3d()`: I was pre-swapping the camera position into
canvas coords (`ey = p[3]=gameZ`, `ez = p[2]=gameY`) and then adding
game-space forward components (`fx, fy, fz`) to those pre-swapped
coordinates. Result: the `fy` (horizontal Y) offset was added to the
vertical axis, `fz` (vertical) was added to the horizontal depth axis.

Rewrite keeps every vector math step in pure game space (X, Y, Z=up)
and only swaps (x, z, y) at the `project3d` boundary via a local
`projGame` helper. Also replace the cross-product right/up vectors
with the well-known "right = normalize(forward x world_up)" form so
the pyramid's width axis really is horizontal to the camera.

- `web/templates/index.html` `draw3d()`: add `projGame(gx, gy, gz)`
  thin wrapper; rewrite the capture-marker loop using only game-space
  math. Apex/tip/far-rect corners all computed in (gameX, gameY, gameZ)
  and projected via `projGame`.

### [v0.2.0] a804214 -- xiaoni -- Unified 60Hz streaming for rdc-step + restore on any exit + decode fallback

Three user-reported bugs in one commit:

1. **Play jittered, Preview smooth.** rdc-step was a waypoint-driven
   `for pose in points` loop with `time.sleep(min(0.05, target - now))`
   — capped at 20 Hz between pokes so motion looked staccato. Preview
   (non-capture) already used a 60 Hz `interp_linear` time-based loop
   and looked smooth.

2. **Stop did not restore the pre-play pose, so a subsequent Play with
   relative_origin started from the stranded position.** Restore was
   only in the rdc-step branch's `finally`; Preview / streaming exited
   without calling `game_profile.write_camera`.

3. **3 captures logged but manual Decode saw `no .rdc files in
   output\ue5_rdoc\captures`.** Bridge likely wrote to RenderDoc's
   default template path (`%TEMP%\RenderDoc`) rather than the
   grabber's configured capture_dir; decoder had no fallback.

`drivers/trajectory_player.py`
- Removed the rdc-step specific waypoint loop. Both Preview and Play
  now go through the single 60 Hz `interp_linear` time-based loop.
  When `renderdoc_capture=True`, the loop additionally carries
  `cap_times` = sorted `{points[i].t for i in capture_indices}`; after
  each tick's poke, if the streaming cursor just crossed the next
  capture time we re-interp the pose at that exact time, poke it,
  sleep `settle`, fire `__cam_rdc_capture`, dwell `interval - settle`,
  then fold `time.monotonic() - pause_start` into ``pause_budget`` so
  the streaming clock stays in phase with the preset's `t`. Ticks in
  between captures are real 60 Hz pokes, so in-game motion is now as
  smooth as Preview.
- Moved `restore_pose -> game_profile.write_camera` out of the
  rdc-step-only finally into the unified finally block. Both Preview
  and Play exits (including Stop mid-flight) now restore the original
  pose.
- Startup log expanded: `rdc-step capture_dir=<path> exists=<bool>
  captures_planned=<N> interval=<s>`; warns when capture_dir is set
  but doesn't exist on disk.

`web/routes/trajectory.py` `/api/trajectory/decode`
- When no explicit `paths` body is given and the grabber's
  `capture_dir` is empty, also glob `%TEMP%\RenderDoc\**\*.rdc` (and
  `%TEMP%\**\*.rdc` as a last resort) so captures that land in
  RenderDoc's default template directory still get picked up. Error
  response now includes the `searched` list so the user can see where
  we looked.

### [v0.2.0] 54cf28f -- xiaoni -- Uniform FOV marker size in 3D preview

Follow-up to `5e7e1aa`: user reported capture markers with large FOV
values blew up the frustum on the 3D canvas ("视图框特别长"). The
markers are a schematic "here is a camera" icon, not a physically
accurate frustum, so render them all the same size.

- `web/templates/index.html` `draw3d()`: drop the per-point
  `fovLen * tan(fov/2)` computation, replace with fixed
  `FOV_HALF_W = fovLen * 0.28`, `FOV_HALF_H = fovLen * 0.16` (approx
  16:9 hint). The capture point's `fov` field is intentionally no
  longer consulted for the marker; it's still written to trajectory
  JSON for downstream consumers.

### [v0.2.0] 5e7e1aa -- xiaoni -- Fine path streaming + sparse captures + FOV/arrow 3D markers

User asks:
- 3D preview should draw the smoothest path.
- Camera should actually move smoothly at the configured speed, every
  frame.
- Captures are computed from sample count over total time; preview
  them on the 3D canvas with FOV frustum + forward arrow.

Split "path density" from "capture count". All 5 presets now generate
a fine path (`FINE_PATH_SAMPLES = 256`) for streaming + preview, while
the user's ``samples`` param becomes the sparse capture count (evenly
spaced indices into the fine path).

`drivers/trajectory_presets.py`
- New `generate_smooth(preset, params) -> (fine_path, capture_indices)`.
  Computes the capture indices as `round(i * (N-1) / (samples-1))` so
  they land exactly on evenly-spaced time ticks.

`web/routes/trajectory.py`
- `_generate_points` returns `(preset, fine_path, capture_indices)`.
- `/api/trajectory/preview` response adds `capture_indices` +
  `capture_count` alongside the existing `points` (which is now the
  fine path).
- `/api/trajectory/play` threads `capture_indices` into
  `TrajectoryPlayer.play()`.

`drivers/trajectory_player.py`
- `play()` accepts `capture_indices`; defaults to "every waypoint is a
  capture" when absent (back-compat with callers that passed sparse
  lists directly).
- rdc-step `_run()` now streams every fine waypoint in real time
  (target = `stream_start + pose.t + stream_pause`) so the in-game
  camera actually moves smoothly instead of jumping 8 octagonal
  segments. Only indices in ``capture_indices`` trigger
  ``__cam_rdc_capture`` + the ``capture_interval`` dwell; the time
  spent on capture dwells is added to ``stream_pause`` so the
  remaining waypoints stay phase-locked with their `t`.

`web/templates/index.html`
- Preview response is stashed as `{name, points, capture_indices}`.
- 3D renderer replaces the old "every 20th waypoint gets an arrow"
  sparse-tick overlay with: per-capture-index amber dot, forward arrow,
  and a 4-edge FOV frustum (apex at camera pos -> 4 corners of a far
  rect sized by `fovLen * tan(fov/2)`), plus a closed far rectangle.
  Uses the waypoint's FOV, pitch, yaw (roll ignored for the frustum
  hint). Fallback to 8 evenly-spaced indices when the server didn't
  ship `capture_indices` yet.

### [v0.2.0] 9495fd1 -- xiaoni -- Speed-driven trajectories + Preview/Play/Stop row

User feedback: entering "duration" is not intuitive; speed (units/s) is.
Also Pause/Resume buttons aren't used, and there should be a Preview
button that streams the path without burning RDC captures.

`drivers/trajectory_presets.py`
- New `_path_length(preset, params)` helper with closed-form lengths
  for orbit (2pi*r), helix (sqrt(circumference^2 + height^2)), line
  (Euclidean), figure8 (4pi*r), custom (polyline sum).
- `generate()` consumes a `speed` key if present and > 0, computing
  `duration = length / speed` before dispatching to the preset
  function. `speed` is popped so the preset fn (which still takes
  `duration`) is not confused. When `speed` is missing or 0 the caller's
  `duration` is honored (back-compat for saved trajectories).
- `PRESET_SCHEMA`: replaced `duration` with `speed` (orbit=200,
  helix=400, line=100, figure8=300, custom=100 units/s). `samples`
  default changed to 8 across all presets. Help text explains the
  `duration = length / speed` relationship per preset.

`web/templates/index.html`
- Trajectory control row rebuilt: `Preview | Play | Stop | Decode |
  Preview 3D | Clear 3D`. Pause and Resume buttons dropped
  (their JS fns remain, dead but harmless). Preview (new) calls
  `/api/trajectory/play` with `renderdoc_capture:false` via a shared
  `_trajBuildBody(rdc) / _trajPost(body, label)` helper pair.

### [v0.2.0] c41089a -- xiaoni -- Manual Decode button + /api/trajectory/decode

Follow-up to `40acc76`: user asked for an explicit decode trigger so
re-decoding / post-hoc decode (session started without grabber, or
auto-decode missed) is a one-click action instead of replaying a
trajectory.

- `web/routes/trajectory.py` new `POST /api/trajectory/decode`:
  requires an active RenderDoc grabber (`web.state.get_active_grabber`),
  collects `.rdc` files from `grabber.capture_dir` sorted by mtime (or
  accepts an explicit `{"paths": [...]}` body for targeted re-decode),
  kicks `grabber.export_batch(paths, output_dir)` on a background
  `manual-decode` thread, and flips player state to `exporting` while
  in flight. `output_dir` comes from the session's
  `_capture_state["output_dir"]`.
- `web/templates/index.html`: new `Decode` button in the Trajectory
  control row (next to Play/Pause/Resume/Stop) + `trajDecode()` JS
  helper that posts empty body; server picks "all .rdc in capture_dir".
  Tooltip explains this is also the fallback for re-decoding.

### [v0.2.0] 40acc76 -- xiaoni -- Post-loop auto-decode + restore start pose

User report: 8 captures fired cleanly on 3 s interval but nothing
happened after the rdc-step loop -- "No captures yet" in the gallery,
no PNGs, camera left stranded on the last waypoint.

Two fixes in one commit, both for the trajectory Play path:

(1) Post-loop auto-decode via the active RenderDoc grabber.
- `web/state.py`: new `set_active_grabber(g)` / `get_active_grabber()`
  thread-safe module slot. `main.run_capture` publishes the grabber
  after `grabber.setup()` succeeds and clears it in the finally block.
- `web/routes/trajectory.py` `/api/trajectory/play`: if the active
  grabber exposes `export_batch`, build a decode callback that calls
  `grabber.export_batch(rdc_paths, output_dir)` where `output_dir`
  comes from the session's `_capture_state['output_dir']`. Pass the
  grabber's `capture_dir` so the player knows where .rdc files land.
- `drivers/trajectory_player.py`: rdc-step loop now watches
  `capture_dir` via `set(Path.glob('*.rdc'))` diffing and collects new
  .rdc paths per pose. On loop exit, if `decode_callback` is set and
  at least one .rdc was collected, fire the callback on a background
  thread (so the player thread itself can unwind cleanly). Player
  state transitions `playing -> exporting -> idle` so the UI poll can
  show the decode phase.

(2) Restore the pre-play camera pose so the user ends up exactly where
they were before pressing Play.
- `TrajectoryPlayer.play()` now unconditionally snapshots the current
  pose via `game_profile.read_camera_pose`. When `relative_origin` is
  on the same read is reused for the offset; it's also threaded into
  `_run` as `restore_pose` and consumed in the rdc-step finally block,
  which calls `game_profile.write_camera(...)` with the stored pose.
  Failure is logged but does not abort the exporting pass.

### [v0.2.0] 8ed197d -- xiaoni -- RDC-step capture_interval (16->16 captures land)

User hit: figure8 trajectory Play with 16 samples @ 60 Hz + rdc_capture
fired all 16 __cam_rdc_capture commands in ~0.5 s (log "rdc-step done
captures=16" at +0.543 s after start) and only 2 .rdc files actually
landed because the hardcoded step was `max(1/rate_hz, 0.033)` = 33 ms
per pose -- RenderDoc can't capture 30 Presents in 0.5 s from queued
triggers.

- `drivers/trajectory_player.py` `TrajectoryPlayer.play()`: new
  `capture_interval: float = 1.5` param. rdc-step loop now:
  1. Poke camera + short settle (`max(1/rate_hz, 0.05)`) so the new
     pose reaches the render thread.
  2. Fire `__cam_rdc_capture`.
  3. Sleep the remaining `interval - settle`, in 100 ms chunks so
     Stop is responsive during long intervals.
  4. Log `[PLAYER] capture X/N triggered (interval=Ns)` per pose.
  Interval lower-bounded to `settle`.
- `web_ui.py` `/api/trajectory/play`: forwards
  `capture_interval=max(0.1, body["capture_interval"] or 1.5)`.
- `web/templates/index.html` Bridge Debug panel: new
  `#capture_interval` input next to `#focus_delay` (default 1.5 s,
  min 0.1, step 0.1). Persisted in localStorage under
  `captureAIshi.captureInterval`. Wired into `trajPlay()`.

Deterministic sync via bridge `__cam_rdc_capture_await` (polling
`RenderDoc::Inst().GetCaptures().size()`) + post-loop auto-decode
via `grabber.export_batch(rdc_paths, output_dir)` are deferred --
they need bridge DLL rebuild and grabber-singleton wiring.

### [v0.2.0] 8554e66 -- xiaoni -- run_capture: launch-and-wait session mode

Follow-up to `f6c58ad`: raising inside `run_capture` killed the main
Web UI Start button (user report: "Legacy volume/snake/cone capture
pipeline has been removed. Use the Web UI Play button..." traceback).
The Start button still needs to launch the game via renderdoc and
hold the bridge connection open so Capture / Play can be used.

`main.run_capture` now:
1. Creates driver / UI hider / grabber.
2. `grabber.setup()` to launch the game via renderdoccmd (or inject).
3. Connects the driver (manual-mode fallback on connection failure).
4. Enables debug camera + runs the UWorld / LocalPlayer readiness gate.
5. Hides UI once.
6. Blocks on `stop_event` / KeyboardInterrupt.
7. Finally block restores UI + tears down grabber + disconnects driver.

No pose generation, no `poses.json`, no capture loop. All capture work
is driven from the Debug panel (Capture button) and Trajectory panel
(Play button) against the live bridge. The dead pose-gen + capture
loop remains after a `return` statement inside run_capture and will be
deleted in the next sweep along with `core/snake_path.py`,
`core/cone_rotation.py`, `BoundingVolume`, `smooth_waypoints`, and
their tests.

### [v0.2.0] d03a98c -- xiaoni -- Configurable focus delay for Capture + Play

Batman AK (and other focus-sensitive games) enters the pause menu when
the browser click steals focus; the game stops ticking its hooked code,
so `/api/hacks/capture` times out and trajectory Play writes fail. The
trajectory_player already took a `focus_delay` param (default 5.0s) but
the web UI was hardcoding 5s and the Capture button had no delay at all.

- `web/templates/index.html` Bridge Debug panel: new `#focus_delay`
  number input (default 5.0, step 0.5, min 0) with tooltip explaining
  the alt-tab window. Value persists in `localStorage` under
  `captureAIshi.focusDelay`, reloaded on DOMContentLoaded.
- `_afterFocusDelay(fn)` helper logs "waiting Ns for game focus..." to
  the debug console then `setTimeout`'s the fn; delay == 0 fires
  immediately (no wait, no log).
- `hackCapture()` wrapped in `_afterFocusDelay` so the Bridge Debug
  "Capture" button now respects the configured delay (previously fired
  instantly).
- `trajPlay()` passes `focus_delay: focusDelay()` in the
  `/api/trajectory/play` POST body instead of letting the backend pick
  its 5.0 default.

Backend consumption already in place: `web_ui.py:409` clamps the
incoming `focus_delay` to `>= 0` and threads it into
`TrajectoryPlayer.play()` → `_auto_capture(focus_delay=...)`, which
only sleeps when `focus_delay > 0`.

### [v0.2.0] f6c58ad -- xiaoni -- Remove legacy volume/snake/cone capture pipeline

User request: drop the volume + snake path + cone rotation capture mode
(source of 956-capture runs). Trajectory-based capture
(`drivers/trajectory_player.py`) is now the only supported path.

- `main.py` `run_capture`: early-raises `RuntimeError` with migration
  message. Old Steps 1-3 + capture_loop left unreachable short-term
  (full deletion in follow-up sweep that also drops
  `core/snake_path.py`, `core/cone_rotation.py`, `BoundingVolume`,
  tests, and `gui.py` spinners).
- `main.py` argparse: dropped `--volume-min/--volume-max/--spacing/
  --smooth/--smooth-points/--cone-angle/--cone-samples/--cone-rings`.
- `web_ui.py` `_build_args` + `/api/defaults`: dropped volume /
  spacing / cone / smooth fields. Residual preset data blobs at lines
  719+ kept (inert now, swept next session).
- `web/templates/index.html`: removed `catArea`, `catPath`, `catCone`
  detail panels; removed corresponding `catMap` entries (lv2 menu items
  were already gone since `c656837`). Dropped `vol_min/max`, `spacing`,
  `smooth*`, `cone_*` references from `getFormData`, `applyParams`,
  `_applyGameConfig`, `updateVisibility` (`smoothPointsWrap`), and
  the 3D visualizer (bounding box + grid drew from the removed
  `vol_min_x` / `spacing` inputs).

Batman `ue3_packed_int` trajectory conversion from `afc35b5` is still
in place; this CL doesn't touch that path.

### [v0.2.0] afc35b5 -- xiaoni -- Batman ue3_packed_int deg conversion

Fix long-standing TODO in `configs/hacks/batman_ak.json`: camera rotation
writes for UE3 were casting deg floats to i32 verbatim, so any non-integer
or out-of-range angle got truncated and rotation was effectively broken.

- `drivers/game_profile.py`: add `_deg_to_ue3_packed` / `_ue3_packed_to_deg`
  helpers (FRotator: 0x10000 = 360 deg, normalized to [-32768, 32768) so
  values stay inside signed int32 and any ViewPitchMin/Max game clamp).
- `drivers/game_profile.write_camera`: convert pitch/yaw/roll deg -> packed
  int before the i32 poke when `rotation.type == "ue3_packed_int"`.
- `drivers/game_profile.read_camera_pose`: reverse direction - packed -> deg
  on read so the pose dict stays in degrees for UI / trajectory.
- `drivers/trajectory_player.py`: `_PokeField` gains `raw_type` so per-tick
  `_pose_value` can apply the same conversion before the i32 wire poke.
- `tests/test_trajectory.py`: new `TestUE3PackedInt` class (4 cases) -
  known-value table, deg<->packed roundtrip, float input from mem_peek,
  `_pose_value` integration via `_PokeField`.

Bridge side verified no change needed: `console_server.h` i32 parse uses
`strtol` (accepts negatives) then `(uint32_t)(int32_t)v` to store the
unsigned DWORD; e.g. -16384 -> 0xFFFFC000 which FRotator wraps correctly
as -90 deg.

batman_ak.json `_comment` updated to drop the "next commit" marker.

### [v0.2.0] c656837 -- xiaoni -- Gemini review sweep + UI Phase 1 bug fixes

Gemini external + round-2 review items, plus 2 UI bugs reported by the
user after testing the Phase 1 build. Next session = UI Phase 2
(main.py trajectory-driven capture + legacy form removal).

Fixed (bridge, both trees where applicable):
- P0 strtof locale trap (Gemini): new ascii_strtof/ascii_strtod parsers;
  all strtof/strtod sites in console_server.h + bridge.cpp replaced.
- P1 handle_client dead socket not removed (Gemini): renderdoc tree
  slot cleanup on thread exit + trailing-compaction. 3rdparty tree
  already did this.
- P1 g_smooth_factor atomic (Gemini): std::atomic<float> with relaxed
  ordering on both trees.
- P1 UObject GC lifecycle (Gemini round-2, verified by Opus 4.7):
  UEVersionLayout.ue_obj_flags_off field + cam_manager_alive() SEH
  probe + clear-on-GC-mark. Renderdoc-tree only (3rdparty lacks the
  layout struct).

Fixed (UI, reported by user against 2325ee6):
- Bridge Debug "Advanced" toggle did nothing: `toggleAdvancedAob()` was
  defined inside the IIFE that wraps `toggleDebugPanel`, so it wasn't
  on window. Moved to global scope.
- Cascade Lv2 menu still listed Capture Area / Path / Cone Rotation.
  Removed those 3 items from the lv2 menu. The DOM nodes they opened
  are intentionally kept so stale JS reading vol_min_x/spacing/cone_angle
  ids keeps seeing the default values; full removal lands with the
  Phase 2 main.py migration.

Deferred to next session:
- P2 __try call-chain audit (review-only, partial done -- cam_patch_write
  is clean, but other __try sites need a full sweep).
- P2 Catmull-Rom uniform -> centripetal.

### [v0.2.0] 2325ee6 -- xiaoni -- UI Phase 1: debug refactor + custom trajectory + save/load + auto-preview

Phase 1 of the operator workflow re-focus. Phase 2 (backend capture
migration + removing legacy volume/spacing/cone pipeline) lands in a
separate CL.

UI:
- Bridge Debug panel trimmed. REMOVED from always-visible row:
  slomo / Normal / FPS / Stat Off / DebugCam / HUD Off / HUD On / Pause
  / Status / Arm Break. Status + Arm Break survived into new Advanced
  section. KEPT visible: Re-scan UE, Cam POV (Find/Read/OV On/OV Off).
- COLLAPSED under new "Advanced: AOB intercept + per-game profile":
  Intercept (List/NOP/Pass/Uninstall + install form), per-game Profile
  (Apply/Lock/Unlock/Clear + select), Capture (Capture/Read Addr/Test).
- Trajectory panel: Save/Del + saved-trajectory dropdown
  (configs/trajectories/*.json round-trip); auto-preview checkbox
  (250 ms debounced); RDC capture checkbox plumbed into
  TrajectoryPlayer.play(renderdoc_capture=...).

Backend:
- `drivers/trajectory_presets.py`: new `custom` preset (3/6/7-tuple
  waypoints, linear subdivision, optional look_at).
- `web_ui.py`: `/api/trajectory/save` + `/api/trajectory/saved/<name>`
  GET/DELETE + list. Name slugged to block path traversal.
- `drivers/trajectory_player.py`: PlayerStatus carries `renderdoc_capture`.

Tests: 46 in test_trajectory.py (custom preset + 7 saved-trajectory
flask tests incl. path-traversal rejection). All green.

Phase 2 TODO (next CL): main.py trajectory-driven capture; remove
volume/spacing/cone UI form; repurpose cone as per-waypoint sweep into
trajectory JSON; wire RDC capture trigger in backend.

### [v0.2.0] ee9a5db -- xiaoni -- Game library trim to 6 active titles

- `configs/game_library.json`: 332 -> 6. Active: StackOBot (UE5 self-built),
  Batman: Arkham Knight (UE3), Hellblade: Senua's Sacrifice (UE4),
  Cyberpunk 2077 (REDengine 4), Unreal Physics (UE5), Black Myth: Wukong (UE5).
- `configs/game_library_full.json`: backup of the original 332-entry UUU lib.
- `configs/hacks/unreal_physics.json` + `black_myth_wukong.json`: STUB profiles
  (intercepts=[], camera_write_profile.enabled=false). apply_profile() will
  only run __cam_intercept_uninstall until intercepts[] populated by Commit D
  auto-discovery or CE.
- `/api/games` now returns 6, `/api/hacks/list` returns 6. Profile dropdown
  and Game Library panel both show only these titles after hard refresh.

---

旧版 CL 和已完成 TODO 见 `agents/reversing/ARCHIVE.md`。
