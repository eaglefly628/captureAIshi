# Rendering Agent -- xiaoxuan

RenderDoc integration, GBuffer analysis, depth/normal export. Files: `renderdoc/renderdoccmd/`, `grabbers/`.

C++: ASCII only, `/W4 /WX`. Python: percentile depth normalization, FrameData(rgb, depth, normal).

renderdoccmd: `capture [--opt-*] <exe> [args]`. All `--opt-*` flags BEFORE the exe path.

Branch: `claudeMainBranch` only. TODO/specs in `agents/rendering/SHARED.md`.
