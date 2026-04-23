# Game Hack Profile Schema

One file per game in `configs/hacks/<id>.json`. Loaded by `drivers/game_profile.py` and applied to the running bridge at 127.0.0.1:9998.

## Top-level fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema_version` | int | yes | Currently `1`. |
| `id` | string | yes | Stable slug (matches filename). `a-z0-9_` only. |
| `display_name` | string | yes | Human-readable game name shown in UI dropdown. |
| `process_names` | string[] | yes | Executable names used for auto-detect (e.g. `["BatmanAK.exe"]`). |
| `engine` | string | yes | `UE3` / `UE4` / `UE5` / `CryEngine` / etc. Informational. |
| `engine_version` | string | no | Specific build the AOBs were derived from. |
| `credits` | string | no | Who figured out the AOBs (usually IGCS author). |
| `source` | string | no | Reference link / path (e.g. `docs/refCode/igcs/Cameras/BatmanArkhamKnight/`). |
| `notes` | string | no | Caveats for operator. |
| `intercepts` | object[] | yes | List of MOV-patch sites. See below. |
| `camera_write_profile` | object | no | Layout of camera struct for trajectory writing. |
| `launch_arg_style` | string | no | Launch arg format for windowed + resolution. `"unreal"` (default): `-Windowed -ResX=W -ResY=H`. `"redengine"`: `-windowed -width=W -height=H`. |

## `intercepts[]` item

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Identifier for `__cam_intercept_list` output. |
| `description` | string | no | What this block writes. |
| `size` | int | yes | Bytes to NOP (covers entire patched region). |
| `aob_literal` | string | prefer | Exact hex bytes from target build. Space-separated. |
| `aob_wildcard` | string | prefer | Version-tolerant variant with `??` wildcards. |
| `prefer` | string | no | `literal` (default) or `wildcard`. If preferred fails, the other is tried. |
| `default_mode` | string | no | `pass` (default) or `nop`. |

At least one of `aob_literal` or `aob_wildcard` must be present.

## `capture` (optional)

Per-game texture index overrides for `renderdoccmd exportframe`. Set indices by opening a `.rdc` file in the qrenderdoc GUI with `--dump-all` to see all ColorTargets, then pin the correct ones here. All fields default to auto-detect (-1 / true / null).

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `rgb_index` | int | -1 | Texture index for RGB output. -1 = auto (first Float ColorTarget, fallback SwapBuffer). |
| `normal_index` | int | -1 | Texture index for normal map. -1 = auto (R10G10B10A2 scan + pipeline state). |
| `depth_index` | int | -1 | Texture index for depth. -1 = auto (first DepthTarget). |
| `depth_reversed_z` | bool | true | Applied Python-side in image_loader. true = UE5 reversed-Z (near->1, far->0) renders near=white. false = UE3/standard (near->0, far->1) renders near=white. |
| `depth_range` | [float,float] or null | null | Applied Python-side. Fixed [black_point, white_point] for raw-float depth.exr normalization. null = auto (1st-99th percentile per frame). |

## `camera_write_profile` (optional, future use)

Enables trajectory playback. Currently only UE4/UE5 auto-populate this via `find_cam_pov`. Non-UE games wait for the asm pointer-capture stub.

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | bool | `false` until pointer-capture is implemented. |
| `struct_base_reg` | string | Register holding camera struct at intercept time (`rbx` / `rsi` / `rdi` / etc.). |
| `capture_from_intercept` | string | Name of intercept whose trampoline captures the register. |
| `location` | object | `{ x, y, z, type }` where `type` is `float32` or `double64`. |
| `rotation` | object | `{ pitch, yaw, roll, type }` where `type` is `float32`, `double64`, or `ue3_packed_int`. |
| `rotation_matrix` | object | `{ row0, row1, row2, type, rotation_convention }`. Offsets to the 3 basis-vector rows (each 3 floats, stride 4 bytes). `rotation_convention` is `"ac6"` (default, IGCS-GITC DirectX LH: M=Mz(-r)·Mx(-p)·My(y)) or `"metro"` (4A Engine cryengine-specific: M=Mx(-r)·Mz(-p)·My(y)). |
| `fov` | object | `{ off, type }`. |

All `_off` / `x` / `y` / ... fields accept either `"0x574"` (hex string) or `1396` (decimal int).

## Conventions

- Literal AOBs come verbatim from IGCS reference code or in-house CE analysis.
- Wildcard AOBs mask version-dependent immediates (disp8, disp32 low bytes, strings).
- Keep `size` minimal: NOP only as many bytes as needed. Large NOP regions risk nuking load instructions.
