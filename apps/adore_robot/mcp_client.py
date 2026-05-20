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

import http.client
import json
import threading
import time
import urllib.parse
from typing import Any


DEFAULT_TOOLSETS = [
    "ToolsetRegistry.EditorAppToolset",
    "toolset_registry.toolsets.core.object.ObjectTools",
    "toolset_registry.toolsets.core.scene.SceneTools",
    "toolset_registry.toolsets.core.programmatic.ProgrammaticToolset",
]


class UnrealMCPClient:
    PROTOCOL_VERSION = "2025-11-25"

    def __init__(self, url: str = "http://127.0.0.1:8000/mcp", timeout: float = 30.0,
                 verbose: bool = False):
        self.url = url
        parsed = urllib.parse.urlparse(url)
        self._host = parsed.hostname or "127.0.0.1"
        self._port = parsed.port or 80
        self._path = parsed.path or "/mcp"
        self.timeout = timeout
        self._session_id: str | None = None
        self._next_id = 1
        self._lock = threading.Lock()
        self._loaded_toolsets: set[str] = set()
        # Persistent http.client.HTTPConnection -- reused across all POSTs so
        # the underlying TCP socket survives across RPCs. urllib opens a new
        # socket per request, which UE 5.8 Preview's ModelContextProtocol
        # HttpServer hates (HttpConnection state machine asserts on rapid
        # new connections). curl works because it reuses connections;
        # http.client.HTTPConnection matches that behaviour.
        self._conn: http.client.HTTPConnection | None = None
        self.verbose = verbose

    def _ensure_conn(self) -> http.client.HTTPConnection:
        if self._conn is None:
            self._conn = http.client.HTTPConnection(
                self._host, self._port, timeout=self.timeout
            )
        return self._conn

    def _close_conn(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _post(self, payload: dict, extra_headers: dict | None = None) -> tuple[int, dict, str]:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Content-Length": str(len(body)),
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        if extra_headers:
            headers.update(extra_headers)

        def _do() -> tuple[int, dict, str]:
            conn = self._ensure_conn()
            conn.request("POST", self._path, body=body, headers=headers)
            resp = conn.getresponse()
            status = resp.status
            resp_headers = {k: v for k, v in resp.getheaders()}
            ctype = (resp_headers.get("Content-Type")
                     or resp_headers.get("content-type") or "")
            if "event-stream" in ctype.lower():
                # UE 5.8 returns SSE without closing the connection -- a
                # plain resp.read() would block until the server's idle
                # timeout (~15s) even though the event arrived in <1ms.
                # Read line-by-line, return as soon as we see a complete
                # event (data: ... \n\n).
                lines: list[str] = []
                seen_data = False
                while True:
                    line_b = resp.readline()
                    if not line_b:
                        break  # EOF
                    line = line_b.decode("utf-8", "replace")
                    lines.append(line)
                    stripped = line.rstrip("\r\n")
                    if stripped.startswith("data:"):
                        seen_data = True
                    elif stripped == "" and seen_data:
                        break
                raw = "".join(lines)
            else:
                raw = resp.read().decode("utf-8", "replace")
            return status, resp_headers, raw

        try:
            return _do()
        except TimeoutError as e:
            # UE Game Thread Spike held the connection too long. Distinct
            # from disconnect -- log as WARN, caller may retry.
            self._close_conn()
            raise TimeoutError(
                f"MCP server timed out after {self.timeout}s -- UE Game Thread "
                f"likely Spiked on a heavy tool call (load_toolset / Generate). "
                f"Either bump UnrealMCPClient(timeout=...) or retry."
            ) from e
        except (http.client.BadStatusLine,
                http.client.RemoteDisconnected,
                http.client.HTTPException,
                ConnectionResetError,
                BrokenPipeError) as e:
            # Server closed the socket between RPCs (e.g. keep-alive
            # timeout). Reopen and retry once.
            self._close_conn()
            try:
                return _do()
            except (http.client.HTTPException, OSError) as e2:
                self._close_conn()
                raise ConnectionError(
                    f"cannot reach MCP server at {self.url}: {e2} -- "
                    f"server may have crashed (check UE for assertion log)"
                ) from e2
        except OSError as e:
            self._close_conn()
            raise ConnectionError(
                f"cannot reach MCP server at {self.url}: {e} -- "
                f"server may have crashed or not started"
            ) from e

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
        t0 = time.time()
        status, headers, raw = self._post(payload)
        data = self._parse_sse_or_json(raw)
        if self.verbose:
            label = method
            if method == "tools/call" and isinstance(params, dict):
                label += f"({params.get('name','?')})"
                if params.get("name") == "load_toolset":
                    args = params.get("arguments") or {}
                    label += f"[{args.get('toolset_name','?')}]"
            elapsed_ms = int((time.time() - t0) * 1000)
            print(f"  [mcp] {label:60s} {elapsed_ms:>6d}ms  status={status}",
                  flush=True)
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
        t0 = time.time()
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
        # IMPORTANT: do NOT send `notifications/initialized` here.
        # MCP 2025-11-25 spec says client SHOULD send it post-initialize,
        # but UE 5.8 Preview ModelContextProtocol plugin's HttpConnection
        # state machine asserts (HttpConnection.cpp:184
        # EHttpConnectionState::AwaitingProcessing) when a notification
        # POST arrives back-to-back with subsequent tool calls -- crashes
        # UE. Skip it. The tools/call methods work without the explicit
        # initialized notification on this server.
        # Brief settle so UE finishes post-init bookkeeping before our
        # first real RPC. 0.2s is plenty in practice (was 0.8 originally,
        # over-conservative).
        time.sleep(0.2)
        if self.verbose:
            print(f"  [mcp] initialize{'':50s} {int((time.time()-t0)*1000):>6d}ms  "
                  f"(incl 200ms settle)", flush=True)
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
                           gap_seconds: float = 0.1,
                           progress_cb=None) -> dict:
        """Load default 4 core toolsets if not already loaded this session.

        Workarounds for UE 5.8 Preview ModelContextProtocol plugin bugs:
        - Prime the HTTP connection state machine with a `tools/list` call
          BEFORE the first `load_toolset`. Without this, calling load_toolset
          as the first tool dispatch on a fresh session triggers an engine
          assertion (HttpConnection.cpp:184) and crashes UE. User's earlier
          manual curl tests survived because they ran tools/list first.
        - Small gap (default 0.5s) between successive load_toolset calls.
        """
        names = names or DEFAULT_TOOLSETS
        total = 1 + len(names)  # prime + N loads
        def _emit(phase: str, idx: int, name: str, status: str) -> None:
            if progress_cb is None:
                return
            try:
                progress_cb({"phase": phase, "current": idx, "total": total,
                             "toolset": name, "status": status})
            except Exception:
                pass

        self.ensure_session()
        _emit("prime", 0, "tools/list", "running")
        try:
            self._rpc("tools/list")
            _emit("prime", 1, "tools/list", "done")
        except Exception as e:
            _emit("prime", 1, "tools/list", f"warn: {e}")

        loaded = []
        skipped = []
        failed = []
        first = True
        for i, n in enumerate(names):
            step_idx = 1 + i  # 1-based after prime
            if n in self._loaded_toolsets:
                skipped.append(n)
                _emit("skipped", step_idx + 1, n, "done")
                continue
            if not first and gap_seconds > 0:
                time.sleep(gap_seconds)
            first = False
            _emit("loading", step_idx, n, "running")
            try:
                self.call_tool("load_toolset", {"toolset_name": n})
                self._loaded_toolsets.add(n)
                loaded.append(n)
                _emit("loading", step_idx + 1, n, "done")
            except Exception as e:
                failed.append({"toolset": n, "error": f"{type(e).__name__}: {e}"})
                _emit("loading", step_idx + 1, n, f"error: {e}")
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

    # ─── Demo v0 actor primitives (native MCP, NO execute_tool_script) ──
    # UE 5.8 ProgrammaticToolset Python sandbox refuses `import unreal`
    # (allowlist = {math, json, copy, re, datetime}). All demo actor ops
    # therefore go through SceneTools native RPCs, which call into the
    # editor on the game thread directly.

    DEMO_FOLDER = "Demo/v0"

    # Per-level actor ledger.  Shape: { level_path: { handle: record } }
    # so RobotDemo1 and RobotDemo2 never see each other's actors.
    # Persisted to apps/adore_robot/.demo_ledger.json across Flask restarts.
    _DEMO_LEDGER: dict = {}
    _LEDGER_FILE = "apps/adore_robot/.demo_ledger.json"
    _level_cache: str = ""
    _level_cache_ts: float = 0.0

    @classmethod
    def _ledger_load(cls):
        import json as _j, os as _os
        try:
            if _os.path.exists(cls._LEDGER_FILE):
                with open(cls._LEDGER_FILE, "r", encoding="utf-8") as f:
                    data = _j.load(f)
                # back-compat: older ledger was flat {handle: record}.
                # Wrap it under a "_legacy" level so we don't lose history.
                if data and not any(isinstance(v, dict) and
                                    any(isinstance(vv, dict) and "actor_handle" in vv
                                        for vv in v.values())
                                    for v in data.values()):
                    cls._DEMO_LEDGER = {"_legacy": data}
                else:
                    cls._DEMO_LEDGER = data
        except Exception:
            cls._DEMO_LEDGER = {}

    @classmethod
    def _ledger_save(cls):
        import json as _j
        try:
            with open(cls._LEDGER_FILE, "w", encoding="utf-8") as f:
                _j.dump(cls._DEMO_LEDGER, f, ensure_ascii=False, indent=0)
        except Exception:
            pass

    def _current_level_cached(self) -> str:
        """get_current_level with a 2s cache to avoid one RPC per spawn."""
        now = time.time()
        if now - self._level_cache_ts < 2.0 and self._level_cache:
            return self._level_cache
        try:
            lvl = self.get_current_level() or "_unknown"
        except Exception:
            lvl = self._level_cache or "_unknown"
        self._level_cache = lvl
        self._level_cache_ts = now
        return lvl

    def _ledger_bucket(self) -> dict:
        """Return (and create if absent) the per-level bucket."""
        lvl = self._current_level_cached()
        if lvl not in self._DEMO_LEDGER:
            self._DEMO_LEDGER[lvl] = {}
        return self._DEMO_LEDGER[lvl]

    def _demo_origin_world_cm(self) -> dict:
        """Return BP_DemoOrigin world location in cm, or origin if absent."""
        if getattr(self, "_demo_origin_cache", None):
            return self._demo_origin_cache
        try:
            anchors = self.call_tool_unwrapped(
                "toolset_registry.toolsets.core.scene.SceneTools.find_actors",
                {"glob": "*DemoOrigin*"},
            )
            if isinstance(anchors, dict):
                anchors = anchors.get("actors") or anchors.get("results") or []
            if isinstance(anchors, list) and anchors:
                first = anchors[0]
                ref = first.get("refPath") if isinstance(first, dict) else first
                if ref:
                    props = self.get_actor_properties(ref, ["root_component"])
                    rc = props.get("root_component") if isinstance(props, dict) else None
                    if isinstance(rc, dict):
                        loc = (
                            rc.get("relative_location")
                            or rc.get("relativeLocation")
                            or rc.get("location")
                            or {}
                        )
                        if isinstance(loc, dict) and "x" in loc:
                            self._demo_origin_cache = {
                                "x": float(loc.get("x", 0)),
                                "y": float(loc.get("y", 0)),
                                "z": float(loc.get("z", 0)),
                            }
                            return self._demo_origin_cache
        except Exception:
            pass
        self._demo_origin_cache = {"x": 0.0, "y": 0.0, "z": 0.0}
        return self._demo_origin_cache

    @staticmethod
    def _xform(loc_cm: dict, yaw_deg: float = 0.0) -> dict:
        return {
            "location": {"x": loc_cm["x"], "y": loc_cm["y"], "z": loc_cm["z"]},
            "rotation": {"pitch": 0.0, "yaw": float(yaw_deg), "roll": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
        }

    def demo_spawn(self, asset_path: str, asset_name: str,
                   x_m: float, y_m: float, z_m: float = 0.0,
                   yaw_deg: float = 0.0) -> dict:
        """Spawn a static mesh at scene-local (x,y,z) meters. Tags via
        outliner folder Demo/v0 for safe bulk-delete later."""
        self.auto_load_toolsets()
        anchor = self._demo_origin_world_cm()
        world = {
            "x": anchor["x"] + x_m * 100,
            "y": anchor["y"] + y_m * 100,
            "z": anchor["z"] + z_m * 100,
        }
        # Unique-ish name so the outliner doesn't auto-rename and lose us.
        suffix = int(time.time() * 1000) & 0xFFFF
        actor_name = f"Demo_{asset_name}_{suffix}"
        spawned = self.call_tool_unwrapped(
            "toolset_registry.toolsets.core.scene.SceneTools.add_to_scene_from_asset",
            {
                "asset_path": asset_path,
                "name": actor_name,
                "xform": self._xform(world, yaw_deg),
            },
        )
        actor_ref = None
        if isinstance(spawned, str):
            actor_ref = spawned
        elif isinstance(spawned, dict):
            actor_ref = spawned.get("refPath") or spawned.get("actor")
        # Move into demo folder + write asset_name as an actor tag so
        # the actor is self-identifying when we re-load a saved level
        # without the in-memory ledger. Best-effort; ignore individual
        # failures.
        if actor_ref:
            try:
                self.call_tool_unwrapped(
                    "toolset_registry.toolsets.core.scene.SceneTools.set_actor_folder",
                    {"actor": actor_ref, "folder_path": self.DEMO_FOLDER},
                )
            except Exception:
                pass
            try:
                self.set_actor_properties(actor_ref, {"tags": [
                    "demo_v0_spawned",
                    f"demo_v0_asset:{asset_name}",
                    f"demo_v0_handle:{actor_name}",
                ]})
            except Exception:
                pass
        record = {
            "actor_handle": actor_name,
            "actor_ref": actor_ref,
            "asset_name": asset_name,
            "x": x_m, "y": y_m, "z": z_m, "yaw_deg": yaw_deg,
        }
        bucket = self._ledger_bucket()
        bucket[actor_name] = record
        if actor_ref:
            bucket[actor_ref] = record  # alt lookup
        self._ledger_save()
        return record

    def _list_demo_folder(self) -> list:
        """get_actors_in_folder, but treat 'folder does not exist' as
        empty so list/clear/delete don't error before the first spawn."""
        try:
            actors = self.call_tool_unwrapped(
                "toolset_registry.toolsets.core.scene.SceneTools.get_actors_in_folder",
                {"folder_path": self.DEMO_FOLDER, "recursive": False},
            )
        except Exception as e:
            if "does not exist" in str(e).lower() or "Folder does not exist" in str(e):
                return []
            raise
        if isinstance(actors, dict):
            actors = actors.get("actors") or actors.get("results") or []
        return actors if isinstance(actors, list) else []

    def _find_demo_actor(self, handle: str) -> str | None:
        actors = self._list_demo_folder()
        for a in actors:
            ref = a.get("refPath") if isinstance(a, dict) else a
            if not ref:
                continue
            name = ref.rsplit(".", 1)[-1]
            if name == handle or handle in name:
                return ref
        return None

    def demo_delete(self, handle: str) -> dict:
        self.auto_load_toolsets()
        bucket = self._ledger_bucket()
        rec = bucket.get(handle)
        ref = (rec or {}).get("actor_ref") or self._find_demo_actor(handle)
        if not ref:
            return {"error": f"no demo actor matching '{handle}'"}
        ok = self.call_tool_unwrapped(
            "toolset_registry.toolsets.core.scene.SceneTools.remove_from_scene",
            {"actor": ref},
        )
        for k in [handle, ref] + ([rec.get("actor_handle")] if rec else []):
            if k:
                bucket.pop(k, None)
        self._ledger_save()
        return {"deleted": handle, "actor_ref": ref, "ok": bool(ok)}

    def demo_move(self, handle: str, x_m: float, y_m: float, z_m: float = 0.0) -> dict:
        """Move via delete + respawn at new (x,y,z) keeping asset + yaw.
        ObjectTools.set_properties can't reach AStaticMeshActor's transform
        via root_component, so we fake it by re-spawning. New actor gets a
        new handle; we update the ledger so the LLM's next reference works."""
        self.auto_load_toolsets()
        bucket = self._ledger_bucket()
        rec = bucket.get(handle)
        if not rec:
            ref = self._find_demo_actor(handle)
            if not ref:
                return {"error": f"no demo actor matching '{handle}'"}
            rec = {"actor_ref": ref, "asset_name": "unknown", "yaw_deg": 0.0}
        # delete old
        try:
            self.call_tool_unwrapped(
                "toolset_registry.toolsets.core.scene.SceneTools.remove_from_scene",
                {"actor": rec["actor_ref"]},
            )
        except Exception:
            pass
        bucket.pop(handle, None)
        if rec.get("actor_ref"):
            bucket.pop(rec["actor_ref"], None)
        # respawn at new location
        from demo.asset_registry import resolve as _resolve  # late import: avoid cycle
        try:
            asset_path = _resolve(rec.get("asset_name", "shelf"))
        except Exception:
            asset_path = _resolve("shelf")  # fallback
        new_rec = self.demo_spawn(
            asset_path=asset_path,
            asset_name=rec.get("asset_name", "shelf"),
            x_m=x_m, y_m=y_m, z_m=z_m,
            yaw_deg=rec.get("yaw_deg", 0.0),
        )
        return {
            "actor_handle": new_rec["actor_handle"],
            "old_handle": handle,
            "new_xyz_m": [x_m, y_m, z_m],
            "actor_ref": new_rec["actor_ref"],
        }

    def demo_list(self) -> dict:
        """Return ledger entries that still correspond to a live actor in
        the Demo/v0 folder. Source of truth = our spawn ledger; we
        intersect with the live folder so deletes outside the LLM (manual
        Editor cleanup, level reload) don't leave stale handles."""
        self.auto_load_toolsets()
        live_refs = set()
        for a in self._list_demo_folder():
            ref = a.get("refPath") if isinstance(a, dict) else a
            if ref:
                live_refs.add(ref)
        bucket = self._ledger_bucket()
        out = []
        seen_handles = set()
        for k, rec in list(bucket.items()):
            h = rec.get("actor_handle")
            if not h or h in seen_handles:
                continue
            seen_handles.add(h)
            if live_refs and rec.get("actor_ref") and rec["actor_ref"] not in live_refs:
                # ledger entry stale -- actor gone from level
                bucket.pop(k, None)
                continue
            out.append({
                "actor_handle": h,
                "asset_name": rec.get("asset_name", "unknown"),
                "x": rec.get("x", 0),
                "y": rec.get("y", 0),
                "z": rec.get("z", 0),
                "yaw_deg": rec.get("yaw_deg", 0),
            })
        return {"objects": out}

    def demo_clear(self) -> dict:
        self.auto_load_toolsets()
        cleared = 0
        # iterate the folder live (covers actors spawned outside ledger too)
        for a in self._list_demo_folder():
            ref = a.get("refPath") if isinstance(a, dict) else a
            if not ref:
                continue
            try:
                self.call_tool_unwrapped(
                    "toolset_registry.toolsets.core.scene.SceneTools.remove_from_scene",
                    {"actor": ref},
                )
                cleared += 1
            except Exception:
                pass
        self._ledger_bucket().clear()
        self._ledger_save()
        return {"cleared": cleared}

    def demo_switch_level(self, level_path: str) -> dict:
        """Load a different .umap in the editor. Invalidates the level
        cache so the next demo_* call buckets into the new level."""
        self.auto_load_toolsets()
        # normalize: accept "RobotDemo1" -> "/Game/RobotDemo1"
        if level_path and not level_path.startswith("/"):
            level_path = "/Game/" + level_path
        try:
            self.call_tool_unwrapped(
                "toolset_registry.toolsets.core.scene.SceneTools.load_level",
                {"level_path": level_path},
            )
        except Exception as e:
            return {"error": f"load_level failed: {type(e).__name__}: {e}",
                    "level_path": level_path}
        self._level_cache = ""
        self._level_cache_ts = 0.0
        new = self._current_level_cached()
        return {"ok": True, "level_path": new}

    def demo_generate_warehouse(self, asset_resolver, **p) -> dict:
        """Server-side warehouse layout algorithm. asset_resolver(name)
        maps demo asset_name -> UE asset path. Calls demo_spawn many
        times; returns aggregate dict."""
        import random as _rand
        if p.get("clear_first", True):
            self.demo_clear()
        rng = _rand.Random(int(p.get("seed", 0)))
        shelves_per_row = int(p.get("shelves_per_row", 6))
        shelf_rows = int(p.get("shelf_rows", 3))
        aisle_w = float(p.get("aisle_width_m", 3.0))
        SHELF_W, SHELF_D = 1.6, 1.2
        row_pitch = SHELF_D + aisle_w
        total_span = shelf_rows * SHELF_D + (shelf_rows - 1) * aisle_w
        y_start = -total_span / 2 + SHELF_D / 2
        row_x_extent = (shelves_per_row - 1) * SHELF_W
        x_start = -row_x_extent / 2
        room_w = float(p.get("room_w_m", 30))
        room_l = float(p.get("room_l_m", 40))
        aisle_y = []
        spawned = []

        def _spawn(asset_name, x, y, yaw=0.0):
            res = self.demo_spawn(asset_resolver(asset_name), asset_name, x, y, 0, yaw)
            spawned.append({"actor_handle": res["actor_handle"],
                            "asset_name": asset_name, "x": x, "y": y})

        for r in range(shelf_rows):
            y = y_start + r * row_pitch
            for s in range(shelves_per_row):
                _spawn("shelf", x_start + s * SHELF_W, y)
            if r < shelf_rows - 1:
                aisle_y.append(y + SHELF_D / 2 + aisle_w / 2)
        for i in range(int(p.get("forklift_count", 1))):
            ay = (rng.choice(aisle_y) if aisle_y
                  else (y_start - row_pitch / 2 if i % 2 == 0 else y_start + total_span))
            ax = rng.uniform(x_start, x_start + row_x_extent)
            _spawn("forklift", ax, ay, rng.choice([0, 90, 180, 270]))
        for _ in range(int(p.get("pallet_count", 10))):
            _spawn("pallet",
                   rng.uniform(x_start - 0.5, x_start + row_x_extent + 0.5),
                   rng.uniform(-total_span / 2 - 1, total_span / 2 + 1),
                   rng.choice([0, 90]))
        for _ in range(int(p.get("box_count", 5))):
            _spawn("box",
                   rng.uniform(-room_w / 2 + 1, room_w / 2 - 1),
                   rng.uniform(-room_l / 2 + 1, room_l / 2 - 1),
                   rng.uniform(0, 360))
        for _ in range(int(p.get("drum_count", 3))):
            _spawn("drum",
                   rng.choice([-room_w / 2 + 1, room_w / 2 - 1]),
                   rng.uniform(-room_l / 2 + 1, room_l / 2 - 1))
        for _ in range(int(p.get("worker_count", 0))):
            _spawn("worker",
                   rng.uniform(-room_w / 2 + 2, room_w / 2 - 2),
                   rng.uniform(-room_l / 2 + 2, room_l / 2 - 2),
                   rng.uniform(0, 360))
        by_asset: dict = {}
        for s in spawned:
            by_asset[s["asset_name"]] = by_asset.get(s["asset_name"], 0) + 1
        return {"spawned": spawned, "total": len(spawned), "by_asset": by_asset}

    def capture_editor_image(self) -> bytes | None:
        """Snap the active UE Editor viewport via EditorAppToolset. Returns
        raw PNG bytes; powers the "real UE PIP" so the customer sees the
        SVG schematic AND the actual engine output side by side."""
        self.auto_load_toolsets()
        try:
            result = self.call_tool_unwrapped(
                "ToolsetRegistry.EditorAppToolset.CaptureEditorImage"
            )
        except Exception:
            return None
        import base64 as _b64
        if isinstance(result, str):
            try:
                return _b64.b64decode(result)
            except Exception:
                return None
        if isinstance(result, dict):
            for k in ("image", "data", "png", "base64"):
                v = result.get(k)
                if isinstance(v, str):
                    try:
                        return _b64.b64decode(v)
                    except Exception:
                        pass
            for k in ("path", "file", "filepath", "image_path"):
                p = result.get(k)
                if isinstance(p, str):
                    try:
                        with open(p, "rb") as f:
                            return f.read()
                    except Exception:
                        pass
        return None

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


# Load persistent ledger at import time so the very first /api/demo/list
# after Flask restart already has handle -> asset_name mapping ready.
UnrealMCPClient._ledger_load()
