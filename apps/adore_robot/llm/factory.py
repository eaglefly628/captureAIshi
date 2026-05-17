"""Provider factory.

Defaults match v0.3.3 direction-B decision (老白 2026-05-16):
- Text reasoning / NL->tool: deepseek (V3.2, OpenAI-compatible).
- Multimodal (thumbnail feedback loop, v0.4): qwen-vl-max via qwen kind.
- Premium fallback: anthropic (claude-sonnet-4-6).

Pick provider via env ADORE_LLM_PROVIDER, or pass `provider=` explicitly.
API key resolution: explicit arg > env var named in PROVIDERS[p]["env"].
"""

from __future__ import annotations

import os
from typing import Any

from .anthropic_adapter import AnthropicClient
from .base import BaseLLMClient
from .keyword import KeywordFallbackClient
from .openai_compat import OpenAICompatClient


PROVIDERS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "kind": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "env": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "kind": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3-max",
        "env": "DASHSCOPE_API_KEY",
    },
    "qwen-vl": {
        "kind": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-vl-max",
        "env": "DASHSCOPE_API_KEY",
    },
    "glm": {
        "kind": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-plus",
        "env": "ZHIPUAI_API_KEY",
    },
    "kimi": {
        "kind": "openai",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-32k",
        "env": "MOONSHOT_API_KEY",
    },
    "doubao": {
        "kind": "openai",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-pro-32k",
        "env": "ARK_API_KEY",
    },
    "anthropic": {
        "kind": "anthropic",
        "model": "claude-sonnet-4-6",
        "env": "ANTHROPIC_API_KEY",
    },
    "keyword": {
        "kind": "keyword",
        "model": "offline-heuristic-v1",
        "env": None,
    },
}


def auto_detect_provider() -> str:
    """Pick first provider whose API key is present, else 'keyword' fallback."""
    for name in ("deepseek", "qwen", "glm", "kimi", "doubao", "anthropic"):
        env = PROVIDERS[name].get("env")
        if env and os.environ.get(env):
            return name
    return "keyword"


def make_llm_client(
    provider: str | None = None,
    *,
    model: str | None = None,
    api_key: str | None = None,
    timeout: float = 60.0,
) -> BaseLLMClient:
    provider = provider or os.environ.get("ADORE_LLM_PROVIDER") or auto_detect_provider()
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; available: {sorted(PROVIDERS)}")
    cfg = PROVIDERS[provider]
    if cfg["kind"] == "keyword":
        return KeywordFallbackClient()
    api_key = api_key or os.environ.get(cfg["env"])
    if not api_key:
        raise RuntimeError(f"missing API key: set env {cfg['env']} or pass api_key=")
    chosen_model = model or cfg["model"]
    if cfg["kind"] == "openai":
        return OpenAICompatClient(
            base_url=cfg["base_url"],
            api_key=api_key,
            model=chosen_model,
            timeout=timeout,
        )
    if cfg["kind"] == "anthropic":
        return AnthropicClient(
            api_key=api_key,
            model=chosen_model,
            timeout=timeout,
        )
    raise RuntimeError(f"provider {provider!r} has unsupported kind {cfg['kind']!r}")
