# Custom UPCGSettings Node Cheatsheet

> 给 xiaohuan 写自定义 PCG 节点的标准模板。文件放 `Plugins/AdoreRobotPCG/Source/AdoreRobotPCG/Public|Private/`。

## 模块结构

```
Plugins/AdoreRobotPCG/
├── AdoreRobotPCG.uplugin
└── Source/AdoreRobotPCG/
    ├── AdoreRobotPCG.Build.cs
    ├── Public/
    │   └── PCGSettings_RoomGraphToWalls.h
    └── Private/
        ├── AdoreRobotPCGModule.cpp
        └── PCGSettings_RoomGraphToWalls.cpp
```

## Build.cs 模板

```csharp
using UnrealBuildTool;

public class AdoreRobotPCG : ModuleRules
{
    public AdoreRobotPCG(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(new string[]
        {
            "Core",
            "CoreUObject",
            "Engine",
            "PCG",
        });

        PrivateDependencyModuleNames.AddRange(new string[]
        {
            "PCGGeometryScriptInterop",
            "GeometryScriptingCore",
        });
    }
}
```

## .uplugin 模板

```json
{
  "FileVersion": 3,
  "Version": 1,
  "VersionName": "0.1",
  "FriendlyName": "AdoreRobot PCG",
  "Description": "Custom PCG nodes for adore_robot scene generation",
  "Category": "Procedural",
  "EnabledByDefault": true,
  "Modules": [{
    "Name": "AdoreRobotPCG",
    "Type": "Runtime",
    "LoadingPhase": "Default"
  }],
  "Plugins": [
    {"Name": "PCG", "Enabled": true},
    {"Name": "PCGGeometryScriptInterop", "Enabled": true}
  ]
}
```

## UPCGSettings 子类样板 (header)

```cpp
// PCGSettings_RoomGraphToWalls.h
#pragma once

#include "CoreMinimal.h"
#include "PCGSettings.h"
#include "PCGSettings_RoomGraphToWalls.generated.h"

UCLASS(BlueprintType, ClassGroup = (Procedural))
class ADOREROBOTPCG_API UPCGSettings_RoomGraphToWalls : public UPCGSettings
{
    GENERATED_BODY()

public:
    UPCGSettings_RoomGraphToWalls();

    // 节点 metadata
    virtual FName AdditionalTaskName() const override { return TEXT("RoomGraphToWalls"); }
#if WITH_EDITOR
    virtual FText GetDefaultNodeTitle() const override
    {
        return NSLOCTEXT("PCG", "RoomGraphToWalls", "Room Graph To Walls");
    }
    virtual EPCGSettingsType GetType() const override { return EPCGSettingsType::Generic; }
#endif

    // 节点参数 (UPROPERTY EditAnywhere 会在 PCG 节点 inspector 显示)
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Walls")
    float WallHeight = 280.0f;   // cm

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Walls")
    float WallThickness = 15.0f; // cm

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Walls")
    bool bGenerateDoorways = true;

protected:
    virtual TArray<FPCGPinProperties> InputPinProperties() const override;
    virtual TArray<FPCGPinProperties> OutputPinProperties() const override;
    virtual FPCGElementPtr CreateElement() const override;
};
```

## Element 实现 (cpp)

```cpp
// PCGSettings_RoomGraphToWalls.cpp
#include "PCGSettings_RoomGraphToWalls.h"
#include "PCGElement.h"
#include "PCGComponent.h"
#include "PCGContext.h"
#include "Data/PCGPointData.h"

namespace
{
    class FPCGElement_RoomGraphToWalls : public IPCGElement
    {
    protected:
        virtual bool ExecuteInternal(FPCGContext* Context) const override
        {
            const UPCGSettings_RoomGraphToWalls* Settings =
                Context->GetInputSettings<UPCGSettings_RoomGraphToWalls>();
            check(Settings);

            TArray<FPCGTaggedData> Inputs = Context->InputData.GetInputsByPin(TEXT("RoomGraph"));
            FPCGTaggedData& Output = Context->OutputData.TaggedData.Emplace_GetRef();

            UPCGPointData* WallPoints = NewObject<UPCGPointData>();
            // ... iterate room graph, emit wall points ...
            Output.Data = WallPoints;
            Output.Pin = TEXT("WallPoints");
            return true;
        }
    };
}

UPCGSettings_RoomGraphToWalls::UPCGSettings_RoomGraphToWalls() = default;

TArray<FPCGPinProperties> UPCGSettings_RoomGraphToWalls::InputPinProperties() const
{
    TArray<FPCGPinProperties> Pins;
    Pins.Emplace(TEXT("RoomGraph"), EPCGDataType::Param);
    return Pins;
}

TArray<FPCGPinProperties> UPCGSettings_RoomGraphToWalls::OutputPinProperties() const
{
    TArray<FPCGPinProperties> Pins;
    Pins.Emplace(TEXT("WallPoints"), EPCGDataType::Point);
    return Pins;
}

FPCGElementPtr UPCGSettings_RoomGraphToWalls::CreateElement() const
{
    return MakeShared<FPCGElement_RoomGraphToWalls>();
}
```

## Module 注册

```cpp
// AdoreRobotPCGModule.cpp
#include "Modules/ModuleManager.h"

class FAdoreRobotPCGModule : public IModuleInterface {};
IMPLEMENT_MODULE(FAdoreRobotPCGModule, AdoreRobotPCG)
```

## 验证

1. 重新 generate project files
2. VS 编译 `AdoreRobot` target
3. UE Editor 重启
4. PCG Graph 里右键 -> Add Node -> 应该看到 "Room Graph To Walls"
5. 接 input pin (param) 和 output pin (point)，调参数验证

## 常见坑

1. **节点不出现**：检查 `LoadingPhase=Default` 且 plugin enabled；看 OutputLog `LogPCG` 通道
2. **ExecuteInternal crash**：input pin 没接东西时 GetInputsByPin 返回空数组，记得判 `Num() > 0`
3. **多线程问题**：PCG 默认多线程跑 element，不要在 ExecuteInternal 里碰 UObject 创建以外的 game thread API；要回主线程用 `AsyncTask(ENamedThreads::GameThread, ...)`
4. **Hot reload 无效**：PCG 节点改了 header 必须重启 editor，不能 hot reload

## 外部 reference (按需 WebFetch)

- UE5 PCG API 文档: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Plugins/PCG/UPCGSettings
- Epic 官方 PCG Sample 源码 (有大量 UPCGSettings 子类参考): https://www.fab.com/listings/4a4f47b1-b8c8-4b21-9614-b8c33feb1adc
