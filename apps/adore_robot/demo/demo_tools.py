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

from typing import Callable

from llm.base import ToolDef

from .asset_registry import ASSET_NAMES, resolve as resolve_asset, pivot_z


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
            "object_budget":  {"type": "integer", "minimum": 4, "maximum": 200,
                               "description": (
                                   "Hard cap on total spawned objects (lights excluded). "
                                   "Pass this when the user explicitly asks for a count "
                                   "like '40 个物件 / put 40 things'. Structural shelves "
                                   "are preserved first; floor decor is randomly trimmed. "
                                   "Omit to let density/count params decide."
                               )},
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

def _resolve_pcg_workspace(mcp) -> dict:
    """Find user-tagged PCG Builder Volume (tag = 'PCG_Workspace') and
    return both its offset from BP_DemoOrigin AND its bounding size.

    Returns:
        {
            "offset_m": (dx, dy),  # always present, (0,0) on any failure
            "size_m":   (w, l, h) or None,  # None if extent unreadable
            "ref":      "/Game/...:PCGBuilderVolume_1" or None,
        }

    PCG Builder Volume root is a Brush/BoxComponent; we try several
    common UE Property names because UE5.8 MCP exposes them with varying
    snake/camel casings depending on the toolset version.

    All exceptions are swallowed -- callers treat missing fields as
    "no volume tagged, fall back to LLM-provided room_w/l_m".
    """
    out: dict = {"offset_m": (0.0, 0.0), "size_m": None, "ref": None}
    try:
        actors = mcp.call_tool_unwrapped(
            "toolset_registry.toolsets.core.scene.SceneTools.find_actors",
            {"tag": "PCG_Workspace"},
        )
        if isinstance(actors, dict):
            actors = actors.get("actors") or actors.get("results") or []
        if not isinstance(actors, list) or not actors:
            return out
        first = actors[0]
        ref = first.get("refPath") if isinstance(first, dict) else first
        if not ref:
            return out
        out["ref"] = ref

        props = mcp.get_actor_properties(ref, ["root_component"])
        rc = props.get("root_component") if isinstance(props, dict) else None
        if not isinstance(rc, dict):
            return out

        # --- offset ---
        loc = (rc.get("relative_location") or rc.get("relativeLocation")
               or rc.get("location") or {})
        if isinstance(loc, dict) and "x" in loc:
            volume_cm = (float(loc.get("x", 0)), float(loc.get("y", 0)))
            bp = mcp._demo_origin_world_cm()
            out["offset_m"] = (
                (volume_cm[0] - bp["x"]) / 100.0,
                (volume_cm[1] - bp["y"]) / 100.0,
            )

        # --- size: prefer box_extent (BoxComponent) * scale ---
        scale = (rc.get("relative_scale3d") or rc.get("relativeScale3D")
                 or {"x": 1, "y": 1, "z": 1})
        sx = float(scale.get("x", 1)); sy = float(scale.get("y", 1)); sz = float(scale.get("z", 1))
        extent_cm = None
        for k in ("box_extent", "boxExtent", "brush_extent", "extent"):
            v = rc.get(k)
            if isinstance(v, dict) and "x" in v:
                extent_cm = (float(v["x"]), float(v["y"]), float(v.get("z", 200)))
                break
        if extent_cm is None:
            # Fallback: dump every prop on the actor and scan for any
            # field whose name contains 'extent' (covers MCP toolset
            # versions that surface PCG Volume extent under unusual keys).
            try:
                all_props = mcp.list_actor_properties(ref)
                if isinstance(all_props, dict):
                    for kk, vv in all_props.items():
                        if "extent" in kk.lower() and isinstance(vv, dict) and "x" in vv:
                            extent_cm = (float(vv["x"]), float(vv["y"]), float(vv.get("z", 200)))
                            break
            except Exception:
                pass

        if extent_cm is not None:
            # box_extent is HALF-extent; full size = 2 * extent * scale
            out["size_m"] = (
                round(2 * extent_cm[0] * sx / 100.0, 2),
                round(2 * extent_cm[1] * sy / 100.0, 2),
                round(2 * extent_cm[2] * sz / 100.0, 2),
            )
    except Exception:
        pass
    return out


def _try_invalidate_viewports(mcp) -> None:
    """Best-effort viewport redraw -- silently no-op if the MCP server
    doesn't expose a redraw tool.

    UE5 Editor throttles viewport tick unless Realtime is enabled, which
    makes remote spawning look frozen until the user hovers the viewport.
    We try several known tool names; the first one that returns without
    raising wins. List of candidates was probed against UE5.8 MCP's
    EditorAppToolset (see tools/probe_mcp.py).
    """
    candidates = (
        "ToolsetRegistry.EditorAppToolset.InvalidateAllViewports",
        "ToolsetRegistry.EditorAppToolset.RedrawAllViewports",
        "ToolsetRegistry.EditorAppToolset.RedrawEditorViewports",
        "toolset_registry.toolsets.core.editor_app.EditorAppTools.invalidate_viewports",
    )
    for name in candidates:
        try:
            mcp.call_tool_unwrapped(name, {})
            return
        except Exception:
            continue


def dispatch_warehouse(
    mcp,
    args: dict,
    on_progress: Callable[[dict], None] | None = None,
    viewport_refresh_every: int = 5,
) -> dict:
    """Run xiaohuan procgen module + spawn each result via mcp.demo_spawn.

    14-param contract (v0.4.2 added object_budget): shelf_density /
    alley_width_m / forklift/worker/pallet/box/drum_count /
    room_w/l_m / seed / lighting_preset / rotation_jitter_deg / chaos /
    object_budget.

    PCG Builder Volume integration:
      - tag "PCG_Workspace" on a PCGBuilderVolume actor
      - offset_m  -> layout centred at volume center
      - size_m    -> overrides room_w_m / room_l_m so layout fits volume

    on_progress (v0.4.2): called with progress dicts at each milestone.
    Payload shapes:
      {"phase":"plan",   "total":N, "by_asset":{...}, "room_w":W, "room_l":L,
       "volume": True/False, "args": {...}}
      {"phase":"spawn",  "i":k, "total":N, "asset_name":s, "ok":bool}
      {"phase":"done",   "spawned":N, "failed":M, "elapsed_s":T}

    viewport_refresh_every: invalidate UE editor viewports every N spawns
    so the user doesn't have to click the editor to see new actors.
    """
    import time
    try:
        from pcg import generate_warehouse
    except ImportError:
        try:
            from ..pcg import generate_warehouse
        except ImportError:
            from apps.adore_robot.pcg import generate_warehouse

    # Optional clear
    if args.get("clear_first", True):
        try:
            mcp.demo_clear()
        except Exception:
            pass

    # PCG_Workspace volume resolution: offset + size (size may be None).
    ws = _resolve_pcg_workspace(mcp)
    workspace_offset_m = ws["offset_m"]
    volume_size_m = ws["size_m"]

    # Filter to pcg-recognized keys.
    pcg_keys = {
        "shelf_density", "alley_width_m", "forklift_count", "worker_count",
        "room_w_m", "room_l_m", "seed", "pallet_count", "box_count",
        "drum_count", "lighting_preset", "rotation_jitter_deg", "chaos",
        "object_budget",
    }
    pcg_args = {k: v for k, v in args.items() if k in pcg_keys}

    # Volume size overrides LLM-supplied room dimensions when available.
    # Margin: leave 0.5m on each side so wall-hugging drums aren't outside.
    room_override = False
    if volume_size_m is not None:
        w, l, _h = volume_size_m
        pcg_args["room_w_m"] = max(4.0, w - 1.0)
        pcg_args["room_l_m"] = max(4.0, l - 1.0)
        room_override = True

    result = generate_warehouse(**pcg_args)
    total = len(result.spawns)
    t_start = time.time()

    if on_progress:
        on_progress({
            "phase": "plan",
            "total": total,
            "by_asset": dict(result.by_asset),
            "room_w": pcg_args.get("room_w_m"),
            "room_l": pcg_args.get("room_l_m"),
            "volume_anchored": bool(ws.get("ref")),
            "volume_size_m": volume_size_m,
            "room_overridden_by_volume": room_override,
            "object_budget": pcg_args.get("object_budget"),
            "args": pcg_args,
        })

    spawned: list[dict] = []
    errors: list[dict] = []
    for i, sr in enumerate(result.spawns):
        asset_name = sr.asset_name
        try:
            asset_path = resolve_asset(asset_name)
        except KeyError:
            asset_path = resolve_asset("box")  # placeholder fallback
        # Floor offset: shift z up by pivot offset so mesh BOTTOM sits at sr.z.
        z_adjusted = float(sr.z) + pivot_z(asset_name)
        try:
            rec = mcp.demo_spawn(
                asset_path=asset_path,
                asset_name=asset_name,
                x_m=float(sr.x) + workspace_offset_m[0],
                y_m=float(sr.y) + workspace_offset_m[1],
                z_m=z_adjusted,
                yaw_deg=float(sr.yaw_deg),
            )
            spawned.append(rec)
            ok = True
        except Exception as e:
            errors.append({
                "asset_name": asset_name,
                "x": sr.x, "y": sr.y,
                "error": f"{type(e).__name__}: {e}",
            })
            ok = False

        if viewport_refresh_every > 0 and (i + 1) % viewport_refresh_every == 0:
            _try_invalidate_viewports(mcp)

        if on_progress:
            evt = {
                "phase": "spawn", "i": i + 1, "total": total,
                "asset_name": asset_name,
                "x": float(sr.x) + workspace_offset_m[0],
                "y": float(sr.y) + workspace_offset_m[1],
                "z": z_adjusted,
                "yaw_deg": float(sr.yaw_deg),
                "ok": ok,
            }
            if ok and spawned:
                last = spawned[-1]
                evt["actor_handle"] = last.get("actor_handle")
                evt["id_number"] = last.get("id_number")
            on_progress(evt)

    # Final viewport flush so the very last batch always shows up.
    _try_invalidate_viewports(mcp)

    by_asset: dict[str, int] = {}
    for s in spawned:
        by_asset[s.get("asset_name", "?")] = by_asset.get(s.get("asset_name", "?"), 0) + 1

    elapsed_s = round(time.time() - t_start, 2)
    if on_progress:
        on_progress({
            "phase": "done", "spawned": len(spawned),
            "failed": len(errors), "elapsed_s": elapsed_s,
        })

    return {
        "spawned": spawned,
        "total": len(spawned),
        "by_asset": by_asset,
        "errors": errors,
        "pcg_args": pcg_args,
        "workspace_offset_m": workspace_offset_m,
        "volume_size_m": volume_size_m,
        "room_overridden_by_volume": room_override,
        "elapsed_s": elapsed_s,
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


