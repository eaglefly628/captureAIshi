# Shadow of the Tomb Raider -- IGCS-GITC AOB Notes

Source: IGCS / ghostinthecamera-GITC  
Engine: Foundation (Crystal Dynamics/Eidos)  
Tested build: v1.0.6

## Struct Offsets (from camera struct base in rcx)

| Field | Offset | Type |
|-------|--------|------|
| Coordinates X/Y/Z | 0x80 / 0x84 / 0x88 | float32 |
| Quaternion X/Y/Z/W | 0xA0 / 0xA4 / 0xA8 / 0xAC | float32 |
| FOV | 0xB0 | float32 |

## AOB Patterns

### CAMERA_ADDRESS_INTERCEPT (occurrence=1)
```
89 59 28 45 33 C0 0F 28 82 80 00 00 00 4C 8B F9 41 0F B6 D1
```
Hook offset: 1, occurrence: 1.

### CAMERA_WRITE1 (rcx = camera struct base)
```
66 0F 7F 81 80 00 00 00 0F 28 8A A0 00 00 00 0F 29 89 A0 00 00 00 8B 82
```
- `66 0F 7F 81 80 00 00 00` = MOVDQU [rcx+0x80], xmm0 (coords at rcx+0x80)
- `0F 29 89 A0 00 00 00` = MOVAPS [rcx+0xA0], xmm1 (quat at rcx+0xA0)
- struct_base_reg: rcx

Hook offset: 1, occurrence: 1.

### CAMERA_AR_FIX (aspect ratio)
```
F3 0F 10 87 D4 01 00 00 F3 0F 11 46 24 F3 0F 10 87 E0 01 00 00 F3 0F 11 46 28
```
Hook offset: 1, occurrence: 1.

## Notes

- Quaternion format. struct_base_reg: rcx (confirmed by MOVDQU [rcx+0x80]).
- Struct layout mirrors AC Odyssey (coords at 0x80, quat at 0xA0, FOV at 0xB0).
- No EAC. Denuvo DRM on newer builds may interfere with some injection methods.
  RenderDoc injection via renderdoccmd should work (injects before DRM initialises).
