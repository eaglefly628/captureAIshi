"""adore_robot.pcg — App-side procedural content generation.

这是 UE PCG 框架在我们 app 端的等价物。chat → DeepSeek tool_call →
本模块 → 输出 SpawnRequest 列表 → xiaoxu runner 通过 MCP SceneTools
spawn 到 UE 场景。

跟 UE PCG 的关系:
- UE PCG: graph 编辑器 + 节点 + ISM 优化, foundry 长期路线
- 本模块: Python 算法, 灵活直接, demo + v1+ 主力实现

不是替代 UE PCG, 是降低门槛 + 控制全栈 + 调试简单。foundry 规模化时
(500+ instance) 才考虑 PCG ISM。

模块结构:
- base: SpawnRequest / LayoutResult / PCGContext (共享数据类型)
- warehouse / living_room / industrial_corner: 3 场景 layout 算法
- primitives: 复用算法 (grid / scatter / jitter / cluster / 等)
- lighting: lighting_preset enum → light actor 配置

参数 contract: apps/adore_robot/docs/pcg_param_contract.md §1
xiaoxu 后端集成: apps/adore_robot/demo/runner.py 调本模块
"""

from .base import SpawnRequest, LayoutResult, PCGContext
from .warehouse import generate_warehouse
from .living_room import generate_living_room
from .industrial_corner import generate_industrial_corner

__all__ = [
    "SpawnRequest",
    "LayoutResult",
    "PCGContext",
    "generate_warehouse",
    "generate_living_room",
    "generate_industrial_corner",
]
