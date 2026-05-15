# Resident Evil 3 -- IGCS-GITC AOB Notes

Source: IGCS / ghostinthecamera-GITC  
Camera version: 1.0.3  
Engine: RE Engine (Capcom)  
Tested build: v1.0+

## Struct Offsets (from camera struct base)

| Field | Offset | Type |
|-------|--------|------|
| Coordinates X/Y/Z | 0x80 / 0x84 / 0x88 | float32 |
| Quaternion X/Y/Z/W | 0xA0 / 0xA4 / 0xA8 / 0xAC | float32 |
| FOV | 0xB4 | float32 |
| Resolution scale | 0x14B4 | float32 |
| Timestop float | 0x380 | float32 |
| Display type | 0x74 | byte |
| DoF selector | 0x4C | dword |
| HUD toggle | 0x8 | byte |

## Notes

- RE Engine, nearly identical to RE2. Key differences: quat at 0xA0 (vs 0x90) and FOV at 0xB4 (vs 0xA4).
- AOB patterns follow the same shape as RE2 with updated displacement bytes.
- Use CAMERA_ADDRESS_INTERCEPT from RE2 as template; wildcarded offsets should match RE3 binary.
- struct_base_reg: rdx (same as RE2 per RE Engine convention).
