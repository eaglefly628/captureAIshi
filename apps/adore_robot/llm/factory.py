"""Provider factory + auto-detection."""

from __future__ import annotations

import os
from typing import Literal

from .base import BaseLLMClient

Provider = Literal[
    "deepseek", "anthropic", "qwen", "glm", "kimi", "doubao", "keyword"
]


def detect_available_provider() -> Provider:
    if os.environ.get("DEEPSEEK_API_KEY"):
        return "deepseek"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("DASHSCOPE_API_KEY"):
        return "qwen"
    if os.environ.get("ZHIPUAI_API_KEY"):
        return "glm"
    if os.environ.get("MOONSHOT_API_KEY"):
        return "kimi"
    if os.environ.get("ARK_API_KEY"):
        return "doubao"
    return "keyword"


def make_llm_client(provider: Provider | None = None) -> BaseLLMClient:
    if provider is None:
        provider = detect_available_provider()

    if provider == "deepseek":
        from .deepseek import DeepSeekClient
        return DeepSeekClient()
    if provider == "anthropic":
        from .anthropic import AnthropicClient
        return AnthropicClient()
    if provider == "keyword":
        from .keyword import KeywordFallbackClient
        return KeywordFallbackClient()
    if provider in {"qwen", "glm", "kimi", "doubao"}:
        from .openai_compat import OpenAICompatClient
        return OpenAICompatClient(provider)

    raise ValueError(f"unknown provider: {provider}")
