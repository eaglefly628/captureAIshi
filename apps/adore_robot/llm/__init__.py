"""LLM provider abstraction for adore_robot.

Default provider: deepseek (V3.2, OpenAI-compatible, ~10x cheaper than Claude
Sonnet 4.6 with stable tool calling). Switchable via env or factory arg to
anthropic / qwen / glm / kimi / doubao.

Usage:
    from llm import make_llm_client, Message, ToolDef
    client = make_llm_client("deepseek")  # or "anthropic", etc.
    resp = client.chat_with_tools(
        messages=[Message(role="user", content="set shelf density to 0.9")],
        tools=[ToolDef(name="set_shelf_density", description="...", input_schema={...})],
        system="You are a PCG parameter editor.",
    )
    for tc in resp.tool_calls:
        print(tc.name, tc.arguments)
"""

from .base import BaseLLMClient, ChatResponse, Message, ToolCall, ToolDef
from .factory import PROVIDERS, make_llm_client

__all__ = [
    "BaseLLMClient",
    "ChatResponse",
    "Message",
    "PROVIDERS",
    "ToolCall",
    "ToolDef",
    "make_llm_client",
]
