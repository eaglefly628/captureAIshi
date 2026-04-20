# Assassin's Creed Odyssey -- IGCS-GITC AOB Notes

Source: IGCS / ghostinthecamera-GITC  
Camera version: 1.0.13  
Engine: Anvil Next (Ubisoft)  
Tested build: v1.5.0+

## Struct Offsets (from camera struct base in rsi)

| Field | Offset | Type |
|-------|--------|------|
| Coordinates X/Y/Z | 0x90 / 0x94 / 0x98 | float32 |
| Quaternion X/Y/Z/W | 0xA0 / 0xA4 / 0xA8 / 0xAC | float32 |
| FOV | 0xB0 | float32 |
| Resolution scale | 0xA4 | float32 |
| Timestop byte 1 | 0x1790 | byte |
| Timestop byte 2 | 0x1868 | byte |
| Timestop byte 3 | 0x1788 | byte |
| DoF enable 1/2 | 0x111 | byte |
| Fog strength | 0x20 | float32 |
| Fog start curve | 0x60 | float32 |

## AOB Patterns

### CAMERA_ADDRESS_INTERCEPT (rsi = camera struct base)
```
66 0F 7F 86 90 00 00 00 66 0F 7F 0F
```
- `66 0F 7F 86 90 00 00 00` = MOVDQU [rsi+0x90], xmm0 (coords at rsi+0x90)
- struct_base_reg: rsi

Hook offset: 0x12.

### CAMERA_WRITE1
```
0F 29 02 0F 28 71 20 41 0F 28 10 41 0F 28 38 0F 28 E2
```
Hook offset: 0x0F.

### CAMERA_WRITE2
```
41 0F 29 38 F3 0F 10 41 30 F3 41 0F 58 01 0F 28 3C 24 F3 41 0F 11 01
```
Hook offset: 0x17.

### TIMESTOP_READ
```
48 89 54 24 28 48 8B 57 18 83 E1 10 4C 31 C1 41 0F 29 7B A8
```
Hook offset: 0x14.

### TOD_WRITE (time of day)
```
0F 2F D1 F3 0F 11 12 72 ?? F3 0F 5C D1
```
Hook offset: 0x1C.

### RESOLUTION_SCALE
```
48 8B 70 60 48 8B 82 48 02 00 00 48 89 B4 24 B8 00 00 00
```
Hook offset: 0x17.

### FOG_READ
```
F3 41 0F 10 7E 58 F3 44 0F 59 51 20 F3 45 0F 10 46 50 0F 29 44 24 70
```
Hook offset: 0x12.

## Notes

- No anti-cheat. RenderDoc injection works fine.
- Ubisoft Connect DRM but no EAC/VAC.
