# Batch Scene Generation Architecture v2 (MCP-native)

> Supersedes `batch_scene_gen_architecture.md` (v1).
> Author: 老白. Date: 2026-05-17. Status: design, pre-implementation.
> Trigger: 老白 2026-05-16 decision -- direction B = fully embrace UE5.8 MCP.
> Reference: `apps/adore_robot/docs/refs/ue58_ai_mcp_overview.md`.

Audience: xiaoxu (build the toolset + plumbing) + xiaohuan (contract source
of truth) + xiaoxuan downstream (knows when EXR triplets land).

---

## §0 Decision Summary

| Axis | v1 | **v2 (this doc)** | Rationale |
|---|---|---|---|
| Editor control protocol | Flask -> `UnrealEditor-Cmd.exe -run=PythonScript` per job (cold-spawn) | **Editor stays open. UE5.8 `ModelContextProtocol` plugin auto-starts MCP server at `http://localhost:8000/mcp`.** All scene ops are MCP `tools/call`. | Cold-spawn cost (~20s editor boot per job) gone. Reflection-driven schema. Toolset survives sessions. |
| Tool definition | Hand-written Anthropic tool JSON | **`UPCGAdoreToolset : UToolsetDefinition` with `UFUNCTION(meta=(AICallable))`. UE generates JSON Schema via reflection.** | Zero hand-written schema. Drift between contract and tool guaranteed gone. |
| LLM provider | Hard-coded Anthropic Claude Sonnet | **`apps/adore_robot/llm/factory.py` -- `make_llm_client(provider)` returns a `BaseLLMClient` with `chat_with_tools(...)`.** Default `deepseek` (V3.2). Switchable to `anthropic`, `qwen`, `qwen-vl`, `glm`, `kimi`, `doubao`. | DeepSeek V3.2 ~10x cheaper than Claude Sonnet 4.6, stable tool calling. NL->delta task is light; premium reserved for hard reasoning. Multimodal (thumbnail feedback v0.4) defaults to `qwen-vl`. |
| Web UI | Flask app owns full PCG control (forms, generate buttons, NL chat) | **Thin shell: job list + thumbnail gallery + NL chat box. All PCG state is in UE. Browser POSTs `/api/mcp/call` proxied to MCP.** | UI never holds canonical PCG state. Refresh-safe. Same UI works for human and LLM agent. |
| Batch headless render | `UnrealEditor-Cmd.exe -run=PythonScript` per variant | **Plan B-1 preferred, Plan B-2 fallback (see §1).** Empirically validated against UE5.8 Preview before locking. | MCP-driven batch unproven; needs implementation-time verification. |

**Locked in this doc** (老白 decision): MCP topology + tool surface naming.
**Pending validation** (xiaoxu, UE5.8 Preview install): Plan B-1 vs B-2 for
batch render.

---

## §1 MCP Topology

### 1.1 Wire diagram

```
+-----------------+         +-----------------+         +--------------------+
|  Browser UI     | <-----> |  Flask (5001)   | <-----> |  UE5.8 Editor      |
|  apps/adore_    |  HTTP   |  apps/adore_    |  HTTP   |  ModelContextProto |
|  robot/web      |  + SSE  |  robot/main.py  |  + SSE  |  col plugin        |
|  (thin shell)   |         |                 |         |  :8000/mcp         |
+-----------------+         +--------+--------+         +---------+----------+
        ^                            |                            |
        |                            | mcp_client.py              | UToolsetRegistry
        |                            | (JSON-RPC 2.0)             | dispatch
        |                            |                            v
        |                            |                  +---------+----------+
        |                            |                  |  UPCGAdoreToolset  |
        |                            |                  |  (C++ in           |
        |                            |                  |  AdoreRobotPCG     |
        |                            |                  |  plugin)           |
        |                            |                  +---------+----------+
        |                            |                            |
        |                            |                            | reflection
        |                            v                            v
        |                  +---------+--------+      +------------+-----------+
        |                  | apps/adore_robot |      |  PCGComponent /        |
        +----------------- | /llm/factory.py  |      |  LevelSequence /       |
        (NL turn results)  | (DeepSeek default,      |  MoviePipelineQueue    |
                           | OpenAI-compat +         +------------------------+
                           | Anthropic adapters)
```

### 1.2 Server lifecycle

In UE editor preferences:

```
Edit -> Project Settings -> Plugins -> Model Context Protocol
  [x] bAutoStartServer
  Port: 8000
  URL Path: /mcp
```

Or one-shot from editor console:

```
ModelContextProtocol.StartServer
ModelContextProtocol.StopServer
```

Security: MCP server enforces Origin checks (no-origin clients + `localhost` +
`127.0.0.1` allowed; everything else rejected). Flask runs on `127.0.0.1:5001`
and proxies, so the browser hits Flask only, MCP only ever sees the Flask
process originating from the same host.

### 1.3 Plan B-1 / B-2 -- batch render strategy

Whether MCP can drive headless batch render is unverified upstream. Two paths:

**Plan B-1 (preferred): Editor stays open, MCP drives the batch.**

- Long-lived UE editor process, MCP server listens on :8000.
- Flask job worker calls a sequence of MCP tools per variant:
  1. `load_scene(scene_id="warehouse")`
  2. `set_shelf_density(0.9)` ... (one tool per parameter)
  3. `trigger_generate()` -- synchronous; returns after PCG `Generate(force=True)` finishes
  4. `trigger_mrq_render(preset="MRQ_MultiPassEXR", output_subdir="warehouse/v0_1")`
  5. `get_manifest_path()` -> reads `manifest.json` written by tool
- Concurrency = 1 (single editor process, GPU + license).
- Cost: ~15 min/variant on RTX 4090 1080p multi-pass EXR (xiaoxu estimate, v1 doc).

**Plan B-2 (fallback): hybrid -- MCP for interactive, commandlet for batch.**

- Same MCP server for browser / NL exploration ("set shelf density, regen").
- Batch worker spawns `UnrealEditor-Cmd.exe -run=PythonScript ...` (old v1 path)
  but the Python script *inside the commandlet* calls `UPCGAdoreToolset` methods
  directly (not through MCP). Same C++ code, same UPROPERTY-driven param surface.
- Trade-off: cold-spawn cost back (~20s/variant), but interactive iteration uses
  MCP and gets the speed.

**Decision gate** (xiaoxu task on UE5.8 Preview workstation):

1. Stand up Plan B-1: editor + MCP server + `UPCGAdoreToolset` with **one**
   warehouse parameter wired.
2. Loop: `set_shelf_density(0.5)` -> `trigger_generate()` -> `trigger_mrq_render()`
   -> `get_manifest_path()`, 5 iterations back-to-back.
3. Watch for: editor leaks (memory / handles), MRQ frame consistency across
   iterations, MCP session timeout. If all stable across 5 iters -> lock B-1.
4. If editor degrades / MRQ output corrupts after N iterations -> document the
   floor (N=3? N=10?) in this §1.3 and switch to B-2 for batch only.

Document the verification result back into this §1.3 with date + UE version
hash on first successful run.

---

## §2 `UPCGAdoreToolset` Method Surface

### 2.1 Naming convention

| Source layer | Form | Example |
|---|---|---|
| xiaohuan contract `name` column | ASCII snake_case | `shelf_density` |
| C++ `UFUNCTION` symbol | PascalCase with `Set`/`Get` prefix | `SetShelfDensity` |
| MCP tool name (auto-derived) | snake_case = contract name with `set_` prefix | `set_shelf_density` |
| AI-visible description | derived from `UFUNCTION` `meta=(ToolTip="...")` | "Shelf fill rate per BSP cell (0.2-1.0, default 0.7)." |

UE's `FBlueprintLibraryToolset` reflection generates tool names from the
`UFUNCTION` symbol (PascalCase -> snake_case automatic). The mapping is
**load-bearing**; xiaoxu must follow it for the LLM tool calls to land.

### 2.2 Parameter tools (1:1 from `pcg_param_contract.md` §1)

#### 2.2.1 Warehouse (`scene_id=warehouse`)

| Contract key | Type | Range | UFUNCTION | Tool name | Implicit regen? |
|---|---|---|---|---|---|
| `shelf_density` | float | 0.2-1.0 | `SetShelfDensity(float Value)` | `set_shelf_density` | No |
| `alley_width_m` | float | 1.5-4.0 | `SetAlleyWidthM(float Value)` | `set_alley_width_m` | No |
| `forklift_count` | int | 0-5 | `SetForkliftCount(int32 Value)` | `set_forklift_count` | No |
| `prop_variety` | int | 1-5 | `SetPropVariety(int32 Value)` | `set_prop_variety` | No |
| `pallet_load_factor` | float | 0.0-1.0 | `SetPalletLoadFactor(float Value)` | `set_pallet_load_factor` | No |
| `lighting_preset` | enum | (see §2.4) | `SetLightingPresetWarehouse(EAdoreLightingWarehouse Preset)` | `set_lighting_preset_warehouse` | No |
| `seed` | int | uint32 | `SetSeed(int32 Value)` | `set_seed` | No |

#### 2.2.2 Living Room (`scene_id=living_room`)

| Contract key | Type | Range | UFUNCTION | Tool name | Implicit regen? |
|---|---|---|---|---|---|
| `furniture_density` | float | 0.3-0.9 | `SetFurnitureDensity(float Value)` | `set_furniture_density` | No |
| `sofa_style` | enum | (see §2.4) | `SetSofaStyle(EAdoreSofaStyle Style)` | `set_sofa_style` | No |
| `decor_variety` | int | 2-8 | `SetDecorVariety(int32 Value)` | `set_decor_variety` | No |
| `clutter_level` | float | 0.0-1.0 | `SetClutterLevel(float Value)` | `set_clutter_level` | No |
| `rug_present` | bool | t/f | `SetRugPresent(bool bValue)` | `set_rug_present` | No |
| `lighting_preset` | enum | (see §2.4) | `SetLightingPresetLivingRoom(EAdoreLightingLivingRoom Preset)` | `set_lighting_preset_living_room` | No |
| `seed` | int | uint32 | `SetSeed(int32 Value)` | `set_seed` | No |

#### 2.2.3 Industrial Corner (`scene_id=industrial_corner`)

| Contract key | Type | Range | UFUNCTION | Tool name | Implicit regen? |
|---|---|---|---|---|---|
| `machine_count` | int | 1-4 | `SetMachineCount(int32 Value)` | `set_machine_count` | No |
| `toolboard_density` | float | 0.3-1.0 | `SetToolboardDensity(float Value)` | `set_toolboard_density` | No |
| `pipe_complexity` | int | 1-5 | `SetPipeComplexity(int32 Value)` | `set_pipe_complexity` | No |
| `oil_stain_amount` | float | 0.0-0.8 | `SetOilStainAmount(float Value)` | `set_oil_stain_amount` | No |
| `crate_count` | int | 0-6 | `SetCrateCount(int32 Value)` | `set_crate_count` | No |
| `lighting_preset` | enum | (see §2.4) | `SetLightingPresetIndustrial(EAdoreLightingIndustrial Preset)` | `set_lighting_preset_industrial` | No |
| `seed` | int | uint32 | `SetSeed(int32 Value)` | `set_seed` | No |

**"Implicit regen? No"** means every setter only updates the
`UAdoreRobotPCGParams` UPROPERTY; PCG re-generate must be explicitly
triggered. Rationale: agent loop control. LLM strategy is "set N params,
then `trigger_generate()` once", not "set one param N times and watch N
regens roll out". Saves ~N-1 PCG generate cycles per turn.

`SetSeed` is shared across the three scenes (same UPROPERTY on a base
`UAdoreRobotPCGParamsBase`; per-scene subclasses inherit). No name clash
because only one scene is loaded at a time.

### 2.3 Orchestration tools (not parameter setters)

| UFUNCTION | Tool name | Returns | Notes |
|---|---|---|---|
| `LoadScene(EAdoreSceneId Scene)` | `load_scene` | `void` | Loads warehouse / living_room / industrial_corner level; resets params to scene defaults. |
| `TriggerGenerate()` | `trigger_generate` | `FString` (manifest pre-stub: `{"status":"ok","ms":4200}`) | Sync; blocks until `UPCGComponent::Generate(true)` completes. |
| `TriggerMRQRender(FString PresetName, FString OutputSubdir)` | `trigger_mrq_render` | `FString` (manifest path) | Sync; blocks until MRQ finishes. `PresetName` default `MRQ_MultiPassEXR`. `OutputSubdir` becomes `Saved/MovieRenders/<subdir>/`. |
| `GetThumbnailPath()` | `get_thumbnail_path` | `FString` (relative to project dir) | After `trigger_mrq_render`, returns `Saved/MovieRenders/<subdir>/thumbnail.png`. |
| `GetCurrentSpec()` | `get_current_spec` | `FString` (JSON) | Snapshot of all active params + scene_id + variant_id. For LLM context priming + UI display. |
| `SetVariantId(FString VariantId)` | `set_variant_id` | `void` | `vMM_NN` per v1 §2.3 schema. Server-side validates pattern. |

All return values are JSON strings (MCP `content` blocks are stringly typed
for now; future v0.4 may upgrade to structured output once UE plugin matures).

### 2.4 UENUM literal lists (xiaoxu codegen reference)

```cpp
UENUM(BlueprintType)
enum class EAdoreSceneId : uint8
{
    Warehouse         UMETA(DisplayName = "warehouse"),
    LivingRoom        UMETA(DisplayName = "living_room"),
    IndustrialCorner  UMETA(DisplayName = "industrial_corner"),
};

UENUM(BlueprintType)
enum class EAdoreLightingWarehouse : uint8
{
    WarehouseSodium  UMETA(DisplayName = "warehouse_sodium"),
    CoolWhite        UMETA(DisplayName = "cool_white"),
    Mixed            UMETA(DisplayName = "mixed"),
};

UENUM(BlueprintType)
enum class EAdoreLightingLivingRoom : uint8
{
    IndoorTungsten   UMETA(DisplayName = "indoor_tungsten"),
    CoolDaylight     UMETA(DisplayName = "cool_daylight"),
    EveningWarm      UMETA(DisplayName = "evening_warm"),
};

UENUM(BlueprintType)
enum class EAdoreLightingIndustrial : uint8
{
    IndoorTungsten   UMETA(DisplayName = "indoor_tungsten"),
    HalogenSpot      UMETA(DisplayName = "halogen_spot"),
    Mixed            UMETA(DisplayName = "mixed"),
};

UENUM(BlueprintType)
enum class EAdoreSofaStyle : uint8
{
    Sectional       UMETA(DisplayName = "sectional"),
    Loveseat        UMETA(DisplayName = "loveseat"),
    Chesterfield    UMETA(DisplayName = "chesterfield"),
};
```

UE reflection emits `enum` JSON Schemas using the `DisplayName` meta when
present (per UE5.8 source per ref doc §2). LLM sees the contract literal
(`warehouse_sodium`), not the C++ symbol (`WarehouseSodium`). xiaoxu MUST set
`DisplayName` on every enum value to keep the contract surface stable.

### 2.5 Plugin layout (xiaoxu owned)

```
apps/adore_robot/unreal_projects/AdoreRobot/Plugins/AdoreRobotPCG/
+-- AdoreRobotPCG.uplugin
+-- Source/
|   +-- AdoreRobotPCG/
|   |   +-- AdoreRobotPCG.Build.cs        (Deps: Engine + PCG + ToolsetRegistry + MoviePipelineCore)
|   |   +-- Public/
|   |   |   +-- AdoreRobotPCGTypes.h      (EAdoreSceneId, ELighting*, ESofaStyle UENUMs)
|   |   |   +-- AdoreRobotPCGParams.h     (UAdoreRobotPCGParams base + 3 per-scene subclasses)
|   |   |   +-- AdoreRobotPCGToolset.h    (UPCGAdoreToolset : UToolsetDefinition)
|   |   +-- Private/
|   |       +-- AdoreRobotPCGParams.cpp
|   |       +-- AdoreRobotPCGToolset.cpp
+-- Content/
    +-- (PCG graphs from xiaohuan reference UPCGAdoreToolset's UPROPERTY surface)
```

Module includes `ToolsetRegistry` so registration happens automatically when
the plugin loads in editor.

---

## §3 LLM Provider Abstraction

### 3.1 Factory entry point

`apps/adore_robot/llm/factory.py` (already committed in this PR):

```python
from llm import make_llm_client, Message, ToolDef

client = make_llm_client()                  # default deepseek (env ADORE_LLM_PROVIDER overrides)
client = make_llm_client("anthropic")       # premium fallback
client = make_llm_client("qwen-vl",         # multimodal (v0.4 thumbnail loop)
                         model="qwen-vl-max")
```

API keys come from per-provider env vars (`DEEPSEEK_API_KEY`,
`DASHSCOPE_API_KEY`, `ZHIPUAI_API_KEY`, `MOONSHOT_API_KEY`, `ARK_API_KEY`,
`ANTHROPIC_API_KEY`). Per-provider config is in `PROVIDERS` dict; adding a
new OpenAI-compatible vendor is one entry.

### 3.2 Unified call shape

```python
resp = client.chat_with_tools(
    messages=[Message(role="user", content="warehouse 货架密一点")],
    tools=[
        ToolDef(name="set_shelf_density",
                description="Shelf fill rate per BSP cell (0.2-1.0).",
                input_schema={"type": "object",
                              "properties": {"value": {"type": "number", "minimum": 0.2, "maximum": 1.0}},
                              "required": ["value"]}),
        # ... pulled from MCP tools/list at session start
    ],
    tool_choice="auto",
    system=SCHEMA_PROMPT + FEW_SHOT + ASSET_INDEX,
    max_tokens=1024,
)
for tc in resp.tool_calls:
    mcp_client.call_tool(tc.name, tc.arguments)
```

### 3.3 Prompt-cache reuse strategy (Anthropic only)

`AnthropicClient` toggles `cache_system=True` + `cache_tools=True` by
default. `system` becomes a single `[{type:"text", text, cache_control:
ephemeral}]` block; `tools[-1]` gets `cache_control: ephemeral`. With a
stable schema across multiple NL turns in the same session, cache hit rate
is high. DeepSeek / Qwen / etc do not have an analogous cache flag in
OpenAI-compatible mode; pricing is already low enough that re-sending the
schema each turn is OK.

### 3.4 MCP tools/list -> ToolDef bridge

At session start, browser opens, Flask issues `mcp_client.list_tools()` once
and converts each MCP tool to a `ToolDef`:

```python
tools = [
    ToolDef(name=t["name"],
            description=t.get("description", ""),
            input_schema=t.get("inputSchema") or t.get("input_schema", {}))
    for t in mcp.list_tools()
]
```

This dict gets cached for the session. Tool list refreshes only when UE
emits `notifications/tools/list_changed` (rare -- happens when plugin
reloads).

### 3.5 Few-shot reuse

xiaohuan's `pcg_param_contract.md` §4.2 (5 few-shot examples) gets included
verbatim in the system prompt. v2 keeps the same five examples; only the
"actuator" changes (v1 emitted one big JSON delta, v2 emits N tool calls).

Add one v2-specific few-shot to `pcg_param_contract.md` §4 (xiaohuan's P1
in `agents/pcg/SHARED.md`):

```
Example 6 -- MCP tool call sequence:
  User: "warehouse 货架密一点, 加 2 台叉车, 然后出图"
  Assistant tool calls (in order):
    1. set_shelf_density({"value": 0.9})
    2. set_forklift_count({"value": 2})
    3. trigger_generate({})
    4. trigger_mrq_render({"preset_name": "MRQ_MultiPassEXR",
                           "output_subdir": "warehouse/v0_2"})
  Rationale: "Two param sets + one generate + one render in a single turn.
              Saves one regenerate cycle vs setting each param separately."
```

---

## §4 Web UI -- Thin Shell

The browser UI no longer owns PCG state. It is a control surface for:

1. **Connection / health**: `/api/mcp/status` polling; show MCP session id,
   reconnect button.
2. **Tool list / debug**: `/api/mcp/tools` -> filterable list. Click a tool
   -> show JSON Schema + free-form args editor + Call button. (already
   implemented in `index.html`.)
3. **NL chat**: textarea + send button. POST `/api/nl/turn` (new) ->
   server runs `llm_client.chat_with_tools(...)` -> server runs each
   resulting tool call against MCP -> server returns combined transcript
   to browser.
4. **Job / thumbnail gallery**: poll `/api/jobs` + render `<scene>/<variant>/thumbnail.png`.
   No control here; jobs are the side-effect of NL turns.
5. **Live progress (SSE)**: stream `tool_call_start`, `tool_call_done`,
   `pcg_generate_done`, `mrq_frame N/M`, `done` events while a turn is in
   flight. Source: hook UE MCP server's `notifications/progress` (if it
   emits one in 5.8 -- otherwise poll `get_current_spec` + `get_thumbnail_path`
   on a 1-second tick).

The existing 291-line `index.html` covers (1)-(2). Add (3)-(5) in
follow-up commits; not blocking for the first end-to-end smoke test
("Flask -> MCP -> set one param -> generate" works in a browser).

### 4.1 New Flask routes (next PR, xiaoxu / 老白)

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/nl/turn` | `{text, session_id?}` | `{turn_id, tool_calls: [...], result: str}` |
| GET  | `/api/nl/turn/<id>/stream` | -- | SSE: `tool_call_*`, `done`, `error` |
| GET  | `/api/jobs` | -- | `[{job_id, scene_id, variant_id, status, thumbnail_path}]` |
| GET  | `/api/thumbnails/<scene>/<variant>` | -- | PNG |

Existing endpoints (`/api/mcp/status`, `/api/mcp/tools`, `/api/mcp/call`)
stay -- they are the debug surface.

---

## §5 Dependency Checklist

### 5.1 xiaoxu (UE side, blocked on UE5.8 Preview workstation)

| Item | Blocker |
|---|---|
| UE5.8 Preview install + plugins enabled (AI Assistant + Toolset Registry + Unreal MCP + All Toolsets) | Need Windows workstation w/ RTX GPU + UE5.8 Preview download |
| `AdoreRobotPCG.uplugin` + `Source/` skeleton (§2.5 layout) | After UE5.8 install |
| `UPCGAdoreToolset` + `UAdoreRobotPCGParams` + 5 UENUMs (§2.2-§2.4) | After plugin skeleton |
| Plan B-1 / B-2 validation per §1.3 -- locks batch path | After toolset wired |
| `MRQ_MultiPassEXR.uasset` re-saved in 5.8 + commandlet smoke | After UE5.8 install |

### 5.2 xiaohuan (PCG side, async with xiaoxu)

| Item | Status |
|---|---|
| `pcg_param_contract.md` §1-§7 | Done (e484db1) |
| `pcg_param_contract.md` §8 AICallable mapping | Pending -- this v2 doc IS the §8 source. Either copy §2.2 here verbatim, or §8 just links here. xiaoxu picks. |
| Example 6 (MCP tool call sequence) added to §4.2 | Pending -- copy from §3.5 of this doc |
| PCG graph wired to `UAdoreRobotPCGParams` UPROPERTY (per §2.5 layout) | Blocked on xiaoxu plugin skeleton |

### 5.3 xiaoxuan (downstream, async)

| Item | Status |
|---|---|
| Multi-layer EXR -> Cosmos Transfer 2.5 prep | Not blocked by v2; same EXR contract as v1. Whenever first MRQ render lands, xiaoxuan can pull a sample. |

### 5.4 老白 decisions (locked here unless flagged)

| Decision | Locked |
|---|---|
| Direction = B (MCP-native) | ✓ 2026-05-16 |
| Default LLM provider | ✓ `deepseek` (factory.py) |
| Multimodal provider (v0.4 thumbnail loop) | ✓ `qwen-vl` (qwen-vl-max) |
| Premium fallback | ✓ `anthropic` (claude-sonnet-4-6) |
| UI host stack | ✓ Flask + vanilla JS (existing) |
| Batch path B-1 vs B-2 | Open -- xiaoxu validates first, locks in §1.3 |
| Robotics Plugin route (A/B/C/D) | Open -- separate doc `docs/robotics_poser_interface.md` (老白 2026-05-17) |
| Agent loop max retries (NL -> generate -> thumbnail -> retry) | Default 3, override per turn. v0.4 (not this version). |
| Job persistence backend | `apps/adore_robot/jobs.jsonl` WAL (v1 §2.4 already covers; carries over) |

### 5.5 Out of scope (postponed)

- LLM-side agent loop on thumbnail (v0.4)
- Houdini Engine integration (no consumer yet)
- MCPClientToolset (UE calls outside MCP -- not in robotics foundry use case)
- Substrate / Mega Lights / Lumen Medium A/B tests -- separate engine-side
  doc by xiaoxu, post-install
- Robotics Plugin choice -- `docs/robotics_poser_interface.md`

---

## §6 Implementation Order (when xiaoxu gets workstation)

1. **Smoke test the stack as-shipped**:
   - Open UE5.8 Preview empty project, enable plugins, `ModelContextProtocol.StartServer`,
     verify `http://localhost:8000/mcp` answers `initialize`.
   - Run `python apps/adore_robot/main.py`, open `http://localhost:5001`,
     click "Refresh" -- expect MCP session id + nonzero tool count from
     `AllToolsets` built-ins.
2. **Plugin skeleton**: `AdoreRobotPCG.uplugin` + one trivial
   `UFUNCTION(meta=(AICallable)) void SetShelfDensity(float Value)` that
   only `UE_LOG`s. Confirm it shows up in `tools/list`.
3. **Wire one param end-to-end**: `SetShelfDensity` writes to a
   `UAdoreRobotPCGParams` instance attached to a PCG actor in a test level;
   call from browser via `/api/mcp/call` -> verify UPROPERTY changes in UE.
4. **PCG re-generate**: add `TriggerGenerate()` tool, confirm PCG output
   updates on call.
5. **MRQ render**: add `TriggerMRQRender(...)` tool, confirm `.exr` files
   land in `Saved/MovieRenders/`.
6. **Loop test (Plan B-1 verification per §1.3)**: 5x back-to-back full
   cycle, lock B-1 or fall to B-2.
7. **Fan out**: rest of warehouse params + 2 other scenes per §2.2.
8. **NL turn**: add `/api/nl/turn` Flask route, smoke test
   "warehouse 货架密一点" -> LLM -> set_shelf_density(0.9) -> trigger_generate.

---

## §7 Open Questions (xiaoxu validates on workstation)

- Does UE5.8 MCP server preserve tool registration across editor PIE
  (Play-In-Editor) sessions, or do tools un/re-register on Play stop/start?
- Can `TriggerMRQRender` block synchronously, or does MRQ run async with
  callbacks? If async, the tool must return a `job_id` and a separate
  `wait_for_render(job_id)` tool needed (less clean).
- `tool_call` argument JSON depth limit -- UE reflection has known issues
  with deeply nested USTRUCTs. We use flat scalars only (per §2.2), so this
  is unlikely to bite, but worth confirming with one nested-struct probe.
- Editor crash recovery: if UE crashes mid-batch, who restarts it? v1 had
  process-per-job so this was self-healing; v2's long-lived editor needs
  either a Flask supervisor (Plan B-1) or commandlet fallback (Plan B-2).
