# UE 5.7/5.8 PCG Framework Node Reference

> Source: Epic 5.7 docs (user 拷贴 2026-05-20)
> 5.8 兼容性: 高（5.7 → 5.8 PCG 主要 delta 在性能 + DAG eval，节点 API stable）
> 用途: PCG graph 节点级 reference, 配 cheatsheet_pcg_graph.md (节点速查) + ue58_pcg_notes_xiaohuan.md (5.8 调研) + ue58_knowledge_base.md (踩坑实录)

## 0. 总体架构

The Procedural Content Generation (PCG) Framework uses the Procedural Node Graph to generate procedural content in Editor and at Runtime. Spatial data flows from a PCG Component in your Level into the graph and is used to generate points. The points are filtered and modified through node chains.

## 1. Blueprint
- **Execute Blueprint**: Execute custom UPCGBlueprintElement BP class.

## 2. Control Flow
- **Branch**: 2-output, boolean-selected. Culled branches optimized out.
- **Select**: 2-input, boolean-selected single output. (Not yet culled.)
- **Select (Multi)**: int/enum/string multi-input version.
- **Switch**: int/string/enum multi-output version.

## 3. Debug
- **Debug**: Non-transient debug point. Editor-only.
- **Sanity Check Point Data**: Validates input in range, cancels generation on fail.
- **Print String**: Optional log/node/screen prefix output. No-op in shipping.

## 4. Density
- **Curve Remap Density**: Remap density via curve.
- **Density Remap**: Linear transform on density.
- **Distance to Density**: Compute density gradient against reference point. **Superseded by Distance node.**

## 5. Filter
- **Attribute Filter**: General-purpose filter on Point Data / Attribute Sets, by attribute or property.
- **Attribute Filter Range**: Range-based version.
- **Density Filter**: Density-based filter. **Superseded by Attribute Filter** but more efficient for that specific case.
- **Discard Points on Irregular Surface**: Multi-point coplanarity test. Example PCG Subgraph.
- **Filter Data By Attribute**: Separate by metadata attribute existence (Inside/Outside Filter outputs).
- **Filter Data by Index**: Index-based filter, Python-range-like string ("0, 2, 4:5, 7:-1").
- **Filter Data By Tag**: Tag-based filter.
- **Filter Data By Type**: Type-based filter (used by UE automatically between mismatched type pins; see ue58_knowledge_base.md §1.12).
- **Point Filter**: Per-point filter (vs Attribute Filter which is per-data).
- **Point Filter Range**: Range-based per-point filter.
- **Self Pruning**: Remove intersections, priority by size/random.

## 6. Generic
- **Add Tags**: Tag input data.
- **Apply On Actor**: Set actor properties from Attribute Set. Can call parameter-less functions. Use carefully — not revertable by PCG.
- **Delete Tags**: Remove tags from input data.
- **Gather**: Collect inputs into single collection. Has Dependency Only pin for execution ordering.
- **Get Data Count**: Output Attribute Set with input pin's data count.
- **Get Entries Count**: Count entries in Attribute Set.
- **Get Loop Index**: Inside a loop subgraph, returns current iteration index.
- **Proxy**: Placeholder swappable at runtime via parameter override.
- **Replace Tags**: Tag rename 1:1, N:1, N:N.
- **Sort Attributes**: Sort by attribute asc/desc.
- **Sort Points**: Alias for Sort Attributes.

## 7. Helpers
- **Spatial Data Bounds To Point**: Bounds → single point representation.

## 8. Hierarchical Generation
- **Grid Size**: Specify grid size for downstream execution.

## 9. Input Output
- **Data Table Row to Attribute Set**: Single row → Attribute Set.
- **Load Alembic File**: Alembic → PCG point data. Requires PCG External Data Interop plugin.
- **Load Data Table**: UDataTable → Point Data or Attribute Set. Data-driven graphs.
- **Load PCG Data Asset**: PCG Data Asset → graph data (sync or async).

## 10. Metadata (核心 - mesh / param 控制都靠这组)

- **Add Attribute**: Adds attribute to point data or attribute set.
- **Attribute Noise**: Noise computation per-point on a target attribute. Modes + min/max range. Useful for variation on continuous params.
- **Attribute Partition**: Split data by attribute values (same value → same partition). Useful for downstream Loop.
- **Attribute Rename**: Rename existing attribute. For subgraph contract matching.
- **Attribute Select**: Min/Max/Median on axis. ~= dot product with axis.
- **Attribute String Op**: String concat etc. Pairs with Print String + Create Target Actor.
- **Break Transform Attribute**: → Translation / Rotation / Scale components.
- **Break Vector Attribute**: → X / Y / Z / W components.
- **Copy Attribute**: Copy attribute from Attribute pin OR from input itself, to new point data. **关键: mesh attribute 注入用这条**.
- **Create Attribute**: **Creates an Attribute Set with a single attribute.** 我们 v0.4 PG_Warehouse 用此包 shelf_mesh path → "Mesh" attribute.
- **Delete Attributes**: Filter (keep/remove) by comma-separated name list.
- **Density Noise**: Alias for Attribute Noise.
- **Filter Attributes by Name**: Alias for Delete Attributes.
- **Get Attribute from Point Index**: Single point + its attributes → separate Attribute Set. Loop-friendly.
- **Make Transform Attribute**: 3 attributes → Transform.
- **Make Vector Attribute**: 2-4 attributes → Vector.
- **Match And Set Attributes**: Match an entry in Match Data table against input, copy values. Cornerstone of data-driven graphs. **Supersedes Point Match and Set**.
  - Match attribute (Match Attributes ↔ Match Attribute)
  - Weighted (Match Weight Attribute) or random
  - Nearest-value fallback with optional max distance threshold
  - Matching attributes NOT propagated to output
- **Merge Attributes**: Merge multiple Attribute Sets in connection order. Non-common attributes default-filled.
- **Point Match and Set**: Legacy alias for Match And Set Attributes. **Doc explicitly notes**: "**A common use case is to select meshes to be used downstream in a Static Mesh Spawner node with the By Attribute selector.**"
- **Transfer Attribute**: Set attribute from same-type, same-size source (spatial→spatial or points→points). For 1:1 attribute propagation.

### 10.1 Attribute Bitwise Op
- And / Not / Or / Xor

### 10.2 Attribute Boolean Op
- And / Imply / Nand / Nimply / Nor / Not / Or / Xnor / Xor

### 10.3 Attribute Compare Op
- Equal / Greater / Greater or Equal / Less / Less or Equal / Not Equal → boolean attribute

### 10.4 Attribute Maths Op
- Abs / Add / Ceil / Clamp / Clamp Max / Clamp Min / Divide / Floor / Frac / Lerp / Max / Min / Modulo / Multiply / One Minus / Pow / Round / Set / Sign / Sqrt / Subtract / Truncate

### 10.5 Attribute Reduce Op
- Average / Max / Min (ensemble values for downstream ops)

### 10.6 Attribute Rotator Op
- Combine / Inverse Transform Rotation / Invert / Lerp / Normalize / Transform Rotation
- **Make Rot from**: Angles / Axis / X / XY / XZ / Y / YX / YZ / Z / ZX / ZY

### 10.7 Attribute Transform Op
- Compose / Invert / Lerp

### 10.8 Attribute Trig Op
- Acos / Asin / Atan / Atan2 / Cos / Deg to Rad / Rad to Deg / Sin / Tan

### 10.9 Attribute Vector Op
- Cross / Distance / Dot / Inverse Transform Direction / Inverse Transform Location / Length / Normalize / Rotate Around Axis / Transform Direction / Transform Rotation

## 11. Param
- **Get Actor Property**: Read property from owner actor (or hierarchy). Supports flat struct or array. **Useful for per-instance control via BP variables**.
- **Get Property From Object Path**: Read property from actor reference via Attribute Set. For data-driven flows.
- **Point To Attribute Set**: Drop point properties, keep attributes only. Optimization / type homogenization.

## 12. Point Ops
- **Apply Scale to Bounds**: bounds = bounds × scale; scale → 1 (preserves sign).
- **Bounds Modifier**: Tweak bounds before Self Pruning / Intersection / Difference.
- **Build Rotation From Up Vector**
- **Combine Points**: All input points → single encompassing point.
- **Duplicate Point**: Duplicate + translate axis + transform per iteration. Fractal patterns.
- **Extents Modifier**: Tweak point extents (bounds manipulation).
- **Split Points**: Cut each point along Split Axis at Split Position → 2 outputs (Before/After). Subdivision-style assemblies.
- **Transform Points**: Random translation/rotation/scale per point. Absolute vs relative.
  - Uniform Scale: lock X=Y=Z
  - Recompute Seed: update seed by world pos
  - Example: Absolute Rotation, Z=0 → all points face Z up

## 13. Sampler
- **Copy Points**: Instance source points per target point. Nested-loop copies (S × T outputs). Heavy on Attribute Inheritance.
- **Mesh Sampler**: Sample points on static mesh. Costly. Requires PCG Geometry Script Interop + Geometry Script plugin.
- **Texture Sampler**: UV sampling. Planar From Texture Data OR Explicit Points UV Coordinates.
- **Select Points**: Probabilistic point subset selection. Normal distribution.
- **Spline Sampler**: Sample along spline curve OR Horizontal/Vertical/Volume (spline volume by control point radius). Closed spline for inside.
- **Surface Sampler**: Grid pattern on surface.
  - **Point Extents**: cell size (vector)
  - **Looseness**: cell size = `extents × (1 + Looseness)`, variation
  - **Points Per Squared Meter**: rate of kept cells (overcrowding control)
  - 5.8 实证字段（见 ue58_knowledge_base.md §1.13）: +Unbounded / +ApplyDensityToPoints / +PointSteepness / +Seed / +KeepZeroDensityPoints
- **Volume Sampler**: 3D voxel-like grid sampling on spatial data.

## 14. Spatial
- **Attribute Set To Point**: Attribute Set → Point Data (one default point per entry).
- **Clip Paths**: Intersect/difference splines with Polygon 2D.
- **Create Points**: Static description → point data. Seed point for processes.
- **Create Points Grid**: Simple grid points, paired with Copy Points for grids-around-sources.
- **Create Polygon 2D**: Polygon 2D from points or spline.
- **Create Spline**: Spline from points. Options: Component or Data Only, Closed/Linear, custom in/out tangents.
- **Create Surface From Polygon 2D**: → implicit surface for sampler/diff/intersect.
- **Create Surface From Spline**: closed spline → implicit surface. May discretize; sample first if very large.
- **Cull Points Outside Actor Bounds**: Cull by component bounds + expansion.
- **Difference**: Source minus union of differences.
  - Density Function: Minimum / Clamped Subtraction / Binary
  - Mode: Inferred / Continuous / Discrete
- **Distance**: Per-point dist to nearest in second input. Optional output as attribute. Auto-ignores self.
- **Find Convex Hull 2D**: 2D convex hull from points (location only).
- **Get Actor Data** (★ 用作 root input): General actor data fetcher.
  - Actor Filter / Include Children
  - Mode: Parse Actor Components / Get Single Point / Get Data from PCG Component / hybrid
  - Extra: Expected Pins / Get Data On All Grids / Allowed Grids / Components Must Overlap Self
- **Get Bounds**: Attribute Set with world-space min/max bounds.
- **Get Landscape Data** / **Get PCG Component Data** / **Get Primitive Data** / **Get Spline Data** / **Get Volume Data**: Specializations.
- **Get Points Count**: int point count per Point Data.
- **Get Segment**: Get segment from point/spline/polygon by index.
- **Get Texture Data**: Load texture as surface. GPU sampling default; option Force CPU for compressed.
- **Inner Intersection**: ∩ of all inputs regardless of pin.
- **Intersection**: Outer per-data on Primary Source against union of others.
- **Make Concrete**: Composite (intersect/diff/union) → point data.
- **Merge Points**: Multiple Point Data → single (attribute defaulted).
- **Mutate Seed**: Per-point seed = f(position, prev seed, this node's seed, component seed). Separate random behaviors.
- **Normal To Density**: Density from point normal (dot-product-like with axis). Tweak trees by slope.
- **Offset Polygon**: Polygon 2D larger/smaller with overlap handling.
- **Point Neighborhood**: Search-distance-based values (dist to center, avg center / density / color).
- **Point From Mesh**: Point with mesh bounds. Often inside partition + Loop + intersection test.
- **Polygon Operation**: Polygon-polygon intersect/union/diff + spline slicing.
- **Projection**: Source → target projection. Often re-projecting points on surfaces after Copy Points.
- **Spatial Noise**: Perlin-like noise written to attribute. Combine with Match And Set for spatial-noise-driven selection.
- **Spline Intersection**: Find 3D spline intersections, add control points or return points.
- **Split Splines**: Subdivide by alpha/dist/key/control points predicate.
- **To Point**: Cast/discretize to point data.
- **Union**: Logical union of distribution functions.
  - Density Function: Maximum / Clamped Addition / Binary
- **World Ray Hit Query**: Surface-like data from physics raycasts.
  - Apply Metadata From Landscape (perf hit) / Ignore PCG Hits / etc.
- **World Volumetric Query**: Volume-like data from physics overlaps.

## 15. Spawner (核心 - 实际 mesh / actor spawn)

- **Create Target Actor**: Empty template actor for spawned artifacts target.
- **Point from Player Pawn**: Point at current player pawn. Runtime generation only.
- **Spawn Actor**: Per-point actor spawn.
  - Template: Actor Class / Instanced Template / By Attribute
  - Collapse: Collapse Actors / Merge PCG only / No Merging
  - No Merging supports per-point property overrides via Spawned Actor Property Override Descriptions
  - Attach Mode: Not attached / Attached / In Folder

- **Static Mesh Spawner** (★ v0.4 PG_Warehouse 主节点): Spawn one static mesh per point.
  - **Mesh Entries** array with **Weight**: sum-weighted percentage selection
  - **Mesh Selector Type** options:
    - **PCG Mesh Selector Weighted**: weight-based (v0 默认)
    - **PCG Mesh Selector By Attribute**: **selects entry based on attribute present on the mesh** (= 我们要的, mesh path 从 point attribute 来)
    - **PCG Mesh Selector Weighted By Category**: lookup category attribute first, then weight inside
  - Output: Selected mesh written to point attribute + mesh bounds pushed to point bounds
  - **Mesh Property Override**: per-entry, attribute → ISM Template Descriptor property

## 16. Subgraph
- **Loop**: Per-data subgraph iteration. Feedback pins: first iter from caller, subsequent from prev iter. Build interdependent data sets.
- **Subgraph**: Execute another graph (recursive allowed, cull-terminated). Reuse + recursion.

## 17. Uncategorized (organization)
- **Add Comment**: Visual aid, not a node.
- **Add Reroute Node**: Edge control points.
- **Add Named Reroute Declaration Node**: Logical reroute without visual edge. Multi-usage, single-definition.

---

## §X v0.4 PG_Warehouse 实操 cookbook (xiaohuan)

按本 reference 解析后的精确节点链路（参 demo_v0_simplified_contract.md + pg_warehouse_graph_design.md）:

### 链路 1: shelf_density → cube 密度 (已实证)
```
Get Actor Data → [FilterDataByType auto] → Surface Sampler → SM Spawner
                                              ↑ PointsPerSquaredMeter ← shelf_density (Graph Param)
                                              ↑ Seed ← seed (Graph Param)
```

### 链路 2: shelf_mesh → cube mesh (待搭, 2026-05-20 路径B)
```
shelf_mesh (Graph Param)
    ↓ bind to Soft Object Path Value
[Create Attribute] (a.k.a. "Create Constant" in 5.8 PCG editor UI)
   Type: Soft Object Path
   Output Target: "Mesh"
    ↓ Out (Attribute Set, single attribute "Mesh")
    ↓
[Copy Attribute]
   Input main: Surface Sampler Out (Point Data)
   Attribute pin: Create Attribute Out
    ↓ Out (Point Data with "Mesh" attribute per point)
    ↓
[Static Mesh Spawner]
   Mesh Selector Type: PCG Mesh Selector By Attribute
   Mesh attribute name: "Mesh"
    ↓ spawn shelf_mesh's path's mesh
```

### 多 mesh 类型 (v1, forklift/pallet/box/drum/worker 各分支)
扩展链路 2 的 pattern, 每分支:
- 单独 Create Attribute (Output Target = "Mesh", value = $asset_mesh)
- 单独 Surface Sampler (或 sub-grouping via Partition / Density Filter)
- 单独 SM Spawner ByAttribute
- 全部输出 union 到 root Output

或更高级: 单 SM Spawner ByAttribute, 用 Match And Set Attributes 节点根据 input 上别的 attribute (e.g. asset_type=shelf/forklift/...) 匹配到不同 mesh path 写到 "Mesh" attribute.

参 demo_v0_simplified_contract.md §10 layout generator (v0 Python 算法版) vs 这个 v1 PCG-native 版本对应关系.

---

## §Y 跟现有项目 ref 的关系

| 文档 | 角色 | 何时看 |
|---|---|---|
| 本 doc (`ue58_pcg_node_reference.md`) | Epic 官方 5.7 完整节点 ref | 想查"某个节点叫啥 / 输入输出 / option" |
| `cheatsheet_pcg_graph.md` | 我们项目角度的速查 | 常用 pattern + 5.6/5.7 集成节点链 |
| `ue58_pcg_notes_xiaohuan.md` | 5.8 一般性变化调研 | 5.8 vs 5.7 高层 delta |
| `ue58_knowledge_base.md` | 项目踩坑实录 | 这个具体 bug 怎么解 |
| `pg_warehouse_graph_design.md` | 我们 PG_Warehouse 节点 spec | 实际搭 graph 看这个 |

新发现 / bug / surprise 加到 `ue58_knowledge_base.md`, 不要改本 doc (本 doc = 上游 Epic 镜像).

---

## §Z 源
- Epic 5.7 PCG Framework Node Reference (user 拷贴 2026-05-20)
- URL (sandbox 不可访问, 用户浏览器可达): `https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-framework-node-reference-in-unreal-engine`
- 5.8 GA 后建议 user re-fetch update 一次
