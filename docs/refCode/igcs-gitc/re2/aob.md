# Resident Evil 2 -- IGCS-GITC AOB Notes

Source: IGCS / ghostinthecamera-GITC  
Camera version: 1.0.2  
Engine: RE Engine (Capcom)  
Tested build: v1.0.2+

## Struct Offsets (from camera struct base)

| Field | Offset | Type |
|-------|--------|------|
| Coordinates X/Y/Z | 0x80 / 0x84 / 0x88 | float32 |
| Quaternion X/Y/Z/W | 0x90 / 0x94 / 0x98 / 0x9C | float32 |
| FOV | 0xA4 | float32 |
| Resolution scale | 0x11CC | float32 |
| Timestop float | 0x380 | float32 |
| Display type | 0x74 | byte |
| DoF selector | 0x4C | dword |
| HUD toggle | 0x8 | byte |

## AOB Patterns

### CAMERA_ADDRESS_INTERCEPT (captures struct base in rdx)
```
F3 0F 10 40 38 F3 0F 11 82 A4 00 00 00 48 83 79 18 00
```
Hook offset: 0x12. At hook point rdx = camera struct base.

### CAMERA_WRITE1 (FOV write)
```
F3 44 0F 10 40 34 8B 40 38 89 87 A4 00 00 00
```
Hook offset: 0x0F.

### CAMERA_WRITE2
```
F2 0F 5A C0 F3 0F 11 87 A4 00 00 00 48 8B 43 50 48 8B 48 18
```
Hook offset: 0x10.

### CAMERA_WRITE3 (coord write, rdi = struct base)
```
F3 0F 10 96 88 00 00 00 F3 0F 11 87 80 00 00 00
```
Hook offset: 0x18. At hook point rdi = destination camera struct base.

### TIMESTOP_READ
```
F3 0F 10 87 84 03 00 00 0F 2F C2 F3 0F 10 9F 80 03 00 00
```
Hook offset: 0x13.

### RESOLUTION_SCALE
```
F3 0F 10 80 CC 11 00 00 48 8D 44 24 54 F3 41 0F 59 46 40
```
Hook offset: 0x13.

### DOF_SELECTOR
```
89 51 4C 85 D2 74 0E 83 EA 01 74 09 83 FA 01 75 08 88 51 50 C3
```
Hook offset: 0x19.

## Notes

- Same engine as RE3 but different FOV offset (RE2: 0xA4, RE3: 0xB4) and slightly different quat base.
- CAMERA_ADDRESS_INTERCEPT is the primary hook for capturing the struct pointer (rdx).
- CAMERA_WRITE3 is the coord write and uses rdi as base -- same struct, different intercept register.
- Confirm which intercept register is active in the bridge hook with CE attach.
