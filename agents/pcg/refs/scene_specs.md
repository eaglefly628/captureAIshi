# Scene Spec Templates

> 每场景一份 JSON，xiaohuan 生成 PCG graph 时按这个 schema 出 metadata，xiaoxu 据此配 MRQ。最终路径：`apps/adore_robot/configs/scenes/<scene_name>.json`

## 通用 schema

```json
{
  "scene_id": "warehouse_v0",
  "scene_type": "warehouse | living_room | industrial_corner",
  "size_m": [50, 50, 8],           // x, y, height (meters)
  "algorithm": "bsp | wfc | grammar | graph",
  "pcg_asset": "Content/PCG/Warehouse/PG_Warehouse_v0",
  "asset_packs": ["Quixel_Industrial", "Fab_MetaShelves_Pack1"],
  "target_instance_count": 2500,
  "frame_count": 30,
  "variants": 5,
  "camera_trajectory": {
    "preset": "orbit | snake | corridor_walk | overhead_sweep",
    "params": {...}
  },
  "urdf_robot": {
    "model": "franka_panda | unitree_h1 | ur5 | none",
    "spawn_xyz": [25, 25, 0],
    "kinematic_pose": "rest | reach | mid_grasp | ..."
  },
  "lighting": "skylight_overcast | indoor_tungsten | warehouse_sodium",
  "mrq_preset": "MRQ_MultiPassEXR"      // xiaoxu 那边的 preset 名
}
```

## Warehouse spec 草稿

```json
{
  "scene_id": "warehouse_v0",
  "scene_type": "warehouse",
  "size_m": [50, 50, 8],
  "algorithm": "bsp",
  "pcg_asset": "Content/PCG/Warehouse/PG_Warehouse_v0",
  "asset_packs": ["Quixel_Industrial"],
  "target_instance_count": 2500,
  "frame_count": 30,
  "variants": 5,
  "camera_trajectory": {
    "preset": "corridor_walk",
    "params": {"speed": 1.2, "height": 1.6, "lookahead": 5.0}
  },
  "urdf_robot": {
    "model": "unitree_h1",
    "spawn_xyz": [25, 25, 0],
    "kinematic_pose": "rest"
  },
  "lighting": "warehouse_sodium",
  "mrq_preset": "MRQ_MultiPassEXR"
}
```

## 客厅 spec 草稿

```json
{
  "scene_id": "living_room_v0",
  "scene_type": "living_room",
  "size_m": [5, 7, 3],
  "algorithm": "graph+wfc",
  "pcg_asset": "Content/PCG/LivingRoom/PG_LivingRoom_v0",
  "asset_packs": ["Fab_MetaSofa", "Megascans_DecorPack"],
  "target_instance_count": 80,
  "frame_count": 30,
  "variants": 5,
  "camera_trajectory": {
    "preset": "orbit",
    "params": {"radius": 3.5, "height": 1.6, "tilt_deg": -10}
  },
  "urdf_robot": {
    "model": "franka_panda",
    "spawn_xyz": [2.5, 3.5, 0],
    "kinematic_pose": "reach"
  },
  "lighting": "indoor_tungsten",
  "mrq_preset": "MRQ_MultiPassEXR"
}
```

## 工业一角 spec 草稿

```json
{
  "scene_id": "industrial_corner_v0",
  "scene_type": "industrial_corner",
  "size_m": [8, 8, 4],
  "algorithm": "grammar",
  "pcg_asset": "Content/PCG/IndustrialCorner/PG_IndustrialCorner_v0",
  "asset_packs": ["Fab_IndustrialMachines", "Custom_Toolboard"],
  "target_instance_count": 120,
  "frame_count": 30,
  "variants": 5,
  "camera_trajectory": {
    "preset": "snake",
    "params": {"path_height": 1.4, "step": 0.5}
  },
  "urdf_robot": {
    "model": "ur5",
    "spawn_xyz": [4, 4, 0],
    "kinematic_pose": "mid_grasp"
  },
  "lighting": "indoor_tungsten",
  "mrq_preset": "MRQ_MultiPassEXR"
}
```
