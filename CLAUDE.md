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

**All work targets `claudeMainBranch`.** Development happens on the
sandbox-assigned `claude/write-handoff-docs-XXXXX` branch (per-session,
the platform refuses direct push to `claudeMainBranch` with HTTP 403).
A GitHub Action auto-forwards every push on `claude/**` to
`claudeMainBranch` within ~10 seconds.

### How the auto-merge works

```
session work
   │
   ▼  git push origin HEAD:claude/write-handoff-docs-XXXXX
sandbox proxy → push succeeds
   │
   ▼  GitHub receives push on claude/** branch
.github/workflows/auto-merge-claude.yml triggers (runs on GitHub side)
   │
   ▼  workflow uses GITHUB_TOKEN:
         git checkout claudeMainBranch
         git merge --ff-only origin/claude/write-handoff-docs-XXXXX
         (falls back to no-ff merge commit if histories diverged)
         git push origin claudeMainBranch
   │
   ▼  ~10s later
claudeMainBranch tip == claude/write-handoff-docs-XXXXX tip
```

**Net effect for new sessions**: just `git push` to whatever branch the
sandbox assigned. Code lands on `claudeMainBranch` automatically. No
manual PR. No user intervention. Workflow file lives at
`.github/workflows/auto-merge-claude.yml` (committed in `2dd243a`).

### Pre-reqs (one-time setup; already done)

1. GitHub default branch = `claudeMainBranch`
   (Settings → General → Default branch)
2. No branch protection rule blocking `GITHUB_TOKEN` from pushing to
   `claudeMainBranch` (Settings → Branches)
3. `.github/workflows/auto-merge-claude.yml` exists on `claudeMainBranch`

### Caveats

- The workflow trusts `claude/**` pushes blindly. If you push broken code,
  `claudeMainBranch` gets broken code ~10s later. Use the auto-merge
  carefully -- think before pushing experimental commits.
- The first push of any session goes through, but if the workflow fails
  (rare -- GitHub Actions outage, branch protection changes, etc.) the
  fallback is a manual PR: open
  `https://github.com/eaglefly628/captureAIshi/pull/new/<branch>`
  and merge by hand.
- "All work goes to claudeMainBranch" is the **logical** policy. The
  **mechanical** path is via the assigned branch + workflow.

### Per-session quickstart

On new session start:
```bash
git checkout claudeMainBranch && git pull origin claudeMainBranch
# work
git push -u origin HEAD:claude/write-handoff-docs-XXXXX
# done -- claudeMainBranch updates itself within ~10s
```

If sandbox lets you push directly to claudeMainBranch (no 403), do that
and skip the assigned-branch indirection -- the workflow no-ops on
already-merged branches.
