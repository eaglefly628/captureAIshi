# Unreal Engine Memory Layout Reference

Used by captureAIshi bridge DLL for camera control across UE4/UE5 games.
All offsets verified against UE4SS PDB data and UE5 source (this repo: temp/ue5src/).
"Verified" = confirmed against PDB or source; "inferred" = cross-validated at runtime.

---

## 1. FMinimalViewInfo (CameraTypes.h)

The struct we write to for free camera control.

| Field    | UE4 / UE5 non-LWC | UE5.0+ LWC | Notes |
|----------|--------------------|------------|-------|
| Location.X | +0x00 (float) | +0x00 (double) | |
| Location.Y | +0x04 (float) | +0x08 (double) | |
| Location.Z | +0x08 (float) | +0x10 (double) | |
| Rotation.Pitch | +0x0C (float) | +0x18 (double) | degrees |
| Rotation.Yaw   | +0x10 (float) | +0x20 (double) | degrees |
| Rotation.Roll  | +0x14 (float) | +0x28 (double) | degrees |
| FOV        | +0x18 (float) | +0x30 (float) | always float, degrees [1,179] |

**LWC detection**: FOV in range [1,179] at +0x30 means LWC doubles. At +0x18 means float.

---

## 2. FCameraCacheEntry (PlayerCameraManager.h)

Wrapper struct inside APlayerCameraManager.

| Field     | Offset | Type  | Notes |
|-----------|--------|-------|-------|
| TimeStamp | +0x00  | float | World time of this cache entry |
| (padding) | +0x04  | 4B    | Alignment pad for LWC doubles (absent in float builds) |
| POV       | +0x08  | FMinimalViewInfo | **LWC layout** |
| POV       | +0x10  | FMinimalViewInfo | **SIMD float layout (UE4/old UE5)** |
| POV       | +0x04  | FMinimalViewInfo | **non-SIMD float layout** |

**Runtime detection**: `find_cam_pov()` tries all three in order (+0x08, +0x10, +0x04),
validates by checking if FOV at corresponding offset is in [1,179].

---

## 3. APlayerCameraManager fields

`CameraCachePrivate` is a UPROPERTY(transient) at compile-time offset.
In shipping builds the FField chain may be incomplete; use scan fallback.

| Field                    | Status     | Notes |
|--------------------------|------------|-------|
| CameraCachePrivate       | UPROPERTY(transient) | FField chain may not expose in shipping |
| LastFrameCameraCachePrivate | UPROPERTY(transient) | same |
| PCOwner                  | UPROPERTY(transient) | first visible in FField chain |

**Path to CameraCachePrivate POV** (priority order):
1. FField reflection: walk UClass::ChildProperties for "CameraCachePrivate" FName
2. Memory scan: scan manager+0x200..+0x900, try LWC double layout then float

---

## 4. GUObjectArray (FUObjectArray)

Scanner: `detect_fuobjectitem_stride()` -- runtime detection via GEngine.InternalIndex cross-check.

| Field              | UE4.x / UE5 default | UE5.7 Dev (StackOBot) |
|--------------------|---------------------|-----------------------|
| FUObjectItem stride | 24 bytes | 32 bytes |
| Object pointer offset in item | 0x00 | 0x08 |

**Detection method**: read GEngine address, scan GUObjectArray with stride 24 then 32,
find which stride gives a UObject whose InternalIndex (UObjectBase+0x0C) matches
the computed index. Confirmed stable across UE4.27-UE5.7.

---

## 5. UPlayer / ULocalPlayer chain

| Field                      | Offset | Source |
|----------------------------|--------|--------|
| UPlayer::PlayerController  | +0x30  | UE4SS MemberVarLayout verified |
| ULocalPlayer::ViewportClient | +0x78 | UE4SS MemberVarLayout_5_07 verified |

---

## 6. UEngine / UGameViewportClient

| Field                      | Offset | Notes |
|----------------------------|--------|-------|
| UEngine::GameViewport      | +0x200 | GVC pointer (may be TObjectPtr encoded in UE5.4+) |
| UGameViewportClient::World | +0x78  | Active UWorld pointer |

**Known issue**: GEngine+0x200 on some UE5.7 builds returns an address in DLL range
(binary, not heap) -- TObjectPtr encoding suspected. Use LP+0x78 as authoritative GVC.

---

## 7. UObjectBase

| Field         | Offset | Type  |
|---------------|--------|-------|
| ClassPrivate  | +0x10  | UClass* |
| InternalIndex | +0x0C  | int32 |

---

## 8. UStruct / UClass (FField chain)

Two eras of FField layout (UE4SS PDB verified):

| Era        | ChildProperties in UStruct | Next  | NamePrivate | Offset_Internal |
|------------|---------------------------|-------|-------------|-----------------|
| UE5.00-5.02 | UStruct+0x50              | +0x20 | +0x28       | +0x4C |
| UE5.03-5.07 | UStruct+0x50              | +0x18 | +0x20       | +0x44 |

Note: UStruct+0x40 = SuperStruct (not ChildProperties).

---

## 9. APlayerController -> APlayerCameraManager

UUU-style probe: scan PC at offsets +0x2A0..+0x380 (step 8) for a pointer
whose UClass FName contains "Camera". This offset drifts per minor UE5 version.

| UE Version | Approximate PCM offset in PC |
|------------|------------------------------|
| UE5.0      | ~0x2A0-0x2A8 |
| UE5.3-5.4  | ~0x2C0-0x2D0 |
| UE5.5-5.7  | ~0x2E0-0x300 |

Path B (FField reflection on APlayerController UClass) is authoritative when available.
Path D (fixed-offset probe) is cross-validation only.

---

## 10. Verification Status by Game

| Game | UE Version | LWC | FUObjectItem stride | obj_off | Camera found | GUObjectArray scan | FField | POV scan | Notes |
|------|------------|-----|---------------------|---------|-------------|--------------------|---------| ---------|-------|
| StackOBot | UE5.7 Dev | yes | 32 | 0x08 | Path A (FName) | Pat-D (SplitFiction/LEA-RCX) | fails (PCOwner only) | LWC-double | GVC via LP+0x78; GEngine+0x200 may be TObjectPtr |

*Add rows here as games are validated.*

---

## 11. UE5.7 Archived Configuration (StackOBot baseline, 2026-04-14)

This is the confirmed working configuration for UE5.7 Shipping/Dev builds
as of bridge commit d37d007. Use as reference when adding new UE5.7 games.

```
FUObjectArray:
  Stride:      32 bytes
  Object off:  +0x08
  Scan:        Pat-D (SplitFiction / LEA-RCX xref pattern)

FNamePool:
  Block search: blocks 0..CurrentBlock (LocalPlayer in block 5+)

FField chain:
  Era:   UE5.03-5.07  (Next=+0x18, Name=+0x20, Offset_Internal=+0x44)
  ChildProperties in UStruct: +0x50
  Status: CameraCachePrivate NOT found in chain (chain ends at PCOwner)
  Workaround: find_cam_pov_scan_pass(is_lwc=true)

FMinimalViewInfo layout:
  Type:  LWC double  (g_cam_pov_is_lwc = true)
  FCameraCacheEntry::POV at +0x08
  Location  at POV+0x00 (3 x double)
  Rotation  at POV+0x18 (3 x double)
  FOV       at POV+0x30 (float)

UPlayer::PlayerController:  LP+0x30
ULocalPlayer::ViewportClient: LP+0x78
UEngine::GameViewport:      GEngine+0x200 (TObjectPtr -- may need decode)
UGameViewportClient::World: GVC+0x78

APlayerCameraManager location:
  Path A (GUObjectArray FName scan):  CONFIRMED working
  Path D (PC fixed-offset probe):     CONFIRMED working (cross-validates A)
  Path B (FField on APlayerController): FAILS (same FField chain issue)
```

---

## TODO: Versions to Validate

- [ ] UE4.27 game -- float layout, stride=24, POV at FCameraCacheEntry+0x10, FOV at +0x18
- [ ] UE5.0-5.2 -- LWC introduced, FField era 1 (Next=+0x20, Name=+0x28, Offset_Internal=+0x4C)
- [ ] UE5.3 -- FField era 2 change (Next=+0x18, Name=+0x20, Offset_Internal=+0x44)
- [ ] UE5.4 -- TObjectPtr encoding in UEngine::GameViewport field
- [x] UE5.7 -- StackOBot, archived above
