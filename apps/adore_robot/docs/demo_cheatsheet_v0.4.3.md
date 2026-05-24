# ADORE Demo Cheat Sheet (v0.4.3)

Quick reference for tomorrow's demo. Walks the LLM/operator through the
flows that are known to work + the rough scripts.

---

## Pre-flight (5 min before demo)

1. UE Editor running, RobotDemo1.umap or RobotDemo2.umap open
2. PCGVolume (TriggerVolume tagged `PCGVolume`) placed in the level
3. Editor Preferences -> General -> Performance -> uncheck
   "Use Less CPU when in Background" (so viewport ticks even when
   ADORE browser is focused)
4. `ModelContextProtocol.StartServer` in UE Output Log
5. `python apps/adore_robot/main.py` -> http://127.0.0.1:5001
6. Splash should show "8 toolsets mounted", click 进入控制台

---

## Demo chat scripts (known good)

### Generate warehouse
- `生成一个仓库 40 个物件`            -> generate_warehouse_layout (SSE progress)
- `换个 seed 再生成一次`              -> regenerate (clear_first=true auto)
- `更乱一点 / chaos 0.8`              -> regenerate with chaos param
- `用冷白灯`                          -> lighting_preset=1
- `换 mixed 灯光`                     -> lighting_preset=2

### Bulk spawn (with progress bar -- new)
- `批量放 100 个纸箱子`               -> bulk_spawn box x100
- `散 200 个油桶`                     -> bulk_spawn drum x200
- `30 个工人`                         -> bulk_spawn worker x30 (robots)

### Single placement / move
- `在 (3, 2) 放一个叉车`              -> spawn_object forklift
- `把 forklift_1 往左移 2 米`          -> nudge_object dx=-2
- `把 box_5 移到 (0, 0)`              -> modify_location

### PIE control (SlateInspector path)
- `play in editor / 开始 PIE / 运行` -> Alt+P via Slate
- `停止 PIE / stop`                   -> Esc via Slate

### Capture (4-channel)
- `capture / 截图 / 给我看 4 通道`    -> 2x2 grid + ObjectID legend
  (RGB real, depth/normal/objectid mock-derived)

### Clear
- `清空场景 / clear all`              -> demo_clear (4-source scan)

---

## Diagnostic URLs (operator only)

- `http://localhost:5001/tools`                       browse 100 MCP tools
- `http://localhost:5001/api/mcp/tools`               raw 100-tool JSON
- `http://localhost:5001/api/mcp/toolsets`            41 toolset names
- `http://localhost:5001/api/mcp/explore_all?short=true` 41 toolsets + tool list
- `http://localhost:5001/api/demo/diagnose_workspace?x=0&y=0`  volume + anchor
- `http://localhost:5001/api/demo/refresh_volume`     re-resolve PCGVolume
- `http://localhost:5001/api/mcp/probe_sandbox`       unreal-import allowed?
- `http://localhost:5001/api/demo/dump_volume_raw`    full schema dump

---

## Known limitations (call out if asked)

- ~0.3% spawn -> actor missing tag + folder (UE deferred reset race).
  `_fixup_markers_after_batch` parked in mcp_client; not auto-invoked.
  TODO: enable post-demo.
- depth/normal/objectid in capture are derived mocks. Real renderdoc
  pipeline lives in apps/capture (xiaoxuan); integration is TODO.
- PIE remote needs Flask on same Windows box as UE (SlateInspector
  works regardless of platform but the SendInput fallback is Windows).
- Robot13_Blueprint path-follower is parked as C++ component in
  docs/cpp/; bp owner has not added it yet. start_patrol uses
  delete+respawn placeholder that flickers.

---

## If something breaks mid-demo

| Symptom | Quick fix |
|---|---|
| Spawn places outside volume | `/api/demo/refresh_volume` then retry |
| 4 channel capture missing tiles | restart Flask (CAPTURE_CACHE may be stale) |
| LLM picks wrong tool | rephrase using a tool description anchor word |
| `box_N_xxxx` orphans after clear | call clear again (4-source scan picks them up) |
| PIE doesn't start | check UE Alt+P binding; fallback `/api/demo/pie_start` |
| Viewport frozen | open viewport tab in UE or toggle Realtime (Ctrl+R) |

---

## Where the code lives

```
apps/adore_robot/
  main.py                  Flask app + all SSE / diagnose endpoints
  mcp_client.py            UE MCP HTTP client + demo_spawn/clear/move
  demo/
    demo_tools.py          13 LLM ToolDefs + dispatchers
    asset_registry.py      asset_name -> UE path + pivot_z map
    pie_control.py         Win32 SendInput fallback (rarely used)
  web/static/app/
    main.jsx               chat send + SSE consumer + relay handlers
    panels.jsx             ChatPanel + CaptureCard + ActionPill
  docs/
    cpp/                   parked C++ PathFollowerComponent
    robot13_path_follower_bp.md
agents/pcg/SHARED.md       v0.4.3 state + TODO (read first on resume)
```
