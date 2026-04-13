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

    UObject* O1 = World->GetOuter();
    UObject* O2 = O1 ? O1->GetOuter() : nullptr;

    // --- World / outer chain ---
    UE_LOG(LogTemp, Warning, TEXT("=== BotDebug BeginPlay ==="));
    UE_LOG(LogTemp, Warning, TEXT("UWorld   ptr=%p"), World);
    UE_LOG(LogTemp, Warning, TEXT("Outer1   ptr=%p  class=%s"),
        O1, O1 ? *O1->GetClass()->GetName() : TEXT("null"));
    UE_LOG(LogTemp, Warning, TEXT("Outer2   ptr=%p  (expect null)"), O2);
    UE_LOG(LogTemp, Warning, TEXT("GEngine  ptr=%p"), GEngine);

    // --- GUObjectArray (compare addr + num with bridge log) ---
    int32 WorldIdx  = GUObjectArray.ObjectToIndex(World);
    int32 EngineIdx = GEngine ? GUObjectArray.ObjectToIndex(GEngine) : -1;
    UE_LOG(LogTemp, Warning,
        TEXT("GUObjectArray  addr=%p  num=%d  ObjFirstGCIndex=%d"),
        &GUObjectArray,
        GUObjectArray.GetObjectArrayNum(),
        GUObjectArray.ObjFirstGCIndex);
    UE_LOG(LogTemp, Warning,
        TEXT("  World  InternalIndex=%d"), WorldIdx);
    UE_LOG(LogTemp, Warning,
        TEXT("  Engine InternalIndex=%d"), EngineIdx);

    // --- FUObjectItem raw layout (confirms stride for bridge detection) ---
    FUObjectItem* Item = GUObjectArray.IndexToObject(WorldIdx);
    if (Item)
    {
        const uint8* B = reinterpret_cast<const uint8*>(Item);
        UE_LOG(LogTemp, Warning,
            TEXT("FUObjectItem[%d]  addr=%p  sizeof=%d"),
            WorldIdx, Item, static_cast<int32>(sizeof(FUObjectItem)));
        UE_LOG(LogTemp, Warning,
            TEXT("  raw +0x00=%016llX  +0x08=%016llX  +0x10=%016llX"),
            *reinterpret_cast<const uint64*>(B + 0x00),
            *reinterpret_cast<const uint64*>(B + 0x08),
            *reinterpret_cast<const uint64*>(B + 0x10));
        UE_LOG(LogTemp, Warning,
            TEXT("  Item->Object=%p  (should == UWorld ptr)"), Item->Object);
    }

    // --- Chunk[0] base (bridge compares its Chunk[0] against this) ---
    FUObjectItem* Item0 = GUObjectArray.IndexToObject(0);
    UE_LOG(LogTemp, Warning, TEXT("Chunk[0] base  IndexToObject(0)=%p"), Item0);

    // --- UWorld class FName ComparisonIndex (what bridge searches in FNamePool) ---
    FName WorldClassName = World->GetClass()->GetFName();
    uint32 CmpIdx = WorldClassName.GetComparisonIndex().Value;
    UE_LOG(LogTemp, Warning,
        TEXT("UWorld class FName: '%s'  ComparisonIndex=0x%08X (block=%d word_off=%d)"),
        *WorldClassName.ToString(),
        CmpIdx,
        CmpIdx >> 16,
        CmpIdx & 0xFFFF);

    volatile int bp = 0; (void)bp;
}
