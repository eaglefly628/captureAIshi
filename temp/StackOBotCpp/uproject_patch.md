# StackOBot .uproject patch

在 StackOBot.uproject 里加一个 "Modules" 数组（FileVersion/EngineAssociation 保持原值不动）：

```json
{
    "FileVersion": 3,
    "EngineAssociation": "5.7",
    ...原有字段...,
    "Modules": [
        {
            "Name": "StackOBot",
            "Type": "Runtime",
            "LoadingPhase": "Default"
        }
    ]
}
```

然后右键 .uproject -> Generate Visual Studio project files
编译 Development Editor 配置
Project Settings -> Maps & Modes -> Default GameMode -> BotDebugGameMode
