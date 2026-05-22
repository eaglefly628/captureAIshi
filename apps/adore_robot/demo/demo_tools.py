"""v0 demo tools: spawn / delete / move / list + 1 layout generator + clear.

Source of truth: apps/adore_robot/docs/demo_v0_simplified_contract.md
§2 (primitive schemas) + §10 (layout gen).

UE 5.8 ProgrammaticToolset Python sandbox forbids `import unreal`, so the
original "inject script" approach (xiaohuan §6) doesn't work. Instead we
map each ToolDef to a UnrealMCPClient method that drives the live editor
via native SceneTools / ObjectTools RPCs.

LLM only ever sees asset_name enum strings. Server resolves to UE paths
via asset_registry.ASSET_REGISTRY immediately before the RPC call.
"""

from __future__ import annotations

from llm.base import ToolDef

from .asset_registry import ASSET_NAMES, resolve as resolve_asset


SCENE_BOUNDS_M = 25.0  # clamp x,y inputs to +/-SCENE_BOUNDS_M


# ─── ToolDef list (handed to LLM in scene mode) ─────────────────────────

SPAWN_OBJECT_TOOL = ToolDef(
    name="spawn_object",
    description=(
        "Spawn a static mesh actor at scene-local (x,y) in meters. Returns "
        "actor_handle for later reference. Yaw is degrees around Z."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "asset_name": {"type": "string", "enum": ASSET_NAMES},
            "x": {"type": "number"},
            "y": {"type": "number"},
            "z": {"type": "number", "default": 0},
            "yaw_deg": {"type": "number", "default": 0},
        },
        "required": ["asset_name", "x", "y"],
    },
)

DELETE_OBJECT_TOOL = ToolDef(
    name="delete_object",
    description="Destroy a demo-spawned actor by handle.",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {"actor_handle": {"type": "string"}},
        "required": ["actor_handle"],
    },
)

MODIFY_LOCATION_TOOL = ToolDef(
    name="modify_location",
    description="Translate an existing actor to ABSOLUTE scene-local (x,y) meters.",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "actor_handle": {"type": "string"},
            "x": {"type": "number"},
            "y": {"type": "number"},
            "z": {"type": "number", "default": 0},
        },
        "required": ["actor_handle", "x", "y"],
    },
)

NUDGE_OBJECT_TOOL = ToolDef(
    name="nudge_object",
    description=(
        "RELATIVE translate -- add (dx, dy, dz) meters to an existing "
        "actor's current location. PREFERRED for '往左/往右/往前/往后 N 米' "
        "and any chat that describes movement as a delta rather than an "
        "absolute target. Server reads current position, so LLM does NOT "
        "need to call list_objects first."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "actor_handle": {"type": "string"},
            "dx": {"type": "number", "default": 0, "description": "delta along +X (right)"},
            "dy": {"type": "number", "default": 0, "description": "delta along +Y (forward)"},
            "dz": {"type": "number", "default": 0},
        },
        "required": ["actor_handle"],
    },
)

LIST_OBJECTS_TOOL = ToolDef(
    name="list_objects",
    description=(
        "List all demo-spawned actors with their handles, asset_names, "
        "and scene-local positions. Use to resolve ambiguous references."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    },
)

GENERATE_WAREHOUSE_TOOL = ToolDef(
    name="generate_warehouse_layout",
    description=(
        "Procedurally lay out a warehouse: shelf rows separated by aisles, "
        "forklifts in aisles, pallets/boxes/drums scattered, optional workers, "
        "ceiling lights. 13 chat-controllable params (xiaohuan procgen module)."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            # Tier 1: 7 必备
            "shelf_density":  {"type": "number", "minimum": 0.2, "maximum": 1.0, "default": 0.7,
                               "description": "Shelf fill rate, drives rows + per_row derivation"},
            "alley_width_m":  {"type": "number", "minimum": 1.5, "maximum": 4.0, "default": 2.4,
                               "description": "Aisle width between shelf rows (meters)"},
            "forklift_count": {"type": "integer", "minimum": 0, "maximum": 5, "default": 1},
            "worker_count":   {"type": "integer", "minimum": 0, "maximum": 8, "default": 0},
            "room_w_m":       {"type": "number", "minimum": 8, "maximum": 40, "default": 18},
            "room_l_m":       {"type": "number", "minimum": 8, "maximum": 60, "default": 28},
            "seed":           {"type": "integer", "minimum": 0, "maximum": 9999, "default": 0},
            # Tier 2: 6 炫酷
            "pallet_count":   {"type": "integer", "minimum": 0, "maximum": 50, "default": 8},
            "box_count":      {"type": "integer", "minimum": 0, "maximum": 30, "default": 5},
            "drum_count":     {"type": "integer", "minimum": 0, "maximum": 20, "default": 3},
            "lighting_preset":{"type": "integer", "minimum": 0, "maximum": 2, "default": 0,
                               "description": "0=warehouse_sodium, 1=cool_white, 2=mixed"},
            "rotation_jitter_deg": {"type": "number", "minimum": 0, "maximum": 180, "default": 15,
                                    "description": "Per-object yaw chaos (0=neat, 180=fully random)"},
            "chaos":          {"type": "number", "minimum": 0.0, "maximum": 1.0, "default": 0.3,
                               "description": "Master messiness knob (position jitter + variety)"},
            "clear_first":    {"type": "boolean", "default": True},
        },
    },
)

CLEAR_DEMO_TOOL = ToolDef(
    name="clear_demo_objects",
    description="Delete every actor tagged demo_v0_spawned in the CURRENT level.",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    },
)

SWITCH_LEVEL_TOOL = ToolDef(
    name="switch_level",
    description=(
        "Open a different UE level (map). Takes a short name like "
        "'RobotDemo1' or 'RobotDemo2' (or a full path like "
        "'/Game/RobotDemo1'). After this returns, subsequent spawn/list/"
        "delete calls scope to the new level's Demo/v0 folder."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "level_path": {"type": "string"},
        },
        "required": ["level_path"],
    },
)

SPAWN_BATCH_TOOL = ToolDef(
    name="spawn_batch",
    description=(
        "Spawn many static mesh actors in one call. PREFERRED for any "
        "intent that places multiple objects -- rows, grids, lines, "
        "evenly-spaced sets, 'put N forklifts in the back', etc. One "
        "tool call instead of N. Each item is {asset_name, x, y, z?, "
        "yaw_deg?} with the same enum + bounds rules as spawn_object."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "items": {
                "type": "array",
                "minItems": 1,
                "maxItems": 60,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "asset_name": {"type": "string", "enum": ASSET_NAMES},
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "z": {"type": "number", "default": 0},
                        "yaw_deg": {"type": "number", "default": 0},
                    },
                    "required": ["asset_name", "x", "y"],
                },
            },
        },
        "required": ["items"],
    },
)


DEMO_TOOLS: list[ToolDef] = [
    SPAWN_OBJECT_TOOL,
    SPAWN_BATCH_TOOL,
    DELETE_OBJECT_TOOL,
    MODIFY_LOCATION_TOOL,
    NUDGE_OBJECT_TOOL,
    LIST_OBJECTS_TOOL,
    GENERATE_WAREHOUSE_TOOL,
    CLEAR_DEMO_TOOL,
    SWITCH_LEVEL_TOOL,
]

DEMO_TOOL_NAMES = {t.name for t in DEMO_TOOLS}


# ─── Server-side validation ─────────────────────────────────────────────

def _clamp_xy(args: dict) -> dict:
    """Clamp x,y to scene bounds. Returns dict + (optional) warning str."""
    out = dict(args)
    warns = []
    for k in ("x", "y"):
        if k in out:
            v = float(out[k])
            c = max(-SCENE_BOUNDS_M, min(SCENE_BOUNDS_M, v))
            if c != v:
                warns.append(f"{k}={v} clamped to {c}")
                out[k] = c
    return out, warns


# ─── MCP dispatch: tool_name -> (mcp_client_method_name, arg_extractor) ──
# Each entry takes the validated args dict and calls the right
# UnrealMCPClient method. The dispatchers are thin so most of the work
# stays in mcp_client.py where it can be tested independently.

def dispatch_spawn(mcp, args: dict) -> dict:
    return mcp.demo_spawn(
        asset_path=resolve_asset(args["asset_name"]),
        asset_name=args["asset_name"],
        x_m=float(args["x"]),
        y_m=float(args["y"]),
        z_m=float(args.get("z", 0)),
        yaw_deg=float(args.get("yaw_deg", 0)),
    )

def dispatch_delete(mcp, args: dict) -> dict:
    return mcp.demo_delete(args["actor_handle"])

def dispatch_move(mcp, args: dict) -> dict:
    return mcp.demo_move(
        handle=args["actor_handle"],
        x_m=float(args["x"]),
        y_m=float(args["y"]),
        z_m=float(args.get("z", 0)),
    )

def dispatch_nudge(mcp, args: dict) -> dict:
    return mcp.demo_nudge(
        handle=args["actor_handle"],
        dx_m=float(args.get("dx", 0)),
        dy_m=float(args.get("dy", 0)),
        dz_m=float(args.get("dz", 0)),
    )

def dispatch_list(mcp, _args: dict) -> dict:
    return mcp.demo_list()

def dispatch_clear(mcp, _args: dict) -> dict:
    return mcp.demo_clear()

def _find_pcg_workspace_offset_m(mcp) -> tuple[float, float]:
    """Find user-tagged PCG Builder Volume (tag = 'PCG_Workspace') and
    return offset in meters from BP_DemoOrigin to the volume center.

    Returns (0.0, 0.0) if either:
    - Volume tag not found (LLM never tagged, or different scene)
    - BP_DemoOrigin missing (anchor falls back to world origin anyway)

    All errors silently fallback to (0, 0) so dispatch_warehouse never throws.
    """
    try:
        actors = mcp.call_tool_unwrapped(
            "toolset_registry.toolsets.core.scene.SceneTools.find_actors",
            {"tag": "PCG_Workspace"},
        )
        if isinstance(actors, dict):
            actors = actors.get("actors") or actors.get("results") or []
        if not isinstance(actors, list) or not actors:
            return (0.0, 0.0)
        first = actors[0]
        ref = first.get("refPath") if isinstance(first, dict) else first
        if not ref:
            return (0.0, 0.0)
        # Read volume location
        props = mcp.get_actor_properties(ref, ["root_component"])
        rc = props.get("root_component") if isinstance(props, dict) else None
        if not isinstance(rc, dict):
            return (0.0, 0.0)
        loc = (
            rc.get("relative_location")
            or rc.get("relativeLocation")
            or rc.get("location")
            or {}
        )
        if not isinstance(loc, dict) or "x" not in loc:
            return (0.0, 0.0)
        volume_cm = (float(loc.get("x", 0)), float(loc.get("y", 0)))
        # Subtract BP_DemoOrigin (existing spawn anchor) to get relative offset
        bp = mcp._demo_origin_world_cm()
        return (
            (volume_cm[0] - bp["x"]) / 100.0,
            (volume_cm[1] - bp["y"]) / 100.0,
        )
    except Exception:
        return (0.0, 0.0)


def dispatch_warehouse(mcp, args: dict) -> dict:
    """Run xiaohuan procgen module + spawn each result via mcp.demo_spawn.

    13-param contract: shelf_density / alley_width_m / forklift/worker/pallet/box/
    drum_count / room_w/l_m / seed / lighting_preset / rotation_jitter_deg / chaos.

    Anchor priority:
    1. PCG Builder Volume tagged "PCG_Workspace" (if present, layout centered here)
    2. BP_DemoOrigin actor (existing fallback in mcp.demo_spawn)
    3. World origin (0,0,0) if both above missing

    Replaces the old mcp.demo_generate_warehouse path (which had a fixed
    12-param algorithm). The new module lives at apps/adore_robot/pcg/.
    """
    # Import here to avoid top-level circular import if pcg evolves
    from apps.adore_robot.pcg import generate_warehouse

    # Optional clear
    if args.get("clear_first", True):
        try:
            mcp.demo_clear()
        except Exception:
            pass  # 没东西可清也 OK

    # Filter to pcg-recognized keys (drops clear_first + 任何未来 LLM 多塞的 key)
    pcg_keys = {
        "shelf_density", "alley_width_m", "forklift_count", "worker_count",
        "room_w_m", "room_l_m", "seed", "pallet_count", "box_count",
        "drum_count", "lighting_preset", "rotation_jitter_deg", "chaos",
    }
    pcg_args = {k: v for k, v in args.items() if k in pcg_keys}

    result = generate_warehouse(**pcg_args)

    # Volume-anchor offset: 0,0 if no PCG Builder Volume tagged
    workspace_offset_m = _find_pcg_workspace_offset_m(mcp)

    # Spawn each SpawnRequest via existing mcp.demo_spawn
    spawned: list[dict] = []
    errors: list[dict] = []
    for sr in result.spawns:
        asset_name = sr.asset_name
        # Resolve asset; unknown (light_sodium / cool_white / etc.) → cube fallback
        try:
            asset_path = resolve_asset(asset_name)
        except KeyError:
            # v0: light + future asset names fallback to cube placeholder
            asset_path = resolve_asset("box")
        try:
            rec = mcp.demo_spawn(
                asset_path=asset_path,
                asset_name=asset_name,
                x_m=float(sr.x) + workspace_offset_m[0],
                y_m=float(sr.y) + workspace_offset_m[1],
                z_m=float(sr.z),
                yaw_deg=float(sr.yaw_deg),
            )
            spawned.append(rec)
        except Exception as e:
            errors.append({
                "asset_name": asset_name,
                "x": sr.x, "y": sr.y,
                "error": f"{type(e).__name__}: {e}",
            })

    by_asset: dict[str, int] = {}
    for s in spawned:
        by_asset[s.get("asset_name", "?")] = by_asset.get(s.get("asset_name", "?"), 0) + 1

    return {
        "spawned": spawned,
        "total": len(spawned),
        "by_asset": by_asset,
        "errors": errors,
        "pcg_args": pcg_args,  # echo back for debugging
        "workspace_offset_m": workspace_offset_m,  # (0,0) if no PCG_Workspace tag
    }


def dispatch_batch(mcp, args: dict) -> dict:
    items = args.get("items") or []
    spawned = []
    errors = []
    for it in items:
        try:
            clamped, _ = _clamp_xy(it)
            rec = mcp.demo_spawn(
                asset_path=resolve_asset(clamped["asset_name"]),
                asset_name=clamped["asset_name"],
                x_m=float(clamped["x"]),
                y_m=float(clamped["y"]),
                z_m=float(clamped.get("z", 0)),
                yaw_deg=float(clamped.get("yaw_deg", 0)),
            )
            spawned.append(rec)
        except Exception as e:
            errors.append({"item": it, "error": f"{type(e).__name__}: {e}"})
    by_asset: dict = {}
    for s in spawned:
        by_asset[s["asset_name"]] = by_asset.get(s["asset_name"], 0) + 1
    return {"spawned": spawned, "total": len(spawned),
            "by_asset": by_asset, "errors": errors}


def dispatch_switch_level(mcp, args: dict) -> dict:
    return mcp.demo_switch_level(args.get("level_path", ""))


DISPATCHERS = {
    "spawn_object": dispatch_spawn,
    "spawn_batch": dispatch_batch,
    "delete_object": dispatch_delete,
    "modify_location": dispatch_move,
    "nudge_object": dispatch_nudge,
    "list_objects": dispatch_list,
    "clear_demo_objects": dispatch_clear,
    "generate_warehouse_layout": dispatch_warehouse,
    "switch_level": dispatch_switch_level,
}


def dispatch(mcp, tool_name: str, args: dict) -> dict:
    fn = DISPATCHERS.get(tool_name)
    if fn is None:
        raise KeyError(f"unknown demo tool: {tool_name}")
    return fn(mcp, args)


