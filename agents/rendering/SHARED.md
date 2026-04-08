# Rendering Agent (小萱) — Shared Notes

## Active TODO

### P0: Normal 自动检测帧间不稳定
p1-p3 检测正确，p0 选错了（彩虹圆环 debug buffer）。每帧 texture index 可能不同。
修复：第一帧 auto-detect 后锁定特征签名，后续帧复用。或 `--normal-index` 锁定。

### P1: Depth 归一化帧间不一致
每帧独立百分位映射导致 depth range 不同。修复：第一帧 range 复用，或固定 near/far。

### P1: 无 Float SceneColor 的游戏 RGB 含 UI
Fallback 到 SwapBuffer 有 UI overlay。修复：集成 renderdoc_hider 到 batch export。

## [v0.2.0] Key Specs (for other agents)

### trajectory.json schema
Position (Y-up m), Rotation (quaternion xyzw), fov_v, aspect, captureImg/depthImg/normalImg, viewName, pointIndex, splineMode

### File naming
`{timestamp}_{viewName}.png` / `_d.png` / `_n.png`

### GBuffer Layout (UE5)
CT0: SceneColor (RGBA16F), CT1: GBufferA/WorldNormal (RGB10A2), Depth: D32F reversed-Z

### CLI params
`--fov` (default 90), `--aspect` (default 16:9)

### UI 同学注意
- lightbox 支持 RGB/Depth/Normal 三种图
- trajectory.json 的 Position + Rotation 可画相机锥体

## Backlog (v0.3.0+)

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P0 | Depth 精度升级 | 16-bit PNG 或 EXR float32 |
| P0 | Motion Vector 导出 | UE5 Velocity buffer (RGBA16F) |
| P1 | Semantic Stencil | CustomDepth/Stencil |
| P1 | 多分辨率 | 1080p + 4K |
| P1 | HDR SceneColor EXR | RGBA16F → EXR |

## Changelog (latest)

### [v0.2.0] bfe81db — 小萱
- Normal 自动检测移到 Python 侧（PIL 分析 RGBA8 PNG）
- C++ 导出所有 ColorTarget 为 ct_{index}.png
- 覆盖率 + 蓝色占比启发式

旧版 CL 和已完成 TODO 见 `agents/rendering/ARCHIVE.md`。
