# captureAIshi Code Review Report

**Date**: 2026-03-19
**Tests**: 25/25 passing
**Overall**: Architecture clean, ready for use with some issues to address

---

## Project Structure

```
captureAIshi/
├── main.py                  # CLI entry, argparse + capture loop
├── gui.py                   # Tkinter desktop GUI (dark theme)
├── web_ui.py                # Flask Web UI
├── setup.py                 # Package config
├── core/
│   ├── waypoint.py          # CameraPose, Waypoint, BoundingVolume
│   ├── snake_path.py        # Snake + grid path generation
│   ├── cone_rotation.py     # Cone multi-angle sampling
│   └── tangent_smoothing.py # Catmull-Rom spline smoothing
├── drivers/
│   ├── base.py              # CameraDriver ABC (context manager)
│   ├── ue5_console.py       # UE5 TCP console driver
│   ├── unity_socket.py      # Unity BepInEx JSON socket driver
│   ├── cheat_engine.py      # CE Lua socket / shared file driver
│   └── manual.py            # Manual confirmation driver (testing)
├── grabbers/
│   ├── base.py              # FrameGrabber ABC + save_frame
│   ├── renderdoc_grabber.py # RenderDoc replay API capture
│   └── screenshot_grabber.py# PIL/mss screenshot + ReShade depth
├── ui_hiders/
│   ├── base.py              # UIHider ABC (chain of responsibility)
│   ├── console_hider.py     # TCP console command UI hiding
│   ├── renderdoc_hider.py   # RenderDoc draw call filtering
│   ├── noop_hider.py        # No-op fallback
│   └── chain.py             # Auto-build fallback chain
├── utils/
│   └── coords.py            # Pipeline <-> UE5 <-> Unity coord conversion
├── web/templates/
│   └── index.html           # Web UI frontend
└── tests/                   # 25 tests, all passing
```

---

## Strengths

- Clean modular architecture: drivers/grabbers/ui_hiders are all pluggable
- UI hider uses chain of responsibility pattern (console -> renderdoc -> noop)
- Coordinate conversions have complete roundtrip tests
- Three UI options: CLI / Tkinter GUI / Flask Web
- CameraDriver supports context manager (`with driver:`)
- Good logging throughout
- Proper abstract base classes with inheritance

---

## Issues Found

### Critical

#### 1. RenderDoc `trigger_capture()` is a stub
**File**: `grabbers/renderdoc_grabber.py:82-92`

`trigger_capture()` does not actually trigger a frame capture. It returns an expected file path without using the RenderDoc API or keyboard simulation. The entire RenderDoc capture pipeline is non-functional.

```python
def trigger_capture(self) -> Optional[Path]:
    self._capture_count += 1
    rdc_path = self.capture_dir / f"frame_{self._capture_count:06d}.rdc"
    # In practice, this would use RenderDoc's API or send a capture key
    # For now, return the expected path
    return rdc_path  # <-- DOES NOT ACTUALLY TRIGGER
```

#### 2. RenderDoc UI Hider not integrated into capture loop
**File**: `ui_hiders/renderdoc_hider.py`

`RenderDocUIHider.hide()` requires `set_replay_context(controller, rd)` to be called first, but `main.py:159` calls `ui_hider.hide()` before any replay context exists. The RenderDoc hider should be invoked per-frame during replay, not once before the capture loop.

#### 3. Missing Flask dependency
**File**: `setup.py`, `requirements.txt`

`web_ui.py` imports Flask but it's not listed in `install_requires` or `requirements.txt`.

### Moderate

#### 4. UE5 rotation conversion is a no-op
**File**: `utils/coords.py:31-39`

`pipeline_to_ue5_rotation()` returns the input unchanged. The docstring acknowledges different axis mappings between Pipeline and UE5, but the implementation does nothing. Tests pass only because they're roundtrip tests.

```python
def pipeline_to_ue5_rotation(rot: np.ndarray) -> np.ndarray:
    pitch, yaw, roll = rot
    return np.array([pitch, yaw, roll])  # <-- SAME VALUES
```

#### 5. Screenshot grabber returns BGR, not RGB
**File**: `grabbers/screenshot_grabber.py:84`

When using `mss`, the captured image is BGRA. `arr[:, :, :3]` produces BGR. The comment says "handled by caller" but no caller does the conversion.

#### 6. GUI Stop button does not work
**File**: `gui.py:625-628`

`_stop_capture()` sets `_stop_event` but `main.py`'s capture loop never checks this event. The capture cannot be interrupted.

#### 7. ConsoleUIHider creates new socket per call
**File**: `ui_hiders/console_hider.py:48-61`

Each `_send_commands()` call creates a new TCP connection and closes it. If the driver already holds a connection, it should be reused.

### Minor

#### 8. Missing optional dependency `mss`
Used as fallback in `screenshot_grabber.py` but not in requirements.

#### 9. No tests for drivers, grabbers, or main orchestration
Test coverage only covers core logic (path gen, cone rotation, coords, ui hider chain). No integration tests.

#### 10. Web UI has no input validation or CSRF protection
`web_ui.py` accepts arbitrary JSON without sanitization.

---

## What Works Today

| Feature | Status |
|---------|--------|
| `--dry-run` mode (generate poses.json) | Ready |
| `--driver manual` (print pose, wait for Enter) | Ready |
| `--grabber screenshot` (system screenshot) | Ready (Windows PIL, Linux needs mss) |
| `python gui.py` (Tkinter GUI) | Ready |
| `python web_ui.py` (Flask Web UI) | Ready (needs `pip install flask`) |
| All 25 unit tests | Passing |

## What Needs Work Before Real Use

| Feature | Blocker |
|---------|---------|
| UE5 driver | Needs UUU installed + rotation fix |
| Unity driver | Needs BepInEx + companion plugin DLL (not provided) |
| RenderDoc grabber | `trigger_capture()` is stub |
| RenderDoc UI hider | Not integrated into capture loop |
| Stop capture mid-run | Stop event not checked in loop |

---

## Recommended Fix Priority

1. Complete `renderdoc_grabber.py` trigger_capture implementation
2. Fix UE5 rotation conversion in `coords.py`
3. Add Flask/mss to `requirements.txt` and `setup.py`
4. Integrate RenderDoc UI hider into per-frame replay
5. Fix BGR -> RGB in screenshot grabber
6. Wire stop event into capture loop
7. Add driver/grabber tests
