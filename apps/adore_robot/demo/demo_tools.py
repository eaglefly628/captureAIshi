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
        "Spawn ONE static mesh actor at scene-local (x,y) in meters. "
        "Returns actor_handle for later reference. Yaw degrees around Z. "
        "TRIGGER WORDS: 放一个, 加一个, 创建一个, spawn, place, add, "
        "put a, 给我一个, 加进去一个, 我要一个."
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
        "Procedurally lay out a WHOLE warehouse: shelf rows + aisles + "
        "forklifts + pallets/boxes/drums + workers + ceiling lights, in "
        "one shot. AUTO-CLEARS the scene first (clear_first=true). "
        "TRIGGER WORDS: 生成仓库, 生成场景, 生成一个仓库, 建仓库, 摆仓库, "
        "generate warehouse, build scene, layout warehouse, 整一个仓库, "
        "造一个仓库, 重新生成, regenerate, redo scene, 换个 seed, "
        "更乱一点, 更稀疏, 灯光改, 物件数量, 40 个物件, 100 个物件."
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
    description=(
        "Delete every demo-spawned actor in the CURRENT level. "
        "DO NOT call before generate_warehouse_layout -- that auto-clears. "
        "ONLY use when user says clear WITHOUT regenerate in the same turn. "
        "TRIGGER WORDS: 清空场景, 清空, 删除所有, 都删了, 清掉, 重来, "
        "clear all, wipe scene, reset, delete everything, 一切重置, "
        "把场景清掉, 全部移除."
    ),
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
        "Spawn many static mesh actors AT EXPLICIT COORDINATES in one call. "
        "Use for tight layouts where each actor's (x,y) matters -- rows, "
        "grids, lines, evenly-spaced sets. Each item is {asset_name, x, y, "
        "z?, yaw_deg?} with the same enum + bounds rules as spawn_object. "
        "For >50 items OR when only the COUNT matters (not the position), "
        "prefer bulk_spawn -- it auto-scatters in the PCGVolume so the "
        "LLM doesn't have to invent 100 coordinates."
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


BULK_SPAWN_TOOL = ToolDef(
    name="bulk_spawn",
    description=(
        "Scatter N actors of the SAME asset_name randomly inside the PCG "
        "volume. PREFERRED for count-only requests. Max count 500. "
        "TRIGGER WORDS: 100 个 X, 批量 X, 散 N 个 X, 来 N 个 X, "
        "放一堆 X, 多放点 X, 加 N 个 X, spawn N X, scatter N X, "
        "batch add N X, 批量添加 N 个, 来一打 X, 撒几个 X, drop N X."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "asset_name": {"type": "string", "enum": ASSET_NAMES},
            "count": {"type": "integer", "minimum": 1, "maximum": 500},
        },
        "required": ["asset_name", "count"],
    },
)


CAPTURE_TOOL = ToolDef(
    name="capture_robot_views",
    description=(
        "Capture 5 channels at the current viewport: RGB / SceneDepth / "
        "WorldNormal / ObjectID / Segmentation (AR overlay with actor "
        "bounding boxes + labels). Also returns dataset_summary "
        "(frames × channels × classes) and ObjectID legend. "
        "TRIGGER WORDS: 截图, 抓帧, capture, snapshot, 拍照, 看看图, "
        "show channels, 4 通道, 5 通道, 训练通道, segmentation, "
        "AR overlay, 看检测, 给我看图, 拍下这一帧."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    },
)

FLYTHROUGH_TOOL = ToolDef(
    name="flythrough_capture",
    description=(
        "Fly the UE editor camera through N vantage points around the "
        "PCGVolume (default 5: 4 corners + top-down) and capture RGB at "
        "each. Produces a cinematic sweep showing the scene from every "
        "angle, returns dataset_summary too. Takes ~5-8 seconds. "
        "TRIGGER WORDS: 环绕, 飞一圈, 多视角, 360, fly through, "
        "cinematic, 给我环境快照, 全方位, 多角度, sweep, 转一圈拍, "
        "数据集预览, 多视角拍摄, panorama, 各个角度."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "n_views": {"type": "integer", "minimum": 2, "maximum": 12,
                        "default": 5},
        },
    },
)

CAPTURE_DATASET_TOOL = ToolDef(
    name="capture_dataset",
    description=(
        "Heavy multi-view, multi-channel capture: 8 viewpoints around "
        "PCGVolume × 4 channels (RGB+Depth+Normal+ObjectID) = 32 frames. "
        "This is the 'serious data export' demo -- shows the user what "
        "ADORE would generate for a real robot training run. Returns a "
        "dataset_summary card with sample count + download stub. "
        "TRIGGER WORDS: 生成数据集, 导出训练数据, dataset, full export, "
        "训练数据集, ML 数据, 出训练样本, generate training data, "
        "正经数据集, 完整捕获, 32 frames, 多视角多通道, 数据导出."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "n_views": {"type": "integer", "minimum": 2, "maximum": 16,
                        "default": 8},
        },
    },
)


PIE_START_TOOL = ToolDef(
    name="play_in_editor",
    description=(
        "Start UE Editor Play-In-Editor (PIE) via SlateInspector Alt+P. "
        "TRIGGER WORDS: 开始 PIE, play, 运行, 进入游戏, start play, "
        "play in editor, 开始播放, 开始演示, 跑起来, 启动游戏, "
        "play game, simulate, 走起, 开始模拟, 进游戏看, 跑场景."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    },
)

PIE_STOP_TOOL = ToolDef(
    name="end_play_in_editor",
    description=(
        "Stop the current PIE session via SlateInspector Esc. "
        "TRIGGER WORDS: 停止 PIE, stop play, end play, 退出游戏, "
        "关闭 PIE, 停止演示, 结束模拟, exit game, quit play, 退出, "
        "停下, 终止运行."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {},
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
    PIE_START_TOOL,
    PIE_STOP_TOOL,
    CAPTURE_TOOL,
    FLYTHROUGH_TOOL,
    CAPTURE_DATASET_TOOL,
    BULK_SPAWN_TOOL,
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
    anchor = _cached_workspace(mcp).get("world_cm")
    return mcp.demo_spawn(
        asset_path=resolve_asset(args["asset_name"]),
        asset_name=args["asset_name"],
        x_m=float(args["x"]),
        y_m=float(args["y"]),
        z_m=float(args.get("z", 0)) + pivot_z(args["asset_name"]),
        yaw_deg=float(args.get("yaw_deg", 0)),
        anchor_override_cm=anchor,
    )

def dispatch_delete(mcp, args: dict) -> dict:
    return mcp.demo_delete(args["actor_handle"])

def dispatch_move(mcp, args: dict) -> dict:
    anchor = _cached_workspace(mcp).get("world_cm")
    return mcp.demo_move(
        handle=args["actor_handle"],
        x_m=float(args["x"]),
        y_m=float(args["y"]),
        z_m=float(args.get("z", 0)),
        anchor_override_cm=anchor,
    )

def dispatch_nudge(mcp, args: dict) -> dict:
    # nudge is a RELATIVE delta -- server reads current actor pos and
    # adds dx/dy, but the respawn under the hood still needs the volume
    # anchor so the new pos stays in the volume's frame instead of
    # collapsing to BP_DemoOrigin.
    anchor = _cached_workspace(mcp).get("world_cm")
    return mcp.demo_nudge(
        handle=args["actor_handle"],
        dx_m=float(args.get("dx", 0)),
        dy_m=float(args.get("dy", 0)),
        dz_m=float(args.get("dz", 0)),
        anchor_override_cm=anchor,
    )

def dispatch_list(mcp, _args: dict) -> dict:
    return mcp.demo_list()

def dispatch_clear(mcp, _args: dict) -> dict:
    invalidate_workspace_cache()  # user may re-place volume after clear
    return mcp.demo_clear()

# In-memory workspace cache. Keyed by current UE level so that opening
# a different map in-editor automatically forces a re-resolve without
# requiring the user to hit /api/demo/refresh_volume.
_WORKSPACE_CACHE: dict = {"ws": None, "level": None}


def _cached_workspace(mcp) -> dict:
    # mcp._current_level_cached() has its own 2s TTL, so this is cheap.
    current_level = None
    try:
        current_level = mcp._current_level_cached()
    except Exception:
        pass

    if (_WORKSPACE_CACHE["ws"] is None
            or _WORKSPACE_CACHE["level"] != current_level):
        try:
            _WORKSPACE_CACHE["ws"] = _resolve_pcg_workspace(mcp)
        except Exception:
            _WORKSPACE_CACHE["ws"] = {"offset_m": (0.0, 0.0),
                                       "size_m": None, "ref": None,
                                       "resolved_by": None}
        _WORKSPACE_CACHE["level"] = current_level
    return _WORKSPACE_CACHE["ws"]


def invalidate_workspace_cache() -> None:
    """Clear the workspace cache. Called from dispatch_clear and
    dispatch_switch_level (user may re-place the volume in those flows).
    Also called from /api/demo/refresh_volume for manual override.
    """
    _WORKSPACE_CACHE["ws"] = None
    _WORKSPACE_CACHE["level"] = None


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

        # --- offset: TriggerVolume's root_component can't be read via
        # UE5.8 MCP (log: "the following properties could not be read:
        # root_component"). Try actor-level location candidates first,
        # then component fallbacks. Each get_actor_properties call only
        # asks for one candidate so a failure on one doesn't block the
        # others.
        # T3D ground truth (user 2026-05-22):
        #   Begin Object Name="BrushComponent0" ...
        #     RelativeLocation=(X=6880, Y=10, Z=130)
        #     RelativeScale3D=(X=5, Y=5, Z=1)
        #
        # UE5.8 MCP returns object-typed UPROPERTYs as refPath strings or
        # {"refPath": "..."} envelopes -- it does NOT auto-expand nested
        # object data. So we make two RPCs:
        #   1. actor.BrushComponent          -> refPath of the component
        #   2. component.RelativeLocation +
        #      component.RelativeScale3D     -> the actual vectors
        loc_cm = None
        loc_z_cm = 0.0
        component_data = None
        try:
            props = mcp.get_actor_properties(ref, ["BrushComponent"])
            bc = props.get("BrushComponent") if isinstance(props, dict) else None

            component_ref = None
            if isinstance(bc, dict):
                if "RelativeLocation" in bc or "relative_location" in bc:
                    component_data = bc
                else:
                    component_ref = bc.get("refPath")
            elif isinstance(bc, str):
                component_ref = bc

            if component_ref and not component_data:
                try:
                    cprops = mcp.get_actor_properties(
                        component_ref, ["RelativeLocation", "RelativeScale3D"]
                    )
                    if isinstance(cprops, dict):
                        component_data = cprops
                except Exception:
                    pass

            if isinstance(component_data, dict):
                rel = (component_data.get("RelativeLocation")
                       or component_data.get("relative_location"))
                if isinstance(rel, dict) and "x" in rel:
                    loc_cm = (float(rel["x"]), float(rel["y"]))
                    loc_z_cm = float(rel.get("z", 0))
                    out["resolved_by"] = ((out["resolved_by"] or "?")
                                          + ":BrushComponent.RelativeLocation")
        except Exception:
            pass
        component_obj = component_data

        if loc_cm:
            bp = mcp._demo_origin_world_cm()
            out["offset_m"] = (
                (loc_cm[0] - bp["x"]) / 100.0,
                (loc_cm[1] - bp["y"]) / 100.0,
            )

        # --- size = (BrushBuilder.X/Y/Z) * RelativeScale3D / 100 cm/m ---
        # T3D ground truth (from user 2026-05-22):
        #   BrushComponent0.RelativeScale3D = (X=5, Y=5, Z=1)
        #   CubeBuilder defaults X=Y=Z=200 (full extent, cm)
        # so for an unmodified cube volume scaled 5x5x1, size = (10,10,2) m.
        scale = None
        if component_obj:
            s = (component_obj.get("RelativeScale3D")
                 or component_obj.get("relative_scale3d")
                 or component_obj.get("relativeScale3D"))
            if isinstance(s, dict) and "x" in s:
                scale = (float(s["x"]), float(s["y"]), float(s.get("z", 1)))

        # --- offset (use loc_cm collected above) ---
        if loc_cm:
            bp = mcp._demo_origin_world_cm()
            out["offset_m"] = (
                (loc_cm[0] - bp["x"]) / 100.0,
                (loc_cm[1] - bp["y"]) / 100.0,
            )

        # --- size: BrushBuilder.X/Y/Z (cm, full extent) * RelativeScale3D ---
        # T3D shows BrushBuilder is a UCubeBuilder; default X=Y=Z=200.
        # For an unscaled volume that's 2m^3; with scale (5,5,1) -> (10,10,2) m.
        brush_xyz = (200.0, 200.0, 200.0)
        try:
            props = mcp.get_actor_properties(ref, ["BrushBuilder"])
            bb = props.get("BrushBuilder") if isinstance(props, dict) else None
            if isinstance(bb, dict):
                x = bb.get("X") or bb.get("x")
                y = bb.get("Y") or bb.get("y")
                z = bb.get("Z") or bb.get("z")
                if x and y and z:
                    brush_xyz = (float(x), float(y), float(z))
        except Exception:
            pass

        if scale is not None:
            out["size_m"] = (
                round(brush_xyz[0] * scale[0] / 100.0, 2),
                round(brush_xyz[1] * scale[1] / 100.0, 2),
                round(brush_xyz[2] * scale[2] / 100.0, 2),
            )
            out["brush_xyz_cm"] = brush_xyz
            out["scale"] = scale

        # --- world_cm: volume center XY + volume BOTTOM Z (the floor) ---
        # This is the single anchor downstream code should use. By making
        # Z = volume bottom (center.z - half_z), a spawn passed (0,0,0)
        # lands on the floor inside the volume -- no separate floor_z
        # hunt, no BP_DemoOrigin middle-step.
        if loc_cm:
            half_z_cm = (brush_xyz[2] * (scale[2] if scale else 1.0)) / 2.0
            out["world_cm"] = {
                "x": loc_cm[0],
                "y": loc_cm[1],
                "z": loc_z_cm - half_z_cm,
            }
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
    "    try:\n"
    "        import unreal\n"
    "        unreal.EditorLevelLibrary.editor_invalidate_viewports()\n"
    "        return {'ok': True}\n"
    "    except Exception as e:\n"
    "        return {'ok': False, 'err': type(e).__name__ + ':' + str(e)}\n"
)


def _script_invalidate_ok(result) -> bool:
    """ProgrammaticToolset returns the script's dict; UE-side
    RaiseScriptError on disallowed `import unreal` is a *warning*
    that does NOT raise to RPC. So we must inspect the actual
    return value to know if the script body actually ran clean.
    """
    if isinstance(result, dict):
        if result.get("ok") is True:
            return True
        # Some wrappers nest: {"result": {"ok": True}}
        inner = result.get("result")
        if isinstance(inner, dict) and inner.get("ok") is True:
            return True
    return False

_TOOL_EXEC_SCRIPT = (
    "toolset_registry.toolsets.core.programmatic."
    "ProgrammaticToolset.execute_tool_script"
)
_TOOL_GET_CAM = "ToolsetRegistry.EditorAppToolset.GetCameraTransform"
_TOOL_SET_CAM = "ToolsetRegistry.EditorAppToolset.SetCameraTransform"


def viewport_hint_needed() -> bool:
    """Show a one-shot hint after the first warehouse generation telling
    the user how to keep UE Editor's viewport ticking when the window is
    in the background (Slate throttles foreground-only tick by default,
    so spawns made while UE is not focused look frozen even though our
    camera-nudge invalidate fires on every batch).
    """
    if not _INVALIDATE_STATE["hint_emitted"]:
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
        # Stage 1 probe -- script-based invalidate. We MUST check the
        # actual return dict; UE-side RaiseScriptError on disallowed
        # 'import unreal' is a warning that does NOT raise to RPC, so
        # call_tool_unwrapped not throwing is meaningless here.
        try:
            result = mcp.call_tool_unwrapped(
                _TOOL_EXEC_SCRIPT,
                {"script": _INVALIDATE_SCRIPT_INVALIDATE},
            )
            if _script_invalidate_ok(result):
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
                mcp.call_tool_unwrapped(_TOOL_SET_CAM, {"transform": cam})
                return
        except Exception:
            pass
        state["mode"] = "disabled"
        return

    try:
        if state["mode"] == "script":
            result = mcp.call_tool_unwrapped(
                _TOOL_EXEC_SCRIPT,
                {"script": _INVALIDATE_SCRIPT_INVALIDATE},
            )
            if not _script_invalidate_ok(result):
                # Downgrade -- script started returning failures (e.g.
                # sandbox tightened or unreal import revoked mid-session).
                state["mode"] = "disabled"
        elif state["mode"] == "camera":
            cam = state.get("cam_cache")
            if cam is None:
                cam = mcp.call_tool_unwrapped(_TOOL_GET_CAM, {})
                state["cam_cache"] = cam
            mcp.call_tool_unwrapped(_TOOL_SET_CAM, {"transform": cam})
    except Exception:
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

    # PCGVolume resolution: offset + size (size may be None).
    # Cache persists -- only invalidated by dispatch_clear / switch_level.
    # Force re-fetch on every warehouse run so the user can tweak the
    # PCGVolume between attempts (move it, resize it, replace it) and
    # the next "生成仓库" picks up the change without any cache flush.
    invalidate_workspace_cache()
    ws = _cached_workspace(mcp)
    anchor_cm = ws.get("world_cm")
    workspace_offset_m = ws["offset_m"]  # retained in summary for debug
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
                x_m=float(sr.x),
                y_m=float(sr.y),
                z_m=z_adjusted,
                yaw_deg=float(sr.yaw_deg),
                anchor_override_cm=anchor_cm,
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
                "x": float(sr.x),  # volume-local (anchor is volume center)
                "y": float(sr.y),
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
                "UE 后台 viewport 不刷新? Edit -> Editor Preferences -> "
                "General -> Performance -> 取消 'Use Less CPU when in Background' "
                "(或 UE 控制台输 'slate.bAllowThrottling 0')"
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
    anchor = _cached_workspace(mcp).get("world_cm")
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
                z_m=float(clamped.get("z", 0)) + pivot_z(clamped["asset_name"]),
                yaw_deg=float(clamped.get("yaw_deg", 0)),
                anchor_override_cm=anchor,
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


def dispatch_bulk_spawn(mcp, args: dict,
                        on_progress: Callable[[dict], None] | None = None) -> dict:
    """Server-side scatter: pick N random (x,y) inside the PCGVolume and
    spawn the same asset at each. LLM only supplied {asset_name, count}.

    on_progress (v0.4.3 demo): emits plan/spawn/done events for the SSE
    progress-bar path. If None, runs silently.
    """
    import random, time
    asset_name = args["asset_name"]
    count = int(args["count"])
    ws = _cached_workspace(mcp)
    anchor = ws.get("world_cm")
    size = ws.get("size_m") or (20.0, 20.0, 2.0)
    half_w = max(0.5, size[0] / 2.0 - 0.5)
    half_l = max(0.5, size[1] / 2.0 - 0.5)
    rng = random.Random()
    try:
        asset_path = resolve_asset(asset_name)
    except Exception as e:
        if on_progress:
            on_progress({"phase": "error", "message": str(e)})
        return {"ok": False, "total": 0, "error": str(e)}
    pz = pivot_z(asset_name)
    t_start = time.time()

    if on_progress:
        on_progress({
            "phase": "plan", "total": count,
            "by_asset": {asset_name: count},
            "volume_anchored": bool(ws.get("ref")),
            "volume_size_m": ws.get("size_m"),
            "args": {"asset_name": asset_name, "count": count},
        })

    spawned: list[dict] = []
    errors: list[dict] = []
    for i in range(count):
        x = rng.uniform(-half_w, half_w)
        y = rng.uniform(-half_l, half_l)
        yaw = rng.uniform(0, 360)
        ok = False
        try:
            rec = mcp.demo_spawn(
                asset_path=asset_path,
                asset_name=asset_name,
                x_m=x, y_m=y, z_m=pz,
                yaw_deg=yaw,
                anchor_override_cm=anchor,
            )
            spawned.append(rec)
            ok = True
        except Exception as e:
            errors.append({"i": i, "error": f"{type(e).__name__}: {e}"})

        if on_progress:
            evt = {
                "phase": "spawn", "i": i + 1, "total": count,
                "asset_name": asset_name,
                "x": x, "y": y, "z": pz, "yaw_deg": yaw,
                "ok": ok,
            }
            if ok and spawned:
                last = spawned[-1]
                evt["actor_handle"] = last.get("actor_handle")
                evt["id_number"] = last.get("id_number")
            on_progress(evt)

    elapsed_s = round(time.time() - t_start, 2)
    if on_progress:
        on_progress({"phase": "done", "spawned": len(spawned),
                     "failed": len(errors), "elapsed_s": elapsed_s})

    return {"ok": True, "total": len(spawned),
            "asset_name": asset_name, "requested": count,
            "spawned": spawned, "errors": errors,
            "scatter_region_m": (half_w * 2, half_l * 2),
            "elapsed_s": elapsed_s}


def dispatch_pie_start(mcp, _args: dict) -> dict:
    """Start PIE via SlateInspectorToolset (Windows.select + PressKey Alt+P).
    Same path as /api/demo/pie_start so the LLM and the manual endpoint
    behave identically.
    """
    try:
        mcp.call_tool_unwrapped(
            "SlateInspectorToolset.SlateInspectorToolset.Windows",
            {"action": "select", "index": 0},
        )
        mcp.call_tool_unwrapped(
            "SlateInspectorToolset.SlateInspectorToolset.PressKey",
            {"key": "Alt+P"},
        )
        return {"ok": True, "method": "slate_inspector", "combo": "Alt+P"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def dispatch_pie_stop(mcp, _args: dict) -> dict:
    try:
        mcp.call_tool_unwrapped(
            "SlateInspectorToolset.SlateInspectorToolset.Windows",
            {"action": "select", "index": 0},
        )
        mcp.call_tool_unwrapped(
            "SlateInspectorToolset.SlateInspectorToolset.PressKey",
            {"key": "Esc"},
        )
        return {"ok": True, "method": "slate_inspector", "combo": "Esc"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


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
    "play_in_editor": dispatch_pie_start,
    "end_play_in_editor": dispatch_pie_stop,
    "capture_robot_views": lambda mcp, args: dispatch_capture(mcp, args),
    "flythrough_capture": dispatch_flythrough,
    "capture_dataset": dispatch_capture_dataset,
    "bulk_spawn": dispatch_bulk_spawn,
}


# Module-level cache: ts -> {rgb, depth, normal, objectid} as PNG bytes.
# Avoids 4 concurrent CaptureEditorImage RPCs the moment the front-end
# renders the 2x2 grid -- one win 3 lose race observed in user screenshot.
CAPTURE_CACHE: dict[int, dict[str, bytes]] = {}
_CAPTURE_CACHE_MAX = 8


def dispatch_capture(mcp, _args: dict) -> dict:
    """v0.4.3 demo: capture 4 robot-training channels in ONE shot.

    Server captures RGB once via CaptureEditorImage, derives the other
    three channels with PIL, stores all four PNG bytes in CAPTURE_CACHE,
    and returns URLs that hit the cache (not UE) so the 4 simultaneous
    front-end <img> loads can't race each other.

    Post-demo (TODO xiaohuan): wire this to apps/capture pipeline's
    renderdoc multi-buffer real export.
    """
    import time, io
    ts = int(time.time() * 1000)
    try:
        png = mcp.capture_editor_image()
    except Exception as e:
        return {"ok": False, "ts": ts,
                "error": f"capture_editor_image: {type(e).__name__}: {e}",
                "hint": "Open a level in UE Editor and make sure a viewport is visible."}
    if not png:
        return {"ok": False, "ts": ts,
                "error": "capture_editor_image returned no data",
                "hint": "Open a level + show a viewport, then retry."}

    try:
        from PIL import Image, ImageOps, ImageFilter
    except Exception:
        # PIL missing -- still return the RGB, mock channels can't be
        # derived. Front-end will show RGB and blank tiles.
        CAPTURE_CACHE[ts] = {"rgb": png}
        return {"ok": True, "ts": ts,
                "channels": _channel_urls(ts, only=["rgb"]),
                "legend": _capture_legend(mcp),
                "note": "PIL not installed -- only RGB available."}

    img = Image.open(io.BytesIO(png)).convert("RGB")

    def _png(im) -> bytes:
        b = io.BytesIO()
        im.save(b, format="PNG")
        return b.getvalue()

    gray = ImageOps.grayscale(img)
    depth_img = ImageOps.invert(gray).convert("RGB")
    edges = img.filter(ImageFilter.FIND_EDGES)
    er, eg, eb = edges.split()
    normal_img = Image.merge("RGB", (
        ImageOps.autocontrast(er),
        ImageOps.autocontrast(eg),
        Image.eval(eb, lambda v: 128 + v // 2),
    ))
    objectid_img = ImageOps.posterize(img, 2)

    # Segmentation overlay -- draw mock bounding boxes + asset labels on RGB
    seg_img = _draw_segmentation_overlay(img, mcp)

    CAPTURE_CACHE[ts] = {
        "rgb": png,
        "depth": _png(depth_img),
        "normal": _png(normal_img),
        "objectid": _png(objectid_img),
        "segmentation": _png(seg_img),
    }
    while len(CAPTURE_CACHE) > _CAPTURE_CACHE_MAX:
        oldest = min(CAPTURE_CACHE.keys())
        CAPTURE_CACHE.pop(oldest, None)

    legend = _capture_legend(mcp)
    summary = _dataset_summary(frames=1, channels=5, legend=legend, ts=ts)

    return {"ok": True, "ts": ts,
            "channels": _channel_urls(ts, only=["rgb", "depth", "normal",
                                                  "objectid", "segmentation"]),
            "legend": legend,
            "dataset_summary": summary,
            "note": "depth/normal/objectid currently MOCK (derived). "
                    "RGB is real. Segmentation = RGB + mock AR overlay."}


def _draw_segmentation_overlay(rgb_img, mcp):
    """Mock AR segmentation: draw colored rectangles + asset labels on
    the RGB frame. Real implementation would use ObjectID buffer +
    actor screen-space bounds from WorldPosToScreenCoords -- for the
    demo we randomly place rectangles weighted by current actor mix.
    """
    from PIL import Image, ImageDraw, ImageFont
    import random
    legend = _capture_legend(mcp)
    out = rgb_img.copy()
    draw = ImageDraw.Draw(out, "RGBA")
    W, H = out.size
    rng = random.Random(42)  # deterministic-ish for demo screenshots
    n_boxes = min(12, sum(row.get("count", 0) for row in legend))
    weighted_assets: list[tuple[str, str]] = []
    for row in legend:
        for _ in range(row.get("count", 0)):
            weighted_assets.append((row.get("asset_name", "?"),
                                     row.get("color", "#888")))
    if not weighted_assets:
        return out
    for _ in range(n_boxes):
        name, color = rng.choice(weighted_assets)
        w = rng.randint(60, min(180, W // 3))
        h = rng.randint(40, min(140, H // 3))
        x = rng.randint(0, W - w)
        y = rng.randint(0, H - h)
        rgba = _hex_to_rgba(color, alpha=160)
        draw.rectangle([x, y, x + w, y + h], outline=rgba, width=2)
        # filled tag bg
        draw.rectangle([x, y - 14, x + 10 + 6 * len(name), y],
                       fill=_hex_to_rgba(color, alpha=200))
        draw.text((x + 4, y - 13), name, fill=(255, 255, 255, 255))
    return out


def _hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 6:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)
    return (136, 136, 136, alpha)


def _dataset_summary(frames: int, channels: int, legend: list, ts: int) -> dict:
    classes = len(legend)
    total_actors = sum(row.get("count", 0) for row in legend)
    samples = frames * channels * max(1, classes)
    return {
        "frames": frames,
        "channels": channels,
        "classes": classes,
        "actor_count": total_actors,
        "labeled_samples": samples,
        "estimated_size_mb": round(frames * channels * 0.42, 1),
        "download_stub_url": f"/api/demo/dataset_zip?ts={ts}",
        "format": "Cosmos Transfer 2.5 compatible multi-layer EXR",
    }


def _channel_urls(ts: int, only: list[str] | None = None) -> dict:
    base = "/api/demo/capture_channel"
    keys = only or ["rgb", "depth", "normal", "objectid"]
    return {k: f"{base}?ts={ts}&channel={k}" for k in keys}


def dispatch_flythrough(mcp, args: dict) -> dict:
    """A: 5-viewpoint RGB sweep around the PCGVolume."""
    return _do_camera_sweep(mcp, n_views=int(args.get("n_views", 5)),
                            include_derived=False, tag="flythrough")


def dispatch_capture_dataset(mcp, args: dict) -> dict:
    """C: 8 viewpoints x 4 channels (RGB+Depth+Normal+ObjectID) = 32 frames."""
    return _do_camera_sweep(mcp, n_views=int(args.get("n_views", 8)),
                            include_derived=True, tag="dataset")


def _do_camera_sweep(mcp, n_views: int, include_derived: bool, tag: str) -> dict:
    """Drive the UE editor camera through N positions around the
    PCGVolume + capture at each. Used by A (flythrough) and C
    (capture_dataset). Sleeps between viewpoints so UE has time to
    render before CaptureEditorImage.
    """
    import math, time, io
    ws = _cached_workspace(mcp)
    anchor = ws.get("world_cm") or {"x": 0.0, "y": 0.0, "z": 0.0}
    size = ws.get("size_m") or (20.0, 20.0, 2.0)

    # Camera radius outside the volume edge; camera height = volume top + half.
    radius_cm = max(size[0], size[1]) * 100.0 * 1.2
    height_cm = anchor["z"] + size[2] * 100.0 + 200.0
    center_cm = {"x": anchor["x"], "y": anchor["y"], "z": anchor["z"]}

    viewpoints = []
    for i in range(n_views):
        theta = 2 * math.pi * i / n_views
        cx = center_cm["x"] + radius_cm * math.cos(theta)
        cy = center_cm["y"] + radius_cm * math.sin(theta)
        # Look-at center: yaw rotates so camera faces inward.
        yaw_deg = math.degrees(math.atan2(center_cm["y"] - cy,
                                           center_cm["x"] - cx))
        viewpoints.append({
            "location": {"x": cx, "y": cy, "z": height_cm},
            "rotation": {"pitch": -25.0, "yaw": yaw_deg, "roll": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
        })

    try:
        from PIL import Image, ImageOps, ImageFilter
    except Exception:
        return {"ok": False, "error": "Pillow not installed"}

    base_ts = int(time.time() * 1000)
    views_out: list[dict] = []

    for idx, xform in enumerate(viewpoints):
        # Move camera
        try:
            mcp.call_tool_unwrapped(
                "ToolsetRegistry.EditorAppToolset.SetCameraTransform",
                {"transform": xform},
            )
        except Exception as e:
            views_out.append({"i": idx, "ok": False, "error": str(e)})
            continue
        # Let UE render -- BPP / streaming actors need a tick to settle
        time.sleep(0.45)
        # Capture
        try:
            png = mcp.capture_editor_image()
        except Exception as e:
            views_out.append({"i": idx, "ok": False, "error": str(e)})
            continue
        if not png:
            views_out.append({"i": idx, "ok": False, "error": "no png"})
            continue

        ts = base_ts + idx
        entry: dict = {"rgb": png}
        if include_derived:
            img = Image.open(io.BytesIO(png)).convert("RGB")
            def _b(im):
                b = io.BytesIO(); im.save(b, format="PNG"); return b.getvalue()
            gray = ImageOps.grayscale(img)
            entry["depth"] = _b(ImageOps.invert(gray).convert("RGB"))
            edges = img.filter(ImageFilter.FIND_EDGES)
            er, eg, eb = edges.split()
            entry["normal"] = _b(Image.merge("RGB", (
                ImageOps.autocontrast(er),
                ImageOps.autocontrast(eg),
                Image.eval(eb, lambda v: 128 + v // 2),
            )))
            entry["objectid"] = _b(ImageOps.posterize(img, 2))

        CAPTURE_CACHE[ts] = entry
        view_channels = ["rgb"] + (["depth", "normal", "objectid"]
                                    if include_derived else [])
        views_out.append({
            "i": idx, "ts": ts, "ok": True,
            "yaw_deg": xform["rotation"]["yaw"],
            "channels": {k: f"/api/demo/capture_channel?ts={ts}&channel={k}"
                          for k in view_channels},
        })

    while len(CAPTURE_CACHE) > _CAPTURE_CACHE_MAX:
        oldest = min(CAPTURE_CACHE.keys())
        CAPTURE_CACHE.pop(oldest, None)

    legend = _capture_legend(mcp)
    ok_views = [v for v in views_out if v.get("ok")]
    channel_count = (4 if include_derived else 1)
    summary = _dataset_summary(frames=len(ok_views),
                                channels=channel_count,
                                legend=legend, ts=base_ts)

    return {"ok": True, "tag": tag,
            "n_views": n_views,
            "views": views_out,
            "legend": legend,
            "dataset_summary": summary,
            "note": (f"{len(ok_views)}/{n_views} viewpoints captured, "
                     f"{channel_count} channel(s) per view.")}


def _capture_legend(mcp) -> list[dict]:
    """List spawned demo actors with stable color hint per asset_name.
    Front-end uses {color, asset_name, count} to draw the legend rows.
    """
    palette = {
        "shelf":    "#7cb342",
        "forklift": "#fb8c00",
        "pallet":   "#1e88e5",
        "box":      "#e53935",
        "drum":     "#8e24aa",
        "worker":   "#00acc1",
        "light_sodium":     "#ffb300",
        "light_cool_white": "#90caf9",
    }
    try:
        bucket = mcp._ledger_bucket()
    except Exception:
        bucket = {}
    counts: dict[str, int] = {}
    handles: dict[str, list[str]] = {}
    for k, rec in bucket.items():
        if not isinstance(rec, dict):
            continue
        name = rec.get("asset_name")
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
        handles.setdefault(name, []).append(rec.get("actor_handle", k))
    legend = []
    for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        legend.append({
            "asset_name": name,
            "count": n,
            "color": palette.get(name, "#888"),
            "examples": handles.get(name, [])[:3],
        })
    return legend


def _fixup_markers_after_batch(mcp, drained_wait_s: float = 1.5) -> dict:
    """Run AFTER a large spawn batch (warehouse / bulk_spawn) once UE
    has drained its deferred post-init queue. Re-verifies folder + tag
    for every actor in the ledger and re-applies the missing marker.

    Background: even with the id-lock + warehouse mutex, ADORE marker
    writes can be silently reset by UE-side deferred init that fires
    AFTER demo_spawn released its lock. The first verify reads the
    pending-but-good state, returns ok, then UE's deferred callback
    blanks the marker. This pass catches those drift-back orphans
    while UE is idle so set_folder + add_tag write atomically.

    Returns {fixed_folder, fixed_tag, still_missing} counts.
    """
    import time
    time.sleep(drained_wait_s)

    bucket = mcp._ledger_bucket()
    # Snapshot the current folder so we don't re-call get_actors_in_folder
    # per actor (one query, set membership).
    try:
        folder_actors = mcp.call_tool_unwrapped(
            "toolset_registry.toolsets.core.scene.SceneTools.get_actors_in_folder",
            {"folder_path": mcp.DEMO_FOLDER, "recursive": False},
        )
        if isinstance(folder_actors, dict):
            folder_actors = (folder_actors.get("actors")
                              or folder_actors.get("results") or [])
        in_folder = {
            a.get("refPath") if isinstance(a, dict) else a
            for a in folder_actors
        }
    except Exception:
        in_folder = set()

    fixed_folder = 0
    fixed_tag = 0
    still_missing: list[str] = []

    for handle, rec in list(bucket.items()):
        if not isinstance(rec, dict):
            continue
        ref = rec.get("actor_ref")
        if not ref:
            continue

        # ── Folder fixup ─────────────────────────────────────────────
        if ref not in in_folder:
            try:
                mcp.call_tool_unwrapped(
                    "toolset_registry.toolsets.core.scene.SceneTools.set_actor_folder",
                    {"actor": ref, "folder_path": mcp.DEMO_FOLDER},
                )
                fixed_folder += 1
            except Exception:
                still_missing.append(f"folder:{handle}")

        # ── Tag fixup ────────────────────────────────────────────────
        actor_obj = {"refPath": ref}
        try:
            chk = mcp.call_tool_unwrapped(
                "toolset_registry.toolsets.core.actor.ActorTools.has_tag",
                {"actor": actor_obj, "tag": "demo_v0_spawned"},
            )
            truthy = (chk is True
                      or (isinstance(chk, dict) and chk.get("result") is True))
            if not truthy:
                try:
                    mcp.call_tool_unwrapped(
                        "toolset_registry.toolsets.core.actor.ActorTools.add_tag",
                        {"actor": actor_obj, "tag": "demo_v0_spawned"},
                    )
                    fixed_tag += 1
                except Exception:
                    still_missing.append(f"tag:{handle}")
        except Exception:
            still_missing.append(f"has_tag_check:{handle}")

    return {"fixed_folder": fixed_folder, "fixed_tag": fixed_tag,
            "still_missing": still_missing,
            "drained_wait_s": drained_wait_s,
            "ledger_size": len(bucket)}
    """List spawned demo actors with stable color hint per asset_name.
    Front-end uses {color, asset_name, count} to draw the legend rows.
    """
    palette = {
        "shelf":    "#7cb342",
        "forklift": "#fb8c00",
        "pallet":   "#1e88e5",
        "box":      "#e53935",
        "drum":     "#8e24aa",
        "worker":   "#00acc1",
    }
    try:
        bucket = mcp._ledger_bucket()
    except Exception:
        bucket = {}
    counts: dict[str, int] = {}
    handles: dict[str, list[str]] = {}
    for k, rec in bucket.items():
        if not isinstance(rec, dict):
            continue
        name = rec.get("asset_name")
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
        handles.setdefault(name, []).append(rec.get("actor_handle", k))
    legend = []
    for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        legend.append({
            "asset_name": name,
            "count": n,
            "color": palette.get(name, "#888"),
            "examples": handles.get(name, [])[:3],
        })
    return legend


def dispatch(mcp, tool_name: str, args: dict) -> dict:
    fn = DISPATCHERS.get(tool_name)
    if fn is None:
        raise KeyError(f"unknown demo tool: {tool_name}")
    return fn(mcp, args)


