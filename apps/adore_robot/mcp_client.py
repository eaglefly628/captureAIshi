"""Minimal synchronous MCP client for UE5.8 Unreal MCP server.

Talks JSON-RPC 2.0 over HTTP to http://127.0.0.1:8000/mcp by default.
Auto-initializes on first call, auto-re-initializes on session expiry.

UE5.8 enable plugins (Edit -> Plugins): AI Assistant, Toolset Registry,
Unreal MCP, All Toolsets. Run in editor console: `ModelContextProtocol.StartServer`
or check `bAutoStartServer` in Editor Preferences -> Model Context Protocol.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any


class UnrealMCPClient:
    PROTOCOL_VERSION = "2025-11-25"

    def __init__(self, url: str = "http://127.0.0.1:8000/mcp", timeout: float = 30.0):
        self.url = url
        self.timeout = timeout
        self._session_id: str | None = None
        self._next_id = 1
        self._lock = threading.Lock()

    def _post(self, payload: dict, extra_headers: dict | None = None) -> tuple[int, dict, dict]:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status = resp.status
                resp_headers = dict(resp.headers)
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), {"error": {"message": e.read().decode("utf-8", "replace")}}
        except urllib.error.URLError as e:
            raise ConnectionError(f"cannot reach MCP server at {self.url}: {e.reason}") from e
        if not raw.strip():
            return status, resp_headers, {}
        try:
            return status, resp_headers, json.loads(raw)
        except json.JSONDecodeError:
            return status, resp_headers, {"raw": raw}

    def _rpc(self, method: str, params: dict | None = None, _retry: bool = True) -> dict:
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        status, headers, data = self._post(payload)
        if status == 404 and self._session_id and _retry:
            self._session_id = None
            self.initialize()
            return self._rpc(method, params, _retry=False)
        if status >= 400:
            raise RuntimeError(f"MCP error {status}: {data}")
        if isinstance(data, dict) and "error" in data and data["error"]:
            raise RuntimeError(f"JSON-RPC error: {data['error']}")
        return data.get("result", data) if isinstance(data, dict) else {}

    def initialize(self) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": self.PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "adore_robot-flask", "version": "0.3.3"},
            },
        }
        status, headers, data = self._post(payload)
        if status >= 400:
            raise RuntimeError(f"MCP initialize failed {status}: {data}")
        self._session_id = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
        notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        self._post(notif)
        return data.get("result", {}) if isinstance(data, dict) else {}

    def ensure_session(self) -> None:
        if not self._session_id:
            self.initialize()

    def ping(self) -> dict:
        self.ensure_session()
        return self._rpc("ping")

    def list_tools(self) -> list[dict]:
        self.ensure_session()
        result = self._rpc("tools/list")
        return result.get("tools", []) if isinstance(result, dict) else []

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        self.ensure_session()
        return self._rpc("tools/call", {"name": name, "arguments": arguments or {}})

    @property
    def session_id(self) -> str | None:
        return self._session_id
