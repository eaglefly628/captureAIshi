# captureAIshi Bridge — Anti-Cheat & Game Protection Research

**Version:** v0.2.0
**Date:** 2026-03-29
**Author:** captureAIshi team

---

## 1. Executive Summary

Our bridge DLL uses the same injection technique (CreateRemoteThread + LoadLibraryW)
as UUU and IGCS. After researching how these established tools handle game
protections, the conclusion is clear:

**UUU/IGCS do NOT bypass anti-cheat. They explicitly refuse to support
anti-cheat-protected games.**

Our strategy should follow the same principle: **target single-player games
without kernel-level anti-cheat.** This covers 90%+ of the games we care about
for training data capture.

---

## 2. Protection Systems Classification

### 2.1 DRM (Digital Rights Management) — Usually Not a Problem

| System | Blocks injection? | Impact on us | Notes |
|--------|-------------------|-------------|-------|
| **Steam Stub** | No | None | Basic wrapper, does not interfere with runtime injection |
| **Denuvo** | Sometimes | Low | Code virtualization + integrity checks. Blocks EXE patching but usually does NOT block runtime DLL injection. UUU works with most Denuvo games |
| **Epic Online Services** | No | None | Distribution platform, not protection |

### 2.2 Anti-Tamper — Game-Specific

| System | Blocks injection? | Impact on us | Workaround |
|--------|-------------------|-------------|------------|
| **Capcom Anti-Tamper** | Yes (crash) | High | REFramework by Praydog disables it. Required for RE4 Remake, Dragon's Dogma 2, RE Village, RE9 |
| **Arxan** | Yes | High | No known general workaround. Blocks modpatch and DLL injection |
| **Custom integrity checks** | Varies | Medium | Per-game analysis needed |

### 2.3 Anti-Cheat — Kernel Level (Hard Block)

| System | Blocks injection? | Blocks memory R/W? | Impact | Games |
|--------|-------------------|--------------------|--------|-------|
| **EAC (Easy Anti-Cheat)** | Yes | Partial | **HARD BLOCK** | Fortnite, Elden Ring (online), many UE5 MP games |
| **BattlEye** | Yes | Partial | **HARD BLOCK** | PUBG, DayZ, Rainbow Six Siege |
| **Vanguard (Riot)** | Yes | Yes | **TOTAL BLOCK** | Valorant (not UE but worth noting) |
| **nProtect GameGuard** | Yes | Yes | **TOTAL BLOCK** | Various Korean MMOs |

### 2.4 Summary Matrix

```
                     DLL Injection    Memory R/W    Console Cmds
No protection        YES              YES           YES (via GEngine)
Denuvo only          YES (usually)    YES           YES
Capcom Anti-Tamper   NO (crash)       YES           NO
EAC / BattlEye      NO (blocked)     PARTIAL       NO
Vanguard             NO               NO            NO
```

---

## 3. UUU/IGCS Strategy Analysis

### 3.1 UUU (Otis_Inf) Official Position

Source: [UUU v5 page](https://opm.fransbouma.com/uuuv5.htm),
[FAQ](https://opm.fransbouma.com/faq.htm)

- "Games which have anti-cheat in general won't get a camera mod."
- "Online games are a no-go too."
- "There won't be code added to the UUU to make it work with these games."
- Exception: Elden Ring — anti-cheat can be trivially disabled by
  launching `eldenring.exe` directly with a `steam_appid.txt` file,
  which disables online and EAC simultaneously.

### 3.2 IGCS (Open Source Camera System) Strategy

Source: [IGCS GitHub](https://github.com/FransBouma/InjectableGenericCameraSystem)

- Does NOT include any anti-cheat bypass code.
- Each game gets a per-game camera DLL with specific memory offsets.
- Uses MinHook for function hooking (user-mode only).
- Community forks (IGCS-GITC) may support anti-cheat games but warn
  about ban risks.

### 3.3 Common Workarounds Used by the Community

| Workaround | How it works | Risk level |
|-----------|--------------|------------|
| **Launch EXE directly** (skip launcher) | Bypasses EAC/BattlEye that loads via launcher. Disables online. | Low — just disables MP |
| **REFramework** | Patches Capcom's anti-tamper at runtime before it activates | Low — established tool |
| **Rename/delete EAC DLL** | Remove `EasyAntiCheat.dll` from game folder, launch directly | Low — disables online |
| **steam_appid.txt trick** | Place file in game dir, launch EXE directly to skip Steam's AC bootstrap | Low |
| **Offline mode** | Disconnect network before launch | Low |

**Key insight:** All these workarounds **disable** anti-cheat rather than
bypass it. This is acceptable for single-player screenshot/capture workflows.

---

## 4. Our Strategy: captureAIshi Bridge v0.2.0

### 4.1 Target Scope

We target **single-player UE5 games** for training data capture.
This means:

- Most games we care about do NOT have kernel-level anti-cheat
- Games with Denuvo usually still work (DLL injection is fine)
- Online-only / competitive games are out of scope entirely

### 4.2 Driver Fallback Chain

```
Attempt 1: Bridge DLL injection (--driver ue5 --auto-inject)
  |-- Works: full console access, camera path, timestop, etc.
  |-- Fails: try next
  v
Attempt 2: External UUU (--driver ue5)
  |-- Works: same capabilities via UUU's TCP console
  |-- Fails: try next
  v
Attempt 3: External memory R/W (--driver memory)
  |-- Works: camera control only (no console commands)
  |-- Fails: try next
  v
Attempt 4: Cheat Engine (--driver cheatengine)
  |-- Works: CE has its own kernel driver for protected processes
  |-- Fails: try next
  v
Attempt 5: Manual mode (--driver manual)
  |-- Always works: user positions camera manually
```

### 4.3 Anti-Cheat Pre-Check (Planned)

Before injection, detect if anti-cheat is present:

1. Check if `EasyAntiCheat.dll` or `BEService.exe` exists in game directory
2. Check if EAC/BE services are running (`sc query EasyAntiCheat`)
3. If detected, warn user and suggest:
   - Launch game EXE directly (skip launcher)
   - Use `--driver memory` instead
   - Delete/rename anti-cheat DLLs (single-player only)

### 4.4 What We Do NOT Do

- We do NOT bypass kernel-level anti-cheat
- We do NOT hook kernel functions
- We do NOT write kernel drivers
- We do NOT support online/multiplayer games
- We do NOT circumvent DRM (Denuvo, etc.)

This is a **photography and data capture tool** for single-player games,
following the same ethical line as UUU/IGCS.

---

## 5. Compatibility Quick Reference

### 5.1 Known Compatible (UE5, no anti-cheat)

These game types work with our bridge out of the box:

- UE5 single-player games without anti-cheat (majority)
- UE5 games with Denuvo only (most still allow DLL injection)
- UE5 games where anti-cheat can be disabled (launch EXE directly)

### 5.2 Known Incompatible

| Game Type | Why | Alternative |
|-----------|-----|-------------|
| Fortnite | EAC + online only | Out of scope |
| UE5 games with EAC (online mode) | Kernel AC blocks injection | Disable AC, use offline |
| UE5 games with BattlEye | Kernel AC blocks injection | Same as above |
| Non-UE5 games | Different engine | Use Unity driver or CE |

### 5.3 Requires Workaround

| Game | Protection | Workaround |
|------|-----------|------------|
| Elden Ring | EAC | Launch eldenring.exe directly with steam_appid.txt |
| RE4 Remake | Capcom Anti-Tamper | Install REFramework first |
| Dragon's Dogma 2 | Capcom Anti-Tamper | Install REFramework first |

---

## 6. References

- [UUU v5 Documentation](https://opm.fransbouma.com/uuuv5.htm)
- [UUU FAQ](https://opm.fransbouma.com/faq.htm)
- [IGCS GitHub](https://github.com/FransBouma/InjectableGenericCameraSystem)
- [IGCS Injector](https://github.com/FransBouma/InjectableGenericCameraSystem/tree/master/Tools/IGCSInjector)
- [FRAMED Screenshot Community - UE4 Console Unlocker Guide](https://framedsc.com/GeneralGuides/universal_ue4_consoleunlocker.htm)
- [Recent UUU-compatible games (Patreon)](https://www.patreon.com/posts/recent-games-uuu-131727000)
