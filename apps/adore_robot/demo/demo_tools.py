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
    off = _cached_workspace(mcp).get("offset_m", (0.0, 0.0))
    return mcp.demo_spawn(
        asset_path=resolve_asset(args["asset_name"]),
        asset_name=args["asset_name"],
        x_m=float(args["x"]) + off[0],
        y_m=float(args["y"]) + off[1],
        z_m=float(args.get("z", 0)) + pivot_z(args["asset_name"]),
        yaw_deg=float(args.get("yaw_deg", 0)),
    )

def dispatch_delete(mcp, args: dict) -> dict:
    return mcp.demo_delete(args["actor_handle"])

def dispatch_move(mcp, args: dict) -> dict:
    off = _cached_workspace(mcp).get("offset_m", (0.0, 0.0))
    return mcp.demo_move(
        handle=args["actor_handle"],
        x_m=float(args["x"]) + off[0],
        y_m=float(args["y"]) + off[1],
        z_m=float(args.get("z", 0)),
    )

def dispatch_nudge(mcp, args: dict) -> dict:
    # Nudge is a RELATIVE delta -- no workspace anchor needed; the
    # mcp.demo_nudge server-side reads current actor pos and adds dx/dy.
    return mcp.demo_nudge(
        handle=args["actor_handle"],
        dx_m=float(args.get("dx", 0)),
        dy_m=float(args.get("dy", 0)),
        dz_m=float(args.get("dz", 0)),
    )

def dispatch_list(mcp, _args: dict) -> dict:
    return mcp.demo_list()

def dispatch_clear(mcp, _args: dict) -> dict:
    invalidate_workspace_cache()  # user may re-place volume after clear
    return mcp.demo_clear()

# In-memory workspace cache. dispatch_spawn/batch/move query MCP every
# call would mean an extra ~30ms RPC per actor on a 60-item batch.
# Cache for 30s; cleared explicitly when level switches or demo clears.
_WORKSPACE_CACHE: dict = {"ws": None, "ts": 0.0}
_WORKSPACE_TTL_S = 30.0


def _cached_workspace(mcp) -> dict:
    import time
    now = time.time()
    cached = _WORKSPACE_CACHE.get("ws")
    if cached is None or (now - _WORKSPACE_CACHE.get("ts", 0)) > _WORKSPACE_TTL_S:
        try:
            cached = _resolve_pcg_workspace(mcp)
        except Exception:
            cached = {"offset_m": (0.0, 0.0), "size_m": None, "ref": None}
        _WORKSPACE_CACHE["ws"] = cached
        _WORKSPACE_CACHE["ts"] = now
    return cached


def invalidate_workspace_cache() -> None:
    """Clear the workspace cache. Call after switch_level / clear_demo
    when the user might have moved or replaced the PCGBuilderVolume.
    """
    _WORKSPACE_CACHE["ws"] = None
    _WORKSPACE_CACHE["ts"] = 0.0


def _resolve_pcg_workspace(mcp) -> dict:
    """Find the user's workspace volume and return offset + bounds.

    Resolution order:
      1. find_actors {tag: 'PCGVolume'} -- explicit user opt-in.
         Works for any actor type (TriggerVolume, APCGVolume, custom BP).
      2. find_actors {glob: '*TriggerVolume*'} -- fallback. If the level
         has exactly one TriggerVolume we adopt it silently; if there
         are multiple we still pick the first but log a hint.
      3. find_actors {glob: '*PCGVolume*' / '*PCGBuilderVolume*'} -- last
         fallback for APCGVolume placements without a tag.

    Returns:
        {"offset_m": (dx, dy), "size_m": (w,l,h)|None, "ref": str|None,
         "resolved_by": "tag"|"trigger_volume_glob"|"pcg_volume_glob"|None}

    All exceptions are swallowed -- callers treat missing fields as
    "no volume tagged, fall back to LLM-provided room_w/l_m".
    """
    out: dict = {"offset_m": (0.0, 0.0), "size_m": None, "ref": None,
                 "resolved_by": None}
    try:
        ref = None
        # Stage 1: explicit tag.
        try:
            tagged = mcp.call_tool_unwrapped(
                "toolset_registry.toolsets.core.scene.SceneTools.find_actors",
                {"tag": "PCGVolume"},
            )
            if isinstance(tagged, dict):
                tagged = tagged.get("actors") or tagged.get("results") or []
            if isinstance(tagged, list) and tagged:
                first = tagged[0]
                ref = first.get("refPath") if isinstance(first, dict) else first
                if ref:
                    out["resolved_by"] = "tag"
        except Exception:
            pass

        # Stage 2: TriggerVolume glob fallback (user just dropped a
        # TriggerVolume in the level without tagging it).
        if ref is None:
            try:
                tvs = mcp.call_tool_unwrapped(
                    "toolset_registry.toolsets.core.scene.SceneTools.find_actors",
                    {"glob": "*TriggerVolume*"},
                )
                if isinstance(tvs, dict):
                    tvs = tvs.get("actors") or tvs.get("results") or []
                if isinstance(tvs, list) and tvs:
                    first = tvs[0]
                    ref = first.get("refPath") if isinstance(first, dict) else first
                    if ref:
                        out["resolved_by"] = "trigger_volume_glob"
            except Exception:
                pass

        # Stage 3: APCGVolume glob fallback.
        if ref is None:
            for pat in ("*PCGBuilderVolume*", "*PCGVolume*"):
                try:
                    res = mcp.call_tool_unwrapped(
                        "toolset_registry.toolsets.core.scene.SceneTools.find_actors",
                        {"glob": pat},
                    )
                    if isinstance(res, dict):
                        res = res.get("actors") or res.get("results") or []
                    if isinstance(res, list) and res:
                        first = res[0]
                        ref = first.get("refPath") if isinstance(first, dict) else first
                        if ref:
                            out["resolved_by"] = "pcg_volume_glob"
                            break
                except Exception:
                    continue

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

        # --- size: try box_extent (BoxComponent / BrushComponent) * scale ---
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
            out["size_m"] = (
                round(2 * extent_cm[0] * sx / 100.0, 2),
                round(2 * extent_cm[1] * sy / 100.0, 2),
                round(2 * extent_cm[2] * sz / 100.0, 2),
            )
    except Exception:
        pass
    return out


# UE5.8 MCP exposes 39 tools; NONE of them are named *Invalidate* /
# *Redraw* / *Refresh*. (Verified via /api/mcp/tools 2026-05-22.)
# The only documented paths to force an editor viewport tick are:
#   1) ProgrammaticToolset.execute_tool_script + import unreal +
#      unreal.EditorLevelLibrary.editor_invalidate_viewports()
#      -- but the script sandbox may disallow `import unreal`; we probe
#      get_execution_environment once and cache the verdict.
#   2) User manually enables Realtime (Ctrl+R / viewport toolbar ⚡)
#      in UE Editor viewport.
#   3) CaptureEditorImage as a side effect of the front-end PIP refresh
#      -- this DOES force a render frame and is the path that makes the
#      ADORE web UI feel real-time. The actual UE Editor viewport window
#      still only ticks when capture/realtime fires, but the ADORE
#      preview is the visible surface the user watches during a demo.
_INVALIDATE_STATE: dict = {
    "mode": None,               # "script" | "camera" | "disabled"
    "cam_cache": None,           # cached GetCameraTransform result for camera nudge
    "hint_emitted": False,       # summary tip shown at most once per session
}

_INVALIDATE_SCRIPT_INVALIDATE = (
    "def run():\n"
    "    import unreal\n"
    "    unreal.EditorLevelLibrary.editor_invalidate_viewports()\n"
    "    return {'ok': True}\n"
)

_TOOL_EXEC_SCRIPT = (
    "toolset_registry.toolsets.core.programmatic."
    "ProgrammaticToolset.execute_tool_script"
)
_TOOL_GET_CAM = "ToolsetRegistry.EditorAppToolset.GetCameraTransform"
_TOOL_SET_CAM = "ToolsetRegistry.EditorAppToolset.SetCameraTransform"


def viewport_hint_needed() -> bool:
    """True the first time we determine invalidate is unavailable.
    dispatch_warehouse appends this to the summary so the chat surface
    explains why the actual UE viewport window looks frozen between
    spawns -- user should enable Realtime (Ctrl+R) on the viewport,
    or build the BP RefreshViewport function we documented in
    docs/scene_foundry_bp_contract.md.
    """
    if _INVALIDATE_STATE["mode"] == "disabled" and not _INVALIDATE_STATE["hint_emitted"]:
        _INVALIDATE_STATE["hint_emitted"] = True
        return True
    return False


def _try_invalidate_viewports(mcp) -> None:
    """Best-effort viewport redraw. Two-stage probe on first call:

      1. Try `execute_tool_script` with `import unreal` -- this is the
         only direct invalidate path. If the script sandbox allows the
         unreal module, we cache mode="script" and use it forever.
      2. Fallback to GetCameraTransform + SetCameraTransform-with-same-
         transform. Setting the camera to its current value is a no-op
         visually but forces the viewport to tick. Cache mode="camera".
      3. If both fail (no sandbox + no editor app toolset), cache
         mode="disabled" and emit the hint via viewport_hint_needed().

    None of UE5.8 MCP's 39 native tools is named *Invalidate* /
    *Redraw* / *Refresh*, so the indirect script + camera-nudge
    paths above are the only options without user BP intervention.
    """
    state = _INVALIDATE_STATE
    if state["mode"] == "disabled":
        return

    if state["mode"] is None:
        # Stage 1 probe -- script-based invalidate.
        try:
            mcp.call_tool_unwrapped(_TOOL_EXEC_SCRIPT,
                                    {"script": _INVALIDATE_SCRIPT_INVALIDATE})
            state["mode"] = "script"
            return
        except Exception:
            pass
        # Stage 2 probe -- camera nudge.
        try:
            cam = mcp.call_tool_unwrapped(_TOOL_GET_CAM, {})
            if isinstance(cam, dict):
                state["cam_cache"] = cam
                state["mode"] = "camera"
                # exercise the round-trip immediately so we KNOW it works
                mcp.call_tool_unwrapped(_TOOL_SET_CAM, {"transform": cam})
                return
        except Exception:
            pass
        state["mode"] = "disabled"
        return

    try:
        if state["mode"] == "script":
            mcp.call_tool_unwrapped(_TOOL_EXEC_SCRIPT,
                                    {"script": _INVALIDATE_SCRIPT_INVALIDATE})
        elif state["mode"] == "camera":
            cam = state.get("cam_cache")
            if cam is None:
                cam = mcp.call_tool_unwrapped(_TOOL_GET_CAM, {})
                state["cam_cache"] = cam
            mcp.call_tool_unwrapped(_TOOL_SET_CAM, {"transform": cam})
    except Exception:
        # One-time failure -> permanently downgrade rather than keep
        # spamming a broken tool name. Next session will re-probe.
        state["mode"] = "disabled"


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
      - tag "PCGVolume" on a PCGBuilderVolume actor
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

    # PCGVolume volume resolution: offset + size (size may be None).
    # Force a fresh fetch -- user may have just moved the volume.
    invalidate_workspace_cache()
    ws = _cached_workspace(mcp)
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
        done_payload = {
            "phase": "done", "spawned": len(spawned),
            "failed": len(errors), "elapsed_s": elapsed_s,
        }
        if viewport_hint_needed():
            done_payload["viewport_hint"] = (
                "UE viewport 不会自动刷新 -- 请按 Ctrl+R 启用 viewport Realtime, "
                "或在 PCGVolume 蓝图里加 RefreshViewport function (见 docs/scene_foundry_bp_contract.md)"
            )
        on_progress(done_payload)

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
    off = _cached_workspace(mcp).get("offset_m", (0.0, 0.0))
    spawned = []
    errors = []
    for it in items:
        try:
            clamped, _ = _clamp_xy(it)
            rec = mcp.demo_spawn(
                asset_path=resolve_asset(clamped["asset_name"]),
                asset_name=clamped["asset_name"],
                x_m=float(clamped["x"]) + off[0],
                y_m=float(clamped["y"]) + off[1],
                z_m=float(clamped.get("z", 0)) + pivot_z(clamped["asset_name"]),
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
    invalidate_workspace_cache()  # different level => different volume
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


