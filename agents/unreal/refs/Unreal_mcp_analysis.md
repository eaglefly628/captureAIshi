# ChiR24/Unreal_mcp -- Reference Analysis (xiaoxu, 2026-05-20)

Cloned to `agents/unreal/refs/Unreal_mcp/` (shallow). README + handler-mapping + plugin source skimmed.

## Architecture comparison

|                  | ChiR24/Unreal_mcp                                                | captureAIshi / adore_robot                                  |
| ---------------- | ---------------------------------------------------------------- | ----------------------------------------------------------- |
| **MCP server**   | TypeScript / Node (npm `unreal-engine-mcp-server`)               | Python / Flask                                              |
| **UE plugin**    | Custom `McpAutomationBridge` (~70 cpp files in `plugins/`)       | Epic 5.8 official `ModelContextProtocol` + Toolset Registry |
| **Transport**    | HTTP+SSE direct **or** WebSocket via TS bridge                   | HTTP+SSE only                                               |
| **Tool surface** | 22 canonical "manager" tools, action-dispatched                  | 6-8 specific tools (spawn_object, spawn_batch, ...)         |
| **Coverage**     | Asset, BP, Actor, Material, Niagara, Sequencer, GAS, Audio, BT…  | Demo v0 scene editing only (robotics scenes)                |
| **Maturity**     | Production-style: caching, rate limit, capability tokens, tests  | Demo v0; no auth, no tests yet                              |

## Key design decisions vs us

### 1. Action-dispatched canonical tools

Their LLM surface: ~22 tools like `manage_asset`, `control_actor`, `manage_blueprint`. Each takes an `action` arg
(`spawn`, `delete`, `transform`, `set_visibility`, ...) that fans out to a specific C++ handler.

```ts
control_actor({ action: "spawn", class_path: "/Game/SM_Cube", location: {...} })
```

vs our `spawn_object(asset_name, x, y, ...)` style.

**Trade-off**: fewer tool slots in the schema (LLM picks `control_actor`, then chooses action) but harder for
the LLM to know which action takes which args. They mitigate with verbose tool descriptions + schemas. For
robotics demo with 6 actions total, our 1:1 mapping is friendlier; if we grow past 20 actions, action-dispatch
starts paying off.

### 2. Native C++ over Epic MCP

This is the route 老白 originally proposed in v0.3.3 P0-1 (`UPCGAdoreToolset` C++ plugin). We chose Epic's
official 5.8 MCP plugin instead and validated it covers PCG writes via ObjectTools reflection -- saving ~2-3
weeks of plugin dev (ue58_mcp_validation_log.md §5).

**ChiR24's plugin has features Epic's doesn't expose**:
- Niagara authoring (create system, edit modules, GPU sim params)
- Behavior Tree node creation + connection
- Material graph expression nodes
- World Partition / Foliage / Insights handlers

For our robotics scene foundry these are out of scope. **But if a customer asks "let me design a robot
behavior tree by chat" we'd hit the wall**. Worth knowing the option exists.

### 3. Plugin handler decomposition

70+ `McpAutomationBridge_*Handlers.cpp` files, each owning one category. Clean separation. If we ever build
our own C++ plugin (rejected for now), this layout is a good template.

### 4. Patterns worth stealing now

- **Asset caching with TTL** (their README: 10-second TTL). We hardcode `ASSET_REGISTRY` -- when user
  swaps in real meshes, we could auto-refresh. Cheap win post-demo.
- **Command safety pattern-based validation**. Our `execute_tool_script` is dead (UE sandbox), but if we
  ever expose `set_actor_properties` with free-form JSON we should pattern-block dangerous keys.
- **Capability token auth**. Currently `/api/mcp/*` is wide open on `127.0.0.1`. For production
  deployment add a token from `.env`.
- **Per-IP rate limit on metrics endpoint**. We don't have a metrics endpoint yet -- when we add one for
  ops, copy.
- **Dynamic type discovery** for `spawnable types`. We hard-code 6 asset_names; theirs introspects.
  If user wants chat to spawn ANY mesh in their /Game/, we'd need this.

### 5. Patterns NOT to copy

- **22 manager tools**: overkill for our v0 scope. Adds LLM confusion (which action?).
- **WebSocket transport**: HTTP+SSE works fine for UE 5.8, less infrastructure.
- **TypeScript stack**: Python is fine for our scale, and the rest of captureAIshi is Python.
- **Whole-engine API surface**: we're a robotics scene foundry, not a general UE editor. Narrow tools
  with focused docstrings win for LLM accuracy.

## Concrete TODOs spun off

- [ ] (P2 post-demo) Asset registry → query `AssetRegistry` via `manage_asset.list` equivalent to
  auto-build registry from `/Game/Demo/` folder contents.
- [ ] (P2) Capability token in `.env` + `Authorization: Bearer` check on `/api/mcp/*` and `/api/demo/*`.
- [ ] (P3) If customer wants robot behavior trees: evaluate building a thin C++ wrapper around
  `McpAutomationBridge_BehaviorTreeHandlers` instead of waiting on Epic.

## Reference files worth re-reading

- `README.md` — full tool catalog (22 tools × multi-actions each)
- `docs/handler-mapping.md` — ts tool → C++ handler crosswalk, design pattern textbook
- `docs/Engine-API-Reference.md` — which UE APIs they call per handler
- `plugins/McpAutomationBridge/Source/.../Private/McpAutomationBridge_ControlHandlers.cpp` — spawn /
  delete / transform actor implementation, compare with ours which goes through SceneTools native
- `docs/native-automation-progress.md` — their migration log from script-based to native; their gotchas
  match ours (sandbox limitations, transform reflection, etc.)

## Bottom line

Their repo is a textbook full-coverage UE MCP server (general purpose, customer = devs). Ours is a
focused robotics scene foundry (customer = embodied AI training data buyers). **Architectures
diverge correctly per use case**; the patterns to steal are operational (caching, auth, rate limit)
not architectural. Keep it as `agents/unreal/refs/Unreal_mcp/` for future "how would they handle X"
lookups.
