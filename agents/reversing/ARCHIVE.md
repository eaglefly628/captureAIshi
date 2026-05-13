# Reverse Engineering Agent (小逆) — Archive

已完成 TODO 和详细调研。从 SHARED.md 归档以节省 token。

---
## Archived 2026-05-13 (auto-archive: beyond top 3 CL + closed TODOs)

### Closed TODOs

- [x] **P1: trajectory decode callbacks 不保存 PNG** (spotted by 小萱, fixed 9498850) —
  `export_batch` 返回 numpy arrays，调用方需调 `save_frame` 写盘。
  `trajectory_play._decode` 和 `/api/trajectory/decode._run_decode` 都直接丢弃了
  返回值，导致 rdc-step 采集后 output_dir/frames/ 为空。已在 trajectory.py 两处
  补 save_frame 循环，用 rdc_path.stem 为文件名 base。

### Archived CL entries (beyond top 3 / older than 14 days)

### [v0.3.0] 75fb383 -- xiaoni -- Vendor unicap source (drop submodule)

- `3rdparty/reshade/` -- full ReShade core source 60MB (was unicap/reshade/), pin 6.7.3.16 UNOFFICIAL; builds dxgi.dll proxy via MSBuild.
- `3rdparty/reshade_bridge/{sdk,frame_capture,deps,shaders}/` -- addon SDK headers + frame_capture.cpp (1350 LOC) + imgui/stb/tinyexr + DepthToAddon/BackBufferExport/CaptureStatus shaders.
- `3rdparty/unicap` submodule + `.gitmodules` removed. Per project decision: unicap is "ours" now; no upstream sync.
- `3rdparty/reshade_bridge/src/CMakeLists.txt` -- SDK include points at vendored `../sdk/` instead of submodule path.
- `3rdparty/reshade_bridge/README.md` -- Layout + Provenance + Phase 0.5/1/2 sections; Phase 1 lean = embed frame_capture into bridge addon (one .addon to ship).
- NOT vendored: unicap `main.py`/`tools/capture/`/`profiles/`/`unicap_gui/`/`auto_play/` -- captureAIshi has its own pipeline; only protocol bits port to `grabbers/reshade_grabber.py` in Phase 1.

### [v0.3.0] eb65088 -- xiaoni -- Path B scaffold: reshade_bridge addon

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

## Completed TODO

- [x] **P0: ConsoleServer_Start Sleep(5000)** — 改轮询 500ms, 60s timeout。
- [x] **P0: detached client threads 无清理** — tracked vector + join。
- [x] **P1: static 全局变量在 header** — 加注释说明单 TU include。
- [x] **P1: vtable 暴力搜索用用户命令** — 改 `stat none` 探测。
- [x] **P1: __path_delete atoi 负数溢出** — 加 `val < 0` 检查。
- [x] **P1: C++ headers Unicode** (fixed by 主程序员) — U+2500 → ASCII。
- [x] **P2: toggle_hud ShowFlag.PostProcessing** — 移除，只用 ShowHUD。
- [x] **P2: Quat 旋转顺序** — 改 YXZ，与 Python 一致。
- [x] **P2: 缺 CL** — 已补。
- [x] **P3: AOB 数据库调研** — 结论：不需要 per-game DB。

## [v0.1.0] Tested Games
- EagleWalkLJB (UE5 demo): RenderDoc OK, console OK, ToggleDebugCamera OK

## [v0.2.0] AOB Database Research

结论：不需要 per-game 数据库。UUU 用引擎通用 pattern。

可复用资源: patternsleuth (Rust), UEVR (praydog), UE4SS (Lua), IGCS (手工 AOB)

我们的改进: 8 个锚点 (CALIBRATEMOTION, SeamlessTravel FlushLevelStreaming, StaticConstructObject_Internal, r.HLOD + 原 4 个 wide)。

## [v0.2.0] ProcessConsoleExec VTable Research (2026-04-08)

### Root Cause: Wrong Function + Wrong VTable Range

我们一直在调用错误的函数:
- **错误**: 找 `UObject::Exec(UWorld*, TCHAR*, FOutputDevice&)` at vtable[110-130]
- **正确**: 找 `UObject::ProcessConsoleExec(TCHAR*, FOutputDevice&, UObject*)` at vtable[65-90]

参数顺序也完全不同:
- 旧: `fn(this, world, cmd, ar)` -- rdx=UWorld*, r8=cmd, r9=ar
- 新: `fn(this, cmd, ar, executor)` -- rdx=cmd, r8=ar, r9=executor

### UE4SS PDB-Verified VTable Indices

来源: UE4SS `assets/VTableLayoutTemplates/` (PDB 符号导出)
ProcessConsoleExec = ProcessEvent + 3 (永远)

| UE Version | ProcessEvent | ProcessConsoleExec |
|------------|:----------:|:-----------------:|
| 4.10 | 50 | 53 |
| 4.11-4.13 | 53 | 56 |
| 4.14 | 57 | 60 |
| 4.15 | 58 | 61 |
| 4.16 | 62 | 65 |
| 4.17-4.19 | 63 | 66 |
| 4.20 | 65 | 68 |
| 4.21-4.22 | 64 | 67 |
| 4.23-4.25 | 66 | 69 |
| 4.26 | 67 | 70 |
| 4.27 | 68 | 71 |
| 5.00 | 75 | 78 |
| 5.01 | 76 | 79 |
| 5.02-5.04 | 77 | 80 |
| 5.05 | 79 | 82 |
| 5.06-5.07 | 76 | 79 |

### Index 非单调递增原因

- UE 5.01: UObjectBase 加了 `GetFNameForStatID` (+1)
- UE 5.05: UObjectBaseUtility 加了新条目 (+1)
- UE 5.06: UObject 移除了多个虚函数 (PreSaveRoot, PostSaveRoot 等), index 回落

### UEVR 方案参考

- UEVR 用私有子模块 UESDK (不公开) 解析 vtable
- UE4SS 用 PDB 符号表 + INI 模板 (最可靠)
- UE4SS 的 UVTD (Unreal VTable Dumper) 从 PDB 自动导出 vtable 布局

### 验证方法: Ar-callback detection

真正的 ProcessConsoleExec 会调用 `Ar.Serialize()` (FOutputDevice 虚函数)。
用 dummy FOutputDevice + callback flag 检测: 如果 Ar 被调用 = 找到 Exec。

## [v0.1.0] Camera Control Details

### Unity
- BepInEx plugin (IL2CPP + Mono)
- UnityExplorer runtime inspector

---
## Archived 2026-04-18 (精简 SHARED.md)

### Closed TODO items (全部已完成)

- [x] P0: 3rdparty/bridge/src/ 与 renderdoc/ 双树分叉 → e2cd967 同步
- [x] P0: line_buf 无大小上限 → 1MB cap + disconnect
- [x] P0: ue5_engine.h 文件拆分 → c088120 (5 子文件)
- [x] P0: cmd_queue CAS 引入消费者读半写槽 → 2c0ea17 per-slot ready flag
- [x] P0: cam_patch_write() patch 时未暂停游戏线程 → SuspendThread
- [x] P0: ue5_scan_engine.h 裸指针解引用无 SEH (×2) → seh_read_ptr
- [x] P0: ue5_scan_camera.h FField 裸解引用 (×2) → seh_read_u32_ok
- [x] P0: g_cam_override_state 多线程撕裂读写 → g_cam_override_mutex
- [x] P0: strtof locale 陷阱 → ascii_strtof / ascii_strtod (both trees)
- [x] P1: recv() 错误和关闭未区分 → n==0/n<0 split
- [x] P1: __path_delete atoi 整数溢出 → strtol + bounds
- [x] P1: camera_path.h count/tick/list 无 mutex → mutable + lock_guard
- [x] P1: ClientArg CreateThread 失败泄漏 → delete arg + closesocket
- [x] P1: camera_intercept.h memcpy 无 SEH (×2) → cam_seh_memcpy
- [x] P1: VirtualQuery 未检查 size 跨页 → cross-boundary check
- [x] P1: InterpolatedCamera cam 未初始化 → zero-init
- [x] P1: camera_path.h play/stop 未持锁 → stop_unlocked()
- [x] P1: __cam_mem_write 未做 NaN/Inf 过滤 → cs_sanitize_float
- [x] P1: g_cam_pov_ptr 无同步 → g_cam_pov_mutex + try_lock
- [x] P1: ConsoleServer_Stop WSACleanup 时序 → 移到 Stop()
- [x] P1: console_server.h Sleep(5000) → module-size-stability poll
- [x] P1: console_server.h 无 WSAStartup → cs_server_main 内初始化
- [x] P1: EnumWindows 重复代码 → find_game_window()
- [x] P1: cmd_queue 生产者无溢出保护 → drop with log
- [x] P1: 33rd client socket-reuse UAF → slot-full check before CreateThread
- [x] P1: cam_patch_write SuspendThread 下 bridge_log 死锁 → 改错误缓冲
- [x] P1: __cam_mem_find 暂停 override 竞争窗口 → g_cam_pov_mutex
- [x] P1: handle_client 退出不从 g_client_socks 移除 → slot cleanup
- [x] P1: g_smooth_factor 裸读写数据竞争 → std::atomic<float>
- [x] P1: UObject GC lifecycle 校验缺失 → cam_manager_alive() flags check
- [x] P1: WSACleanup ordering + scan 线程超时 (caveat noted)
- [x] P2: cs_smooth_initialized 数据竞争 → std::atomic<bool>
- [x] P2: BRIDGE_LOG vsnprintf truncation → clamp n to avail-1
- [x] P2: g_fexec_hook_count volatile → std::atomic<LONG>
- [x] P2: 第 33 个客户端 socket 泄漏 → shutdown + closesocket
- [x] P2: Sleep(100) → SwitchToThread()
- [x] P2: client thread shutdown → ClientSlot + shutdown(SD_BOTH)
- [x] P2: console_server.h strtof INF/NaN → cs_sanitize_float
- [x] P2: hardcoded sleep(0.5) → cam_read() FOV poll
- [x] P2: g_gvc_ptr binary-address bug → LP+0x78 authoritative
- [x] Gemini 第二轮外审 3 条驳回 (Nagle/accept 阻塞/LWC 严重性) — 经 Opus 4.7 验证均为 false alarm 或定性夸张

### Archived CL entries (older than 14 days)

#### [v0.2.0] 46cb892 -- xiaoni -- Commit C: trajectory 3D preview
Hooks /api/trajectory/preview into view3d canvas. Preview 3D / Clear 3D
buttons; cyan path + start/end dots + yaw/pitch arrows + red playhead bisect.
UE Z-up -> canvas Y-up swap done in draw pass. 32 tests passed.

#### [v0.2.0] 2c0ea17 -- xiaoni -- Opus 4.7 round-2 review (5 items)
P0 cmd_queue per-slot ready flag. P1: 33rd-client pre-CreateThread check;
cam_patch_write error buffer after resume; g_cam_pov_mutex in tick+find.
P2 g_fexec_hook_count -> std::atomic<LONG>.

#### [v0.2.0] 1a10b3d -- xiaoni -- Opus 4.7 review sweep (13 items)
2 P0 (cmd_queue CAS, SuspendThread patch), 7 P1 (VirtualQuery cross-page,
zero-init, play/stop mutex, sanitize_float, pov sync, WSACleanup, EnumWindows),
4 P2 (BRIDGE_LOG, g_fexec_hook, 33rd socket, SwitchToThread).

#### [v0.2.0] 76cbd5a -- xiaoni -- Commit B: trajectory presets + 60 Hz player
orbit/helix/line/figure8 generators. TrajectoryPlayer 60Hz writer thread,
persistent _PokeSession, pause/resume/loop. 7 Flask routes. 26 tests.

#### [v0.2.0] (pending) -- xiaoni -- IGCS-style camera intercept (MVP)
camera_intercept.h: AOB scan + VirtualProtect byte-swap + cam_suspend_others.
TCP: __cam_intercept_install_aob/nop/pass/list/uninstall.

#### [v0.2.0] 8994179 -- xiaoni -- 老白 bug fix sweep
Batch 12-of-14: SEH on bare ptrs, g_cam_override_mutex, line_buf 1MB cap,
strtol path_delete, camera_path mutex, WSA lifecycle, overflow bound check,
sanitize_float, ClientSlot shutdown, SwitchToThread.

#### [v0.2.0] e2cd967 -- 主程序员 -- 3rdparty build tree sync
Applied equivalent P0/P1/P2 fixes to compiled tree (3rdparty/bridge/src/).
Both trees remain independent (CMake consolidation TBD).

#### [v0.2.0] Earlier CLs (c088120, d82c2b4, a403a51, 738ea13, 152fc53,
d37d007+5a050ec, 6879265, (prev pending), a0fe8c3, 373cf2b, 711d8eb,
aea22c7, 951ee30, stride-fix, PCE-fix, d32d2aa)
See git log for full details. All shipped to claudeMainBranch.

---
## Archived 2026-04-25 (超过 3 条 CL 限制)

### [v0.2.0] f82f461 -- xiaoni -- Fix capture marker orientation in 3D preview
- `web/templates/index.html` `draw3d()`: kept all vector math in game space; added `projGame(gx,gy,gz)` wrapper; rewrite capture-marker loop. Fixed fy/fz axis swap bug.

### [v0.2.0] a804214 -- xiaoni -- Unified 60Hz streaming for rdc-step + restore on any exit + decode fallback
- `trajectory_player.py`: unified rdc-step + preview into single 60Hz `interp_linear` loop; moved restore_pose to unified finally block.
- `web/routes/trajectory.py`: decode fallback globs `%TEMP%\RenderDoc\**\*.rdc`.

### [v0.2.0] 54cf28f -- xiaoni -- Uniform FOV marker size in 3D preview
- `draw3d()`: replaced per-point `fovLen*tan(fov/2)` with fixed `FOV_HALF_W/H` constants.

### [v0.2.0] 5e7e1aa -- xiaoni -- Fine path streaming + sparse captures + FOV/arrow 3D markers
- `trajectory_presets.py`: new `generate_smooth()` returning (fine_path, capture_indices) with FINE_PATH_SAMPLES=256.
- `web/routes/trajectory.py`: preview/play return capture_indices; 3D renderer shows amber dot + FOV frustum per capture.

### [v0.2.0] 9495fd1 -- xiaoni -- Speed-driven trajectories + Preview/Play/Stop row
- `trajectory_presets.py`: new `_path_length()` + speed->duration conversion; PRESET_SCHEMA uses speed.
- UI: rebuilt control row Preview|Play|Stop|Decode|Preview3D|ClearD; dropped Pause/Resume.

### [v0.2.0] c41089a -- xiaoni -- Manual Decode button + /api/trajectory/decode
- New `POST /api/trajectory/decode` endpoint; UI Decode button.

### [v0.2.0] 40acc76 -- xiaoni -- Post-loop auto-decode + restore start pose
- `web/state.py`: set/get_active_grabber(). Post-loop decode callback fires export_batch on background thread.
- `TrajectoryPlayer.play()`: snapshots + restores pose on any exit.

### [v0.2.0] 8ed197d -- xiaoni -- RDC-step capture_interval (16->16 captures land)
- `TrajectoryPlayer.play()`: new `capture_interval=1.5` param; loop poke->settle->capture->dwell.
- UI: `#capture_interval` input persisted in localStorage.

### [v0.2.0] 8554e66 -- xiaoni -- run_capture: launch-and-wait session mode
- `main.run_capture`: now launch+connect+block on stop_event only; all capture driven from UI.

### [v0.2.0] d03a98c -- xiaoni -- Configurable focus delay for Capture + Play
- UI: `#focus_delay` input + `_afterFocusDelay(fn)` helper; trajPlay() passes focus_delay to backend.

### [v0.2.0] f6c58ad -- xiaoni -- Remove legacy volume/snake/cone capture pipeline
- `main.py`: early-raise on run_capture; dropped volume/spacing/cone argparse + UI panels.

### [v0.2.0] afc35b5 -- xiaoni -- Batman ue3_packed_int deg conversion
- `game_profile.py`: `_deg_to_ue3_packed`/`_ue3_packed_to_deg`; write_camera + read_camera_pose use them.
- `trajectory_player.py`: `_PokeField.raw_type` for per-tick conversion.
- 4 new tests in `test_trajectory.py`.

### [v0.2.0] c656837 -- xiaoni -- Gemini review sweep + UI Phase 1 bug fixes
- Bridge: ascii_strtof/ascii_strtod; slot cleanup on client exit; g_smooth_factor atomic; cam_manager_alive() GC check.
- UI: fixed toggleAdvancedAob() scope; removed Lv2 menu Capture Area/Path/Cone items.

### [v0.2.0] 2325ee6 -- xiaoni -- UI Phase 1: debug refactor + custom trajectory + save/load + auto-preview
- Bridge Debug panel trimmed; Advanced section collapsed; Trajectory panel gets Save/Del/auto-preview.
- Backend: custom preset; /api/trajectory/save + saved/<name> GET/DELETE; 46 tests green.

### [v0.2.0] ee9a5db -- xiaoni -- Game library trim to 6 active titles
- `game_library.json`: 332->6 active titles; stub profiles for unreal_physics + black_myth_wukong.

---

## Cleared 2026-05-13 (user requested clean slate before new PCG direction)

All Active TODO items cleared from SHARED.md. To recover full content:
  git show 039e250:agents/reversing/SHARED.md
or browse:
  https://github.com/eaglefly628/captureAIshi/blob/039e250/agents/reversing/SHARED.md

Inventory (Active TODO Open items, 10 items):
- [P0] Path B Phase 2 build & validate end-to-end on Hellblade II
- [P0] UpdateCamera 覆写 -- 渲染线程边界 hook (ULocalPlayer::GetViewPoint)
- [P0] 真实 UE5 游戏端到端验证 (StackOBot)
- [P0] Path D 逆向补全 (PC+0x100..0x800 manager ptr 扫描)
- [P0] UUU 功能复刻 (per-node FOV / __path_play / __path_loop / __path_pause / __camera_get)
- [P1] AC 预检脚本 (EasyAntiCheat.dll / BEService.exe)
- [P2] CL 条目缺失 (c088120 / 43ac097)
- [P2] __try 块内 C++ 对象析构跳过
- [P2] Catmull-Rom 非均匀段距突变 (升 Centripetal)
- [P2] _detect_bridge 无重试 (加 2-3 次指数退避)
- [P2] 增强 Pause (UWorld::IsPaused 内存写入 fallback)
Planning section cleared:
- "Commit D (next major) -- UE 自动探测 (StackOBot 并轨)"
