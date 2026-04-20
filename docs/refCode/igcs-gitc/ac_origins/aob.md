# Assassin's Creed Origins -- IGCS-GITC AOB Notes

Source: IGCS / ghostinthecamera-GITC  
Camera version: 1.0.10  
Engine: AnvilNext 2.0 (Ubisoft)  
Tested build: v1.51+

## Struct Offsets (from camera struct base)

| Field | Offset | Type |
|-------|--------|------|
| Coordinates X/Y/Z | 0x60 / 0x64 / 0x68 | float32 |
| Secondary coords | 0x2E0 | float32 |
| Player model coords | 0x470 | float32 |
| Quaternion X/Y/Z/W | 0x70 / 0x74 / 0x78 / 0x7C | float32 |
| Player quaternion | 0x480 | float32 |
| FOV | 0x264 | float32 |
| Resolution scale | 0xA8 | float32 |
| Timestop flag 1 | 0x1458 | byte |
| Timestop flag 2 | 0x1460 | byte |

## AOB Patterns

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

- Camera write AOB patterns for AC Origins not extracted from public IGCS source.
  Use struct offsets (0x60 coords, 0x70 quat, 0x264 FOV) and scan for writes with CE.
- AnvilNext 2.0 uses the same Anvil base as Odyssey but with different struct layout (coords at 0x60 vs 0x90).
- struct_base_reg: TBD (CE verification needed). Likely rsi or rcx per Anvil convention.
- No EAC. Ubisoft Connect DRM only.
