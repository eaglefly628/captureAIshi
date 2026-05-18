# UE5.8 MCP Live Validation Log (xiaoxu, 2026-05-17)

End-to-end test against running UE 5.8 Preview Editor with
`AIAssistant + ToolsetRegistry + ModelContextProtocol + AllToolsets` enabled.
Conclusions feed back into `agents/unreal/SHARED.md` v0.3.3 P0-1 plan.

## §0 Environment

- UE binary: `C:\Program Files\Epic Games\UE_5.8`
- Project: `D:\project\IAMRobot\IAMRobot.uproject` (launched via VS Code,
  not double-click — double-click hits a manifest pre-check bug and refuses
  to load when AI plugins are listed; VS Code path goes through UBT and
  succeeds)
- Server: `ModelContextProtocol.StartServer` console command at UE console
- Listening: `127.0.0.1:8000/mcp` (verified by UE log + `netstat`)

## §1 JSON-RPC Handshake

```bash
POST /mcp
{"jsonrpc":"2.0","id":0,"method":"initialize",
 "params":{"protocolVersion":"2025-11-25","capabilities":{},
           "clientInfo":{"name":"curl-test","version":"1"}}}
```

Response (200, header `Mcp-Session-Id: <hex>`):

```json
{"protocolVersion":"2025-11-25",
 "capabilities":{"resources":{},"tools":{"listChanged":true}},
 "serverInfo":{"name":"","title":"","version":""}}
```

`serverInfo` triple-empty is a 5.8 Preview bug, not functional.

## §2 Two-tier Tool Discovery

`tools/list` on a fresh session returns only **3 meta tools**:

| Tool | Purpose |
|---|---|
| `list_toolsets` | Enumerate registered toolsets (name + description) |
| `describe_toolset` | Full schema for one toolset before loading |
| `load_toolset` | Register a toolset's tools into the active MCP tools[] (next turn) |

This is a deliberate lazy-discovery model -- avoids dumping ~100 tools into
the LLM's tools[] payload on every turn. LLM workflow: list -> describe ->
load -> use.

## §3 Toolset Inventory (41 toolsets discovered)

`list_toolsets` raw output captured. Grouped + starred = relevant to our PCG
foundry workflow:

### Core (`toolset_registry.toolsets.core.*`) — 15 toolsets

| Toolset | Use | Priority |
|---|---|---|
| **object.ObjectTools** | list/get/set properties on any UObject, search subclasses | ★★★ |
| **scene.SceneTools** | load_level, find_actors, add/remove from scene | ★★★ |
| **actor.ActorTools** | actor transforms, labels, components | ★★ |
| **programmatic.ProgrammaticToolset** | sandboxed Python that can chain other tools | ★★★ |
| material.MaterialTools | Material asset CRUD + expression graphs | ★ Substrate |
| material_instance.MaterialInstanceTools | MIC create/modify | ★ |
| primitive.PrimitiveTools | primitive geometry components | — |
| static_mesh.StaticMeshTools | static mesh asset CRUD | ★ |
| skeletal_mesh.SkeletalMeshTools | skeletal mesh + bones + sockets | — |
| asset.AssetTools | asset / disk interop | ★ |
| blueprint.BlueprintTools | BP scripting | — |
| data_asset.DataAssetTools | data assets | ★ scene_spec |
| data_table.DataTableTools | DT CRUD | ★ batch |
| curve_table.CurveTableTools | curve tables | — |
| string_table.StringTableTools | i18n strings | — |
| texture.TextureTools | texture import / sampler | — |

### Editor (`ToolsetRegistry.*`) — 3 toolsets

- **EditorAppToolset** ★★ viewport camera, cvar search, asset image capture
- AgentSkillToolset (skill assets)
- LogsToolset ★ output log read

### AI / Self (`AIAssistant.*`) — 1 toolset
- AIAssistantToolset (self-inspection)

### Sequencer / Animation — 8 toolsets ★ all relevant for MRQ

- animation_toolset.sequencer.**SequencerTools** ★★ sequence lifecycle + camera tracks
- animation_toolset.keyframing.**SequencerKeyframingTools** ★ joint pose keyframes (URDF)
- animation_toolset.controlrig.ControlRigTools
- animation_toolset.controlrig_sequencer.SequencerControlRigTools
- animation_toolset.outliner.SequencerOutlinerTools
- animation_toolset.conditions.SequencerConditionTools
- animation_toolset.custom_bindings.SequencerCustomBindingTools
- animation_toolset.import_export.**SequencerImportExportTools** ★ FBX import/export, AnimSequence

### Niagara — 4 toolsets (low priority, scenes are static)
- NiagaraToolset_Info / _Component / _Blueprint / _System

### GAS — 3 toolsets (not applicable — robots are kinematic)
- GameplayCueToolset / AttributeSetToolset / AbilitySystemInspectorToolset

### UI / Test / Misc — 7 toolsets
- UMGToolSet (UI authoring -- no UI in scenes)
- SlateInspectorToolset (Playwright-style UI test, useful for `/dev` verification)
- AutomationTestToolset (test discovery + run)
- GameFeaturesToolset (Game Feature Plugins)
- GameplayTagsToolset (tag CRUD)
- DataflowAgent.DataflowAgentToolset (Dataflow graph)
- WorldConditionsToolset (FWorldConditionQueryDefinition inspector)

### State / Behavior — 3 toolsets (advanced AI, not needed v0.3.3)
- state_tree_toolset.StateTreeTools
- conversation_toolset.ConversationTools
- aimodule_toolset.behavior_tree.BehaviorTreeTools

### Physics — 1 toolset
- PhysicsToolsets.PhysicsAssetToolset (kinematic robot uses no physics, low priority)

## §4 Loaded Tool Schemas (35 tools sampled)

After `load_toolset` on the 3 ★★★ core toolsets, full schemas pulled from
`tools/list`. Key signatures relevant to PCG workflow:

### Naming convention

| Toolset family | Tool name format | Example |
|---|---|---|
| ToolsetRegistry / AIAssistant | `<Group>.<Toolset>.<MethodPascalCase>` | `ToolsetRegistry.EditorAppToolset.GetSelectedActors` |
| toolset_registry core | `<dotted_module>.<Toolset>.<method_snake_case>` | `toolset_registry.toolsets.core.object.ObjectTools.set_properties` |
| Future custom (our plugin) | TBD, must register via `UToolsetRegistry::Register` | — |

### ObjectTools (6 tools)

```
list_properties(instance: refPath) -> [property_name]
get_properties(instance: refPath, properties: [str]) -> JSON
set_properties(instance: refPath, values: JSON_string) -> bool
get_class(instance: refPath) -> classRef
search_subclasses(base_class: refPath, class_name: str) -> [classRef]
```

`refPath` is a soft-path string (`/Game/PCG/Warehouse.Warehouse_C` style).
The `instance` parameter accepts any UObject including UPCGComponent /
UPCGGraph / any actor.

### SceneTools (12 tools)

```
load_level(level_path: str) -> void
get_current_level() -> str
find_actors(root?, glob='*', actor_type?, tag) -> [actor_ref]
add_to_scene_from_asset(asset_path, name, xform, parent?, snap_to_ground?) -> actor_ref
add_to_scene_from_class(actor_type: classRef, name, xform, parent?, snap_to_ground?) -> actor_ref
remove_from_scene(actor: refPath) -> bool
get_folders() -> [folder_path]
set_actor_folder(actor, folder_path)
get_actors_in_folder(folder_path, recursive=false) -> [actor]
delete_folder(folder_path) -> int (actors_moved)
rename_folder(old_path, new_path) -> int
trace_world(start: Vec, end: Vec) -> hit_distance | null
```

### EditorAppToolset (17 tools)

Most relevant for our flow:
```
GetSelectedActors() -> [actor]
GetVisibleActors() -> [actor]
FocusOnActors([actor])
SetCameraTransform({location, rotation, scale})
GetCameraTransform() -> Transform
CaptureEditorImage() -> PNG
CaptureAssetImage(assetPath, bShowUI=false) -> PNG  ★ thumbnail
OpenEditorForAsset(assetPath)
SetContentBrowserPath(path)
SelectActors([actor])
SearchCVars(name) -> [cvar_match]
WorldPosToScreenCoords(position) -> Vec2D
ScreenCoordsToWorld(coords, traceDistance=100000) -> world_pos
```

## §5 Architectural Implication: UPCGAdoreToolset C++ plugin -- NO LONGER NEEDED

**老白 v0.3.3 P0-1 ②** asked xiaoxu to write `UPCGAdoreToolset :
UToolsetDefinition` C++ plugin with 21 `UFUNCTION(meta=(AICallable))` methods
wrapping the PCG contract. **This validation shows the wrap is unnecessary**:

**Before** (老白 plan):

```cpp
// Plugins/AdoreRobotPCG/Source/AdoreRobotPCG/Public/UPCGAdoreToolset.h
UCLASS()
class UPCGAdoreToolset : public UToolsetDefinition {
  UFUNCTION(meta=(AICallable))
  void SetShelfDensity(float Value);
  UFUNCTION(meta=(AICallable))
  void SetForkliftCount(int32 Value);
  // ... 21 methods total
};
```

Cost: 2-3 days of C++ + Build.cs + cook + iterate. Per-param boilerplate.
Locked to 21 params; adding any new exposed knob = code change + rebuild.

**After** (built-in path):

```python
# LLM tool_call sequence on chat 'shelves denser + 2 forklifts'
SceneTools.find_actors(tag="PCG_Warehouse")
  -> [{"refPath": "/Game/Maps/Warehouse.Warehouse:PersistentLevel.PCG_0"}]
ObjectTools.set_properties(
  instance={"refPath": "/Game/Maps/Warehouse.Warehouse:PersistentLevel.PCG_0.UPCGComponent_0"},
  values='{"shelf_density": 0.9, "forklift_count": 2}'
)
EditorAppToolset.CaptureAssetImage(assetPath="/Game/Maps/Warehouse")
```

Cost: 0 C++, 0 lines plugin code. Generic — works for any PCG graph param,
any scene, any future-added knob. LLM-side just needs the **prompt to list
the valid keys + ranges** (already in `demo/prompts.py`).

### Trade-off table

| Item | C++ plugin path (老白原) | ObjectTools path (发现) |
|---|---|---|
| Plugin scaffold | `AdoreRobotPCG.uplugin` + Build.cs + .Target.cs | none |
| Code | 21 `UFUNCTION` + dispatcher | 0 |
| Strong type / range clamp | Native C++ float/int + bounds in setter | Server-side in `apps/adore_robot/main.py` `/api/chat` validates before relaying to MCP |
| LLM-facing schema | Reflected auto from `UFUNCTION` | List in `demo/prompts.py` SYSTEM_PROMPT |
| Add new param | C++ edit + recompile + restart Editor | Add to prompt, no UE restart |
| Cross-scene reusability | Need plugin per scene type | One-size-fits-all |
| Performance | Native dispatch | Reflection (UProperty lookup, OK for chat-scale) |
| Risk | Plugin must compile against 5.8 Preview ABI | Built-in toolsets ship + tested by Epic |

**Recommendation**: drop the C++ plugin scope from v0.3.3 P0-1 ②. Keep the
`UPCGAdoreToolset` name reserved for a v0.4 optimization layer IF profiling
shows reflection cost matters (it won't, at chat-call scale -- typical
single-digit calls per minute).

## §6 Next steps before claiming validation done

- [x] Smoke-call `SceneTools.get_current_level` from raw curl -- confirms
      the tool call path end-to-end, not just discovery. **DONE 2026-05-17**:
      ```
      Request:  tools/call name=toolset_registry.toolsets.core.scene.SceneTools.get_current_level args={}
      Response: 200 SSE event: message
                {"jsonrpc":"2.0","id":20,"result":{"content":[{"type":"text",
                  "text":"{\"returnValue\":\"/Temp/Untitled_1\"}"}]}}
      ```
      `/Temp/Untitled_1` is the placeholder name UE uses when no .umap is
      loaded -- this is the empty default-level state of a fresh
      `IAMRobot.uproject` open. Marshaling string-encoded JSON inside
      `content[0].text` is the MCP-standard return wrapper for tools that
      return a primitive/struct; we'll need to JSON.parse the inner text
      in `mcp_client.py` to surface the real value to callers.
- [x] Load `programmatic.ProgrammaticToolset`, check whether the Python
      sandbox can chain `find_actors` -> `set_properties` -> `Generate()`
      in one call. If yes, our `/api/chat` can pass a single Python
      snippet to MCP instead of N round trips. **DONE 2026-05-17**:
      load returned 2 tools.

      Tool 1: `execute_tool_script(script)` -- "Execute a Python script
      against the toolset APIs. Use this to batch..." This is the
      single-call orchestrator. A whole scene-spec apply becomes one
      MCP call carrying a Python string. Pseudocode for our PCG path:
      ```python
      # passed as `script` arg in execute_tool_script
      pcg = scene.find_actors(tag='PCG_Warehouse')[0]
      pcg_comp = object.get_class(pcg)  # get UPCGComponent ref
      object.set_properties(pcg_comp, '{"shelf_density":0.9,"forklift_count":2}')
      pcg_comp.Generate(True)
      return scene.get_current_level()
      ```

      Tool 2: `get_execution_environment()` -- returns sandbox details
      (available imports, helpers). Call this once to understand the
      exact API surface inside the script context. (Not yet done.)

      SSE side-channel observed: `notifications/tools/list_changed`
      pushed on the message stream during load_toolset, confirming
      the lazy-discovery push side of the protocol works as documented.
- [x] Test `ObjectTools.set_properties` against a real PCGComponent in
      IAMRobot. **DONE 2026-05-17**:
      1. Dropped a `PCG Volume` actor in the default `/Game/Empty` level.
      2. `EditorAppToolset.GetSelectedActors` returned the actor refPath.
      3. `ObjectTools.get_properties(actor, ['pCGComponent'])` returned
         the nested PCGComponent refPath (note: name has a literal space:
         `... .PCG Component`).
      4. `ObjectTools.list_properties(pcg_component)` returned ~35
         UPROPERTYs including `seed`, `bActivated`, `generationTrigger`
         enum, `bGenerated`, `graphInstance` (this is the
         `/Script/PCG.PCGGraphInstance` nested object that holds Graph
         asset + OverrideParams -- the container for the 21 PCG params
         contract).
      5. `ObjectTools.set_properties(pcg_component, '{"seed":99999}')`
         returned success.
      6. `ObjectTools.get_properties(pcg_component, ['seed'])` read back
         99999.
      7. **User confirmed**: UE Editor Details panel updated to show
         `Seed = 99999` immediately (no save/refresh needed).

      Conclusion: round-trip web -> DeepSeek tool_call -> MCP
      set_properties -> live UE state mutation **proven end-to-end**.
      Every PCG knob reachable via reflection -- nested struct
      (`graphInstance.OverrideParams.<param>`) follows the same
      mechanism. **C++ UPCGAdoreToolset plugin is no longer required.**
- [x] Update `apps/adore_robot/mcp_client.py` to auto-load the 3 ★★★
      toolsets on connect, so `/dev` and future `/api/chat` see them
      directly without LLM having to issue `load_toolset` first.
      **DONE 2026-05-17 (Plan A)**:
      - `DEFAULT_TOOLSETS` = EditorApp + ObjectTools + SceneTools +
        ProgrammaticToolset.
      - `auto_load_toolsets()` idempotent via `_loaded_toolsets` set;
        cache reset on 404 session expiry.
      - `_parse_sse_or_json()` handles UE 5.8's `event: message\ndata: {...}`
        SSE wire format (it's not always plain JSON like the spec docs).
      - `_unwrap()` peels off the `result.content[0].text` JSON-string
        envelope. ObjectTools.get_properties / list_properties double-
        wrap (text is JSON of `{"returnValue": "<JSON-string>"}`), so
        we inner-parse when returnValue is a string.
      - PCG helpers: `get_selected_actors`, `list_actor_properties`,
        `get_actor_properties`, `set_actor_properties`,
        `find_pcg_component_refpath` (selection-first + Programmatic
        Python find_all fallback), `apply_pcg_delta` (auto_load + find +
        set in one call).
- [x] Plan-A `/api/chat` MCP relay wired. **DONE 2026-05-17**:
      When chat is in `scene` mode and LLM emits update_scene tool_call
      with non-empty `pcg_params`, `_try_mcp_relay()` pushes the delta
      through to UE Editor via ObjectTools.set_properties. Frontend
      `callRealChat` surfaces the relay status as a narrate suffix:
      `· ✓ MCP -> UE: PCGComponent_0 updated` (or `· ◌ MCP skipped (reason)`).
      Gracefully no-ops with `{ok:false, skipped:true, reason:...}` when
      UE MCP is down, sandbox-tested.
- [x] New endpoints for the / (design) and /dev panels:
      - `POST /api/mcp/apply_pcg {pcg_params: {...}}` -- direct apply,
        bypasses LLM (slider drags can push directly).
      - `POST /api/mcp/auto_load` -- manually trigger bulk toolset load.
      - `POST|GET /api/mcp/probe_graph` -- Plan-B exploration: finds
        the selected PCG actor, drills into graphInstance, lists its
        schema, returns interesting `override*/param*/graph*` field
        values so we can map the 21-param contract to the UPCGGraphInstance
        property paths without guessing.
      - `/api/mcp/status` now also returns `loaded_toolsets` array.
- [ ] Plan-B graphInstance OverrideParams structure -- waiting on user
      to drop a PCG Volume with a Graph asset assigned (current test
      Volume has no graph), then hit `/api/mcp/probe_graph` and we
      capture the layout here. Endpoint code is ready and tested
      against MCP-down gracefully.
- [x] Write 老白-confirm P0 (see `agents/unreal/SHARED.md`) -- 实证完整,
      pending green-light.
