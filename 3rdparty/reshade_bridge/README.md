# reshade_bridge -- Path B injection vehicle

Independent re-implementation of `3rdparty/bridge/` as a ReShade addon DLL.
Same TCP 9998 protocol, same UE5 engine scan, same camera/HUD/path control.
Only the injection vehicle differs.

| Aspect | Path A (current) | Path B (this directory) |
|--------|------------------|-------------------------|
| Loader | `renderdoccmd inject captureAIshi_bridge.dll` | `dxgi.dll` proxy + `*.addon` scan |
| AC trigger | LoadLibraryW / CreateRemoteThread style | None (proxy DLL placed next to game exe) |
| Output binary | `captureAIshi_bridge.dll` | `captureAIshi_bridge.addon` |
| Source files | `3rdparty/bridge/src/` | `3rdparty/reshade_bridge/src/` (copy) |
| Driver protocol | TCP 9998 bridge protocol | Same |
| Frame capture | renderdoccmd .rdc -> RGB+Depth+Normal | ReShade addon -> BMP + EXR (Phase 1) |

Path A and Path B are **never both active** in the same game session. The UI
dropdown (`injection_mode`) selects one. Driver and grabber pick a sibling
implementation per mode.

## Why duplicate the source?

Per project decision: full code independence. A bug fix in Path A's
`pattern_scan.h` does NOT propagate automatically to Path B -- both must be
edited. The trade is: Path A is battle-tested on Batman: Arkham Knight and
must not regress while Path B is being brought up; sharing headers risked
that.

When Path B becomes the primary vehicle (because it works on AC games where
Path A cannot inject), the workflow inverts: bug fixes land in Path B first
and back-port to Path A.

## Status

**Phase 0 (this commit)**: scaffold only.
- 4 source files copied verbatim from `3rdparty/bridge/src/`
- `bridge.cpp` modified in two places only:
  1. Added `#include <reshade.hpp>`
  2. `DllMain` now calls `reshade::register_addon` / `unregister_addon`
     alongside the existing `startup` thread
- `NAME` / `DESCRIPTION` exports added so ReShade lists the addon
- CMakeLists builds `captureAIshi_bridge.addon`
- **Not yet built / tested.** Compilation against ReShade SDK pending Windows host.

**Phase 0.5 (this commit)**: vendor unicap source into our tree.
- ReShade core source -> `3rdparty/reshade/`
- Addon SDK headers + `frame_capture.cpp` + deps + shaders -> `3rdparty/reshade_bridge/{sdk,frame_capture,deps,shaders}/`
- `3rdparty/unicap` submodule dropped; `.gitmodules` removed
- See "Provenance" + "Layout" sections below

**Phase 1 (next)**: hook ReShade frame events for capture.
- Register `reshade_present` / `bind_render_targets_and_depth_stencil` events
- Decide: embed `frame_capture.cpp` into bridge addon vs co-load as sibling
- Write `grabbers/reshade_grabber.py` to consume addon output

**Phase 2**: end-to-end on Hellblade II (the AC game that motivated this).

## Layout

```
3rdparty/reshade_bridge/
├── README.md              this file
├── src/                   Path B bridge port (copy of 3rdparty/bridge/ + reshade hooks)
│   ├── bridge.cpp
│   ├── pattern_scan.h
│   ├── ue5_engine.h
│   ├── camera_path.h
│   └── CMakeLists.txt
├── sdk/                   ReShade addon SDK headers (vendored, edit in place)
│   ├── reshade.hpp
│   ├── reshade_api.hpp
│   ├── reshade_events.hpp
│   └── ...
├── deps/                  header-only deps for frame_capture
│   ├── imgui/             ReShade overlay widgets (used by frame_capture overlay)
│   ├── stb/               stb_image / stb_image_write / stb_image_resize
│   └── tinyexr/           EXR encoder for depth/normal export
├── frame_capture/         ReShade frame-capture addon (vendored from unicap)
│   ├── frame_capture.cpp  ~1350 LOC; color BMP/PNG + depth/normal EXR
│   ├── FormatEnum.h
│   └── ...
└── shaders/               FX shaders the addon reads back
    ├── DepthToAddon.fx    exports DepthToAddon_DepthTex / _NormalTex
    ├── BackBufferExport.fx
    ├── CaptureStatus.fx
    └── ReShade.fxh
```

The sibling `3rdparty/reshade/` directory holds the **ReShade core source**
(60 MB, builds `dxgi.dll` proxy via MSBuild). Also vendored, also edit in
place when needed. Pin: 6.7.3.16 UNOFFICIAL (originally from unicap repo).

## Provenance

All vendored code originated in https://github.com/raptoravis/unicap @ commit
`424113d` (cloned briefly as a submodule, then absorbed). Per project
decision (2026-05-09): unicap is treated as "ours" -- there is no upstream
sync workflow, no submodule, no compatibility constraint. Edit any file
freely. If unicap upstream changes, that is a manual cherry-pick choice.

What was inherited:
- Full ReShade core source         -> `3rdparty/reshade/` (60 MB)
- ReShade addon SDK headers        -> `3rdparty/reshade_bridge/sdk/`
- Frame-capture addon source       -> `3rdparty/reshade_bridge/frame_capture/`
- Header-only addon deps           -> `3rdparty/reshade_bridge/deps/{imgui,stb,tinyexr}`
- DepthToAddon / BackBufferExport / CaptureStatus shaders -> `shaders/`

What was deliberately NOT inherited (we have our own):
- unicap `main.py` (Python CLI orchestrator)
- unicap `tools/capture/` (survey + capture loop) -- the protocol bits we
  need will land in `grabbers/reshade_grabber.py` when Phase 1 wires Python
  to the addon. Survey-skip-count auto-detection is one such function.
- unicap `profiles/`, `unicap_gui/`, `auto_play/` etc. -- captureAIshi has
  its own UI / profile / driver layer.

## Build (Windows)

```powershell
# Path B bridge addon (TCP + GEngine + camera control, no frame capture yet)
cd 3rdparty\reshade_bridge\src
cmake -B build -G "Visual Studio 17 2022" -A x64
cmake --build build --config Release
# -> 3rdparty\reshade_bridge\captureAIshi_bridge.addon

# ReShade core (dxgi.dll proxy that loads the .addon)
# Driven by MSBuild against ReShade.sln; see 3rdparty\reshade\README.md
```

A top-level CMakeLists wiring all pieces (bridge addon + frame_capture addon
+ ReShade core + shader copy) lands in Phase 1 along with the actual
deployment script (which `dxgi.dll` and `*.addon` files go into the game
directory).

## Phase 1 plan (next session)

1. Wire frame-capture events in `bridge.cpp` (or co-load `frame_capture.cpp`
   as a sibling `.addon` -- decision below).
2. **Embed vs co-load decision**: lean toward **embed** so the entire Path B
   payload is one `.addon` file plus shaders. Co-loading was preferred when
   we treated unicap as upstream black-box; now that it is ours, one binary
   is simpler to ship. Confirm before Phase 1 work starts.
3. Adapt sidecar-file protocol to bridge TCP channel where it makes sense
   (output dir redirection -> single TCP command; per-frame state ping
   stays as `%TEMP%/captureAIshi/` files for live in-game overlay).
4. Write `grabbers/reshade_grabber.py` to consume addon output (BMP/PNG +
   EXR pairs, same downstream contract as renderdoc grabber).
5. Add UI dropdown `injection_mode = renderdoc | reshade`; main.py picks
   grabber + injection script per mode.

## Frame-capture reference (Phase 1 reading)

| Question | Where to look |
|---|---|
| How does color export work? | `frame_capture/frame_capture.cpp` -- `runtime->capture_screenshot()` (post-UI) or `on_bind_rts_dsv` hook (pre-UI) |
| How are Depth + Normal exported? | `shaders/DepthToAddon.fx` exposes `DepthToAddon_{Depth,Normal}Tex`; addon reads them back to EXR |
| Pre-UI skip count auto-detect | unicap `tools/capture/survey.py` (NOT vendored; port to Python in Phase 1) |
| Sidecar files (Python <-> addon) | `frame_capture.cpp` reads `fc_output_dir.txt` / `fc_skip_count.txt` / `fc_state.txt` from game exe dir each `on_reshade_present` |
