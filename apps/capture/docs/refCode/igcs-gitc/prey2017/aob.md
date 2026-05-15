# Prey (2017) -- IGCS-GITC AOB Notes

Source: IGCS / ghostinthecamera-GITC  
Camera version: 1.0.5  
Engine: CryEngine V (Arkane/Crytek)  
Tested build: v1.0.4+

## Struct Offsets (from camera struct base in rsi)

| Field | Offset | Type |
|-------|--------|------|
| Coordinates X/Y/Z | 0x00 / 0x04 / 0x08 | float32 |
| FOV | 0x08 | float32 |
| Look data (euler) | 0x0C / 0x10 / 0x14 | float32 |
| Timestop | 0x08 | float32 |

Note: FOV and Z coord share offset 0x08 per IGCS reference. Likely two separate structs
pointed at by different intercepts. Verify with CE attach.

## AOB Patterns

### CAMERA_ADDRESS_INTERCEPT (rsi = camera struct base)
```
F3 0F 11 4E 0C F3 0F 11 56 10 F3 0F 11 5E 14 F3 0F 11 46 18 F3 0F 11 3E F3 0F 11 76 04 F3 44 0F 11 46 08
```
- `F3 0F 11 3E` = MOVSS [rsi], xmm7 (X coord at rsi+0x0)
- `F3 0F 11 76 04` = MOVSS [rsi+0x04], xmm6 (Y coord at rsi+0x04)
- `F3 0F 11 4E 0C` = MOVSS [rsi+0x0C], xmm1 (look data at rsi+0x0C)
- struct_base_reg: rsi

Hook offset: 0x23.

### FOV_INTERCEPT
```
F3 0F 58 48 08 0F 2F C8 76 03 0F 28 C1 48 83 C4 20
```
Hook offset: 0x11.

### CAMERA_WRITE1
```
8B 02 89 01 8B 42 04 89 41 04
```
Hook offset: 0x28.

### CAMERA_WRITE2
```
F3 44 0F 58 68 04 F3 44 0F 58 20 F3 44 0F 58 70 08 F3 44 0F 11 67 1C F3 44 0F 11 6F 20
```
Hook offset: 0x1D.

### CAMERA_WRITE3
```
F3 44 0F 11 77 24 F3 0F 10 8D 88 00 00 00 48 8D 4F 1C
```
Hook offset: 0x12.

### TIMESTOP
```
48 89 5C 24 10 48 89 6C 24 18 48 89 74 24 20 57 41 54 41 55 41 56 41 57 48 83 EC 40 48 8B B1
```
Hook offset: 0x0F.

## Notes

- CryEngine V stores coordinates and look data as floats. "Look data" at 0x0C is likely
  pitch/yaw/roll in degrees (CryEngine FCamera::SetRotation style).
- struct_base_reg: rsi (confirmed by MOVSS [rsi], xmm7 and MOVSS [rsi+0x04], xmm6).
- No anti-cheat in SP.
