# Reverse Engineering Agent — Shared Notes

This file is used for inter-agent communication. The RE agent writes game compatibility findings, injection methods, and camera control research here.

## [v0.1.0] Camera Control Methods

### UE5 Released Games
1. **captureAIshi Bridge DLL** — Self-hosted console server injected into game process
   - `ToggleDebugCamera` → free camera mode
   - `SetViewLocation X Y Z` / `SetViewRotation P Y R`
   - Works on most single-player UE4/UE5 games without anti-cheat
   - Includes camera path (Catmull-Rom + SLERP), timestop, HUD toggle, hotsampling
2. **Cheat Engine** — Direct memory write to camera transform
   - Requires finding ViewMatrix offset per game
   - More universal but needs per-game setup
3. **External Memory Driver** — ReadProcessMemory/WriteProcessMemory from outside
   - No DLL injection needed, bypasses most user-mode anti-cheat
   - Requires per-game memory offsets (found via CE)

### Unity Released Games
1. **BepInEx** — Plugin framework for Unity games
   - Custom plugin receives TCP commands for camera control
   - Works on most Unity games (IL2CPP and Mono)
2. **UnityExplorer** — Runtime inspector, can modify camera

## [v0.2.0] Bridge DLL Architecture

Bridge DLL (`3rdparty/bridge/`) replaces external UUU dependency:
- **Injection**: `injector.py` — CreateRemoteThread + LoadLibraryW (same as RenderDoc)
- **GEngine scan**: String xref method (finds `ToggleDebugCamera`/`r.Streaming.PoolSize` in memory, traces xrefs to locate GEngine global)
- **Console exec**: GEngine->Exec() via vtable call with validation
- **Camera path**: Keyframe system with Catmull-Rom position + SLERP rotation, 60Hz tick thread
- **TCP protocol**: Newline-delimited commands on port 9998, compatible with `ue5_console.py`

Anti-cheat research: see `docs/anti_cheat_research.md`

## [v0.1.0] Tested Games
- EagleWalkLJB (UE5 demo): RenderDoc injection OK, console OK, ToggleDebugCamera OK
