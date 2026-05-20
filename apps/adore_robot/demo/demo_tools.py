"""v0 demo tools: spawn / delete / move / list + 3 layout generators.

Source of truth: apps/adore_robot/docs/demo_v0_simplified_contract.md
§2 (primitive schemas) + §6 (unreal-python snippets) + §10 (layout gen).

Each tool definition pairs a ToolDef (for the LLM) with a Python script
builder. The script is injected via MCP `execute_tool_script` so it runs
inside UE's PythonScriptPlugin sandbox.

LLM only ever sees asset_name enum strings. Server resolves to UE paths
via asset_registry.ASSET_REGISTRY immediately before script injection.
"""

from __future__ import annotations

import json

from llm.base import ToolDef

from .asset_registry import ASSET_NAMES, ASSET_REGISTRY


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


# ─── Script builders (each returns a single Python source string) ───────

_HEAD = f"""
import unreal, random, json
ASSET_REGISTRY = {json.dumps(ASSET_REGISTRY)}
def _anchor():
    aes = unreal.EditorActorSubsystem()
    for a in aes.get_all_level_actors():
        if a.get_actor_label() == "BP_DemoOrigin" or "DemoOrigin" in a.get_name():
            return a.get_actor_location()
    return unreal.Vector(0, 0, 0)

def _spawn(asset_name, x_m, y_m, z_m=0.0, yaw_deg=0.0, anchor=None):
    anchor = anchor or _anchor()
    mesh = unreal.load_object(None, ASSET_REGISTRY[asset_name])
    loc = unreal.Vector(anchor.x + x_m*100, anchor.y + y_m*100, anchor.z + z_m*100)
    rot = unreal.Rotator(0, 0, yaw_deg)
    actor = unreal.EditorActorSubsystem().spawn_actor_from_object(mesh, loc, rot)
    actor.tags = ["demo_v0_spawned", "demo_v0_asset:" + asset_name]
    return actor.get_name()

def _find(actor_handle):
    aes = unreal.EditorActorSubsystem()
    for a in aes.get_all_level_actors():
        if a.get_name() == actor_handle:
            return a
    return None

def _clear_demo():
    aes = unreal.EditorActorSubsystem()
    n = 0
    for a in list(aes.get_all_level_actors()):
        if "demo_v0_spawned" in [str(t) for t in a.tags]:
            aes.destroy_actor(a); n += 1
    return n
"""


def build_spawn_object_script(args: dict) -> str:
    """args: asset_name, x, y, z?, yaw_deg?"""
    return _HEAD + f"""
res = {{"actor_handle": _spawn(
    {json.dumps(args['asset_name'])},
    {float(args['x'])}, {float(args['y'])},
    {float(args.get('z', 0))}, {float(args.get('yaw_deg', 0))})}}
return res
"""


def build_delete_object_script(args: dict) -> str:
    return _HEAD + f"""
handle = {json.dumps(args['actor_handle'])}
a = _find(handle)
if a is None:
    res = {{"error": "no such actor: " + handle}}
elif "demo_v0_spawned" not in [str(t) for t in a.tags]:
    res = {{"error": "actor not owned by demo session: " + handle}}
else:
    unreal.EditorActorSubsystem().destroy_actor(a)
    res = {{"deleted": handle}}
return res
"""


def build_modify_location_script(args: dict) -> str:
    return _HEAD + f"""
handle = {json.dumps(args['actor_handle'])}
a = _find(handle)
if a is None:
    res = {{"error": "no such actor: " + handle}}
else:
    anchor = _anchor()
    new_loc = unreal.Vector(
        anchor.x + ({float(args['x'])}) * 100,
        anchor.y + ({float(args['y'])}) * 100,
        anchor.z + ({float(args.get('z', 0))}) * 100,
    )
    a.set_actor_location(new_loc, sweep=False, teleport=True)
    res = {{"actor_handle": handle, "new_xyz_m": [{float(args['x'])}, {float(args['y'])}, {float(args.get('z', 0))}]}}
return res
"""


def build_list_objects_script(_args: dict) -> str:
    return _HEAD + """
aes = unreal.EditorActorSubsystem()
anchor = _anchor()
out = []
for a in aes.get_all_level_actors():
    tags = [str(t) for t in a.tags]
    if "demo_v0_spawned" not in tags:
        continue
    asset = "unknown"
    for t in tags:
        if t.startswith("demo_v0_asset:"):
            asset = t.split(":", 1)[1]; break
    loc = a.get_actor_location()
    rot = a.get_actor_rotation()
    out.append({
        "actor_handle": a.get_name(),
        "asset_name": asset,
        "x": (loc.x - anchor.x) / 100,
        "y": (loc.y - anchor.y) / 100,
        "z": (loc.z - anchor.z) / 100,
        "yaw_deg": rot.yaw,
    })
return {"objects": out}
"""


def build_clear_script(_args: dict) -> str:
    return _HEAD + """
return {"cleared": _clear_demo()}
"""


def build_warehouse_layout_script(args: dict) -> str:
    """xiaohuan demo_v0_simplified_contract.md §10.3 algorithm, baked in."""
    p = {
        "room_w_m": float(args.get("room_w_m", 30)),
        "room_l_m": float(args.get("room_l_m", 40)),
        "shelf_rows": int(args.get("shelf_rows", 3)),
        "shelves_per_row": int(args.get("shelves_per_row", 6)),
        "aisle_width_m": float(args.get("aisle_width_m", 3.0)),
        "forklift_count": int(args.get("forklift_count", 1)),
        "pallet_count": int(args.get("pallet_count", 10)),
        "box_count": int(args.get("box_count", 5)),
        "drum_count": int(args.get("drum_count", 3)),
        "worker_count": int(args.get("worker_count", 0)),
        "seed": int(args.get("seed", 0)),
        "clear_first": bool(args.get("clear_first", True)),
    }
    return _HEAD + f"""
P = {json.dumps(p)}
SHELF_W, SHELF_D = 1.6, 1.2
if P["clear_first"]:
    _clear_demo()
rng = random.Random(P["seed"])
anchor = _anchor()
spawned = []
row_pitch = SHELF_D + P["aisle_width_m"]
total_span = P["shelf_rows"] * SHELF_D + (P["shelf_rows"] - 1) * P["aisle_width_m"]
y_start = -total_span / 2 + SHELF_D / 2
row_x_extent = (P["shelves_per_row"] - 1) * SHELF_W
x_start = -row_x_extent / 2
aisle_y = []
for r in range(P["shelf_rows"]):
    y = y_start + r * row_pitch
    for s in range(P["shelves_per_row"]):
        x = x_start + s * SHELF_W
        h = _spawn("shelf", x, y, 0, 0, anchor)
        spawned.append({{"actor_handle": h, "asset_name": "shelf", "x": x, "y": y}})
    if r < P["shelf_rows"] - 1:
        aisle_y.append(y + SHELF_D/2 + P["aisle_width_m"]/2)
for i in range(P["forklift_count"]):
    ay = rng.choice(aisle_y) if aisle_y else (y_start - row_pitch/2 if i%2==0 else y_start + total_span)
    ax = rng.uniform(x_start, x_start + row_x_extent)
    yaw = rng.choice([0,90,180,270])
    h = _spawn("forklift", ax, ay, 0, yaw, anchor)
    spawned.append({{"actor_handle": h, "asset_name": "forklift", "x": ax, "y": ay}})
for _ in range(P["pallet_count"]):
    px = rng.uniform(x_start - 0.5, x_start + row_x_extent + 0.5)
    py = rng.uniform(-total_span/2 - 1, total_span/2 + 1)
    h = _spawn("pallet", px, py, 0, rng.choice([0,90]), anchor)
    spawned.append({{"actor_handle": h, "asset_name": "pallet", "x": px, "y": py}})
for _ in range(P["box_count"]):
    bx = rng.uniform(-P["room_w_m"]/2 + 1, P["room_w_m"]/2 - 1)
    by = rng.uniform(-P["room_l_m"]/2 + 1, P["room_l_m"]/2 - 1)
    h = _spawn("box", bx, by, 0, rng.uniform(0, 360), anchor)
    spawned.append({{"actor_handle": h, "asset_name": "box", "x": bx, "y": by}})
for _ in range(P["drum_count"]):
    dx = rng.choice([-P["room_w_m"]/2 + 1, P["room_w_m"]/2 - 1])
    dy = rng.uniform(-P["room_l_m"]/2 + 1, P["room_l_m"]/2 - 1)
    h = _spawn("drum", dx, dy, 0, 0, anchor)
    spawned.append({{"actor_handle": h, "asset_name": "drum", "x": dx, "y": dy}})
for _ in range(P["worker_count"]):
    wx = rng.uniform(-P["room_w_m"]/2 + 2, P["room_w_m"]/2 - 2)
    wy = rng.uniform(-P["room_l_m"]/2 + 2, P["room_l_m"]/2 - 2)
    yaw = rng.uniform(0, 360)
    h = _spawn("worker", wx, wy, 0, yaw, anchor)
    spawned.append({{"actor_handle": h, "asset_name": "worker", "x": wx, "y": wy}})
by_asset = {{}}
for s in spawned:
    by_asset[s["asset_name"]] = by_asset.get(s["asset_name"], 0) + 1
return {{"spawned": spawned, "total": len(spawned), "by_asset": by_asset}}
"""


SCRIPT_BUILDERS = {
    "spawn_object": build_spawn_object_script,
    "delete_object": build_delete_object_script,
    "modify_location": build_modify_location_script,
    "list_objects": build_list_objects_script,
    "clear_demo_objects": build_clear_script,
    "generate_warehouse_layout": build_warehouse_layout_script,
}


def build_script_for(tool_name: str, args: dict) -> str:
    """Return injectable unreal-python source for a demo tool call.

    The script always assigns its result to a `res` local. The MCP server
    side captures `res` and returns it.
    """
    if tool_name not in SCRIPT_BUILDERS:
        raise KeyError(f"unknown demo tool: {tool_name}")
    return SCRIPT_BUILDERS[tool_name](args)
