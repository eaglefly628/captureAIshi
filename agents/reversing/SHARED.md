# Reverse Engineering Agent (小逆) — Shared Notes

Current context lives here. Completed items and old CL entries move to
`agents/reversing/ARCHIVE.md`. Auto-archive rule: CL entries older than
**14 days** are moved to ARCHIVE.md on next session (see
`.claude/rules/versioning.md`).

## Active TODO

### Open items

- [ ] **P0: Path B Phase 2 -- build & validate end-to-end on Hellblade II**
  Phase 0 / 0.5 / 1 done (eb65088 / 75fb383 / Phase 1 commit). Code path
  is in place: bridge.cpp + frame_capture embedded -> one
  `captureAIshi_bridge.addon`; `grabbers/reshade_grabber.py` reads its
  output; UI dropdown + main.py factory wired; `scripts/deploy_reshade.py`
  copies binaries into game dir.
  Outstanding before "works":
    - Build the addon on a Windows host:
        `cd 3rdparty/reshade_bridge/src && cmake -B build -G "Visual Studio 17 2022" -A x64 && cmake --build build --config Release`
      and the ReShade core (3rdparty/reshade/) for `dxgi.dll`.
    - Iterate on inevitable C++ compile errors from embedding (FormatEnum
      symbol clashes, /utf-8 mismatches, MSVC /W3 warnings, etc.).
    - `scripts/deploy_reshade.py --game-dir <hellblade2> --output-dir <out>`,
      launch game, verify ReShade overlay shows "captureAIshi Bridge".
    - Connect bridge driver (TCP 9998), confirm GEngine scan finds UE5
      objects; run a short trajectory; confirm BMP+EXR triplets land.
    - Optional polish: `__fc_capture_now` TCP command for pose-precise
      capture (current grabber polls timer-driven output, ~33ms latency).
  Path A unaffected throughout. Reference: 3rdparty/reshade_bridge/README.md.

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

### [v0.3.0] (pending) -- xiaoni -- pre-UI survey: manual trigger via Web UI button + /api/reshade/survey (was auto-on-setup, now too eager)

User report: auto-survey in setup() ran before Batman AK reached 3D
gameplay (publisher logos / loading screen / main menu have no DSV
passes), every first-run returned "no recommendation" and skipped.
Survey should be user-triggered after they confirm they're in scene.

- `grabbers/reshade_grabber.py`: deleted `_maybe_run_first_run_survey`
  auto-trigger from `setup()`; replaced with `_log_pre_ui_hint` that
  warns if pre-UI is requested but no skip persisted; exposed
  `run_pre_ui_survey()` as public API for explicit invocation.
- `web/routes/reshade.py` (new): `POST /api/reshade/survey` ->
  `grabber.run_pre_ui_survey()`. 409 if no active session or grabber
  is not ReShade. 503 if survey returns None.
- `web/routes/__init__.py`: register `reshade_bp`.
- `web/templates/index.html`: new "Pre-UI: Run Pre-UI Survey" button
  in Bridge Debug panel + `reshadeSurvey()` JS handler with status
  pill (running / skip=N / failed:<reason>).
- Peer-review note left in `agents/rendering/SHARED.md` P2 for xiaoxuan
  to add real F6 keypress handler in `frame_capture.cpp` (currently
  the `[F6] 开始 survey` overlay hint is decorative -- no handler).

### [v0.3.0] bed4cd2 -- xiaoni -- web UI: forward hack_profile_id -> args.game so capture_profile reaches grabber

Diagnostic on Batman AK ReShade run: ini stayed at `FC_PreUICapture=0`
+ `FC_ExportNormal=0` + `FC_PreUISkipCount=0`, survey never fired,
no `[INIT] Loaded game profile 'batman_ak'` log. Root cause:
`web/helpers.py._build_args` never set `args.game`, so
`main._load_capture_profile` always returned `{}` for Web-UI launches.
The 8854614 + 07210e2 fixes ship empty into the grabber from the UI.

- `web/helpers.py`: `args.game = hack_profile_id or None`.
- `grabbers/reshade_grabber.py` `_maybe_run_first_run_survey`: log the
  silent-skip reason (was returning without any log line when
  `rgb_strategy` did not request pre_ui).

### [v0.3.0] 07210e2 -- xiaoni -- ReShade grabber auto-runs pre-UI survey on first run + persists FC_PreUISkipCount

Pre-UI capture needs both `FC_PreUICapture=1` AND a per-game
`FC_PreUISkipCount=N` (N != 0 for almost every game). The previous
fix wired the bool flag but left N=0, so Batman AK still grabbed
post-UI frames. New flow:

- `_resolve_pre_ui_skip`: profile.pre_ui_skip_count > game-dir
  sidecar `.captureAIshi_skip.txt` > 0.
- `_maybe_run_first_run_survey`: when rgb_strategy contains `pre_ui`
  and no skip is pinned/persisted, invoke `tools.capture.survey.run`
  against the live game, persist the recommended skip to the sidecar,
  rewrite `unicap.ini`, terminate + relaunch the game so the addon
  picks up the new value via `reshade::get_config_value`.
- Survey is best-effort: if the game is still at the main menu /
  no opencv installed / survey aborts, we log clearly and continue
  with skip=0 -- user can delete the sidecar and rerun once they
  are in actual gameplay.
- `_write_reshade_config` emits `FC_PreUISkipCount=<resolved>`.

### [v0.3.0] 8854614 -- xiaoni -- ReShade grabber honours capture_profile (pre-UI / normal / depth PNG)

- `grabbers/reshade_grabber.py` ctor: new `capture_profile` param.
- `_write_reshade_config`: `FC_PreUICapture=1` when rgb_strategy has
  `pre_ui`; `FC_ExportNormal=1` when normal_strategy non-empty/non-"none".
- `save_frame`: after copy2, run `_read_exr_red` + `_normalize_depth`
  (curve + reversed_z) and write `<base>_d.png` next to .exr (parity
  with RDC path).
- `main.py`: hoist profile load to `_load_capture_profile(args)`;
  both renderdoc + reshade branches pass `capture_profile=`.
- Addon reads FC_* once at startup, so the game must be restarted
  once for new ini values to apply.

### [v0.3.0] cd631a4 -- xiaoni -- Path B "embedded" variant: bridge baked into dxgi.dll

Mirrors Path A's `renderdoc/renderdoc/core/bridge/` pattern where bridge code compiles into renderdoc.dll itself. New variant: `dxgi.dll` (= ReShade64.dll renamed) directly contains TCP 9998 + GEngine scan + frame capture. No separate `.addon` file. Standalone addon path at `3rdparty/reshade_bridge/` left intact -- both build modes now coexist.

- `3rdparty/reshade/source/captureAIshi/` (new): copies of bridge.cpp + 4 headers + frame_capture.cpp + FormatEnum.h + embed_api.h; `deps/` for v1 stb_image_resize + tinyexr + miniz (ReShade core does not provide these).
- `bridge.cpp` (embedded copy): DllMain / NAME / DESCRIPTION / register_addon ripped (those are addon idioms). Public ABI = `extern "C" void bridge_start() / bridge_stop()`.
- `frame_capture.cpp` (embedded copy): drops `STB_IMAGE_WRITE_IMPLEMENTATION` (reshade core's `deps/stb_impl.c` provides it; redefining = link error). Keeps `STB_IMAGE_RESIZE_IMPLEMENTATION` + `TINYEXR_IMPLEMENTATION`. Adds `WIN32_LEAN_AND_MEAN` (winsock.h vs winsock2.h).
- `3rdparty/reshade/source/dll_main.cpp`: includes `captureAIshi/embed_api.h`; ATTACH calls `bridge_start()` + `fc_embed::register_events()` + `start_workers()`; DETACH symmetric reverse.
- `3rdparty/reshade/ReShade.vcxproj`: 2 new `<ClCompile>` entries with `WarningLevel=Level3`, `TreatWarningAsError=false`, third-party warning silencing, and `AdditionalIncludeDirectories` for `deps/imgui;deps/stb;source/captureAIshi` on frame_capture.cpp. `ws2_32.lib` + `psapi.lib` pulled via `#pragma comment(lib,...)` in bridge.cpp.
- Built unverified -- expect a couple iterations of compile errors on first Windows MSBuild. Reference: Path A precedent in `renderdoc/renderdoc/core/core.cpp:43,689,788`.

### [v0.3.0] 41d7e26 -- xiaoni -- Path B review fixes (P0..P2 from architect review)

- C++ loader-lock fix: `bridge.cpp` DllMain now only calls `fc_embed::register_events()` (event hooks, no thread spawn); `fc_embed::start_workers()` runs in the deferred bootstrap thread alongside `startup()`. Symmetrical detach order: `shutdown()` -> `stop_workers` -> `unregister_events` -> `unregister_addon`.
- C++ symbol isolation: `frame_capture.cpp` internals wrapped in anonymous namespace; only `fc_embed::{register,unregister}_events` + `fc_embed::{start,stop}_workers` are visible. New `frame_capture/embed_api.h` is the single ABI seen by bridge.cpp.
- Build hygiene: per-file `/W4 /WX` on `bridge.cpp`, `/W3` on vendored `frame_capture.cpp` + imgui sources -- our own code keeps the warning-as-error safety net Path A enjoys.
- Grabber triplet race fix: `_wait_quiescent()` re-stat()s color/depth/normal until sizes are stable across consecutive samples before reading; rejects zero-size files; bounded by `poll_timeout_s`.
- Grabber readiness gate: `setup()` polls `bridge_port` (default 9998) for up to `readiness_timeout_s` (default 60s) before returning -- analogue of `RenderDocGrabber.wait_for_port`.
- Grabber double-IO fix: `save_frame()` overridden to copy addon-produced files instead of re-encoding decoded numpy arrays (preserves float-EXR depth precision; falls back to base `save_frame` when `_last_paths` is empty, e.g. unit tests).
- `scripts/deploy_reshade.py`: backs up any pre-existing `dxgi.dll` / `*.addon` to `*.before-captureAIshi`; `--undeploy` restores the backup.
- Tests: 14 unit tests for `ReShadeGrabber` (prefix detection, candidate paths, quiescence on stable / growing / empty files, sidecar lifecycle, save_frame copy + base fallback, readiness gate timeout). `python -m pytest tests/test_reshade_grabber.py` passes locally.

### [v0.3.0] 4c5ad75 -- xiaoni -- Path B Phase 1: embed frame_capture; grabber + UI wired

- `3rdparty/reshade_bridge/src/CMakeLists.txt` -- adds `frame_capture/frame_capture.cpp` + imgui `*.cpp` + deps include dirs (sdk/imgui/stb/tinyexr) to bridge target; one `.addon` output.
- `3rdparty/reshade_bridge/frame_capture/frame_capture.cpp` -- removed standalone DllMain/NAME/DESCRIPTION; new `init_addon_FC()` + `shutdown_addon_FC()` wrappers (worker threads + reshade event registration) for bridge.cpp to call.
- `3rdparty/reshade_bridge/src/bridge.cpp` -- DllMain calls init/shutdown FC alongside `reshade::register_addon`; NAME/DESC updated to advertise both subsystems.
- `grabbers/reshade_grabber.py` -- new FrameGrabber that polls `<output_dir>` for `<exe> <ts> {BackBuffer.{png,bmp},DepthBuffer.exr,NormalBuffer.exr}` triplets; setup() writes `fc_output_dir.txt` sidecar to game dir.
- `web/templates/index.html` + `main.py:create_grabber` -- new `reshade` grabber option / branch.
- `scripts/deploy_reshade.py` -- copies dxgi.dll + .addon + shaders into a game dir, primes sidecar; `--undeploy` reverses.

---

旧版 CL 和已完成 TODO 见 `agents/reversing/ARCHIVE.md`。
