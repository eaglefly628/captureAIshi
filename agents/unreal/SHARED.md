# UE5 Fullstack Agent (小虚) — Shared Notes

## Active TODO

_新设岗位 2026-05-15（老白）。首批 P0 待派。_

候选起步任务（老白未最终决定，先列着）：
- [ ] **P0: `apps/adore_robot/unreal_projects/AdoreRobot.uproject` scaffold** -- UE5.6 空工程 + 必备 plugin (PCG / PCG Geometry Script Interop / Geometry Script / Modeling Tools / Mass Entity / Robotics Plugin)。建好 Source/AdoreRobot/AdoreRobot.{Build.cs,Target.cs}
- [ ] **P0: MRQ multi-pass preset** -- `Config/MovieRender/MRQ_MultiPassEXR.uasset`：Deferred + Object Identifier + World Normal + Scene Depth + GBuffer A + multi-layer EXR 输出 + SS=8 TS=4 + deterministic CVars (motion blur / auto-exposure off)。验证 1 帧能跑通
- [ ] **P1: Robotics Plugin URDF import 验证** -- import FRANKA Panda + 写一段 BP 改 joint，确认 kinematic posing 通路
- [ ] **P2: custom UPCGSettings 模板** -- 给 xiaohuan 留一个 `Plugins/AdoreRobotPCG/Source/AdoreRobotPCG/Public/PCGSettings_Example.h` 样板，下次 xiaohuan 提需求时按这个模板写

## Boundary & Handoff

- **接 xiaohuan**: PCG graph asset + scene metadata + URDF joint state CSV/JSON
- **给 xiaohuan**: 如果他需要的功能内置节点搞不定，写 custom `UPCGSettings` 子类
- **给 xiaoxuan**: cooked package + MRQ preset，下游用 MRQ 渲染多层 EXR

## Reference 速查

详见 `agents/unreal/refs/`:
- `cheatsheet_mrq.md` -- MRQ multi-pass EXR 配置 + deterministic CVars
- `cheatsheet_custom_pcg_node.md` -- UPCGSettings 子类样板

## Changelog

_暂无，等首批 PR_
