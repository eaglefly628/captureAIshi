# Watch Dogs 2 -- IGCS-GITC AOB Notes

Source: IGCS / ghostinthecamera-GITC  
Camera version: 1.0.5  
Engine: Disrupt (Ubisoft)  
Tested build: v1.016+

## Struct Offsets (from camera struct base in rbx)

| Field | Offset | Type |
|-------|--------|------|
| Coordinates X/Y/Z | 0x64 / 0x68 / 0x6C | float32 |
| Rotation/look X/Y/Z | 0x70 / 0x74 / 0x78 | float32 |
| FOV | 0x7C | float32 |
| Game speed | 0x84 | float32 |
| Time of day | 0x00 | float32 |

## AOB Patterns

### CAMERA_ADDRESS_INTERCEPT (rbx = camera struct base)
```
48 8B 44 24 20 48 89 43 70 8B 44 24 28 89 43 78 F3 0F 11 73 7C 8B 83
```
- `48 89 43 70` = MOV [rbx+0x70], rax (rotation at rbx+0x70)
- `F3 0F 11 73 7C` = MOVSS [rbx+0x7C], xmm6 (FOV at rbx+0x7C)
- struct_base_reg: rbx

Hook offset: 0x15.

### CAMERA_WRITE
```
41 89 00 8B 42 04 41 89 40 04 8B 42 08 41 89 40 08 48 8B 0D
```
Hook offset: 0x11.

### GAMESPEED_ADDRESS
```
F2 0F 10 93 80 00 00 00 66 0F 2F CA 72 03 0F 28 CA
```
Hook offset: 0x11.

### TOD_ADDRESS (time of day)
```
48 8B 08 48 8D 54 24 50 48 89 4C 24 20 48 8D 4C 24 20
```
Hook offset: 0x12.

### HOTSAMPLE_CODE
```
44 8B B3 ?? ?? ?? ?? 8B AB
```
Hook offset: 0x11.

## Notes

- Disrupt engine (Ubisoft). Same engine family as Watch Dogs 1 but different struct layout.
- Rotation at 0x70-0x78 is 3 floats -- likely a look-at vector or euler angles, not quaternion.
- struct_base_reg: rbx (confirmed by MOV [rbx+0x70] and MOVSS [rbx+0x7C]).
- No EAC. Ubisoft Connect DRM only. SP injection works fine.
