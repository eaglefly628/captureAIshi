# Sekiro: Shadows Die Twice -- IGCS-GITC AOB Notes

Source: IGCS / ghostinthecamera-GITC  
Camera version: 2.10  
Engine: Custom FromSoftware engine  
Tested build: v1.06

## Struct Offsets (from camera struct base in rbx)

| Field | Offset | Type |
|-------|--------|------|
| Rotation matrix (3x3) | 0x10 | float32[9] (row-major) |
| Coordinates X/Y/Z | 0x40 / 0x44 / 0x48 | float32 |
| FOV | 0x50 | float32 |
| DoF focus | 0x28 | float32 |
| Timescale | 0x344 | float32 |

Note: Uses 3x3 rotation matrix, NOT quaternion. Matrix occupies 0x10..0x34 (9 floats).

## AOB Patterns

### CAMERA_ADDRESS_INTERCEPT / CAM_BLOCK1 (rbx = camera struct base)
```
21 19 C1 FF 0F 28 00 66 0F 7F 43 10
```
- `66 0F 7F 43 10` = MOVDQU [rbx+0x10], xmm0 (writes matrix into struct at rbx+0x10)
- struct_base_reg: rbx

### FOV_INTERCEPT
```
89 41 50 48 8B D9 8B
```
Hook offset: 0x03.

### DOF_KEY
```
41 3B 40 28 41 8B 41 2C
```
Hook offset: 0x11.

### TIMESTOP
```
F3 0F 59 88 68 02 00 00 F3 0F 59 88 64 03 00 00 48 8D 3D
```
Hook offset: 0x10.

### ULTRAWIDE (UWKEY)
```
F3 0F 58 4E 50 F3 0F 11 4E 50
```
Hook offset: 0x0E.

### PAUSE_BYTE
```
01 00 00 00 F3 0F 10 40 0C 0F 2F C6 0F 43 CA 88 0D 76 D0 30 03
```

## Notes

- Rotation is a 3x3 row-major float matrix, not a quaternion. The bridge camera_write_profile
  schema currently only supports quaternion and euler. Matrix rotation needs schema extension
  or conversion at the driver layer (matrix_to_quat conversion).
- struct_base_reg: rbx (confirmed by MOVDQU [rbx+0x10]).
- EAC present but SP mode can be launched without it (rename eac_launcher or use offline mode).
