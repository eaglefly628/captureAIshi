"""Anthropic adapter -- Claude 4.x via /v1/messages.

Prompt caching is on by default: system prompts and tools[] arrays get
cache_control=ephemeral, so repeated calls with the same schema hit the
cache. Per .claude/skills/claude-api: apps built against Anthropic should
include caching.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .base import BaseLLMClient, ChatResponse, Message, ToolCall, ToolDef


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicClient(BaseLLMClient):
    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-6",
        timeout: float = 60.0,
        cache_system: bool = True,
        cache_tools: bool = True,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.cache_system = cache_system
        self.cache_tools = cache_tools

    def chat_with_tools(
        self,
        messages: list[Message],
        tools: list[ToolDef] | None = None,
        tool_choice: str | dict | None = None,
        max_tokens: int = 1024,
        temperature: float | None = None,
        system: str | None = None,
    ) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": _to_anthropic_messages(messages),
        }
        if system:
            payload["system"] = _system_blocks(system, self.cache_system)
        if temperature is not None:
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = _tools_to_anthropic(tools, self.cache_tools)
            if tool_choice is not None:
                payload["tool_choice"] = _tool_choice_to_anthropic(tool_choice)
        return self._post_messages(payload)

    def _post_messages(self, payload: dict) -> ChatResponse:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            ANTHROPIC_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise RuntimeError(f"anthropic HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise ConnectionError(f"cannot reach {ANTHROPIC_URL}: {e.reason}") from e
        data = json.loads(raw)
        return _parse_anthropic_response(data)


def _system_blocks(system: str, cache: bool) -> list[dict]:
    block: dict = {"type": "text", "text": system}
    if cache:
        block["cache_control"] = {"type": "ephemeral"}
    return [block]


def _tools_to_anthropic(tools: list[ToolDef], cache: bool) -> list[dict]:
    out: list[dict] = []
    for i, t in enumerate(tools):
        entry: dict = {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        if cache and i == len(tools) - 1:
            entry["cache_control"] = {"type": "ephemeral"}
        out.append(entry)
    return out


def _tool_choice_to_anthropic(tc: str | dict) -> dict:
    if isinstance(tc, str):
        if tc == "auto":
            return {"type": "auto"}
        if tc == "required":
            return {"type": "any"}
        if tc == "none":
            return {"type": "none"}
        return {"type": "tool", "name": tc}
    if isinstance(tc, dict) and "name" in tc:
        return {"type": "tool", "name": tc["name"]}
    return tc


def _to_anthropic_messages(messages: list[Message]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        if m.role == "system":
            continue
        if m.role == "tool":
            out.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id or "",
                    "content": m.content if isinstance(m.content, str) else json.dumps(m.content),
                }],
            })
        else:
            out.append({"role": m.role, "content": m.content})
    return out


def _parse_anthropic_response(data: dict) -> ChatResponse:
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in data.get("content", []) or []:
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            tool_calls.append(ToolCall(
                id=block.get("id", ""),
                name=block.get("name", ""),
                arguments=block.get("input", {}) or {},
            ))
    return ChatResponse(
        text="".join(text_parts),
        tool_calls=tool_calls,
        finish_reason=data.get("stop_reason", "stop"),
        usage=data.get("usage", {}),
        raw=data,
    )
