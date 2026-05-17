"""DeepSeek-V3.2 client (OpenAI-compatible chat/completions).

API: https://api.deepseek.com/v1/chat/completions
Auth: Bearer ${DEEPSEEK_API_KEY}
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .base import BaseLLMClient, ChatResult, ToolCall, ToolSpec


class DeepSeekClient(BaseLLMClient):
    provider = "deepseek"

    def __init__(
        self,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com/v1",
        timeout: float = 30.0,
    ):
        self.model = os.environ.get("DEEPSEEK_MODEL", model)
        self.base_url = os.environ.get("DEEPSEEK_BASE_URL", base_url).rstrip("/")
        self.timeout = timeout
        self.api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY not set")

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
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in tools
            ]
            if force_tool:
                payload["tool_choice"] = {
                    "type": "function",
                    "function": {"name": force_tool},
                }

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"DeepSeek HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}"
            ) from e
        elapsed_ms = int((time.time() - t0) * 1000)

        tool_calls: list[ToolCall] = []
        text = ""
        choices = data.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            text = msg.get("content") or ""
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {"_raw": raw_args}
                tool_calls.append(
                    ToolCall(
                        name=fn.get("name") or "",
                        arguments=args,
                        rationale=args.get("rationale", "") if isinstance(args, dict) else "",
                    )
                )

        return ChatResult(
            provider=self.provider,
            model=self.model,
            tool_calls=tool_calls,
            text=text,
            elapsed_ms=elapsed_ms,
            raw=data,
        )
