// PathFollowerComponent.h
// ADORE Robot13 path follower -- attach to any Actor (typically
// Robot13_Blueprint). ADORE Python writes Waypoints + flips bIsWalking
// = true via ObjectTools.set_properties; this component owns the
// per-tick movement.
//
// Drop into:
//   apps/adore_robot/unreal_projects/AdoreRobot/Source/AdoreRobot/Public/
//
// Build.cs dependency: Core, CoreUObject, Engine, KismetMath.
// ASCII only -- enforced by .claude/rules/cpp-rules.md and /W4 /WX.

#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "PathFollowerComponent.generated.h"


UCLASS(ClassGroup = (Adore),
       meta = (BlueprintSpawnableComponent),
       DisplayName = "Path Follower")
class ADOREROBOT_API UPathFollowerComponent : public UActorComponent
{
    GENERATED_BODY()

public:
    UPathFollowerComponent();

    // World-space waypoints in cm. ADORE Python writes this array via
    // ObjectTools.set_properties before flipping bIsWalking = true.
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Path",
              meta = (ExposeOnSpawn = "true"))
    TArray<FVector> Waypoints;

    // Linear speed in cm/s. 200 cm/s = 2 m/s default.
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Path",
              meta = (ClampMin = "0.0", UIMin = "0.0", UIMax = "1000.0"))
    float WalkSpeed = 200.f;

    // Index of the waypoint the actor is currently walking toward.
    UPROPERTY(VisibleAnywhere, BlueprintReadWrite, Category = "Path")
    int32 CurrentIndex = 0;

    // Master on/off. ADORE sets this true after writing the path.
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Path")
    bool bIsWalking = false;

    // If true, wrap CurrentIndex back to 0 on overflow. If false, stop
    // walking when the last waypoint is reached.
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Path")
    bool bLoopPath = true;

    // Yaw the actor toward each next waypoint (pitch/roll left alone).
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Path")
    bool bRotateToFace = true;

    // Distance in cm at which a waypoint counts as reached.
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Path",
              meta = (ClampMin = "0.1"))
    float ArriveTolerance = 10.f;

    UFUNCTION(BlueprintCallable, Category = "Path")
    void StartWalking();

    UFUNCTION(BlueprintCallable, Category = "Path")
    void StopWalking();

    // One-shot helper: replace the path and start walking. ADORE Python
    // can use this instead of writing each field separately.
    UFUNCTION(BlueprintCallable, Category = "Path")
    void SetWaypointsAndStart(const TArray<FVector>& NewWaypoints,
                              bool bLoop = true);

    virtual void TickComponent(float DeltaTime,
                               ELevelTick TickType,
                               FActorComponentTickFunction* ThisTickFunction) override;

protected:
    virtual void BeginPlay() override;
};
