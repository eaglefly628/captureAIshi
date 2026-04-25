# Architecture Reference

On-demand reference — read when working on pipeline structure, startup ordering, or `.claude/` layout.

## Pipeline

1. **Core** (`core/`) — Pure Python path generation (waypoints, snake path, cone rotation, tangent smoothing). Engine-agnostic.
2. **Drivers** (`drivers/`) — Camera control adapters. Each driver connects to a game via its specific protocol (UE5 console TCP, Unity BepInEx socket, Cheat Engine memory, manual).
3. **Grabbers** (`grabbers/`) — Frame capture. RenderDoc replay API for RGB+Depth+Normal, screenshot fallback.
4. **Web UI** (`web_ui.py` + `web/templates/`) — Flask + pywebview desktop GUI. Capture controls, log viewer, image gallery, 3D waypoint visualizer.
5. **Utils** (`utils/`) — Shared utilities (coordinate system conversions, etc.).

## Startup order

```
grabber.setup()          # 1. Launch game via renderdoccmd
  +- _wait_for_game_ready()  # 2. Poll until game port is open
driver.__enter__()       # 3. Connect to game's control socket
capture_loop()           # 4. Iterate poses
driver.__exit__()        # 5. Disconnect
grabber.teardown()       # 6. Cleanup
```

The grabber MUST launch and confirm the game is running BEFORE the driver attempts to connect. Enforced in `main.py` Step 6/7.

## Error handling

- Validate at system boundaries (user config, external tool output, network responses).
- Trust internal code paths — don't add defensive checks for states that can't happen.
- Log actionable information: what failed, what was expected, what to try next.
- If renderdoccmd exits early, log the return code and stop — don't retry blindly.

## .claude/ Structure

```
.claude/
+-- settings.json              Permissions + config
+-- rules/                     Modular instruction files
|   +-- code-style.md          Python conventions, file conventions
|   +-- cpp-rules.md           C++ ASCII/MSVC rules
|   +-- no-sleep.md            No time-based async readiness
|   +-- edit-discipline.md     Edit tool safety rules
|   +-- versioning.md          Version bump + CL rules
|   +-- peer-review.md         Competitive review
|   +-- coding-discipline.md   Think/Simplicity/Surgical/Goal-driven rules
|   +-- architecture.md        This file (on-demand)
+-- commands/                  Slash commands
+-- agents/                    Agent role definitions
    +-- ui.md                  xiaoyu (web_ui.py, web/templates/)
    +-- rendering.md           xiaoxuan (renderdoccmd, grabbers/)
    +-- reversing.md           xiaoni (drivers/, 3rdparty/bridge/)
```

Inter-agent communication stays in `agents/*/SHARED.md`. Context dashboard at `agents/STATUS.md`.

## Canonical Agent Names

| Role | Name | Domain |
|------|------|--------|
| UI | xiaoyu (小由) | `web_ui.py`, `web/templates/` |
| Rendering | xiaoxuan (小萱) | `renderdoccmd`, `grabbers/` |
| Reversing | xiaoni (小逆) | `drivers/`, `3rdparty/bridge/` |

Use these exact names in CL entries, TODO attributions, and peer review comments.
