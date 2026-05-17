"""Provider-agnostic dataclasses + ABC.

Schema notes:
- `Message.content` is str for plain text turns, or list[dict] for
  multi-block (tool_use / tool_result) turns. Providers normalize on send.
- `ToolDef.input_schema` is a strict JSON Schema; same shape works for
  Anthropic tools[] and OpenAI tools[].function.parameters.
- `ChatResponse.tool_calls` is empty when the model only returned text.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict]
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class ToolDef:
    name: str
    description: str
    input_schema: dict


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ChatResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict = field(default_factory=dict)
    raw: Any = None


class BaseLLMClient(ABC):
    @abstractmethod
    def chat_with_tools(
        self,
        messages: list[Message],
        tools: list[ToolDef] | None = None,
        tool_choice: str | dict | None = None,
        max_tokens: int = 1024,
        temperature: float | None = None,
        system: str | None = None,
    ) -> ChatResponse:
        """Single-turn chat. tool_choice: None | "auto" | "required" | {"name": str}."""
        ...
