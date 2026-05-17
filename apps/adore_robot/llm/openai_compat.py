"""OpenAI-compatible client stub for Qwen / GLM / Kimi / Doubao.

Each provider exposes an OpenAI-format /chat/completions endpoint with
its own base URL + API key env var. Full implementation lands when
xiaoxu picks one for testing; demo stays on DeepSeek + Anthropic.
"""

from __future__ import annotations

import os
from typing import Literal

from .base import BaseLLMClient, ChatResult, ToolSpec

PROVIDER_CONFIG = {
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "key_env": "DASHSCOPE_API_KEY",
        "default_model": "qwen-max",
    },
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "key_env": "ZHIPUAI_API_KEY",
        "default_model": "glm-4-plus",
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "key_env": "MOONSHOT_API_KEY",
        "default_model": "moonshot-v1-32k",
    },
    "doubao": {
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "key_env": "ARK_API_KEY",
        "default_model": "doubao-pro-32k",
    },
}


class OpenAICompatClient(BaseLLMClient):
    def __init__(self, provider: Literal["qwen", "glm", "kimi", "doubao"]):
        cfg = PROVIDER_CONFIG[provider]
        self.provider = provider
        self.base_url = os.environ.get(f"{provider.upper()}_BASE_URL", cfg["base_url"])
        self.model = os.environ.get(f"{provider.upper()}_MODEL", cfg["default_model"])
        self.api_key = os.environ.get(cfg["key_env"], "")
        if not self.api_key:
            raise RuntimeError(f"{cfg['key_env']} not set")

    def chat_with_tools(
        self,
        system: str,
        user: str,
        tools: list[ToolSpec],
        force_tool: str | None = None,
        max_tokens: int = 1024,
    ) -> ChatResult:
        from .deepseek import DeepSeekClient
        proxy = DeepSeekClient.__new__(DeepSeekClient)
        proxy.api_key = self.api_key
        proxy.base_url = self.base_url
        proxy.model = self.model
        proxy.timeout = 30.0
        proxy.provider = self.provider
        return DeepSeekClient.chat_with_tools(
            proxy, system=system, user=user, tools=tools,
            force_tool=force_tool, max_tokens=max_tokens,
        )
