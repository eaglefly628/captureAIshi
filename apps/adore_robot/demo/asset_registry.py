"""Demo v0 asset_name -> UE asset path mapping.

LLM only sees the asset_name enum (xiaohuan demo_v0_simplified_contract.md
§1). Server-side resolves to the real UE path before injecting into the
unreal-python script.

Placeholder: all 6 names point to PCG plugin sample cube until real
warehouse meshes are downloaded. Swap entries one-by-one as assets land.
"""

from __future__ import annotations

# UE path notation, not Windows filesystem path. Engine plugin "PCG"
# mounts its Content at /PCG/. Asset reference uses the .Asset suffix
# convention for load_object, but load_object also accepts the path
# without suffix in 5.8.
_CUBE_PLACEHOLDER = "/PCG/SampleContent/MeshSockets/Meshes/1M_CubeWithSocket.1M_CubeWithSocket"

# Real warehouse asset paths (PackedLevelActor / StaticMesh). Pivot is
# the asset's published pivot point in UE; PackedLevels typically place
# the pivot at floor level (z=0) already, so pivot_z_m = 0.
_FORKLIFT_REAL = "/Game/Scene_Warehouse/Maps/PackedLevels/Ind_War_HandTruck_01.Ind_War_HandTruck_01"
# In ADORE the "worker" slot is actually the robot scout -- this is a
# robotics training-scene foundry, the moving agent IS the robot.
_ROBOT_REAL = "/Game/Robot_scout_R_21/Mesh/SK_Robot_scout_R21.SK_Robot_scout_R21"
_DRUM_REAL = ("/Game/Scene_Warehouse/Assets/MS/3D/Ind_Aba_Storage_Barrel_Metal_Green_01/"
              "SM_Ind_Aba_Storage_Barrel_Metal_Green_01.SM_Ind_Aba_Storage_Barrel_Metal_Green_01")
_BOX_REAL = ("/Game/Scene_Warehouse/Assets/MS/3D/Ind_War_Storage_Box_Cardboard_Worn_02/"
             "SM_Ind_War_Storage_Box_Cardboard_Worn_02.SM_Ind_War_Storage_Box_Cardboard_Worn_02")

# Rack variants: 4 BPP variants in the same package; resolve() picks one
# at random per call so a 'shelf' row visually varies. Single-asset
# entries stay as plain strings (no behavior change).
_SHELF_VARIANTS = [
    "/Game/Scene_Warehouse/Assets/Blueprints/BPP_Ind_War_Rack_01.BPP_Ind_War_Rack_01",
    "/Game/Scene_Warehouse/Assets/Blueprints/BPP_Ind_War_Rack_02.BPP_Ind_War_Rack_02",
    "/Game/Scene_Warehouse/Assets/Blueprints/BPP_Ind_War_Rack_03.BPP_Ind_War_Rack_03",
    "/Game/Scene_Warehouse/Assets/Blueprints/BPP_Ind_War_Rack_04.BPP_Ind_War_Rack_04",
]

ASSET_REGISTRY: dict[str, "str | list[str]"] = {
    # Warehouse v0 (LLM primary catalog)
    "shelf":    _SHELF_VARIANTS,   # random rack variant per spawn
    "forklift": _FORKLIFT_REAL,    # real Ind_War_HandTruck_01 PackedLevel
    "pallet":   _CUBE_PLACEHOLDER,
    "box":      _BOX_REAL,         # SM_Ind_War_Storage_Box_Cardboard_Worn_02
    "drum":     _DRUM_REAL,        # SM_Ind_Aba_Storage_Barrel_Metal_Green_01
    "worker":   _ROBOT_REAL,       # SK_Robot_scout_R21 -- the robot agent

    # Lighting (warehouse procgen v0.4.1 -- xiaohuan apps/adore_robot/pcg/)
    # Real impl: BP_MegaLight_Sodium / CoolWhite; v0 placeholder cube
    "light_sodium":      _CUBE_PLACEHOLDER,
    "light_cool_white":  _CUBE_PLACEHOLDER,
    "light_mixed":       _CUBE_PLACEHOLDER,

    # Living room v0.4.1 (xiaohuan generate_living_room)
    "sofa":            _CUBE_PLACEHOLDER,
    "coffee_table":    _CUBE_PLACEHOLDER,
    "side_table":      _CUBE_PLACEHOLDER,
    "chair":           _CUBE_PLACEHOLDER,
    "floor_lamp":      _CUBE_PLACEHOLDER,
    "table_lamp":      _CUBE_PLACEHOLDER,
    "ceiling_pendant": _CUBE_PLACEHOLDER,
    "rug":             _CUBE_PLACEHOLDER,
    "plant":           _CUBE_PLACEHOLDER,
    "bookshelf":       _CUBE_PLACEHOLDER,
    "tv_unit":         _CUBE_PLACEHOLDER,
    "wall_art":        _CUBE_PLACEHOLDER,
    "clutter_small":   _CUBE_PLACEHOLDER,

    # Industrial corner v0.4.1 (xiaohuan generate_industrial_corner)
    "machine":         _CUBE_PLACEHOLDER,
    "workbench":       _CUBE_PLACEHOLDER,
    "toolboard":       _CUBE_PLACEHOLDER,
    "tool_small":      _CUBE_PLACEHOLDER,
    "pipe":            _CUBE_PLACEHOLDER,
    "cable_reel":      _CUBE_PLACEHOLDER,
    "crate":           _CUBE_PLACEHOLDER,
    "conduit":         _CUBE_PLACEHOLDER,
    "fume_hood":       _CUBE_PLACEHOLDER,
    "oil_stain_decal": _CUBE_PLACEHOLDER,
}

ASSET_NAMES = list(ASSET_REGISTRY.keys())

# --- Pivot vertical offset (meters) -----------------------------------------
# Cube placeholder is 1m^3 with pivot at center -> base sits 0.5m below pivot.
# Adding this to z keeps the mesh's bottom on the floor instead of bisecting it.
# When real meshes land, override here per-asset.
_CUBE_PIVOT_Z_M = 0.5
ASSET_PIVOT_Z_M: dict[str, float] = {
    name: _CUBE_PIVOT_Z_M for name in ASSET_NAMES
}
# Ceiling lights hang from ceiling -- no floor offset needed (their z is
# already set to ceiling_h_m in pcg/lighting.py).
for _light in ("light_sodium", "light_cool_white", "light_mixed", "ceiling_pendant"):
    ASSET_PIVOT_Z_M[_light] = 0.0
# Real assets (PackedLevel / BPP / SkeletalMesh / StaticMesh) publish
# their pivot at floor level (z=0) -- no extra lift needed when spawning.
for _real in ("forklift", "shelf", "worker", "drum", "box"):
    ASSET_PIVOT_Z_M[_real] = 0.0


def _normalize_asset_path(p: str) -> str:
    """Convert UE Object Path -> Package Path when the trailing object
    name is the same as the package's last segment (UE 'default object'
    convention -- equivalent forms, but package path is what UE5 MCP's
    add_to_scene_from_asset documents in its example).

    Rules:
      '/Game/X/Foo.Foo'        -> '/Game/X/Foo'      (default object, simplify)
      '/Game/X/Foo.SubObj'     -> '/Game/X/Foo.SubObj' (kept; package has multiple objects)
      '/Game/X/Foo'            -> '/Game/X/Foo'      (already package path)
    """
    if "." not in p:
        return p
    pkg, _, obj = p.rpartition(".")
    last_seg = pkg.rsplit("/", 1)[-1]
    return pkg if obj == last_seg else p


def resolve(asset_name: str) -> str:
    """Returns the UE asset path (normalized to package form when
    applicable), or raises KeyError if not in v0 catalog.

    If the registry entry is a list (asset variants), picks one uniformly
    at random per call so e.g. a shelf row gets visual variety. The choice
    is INTENTIONALLY not pcg-seeded -- it's purely cosmetic and we don't
    want a re-spawn with the same seed to keep the same rack stamp.
    """
    if asset_name not in ASSET_REGISTRY:
        raise KeyError(
            f"asset_name '{asset_name}' not in v0 catalog; "
            f"valid: {', '.join(ASSET_NAMES)}"
        )
    v = ASSET_REGISTRY[asset_name]
    if isinstance(v, list):
        import random
        v = random.choice(v)
    return _normalize_asset_path(v)


def pivot_z(asset_name: str) -> float:
    """Vertical offset (m) to add so the asset's BOTTOM sits at z=0.

    Returns 0.0 for unknown names (safe no-op).
    """
    return ASSET_PIVOT_Z_M.get(asset_name, 0.0)
