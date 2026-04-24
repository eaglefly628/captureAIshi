---
name: ghidra-aob-extraction
description: |
  Extract AOB (Array-of-Bytes) signatures from a binary open in Ghidra and attribute
  each pattern to the game(s) it targets. Use when the user asks to mine AOB/signature
  patterns, identify which games an IGCS-style / camera-hack / trainer DLL supports,
  find byte-pattern-per-game mappings, or do any Ghidra-driven reverse-engineering
  where patterns are registered via `addAOB(container, name, pattern)`-style calls.
  Works with the GhidraMCP bridge (MCP tools or raw `http://127.0.0.1:8080/` HTTP).
---

# Ghidra AOB pattern extraction

This skill distills a proven workflow for extracting byte-pattern signatures and
mapping them to games, out of a binary loaded in Ghidra. It assumes the user has
the **GhidraMCP** plugin running (exposes `http://127.0.0.1:8080/`) and possibly
also has `mcp__ghidra__*` MCP tools configured — both are supported.

Reference implementation and a line-by-line walkthrough of the original derivation
live in `REVERSE_ENGINEERING_WALKTHROUGH.md` and `extract_aob_patterns.py` at the
project root.

---

## When to use

Invoke this skill for requests like:

- "find all AOB patterns in this DLL"
- "which games does this trainer support?"
- "extract byte signatures grouped by game"
- "reverse engineer this IGCS / camera-hack binary"
- "map each signature to its game"
- "what's the AOB for `<game>` in this build?"

Do **not** use it for: generic Ghidra scripting, non-AOB reverse engineering,
IDA-only workflows, or when the binary has no Ghidra project open.

---

## Prerequisites (verify these first)

1. **Ghidra HTTP reachable**:
   `curl -sf http://127.0.0.1:8080/methods?limit=1` must succeed.
   If not, tell the user to start the GhidraMCP plugin in Ghidra
   (`Tool → Script Manager → GhidraMCP.java → Run`). Offer to retry.
2. **MCP tools may or may not be loaded** — the bridge sometimes fails to
   auto-connect. If `mcp__ghidra__*` tools aren't present, fall back to raw
   HTTP via `urllib.request` / `curl`. Semantics are identical.
3. **Binary must be analyzed** — a fresh import with "Analyze" unchecked will
   have no decompilation or strings.

---

## Core pipeline (8 steps)

### Step 1 — Confirm service + binary identity

```bash
curl -s http://127.0.0.1:8080/segments?limit=50
curl -s "http://127.0.0.1:8080/strings?limit=500&filter=<hint>"
```

Read the head and tail of strings to identify frameworks
(FreeType, Dear ImGui, specific C++ mangled class names).
Pick one distinctive AOB-related string, `filter=` for it, and note the format
error messages — they reveal the pattern grammar (typically
`"48 8D 15 | ?? ?? ?? ?? EB 16 ..."` where `|` is a capture offset and `??` a
byte wildcard).

### Step 2 — Find registration wrappers (`addAOB`-style)

1. Find one AOB name string (via string listing, `filter=AOB_`).
2. `xrefs_to` that string → pick any caller.
3. Decompile the caller — look for the triplet:
   ```c
   pat  = make_string("<hex pattern>");
   name = make_string("AOB_<NAME>");
   register(container, name, pat);   // FUN_xxxxxx(container, name, pat)
   ```
4. Record all `register` function addresses — these are the **addAOB wrappers**.
   Every registrar in the binary xrefs at least one of them.

**Wrapper count varies by engine/build**: UE5 unlockers typically have **3
wrappers** (3-arg, 4-arg, 5-arg variants — all delegating to one inner
registrar). UE4 unlockers typically have **4 wrappers** (3-, 4-, 5-, 6-arg).
Addresses also shift between minor versions, so never hard-code them without
probing first. Observed addresses for reference:

| Build | Wrappers |
|---|---|
| UUU v5.8.11 (UE5) | `180108570`, `1801084c0`, `180108700` |
| UUU v5.8.10 (UE5) | `180107fe0`, `180107c40`, `180107ab0`, `180107cf0` |
| UUU v4.11.5 (UE4) | `1800ea000`, `1800ea1c0`, `1800ea270`, `1800ea330` |

**Sanity check**: a valid wrapper signature is
`(longlong container, undefined8* name, undefined8* pat, ...)` — it calls a
`make_string`-style copy on both `name` and `pat`, then forwards to an inner
registrar. If the decompile doesn't match that shape, you've grabbed an
unrelated function (e.g. `find_aob_by_name`, which takes `(container, name,
char)` and returns a pointer).

### Step 3 — Enumerate **all** game identifiers (not just class names)

**Critical step — this is where naïve approaches fail.** Most binaries support
more games than their *Feature / *Handler class names suggest, because games
are also identified by runtime process-name `strcmp` calls.

Pull strings **paginated** (the `/strings` endpoint silently caps at ~2000 per
call — you will miss half the binary otherwise):

```python
all_strings = []
for off in range(0, 20000, 2000):
    chunk = get("strings", offset=off, limit=2000)
    if not chunk: break
    all_strings.extend(chunk)
    if len(chunk) < 2000: break
```

Then gather game identifiers from **two sources**:

a) **Process-name literals** (PE shipping name):
   ```regex
   ^[A-Za-z0-9_]+(-Win64-Shipping|-Shipping|-Win)$
   ```

b) **Every argument literal passed to a string-compare function** (find these by
   decompiling each registrar function and grepping for
   `FUN_<cmp>(x, "<literal>")`). This captures identifiers that don't match the
   process-name regex (e.g., `MafiaTheOldCountry`, short `Borderlands4`).

Merge both sets; canonicalize duplicates (e.g. `TheOuterWorlds2` and
`TheOuterWorlds2-Win` are the same game).

### Step 4 — Build the complete registrar set

Functions to decompile = union of:

- `xrefs_to(addAOB_wrapper)` for each of the ~3 wrappers
- `xrefs_to(aob_name_string)` for each `AOB_*` name
- `xrefs_to(game_identifier_string)` for each game id

Deduplicate. Usually 10–40 functions per binary.

### Step 5 — Parse each registrar with brace-scope awareness

**Do not just scan literals linearly.** Registrars have this structure:

```c
// Pre-branch: shared multi-variant candidates registered for all games
register(name, pattern_A);
register(name, pattern_B);

// Per-game override: same AOB name, game-specific pattern
if (strcmp(proc, "Game1-Win") != 0) {
    register(name, pattern_for_game1);
}

// OR-disjunction: one pattern shared between two games
if (strcmp(proc, "GameA") == 0 || strcmp(proc, "GameB") == 0) {
    register(name, pattern_for_A_and_B);
}

// Post-branch / after-LAB_xxx label: back to shared
register(name2, pattern_C);
```

Write an **event-stream parser** that emits:

| Event | Trigger |
|---|---|
| `game_tag` | literal matches one of your game-identifier strings |
| `pat` | literal matches `^[0-9A-Fa-f ?|]+$` and has ≥3 spaces, ≥8 chars |
| `name` | literal matches `^AOB_[A-Z0-9_]+$` |
| `brace_open` / `brace_close` | `{` / `}` |
| `if_ne` / `if_eq` | `if (cVar1 != '\0')` / `if (cVar1 == '\0')` |
| `goto` | `goto LAB_xxxxxx` |
| `label` | `^LAB_xxxxxx:` at start of line |

Walk events in position order, maintaining a **context stack** of
`{games: [...], depth: int, end_label: str|None}`. Rules:

- `game_tag` → push to `pending_tags`.
- `if_ne` then `brace_open` → pop `pending_tags` as a new context at the new
  brace depth.
- `if_eq` then `brace_open` → enter **OR-building** mode; absorb subsequent
  `game_tag`s and a `goto LAB_xxx`; when the matching `}` closes and depth
  returns, push a context with `end_label=LAB_xxx` for the combined game set.
- `brace_close` → pop contexts matching current depth.
- `label LAB_xxx` → pop any context whose `end_label` matches.
- `pat` → remember as `last_pat`.
- `name` + `last_pat` not None → attribute `(pattern, name)` to **every** game
  in the current stack. If stack is empty, attribute to `"Shared / <framework>"`.

This correctly handles:

- Pre-branch patterns → shared
- `if (proc == X) { ... }` → game X only
- `if (proc == A || proc == B)` compiled as `if(A==0){if(B==0) goto L;} body L:` → both A and B
- Nested conditions (rare but handled by brace depth)
- Post-`LAB:` patterns → back to shared, not leaking into the previous branch

### Step 6 — Fallback attribution for name-prefixed AOBs

Some AOBs are game-specific by name convention (e.g., `AOB_BL4_*`, `AOB_SHF_*`).
After the structural parse, re-bucket these by prefix even if the parser placed
them in "Shared":

```python
PREFIX_TO_GAME = [
    # UE5
    ("AOB_BL4_",                               "Borderlands 4"),
    ("AOB_SHF_",                               "Silent Hill f"),
    # UE4
    ("AOB_FF7REBIRTH_",                        "Final Fantasy VII Rebirth"),
    ("AOB_FF7R_",                              "Final Fantasy VII Remake"),
    ("AOB_LSA_",                               "Lost Soul Aside"),
    ("AOB_SOM_",                               "South of Midnight"),
    ("AOB_TI_",                                "The Invincible"),
    ("AOB_SB_",                                "Stellar Blade"),
    ("AOB_SPECIAL_CASE_TINA_WONDERLANDS_",     "Tiny Tina's Wonderlands"),
    ("AOB_SPECIAL_CASE_HOGWARTS_LEGACY_",      "Hogwarts Legacy"),
    ("AOB_SPECIAL_CASE_JEDI_SURVIVOR_",        "Star Wars Jedi: Survivor"),
    ("AOB_SPECIAL_CASE_THE_QUARRY_",           "The Quarry"),
]
for aob in list(game_data["Shared / UE framework (all games)"]):
    for pfx, game in PREFIX_TO_GAME:
        if aob.startswith(pfx):
            game_data[game][aob] = game_data["Shared / UE framework (all games)"].pop(aob)
            break
```

The `AOB_PM_*` prefix (photo-mode camera state) appears in UE4 builds with no
corresponding process-name `strcmp` — leave those in "Shared".

### Step 7 — Serialize (with engine + purpose_guess)

Every emitted key should carry a `purpose_guess` string — a short
human-readable classification derived from the AOB name by substring match.
The top-level also carries an `engine` field (`"UE4"` or `"UE5"`) so a merged
cross-build catalog can disambiguate same-named games or shared buckets.

**Output structure**:

```json
{
  "engine": "UE5",
  "summary": {
    "total_games_detected": 13,
    "total_games_with_specific_overrides": 9,
    "total_keys": 49,
    "total_variants": 215,
    "per_game": { "<Game>": {"keys": N, "variants": M}, ... }
  },
  "games": {
    "<Game Name>": {
      "engine": "UE5",
      "key_count": N,
      "keys": [
        {
          "key": "AOB_NAME",
          "purpose_guess": "Camera struct copy intercept",
          "variant_count": M,
          "patterns": ["<hex pattern 1>", "<hex pattern 2>"],
          "registered_in": ["FUN_xxxxxxxx"]
        }
      ]
    },
    "<Game with no override>": {
      "engine": "UE5",
      "key_count": 0,
      "keys": [],
      "note": "detected as game id in the binary but no game-specific pattern overrides were extracted — game likely relies on the shared multi-variant pool"
    }
  }
}
```

Include games with zero overrides; they are meaningful (those titles rely
entirely on the shared multi-variant fallback pool).

**`purpose_guess` classifier**: substring-match the AOB name (after stripping
the `AOB_` and any game-specific prefix) against an ordered rule list,
most-specific first. The known substrings fall into a dozen domains:

| Domain | Example substrings → label |
|---|---|
| Camera transforms | `CAMERA_STRUCT_INTERCEPT` → "Camera struct copy intercept"; `CAMERA_WRITE_INTERCEPT`, `CAMERA_MENU_WRITE_INTERCEPT`, `CAMERA_LOCKED_FOV_READ`, `COORDS_WRITE`, `ANGLES_WRITE` |
| Black-bar removal | `CAMERA_BLACKBARS_PLAYER_CAMERA_MANAGER`, `CAMERA_BLACKBARS_CAMERA_COMPONENT`, `CAMERA_BLACKBARS_REMOVAL` |
| Depth-of-field / FOV | `LENSVIGNETTE`, `FSTOPOVERRIDE_READ`, `FSTOP_READ`, `FOV_WRITE`, `FOV_READ`, `INTERCEPT_FOV`, `PLAYERCAMERACONTROLLER_FOV_WRITE` |
| HUD / Slate / UMG | `HUD_DRAW`, `HUD_SCALE_FACTOR`, `HUDSIZE_READ`, `WIDGETOPACITYSET`, `WIDGETPAINT_OPACITYREAD`, `SVIEWPORT_ONPAINT_CALL_COMPOUNDWIDGET`, `SVIRTUALWINDOW_ONPAINT_CALL_SCOMPOUNDWIDGET`, `FSLATEAPPLICATION_APP_ACTIVATION` |
| Aspect / atmosphere / post-process | `ASPECTRATIO_CONSTRAINT`, `ASPECT_CONSTRAINT`, `WRITEATMOSPHERICS`, `POSTPROCESSWRITE` |
| Skeletal mesh | `FILLCOMPONENTSPACETRANSFORMS`, `REQUIREDBONESOFFSET` |
| Input / time / pause | `BLOCK_GAMEPAD_INPUT`, `GAMEPAD_INPUT_READ`, `TIMEDILATION_CLAMPJMP`, `TIMEDILATION4VALUES`, `GET_TIMEDILATION`, `TIMEDILATION`, `GAMECLOCK_TICK_PREVENTION`, `TIMER_STRUCT`, `TIMER_TICKS_WRITE`, `UWORLD_ISPAUSE`, `UWORLD_SPAWNACTOR` |
| Core engine pointers / hooks | `UOBJECT_PROCESSEVENT`, `STATICCONSTRUCTOBJECT`, `FCONSOLEMANAGER`, `ENABLE_SET_COMMAND`, `ALLOWCHEATSCALL`, `ENGINEVERSION`, `GENGINE`, `NAMESSTORE`, `OBJECTSSTORE` |
| Misc game-specific | `MAINTHREAD_CALL_INTERCEPT` |

Rules for writing the classifier:

1. **Check most-specific substrings first** — `CAMERA_STRUCT_INTERCEPT` must
   match before `CAMERA_WRITE`; `GET_TIMEDILATION` before `TIMEDILATION`.
2. **Strip game prefixes first**, then tag the output with a `[Game]`
   bracket. E.g. `AOB_FF7REBIRTH_LENSVIGNETTE_LOCATION` →
   `[FF7 Rebirth] Lens vignette parameter`.
3. **Trailing version suffix** like `_427`, `_411` marks an engine-version-tagged
   variant of the family; strip with `re.sub(r"_\d+$", "", tail)` and retry.
4. **Every key should map.** If any key falls through to "(uncategorized)",
   add a rule — don't ship the output.

### Step 8 — Enrich / merge (when producing a cross-build catalog)

When the user asks for results from multiple builds in one file, write a
separate `enrich_and_merge.py` that:

1. Reads each per-build JSON (`aob_patterns_by_game<version>.json`).
2. Injects `engine` + per-key `purpose_guess` in place.
3. Emits a merged `aob_patterns_by_game.json` with top-level `totals`, a
   per-engine section for UE4 and UE5, and `binary` / `source` provenance.

UE4 and UE5 game rosters are **disjoint** in every observed build, so a merge
keyed by engine doesn't produce name collisions. The `"Shared / UE framework
(all games)"` bucket does collide, though — keep it inside each engine's
`games` map, not hoisted to the root.

---

## Canonical mappings (project-specific knowledge)

These are known codename → game mappings observed across UUU builds. Rosters
are **engine-specific**: UE4 and UE5 unlockers ship completely different game
sets (no overlap). Extend the tables when new codenames appear.

### UE5 builds (e.g. UniversalUE5Unlocker 5.8.x)

| Identifier seen in binary | Canonical game |
|---|---|
| `b1-Win64-Shipping` / `Borderlands4` | Borderlands 4 |
| `Avowed-Win` | Avowed |
| `TheOuterWorlds2` / `TheOuterWorlds2-Win` | The Outer Worlds 2 |
| `OblivionRemastered-Win` | Oblivion Remastered |
| `CodeVein2-Win` | Code Vein II |
| `Banishers-Win64-Shipping` | Banishers: Ghosts of New Eden |
| `Stalker2-Win` | S.T.A.L.K.E.R. 2 (present in 5.8.11, *absent* in 5.8.10) |
| `Hellblade2-Win64-Shipping` | Hellblade II |
| `SHf-Win64-Shipping` | Silent Hill f |
| `Polaris-Win64-Shipping` | Tekken 8 (UE codename Polaris) |
| `MafiaTheOldCountry` | Mafia: The Old Country |
| `M1-Win64-Shipping` | *Unknown — investigate factory function's display-name literal* |
| `TQ2-Win64-Shipping` | *Unknown — investigate factory function's display-name literal* |

### UE4 builds (e.g. UniversalUE4Unlocker 4.11.x)

| Identifier seen in binary | Canonical game |
|---|---|
| `ProjectlsaSteam-Win64-Shipping` | Lost Soul Aside |
| `SB-Win64-Shipping` | Stellar Blade |
| `TheInvincible-Win64-Shipping` | The Invincible |
| `Scorn-Win64-Shipping` | Scorn |
| `TheQuarry-Win64-Shipping` | The Quarry |
| `IndianaEpicGameStore-Win64-Shipping` | Indiana Jones (Epic Game Store) |
| `U9-Win64-Shipping` | *Unknown (UE codename U9)* |
| `ff7remake_` | Final Fantasy VII Remake (startsWith check, not strcmp) |
| `ff7rebirth_` | Final Fantasy VII Rebirth (startsWith check, not strcmp) |
| `HogwartsLegacy` | Hogwarts Legacy |
| `JediSurvivor` | Star Wars Jedi: Survivor |
| `Wonderlands` | Tiny Tina's Wonderlands |
| `SouthOfMidnight` | South of Midnight |

**Note on short-form tags**: UE4 builds mix `*-Win64-Shipping` process-name
strings (`strcmp`) with short identifiers (`HogwartsLegacy`, `JediSurvivor`,
`ff7remake_`). Some match via `strcmp`, others via `startsWith`-style checks.
Both need to be in your `GAME_TAGS` map.

### AOB name prefix → game (fallback bucketing)

| Name prefix | Game |
|---|---|
| `AOB_BL4_` | Borderlands 4 |
| `AOB_SHF_` | Silent Hill f |
| `AOB_FF7REBIRTH_` | Final Fantasy VII Rebirth |
| `AOB_FF7R_` | Final Fantasy VII Remake |
| `AOB_LSA_` | Lost Soul Aside |
| `AOB_SOM_` | South of Midnight |
| `AOB_TI_` | The Invincible |
| `AOB_SB_` | Stellar Blade |
| `AOB_SPECIAL_CASE_TINA_WONDERLANDS_` | Tiny Tina's Wonderlands |
| `AOB_SPECIAL_CASE_HOGWARTS_LEGACY_` | Hogwarts Legacy |
| `AOB_SPECIAL_CASE_JEDI_SURVIVOR_` | Star Wars Jedi: Survivor |
| `AOB_SPECIAL_CASE_THE_QUARRY_` | The Quarry |
| `AOB_PM_` | *(Photo-mode camera state — leave as Shared)* |

**Tip for resolving unknown codenames**: find the game's Feature factory
function (usually called from a routing function's per-game branch) and
look for a string literal like `"<Game Name> specific features"` inside its
body — that's the human-readable name. The C++ mangled class name
`.?AV<Name>Feature@FeaturesPerGame@GameSpecific@IGCS@@` is a reliable
secondary source for the canonical game name.

---

## Hard-won pitfalls (don't repeat these)

1. **`/strings` endpoint silently caps at ~2000 entries** with no error. Always
   paginate with `offset` + `limit`, or use `filter=` for targeted queries.
2. **Do not trust `*Feature` / `*Handler` class names as the full game list.**
   Most games are identified only by runtime `strcmp` on process names.
3. **Pattern literals don't always contain wildcards.** Game-specific patterns
   are often pure hex (e.g., `"48 89 46 10 0F 28 44 24 ..."`). Don't require
   `?` or `|` in your regex.
4. **Same AOB name → different pattern per game.** The pattern for
   `AOB_CUSTOM_WRITEATMOSPHERICS_CALL_LOCATION` in game A is a completely
   different byte sequence than in game B. Do not merge them by name.
5. **`if (A == 0) { if (B == 0) goto L; } body L:`** is the compiled form of
   `if (A || B) body`. Without detecting this, you'll miss AOBs shared between
   two games and may leak shared registrations into one game's bucket.
6. **`goto LAB_xxx` is a control-flow exit, not noise.** A naive "split by game
   tag" approach will glue shared registrations following a `LAB:` to the
   preceding game branch.
7. **MCP tools may not be loaded** even when configured — the bridge can fail
   silently. Always probe the raw HTTP endpoint first; fall back gracefully.
8. **On Windows, CPython's default stdout encoding is GBK** — Unicode output
   (bullets, arrows, CJK) crashes with `UnicodeEncodeError`. Use
   `sys.stdout.reconfigure(encoding='utf-8')` or `PYTHONIOENCODING=utf-8`.
9. **Wrapper addresses shift between minor versions** and wrapper *count*
   differs between engines (UE5 ≈ 3 wrappers, UE4 ≈ 4). Never reuse a prior
   build's hard-coded `ADDAOB_WRAPPERS` list — always re-locate by xref-ing
   an `AOB_` name string in the currently loaded binary.
10. **Two binaries with identical segment layouts may still differ.** UUU
    4.11.4 and 4.11.5 have byte-identical `.text`/`.rdata` ranges and the
    same wrapper addresses but different MD5s — the delta is in data/
    metadata sections. Confirm the loaded binary by the PE filename string
    or by running against both if uncertain.
11. **Always produce a `purpose_guess` for every key.** If any key falls
    through to `"(uncategorized)"`, extend the rule table — don't ship.

---

## Execution template

1. Read `REVERSE_ENGINEERING_WALKTHROUGH.md` if present — it has the reasoning
   trace and code for the last successful run on this repo.
2. Check `http://127.0.0.1:8080/methods?limit=1` is alive.
3. Identify the loaded binary via `/segments` and a filter like
   `/strings?filter=Unlocker` — decide engine (UE4/UE5) and version.
4. **Probe wrappers fresh** — never reuse prior addresses. Find one AOB name
   string, xref it, decompile a registrar, extract the 3-or-4 wrapper
   addresses. Verify each matches the expected signature shape (Step 2).
5. Produce a version-specific extractor (e.g. `extract_aob_patterns_X.Y.Z.py`)
   by cloning the base `extract_aob_patterns.py` and patching:
   - `ADDAOB_WRAPPERS` — the just-probed addresses
   - `GAME_TAGS` — from the engine-specific canonical table
   - `PREFIX_TO_GAME` — from the name-prefix table
   - `OUT` — the target JSON path
6. Run the extractor with `PYTHONIOENCODING=utf-8`; report counts
   `{games, keys, variants}` and any games with zero overrides (explain
   they rely on the shared pool).
7. If new game codenames appear that aren't in the canonical tables, find the
   per-game Feature factory function and read its display-name literal
   (`"<Game Name> specific features"`) to resolve the codename. Add to the
   tables for next time.
8. **Enrichment**: inject top-level `engine` and per-key `purpose_guess` via
   the substring-rule classifier (Step 7). Verify zero entries map to
   `"(uncategorized)"` — extend rules if any do.
9. **Merge** (when spanning multiple builds): use `enrich_and_merge.py` to
   emit the combined `aob_patterns_by_game.json` with per-engine sections.

## MCP ↔ HTTP reference

| If available: MCP tool | Otherwise: HTTP |
|---|---|
| `mcp__ghidra__list_strings(filter=..., offset=..., limit=...)` | `GET /strings?filter=...&offset=...&limit=...` |
| `mcp__ghidra__get_xrefs_to(address="0x...")` | `GET /xrefs_to?address=0x...&limit=50` |
| `mcp__ghidra__decompile_function_by_address(address="0x...")` | `GET /decompile_function?address=0x...` |
| `mcp__ghidra__decompile_function(name="FUN_...")` | `POST /decompile` (body = function name) |
| `mcp__ghidra__list_namespaces`/`list_classes` | `GET /namespaces` / `GET /classes` |
| `mcp__ghidra__list_segments` | `GET /segments` |
| `mcp__ghidra__search_functions_by_name(query=...)` | `GET /searchFunctions?query=...` |

Prefer MCP tools when present — they integrate cleanly with permissions. Fall
back to HTTP only when the bridge isn't loaded.

---

## GUI-only fallback (when no automation)

If the user insists on a pure-Ghidra-GUI walkthrough (no scripting), the
approximate manual recipe is:

1. `Window → Defined Strings` → filter on `AOB_` → note every name + address.
2. For each name, `Ctrl+Shift+F` to list xrefs → record caller functions.
3. For each process-name-format string (`*-Win`, `*-Shipping`), do the same.
4. Decompile each registrar function (`Ctrl+E` or Decompiler panel).
5. Use `Ctrl+M` to match `{ }` braces and visually trace each
   `if (strcmp(..., "<game>")) { ... }` body.
6. Hand-transcribe each `(pattern, name)` literal pair into a spreadsheet,
   tagging with the active game context.
7. For `goto LAB_xxx` → manually find the matching `LAB_xxx:` label line and
   close the game context there.

Expect this to take hours and be error-prone on OR-disjunction branches.
Scripted extraction exists for a reason.
