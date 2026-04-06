# captureAIshi -- Development Guidelines

## Context Awareness

After each response, do two things:

1. Append a one-line context estimate at the end of your response:
   ```
   Context: ~XX%
   ```
2. Update your row in `agents/STATUS.md` with your current percentage and timestamp. This file is the shared dashboard the lead programmer reads.

Estimate based on: how many files you've read, how much code you've generated, how many turns have passed. When approaching ~70%, proactively warn the lead programmer. At ~85%, wrap up, push, write CL, suggest new session.

## Auto-Start Rule

When a new session starts, IMMEDIATELY:
1. `git checkout claudeMainBranch && git pull origin claudeMainBranch`
2. Read your own SHARED.md for uncompleted TODO items
3. Start working on the highest priority (P0 > P1 > P2) incomplete task
4. Do NOT wait for instructions -- begin autonomously

## Version

**Current: v0.2.0** -- See `.claude/rules/versioning.md` for full changelog and rules.

## Architecture

Pipeline for capturing RGB + Depth + Normal from published games:

1. **Core** (`core/`) -- Pure Python path generation (waypoints, snake path, cone rotation, tangent smoothing). Engine-agnostic.
2. **Drivers** (`drivers/`) -- Camera control adapters. Each driver connects to a game via its specific protocol (UE5 console TCP, Unity BepInEx socket, Cheat Engine memory, manual).
3. **Grabbers** (`grabbers/`) -- Frame capture. RenderDoc replay API for RGB+Depth+Normal, screenshot fallback.
4. **Web UI** (`web_ui.py` + `web/templates/`) -- Flask + pywebview desktop GUI. Capture controls, log viewer, image gallery, 3D waypoint visualizer.
5. **Utils** (`utils/`) -- Shared utilities (coordinate system conversions, etc.).

### Startup order

```
grabber.setup()          # 1. Launch game via renderdoccmd
  +- _wait_for_game_ready()  # 2. Poll until game port is open
driver.__enter__()       # 3. Connect to game's control socket
capture_loop()           # 4. Iterate poses
driver.__exit__()        # 5. Disconnect
grabber.teardown()       # 6. Cleanup
```

The grabber MUST launch and confirm the game is running BEFORE the driver attempts to connect. Enforced in `main.py` Step 6/7.

### Error handling

- Validate at system boundaries (user config, external tool output, network responses).
- Trust internal code paths -- don't add defensive checks for states that can't happen.
- Log actionable information: what failed, what was expected, what to try next.
- If renderdoccmd exits early, log the return code and stop -- don't retry blindly.

## .claude/ Structure

```
.claude/
+-- settings.json              Permissions + config
+-- rules/                     Modular instruction files
|   +-- code-style.md          Python conventions, file conventions
|   +-- cpp-rules.md           C++ ASCII/MSVC rules
|   +-- no-sleep.md            No time-based async readiness
|   +-- edit-discipline.md     Edit tool safety rules
|   +-- versioning.md          Version bump + CL rules + changelog
|   +-- peer-review.md         Competitive review + agent names
+-- commands/                  Slash commands
|   +-- review.md              /project:review
|   +-- status.md              /project:status
+-- agents/                    Agent role definitions
    +-- ui.md                  xiaoyu (web_ui.py, web/templates/)
    +-- rendering.md           xiaoxuan (renderdoccmd, grabbers/)
    +-- reversing.md           xiaoni (drivers/, 3rdparty/bridge/)
```

Inter-agent communication stays in `agents/*/SHARED.md`. Context dashboard at `agents/STATUS.md`.

## Branch Policy

**All work MUST be committed and pushed directly to `claudeMainBranch`.** Do NOT create feature branches, do NOT push to `claude/xxx` auto-generated branches. If the platform assigns you a different branch, switch to `claudeMainBranch` before doing any work:

```bash
git checkout claudeMainBranch
git pull origin claudeMainBranch
```

GitHub default branch must be set to `claudeMainBranch` (Settings -> General -> Default branch).
