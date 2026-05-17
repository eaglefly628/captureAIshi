"""LLM provider abstraction for adore_robot.

老白 v0.3.3 派单 #10: make_llm_client(provider) -> BaseClient unified
chat_with_tools interface. Default DeepSeek-V3.2 (OpenAI compat, ~10x
cheaper than Sonnet 4.6). Fallback to keyword matcher when no API key.
"""

from .base import BaseLLMClient, ToolCall, ToolSpec
from .factory import make_llm_client, detect_available_provider

__all__ = [
    "BaseLLMClient",
    "ToolCall",
    "ToolSpec",
    "make_llm_client",
    "detect_available_provider",
]
