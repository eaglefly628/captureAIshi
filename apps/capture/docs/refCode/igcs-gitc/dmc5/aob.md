# Devil May Cry 5 -- IGCS-GITC AOB Notes

Source: IGCS / ghostinthecamera-GITC  
Camera version: 1.0.2  
Engine: RE Engine (Capcom, same as RE2/RE3)  
Tested build: v1.0.1+

## Struct Offsets (from captured camera struct pointer)

CAUTION: Offsets are NEGATIVE from the captured pointer. The pointer points INTO the
middle of the camera object. Coords and quat are before the pointer in memory.

| Field | Offset | Type |
|-------|--------|------|
| Coordinates X/Y/Z | -0xF0 / -0xEC / -0xE8 | float32 |
| Quaternion X/Y/Z/W | -0xE0 / -0xDC / -0xD8 / -0xD4 | float32 |
| FOV | 0x38 | float32 |
| DoF selector | 0x4C | dword |
| Display type | 0x74 | byte |
| Resolution scale | 0x126C | float32 |
| Timestop float | 0x380 | float32 |
| HUD toggle | 0x8 | byte |

## AOB Patterns

### CAMERA_ADDRESS_INTERCEPT
```
F3 0F 11 46 38 48 8B 43 50 48 83 78 18 00 75 ?? F3 0F
```
Hook offset: 0x0E. At hook point: rsi = camera object (FOV at rsi+0x38).

### CAMERA_WRITE1 (quat write, rdi = struct base)
```
41 8B 06 89 47 40 41 8B 46 04 89 47 44 41 8B 46 08 89 47 48 41 8B 46 0C 89 47 4C 80 BF D2 00 00 00 00
```
Hook offset: 0x1B.

### CAMERA_WRITE2 (coord write)
```
8B 08 89 4F 40 8B 48 04 89 4F 44 8B 48 08 89 4F 48 8B 40 0C 89 47 4C 80 BF D2 00 00 00 00
```
Hook offset: 0x17.

### CAMERA_WRITE3
```
EB ?? 41 8B 06 89 47 30 41 8B 46 04 89 47 34 41 8B 46 08 89 47 38 80 BF D2 00 00 00 00
```
Hook offset: 0x14.

### TIMESTOP_READ
```
F3 0F 10 8B ?? 03 00 00 F3 0F 10 83 ?? 03 00 00 F3 0F 59 8B ?? 03 00 00
```
Hook offset: 0x18.

### RESOLUTION_SCALE
```
F3 0F 10 80 6C 12 00 00 48 8D 44 24 3C F3 41 0F 59 46 40
```
Hook offset: 0x13.

## Notes

- Negative struct offsets are unusual. The bridge camera_write_profile schema does not support
  negative offsets -- needs schema extension or a secondary pointer that points to the actual
  start of the camera data block (ptr - 0xF0).
- For now, use the CAMERA_ADDRESS_INTERCEPT at rsi+0x38 for FOV (positive), and derive coords
  and quat by subtracting from that pointer (external pointer math needed in the driver).
- struct_base_reg TBD pending CE verification of which register holds the negative-offset data.
