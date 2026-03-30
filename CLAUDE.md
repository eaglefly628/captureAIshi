# captureAIshi — Development Guidelines

## Context Awareness

After each response, append a one-line context estimate at the end:

```
📊 Context: ~XX%
```

Estimate based on: how many files you've read, how much code you've generated, how many turns have passed. This is a rough self-assessment, not exact. When approaching ~70%, proactively warn the lead programmer that a fresh session may be needed soon. At ~85%, wrap up current work, push, write CL, and suggest starting a new session.

## Version

**Current: v0.2.0**

### Changelog

| Version | Date       | Summary |
|---------|------------|---------|
| v0.1.0  | 2026-03-28 | End-to-end pipeline: renderdoccmd launch, trigger capture, export RGB+Depth PNG |
| v0.2.0  | 2026-03-29 | trajectory.json output, normal buffer export, camera intrinsics (FOV/aspect), UI lightbox/progress/gallery/3D visualizer |
| v0.2.0  | 2026-03-30 | Bridge console server embedded in renderdoc.dll (GEngine auto-scan, camera path, timestop, HUD toggle, hotsampling). External memory driver for anti-cheat games. Removed UUU dependency. |

### Versioning Rules

- **Bump minor** (v0.X.0) for new features or API/schema changes that other agents need to know about.
- **Bump patch** (v0.X.Y) for bug fixes or internal refactors that don't affect inter-agent contracts.
- Lead programmer bumps the version in this file. Agents do NOT bump it themselves.
- **All SHARED.md updates MUST include a version tag** in the section header, e.g. `## [v0.2.0] Feature Name`. This is how agents reference specific changes.
- When an agent needs to tell another agent about a change, reference the version: "see rendering SHARED.md [v0.2.0]" — not dates or commit hashes.
- Agents reading SHARED.md should check the version tag to know if they've already consumed that update.
- **Every push MUST include a changelog entry** in the agent's own SHARED.md. A push without a corresponding CL entry is an incomplete submission. Format: `### [v0.X.Y] <sha> — <agent name>` with bullet summary. No exceptions.

### Agent Names (canonical)

| Agent | Name | Domain |
|-------|------|--------|
| UI | 小由 | web_ui.py, web/templates/ |
| Rendering | 小萱 | renderdoccmd, grabbers/ |
| Reversing | 小逆 | drivers/, 3rdparty/bridge/ |

Use these exact names in all CL entries, TODO attributions, and peer review comments. No variations (not 小萱萱, not 小逆逆, etc.).

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

### Edit tool discipline

When using the Edit tool (old_string → new_string replacement):
- **Minimize the replacement scope.** Only include the lines you're actually changing. Do NOT select a 20-line block just to change 2 lines — you WILL accidentally drop surrounding logic.
- **If you must replace a large block**, read it line by line and verify every line from `old_string` appears in `new_string` (unless intentionally removing it).
- **Prefer multiple small edits** over one big edit. Safer and easier to review.

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
