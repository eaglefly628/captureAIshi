using UnrealBuildTool;

public class StackOBot : ModuleRules
{
    public StackOBot(ReadOnlyTargetRules Target) : base(Target)
    {
        // NoSharedPCHs avoids looking for CoreUObjectSharedPCH.h
        // which doesn't exist in UE 5.7 binary (non-source) installs.
        PCHUsage = PCHUsageMode.NoSharedPCHs;

        PublicDependencyModuleNames.AddRange(new string[] {
            "Core", "CoreUObject", "Engine"
        });
    }
}
