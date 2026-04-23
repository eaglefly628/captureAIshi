# Reverse Engineering Agent (小逆) — Shared Notes

Current context lives here. Completed items and old CL entries move to
`agents/reversing/ARCHIVE.md`. Auto-archive rule: CL entries older than
**14 days** are moved to ARCHIVE.md on next session (see
`.claude/rules/versioning.md`).

## Active TODO

### Open items

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

### [v0.2.0] (pending push) -- xiaoni -- Post-loop auto-decode + restore start pose

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
