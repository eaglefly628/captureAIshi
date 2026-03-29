# captureAIshi — Development Guidelines

## Architecture

Pipeline for capturing RGB + Depth + Normal from published games:

1. **Core** (`core/`) — Pure Python path generation (waypoints, snake path, cone rotation, tangent smoothing). Engine-agnostic.
2. **Drivers** (`drivers/`) — Camera control adapters. Each driver connects to a game via its specific protocol (UE5 console TCP, Unity BepInEx socket, Cheat Engine memory, manual).
3. **Grabbers** (`grabbers/`) — Frame capture. RenderDoc replay API for RGB+Depth+Normal, screenshot fallback.
4. **Web UI** (`web_ui.py` + `web/templates/`) — Flask + pywebview desktop GUI. Capture controls, log viewer, image gallery, 3D waypoint visualizer.
5. **Utils** (`utils/`) — Shared utilities (coordinate system conversions, etc.).

## Design Principles

### No time-based assumptions for async readiness

**Never use `sleep(N)` to wait for an external process or service to become ready.** Always use a deterministic signal:

- **Process readiness**: Poll for a concrete indicator (TCP port open, file appears on disk, process stdout contains ready message).
- **Game startup**: `_wait_for_game_ready()` polls the game's control port. Only after the port responds does the pipeline proceed to driver connection.
- **Capture completion**: Check for `.rdc` file existence on disk, don't assume a fixed delay is enough.
- **Timeouts are safety nets**, not expected flow. Log a warning when a timeout is hit — it means something unexpected happened.

### Startup order matters

The pipeline has strict ordering dependencies:

```
grabber.setup()          # 1. Launch game via renderdoccmd
  └─ _wait_for_game_ready()  # 2. Poll until game port is open
driver.__enter__()       # 3. Connect to game's control socket
capture_loop()           # 4. Iterate poses
driver.__exit__()        # 5. Disconnect
grabber.teardown()       # 6. Cleanup
```

The grabber MUST launch and confirm the game is running BEFORE the driver attempts to connect. This is enforced in `main.py` Step 6/7.

### renderdoccmd CLI reference

Source: `renderdoc/renderdoccmd/renderdoccmd.cpp`

Syntax: `renderdoccmd capture [options] <executable> [game args]`

**All `--opt-*` flags MUST come before the executable path.** Game arguments go after.

Valid flags:
- `--opt-disallow-vsync`
- `--opt-disallow-fullscreen`
- `--opt-api-validation`
- `--opt-api-validation-unmute`
- `--opt-collect-callstacks`
- `--opt-collect-callstacks-only-actions`
- `--opt-ref-all-resources`
- `--opt-save-all-initials`
- `--opt-capture-all-cmd-lists`
- `--opt-hook-children` — Required for UE5 packaged games (launcher spawns child renderer)
- `--opt-debug-output-mute`
- `--opt-soft-memory-limit <MB>`
- `--capture-file <path>` — Base path for .rdc files
- `--wait-for-exit` — Keep renderdoccmd alive until game exits

### Error handling philosophy

- Validate at system boundaries (user config, external tool output, network responses).
- Trust internal code paths — don't add defensive checks for states that can't happen.
- Log actionable information: what failed, what was expected, what to try next.
- If renderdoccmd exits early, log the return code and stop — don't retry blindly.

### C/C++ code rules

- **ASCII only in source files.** No Unicode characters (arrows, em-dashes, special symbols) in `.cpp`/`.h` files. The MSVC build uses `/W4 /WX` (warnings as errors) and code page 936 triggers C4819 for non-ASCII. Use `->` not `→`, `~` not `≈`, `--` not `—`.
- All strings and comments must be plain ASCII.

## File conventions

- Python 3.11+, formatted with Black
- All paths use `pathlib.Path` internally
- Coordinates: pipeline uses Y-up right-handed (meters). Convert at driver boundary.
- Config files stored in `./configs/`, output in `./output/<session>/`
- `.gitignore` should exclude: `__pycache__/`, `*.pyc`, `.venv/`, `renderdoc/`, `configs/`, `output/`, `captures/`

## Testing

```bash
python -m pytest tests/           # Unit tests
python main.py --dry-run --driver manual  # Verify path generation + CLI
```
