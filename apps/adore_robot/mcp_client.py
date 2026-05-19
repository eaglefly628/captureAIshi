"""Minimal synchronous MCP client for UE5.8 Unreal MCP server.

Talks JSON-RPC 2.0 over HTTP to http://127.0.0.1:8000/mcp by default.
Auto-initializes on first call, auto-re-initializes on session expiry.

UE5.8 enable plugins (Edit -> Plugins): AI Assistant, Toolset Registry,
Unreal MCP, All Toolsets. Run in editor console: `ModelContextProtocol.StartServer`
or check `bAutoStartServer` in Editor Preferences -> Model Context Protocol.

PCG flow (proven 2026-05-17, see docs/ue58_mcp_validation_log.md):
  client.auto_load_toolsets()        # one-time per session
  pcg_ref = client.find_pcg_component_refpath()
  client.set_actor_properties(pcg_ref, {"seed": 12345, "shelf_density": 0.9})
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any


DEFAULT_TOOLSETS = [
    "ToolsetRegistry.EditorAppToolset",
    "toolset_registry.toolsets.core.object.ObjectTools",
    "toolset_registry.toolsets.core.scene.SceneTools",
    "toolset_registry.toolsets.core.programmatic.ProgrammaticToolset",
]


class UnrealMCPClient:
    PROTOCOL_VERSION = "2025-11-25"

    def __init__(self, url: str = "http://127.0.0.1:8000/mcp", timeout: float = 30.0):
        self.url = url
        self.timeout = timeout
        self._session_id: str | None = None
        self._next_id = 1
        self._lock = threading.Lock()
        self._loaded_toolsets: set[str] = set()

    def _post(self, payload: dict, extra_headers: dict | None = None) -> tuple[int, dict, str]:
        body = json.dumps(payload).encode("utf-8")
        # NOTE: do NOT send `Connection: close` here -- forcing the UE 5.8
        # MCP server to close the TCP socket mid-load_toolset triggered
        # wil::ResultException rethrows in the AI plugin (user crashed UE
        # 2026-05-17). Accept that each tool call takes ~15s due to the
        # server's keep-alive timeout instead. auto_load_toolsets adds a
        # 0.5s gap between loads to give the Python sandbox time to digest.
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
            return e.code, dict(e.headers), e.read().decode("utf-8", "replace")
        except urllib.error.URLError as e:
            raise ConnectionError(f"cannot reach MCP server at {self.url}: {e.reason}") from e
        return status, resp_headers, raw

    @staticmethod
    def _parse_sse_or_json(raw: str) -> dict:
        """Server may return either plain JSON or SSE event stream
        (`event: message\\ndata: {...}\\n\\n`). Extract the last data: line."""
        if not raw.strip():
            return {}
        # SSE form: scan for `data: {...}`
        if raw.startswith("event:") or "\ndata:" in raw or raw.startswith("data:"):
            last = None
            for line in raw.splitlines():
                if line.startswith("data:"):
                    last = line[5:].strip()
            if last:
                try:
                    return json.loads(last)
                except json.JSONDecodeError:
                    return {"raw": last}
            return {"raw": raw}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}

    def _rpc(self, method: str, params: dict | None = None, _retry: bool = True) -> dict:
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        status, headers, raw = self._post(payload)
        data = self._parse_sse_or_json(raw)
        if status == 404 and self._session_id and _retry:
            self._session_id = None
            self._loaded_toolsets.clear()
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
        status, headers, raw = self._post(payload)
        if status >= 400:
            raise RuntimeError(f"MCP initialize failed {status}: {raw[:400]}")
        self._session_id = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
        data = self._parse_sse_or_json(raw)
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

    @staticmethod
    def _unwrap(result: Any) -> Any:
        """Tool call results wrap as {content:[{type:'text', text:'<JSON>'}]}.
        Unwrap to get the actual payload. ObjectTools.list_properties /
        get_properties double-wrap (text is JSON of {returnValue:'<JSON>'}),
        so we parse the inner returnValue string too when it's a string."""
        if not isinstance(result, dict):
            return result
        content = result.get("content")
        if not isinstance(content, list) or not content:
            return result
        first = content[0]
        if not isinstance(first, dict):
            return result
        text = first.get("text")
        if not isinstance(text, str):
            return result
        try:
            outer = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(outer, dict) and "returnValue" in outer:
            inner = outer["returnValue"]
            if isinstance(inner, str):
                try:
                    return json.loads(inner)
                except json.JSONDecodeError:
                    return inner
            return inner
        return outer

    def call_tool_unwrapped(self, name: str, arguments: dict | None = None) -> Any:
        return self._unwrap(self.call_tool(name, arguments))

    def auto_load_toolsets(self, names: list[str] | None = None,
                           gap_seconds: float = 0.5) -> dict:
        """Load default 4 core toolsets if not already loaded this session.
        Idempotent -- skips ones in _loaded_toolsets cache. Adds a small
        gap between loads to give UE 5.8's Python sandbox loader time to
        digest (rapid back-to-back loads were observed to stress the
        ModelContextProtocol plugin)."""
        self.ensure_session()
        names = names or DEFAULT_TOOLSETS
        loaded = []
        skipped = []
        failed = []
        first = True
        for n in names:
            if n in self._loaded_toolsets:
                skipped.append(n)
                continue
            if not first and gap_seconds > 0:
                time.sleep(gap_seconds)
            first = False
            try:
                self.call_tool("load_toolset", {"toolset_name": n})
                self._loaded_toolsets.add(n)
                loaded.append(n)
            except Exception as e:
                failed.append({"toolset": n, "error": f"{type(e).__name__}: {e}"})
        return {"loaded": loaded, "skipped": skipped, "failed": failed,
                "total_loaded": len(self._loaded_toolsets)}

    # ─── EditorApp convenience ────────────────────────────────────────────
    def get_selected_actors(self) -> list[dict]:
        result = self.call_tool_unwrapped(
            "ToolsetRegistry.EditorAppToolset.GetSelectedActors"
        )
        if isinstance(result, list):
            return result
        return result.get("actors", []) if isinstance(result, dict) else []

    def get_current_level(self) -> str:
        result = self.call_tool_unwrapped(
            "toolset_registry.toolsets.core.scene.SceneTools.get_current_level"
        )
        if isinstance(result, str):
            return result
        return result.get("level", "") if isinstance(result, dict) else ""

    # ─── ObjectTools wrappers ─────────────────────────────────────────────
    def list_actor_properties(self, refpath: str) -> Any:
        return self.call_tool_unwrapped(
            "toolset_registry.toolsets.core.object.ObjectTools.list_properties",
            {"instance": {"refPath": refpath}},
        )

    def get_actor_properties(self, refpath: str, props: list[str]) -> dict:
        result = self.call_tool_unwrapped(
            "toolset_registry.toolsets.core.object.ObjectTools.get_properties",
            {"instance": {"refPath": refpath}, "properties": props},
        )
        return result if isinstance(result, dict) else {}

    def set_actor_properties(self, refpath: str, values: dict) -> Any:
        """Sets one or more UPROPERTY values via reflection. Returns the
        result (typically `True` or a status object)."""
        return self.call_tool_unwrapped(
            "toolset_registry.toolsets.core.object.ObjectTools.set_properties",
            {"instance": {"refPath": refpath}, "values": json.dumps(values)},
        )

    # ─── PCG helpers (built on top of ObjectTools) ────────────────────────
    def find_pcg_component_refpath(self) -> str:
        """Best-effort locate the PCG Component refPath:
        1. If the user has selected one or more actors in the level editor,
           prefer the first one whose path contains 'PCG'.
        2. Otherwise fall back to ProgrammaticToolset Python find that
           enumerates the entire level for any PCG*Volume / PCG*Actor.
        Raises if none found; caller renders a helpful error message."""
        selected = self.get_selected_actors()
        candidates: list[str] = []
        if isinstance(selected, list):
            for actor in selected:
                ref = actor.get("refPath") if isinstance(actor, dict) else None
                if ref and "PCG" in ref:
                    candidates.append(ref)
        if not candidates:
            try:
                script = (
                    "import unreal\n"
                    "subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)\n"
                    "actors = subsys.get_all_level_actors() if subsys else []\n"
                    "out = []\n"
                    "for a in actors:\n"
                    "    if not a: continue\n"
                    "    cls = a.get_class().get_path_name() if a.get_class() else ''\n"
                    "    if 'PCG' in cls:\n"
                    "        out.append(a.get_path_name())\n"
                    "return out\n"
                )
                result = self.call_tool_unwrapped(
                    "toolset_registry.toolsets.core.programmatic.ProgrammaticToolset.execute_tool_script",
                    {"script": script},
                )
                if isinstance(result, list):
                    candidates = [r for r in result if isinstance(r, str) and "PCG" in r]
                elif isinstance(result, str) and "PCG" in result:
                    candidates = [result]
            except Exception:
                pass
        if not candidates:
            raise RuntimeError(
                "no PCG actor found in current level -- "
                "drop a PCG Volume into the level (or select an existing one) and retry"
            )
        actor_ref = candidates[0]
        props = self.get_actor_properties(actor_ref, ["pCGComponent"])
        pcg_field = props.get("pCGComponent") if isinstance(props, dict) else None
        pcg_ref = pcg_field.get("refPath") if isinstance(pcg_field, dict) else None
        if not pcg_ref:
            raise RuntimeError(
                f"actor {actor_ref!r} has no pCGComponent sub-object; "
                "this may not be a PCG Volume actor"
            )
        return pcg_ref

    def trigger_pcg_generate(self, pcg_component_refpath: str, force: bool = True) -> Any:
        """Call PCGComponent.Generate(force) via ProgrammaticToolset Python
        sandbox (UPCGComponent.Generate is a UFUNCTION exposed in Python).
        Required after set_properties for the graph to re-sim with new params."""
        script = (
            "import unreal\n"
            "ref = " + json.dumps(pcg_component_refpath) + "\n"
            "comp = unreal.load_object(None, ref)\n"
            "if comp is None:\n"
            "    return {'ok': False, 'reason': 'load_object returned None for ' + ref}\n"
            "force = " + ("True" if force else "False") + "\n"
            "comp.generate_local(force)\n"
            "return {'ok': True, 'component': ref, 'force': force}\n"
        )
        return self.call_tool_unwrapped(
            "toolset_registry.toolsets.core.programmatic.ProgrammaticToolset.execute_tool_script",
            {"script": script},
        )

    def apply_pcg_delta(self, params: dict, regenerate: bool = True) -> dict:
        """One-call orchestration: ensure toolsets loaded, find PCG
        Component, set the provided pcg_params delta, optionally trigger
        a regen so the graph re-sims with the new values. Returns a dict
        describing what happened so the caller can render it in chat."""
        self.auto_load_toolsets()
        pcg_ref = self.find_pcg_component_refpath()
        write_result = self.set_actor_properties(pcg_ref, params)
        generate_result = None
        if regenerate:
            try:
                generate_result = self.trigger_pcg_generate(pcg_ref, force=True)
            except Exception as e:
                generate_result = {"ok": False, "reason": f"{type(e).__name__}: {e}"}
        return {
            "ok": True,
            "pcg_component": pcg_ref,
            "applied": params,
            "raw_result": write_result,
            "regenerated": generate_result,
        }

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def loaded_toolsets(self) -> list[str]:
        return sorted(self._loaded_toolsets)
