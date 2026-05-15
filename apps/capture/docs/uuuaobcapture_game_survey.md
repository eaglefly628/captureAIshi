# UUU AOB Catalog -- Game Survey & Injection Ranking

> **Source**: `uuuaobcapture/` (raptoravis IGCS / Universal Unreal Unlocker
> AOB extraction, see `REVERSE_ENGINEERING_WALKTHROUGH.md` for the
> Ghidra workflow).
>
> **Catalog**: `uuuaobcapture/aob_patterns_by_game.json` --
> 26 unique games, 105 keys, 397 candidate patterns. Split between
> UniversalUE4Unlocker 4.11.5 (UE4 builds) and UniversalUE5Unlocker
> 5.8.11 (UE5 builds).

This document is the snapshot taken on 2026-04-26. Re-run
`uuuaobcapture/extract_aob_patterns_*.py` if a newer UUU build lands.

---

## 1. Cracked Games -- Full List

### UE5 unlocker (`UniversalUE5Unlocker5.8.11.dll`)

| Game | Per-game keys | Notes |
|---|---:|---|
| Borderlands 4 | 5 | UE5 codename `b1` |
| Avowed | 3 | UE5, Obsidian / MS |
| The Outer Worlds 2 | 2 | UE5, Obsidian / MS |
| Oblivion Remastered | 2 | UE5 wrapper around Gamebryo, Bethesda |
| Unknown (UE codename M1) | 2 | Process name `M1-Win64-Shipping`; identity TBD |
| Code Vein II | 1 | UE5, Bandai Namco |
| Mafia: The Old Country | 1 | UE5, Hangar 13 / 2K |
| S.T.A.L.K.E.R. 2 | 1 | UE5, GSC Game World |
| Silent Hill f | 1 | UE5, Konami |
| Banishers: Ghosts of New Eden | 0 (shared only) | UE5, Don't Nod |
| Hellblade II | 0 (shared only) | UE5, Ninja Theory / MS |
| Tekken 8 (codename Polaris) | 0 (shared only) | UE5, Bandai Namco |
| Unknown (UE codename TQ2) | 0 (shared only) | Identity TBD |

Shared UE5 framework pool: 31 keys, 197 variants -- works for any
UE5 game including the four "shared only" entries above.

### UE4 unlocker (`UniversalUE4Unlocker4.11.5.dll`)

| Game | Per-game keys | Notes |
|---|---:|---|
| Final Fantasy VII Rebirth | 9 | Most invested per-game patterns |
| Stellar Blade | 2 | UE4, Shift Up |
| Lost Soul Aside | 2 | UE4, Sony / Ultizero |
| Final Fantasy VII Remake | 1 | UE4, Square Enix |
| Hogwarts Legacy | 1 | UE4, Avalanche |
| South of Midnight | 1 | UE4, Compulsion / MS |
| Star Wars Jedi: Survivor | 1 | UE4, Respawn |
| The Invincible | 1 | UE4, Starward |
| The Quarry | 1 | UE4, Supermassive |
| Tiny Tina's Wonderlands | 1 | UE4, Gearbox |
| Indiana Jones | 0 (shared only) | UE4, MachineGames; Steam now too |
| Scorn | 0 (shared only) | UE4, Ebb Software |
| Unknown (UE codename U9) | 0 (shared only) | Identity TBD |

Shared UE4 framework pool: 36 keys, 162 variants.

---

## 2. Injection-Ease Ranking (Steam-version-closest)

Ranking criteria (descending priority):

1. **Anti-cheat severity** -- kernel-mode AC (EAC, BattlEye, Vanguard)
   makes external DLL injection extremely hard. User-mode AC harder.
   No AC = trivial.
2. **Single-player vs multiplayer** -- pure SP is friendly to camera
   mods; competitive multiplayer almost always blocks injection.
3. **DRM** -- Denuvo can occasionally interfere with injection but
   usually permits IGCS for offline play. SteamDRM is a no-op.
4. **Engine version match with UUU build** -- AOB patterns are tied
   to specific UE compiler / linker output. Games whose Steam build
   matches the UUU 4.11.5 / 5.8.11 era (~2024-2026) are most
   reliable; older or much newer builds risk pattern drift.
5. **Per-game AOB coverage** -- games with dedicated keys in the
   catalog get higher confidence than shared-only entries.

### Tier 1 -- almost-one-shot inject (no AC + SP + Steam) ⭐⭐⭐

These are the highest-ROI candidates for the next pipeline expansion.

| # | Game | Engine | Year | AC | Comments |
|---|------|--------|------|----|----------|
| 1 | **Hellblade II** | UE5 | 2024 | none | MS first-party; matches UUU 5.8.11 era; we already own a Hellblade I config to fork |
| 2 | **Avowed** | UE5 | 2025 | none | Obsidian/MS; 3 per-game keys land directly |
| 3 | **Oblivion Remastered** | UE5 | 2025 | none | Bethesda; mod-friendly history |
| 4 | **The Quarry** | UE4 | 2022 | none | Supermassive; narrative SP, build long-stable |
| 5 | **The Invincible** | UE4 | 2023 | none | Starward exploration SP |
| 6 | **South of Midnight** | UE4 | 2025 | none | Compulsion/MS first-party |

### Tier 2 -- Denuvo or anti-tamper, injection usually works ⭐⭐

| # | Game | Engine | Year | DRM/AC | Comments |
|---|------|--------|------|--------|----------|
| 7 | Stellar Blade | UE4 | 2025 | none on PC port | Shift Up |
| 8 | Hogwarts Legacy | UE4 | 2023 | Denuvo removed 2024 | IGCS already known to work |
| 9 | Star Wars Jedi: Survivor | UE4 | 2023 | Denuvo removed | EA / Respawn |
| 10 | Mafia: The Old Country | UE5 | 2025 | Denuvo | Hangar 13 |
| 11 | Silent Hill f | UE5 | 2025 | likely Denuvo | Konami |
| 12 | The Outer Worlds 2 | UE5 | 2025 | unknown anti-tamper | MS first-party |
| 13 | Lost Soul Aside | UE4 | 2025 | Sony PC port | UltiZero |
| 14 | Final Fantasy VII Remake | UE4 | 2022 | Denuvo + offline | Square Enix |
| 15 | Final Fantasy VII Rebirth | UE4 | 2025 | Denuvo | 9 per-game keys -- IGCS most invested |
| 16 | Banishers | UE5 | 2024 | Denuvo | Don't Nod |
| 17 | Code Vein II | UE5 | 2026 | Denuvo expected | Bandai Namco |
| 18 | Indiana Jones (Great Circle) | UE4 | 2024 | none | Now on Steam too |

### Tier 3 -- has EAC but offline mode often unblocked ⭐

| # | Game | Engine | Year | AC | Comments |
|---|------|--------|------|----|----------|
| 19 | S.T.A.L.K.E.R. 2 | UE5 | 2024 | EAC for online | SP launches without |
| 20 | Borderlands 4 | UE5 | 2025 | EAC for matchmaking | SP/co-op offline works |
| 21 | Tiny Tina's Wonderlands | UE4 | 2022 | EOS/EAC online | SP works |

### Tier 4 -- kernel-AC, very hard / risky ✗

| # | Game | Engine | Year | AC | Comments |
|---|------|--------|------|----|----------|
| 22 | Tekken 8 (Polaris) | UE5 | 2024 | TekkenChat + Denuvo | Competitive multiplayer; ban risk |

### Tier 5 -- low priority

| # | Game | Note |
|---|------|------|
| 23 | Scorn | Shared only; little ROI vs Tier 1 |
| 24 | Unknown M1 / TQ2 / U9 | Codenames not yet identified |

---

## 3. Recommendation Summary

**Highest ROI -- pick first**: **Hellblade II**, **Avowed**, **The Quarry**.

- All three are pure single-player.
- All three are no-AC.
- Hellblade II reuses our existing UE4 Hellblade pipeline (just bump
  AOBs to UUU 5.8.11 shared pool).
- Avowed brings 3 per-game keys (camera_atmospherics-class hooks)
  that land directly from the catalog.
- The Quarry has been stable on Steam for ~3 years -- low pattern
  drift risk; great smoke-test target before tackling 2025 titles.

Once any one of these passes the end-to-end test (camera write +
GBuffer + depth + decode), the rest of Tier 1-2 collapses to "copy
config + adjust offsets" labour, since the AOBs are already cached
in `uuuaobcapture/aob_patterns_by_game.json`.

---

## 4. Re-running the Survey

```bash
# UE4 catalog
python uuuaobcapture/extract_aob_patterns_4.11.5.py

# UE5 catalog
python uuuaobcapture/extract_aob_patterns_5.8.11.py

# Merge both into the unified catalog
python uuuaobcapture/enrich_and_merge.py
```

The walkthrough (`uuuaobcapture/REVERSE_ENGINEERING_WALKTHROUGH.md`)
documents the Ghidra HTTP API + `extract_aob_patterns.py` v4 parser
that produced these files. Knowing the per-game register lookup
pattern there is what will let us hand-pick AOBs into our own
`configs/hacks/` profiles below.
