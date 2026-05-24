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
from pathlib import Path as _Path
from typing import Any


DEFAULT_TOOLSETS = [
    "ToolsetRegistry.EditorAppToolset",
    "toolset_registry.toolsets.core.object.ObjectTools",
    "toolset_registry.toolsets.core.scene.SceneTools",
    "toolset_registry.toolsets.core.programmatic.ProgrammaticToolset",
    # v0.4.3 census (xiaohuan 2026-05-22): Epic ships 41 toolsets total
    # in UE 5.8 Preview; only ~4 were auto-loaded. Adding ActorTools
    # unlocks SetActorLocation/Rotation/Scale (the standard AActor API)
    # so demo_move + patrol can stop using delete+respawn (no more
    # flicker). AssetTools + StaticMeshTools provide bounds metadata
    # for footprint-accurate overlap detection. SlateInspectorToolset
    # is the Playwright-style UI driver -- PIE control via UI when
    # Epic still has no native PIE toolset.
    "toolset_registry.toolsets.core.actor.ActorTools",
    "toolset_registry.toolsets.core.asset.AssetTools",
    "toolset_registry.toolsets.core.static_mesh.StaticMeshTools",
    "SlateInspectorToolset.SlateInspectorToolset",
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
            except (OSError, http.client.HTTPException) as e:
                # Already-broken socket on close is normal; broader
                # exceptions get logged so a real leak isn't masked.
                pass
            except Exception as e:
                print(f"[mcp] unexpected exception on _close_conn: "
                      f"{type(e).__name__}: {e}", flush=True)
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
    # Absolute path so Flask cwd doesn't matter for ledger persistence.
    _LEDGER_FILE = str(_Path(__file__).resolve().parent / ".demo_ledger.json")
    _level_cache: str = ""
    _level_cache_ts: float = 0.0

    def _next_id_for(self, bucket: dict, asset_name: str) -> int:
        """Per-asset auto-increment ID. Scans current bucket so we don't
        collide if the user reloaded a level with existing demo actors."""
        used = set()
        for rec in bucket.values():
            if rec.get("asset_name") == asset_name:
                idn = rec.get("id_number")
                if isinstance(idn, int):
                    used.add(idn)
        i = 1
        while i in used:
            i += 1
        return i

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
        """get_current_level with a 2s cache to avoid one RPC per spawn.
        On RPC failure we keep the last-known value as a soft fallback
        but reset the timestamp so the very next call retries instead
        of trusting a stale value for the rest of the 2s window."""
        now = time.time()
        if now - self._level_cache_ts < 2.0 and self._level_cache:
            return self._level_cache
        try:
            lvl = self.get_current_level() or "_unknown"
            self._level_cache = lvl
            self._level_cache_ts = now
            return lvl
        except Exception:
            self._level_cache_ts = 0.0  # force retry next call
            return self._level_cache or "_unknown"

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
                   yaw_deg: float = 0.0,
                   id_number_override: int | None = None,
                   anchor_override_cm: dict | None = None) -> dict:
        """Spawn a static mesh at scene-local (x,y,z) meters. Tags via
        outliner folder Demo/v0 for safe bulk-delete later.

        id_number_override: when set (e.g. by demo_move's respawn path),
        keeps the previous handle's number so the user's "F1" doesn't
        become "F2" after a move.

        anchor_override_cm: {x, y, z} in cm. When given, used as the
        world anchor INSTEAD of BP_DemoOrigin -- typically the PCGVolume
        center XY + volume-bottom Z so a spawn at (0,0,0) lands on the
        floor inside the volume. Falls back to BP_DemoOrigin when None.
        """
        self.auto_load_toolsets()
        anchor = anchor_override_cm if anchor_override_cm else self._demo_origin_world_cm()
        world = {
            "x": anchor["x"] + x_m * 100,
            "y": anchor["y"] + y_m * 100,
            "z": anchor["z"] + z_m * 100,
        }
        # Customer-friendly auto-increment per asset type: forklift_1,
        # forklift_2, shelf_1 ... User can say "挪开 2 号叉车" and LLM
        # maps it through list_objects -> handle "forklift_2".
        bucket_for_id = self._ledger_bucket()
        id_number = (id_number_override if id_number_override is not None
                     else self._next_id_for(bucket_for_id, asset_name))
        actor_name = f"{asset_name}_{id_number}"
        spawned = self.call_tool_unwrapped(
            "toolset_registry.toolsets.core.scene.SceneTools.add_to_scene_from_asset",
            {
                "asset_path": asset_path,
                "name": actor_name,
                "xform": self._xform(world, yaw_deg),
            },
        )
        # ── Stage A: extract actor_ref from the spawn return value ──
        # add_to_scene_from_asset's return shape varies between asset
        # types (PackedLevelActor nests it under .actor, StaticMeshActor
        # returns a bare refPath, sometimes wrapped in {refPath:}). Walk
        # all known shapes; fall through to a glob-by-name lookup when
        # nothing parses.
        actor_ref = self._extract_actor_ref(spawned)
        if not actor_ref:
            actor_ref = self._find_by_actor_name(actor_name)

        # ── Stage B: apply markers (folder + tags) with verify + retry ──
        # PackedLevelActor and LevelInstance subclasses frequently refuse
        # set_actor_folder / set_actor_properties on the first attempt
        # because the actor is still streaming (LogStreaming shows
        # 'flushing async loading' right after add_to_scene). Retrying
        # after a short wait lets the actor finish init and accept the
        # write. We verify each marker stuck after every attempt so a
        # silent-success-but-no-effect failure mode (UE5.8 MCP returns
        # ok=true even when reflection drops the write) gets caught.
        marker_result = {"folder_ok": False, "tag_ok": False,
                          "tries": 0, "errors": []}
        if actor_ref:
            marker_result = self._apply_markers_with_retry(
                actor_ref=actor_ref,
                asset_name=asset_name,
                actor_name=actor_name,
                x_m=x_m, y_m=y_m, z_m=z_m, yaw_deg=yaw_deg,
            )
            if not (marker_result["folder_ok"] and marker_result["tag_ok"]):
                # Loud warn so we see broken markers immediately instead
                # of discovering them on the next demo_clear orphan.
                print(f"[demo_spawn] WARN marker incomplete for "
                      f"{actor_name}: folder_ok={marker_result['folder_ok']} "
                      f"tag_ok={marker_result['tag_ok']} "
                      f"errors={marker_result['errors']}", flush=True)

        record = {
            "actor_handle": actor_name,
            "actor_ref": actor_ref,
            "asset_name": asset_name,
            "id_number": id_number,
            "x": x_m, "y": y_m, "z": z_m, "yaw_deg": yaw_deg,
            "marker_result": marker_result,
        }
        bucket = self._ledger_bucket()
        bucket[actor_name] = record
        if actor_ref:
            bucket[actor_ref] = record  # alt lookup
        self._ledger_save()
        return record

    # ── Helpers for demo_spawn ────────────────────────────────────────

    @staticmethod
    def _extract_actor_ref(spawned) -> str | None:
        """Walk every known shape add_to_scene_from_asset returns and
        pick out the actor refPath. Returns None if no string ref is
        recoverable; caller can fall back to glob-by-name.
        """
        if isinstance(spawned, str):
            return spawned
        if not isinstance(spawned, dict):
            return None
        r = spawned.get("refPath")
        if isinstance(r, str):
            return r
        actor = spawned.get("actor")
        if isinstance(actor, str):
            return actor
        if isinstance(actor, dict):
            r = actor.get("refPath")
            if isinstance(r, str):
                return r
        # Last shape: MCP envelope {"result": {actor: {refPath}}, ...}
        result = spawned.get("result")
        if isinstance(result, dict):
            return UnrealMCPClient._extract_actor_ref(result)
        return None

    def _find_by_actor_name(self, actor_name: str) -> str | None:
        """Resolve an actor we just spawned by the unique name we gave
        it. Used as a fallback when the spawn RPC return shape didn't
        carry a parseable refPath."""
        try:
            res = self.call_tool_unwrapped(
                "toolset_registry.toolsets.core.scene.SceneTools.find_actors",
                {"glob": actor_name},
            )
            if isinstance(res, dict):
                res = res.get("actors") or res.get("results") or []
            if isinstance(res, list) and res:
                first = res[0]
                ref = first.get("refPath") if isinstance(first, dict) else first
                if isinstance(ref, str):
                    return ref
        except Exception:
            pass
        return None

    def _apply_markers_with_retry(self, actor_ref: str, asset_name: str,
                                   actor_name: str, x_m: float, y_m: float,
                                   z_m: float, yaw_deg: float,
                                   deadline_s: float = 5.0) -> dict:
        """Set Demo/v0 folder + tags on actor; verify both stuck; retry
        on failure. Returns a result dict the caller logs/inspects.

        The verify step is the critical part: UE5.8 MCP set_properties
        returns ok=true even when reflection silently drops the write
        on async-streaming or read-only-during-init actors (typical for
        PackedLevelActor). Reading back the tags + checking the folder's
        actor list is the only way to know we actually marked the actor.
        """
        import time
        desired_tags = [
            "demo_v0_spawned",
            f"demo_v0_asset:{asset_name}",
            f"demo_v0_handle:{actor_name}",
            f"demo_v0_pos:{x_m:.3f},{y_m:.3f},{z_m:.3f}",
            f"demo_v0_yaw:{yaw_deg:.2f}",
        ]
        out: dict = {"folder_ok": False, "tag_ok": False,
                     "tries": 0, "errors": []}

        deadline = time.time() + deadline_s
        wait_s = 0.1   # initial backoff; doubles each round, capped 0.6s

        while time.time() < deadline:
            out["tries"] += 1
            attempt = out["tries"]

            # ── Folder: set then verify ─────────────────────────────────
            if not out["folder_ok"]:
                try:
                    self.call_tool_unwrapped(
                        "toolset_registry.toolsets.core.scene.SceneTools.set_actor_folder",
                        {"actor": actor_ref, "folder_path": self.DEMO_FOLDER},
                    )
                except Exception as e:
                    out["errors"].append(f"set_folder t{attempt}: {type(e).__name__}: {e}")
                try:
                    folder_actors = self.call_tool_unwrapped(
                        "toolset_registry.toolsets.core.scene.SceneTools.get_actors_in_folder",
                        {"folder_path": self.DEMO_FOLDER, "recursive": False},
                    )
                    if isinstance(folder_actors, dict):
                        folder_actors = (folder_actors.get("actors")
                                          or folder_actors.get("results") or [])
                    if isinstance(folder_actors, list):
                        refs_in_folder = [
                            a.get("refPath") if isinstance(a, dict) else a
                            for a in folder_actors
                        ]
                        if actor_ref in refs_in_folder:
                            out["folder_ok"] = True
                except Exception as e:
                    out["errors"].append(f"verify_folder t{attempt}: {type(e).__name__}: {e}")

            # ── Tag: set then verify ────────────────────────────────────
            if not out["tag_ok"]:
                try:
                    self.set_actor_properties(actor_ref, {"tags": desired_tags})
                except Exception as e:
                    out["errors"].append(f"set_tags t{attempt}: {type(e).__name__}: {e}")
                try:
                    chk = self.get_actor_properties(actor_ref, ["tags"])
                    tags = chk.get("tags") if isinstance(chk, dict) else None
                    if isinstance(tags, list) and "demo_v0_spawned" in [str(t) for t in tags]:
                        out["tag_ok"] = True
                except Exception as e:
                    out["errors"].append(f"verify_tags t{attempt}: {type(e).__name__}: {e}")

            if out["folder_ok"] and out["tag_ok"]:
                return out
            time.sleep(wait_s)
            wait_s = min(wait_s * 1.5, 0.6)

        return out

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

    def demo_move(self, handle: str, x_m: float, y_m: float, z_m: float = 0.0,
                  anchor_override_cm: dict | None = None) -> dict:
        """Move via delete + respawn at new (x,y,z) keeping asset + yaw.
        ObjectTools.set_properties can't reach AStaticMeshActor's transform
        via root_component, so we fake it by re-spawning. New actor gets a
        new handle; we update the ledger so the LLM's next reference works.

        anchor_override_cm: passed straight through to demo_spawn so the
        respawned actor anchors against the same frame the original used
        (typically PCGVolume center) rather than slipping back to
        BP_DemoOrigin.
        """
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
        # Preserve the old id_number so 'F1' stays 'F1' after a move
        # (was reassigning to the next free integer -> UX confusion).
        new_rec = self.demo_spawn(
            asset_path=asset_path,
            asset_name=rec.get("asset_name", "shelf"),
            x_m=x_m, y_m=y_m, z_m=z_m,
            id_number_override=rec.get("id_number"),
            yaw_deg=rec.get("yaw_deg", 0.0),
            anchor_override_cm=anchor_override_cm,
        )
        return {
            "actor_handle": new_rec["actor_handle"],
            "old_handle": handle,
            "new_xyz_m": [x_m, y_m, z_m],
            "actor_ref": new_rec["actor_ref"],
            "asset_name": new_rec.get("asset_name"),
            "id_number": new_rec.get("id_number"),
            "yaw_deg": new_rec.get("yaw_deg"),
        }

    def set_worker_path(self, handle: str,
                        waypoints_world_cm: list[tuple[float, float, float]],
                        walk_speed_cms: float = 200.0,
                        loop: bool = True) -> dict:
        """Write a path into Robot13_Blueprint's Waypoints array + flip
        IsWalking = true. Requires the BP-side variables documented in
        docs/robot13_path_follower_bp.md (Waypoints / WalkSpeed /
        LoopPath / IsWalking / CurrentIndex, all Instance Editable).

        Returns {ok, actor_ref, n_waypoints, error?}.
        """
        self.auto_load_toolsets()
        bucket = self._ledger_bucket()
        rec = bucket.get(handle)
        ref = rec.get("actor_ref") if rec else None
        if not ref:
            ref = self._find_demo_actor(handle)
            if not ref:
                return {"ok": False, "error": f"no actor matching '{handle}'"}

        # Reset IsWalking first so a half-written Waypoints array doesn't
        # cause a Tick to read uninitialised data.
        try:
            self.set_actor_properties(ref, {"IsWalking": False})
        except Exception:
            pass

        wps = [{"x": float(p[0]), "y": float(p[1]),
                "z": float(p[2]) if len(p) > 2 else 0.0}
               for p in waypoints_world_cm]
        try:
            # Write both with-b and without-b bool keys so this works
            # regardless of whether UE5.8 MCP strips the 'b' UPROPERTY
            # prefix or keeps it. Set the path first; flip IsWalking
            # last so the Tick never sees a half-written Waypoints array.
            self.set_actor_properties(ref, {
                "Waypoints": wps,
                "WalkSpeed": float(walk_speed_cms),
                "LoopPath": bool(loop),
                "bLoopPath": bool(loop),
                "CurrentIndex": 0,
            })
            self.set_actor_properties(ref, {
                "IsWalking": True,
                "bIsWalking": True,
            })
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}",
                    "actor_ref": ref}
        return {"ok": True, "actor_ref": ref,
                "n_waypoints": len(wps), "walk_speed_cms": walk_speed_cms,
                "loop": loop}

    def demo_list(self) -> dict:
        """Return every actor currently in the Demo/v0 folder, augmented
        with whatever metadata we can find. Two sources, tried in order:

          1. In-memory ledger keyed by actor_ref (fast, has exact spawn
             coords + id_number).
          2. The actor's own `tags` UPROPERTY (slow but survives Flask
             restart, level reload, and ledger deletion -- we wrote
             demo_v0_asset:<name> + demo_v0_handle:<name> at spawn time).

        Position falls back to (0,0) when no ledger entry exists; if the
        user reloaded a saved .umap the visual stays at origin but the
        handle + asset + id are still recoverable so the LLM can still
        delete / move them by name."""
        self.auto_load_toolsets()
        live_refs = []
        for a in self._list_demo_folder():
            ref = a.get("refPath") if isinstance(a, dict) else a
            if ref:
                live_refs.append(ref)
        bucket = self._ledger_bucket()
        # Index ledger entries by actor_ref so we can join with live list.
        by_ref: dict = {}
        for k, rec in list(bucket.items()):
            r = rec.get("actor_ref")
            if r:
                by_ref[r] = rec

        out = []
        seen_handles = set()
        for ref in live_refs:
            rec = by_ref.get(ref)
            handle = rec.get("actor_handle") if rec else None
            asset = rec.get("asset_name") if rec else None
            id_n = rec.get("id_number") if rec else None
            x = rec.get("x") if rec else None
            y = rec.get("y") if rec else None
            z = rec.get("z") if rec else None
            yaw = rec.get("yaw_deg") if rec else None
            # Fallback: read tags directly from the actor.  Tags carry
            # asset/handle/pos/yaw so we can render this actor even when
            # the in-memory ledger has no entry for it.
            if handle is None or asset is None or x is None or y is None:
                try:
                    props = self.get_actor_properties(ref, ["tags"])
                    tags = props.get("tags", []) if isinstance(props, dict) else []
                    for t in tags:
                        s = str(t)
                        if s.startswith("demo_v0_asset:") and asset is None:
                            asset = s.split(":", 1)[1]
                        elif s.startswith("demo_v0_handle:") and handle is None:
                            handle = s.split(":", 1)[1]
                        elif s.startswith("demo_v0_pos:") and (x is None or y is None):
                            try:
                                parts = s.split(":", 1)[1].split(",")
                                x = float(parts[0]); y = float(parts[1])
                                if len(parts) > 2:
                                    z = float(parts[2])
                            except Exception:
                                pass
                        elif s.startswith("demo_v0_yaw:") and yaw is None:
                            try:
                                yaw = float(s.split(":", 1)[1])
                            except Exception:
                                pass
                except Exception:
                    pass
            if handle is None:
                handle = ref.rsplit(".", 1)[-1]  # last-resort: refPath tail
            if asset is None:
                asset = "unknown"
            # Recover id_number from handle like "forklift_2"
            if id_n is None and "_" in handle:
                tail = handle.rsplit("_", 1)[1]
                if tail.isdigit():
                    id_n = int(tail)
            if handle in seen_handles:
                continue
            seen_handles.add(handle)
            out.append({
                "actor_handle": handle,
                "asset_name": asset,
                "id_number": id_n,
                "x": x if x is not None else 0,
                "y": y if y is not None else 0,
                "z": z if z is not None else 0,
                "yaw_deg": yaw if yaw is not None else 0,
            })

        # Purge ledger entries whose actor_ref is no longer live (manual
        # editor cleanup, level reload, etc.).
        live_set = set(live_refs)
        for k, rec in list(bucket.items()):
            if rec.get("actor_ref") and rec["actor_ref"] not in live_set:
                bucket.pop(k, None)
        self._ledger_save()
        return {"objects": out}

    def demo_clear(self) -> dict:
        """Remove every demo-spawned actor in the current level.

        Earlier this only walked the Demo/v0 outliner folder, but
        PackedLevelActor instances frequently refuse set_actor_folder
        AND set_actor_properties({tags:...}) -- both fail silently. Those
        actors then survived demo_clear with no folder, no tag, no name
        match (the bug user hit on reseed). Fix: union 3 independent
        sources of truth, dedupe by refPath, remove each.
        """
        self.auto_load_toolsets()

        refs: set[str] = set()
        sources_hit = {"folder": 0, "tag": 0, "ledger": 0}

        # Source 1: Demo/v0 outliner folder (the original path).
        try:
            for a in self._list_demo_folder():
                r = a.get("refPath") if isinstance(a, dict) else a
                if r:
                    if r not in refs:
                        sources_hit["folder"] += 1
                    refs.add(r)
        except Exception:
            pass

        # Source 2: tag = 'demo_v0_spawned'. Spawn tries to set this; on
        # PackedLevelActor it may fail, but on every StaticMeshActor it
        # sticks and survives ADORE restarts even when the ledger lost
        # the entry.
        try:
            tagged = self.call_tool_unwrapped(
                "toolset_registry.toolsets.core.scene.SceneTools.find_actors",
                {"tag": "demo_v0_spawned"},
            )
            if isinstance(tagged, dict):
                tagged = tagged.get("actors") or tagged.get("results") or []
            if isinstance(tagged, list):
                for a in tagged:
                    r = a.get("refPath") if isinstance(a, dict) else a
                    if r:
                        if r not in refs:
                            sources_hit["tag"] += 1
                        refs.add(r)
        except Exception:
            pass

        # Source 3: in-memory ledger. Catches PackedLevelActor instances
        # that refused both folder and tag -- as long as ADORE saw them
        # at spawn time, the ledger remembers their refPath.
        try:
            bucket = self._ledger_bucket()
            for _h, rec in bucket.items():
                if not isinstance(rec, dict):
                    continue
                r = rec.get("actor_ref")
                if r:
                    if r not in refs:
                        sources_hit["ledger"] += 1
                    refs.add(r)
        except Exception:
            pass

        cleared = 0
        failed: list[str] = []
        for r in refs:
            try:
                self.call_tool_unwrapped(
                    "toolset_registry.toolsets.core.scene.SceneTools.remove_from_scene",
                    {"actor": r},
                )
                cleared += 1
            except Exception as e:
                failed.append(f"{r}: {type(e).__name__}: {e}")

        self._ledger_bucket().clear()
        self._ledger_save()
        return {"cleared": cleared, "total": len(refs),
                "sources_hit": sources_hit, "failed": failed}

    def demo_nudge(self, handle: str, dx_m: float = 0, dy_m: float = 0, dz_m: float = 0,
                   anchor_override_cm: dict | None = None) -> dict:
        """Relative move: current_pos + (dx, dy, dz). Handles the common
        '往左/前/后 N 米' chat patterns without forcing the LLM to first
        list_objects to look up the absolute target."""
        self.auto_load_toolsets()
        bucket = self._ledger_bucket()
        rec = bucket.get(handle)
        cur_x = rec.get("x", 0) if rec else None
        cur_y = rec.get("y", 0) if rec else None
        cur_z = rec.get("z", 0) if rec else None
        if cur_x is None or cur_y is None:
            # Fallback: query through demo_list which can recover from
            # tags even when ledger is empty. Position may still be 0,0
            # if the actor was never spawned via us.
            for o in self.demo_list().get("objects", []):
                if o.get("actor_handle") == handle:
                    cur_x = o.get("x", 0)
                    cur_y = o.get("y", 0)
                    cur_z = o.get("z", 0)
                    break
        if cur_x is None or cur_y is None:
            return {"error": f"no demo actor matching '{handle}'"}
        # Clamp the post-delta target to scene bounds so '往左 1000 米'
        # doesn't fling the actor out into the void.
        SCENE_BOUNDS_M = 25.0
        new_x = max(-SCENE_BOUNDS_M, min(SCENE_BOUNDS_M, cur_x + dx_m))
        new_y = max(-SCENE_BOUNDS_M, min(SCENE_BOUNDS_M, cur_y + dy_m))
        return self.demo_move(handle, new_x, new_y, cur_z + dz_m,
                              anchor_override_cm=anchor_override_cm)

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
        # Couldn't decode -- log enough context so we can adapt the
        # parser without dumping bytes everywhere.
        if isinstance(result, dict):
            print(f"[mcp] CaptureEditorImage unparsed: dict keys="
                  f"{list(result.keys())}", flush=True)
        else:
            preview = repr(result)[:120] if result is not None else "None"
            print(f"[mcp] CaptureEditorImage unparsed: "
                  f"type={type(result).__name__} preview={preview}", flush=True)
        return None

    def pcg_status(self) -> dict:
        """Cheap one-RPC probe: is there a PCG Volume with a graph bound
        in the current level? Used to decide whether to expose
        update_scene to the LLM. Returns:
          {has_pcg_volume: bool, has_graph: bool, graph_path: str|None,
           pcg_component_ref: str|None, level: str}
        """
        out = {"has_pcg_volume": False, "has_graph": False,
               "graph_path": None, "pcg_component_ref": None,
               "level": self._current_level_cached()}
        try:
            ref = self.find_pcg_component_refpath()
            out["pcg_component_ref"] = ref
            out["has_pcg_volume"] = True
        except Exception:
            return out
        # Read the PCG Component's graphInstance.graph to detect whether
        # a graph asset is actually bound.
        try:
            gi_field = self.get_actor_properties(ref, ["graphInstance"])
            gi_obj = (gi_field.get("graphInstance")
                      if isinstance(gi_field, dict) else None) or {}
            gi_ref = gi_obj.get("refPath")
            if gi_ref:
                graph_field = self.get_actor_properties(gi_ref, ["graph"])
                graph_obj = (graph_field.get("graph")
                             if isinstance(graph_field, dict) else None) or {}
                gp = graph_obj.get("refPath")
                if gp:
                    out["has_graph"] = True
                    out["graph_path"] = gp
        except Exception:
            pass
        return out

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
