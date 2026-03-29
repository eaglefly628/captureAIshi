# Universal Unreal Unlocker (UUU) — Third-Party Setup

UUU enables console commands in packaged UE4/UE5 games. captureAIshi's
`ue5` driver uses it to control the camera via TCP.

## Setup

1. Download UUU from: https://framedsc.com/GeneralGuides/universal_ue4_unlocker.htm
2. Place the UUU executable and DLLs in this directory (`3rdparty/uuu/`)
3. Expected files:
   ```
   3rdparty/uuu/
   ├── UuuClient.exe        (or UUU.exe depending on version)
   ├── UuuClient.dll
   └── ...
   ```

## Usage with captureAIshi

1. Launch your UE5 game (via renderdoccmd or directly)
2. Run UUU and inject into the game process
3. UUU opens a TCP console on port 1985 (or 9998 depending on config)
4. Set `--driver ue5 --driver-port <port>` in captureAIshi
5. The pipeline connects and sends:
   - `ToggleDebugCamera` — enter free camera mode
   - `SetViewLocation X Y Z` — move camera
   - `SetViewRotation P Y R` — rotate camera

## Fallback

If UUU is not running or the port is not open, captureAIshi automatically
falls back to manual mode: captures proceed at the current camera position
without automated movement.

## Notes

- UUU only works with single-player games
- Some games with custom anti-cheat may block injection
- The TCP port must be accessible on localhost (127.0.0.1)
- UUU binaries are NOT checked into git (add them locally)
