# Robotics Poser Interface (A / B / C all-pluggable)

> Author: 老白. Date: 2026-05-17. Status: design, pre-implementation.
> Trigger: 老白 2026-05-15 decision -- not picking A / B / C up-front; all
> three (and possibly D = future Epic official) must implement the same
> interface so they can hot-swap per-scene.

Audience: xiaoxu (UE-side C++ interface + 3 adapter shells) + xiaohuan (the
`scene_spec.robotics_backend` field consumer in PCG metadata).

---

## §0 Plan D Placeholder -- Epic Official Robotics Plugin

**Status (2026-05-17): not verified yet.** xiaoxu has UE5.8 Preview install
TODO. On first install:

1. Open `Plugin Manager`, search `Robot`, `URDF`, `Articulation`, `Inverse
   Kinematics`. Capture screenshots.
2. If any official plugin appears under `Engine/Plugins/Experimental/` or
   `Engine/Plugins/Runtime/`, add a `[verified <date>]` line below + write
   `Plan D` row in §3 and stub `RobotPoser_EpicOfficial` adapter.
3. If nothing official appears, mark this section `[verified <date>: no
   official plugin in 5.8 Preview]` and move on; Plan A/B/C only.

This is the **only** part of this doc that can change without a full
revision. The interface (§1, §2) is locked once xiaoxu starts shell code.

---

## §1 UE5 `IRobotPoser` Interface (C++ `UInterface`)

### 1.1 Why `UInterface` (not pure BP)

We pick C++ `UInterface` because:
- Adapters need to call native plugin APIs (URLab is C++, URoboSim is C++,
  Minimal is C++ -- BP interface forces an unnecessary BP -> native bounce).
- The pose tool surface (`UPCGAdoreToolset`) lives in C++; same module call
  graph.
- BP-only interfaces can't return non-blueprintable types like
  `TSharedPtr<...>` for the handle internals.

If a future use case needs BP-only consumers, add a `BlueprintInterface`
shim that wraps `IRobotPoser` -- don't replace it.

### 1.2 Header (target: `Plugins/AdoreRobotPCG/Source/AdoreRobotPCG/Public/RobotPoserInterface.h`)

```cpp
#pragma once

#include "CoreMinimal.h"
#include "UObject/Interface.h"
#include "Engine/EngineTypes.h"
#include "Math/Transform.h"
#include "RobotPoserInterface.generated.h"

// Backend-opaque handle. Identifies a loaded URDF model instance.
// Backends each maintain their own int -> internal-object map.
USTRUCT(BlueprintType)
struct ADOREROBOTPCG_API FRobotHandle
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly)
    int32 Id = INDEX_NONE;

    UPROPERTY(BlueprintReadOnly)
    FName BackendTag;        // "urlab" / "urobosim" / "minimal" / "epic_official"

    bool IsValid() const { return Id != INDEX_NONE && !BackendTag.IsNone(); }
};

USTRUCT(BlueprintType)
struct ADOREROBOTPCG_API FJointLimits
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly) float LowerRad = 0.f;
    UPROPERTY(BlueprintReadOnly) float UpperRad = 0.f;
    UPROPERTY(BlueprintReadOnly) bool bContinuous = false; // unlimited revolute
};

UINTERFACE(MinimalAPI, Blueprintable)
class URobotPoserInterface : public UInterface
{
    GENERATED_BODY()
};

class ADOREROBOTPCG_API IRobotPoserInterface
{
    GENERATED_BODY()

public:
    /** Parse a URDF file from disk; return a backend-specific handle.
     *  Returns invalid FRobotHandle on parse failure. */
    UFUNCTION(BlueprintCallable, Category="Robotics")
    virtual FRobotHandle LoadURDF(const FString& AbsolutePath) = 0;

    /** All joint names declared in the URDF, in declaration order. */
    UFUNCTION(BlueprintCallable, Category="Robotics")
    virtual TArray<FName> GetJointNames(const FRobotHandle& Handle) const = 0;

    /** Joint limits from URDF (revolute / continuous / prismatic).
     *  Prismatic limits are in meters in LowerRad / UpperRad fields
     *  (interpret per joint type). bContinuous true => unlimited revolute. */
    UFUNCTION(BlueprintCallable, Category="Robotics")
    virtual FJointLimits GetJointLimits(const FRobotHandle& Handle, FName JointName) const = 0;

    /** Set all joint state values at once. Keys are joint names;
     *  values are radians (revolute) or meters (prismatic).
     *  Missing joints keep current pose. */
    UFUNCTION(BlueprintCallable, Category="Robotics")
    virtual void SetJointState(const FRobotHandle& Handle, const TMap<FName, float>& JointValues) = 0;

    /** Forward kinematics on demand: world transform of a named link.
     *  Caller must SpawnInLevel first; otherwise returns identity + logs warning. */
    UFUNCTION(BlueprintCallable, Category="Robotics")
    virtual FTransform GetLinkTransform(const FRobotHandle& Handle, FName LinkName) const = 0;

    /** Instantiate the robot as actor(s) in the active world at WorldTransform.
     *  Returns the root actor (may have child actor / component hierarchy). */
    UFUNCTION(BlueprintCallable, Category="Robotics")
    virtual AActor* SpawnInLevel(const FRobotHandle& Handle, const FTransform& WorldTransform) = 0;

    /** Despawn + free backend resources. Subsequent calls with this handle
     *  return invalid / identity. Safe to call on already-destroyed handle. */
    UFUNCTION(BlueprintCallable, Category="Robotics")
    virtual void DestroyHandle(const FRobotHandle& Handle) = 0;

    /** Backend identity for logging / scene_spec.robotics_backend match. */
    UFUNCTION(BlueprintCallable, Category="Robotics")
    virtual FName GetBackendTag() const = 0;
};
```

### 1.3 Method semantics -- contract

| Method | Required behavior |
|---|---|
| `LoadURDF` | Must accept absolute path. If relative, log warning and reject. URDF parsing failure -> return invalid handle + log; do NOT throw. Re-loading the same path returns a new handle (caller-managed identity). |
| `GetJointNames` | Order = URDF declaration order. Stable across calls for the same handle. Empty array on invalid handle. |
| `GetJointLimits` | Unknown joint -> `FJointLimits{0,0,false}` + log warning. Continuous revolute sets `bContinuous=true`, `LowerRad=UpperRad=0`. |
| `SetJointState` | Atomic: either all known joints applied or none (validate before write). Unknown joint names: log warning + skip; do not abort the whole call. Backends must clamp to `GetJointLimits` before applying. |
| `GetLinkTransform` | If not spawned: log + return `FTransform::Identity`. If spawned: world-space transform after current joint state. |
| `SpawnInLevel` | One actor or actor hierarchy per call. Returns nullptr on invalid handle or no active world. Caller owns despawning (via `DestroyHandle`). |
| `DestroyHandle` | Idempotent. Free actor(s) + internal state. Safe on already-invalid handle (no-op). |
| `GetBackendTag` | Returns the same `FName` used in `FRobotHandle::BackendTag`. Strings: `urlab`, `urobosim`, `minimal`, `epic_official`. ASCII snake_case. |

Backends are NOT required to:
- Handle multiple worlds simultaneously (single editor world assumption).
- Persist joint state across editor PIE start/stop.
- Implement IK / motion planning -- this interface is **kinematic posing only**
  (set joint angles, get link transforms). Anything else is out of scope per
  §9.1.6 of `robotics_scene_foundry_pitch.md`.

### 1.4 Backend tag enum (`scene_spec.robotics_backend` consumer)

```cpp
UENUM(BlueprintType)
enum class EAdoreRoboticsBackend : uint8
{
    Minimal        UMETA(DisplayName = "minimal"),       // Plan C default
    URLab          UMETA(DisplayName = "urlab"),         // Plan A
    URoboSim       UMETA(DisplayName = "urobosim"),      // Plan B
    EpicOfficial   UMETA(DisplayName = "epic_official"), // Plan D (verify §0)
};
```

xiaohuan's `scene_spec.json` adds optional `robotics_backend` (default
`minimal`) -- absent field implies Plan C. Backend selection is per-scene,
not per-robot; mixing backends inside one scene is explicitly unsupported
(adds N-squared interop testing for no real-world need).

---

## §2 Python `RobotPoserBase` (Editor commandlet / unattended use)

For headless commandlet workflows (Plan B-2 batch fallback per
`batch_scene_gen_architecture_v2.md` §1.3), Python mirrors the C++
interface and dispatches through `unreal.py` to the same backend
implementation.

### 2.1 Module layout

```
apps/adore_robot/robotics/
+-- __init__.py
+-- base.py             (RobotPoserBase ABC + dataclasses)
+-- factory.py          (make_poser(backend))
+-- minimal.py          (RobotPoser_Minimal -- Plan C, default)
+-- urlab.py            (RobotPoser_URLab    -- Plan A, shell)
+-- urobosim.py         (RobotPoser_URoboSim -- Plan B, shell)
```

### 2.2 ABC (`apps/adore_robot/robotics/base.py`)

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class RobotHandle:
    id: int
    backend_tag: str   # "minimal" / "urlab" / "urobosim" / "epic_official"

    @property
    def is_valid(self) -> bool:
        return self.id >= 0 and bool(self.backend_tag)


@dataclass(frozen=True)
class JointLimits:
    lower_rad: float       # radians (revolute) or meters (prismatic)
    upper_rad: float
    is_continuous: bool    # unlimited revolute


class RobotPoserBase(ABC):
    """Python mirror of UE's IRobotPoserInterface.

    Each concrete subclass keeps its own int -> internal-object map.
    Handles from one backend are NOT portable to another.
    """

    backend_tag: str = ""  # subclasses must set

    @abstractmethod
    def load_urdf(self, absolute_path: str) -> RobotHandle: ...

    @abstractmethod
    def get_joint_names(self, handle: RobotHandle) -> list[str]: ...

    @abstractmethod
    def get_joint_limits(self, handle: RobotHandle, joint_name: str) -> JointLimits: ...

    @abstractmethod
    def set_joint_state(self, handle: RobotHandle, values: Mapping[str, float]) -> None: ...

    @abstractmethod
    def get_link_transform(self, handle: RobotHandle, link_name: str):
        """Returns unreal.Transform (when run inside unreal.py) or a (location, rotation, scale) tuple."""
        ...

    @abstractmethod
    def spawn_in_level(self, handle: RobotHandle, world_transform) -> object:
        """Returns the spawned actor (unreal.Actor) or None on failure."""
        ...

    @abstractmethod
    def destroy_handle(self, handle: RobotHandle) -> None: ...

    def get_backend_tag(self) -> str:
        return self.backend_tag
```

### 2.3 Factory

```python
# apps/adore_robot/robotics/factory.py
from __future__ import annotations
from typing import Literal

from .base import RobotPoserBase

BackendName = Literal["minimal", "urlab", "urobosim", "epic_official"]


def make_poser(backend: BackendName = "minimal") -> RobotPoserBase:
    if backend == "minimal":
        from .minimal import RobotPoser_Minimal
        return RobotPoser_Minimal()
    if backend == "urlab":
        from .urlab import RobotPoser_URLab
        return RobotPoser_URLab()
    if backend == "urobosim":
        from .urobosim import RobotPoser_URoboSim
        return RobotPoser_URoboSim()
    if backend == "epic_official":
        # populated only after §0 verification finds an official plugin
        raise NotImplementedError("epic_official backend pending §0 plugin verification")
    raise ValueError(f"unknown backend {backend!r}")
```

### 2.4 Concrete adapters (empty shells, mapping strategy only)

Each `*.py` file is a docstring-heavy stub describing the mapping. **Do
not implement in this PR** -- xiaoxu wires the actual calls when the
chosen backend is reached (Plan C first per §3.5).

```python
# apps/adore_robot/robotics/minimal.py
"""RobotPoser_Minimal -- self-hosted URDF parser + UE Actor BP driver.

Mapping strategy (xiaoxu fills on implementation):
- URDF parse: vendor `urdfpy` (LGPL, vendored under apps/adore_robot/3rdparty/)
  or hand-rolled XML walker (URDF is small enough); xiaoxu picks at impl time.
- Spawned actor: one parent AActor + one child UStaticMeshComponent per link;
  joints are SceneComponent transforms (no Articulation).
- SetJointState: walk the joint tree, apply rotations to child components.
- GetLinkTransform: built-in USceneComponent::GetComponentTransform on the
  named link's component.

Limitations: no physics, no collision interactions, no soft-body. Pure
kinematic posing. Sufficient for scene_spec staging (robot in known pose
at known scene location, camera renders, dataset captures).
"""

class RobotPoser_Minimal:
    backend_tag = "minimal"
    # ... (xiaoxu implements)
```

```python
# apps/adore_robot/robotics/urlab.py
"""RobotPoser_URLab -- wraps URLab plugin's API (Plan A).

Mapping strategy (xiaoxu fills on implementation):
- LoadURDF -> URLab `UURDFImporter::ImportURDF(Path)` -> returns
  `AURLabRobot*`. Wrap in FRobotHandle{id=next_id(), backend_tag="urlab"}.
- GetJointNames -> AURLabRobot::GetJointNames().
- SetJointState -> AURLabRobot::SetJointPositions(Map).
- GetLinkTransform -> AURLabRobot::GetLinkComponent(Name)->GetComponentTransform().
- SpawnInLevel -> URLab's actor IS the spawn; we just SetActorTransform.
- DestroyHandle -> AActor::Destroy() + remove from map.

5.8 compatibility: TBD. URLab 5.7-tagged release exists; 5.8 fork may be
needed. xiaoxu validates at backend-switch time.
"""

class RobotPoser_URLab:
    backend_tag = "urlab"
    # ... (xiaoxu implements when Plan A activated)
```

```python
# apps/adore_robot/robotics/urobosim.py
"""RobotPoser_URoboSim -- wraps URoboSim plugin (Plan B).

Mapping strategy (xiaoxu fills on implementation):
- LoadURDF -> URoboSim's `URoboSimURDFParser` + spawn `AURoboSimRobot`.
- GetJointNames / SetJointState -> URoboSim's `UJointController` interface.
- GetLinkTransform -> URoboSim links are USkeletalMeshComponent bones,
  use `GetBoneTransform` after dispatching tick.
- Limitations: URoboSim assumes physics articulation; we override
  `bSimulatePhysics=false` on init.
"""

class RobotPoser_URoboSim:
    backend_tag = "urobosim"
    # ... (xiaoxu implements when Plan B activated)
```

### 2.5 Python <-> UE bridge

When running inside `UnrealEditor-Cmd.exe -run=PythonScript`, the Python
adapter dispatches to the UE-side `UPCGAdoreToolset` (which holds an
`IRobotPoserInterface*`) via reflection:

```python
import unreal
toolset = unreal.PCGAdoreToolset.get_default_object()
toolset.set_joint_state(handle.id, {"shoulder_pan_joint": 0.5, "elbow_joint": -1.2})
```

The Python adapter wraps these calls; users of `RobotPoserBase` never see
`unreal.*` directly. This keeps Python tests runnable outside UE (with a
mock backend).

---

## §3 Plan Comparison + Activation Order

### 3.1 Comparison matrix

| | **Plan C (Minimal)** | **Plan A (URLab)** | **Plan B (URoboSim)** | **Plan D (Epic)** |
|---|---|---|---|---|
| Maintainership | Us | URLab-Sim org (active) | IAI Bremen (active, ROS-focused) | Epic (TBD per §0) |
| 5.8 compat | Our problem (small surface) | Unknown -> needs fork or upstream PR | Unknown -> ditto | Native by assumption |
| Implementation effort | 2-3w (URDF parser + spawner) | 1w (wrap + plumbing) | 1w (wrap + plumbing) | 0.5w (wrap) |
| Physics fidelity | None (kinematic) | MuJoCo (high) | PhysX articulation (high) | TBD |
| Dependency footprint | None | URLab plugin + MuJoCo binaries | URoboSim + ROS-style stack | Epic experimental plugin |
| Use case fit (foundry) | Perfect (static pose for capture) | Overkill (we don't sim physics per §9.1.6) | Overkill + ROS overhead | TBD |

### 3.2 Activation order (老白 decision)

1. **Plan C (Minimal)** -- ship first. Satisfies the entire foundry use
   case (set joint angles, render). Lowest dependency risk. Pure
   kinematic, no MuJoCo / no ROS.
2. **Plan A (URLab)** -- add second, **only if** a customer asks for
   MuJoCo-grade physics validation on the rendered data. Most customers
   use their own physics-sim post-render; we don't need to provide it.
3. **Plan B (URoboSim)** -- add third or skip entirely; redundant with A
   for our use case, but kept in interface to avoid lock-in.
4. **Plan D (Epic)** -- swap-in if Epic ships official + it's competitive.

**Hard constraint**: even though Plans A/B/D are not implemented in this
PR, the interface in §1 / §2 **must satisfy all four**. Renaming a method
or changing a signature later forces all backend wrappers to refactor at
once. Method set is locked here.

### 3.3 Switching backend per scene

`scene_spec.<scene>_<variant>.json` adds:

```json
{
  ...,
  "robotics_backend": "minimal",
  "robots": [
    {
      "urdf_path": "Content/Robots/franka_panda.urdf",
      "world_transform": {"pos": [1.0, 0.0, 0.0], "rot_euler_deg": [0, 0, 90]},
      "joint_state": {"panda_joint1": 0.0, "panda_joint2": -0.5, ...}
    }
  ]
}
```

`robotics_backend` is optional; absent => `minimal`. `joint_state` keys
must match `get_joint_names()` for that URDF; unknown keys logged + skipped
per §1.3.

xiaohuan's PCG metadata writer adds the `robots` block (currently only
spawns non-articulated meshes); xiaoxu's commandlet reads it post-PCG-
generate, calls `make_poser(scene_spec.robotics_backend)`, walks `robots`,
spawns each.

---

## §4 What This PR Delivers vs Defers

### 4.1 In this PR (老白, 2026-05-17)

- This design doc (`apps/adore_robot/docs/robotics_poser_interface.md`).
- Nothing else. No code, no shells, no scene_spec field add.

### 4.2 Deferred to xiaoxu (next session, post-UE5.8 install)

- §0 verification + edit (Plan D verdict).
- `Plugins/AdoreRobotPCG/Source/AdoreRobotPCG/Public/RobotPoserInterface.h` per §1.2.
- `apps/adore_robot/robotics/` skeleton (5 files per §2.1).
- `RobotPoser_Minimal` first-cut implementation (URDF parse + actor spawn
  + joint apply) -- Plan C is the only one with code.
- `scene_spec` schema update: add `robotics_backend` + `robots` fields
  (coordinate with xiaohuan in `agents/pcg/SHARED.md`).

### 4.3 Deferred indefinitely (until customer demand)

- Plan A / Plan B implementations (kept as docstring stubs).
- Plan D plugin discovery only happens once UE5.8 verified.
- Multi-world support, IK solver, motion planning, physics callbacks --
  out of scope per `robotics_scene_foundry_pitch.md` §9.1.6.

---

## §5 Edge Cases + Failure Modes

| Scenario | Behavior |
|---|---|
| Load URDF with malformed XML | LoadURDF returns invalid handle, logs error with file + line. Subsequent calls with invalid handle are no-ops. |
| Joint name typo in `scene_spec.joint_state` | Backend logs warning + skips that joint. Other joints applied. No exception. |
| Out-of-limit joint value (per `GetJointLimits`) | Clamp to nearest limit. Log info-level "clamped joint X from V to limit L". |
| Backend not installed (URLab not found) | `make_poser("urlab")` raises ImportError at construction time with hint "install URLab plugin first". |
| `SpawnInLevel` called without an active editor world | Returns nullptr / None + logs error. (Commandlet workflows must open a level first.) |
| `DestroyHandle` called twice | Second call is a no-op + warns "handle already destroyed". |
| Editor PIE restart between `LoadURDF` and `SpawnInLevel` | Handle is invalidated (actor references stale). `SpawnInLevel` returns nullptr + logs. Caller must `LoadURDF` again. (Backends MAY harden against this, but not required.) |
| Backend tag mismatch (handle says "urlab", caller calls minimal-backend method) | Method returns gracefully (empty / identity) + logs "handle backend tag X does not match poser backend tag Y". |

---

## §6 References

- `apps/adore_robot/docs/robotics_scene_foundry_pitch.md` §9.1.6 (no
  physics-sim scope decision)
- `apps/adore_robot/docs/batch_scene_gen_architecture_v2.md` §1.3 (Plan
  B-1 vs B-2 batch path -- robotics adapters live on the editor side, not
  the commandlet side, regardless of which is chosen)
- `apps/adore_robot/docs/ue58_engine_notes_xiaoxu.md` §5 (original
  Robotics Plugin red-flag note that motivated this doc)
- URDF spec: https://wiki.ros.org/urdf/XML
- URLab: https://github.com/URLab-Sim/UnrealRoboticsLab
- URoboSim: https://github.com/urobosim/URoboSim
- urdfpy (Python parser candidate for Plan C): https://github.com/mmatl/urdfpy
