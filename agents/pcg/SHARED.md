# PCG Agent (小幻) — Shared Notes

## Active TODO

_新设岗位 2026-05-15（老白）。首批 P0 待派。_

候选起步任务（老白未最终决定，先列着）：
- [ ] **P0: warehouse 50x50m PCG graph v0** -- BSP partition + grid spawner，资产用 Quixel industrial pack，输出 `Content/PCG/Warehouse/PG_Warehouse_v0.uasset`。先跑通 30 frame x 1 variant，xiaoxu 配 MRQ preset
- [ ] **P0: 三场景 scene config schema 定稿** -- `apps/adore_robot/configs/scenes/<name>.json`，包含 size / target_instance_count / asset_pack / camera_trajectory / urdf_pose
- [ ] **P1: 客厅 5x7m Graph+WFC 原型** -- 房间图 nodes/edges 设计 + 5 个 module (沙发组/茶几组/电视墙/装饰/地毯)
- [ ] **P2: 工业一角 8x8m grammar 雏形** -- 3 条 grammar rule (机床+工具架+控制台)

## Boundary & Handoff

- **依赖 xiaoxu**: custom UPCGSettings 节点实现（先用 BP/built-in 节点凑齐，不够再请 xiaoxu 写 C++）
- **依赖 xiaoxu**: MRQ preset，渲染时 PCG 必须 Generate-on-Demand 跑完再开 MRQ
- **下游 xiaoxuan**: multi-layer EXR 是最终交付物，PCG 这边只管 scene 准备好

## Reference 速查

详见 `agents/pcg/refs/`:
- `cheatsheet_pcg_graph.md` -- PCG 核心节点 + 数据流模板
- `scene_specs.md` -- warehouse / 客厅 / 工业一角 spec 模板

## Changelog

_暂无，等首批 PR_
