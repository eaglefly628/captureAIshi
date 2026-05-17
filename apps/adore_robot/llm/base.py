"""Provider-neutral LLM client interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    rationale: str = ""


@dataclass
class ChatResult:
    provider: str
    model: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    text: str = ""
    elapsed_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class BaseLLMClient:
    provider: str = "base"
    model: str = ""

    def chat_with_tools(
        self,
        system: str,
        user: str,
        tools: list[ToolSpec],
        force_tool: str | None = None,
        max_tokens: int = 1024,
    ) -> ChatResult:
        raise NotImplementedError
