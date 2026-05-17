"""OpenAI-compatible adapter -- shared by DeepSeek / Qwen / GLM / Kimi / Doubao.

All these vendors expose POST {base_url}/chat/completions with the OpenAI
function-calling schema (tools[].function.{name,description,parameters} +
tool_choice). We hit it with stdlib urllib -- no openai SDK dependency.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .base import BaseLLMClient, ChatResponse, Message, ToolCall, ToolDef


class OpenAICompatClient(BaseLLMClient):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

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
            "messages": _to_openai_messages(messages, system),
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = [_tool_to_openai(t) for t in tools]
            if tool_choice is not None:
                payload["tool_choice"] = _tool_choice_to_openai(tool_choice)
        return self._post_chat(payload)

    def _post_chat(self, payload: dict) -> ChatResponse:
        url = f"{self.base_url}/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise RuntimeError(f"{self.model} HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise ConnectionError(f"cannot reach {url}: {e.reason}") from e
        data = json.loads(raw)
        return _parse_openai_response(data)


def _to_openai_messages(messages: list[Message], system: str | None) -> list[dict]:
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        if m.role == "tool":
            out.append({
                "role": "tool",
                "tool_call_id": m.tool_call_id or "",
                "content": m.content if isinstance(m.content, str) else json.dumps(m.content),
            })
        elif m.role == "assistant" and isinstance(m.content, list):
            text_parts: list[str] = []
            tool_calls: list[dict] = []
            for block in m.content:
                if block.get("type") == "tool_use":
                    tool_calls.append({
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    })
                elif block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            entry: dict = {"role": "assistant", "content": "".join(text_parts) or None}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            out.append(entry)
        else:
            out.append({"role": m.role, "content": m.content})
    return out


def _tool_to_openai(t: ToolDef) -> dict:
    return {
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description,
            "parameters": t.input_schema,
        },
    }


def _tool_choice_to_openai(tc: str | dict) -> Any:
    if isinstance(tc, str):
        if tc in ("auto", "required", "none"):
            return tc
        return {"type": "function", "function": {"name": tc}}
    if isinstance(tc, dict) and "name" in tc:
        return {"type": "function", "function": {"name": tc["name"]}}
    return tc


def _parse_openai_response(data: dict) -> ChatResponse:
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message", {})
    text = msg.get("content") or ""
    tool_calls: list[ToolCall] = []
    for tc in msg.get("tool_calls", []) or []:
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {"_raw": fn.get("arguments")}
        tool_calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args))
    return ChatResponse(
        text=text,
        tool_calls=tool_calls,
        finish_reason=choice.get("finish_reason", "stop"),
        usage=data.get("usage", {}),
        raw=data,
    )
