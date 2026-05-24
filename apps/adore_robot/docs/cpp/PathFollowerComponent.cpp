// PathFollowerComponent.cpp
// Drop into:
//   apps/adore_robot/unreal_projects/AdoreRobot/Source/AdoreRobot/Private/
//
// ASCII only -- see .claude/rules/cpp-rules.md.

#include "PathFollowerComponent.h"

#include "GameFramework/Actor.h"
#include "Kismet/KismetMathLibrary.h"


UPathFollowerComponent::UPathFollowerComponent()
{
    PrimaryComponentTick.bCanEverTick = true;
    PrimaryComponentTick.bStartWithTickEnabled = true;
}

void UPathFollowerComponent::BeginPlay()
{
    Super::BeginPlay();
    if (Waypoints.Num() > 0)
    {
        CurrentIndex = FMath::Clamp(CurrentIndex, 0, Waypoints.Num() - 1);
    }
    else
    {
        CurrentIndex = 0;
    }
}

void UPathFollowerComponent::StartWalking()
{
    bIsWalking = true;
}

void UPathFollowerComponent::StopWalking()
{
    bIsWalking = false;
}

void UPathFollowerComponent::SetWaypointsAndStart(
    const TArray<FVector>& NewWaypoints, bool bLoop)
{
    Waypoints = NewWaypoints;
    CurrentIndex = 0;
    bLoopPath = bLoop;
    bIsWalking = (Waypoints.Num() > 0);
}

void UPathFollowerComponent::TickComponent(
    float DeltaTime,
    ELevelTick TickType,
    FActorComponentTickFunction* ThisTickFunction)
{
    Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

    if (!bIsWalking)
    {
        return;
    }

    const int32 N = Waypoints.Num();
    if (N == 0)
    {
        return;
    }
    if (CurrentIndex < 0 || CurrentIndex >= N)
    {
        CurrentIndex = 0;
    }

    AActor* Owner = GetOwner();
    if (Owner == nullptr)
    {
        return;
    }

    const FVector Current = Owner->GetActorLocation();
    const FVector Target = Waypoints[CurrentIndex];
    const FVector Delta = Target - Current;
    const float Distance = Delta.Size();

    // Arrived at this waypoint -- advance / stop / loop.
    if (Distance < ArriveTolerance)
    {
        const int32 Next = (CurrentIndex + 1) % N;
        if (!bLoopPath && Next == 0)
        {
            bIsWalking = false;
            return;
        }
        CurrentIndex = Next;
        return;
    }

    // Step toward target; never overshoot.
    const FVector Direction = Delta / Distance;
    FVector Step = Direction * WalkSpeed * DeltaTime;
    FVector NewLocation;
    if (Step.Size() >= Distance)
    {
        NewLocation = Target;
    }
    else
    {
        NewLocation = Current + Step;
    }

    Owner->SetActorLocation(NewLocation,
                            /*bSweep*/ false,
                            /*OutSweepHitResult*/ nullptr,
                            ETeleportType::None);

    if (bRotateToFace)
    {
        const FRotator LookAt =
            UKismetMathLibrary::FindLookAtRotation(Current, Target);
        const FRotator YawOnly(0.f, LookAt.Yaw, 0.f);
        Owner->SetActorRotation(YawOnly, ETeleportType::None);
    }
}
