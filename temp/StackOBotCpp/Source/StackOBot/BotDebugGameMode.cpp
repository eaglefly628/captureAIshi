#include "BotDebugGameMode.h"
#include "UObject/UObjectArray.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "UObject/Package.h"

void ABotDebugGameMode::BeginPlay()
{
    Super::BeginPlay();

    UWorld* World = GetWorld();
    if (!World) return;

    int32 Idx    = World->GetUniqueID();
    UObject* O1  = World->GetOuter();
    UObject* O2  = O1 ? O1->GetOuter() : nullptr;
    UObject* O3  = O2 ? O2->GetOuter() : nullptr;

    UE_LOG(LogTemp, Warning, TEXT("=== BotDebug BeginPlay ==="));
    UE_LOG(LogTemp, Warning, TEXT("UWorld   ptr=%p  idx=%d"), World, Idx);
    UE_LOG(LogTemp, Warning, TEXT("Outer1   ptr=%p  class=%s"),
        O1, O1 ? *O1->GetClass()->GetName() : TEXT("null"));
    UE_LOG(LogTemp, Warning, TEXT("Outer2   ptr=%p  class=%s"),
        O2, O2 ? *O2->GetClass()->GetName() : TEXT("null"));
    UE_LOG(LogTemp, Warning, TEXT("Outer3   ptr=%p  class=%s"),
        O3, O3 ? *O3->GetClass()->GetName() : TEXT("null"));
    UE_LOG(LogTemp, Warning, TEXT("GEngine  ptr=%p"), GEngine);
    UE_LOG(LogTemp, Warning, TEXT("GUObjectArray num=%d"),
        GUObjectArray.GetObjectArrayNum());

    // VS breakpoint target -- watch: World, O1, O2, GEngine, &GUObjectArray
    volatile int bp = 0; (void)bp;
}
