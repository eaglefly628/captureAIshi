# captureAIshi -- Development Guidelines

## Context Awareness

After each response, append `Context: ~XX%` and update your row in `agents/STATUS.md` (percentage + timestamp). Warn proactively at ~85%; keep working until compression or explicit stop.

## Auto-Start Rule

On new session, IMMEDIATELY:
1. `git checkout claudeMainBranch && git pull origin claudeMainBranch`
2. Read your own `agents/<role>/SHARED.md` for uncompleted TODO items
3. Start the highest priority (P0 > P1 > P2) incomplete task autonomously

## Notifications

After finishing a TODO / pushing code / producing a document, call `notify("title", "msg")` or `notify_file("title", "path")` from `utils.feishu_notify`.

## Version

**Current: v0.3.0** — see `.claude/rules/versioning.md` for rules, `CHANGELOG.md` for history.

## Architecture

Pipeline for capturing RGB + Depth + Normal from published games:

1. **Core** (`core/`) — Pure Python path generation (waypoints, snake path, cone rotation, tangent smoothing). Engine-agnostic.
2. **Drivers** (`drivers/`) — Camera control adapters. Each driver connects to a game via its specific protocol (UE5 console TCP, Unity BepInEx socket, Cheat Engine memory, manual).
3. **Grabbers** (`grabbers/`) — Frame capture. RenderDoc replay API for RGB+Depth+Normal, screenshot fallback.
4. **Recorders** (`recorders/`) — Optional gameplay video capture. `OBSRecorder` drives OBS Studio over WebSocket v5; `NullRecorder` is the no-op fallback when video is disabled. Output lands as `video.mp4` + `video_metadata.json` (with pose timestamps for trajectory alignment) next to `trajectory.json`.
5. **Web UI** (`web_ui.py` + `web/templates/`) — Flask + pywebview desktop GUI. Capture controls, log viewer, image gallery, 3D waypoint visualizer.
6. **Utils** (`utils/`) — Shared utilities (coordinate system conversions, etc.).

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
|   +-- versioning.md          Version bump + CL rules + changelog
|   +-- peer-review.md         Competitive review + agent names
|   +-- coding-discipline.md   Think/Simplicity/Surgical/Goal-driven rules
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

**All work MUST be committed and pushed directly to `claudeMainBranch`.** Do NOT create feature branches or push to auto-generated `claude/xxx` branches. If the platform assigns a different branch, switch first:

```bash
git checkout claudeMainBranch && git pull origin claudeMainBranch
```

GitHub default branch must be `claudeMainBranch` (Settings → General → Default branch).
