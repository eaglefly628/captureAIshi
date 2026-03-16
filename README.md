# captureAIshi

Cross-engine game capture framework for released games. Captures RGB + Depth from published UE5/Unity games without source code access.

## Architecture

Three-layer design:

- **core/** — Pure Python path generation (snake path, cone rotation, tangent smoothing). Engine-agnostic.
- **drivers/** — Camera control adapters: UE5 console injection, Unity BepInEx mod socket, Cheat Engine memory write, manual mode.
- **grabbers/** — Frame capture: RenderDoc replay API for RGB+Depth, screenshot fallback.

## Quick Start

```bash
pip install -r requirements.txt

# Dry run - generate poses without controlling any game
python main.py --dry-run --driver manual --output-dir ./output

# With RenderDoc + UE5
python main.py --driver ue5 --grabber renderdoc --output-dir ./output

# With Unity socket driver
python main.py --driver unity --grabber renderdoc --unity-host 127.0.0.1 --unity-port 9999
```

## Camera Drivers

| Driver | Engine | Method |
|--------|--------|--------|
| `ue5` | UE5 | Console command injection via TCP (requires UUU) |
| `unity` | Unity | BepInEx plugin TCP socket |
| `cheatengine` | Any | Memory write via Cheat Engine |
| `manual` | Any | Print pose, wait for user |

## Unity Companion Plugin

See `unity_companion/CameraCapturePlugin.cs` — a BepInEx plugin that listens on a TCP socket for JSON pose commands and applies them to `Camera.main`.
