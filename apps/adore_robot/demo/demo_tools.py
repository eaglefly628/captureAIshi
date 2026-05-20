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
    description="Translate an existing actor to new scene-local (x,y) meters.",
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
        "forklifts in aisles, pallets/boxes/drums scattered, optional workers."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "room_w_m": {"type": "number", "minimum": 10, "maximum": 60, "default": 30},
            "room_l_m": {"type": "number", "minimum": 10, "maximum": 60, "default": 40},
            "shelf_rows": {"type": "integer", "minimum": 1, "maximum": 8, "default": 3},
            "shelves_per_row": {"type": "integer", "minimum": 2, "maximum": 12, "default": 6},
            "aisle_width_m": {"type": "number", "minimum": 2.0, "maximum": 5.0, "default": 3.0},
            "forklift_count": {"type": "integer", "minimum": 0, "maximum": 5, "default": 1},
            "pallet_count": {"type": "integer", "minimum": 0, "maximum": 50, "default": 10},
            "box_count": {"type": "integer", "minimum": 0, "maximum": 30, "default": 5},
            "drum_count": {"type": "integer", "minimum": 0, "maximum": 20, "default": 3},
            "worker_count": {"type": "integer", "minimum": 0, "maximum": 8, "default": 0},
            "seed": {"type": "integer", "default": 0},
            "clear_first": {"type": "boolean", "default": True},
        },
    },
)

CLEAR_DEMO_TOOL = ToolDef(
    name="clear_demo_objects",
    description="Delete every actor tagged demo_v0_spawned.",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    },
)


DEMO_TOOLS: list[ToolDef] = [
    SPAWN_OBJECT_TOOL,
    DELETE_OBJECT_TOOL,
    MODIFY_LOCATION_TOOL,
    LIST_OBJECTS_TOOL,
    GENERATE_WAREHOUSE_TOOL,
    CLEAR_DEMO_TOOL,
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

def dispatch_list(mcp, _args: dict) -> dict:
    return mcp.demo_list()

def dispatch_clear(mcp, _args: dict) -> dict:
    return mcp.demo_clear()

def dispatch_warehouse(mcp, args: dict) -> dict:
    return mcp.demo_generate_warehouse(asset_resolver=resolve_asset, **args)


DISPATCHERS = {
    "spawn_object": dispatch_spawn,
    "delete_object": dispatch_delete,
    "modify_location": dispatch_move,
    "list_objects": dispatch_list,
    "clear_demo_objects": dispatch_clear,
    "generate_warehouse_layout": dispatch_warehouse,
}


def dispatch(mcp, tool_name: str, args: dict) -> dict:
    fn = DISPATCHERS.get(tool_name)
    if fn is None:
        raise KeyError(f"unknown demo tool: {tool_name}")
    return fn(mcp, args)


