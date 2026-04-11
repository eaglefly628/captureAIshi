#pragma once
#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "BotDebugGameMode.generated.h"

UCLASS()
class STACKOBOT_API ABotDebugGameMode : public AGameModeBase
{
    GENERATED_BODY()
public:
    virtual void BeginPlay() override;
};
