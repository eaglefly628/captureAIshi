#!/usr/bin/env python
"""Standalone MCP probe -- exercises the new mcp_client.py end-to-end.

Run on the box that hosts the live UE Editor (typically your Windows
workstation). Walks: handshake -> auto-load 4 toolsets -> find PCG
component -> read seed -> write seed -> drill graphInstance for the
21-param OverrideParams layout.

Usage:
    cd D:\\project\\captureAIshi
    set UNREAL_MCP_URL=http://127.0.0.1:8000/mcp  # optional, default
    python apps/adore_robot/tools/probe_mcp.py

Prereqs:
    * UE Editor running with ModelContextProtocol.StartServer
    * PCG Volume placed in the level (Plan-B graph drilldown also wants
      the Volume's Graph asset assigned)
    * Optional: select the PCG Volume actor before running -- otherwise
      we'll fall back to ProgrammaticToolset's find_all.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Allow running from repo root or from apps/adore_robot/tools/
HERE = Path(__file__).resolve()
ADORE_ROOT = HERE.parent.parent  # apps/adore_robot
sys.path.insert(0, str(ADORE_ROOT))

from mcp_client import UnrealMCPClient  # noqa: E402


def banner(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def main() -> int:
    url = os.environ.get("UNREAL_MCP_URL", "http://127.0.0.1:8000/mcp")
    skip_autoload = "--no-autoload" in sys.argv
    client = UnrealMCPClient(url=url)

    banner("Step 1: handshake")
    try:
        info = client.initialize()
        print(f"session_id: {client.session_id}")
        print(f"server info: {info.get('serverInfo', {})}")
        print(f"capabilities: {info.get('capabilities', {})}")
    except ConnectionError as e:
        print(f"FAIL: {e}")
        print("hint: start UE Editor + ` -> ModelContextProtocol.StartServer")
        return 1

    if skip_autoload:
        banner("Step 2: SKIPPED (--no-autoload flag set)")
        print("Assuming toolsets already loaded in a prior curl/probe run.")
        print("If get_properties later fails 'tool not found', drop the flag.")
    else:
        banner("Step 2: auto-load default toolsets")
        load = client.auto_load_toolsets()
        print(json.dumps(load, indent=2, ensure_ascii=False))

    banner("Step 3: get_current_level (sanity smoke)")
    print(client.get_current_level())

    banner("Step 4: find PCG component")
    try:
        pcg_ref = client.find_pcg_component_refpath()
        print(f"PCG Component: {pcg_ref}")
    except RuntimeError as e:
        print(f"FAIL: {e}")
        return 2

    banner("Step 5: read current seed")
    seed_now = client.get_actor_properties(pcg_ref, ["seed"])
    print(json.dumps(seed_now, indent=2, ensure_ascii=False))

    banner("Step 6: write seed = 42424 (then read back)")
    write_result = client.set_actor_properties(pcg_ref, {"seed": 42424})
    print(f"write result: {write_result}")
    read_back = client.get_actor_properties(pcg_ref, ["seed"])
    print(f"read back: {read_back}")
    if isinstance(read_back, dict) and read_back.get("seed") == 42424:
        print("OK: round-trip primitive write proven.")
    else:
        print("WARN: seed did not round-trip as expected")

    banner("Step 7 (Plan-B): drill into graphInstance")
    gi_field = client.get_actor_properties(pcg_ref, ["graphInstance"])
    gi_obj = gi_field.get("graphInstance") if isinstance(gi_field, dict) else None
    gi_ref = gi_obj.get("refPath") if isinstance(gi_obj, dict) else None
    if not gi_ref:
        print("PCG Component has no graphInstance.")
        print("To explore the 21-param OverrideParams layout, assign a PCG")
        print("Graph asset to the Volume in Details panel and re-run.")
        return 0

    print(f"graphInstance: {gi_ref}")
    gi_schema = client.list_actor_properties(gi_ref)
    if isinstance(gi_schema, dict):
        keys = sorted(gi_schema.keys())
        print(f"graphInstance has {len(keys)} fields:")
        for k in keys:
            t = gi_schema[k].get("type", "?") if isinstance(gi_schema[k], dict) else "?"
            print(f"  - {k}: {t}")
        interesting = [k for k in keys
                       if any(s in k.lower() for s in ("override", "param", "graph"))]
        if interesting:
            banner("Step 8: read interesting graphInstance values")
            vals = client.get_actor_properties(gi_ref, interesting)
            print(json.dumps(vals, indent=2, ensure_ascii=False))

    banner("DONE")
    print("All steps green = Plan A wiring + Plan B exploration both verified.")
    print("Paste full output into apps/adore_robot/docs/ue58_mcp_validation_log.md")
    print("to backfill the 21-param OverrideParams structure section.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
