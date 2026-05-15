# Movie Render Queue Cheatsheet

> Multi-pass EXR 配置，给下游 Cosmos Transfer 2.5 喂多通道数据。

## 配置入口

`Window` -> `Cinematics` -> `Movie Render Queue` -> 新建 preset，保存到 `Config/MovieRender/MRQ_MultiPassEXR.uasset`

## 必勾的 Render Pass

| Pass | 通道 | 用途 |
|---|---|---|
| **Deferred Rendering** | FinalImage (RGB) | 最终 beauty pass |
| **Object Identifier** | Object Id mask (uint32) | 实例分割 mask |
| **World Normal** | xyz (float16) | normal pass，下游 normal-aware loss |
| **Scene Depth** | linear depth (float32) | depth pass |
| **GBuffer A** | World Normal (alt) | xiaoxuan 可能要这个备份 |
| **Motion Vectors** (可选) | xy (float16) | 如果做 video，optical flow ground truth |

## Output 配置

- **Format**: `.exr (Multilayer)` -- 一个文件含所有 channel
- **Compression**: `PIZ` (无损，比 zip 快)
- **Resolution**: 1920x1080 起步 (符合 §9.1.6 训练分辨率)，必要时 4K
- **Output dir**: `{project_dir}/Saved/MovieRenders/{scene_id}/{variant_id}/frame_{frame_number}.exr`

## Anti-aliasing

- **Spatial Sample Count**: 8 (起步) / 16 (高质量)
- **Temporal Sample Count**: 4 (起步) / 8 (高质量)
- **Override Anti-Aliasing**: 勾，把 Temporal AA 关掉 (TAA + 多采样会冲突，多采样自己就是 AA)

## Deterministic CVars (Console Variables setting)

加这些避免每次 render 不一样：

```
r.MotionBlurQuality=0
r.EyeAdaptationQuality=0
r.AutoExposure.Method=2     # ManualExposure
r.Tonemapper.Quality=0      # 关 tonemapper bloom 之类 (训练用 raw beauty)
r.SkySpecularOcclusionStrength=0
r.AmbientOcclusionLevels=0  # 关 SSAO，要 GT 走 Lumen 自己的 AO
```

## Console Variables (Lumen + Nanite)

```
r.Nanite=1
r.Lumen.HardwareRayTracing=1   # 有 RTX 卡才开，否则 SW 模式自动
r.Lumen.Reflections.HardwareRayTracing=1
r.Shadow.Virtual.Enable=1
```

## CLI 渲染（自动化）

```bash
# Windows
"C:/Program Files/Epic Games/UE_5.6/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" ^
  "D:/Project/captureAIshi/apps/adore_robot/unreal_projects/AdoreRobot.uproject" ^
  -game ^
  -MoviePipelineConfig="/Game/Cinematics/MRQ_MultiPassEXR.MRQ_MultiPassEXR" ^
  -LevelSequence="/Game/Sequences/Warehouse_v0.Warehouse_v0" ^
  -ExecCmds="r.MotionBlurQuality 0"
```

## 常见坑

1. **PCG 没生成就开 render**：在 LevelSequence 加 PCGRefresh 事件 + delay 1s，确保 PCG Generate-on-Demand 跑完
2. **EXR multi-layer 软件打不开**：用 EXR-IO (Photoshop plugin) / OpenEXR `exrheader` 命令验证；OpenCV/imageio 直接读 channel 名
3. **Object Identifier 全黑**：actor 要勾 "Custom Depth/Stencil" 才会有 ID；或在 MRQ 设置里 "All actors get unique ID"
4. **Lumen 噪点严重**：`r.Lumen.ScreenProbeGather.NumAdaptiveProbes=1024` + Final Gather Sample Count 提到 64

## 验证脚本

```python
# 跑完 render 后用这个验证 EXR 通道齐全
import OpenEXR, Imath
exr = OpenEXR.InputFile("frame_0001.exr")
print(exr.header()["channels"].keys())
# 期望: dict_keys(['FinalImage.R', 'FinalImage.G', 'FinalImage.B',
#                  'WorldNormal.X', 'WorldNormal.Y', 'WorldNormal.Z',
#                  'SceneDepth.R', 'ObjectId.R', ...])
```
