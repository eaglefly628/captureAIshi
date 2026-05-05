# Gameplay Video Recording (v0.3.0)

captureAIshi can record continuous gameplay video alongside the per-pose
RGB / Depth / Normal triplets, so AI training data has matched stills,
moving footage, and camera trajectory for the same session.

The video pipeline talks to **OBS Studio** over its WebSocket v5 API.
OBS handles NVENC hardware encoding so the host frame rate is unaffected
while the game runs at 1080p / 60 fps.

---

## Prerequisites

- **OBS Studio 30.x or newer** (older versions use a different request
  vocabulary and are not supported).
- **obs-websocket plugin enabled** (built into OBS 28+; just enable in
  `Tools -> WebSocket Server Settings`).
- **A scene named "Capture"** with a **Game Capture** source whose
  capture mode is `any_fullscreen` or `window` (matched by your game's
  executable). The `setup_obs.py` helper writes this scene for you.

Video recording is **off by default**. Enable it per-session via the
"Video Recording" panel (or `--video` on the CLI).

---

## First-run setup (one click)

1. Open the captureAIshi Web UI.
2. Go to settings panel `Video Recording`.
3. Click **Setup OBS**. This downloads the official OBS installer
   (~150 MiB) from
   <https://github.com/obsproject/obs-studio/releases>, runs it
   silently into `3rdparty/obs-studio/`, writes a default `Capture`
   scene, enables obs-websocket on port 4455, and stores the generated
   password in `configs/obs.json`.
4. Click **Test Connection** to confirm the websocket is reachable.

You can also run the script directly:

```bash
python scripts/setup_obs.py            # detect + install + configure
python scripts/setup_obs.py --check    # exit 0 if everything is ready
```

If you already have OBS installed, point captureAIshi at it via
`obs_exe_path` in `configs/obs.json` instead of running setup.

---

## Outputs

A session with video enabled produces two extra files in
`output/<session>/`:

- `video.mp4` — the recorded gameplay stream (renamed from whatever
  filename OBS chose).
- `video_metadata.json` — schema version 1, see below.

### `video_metadata.json` schema

```json
{
  "schema_version": 1,
  "video_file": "video.mp4",
  "started_at_iso": "2026-04-27T12:00:00+00:00",
  "stopped_at_iso": "2026-04-27T12:00:42.500000+00:00",
  "duration_seconds": 42.5,
  "framerate": 60.0,
  "resolution": {"width": 1920, "height": 1080},
  "codec": "h264",
  "bitrate_kbps": 50000,
  "obs_version": "30.1.2",
  "obs_scene": "Capture",
  "trajectory_alignment": {
    "method": "wall_clock",
    "session_start_offset_seconds": 0.0,
    "pose_timestamps_seconds": [0.0, 1.5, 3.2]
  }
}
```

### Aligning video frames to poses

`pose_timestamps_seconds[i]` is the wall-clock offset (seconds since
`StartRecord`) at which the i-th pose in `trajectory.json` was captured.
For an arbitrary video time `T`, the matching pose index is the largest
`i` with `pose_timestamps_seconds[i] <= T`.

---

## CLI flags

```
--video / --no-video         Enable/disable recording (default: --no-video)
--obs-host HOST              OBS WebSocket host (default 127.0.0.1)
--obs-port PORT              OBS WebSocket port (default 4455)
--obs-password PWD           OBS WebSocket password
--obs-scene NAME             Scene to switch to before recording
--obs-exe-path PATH          obs64.exe path (overrides auto-detect)
--strict-video               Abort the session if OBS fails (default: degrade)
```

---

## Lifecycle

1. `grabber.setup()` launches the game.
2. `driver.connect()` + `driver.enable_debug_camera()` succeed.
3. (Optional) bridge `__hud_toggle` hides the HUD for clean footage.
4. `OBSRecorder.__enter__()` spawns `obs64.exe` if `auto_launch_obs`
   is true, polls port 4455, calls `SetCurrentProgramScene` and
   `SetRecordDirectory`.
5. `OBSRecorder.start(session_name)` sets `FilenameFormatting` and
   calls `StartRecord`.
6. The Web UI drives captures; each `__cam_rdc_capture` records a
   timestamp into `web.state`.
7. On stop: `StopRecord`, rename to `video.mp4`, write metadata,
   restore HUD via bridge, terminate the spawned OBS process.

If `strict_video` is false (default) and OBS is unreachable, the
recorder degrades to a no-op and the rest of the session runs normally.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "OBS WebSocket not reachable on 127.0.0.1:4455" | OBS isn't running, or the websocket server is disabled | Click **Setup OBS** (one-time), then make sure OBS is allowed to launch (Windows firewall, antivirus). |
| "connect failed: ... 4001" | Wrong password | Re-run `python scripts/setup_obs.py` to regenerate the password and persist it to `configs/obs.json`. |
| Video recorded but blank | Game Capture source can't see the game window | Open OBS, edit the `Game Capture` source, set `priority: window` and pick the game's executable manually. |
| `video.mp4` not produced, only an `.mkv` | OBS recording format isn't MP4 | OBS preferences -> Output -> Recording Format -> mp4. (We rename based on extension; mkv works too.) |
| `pose_timestamps_seconds` empty | The trajectory player wasn't started, or video was disabled | Make sure the **Video Recording** toggle is on before pressing Trajectory -> Play. |

---

## Third-party software

OBS Studio is licensed under GPLv2. captureAIshi does **not**
redistribute OBS binaries; `scripts/setup_obs.py` downloads the
unmodified official installer from
<https://github.com/obsproject/obs-studio/releases> at runtime. Source
for OBS is available at <https://github.com/obsproject/obs-studio>.
captureAIshi communicates with OBS over a network socket only, so the
two programs remain separate works (mere aggregation per the GPLv2
FAQ).
