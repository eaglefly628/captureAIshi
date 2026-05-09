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

**Phase 1 (next)**: hook ReShade frame events for capture.
- Register `reshade_present` / `bind_render_targets_and_depth_stencil` events
- Decide capture-output format (match Path A: PNG color + EXR depth + EXR normal)
- Write `grabbers/reshade_grabber.py` to consume the addon's output

**Phase 2**: end-to-end on Hellblade II (the AC game that motivated this).

## Build (planned, Windows)

```powershell
cd 3rdparty/reshade_bridge/src
cmake -B build -G "Visual Studio 17 2022" -A x64
cmake --build build --config Release
# Output: 3rdparty/reshade_bridge/captureAIshi_bridge.addon
```

ReShade SDK headers come from the `3rdparty/unicap` submodule. Init it first:

```powershell
git submodule update --init --recursive 3rdparty/unicap
```

## Frame capture notes (for Phase 1)

unicap's `99-frame_capture` addon already solves color + depth + normal export
for ReShade and is the reference implementation we should adopt wholesale
rather than re-derive. Key facts:

- **Color**: `runtime->capture_screenshot()` (post-UI) or pre-UI hook on
  `bind_render_targets_and_depth_stencil` -> staging texture -> RGBA8 BMP/PNG.
- **Depth + Normal**: handled by the FX shader `shaders/DepthToAddon.fx` in
  unicap, which exposes `DepthToAddon_DepthTex` and `DepthToAddon_NormalTex`
  texture variables; the addon reads them back to EXR.
- **Pre-UI capture**: needs a per-game `FC_PreUISkipCount` survey first
  (unicap's `tools/capture/survey.py`). For our pipeline a fixed-value
  config per game is acceptable since trajectories are scripted.
- **Sidecar protocol**: unicap's addon reads `%TEMP%/unicap/unicap.ini` plus
  per-game-dir txt files for output redirection. Our addon should likely
  use the bridge TCP channel instead of sidecar files (one less moving part)
  but keeping unicap's file protocol as-is is also viable in Phase 1.

Decision pending for Phase 1: do we **embed** unicap's `frame_capture.cpp`
into this addon (single `.addon` per game), or **co-load** it as a sibling
addon (`98-bridge.addon` + `99-frame_capture.addon`)? Co-loading keeps unicap
upstream as a true black-box dependency. Embedding gives one binary to ship.
Defer to start of Phase 1.
