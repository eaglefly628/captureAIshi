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

ASSET_REGISTRY: dict[str, str] = {
    # Warehouse v0 (LLM primary catalog)
    "shelf":    _CUBE_PLACEHOLDER,
    "forklift": _CUBE_PLACEHOLDER,
    "pallet":   _CUBE_PLACEHOLDER,
    "box":      _CUBE_PLACEHOLDER,
    "drum":     _CUBE_PLACEHOLDER,
    "worker":   _CUBE_PLACEHOLDER,

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


def resolve(asset_name: str) -> str:
    """Returns the UE path, or raises KeyError if not in v0 catalog."""
    if asset_name not in ASSET_REGISTRY:
        raise KeyError(
            f"asset_name '{asset_name}' not in v0 catalog; "
            f"valid: {', '.join(ASSET_NAMES)}"
        )
    return ASSET_REGISTRY[asset_name]
