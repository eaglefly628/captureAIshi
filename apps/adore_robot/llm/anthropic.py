"""Anthropic Claude client (Messages API native tool use)."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .base import BaseLLMClient, ChatResult, ToolCall, ToolSpec


class AnthropicClient(BaseLLMClient):
    provider = "anthropic"

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        base_url: str = "https://api.anthropic.com/v1",
        timeout: float = 30.0,
    ):
        self.model = os.environ.get("ANTHROPIC_MODEL", model)
        self.base_url = os.environ.get("ANTHROPIC_BASE_URL", base_url).rstrip("/")
        self.timeout = timeout
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")

    def chat_with_tools(
        self,
        system: str,
        user: str,
        tools: list[ToolSpec],
        force_tool: str | None = None,
        max_tokens: int = 1024,
    ) -> ChatResult:
        payload: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if tools:
            payload["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in tools
            ]
            if force_tool:
                payload["tool_choice"] = {"type": "tool", "name": force_tool}

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"Anthropic HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}"
            ) from e
        elapsed_ms = int((time.time() - t0) * 1000)

        tool_calls: list[ToolCall] = []
        text_parts: list[str] = []
        for block in data.get("content") or []:
            btype = block.get("type")
            if btype == "tool_use":
                args = block.get("input") or {}
                tool_calls.append(
                    ToolCall(
                        name=block.get("name") or "",
                        arguments=args,
                        rationale=args.get("rationale", "") if isinstance(args, dict) else "",
                    )
                )
            elif btype == "text":
                text_parts.append(block.get("text") or "")

        return ChatResult(
            provider=self.provider,
            model=self.model,
            tool_calls=tool_calls,
            text="\n".join(text_parts),
            elapsed_ms=elapsed_ms,
            raw=data,
        )
