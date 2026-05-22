// app.jsx — main orchestrator

const { useState, useEffect, useRef, useCallback } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "scene": "warehouse",
  "robot": "franka_panda"
}/*EDITMODE-END*/;

function nowStamp() {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
}

// Stage durations (ms) — compressed from 33 minutes
const STAGE_DURATIONS = {
  parse: 1500,
  dispatch: 100, // per call, multiplied by N
  generate: 2200,
  render: 4500,
  package: 1200,
};

// Toolset name -> customer-friendly capability label.
const TOOLSET_LABELS = {
  'session': '神经握手',
  'tools/list': '能力清单',
  'ToolsetRegistry.EditorAppToolset': '编辑器内核 · EditorApp',
  'toolset_registry.toolsets.core.object.ObjectTools': '对象反射层 · ObjectTools',
  'toolset_registry.toolsets.core.scene.SceneTools': '场景态势引擎 · SceneTools',
  'toolset_registry.toolsets.core.programmatic.ProgrammaticToolset': '程序化沙箱 · Programmatic',
};
function toolsetLabel(name) {
  if (!name) return '';
  if (TOOLSET_LABELS[name]) return TOOLSET_LABELS[name];
  // shorten unknown names
  const tail = name.split('.').slice(-1)[0];
  return `${tail}`;
}

function UEViewportPip({ cacheKey, mcpReady }) {
  const [expanded, setExpanded] = React.useState(false);
  const [failed, setFailed] = React.useState(false);
  // Reset failure state whenever a fresh capture is requested. Without
  // this, the first failed fetch latches `failed=true` and the fallback
  // branch hides the <img> forever -- onLoad can never re-fire to
  // recover.  UE briefly down + back = dead PIP until page reload.
  React.useEffect(() => { setFailed(false); }, [cacheKey]);
  if (!mcpReady) return null;
  const src = `/api/mcp/screenshot.png?t=${cacheKey}`;
  return (
    <div className={`ue-pip ${expanded ? 'expanded' : ''}`}
         onClick={() => setExpanded(e => !e)}>
      <div className="ue-pip-hud">
        <span className="ue-pip-dot" />
        <span className="ue-pip-label">UE 5.8 EDITOR · LIVE</span>
        <span className="ue-pip-hint">{expanded ? '✕' : '⤢'}</span>
      </div>
      {failed ? (
        <div className="ue-pip-fallback">无法捕获截图<br/>(open a level in UE)</div>
      ) : (
        <img className="ue-pip-img" src={src} alt="UE viewport"
             onError={() => setFailed(true)}
             onLoad={() => setFailed(false)} />
      )}
    </div>
  );
}

function McpBootOverlay({ state, onRetry, onDismiss }) {
  if (!state) return null;
  const pct = state.total > 0 ? Math.min(100, Math.round((state.current / state.total) * 100)) : 0;
  const elapsed = ((state.elapsed_ms || 0) / 1000).toFixed(1);
  const failed = state.done && state.ok === false;
  const ready = state.done && state.ok === true;

  let headline;
  if (failed) headline = '神经接口未响应';
  else if (ready) headline = 'UNREAL 5.8 EDITOR · LINK ESTABLISHED';
  else if (state.phase === 'handshake') headline = '正在唤醒 Unreal 神经接口';
  else if (state.phase === 'prime') headline = '探测可用能力空间';
  else if (state.phase === 'loading') headline = '挂载 AI 工具集';
  else if (state.phase === 'skipped') headline = '工具集已就绪';
  else headline = 'ADORE-AI · 引导中';

  const subline = failed
    ? state.error
    : ready
      ? `握手完成 · 4 个工具集挂载 · 协议延迟 ${elapsed}s`
      : (state.toolset ? toolsetLabel(state.toolset) : '...');

  const steps = (state.steps || []).slice(-6);
  const sessionShort = state.session_short || (state.started ? String(Math.floor(state.started_at || 0)).slice(-6) : '——');

  return (
    <div className={`mcp-boot ${failed ? 'err' : ''} ${ready ? 'ok' : ''}`}>
      <div className="mcp-boot-scrim" />
      <div className="mcp-boot-card">
        {/* corner brackets via CSS pseudo, plus center watermark */}
        <div className="mcp-boot-watermark" aria-hidden>UE</div>

        <div className="mcp-boot-hud">
          <span className="mcp-boot-tag">
            <span className="mcp-boot-tag-mark" />
            ADORE-AI · NEURAL CONSOLE
          </span>
          <span className="mcp-boot-sid">v0.4.0 · SESSION · {sessionShort}</span>
        </div>

        <div className="mcp-boot-banner">
          <div className="mcp-boot-banner-left">
            <span className="mcp-boot-ue">UNREAL ENGINE</span>
            <span className="mcp-boot-ue-ver">5.8</span>
          </div>
          <span className="mcp-boot-banner-sep" />
          <span className="mcp-boot-banner-proto">
            MODEL CONTEXT PROTOCOL · 2025-11-25
          </span>
          <span className="mcp-boot-banner-grow" />
          <span className={`mcp-boot-link-dot ${ready ? 'on' : failed ? 'err' : ''}`} />
          <span className="mcp-boot-banner-status">
            {ready ? 'LINK ESTABLISHED' : failed ? 'LINK FAILED' : 'LINKING...'}
          </span>
        </div>

        <div className="mcp-boot-title">
          <span className="mcp-boot-glyph" aria-hidden>◈</span>
          <span>{headline}</span>
        </div>
        <div className="mcp-boot-sub">{subline}</div>

        <div className="mcp-boot-bar">
          <div className="mcp-boot-bar-fill" style={{ width: `${pct}%` }} />
          <div className="mcp-boot-bar-scan" />
          <div className="mcp-boot-bar-ticks" aria-hidden />
        </div>
        <div className="mcp-boot-meta">
          <span>{state.current}/{state.total}</span>
          <span>{pct}%</span>
          <span>{elapsed}s</span>
        </div>

        <ul className="mcp-boot-log">
          {steps.map((s, i) => (
            <li key={i} className={s.status === 'done' ? 'done' : s.status?.startsWith('error') ? 'err' : 'run'}>
              <span className="mcp-boot-dot" />
              <span className="mcp-boot-log-name">{toolsetLabel(s.toolset)}</span>
              <span className="mcp-boot-log-at">{(s.at_ms / 1000).toFixed(2)}s</span>
            </li>
          ))}
        </ul>

        <div className="mcp-boot-stats">
          <div className="mcp-boot-stat">
            <span className="mcp-boot-stat-k">PROTOCOL</span>
            <span className="mcp-boot-stat-v">MCP 1.0 · JSON-RPC 2.0</span>
          </div>
          <div className="mcp-boot-stat">
            <span className="mcp-boot-stat-k">TRANSPORT</span>
            <span className="mcp-boot-stat-v">HTTP+SSE :8000</span>
          </div>
          <div className="mcp-boot-stat">
            <span className="mcp-boot-stat-k">CAPABILITY</span>
            {ready ? (
              <a
                className="mcp-boot-stat-v"
                href="/tools"
                target="_blank"
                rel="noopener"
                title="查看所有 toolsets / tools 明细"
                style={{
                  textDecoration: 'underline',
                  textDecorationStyle: 'dotted',
                  textUnderlineOffset: 3,
                  cursor: 'pointer',
                  color: 'inherit',
                }}
              >
                41 toolsets · 35 tools ›
              </a>
            ) : (
              <span className="mcp-boot-stat-v">probing...</span>
            )}
          </div>
        </div>

        <div className="mcp-boot-actions">
          {failed && (
            <>
              <button className="mcp-boot-btn" onClick={onRetry}>重连 UE Editor</button>
              <button className="mcp-boot-btn ghost" onClick={onDismiss}>跳过 · 离线演示</button>
            </>
          )}
          {ready && (
            <>
              <a
                className="mcp-boot-btn ghost"
                href="/tools"
                target="_blank"
                rel="noopener"
                style={{ textDecoration: 'none', display: 'inline-flex',
                         alignItems: 'center' }}
              >
                查看 tools 明细
              </a>
              <button className="mcp-boot-btn" onClick={onDismiss}>进入控制台 ›</button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function App() {
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const scene = tweaks.scene;
  const robot = tweaks.robot;

  const [messages, setMessages] = useState([]);
  const [params, setParams] = useState({ ...DEFAULT_PARAMS });
  const [runStatus, setRunStatus] = useState('idle');
  const [stageProgress, setStageProgress] = useState(0);
  const [runtimeMs, setRuntimeMs] = useState(0);
  const [toolCalls, setToolCalls] = useState([]);
  const [currentFrame, setCurrentFrame] = useState(0);
  const [flashKey, setFlashKey] = useState(null);
  const [rightTab, setRightTab] = useState('params');
  const [dataset, setDataset] = useState(null);
  const [mrqSubdir, setMrqSubdir] = useState('warehouse/v0_demo');
  const [chatMode, setChatMode] = useState('scene');
  const [mcpInit, setMcpInit] = useState(null);
  const [mcpInitDismissed, setMcpInitDismissed] = useState(false);
  // Viewport starts empty (just floor + walls). First successful chat
  // action seeds the mock layout so the customer sees "empty -> populated".
  const [sceneSeeded, setSceneSeeded] = useState(false);
  // Mirror of UE Demo/v0 folder state. Each entry comes from a real
  // server-confirmed action; viewport renders these 1:1 so the SVG iso
  // mock matches what's actually in the UE level.
  const [spawnedActors, setSpawnedActors] = useState([]);
  const [currentLevel, setCurrentLevel] = useState('');
  // PCG availability per current level. Surfaces a chip in TopBar +
  // (later) example prompts hint when PCG mode is on.
  const [pcgStatus, setPcgStatus] = useState(null);
  const [appVersion, setAppVersion] = useState('');
  // Cache-buster counter bumped after every successful chat action so the
  // UE viewport PIP <img> re-fetches.  Also bumped on MCP-ready boot.
  const [ueShotKey, setUeShotKey] = useState(0);

  // Fetch app version once on mount for the TopBar brand chip.
  useEffect(() => {
    fetch('/api/status').then(r => r.json()).then(j => {
      if (j.ok && j.version) setAppVersion(`v${j.version}`);
    }).catch(() => {});
  }, []);

  const busyRef = useRef(false);
  const animFrameRef = useRef(null);

  // Poll MCP init progress. Backend kicks the init thread at startup; we
  // read latest state every 250ms while it's running. A ref tracks the
  // active poll session so retry can cleanly restart it.
  const pollSeqRef = useRef(0);
  const startMcpPoll = useCallback(() => {
    pollSeqRef.current += 1;
    const mySeq = pollSeqRef.current;
    const tick = async () => {
      if (pollSeqRef.current !== mySeq) return;
      try {
        const j = await fetch('/api/mcp/init').then(r => r.json());
        if (pollSeqRef.current !== mySeq) return;
        setMcpInit(j);
        if (!j.done) {
          setTimeout(tick, 250);
        }
        // On done (ok or err): stop polling. Overlay stays open so the
        // customer sees the full handshake -> green-ready flow and the
        // operator decides when to dismiss via the "进入控制台" button.
      } catch {
        if (pollSeqRef.current === mySeq) setTimeout(tick, 1000);
      }
    };
    tick();
  }, []);

  useEffect(() => {
    startMcpPoll();
    return () => { pollSeqRef.current += 1; };  // invalidate on unmount
  }, [startMcpPoll]);

  const refreshPcgStatus = useCallback(async () => {
    try {
      const j = await fetch('/api/mcp/pcg_status').then(r => r.json());
      if (j.ok) setPcgStatus(j);
    } catch {}
  }, []);

  // Sync spawnedActors with UE's Demo/v0 folder. Called automatically
  // when MCP boot finishes (so opening the page already shows whatever
  // RobotDemo.umap has) and from the manual Sync button.
  const syncFromUE = useCallback(async () => {
    try {
      const r = await fetch('/api/demo/list_objects');
      const j = await r.json();
      if (j.ok && Array.isArray(j.objects)) {
        setSpawnedActors(j.objects.map(o => ({
          actor_handle: o.actor_handle,
          asset_name: o.asset_name || 'shelf',
          id_number: o.id_number,
          x: o.x ?? 0, y: o.y ?? 0, z: o.z ?? 0, yaw_deg: o.yaw_deg ?? 0,
        })));
        setSceneSeeded(j.objects.length > 0);
        setUeShotKey(k => k + 1);
      }
    } catch {}
  }, []);

  const clearAllFromUE = useCallback(async () => {
    try {
      await fetch('/api/demo/clear', { method: 'POST' });
      setSpawnedActors([]);
      setSceneSeeded(false);
    } catch {}
  }, []);

  // Auto-sync the moment MCP init turns green.
  useEffect(() => {
    if (mcpInit && mcpInit.done && mcpInit.ok) {
      syncFromUE();
      refreshPcgStatus();
    }
  }, [mcpInit && mcpInit.done && mcpInit.ok, syncFromUE, refreshPcgStatus]);

  // Poll current level every 4s. UE is the source of truth -- when user
  // opens a different .umap in the editor we detect it and re-sync.
  useEffect(() => {
    if (!(mcpInit && mcpInit.done && mcpInit.ok)) return;
    let alive = true;
    const tick = async () => {
      try {
        const j = await fetch('/api/mcp/current_level').then(r => r.json());
        if (!alive) return;
        const lvl = j.ok ? (j.level_path || '') : '';
        if (lvl && lvl !== currentLevel) {
          setCurrentLevel(lvl);
          // Level changed in UE -> wipe local mirror and pull the new
          // level's Demo/v0 contents fresh.  Also re-probe PCG status
          // since the new level may or may not have a PCG graph bound.
          setSpawnedActors([]);
          setSceneSeeded(false);
          syncFromUE();
          refreshPcgStatus();
        }
      } catch {}
      if (alive) setTimeout(tick, 4000);
    };
    tick();
    return () => { alive = false; };
  }, [mcpInit && mcpInit.done && mcpInit.ok, currentLevel, syncFromUE]);

  const retryMcpInit = useCallback(() => {
    setMcpInitDismissed(false);
    setMcpInit(prev => prev ? { ...prev, started: true, done: false, error: null, ok: null, phase: 'handshake', current: 0 } : null);
    fetch('/api/mcp/init', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force: true }),
    }).catch(() => {});
    startMcpPoll();
  }, [startMcpPoll]);

  const updateParam = useCallback((key, value, flash = false) => {
    setParams(prev => ({ ...prev, [key]: value }));
    if (flash) {
      setFlashKey(key);
      setTimeout(() => setFlashKey(prev => prev === key ? null : prev), 900);
    }
  }, []);

  // Detect intended scene from a prompt
  function inferScene(text) {
    if (/客厅|living|sofa|杯|cup/i.test(text)) return 'livingroom';
    if (/工厂|factory|流水|conveyor|工位|扳手|wrench/i.test(text)) return 'factory';
    if (/仓库|warehouse|货架|shelf|叉车|forklift/i.test(text)) return 'warehouse';
    return null;
  }

  // ─── The orchestrated pipeline run ───────────────────────────────────────
  const runPipeline = useCallback(async (userText) => {
    if (busyRef.current) return;
    busyRef.current = true;

    // Reset
    setDataset(null);
    setCurrentFrame(0);
    setRuntimeMs(0);
    const startedAt = performance.now();
    const tickRuntime = () => {
      setRuntimeMs(performance.now() - startedAt);
      animFrameRef.current = requestAnimationFrame(tickRuntime);
    };
    animFrameRef.current = requestAnimationFrame(tickRuntime);

    // 1) Append user message
    setMessages(prev => [...prev, { role: 'user', text: userText, ts: nowStamp() }]);

    // Maybe change scene
    const inferred = inferScene(userText);
    if (inferred && inferred !== scene) {
      setTweak('scene', inferred);
    }
    const effectiveScene = inferred || scene;

    // 2) Insert assistant thinking stub immediately (so user sees activity)
    const assistantIdx = await new Promise(r => {
      setMessages(prev => {
        r(prev.length);
        return [...prev, {
          role: 'assistant', text: '思考中…',
          actions: [],
          thinking: true, ts: nowStamp()
        }];
      });
    });

    // 2b) Real LLM call (DeepSeek-V4-Flash via Flask /api/chat). Returns one
    // update_scene tool_call with pcg_params delta + rationale. We expand
    // the delta into per-param actions so the pipeline animation still
    // shows the granular tool_call stream the design promises.
    let resp;
    try {
      const realCalls = await callRealChat(userText, effectiveScene, params);
      resp = realCalls;
      // Mirror UE state into spawnedActors so the viewport shows exactly
      // what was just spawned/moved/deleted -- nothing more.
      const r = realCalls.relayMeta;
      if (r && r.ok) {
        // Real UE state changed -> grab fresh viewport screenshots.
        // UE Editor's add_to_scene_from_asset is async: it returns when
        // the spawn is queued, not when the new actor has actually been
        // rendered in the viewport. We retry at a few intervals so the
        // PIP catches the engine once the frame settles.
        // Capture cadence: UE's add_to_scene + delete cycles are async
        // and don't settle in one tick. 4 retries span ~5s so even slow
        // editor frames catch up.
        setTimeout(() => setUeShotKey(k => k + 1), 400);
        setTimeout(() => setUeShotKey(k => k + 1), 1200);
        setTimeout(() => setUeShotKey(k => k + 1), 2500);
        setTimeout(() => setUeShotKey(k => k + 1), 5000);
        const res = r.result || {};
        if (r.tool === 'spawn_object' && res.actor_handle) {
          setSpawnedActors(prev => [...prev, {
            actor_handle: res.actor_handle,
            asset_name: res.asset_name,
            id_number: res.id_number,
            x: res.x, y: res.y, z: res.z, yaw_deg: res.yaw_deg,
          }]);
          setSceneSeeded(true);
        } else if (r.tool === 'generate_warehouse_layout' && Array.isArray(res.spawned)) {
          setSpawnedActors(res.spawned.map(s => ({
            actor_handle: s.actor_handle,
            asset_name: s.asset_name,
            id_number: s.id_number,
            x: s.x, y: s.y, z: s.z ?? 0, yaw_deg: s.yaw_deg ?? 0,
          })));
          setSceneSeeded(true);
        } else if (r.tool === 'spawn_batch' && Array.isArray(res.spawned)) {
          setSpawnedActors(prev => [...prev, ...res.spawned.map(s => ({
            actor_handle: s.actor_handle,
            asset_name: s.asset_name,
            id_number: s.id_number,
            x: s.x, y: s.y, z: s.z ?? 0, yaw_deg: s.yaw_deg ?? 0,
          }))]);
          if (res.total > 0) setSceneSeeded(true);
        } else if (r.tool === 'clear_demo_objects') {
          setSpawnedActors([]);
          setSceneSeeded(false);
        } else if (r.tool === 'delete_object' && res.deleted) {
          setSpawnedActors(prev => prev.filter(a => a.actor_handle !== res.deleted));
        } else if ((r.tool === 'modify_location' || r.tool === 'nudge_object') && res.actor_handle) {
          setSpawnedActors(prev => {
            // server may have re-spawned with new handle (see demo_move);
            // drop old, push new entry at new coords.
            const oldH = res.old_handle;
            const keep = oldH ? prev.filter(a => a.actor_handle !== oldH) : prev;
            const old = oldH ? prev.find(a => a.actor_handle === oldH) : null;
            return [...keep, {
              actor_handle: res.actor_handle,
              asset_name: res.asset_name || old?.asset_name || 'shelf',
              // Preserve id_number across server-side delete+respawn
              // so the F1/S3 badge sticks to the same actor. Server now
              // returns it explicitly; fall back to the previous entry.
              id_number: (res.id_number != null) ? res.id_number : old?.id_number,
              x: res.new_xyz_m[0], y: res.new_xyz_m[1], z: res.new_xyz_m[2] ?? 0,
              yaw_deg: (res.yaw_deg != null) ? res.yaw_deg : (old?.yaw_deg ?? 0),
            }];
          });
        } else if (r.tool === 'list_objects' && Array.isArray(res.objects)) {
          setSpawnedActors(res.objects.map(o => ({
            actor_handle: o.actor_handle,
            asset_name: o.asset_name,
            id_number: o.id_number,
            x: o.x, y: o.y, z: o.z ?? 0, yaw_deg: o.yaw_deg ?? 0,
          })));
          if (res.objects.length > 0) setSceneSeeded(true);
        }
      }
    } catch (err) {
      console.error('[chat] real LLM failed, fallback to canned:', err);
      resp = chooseResponse(userText, effectiveScene);
      resp.narrate = `(后端调用失败: ${err.message}, fallback to canned) ` + resp.narrate;
    }

    // refresh the stub with discovered actions
    setMessages(prev => prev.map((m, i) => i === assistantIdx
      ? { ...m, actions: resp.calls.map(c => ({ ...c, status: 'pending' })) }
      : m));

    // PARSE stage
    setRunStatus('parse');
    setToolCalls(resp.calls.map(c => ({ ...c, status: 'pending' })));
    await animateProgress(setStageProgress, STAGE_DURATIONS.parse);

    // Replace assistant text with narrate
    setMessages(prev => prev.map((m, i) => i === assistantIdx
      ? { ...m, text: resp.narrate, thinking: false }
      : m));

    // DISPATCH stage
    setRunStatus('dispatch');
    setStageProgress(0);
    const callTotal = resp.calls.length;
    // execute calls one by one
    for (let i = 0; i < callTotal; i++) {
      const tc = resp.calls[i];

      // mark this call as running
      setToolCalls(prev => prev.map((c, idx) => idx === i ? { ...c, status: 'running' } : c));
      setMessages(prev => prev.map((m, mi) => mi === assistantIdx
        ? { ...m, actions: m.actions.map((a, ai) => ai === i ? { ...a, status: 'running' } : a) }
        : m));

      // Apply effect of the call
      applyToolCallSideEffects(tc, {
        updateParam, setTweak, setMrqSubdir, setRightTab,
      });

      // generate_warehouse_layout is the only deferred tool right now -- it
      // runs as an SSE stream so the user sees per-actor progress instead
      // of waiting 5-15s for one giant relay response. resp.relayMeta is
      // the chat-endpoint's mcp_relay envelope; deferred=true means the
      // backend skipped the synchronous dispatch and handed the args back.
      if (tc.name === 'generate_warehouse_layout'
          && resp.relayMeta && resp.relayMeta.deferred) {
        // Clear any previous warehouse so live spawns are visible.
        setSpawnedActors([]);
        await runWarehouseStream(resp.relayMeta.args || tc.args || {}, {
          onPlan: (d) => {
            setMessages(prev => prev.map((m, mi) => mi === assistantIdx
              ? { ...m,
                  text: `${resp.narrate}  ·  PCG plan: ${d.total} actors`
                       + (d.volume_anchored ? ` · volume ${d.room_w}x${d.room_l}m` : '')
                       + (d.object_budget ? ` · budget ${d.object_budget}` : ''),
                  warehouseProgress: { i: 0, total: d.total, by_asset: d.by_asset || {} } }
              : m));
          },
          onSpawn: (d) => {
            if (d.ok) {
              setSpawnedActors(prev => [...prev, {
                actor_handle: d.actor_handle || `${d.asset_name}_${d.i}`,
                asset_name: d.asset_name,
                id_number: d.id_number != null ? d.id_number : d.i,
                x: d.x, y: d.y, z: d.z ?? 0, yaw_deg: d.yaw_deg ?? 0,
              }]);
            }
            setStageProgress(d.total > 0 ? d.i / d.total : 1);
            setMessages(prev => prev.map((m, mi) => mi === assistantIdx
              ? { ...m,
                  text: `${resp.narrate}  ·  生成中 ${d.i}/${d.total} · ${d.asset_name}`,
                  warehouseProgress: { i: d.i, total: d.total, latest: d.asset_name } }
              : m));
            // Throttled viewport snapshot every ~5 spawns so the PIP shows
            // the build happening in near-real-time without spamming MCP.
            if (d.i % 5 === 0) setUeShotKey(k => k + 1);
          },
          onDone: (d) => {
            // 'done' arrives before 'summary' and carries the optional
            // viewport_hint when invalidate has been permanently disabled.
            // Stash it on the message; onSummary appends the actor count
            // tail without clobbering this hint.
            if (d.viewport_hint) {
              setMessages(prev => prev.map((m, mi) => mi === assistantIdx
                ? { ...m, text: `${m.text}\n💡 ${d.viewport_hint}` }
                : m));
            }
          },
          onSummary: (d) => {
            setSceneSeeded(true);
            setUeShotKey(k => k + 1);
            const tail = d.spawned != null ? `  ·  ✓ ${d.spawned} actors` : '';
            setMessages(prev => prev.map((m, mi) => mi === assistantIdx
              ? { ...m,
                  text: m.text.includes('✓') ? m.text : `${m.text}${tail}`,
                  warehouseProgress: null }
              : m));
          },
          onError: (d) => {
            console.error('[warehouse-stream] error:', d);
            setMessages(prev => prev.map((m, mi) => mi === assistantIdx
              ? { ...m, text: `${resp.narrate}  ·  ✗ ${d.message || 'stream failed'}` }
              : m));
          },
        });
      } else {
        await sleep(220 + Math.random() * 120);
      }

      // mark done
      setToolCalls(prev => prev.map((c, idx) => idx === i ? { ...c, status: 'done' } : c));
      setMessages(prev => prev.map((m, mi) => mi === assistantIdx
        ? { ...m, actions: m.actions.map((a, ai) => ai === i ? { ...a, status: 'done' } : a) }
        : m));

      setStageProgress((i + 1) / callTotal);
    }

    // Only render if a trigger_mrq_render was in the calls
    const willRender = resp.calls.some(c => c.name === 'trigger_mrq_render');

    if (!willRender) {
      setRunStatus('done');
      setStageProgress(1);
      cancelAnimationFrame(animFrameRef.current);
      busyRef.current = false;
      return;
    }

    // ── GENERATE + RENDER + PACKAGE driven by real backend SSE ──────────
    // POST /api/demo/submit returns a real job_id + variant_id, then we
    // open EventSource /api/demo/stream/{job_id} and map status/log/done
    // events to UI stage state. Same protocol the UE commandlet will
    // speak once the C++ pipeline lands, so no UI swap will be needed.
    let submitResp;
    try {
      submitResp = await fetch('/api/demo/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scene_id: effectiveScene,
          pcg_params: params,
          rationale: resp.narrate || '',
          variants: 1,
        }),
      }).then(r => r.json());
    } catch (err) {
      console.error('[pipeline] submit failed:', err);
      setRunStatus('done');
      cancelAnimationFrame(animFrameRef.current);
      busyRef.current = false;
      return;
    }

    const job = submitResp && submitResp.jobs && submitResp.jobs[0];
    if (!job) {
      console.error('[pipeline] submit returned no job', submitResp);
      setRunStatus('done');
      cancelAnimationFrame(animFrameRef.current);
      busyRef.current = false;
      return;
    }
    setMrqSubdir(`${job.scene_id}/${job.variant_id}`);

    setRunStatus('generate');
    setStageProgress(0);

    await new Promise((resolve) => {
      const es = new EventSource(`/api/demo/stream/${job.job_id}`);
      let frameTotal = params.frame_count || 30;

      es.addEventListener('status', (e) => {
        try {
          const d = JSON.parse(e.data);
          if (d.status === 'pcg') {
            setRunStatus('generate');
            setStageProgress(0);
          } else if (d.status === 'mrq') {
            setRunStatus('render');
            setStageProgress(0);
            setRightTab('render');
            if (typeof d.frame_total === 'number') frameTotal = d.frame_total;
          }
          if (typeof d.frame_index === 'number' && typeof d.frame_total === 'number' && d.frame_total > 0) {
            setCurrentFrame(d.frame_index);
            setStageProgress(d.frame_index / d.frame_total);
          }
        } catch {}
      });

      es.addEventListener('log', (e) => {
        try {
          const d = JSON.parse(e.data);
          const tick = /pcg_tick (\d+)\/(\d+)/.exec(d.line || '');
          if (tick) {
            setStageProgress(parseInt(tick[1], 10) / parseInt(tick[2], 10));
            return;
          }
          const mrq = /mrq_frame (\d+)\/(\d+)/.exec(d.line || '');
          if (mrq) {
            const total = parseInt(mrq[2], 10);
            const f = parseInt(mrq[1], 10);
            setCurrentFrame(f);
            setStageProgress(f / total);
          }
        } catch {}
      });

      es.addEventListener('done', async (e) => {
        try {
          const d = JSON.parse(e.data);
          const subdir = `${d.scene_id}/${d.variant_id}`;
          setMrqSubdir(subdir);
          setCurrentFrame(d.frames);

          setRunStatus('package');
          setStageProgress(0);
          await animateProgress(setStageProgress, STAGE_DURATIONS.package);

          const fc = d.frames || frameTotal;
          const ds = {
            path: subdir,
            parquet: `${subdir.replace('/', '_')}.parquet`,
            parquetSize: '184 KB',
            video: `${subdir.replace('/', '_')}.mp4`,
            videoSize: '12.4 MB',
            exrs: fc,
            exrSize: `${(fc * 8.2).toFixed(1)} MB`,
            size: `${(fc * 8.2 + 12.4 + 0.18).toFixed(1)} MB`,
            manifest: d.manifest_path,
            job_id: d.job_id,
          };
          setDataset(ds);
          setMessages(prev => prev.map((m, i) => i === assistantIdx
            ? { ...m, dataset: ds }
            : m));
          setRunStatus('done');
          setStageProgress(1);
        } finally {
          es.close();
          resolve();
        }
      });

      es.addEventListener('error', () => {
        console.error('[stream] EventSource error');
        setRunStatus('done');
        es.close();
        resolve();
      });
    });

    cancelAnimationFrame(animFrameRef.current);
    busyRef.current = false;
  }, [scene, params, setTweak, updateParam]);

  // ─── Free-chat path (no pipeline, no tool_calls; raw LLM reply) ──────────
  const freeChat = useCallback(async (userText) => {
    setMessages(prev => [...prev, { role: 'user', text: userText, ts: nowStamp() }]);
    const idx = await new Promise(r => {
      setMessages(prev => {
        r(prev.length);
        return [...prev, { role: 'assistant', text: '思考中…', thinking: true, ts: nowStamp() }];
      });
    });
    const hist = messages
      .filter(m => (m.role === 'user' || m.role === 'assistant') && m.text)
      .slice(-10)
      .map(m => ({ role: m.role, content: m.text }));
    try {
      const r = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: userText, mode: 'free', history: hist }),
      });
      const data = await r.json();
      if (!data.ok) throw new Error(data.error || 'free chat failed');
      const meta = `${data.provider}/${data.model} · ${data.elapsed_ms}ms`;
      setMessages(prev => prev.map((m, i) => i === idx
        ? { ...m, text: data.text || '(空响应)', thinking: false, meta }
        : m));
    } catch (err) {
      setMessages(prev => prev.map((m, i) => i === idx
        ? { ...m, text: `调用失败: ${err.message}`, thinking: false }
        : m));
    }
  }, [messages]);

  // Cleanup
  useEffect(() => () => cancelAnimationFrame(animFrameRef.current), []);

  // Refresh right-tab to params after render done if user not interacting
  // (kept simple — they can click)

  // Right panel
  const rightTabs = (
    <div className="panel-hd">
      <div className={`tab ${rightTab === 'params' ? 'active' : ''}`} onClick={() => setRightTab('params')}>
        <span>Parameters</span><span className="count">21</span>
      </div>
      <div className={`tab ${rightTab === 'toolcalls' ? 'active' : ''}`} onClick={() => setRightTab('toolcalls')}>
        <span>Tool Calls</span><span className="count">{toolCalls.length}</span>
      </div>
      <div className={`tab ${rightTab === 'render' ? 'active' : ''}`} onClick={() => setRightTab('render')}>
        <span>Render</span>
        <span className="count">{currentFrame}/{params.frame_count}</span>
      </div>
    </div>
  );

  const generating = runStatus === 'generate';
  const projectName = SCENES[scene]?.label || 'Project';
  const jobName = `${scene}/${mrqSubdir.split('/')[1] || 'v0_demo'}`;

  const showMcpBoot = mcpInit && !mcpInitDismissed;
  // After user dismisses the overlay while UE is offline, keep an obvious
  // red banner pinned at the top so the reconnect entry point is never
  // hidden during a customer demo.
  const showOfflineBanner = mcpInit && mcpInitDismissed && mcpInit.done && mcpInit.ok === false;

  return (
    <>
      {showMcpBoot && (
        <McpBootOverlay
          state={mcpInit}
          onRetry={retryMcpInit}
          onDismiss={() => setMcpInitDismissed(true)}
        />
      )}
      {showOfflineBanner && (
        <div className="mcp-offline-banner" role="button" tabIndex={0}
             onClick={retryMcpInit}
             onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') retryMcpInit(); }}>
          <span className="mcp-offline-dot" />
          <span className="mcp-offline-text">
            <b>UE Editor 未连接</b> · 工具调用无法推送到 UE
            <span className="mcp-offline-hint">
              {mcpInit.error ? ` · ${mcpInit.error}` : ' · 启动 UE 后 ModelContextProtocol.StartServer 再点此重连'}
            </span>
          </span>
          <span className="mcp-offline-btn">重连 UE Editor</span>
        </div>
      )}
      <div className={`app${showOfflineBanner ? ' has-offline-banner' : ''}`}>
        <TopBar projectName="adore-data" jobName={`${scene} · ${mrqSubdir.split('/')[1] || 'v0_demo'}`}
          runStatus={runStatus} runtimeS={runtimeMs}
          mcpState={mcpInit} onMcpReconnect={retryMcpInit}
          onSyncFromUE={syncFromUE} onClearAll={clearAllFromUE}
          actorCount={spawnedActors.length}
          currentLevel={currentLevel} appVersion={appVersion}
          pcgStatus={pcgStatus} onRefreshPcg={refreshPcgStatus} />

        {/* LEFT: Chat */}
        <ChatPanel
          messages={messages}
          onSend={(t) => chatMode === 'free' ? freeChat(t) : runPipeline(t)}
          busy={runStatus !== 'idle' && runStatus !== 'done'}
          scene={scene}
          chatMode={chatMode}
          setChatMode={setChatMode}
        />

        {/* CENTER: Viewport + timeline */}
        <div className="center-wrap" style={{ gridArea: 'center' }}>
          <div className="viewport-hd">
            <div className="vp-title">
              <span style={{ fontFamily: 'var(--mono)', color: 'var(--text-3)', fontSize: 11 }}>VIEWPORT</span>
              <span>·</span>
              <span>{SCENES[scene].label}</span>
              <span className={`vp-pill ${generating ? 'gen' : 'live'}`}>
                {generating ? '◈ PCG generating' : runStatus === 'render' ? '◉ MRQ rendering' : '● live'}
              </span>
            </div>
            <span className="vp-spacer" />
            <span className="vp-pill">{params.resolution}</span>
            <div className="vp-mode">
              <button className="vp-mode-btn active">ISO</button>
              <button className="vp-mode-btn">PERSP</button>
              <button className="vp-mode-btn">TOP</button>
            </div>
            <a className="vp-mode-btn"
               href="/3d"
               target="_blank"
               rel="noopener"
               style={{ marginLeft: 6, textDecoration: 'none',
                        color: 'var(--accent)',
                        background: 'var(--accent-soft)',
                        border: '1px solid var(--accent-soft)',
                        fontWeight: 600,
                        display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              3D ↗
            </a>
          </div>
          <div className="viewport-stage">
            <div className="viewport-grid" />
            <Scene
              params={params}
              scene={scene}
              robot={robot}
              generating={generating}
              generateProgress={generating ? stageProgress : 1}
              seeded={sceneSeeded}
              spawnedActors={spawnedActors}
            />
            <div className="viewport-overlay">
              <div className="vp-stat"><span className="k">scene</span><span className="v">{scene}</span></div>
              <div className="vp-stat"><span className="k">robot</span><span className="v">{ROBOTS[robot].label}</span><span className="k">·</span><span className="v">{ROBOTS[robot].dof} DoF</span></div>
              <div className="vp-stat"><span className="k">room</span><span className="v">{params.room_w_m.toFixed(1)} × {params.room_l_m.toFixed(1)} × {params.ceiling_h_m.toFixed(1)} m</span></div>
            </div>
            <div className="viewport-overlay right">
              <div className="vp-stat">
                <span className="k">actors</span>
                <span className="v">{spawnedActors.length}</span>
                {spawnedActors.length > 0 && (() => {
                  const counts = spawnedActors.reduce((acc, a) => {
                    acc[a.asset_name] = (acc[a.asset_name] || 0) + 1;
                    return acc;
                  }, {});
                  const parts = Object.entries(counts).map(([k, v]) =>
                    `${k[0].toUpperCase()}${v}`).join(' · ');
                  return <><span className="k">·</span><span className="v" style={{fontSize: 10, opacity: 0.7}}>{parts}</span></>;
                })()}
              </div>
              <div className="vp-stat"><span className="k">tris</span><span className="v">~{Math.round((118 + params.shelf_density * 240 + params.forklift_count * 30) * 1000).toLocaleString()}</span></div>
              <div className="vp-stat"><span className="k">lumen</span><span className="v">on</span><span className="k">·</span><span className="v">path-tracer ready</span></div>
            </div>
            {/* Schematic vs live UE: left iso SVG is the schematic, this
                PIP is the actual editor viewport, refreshed on every spawn. */}
            <UEViewportPip cacheKey={ueShotKey} mcpReady={!!(mcpInit && mcpInit.done && mcpInit.ok)} />
          </div>
          <Timeline currentStage={runStatus} stageProgress={stageProgress} runtimeS={runtimeMs} />
        </div>

        {/* RIGHT: Parameters / Tool Calls / Render */}
        <div className="panel right" style={{ gridArea: 'right' }}>
          {rightTabs}
          <div className="panel-body">
            {rightTab === 'params' && (
              <ParametersPanel
                params={params}
                setParam={(k, v) => updateParam(k, v, false)}
                flashKey={flashKey} />
            )}
            {rightTab === 'toolcalls' && (
              <ToolCallsPanel toolCalls={toolCalls} />
            )}
            {rightTab === 'render' && (
              <RenderPanel
                params={params}
                frameCount={params.frame_count}
                currentFrame={currentFrame}
                renderActive={runStatus === 'render'}
                mrqJobs={{ subdir: mrqSubdir }}
              />
            )}
          </div>
        </div>

        <StatusBar runStatus={runStatus} runtimeS={runtimeMs} params={params} dataset={dataset} />
      </div>

      <TweaksPanel>
        <TweakSection label="Scene & Robot" />
        <TweakRadio label="场景"
          value={tweaks.scene}
          options={['warehouse', 'livingroom', 'factory']}
          onChange={(v) => setTweak('scene', v)} />
        <TweakSelect label="机器人"
          value={tweaks.robot}
          options={[
            { value: 'franka_panda', label: 'FRANKA Panda (7-DoF arm)' },
            { value: 'unitree_h1', label: 'Unitree H1 (humanoid)' },
            { value: 'ur5', label: 'UR5 (6-DoF arm)' },
          ]}
          onChange={(v) => setTweak('robot', v)} />
      </TweaksPanel>
    </>
  );
}

// ─── Real LLM call to /api/chat ─────────────────────────────────────────────
// Returns design-compatible {narrate, calls[]} shape so the rest of the
// pipeline code (animation, side-effects) keeps working. Backend returns a
// single update_scene tool_call; we expand its pcg_params into per-key
// actions for visual continuity with the design's tool_call stream.
async function callRealChat(userText, scene, currentParams) {
  const r = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text: userText,
      mode: 'scene',
      current_spec: { scene_id: scene, pcg_params: currentParams },
    }),
  });
  const data = await r.json();
  if (!data.ok) {
    throw new Error(data.error || 'chat failed');
  }
  const tc = data.tool_call;
  if (!tc) {
    return { narrate: data.text || '(模型未返回工具调用)', calls: [] };
  }
  const args = tc.arguments || {};
  const relay = data.mcp_relay;

  let calls = [];
  let toolNarrate = '';

  if (tc.name === 'update_scene') {
    const pcgParams = args.pcg_params || {};
    if (args.scene_id && args.scene_id !== scene) {
      calls.push({ name: 'load_scene', args: { scene: args.scene_id } });
    }
    for (const [k, v] of Object.entries(pcgParams)) {
      calls.push({ name: `set_${k}`, args: { value: v } });
    }
    if (calls.length === 0) calls.push({ name: 'no_op', args: {} });
    else calls.push({ name: 'trigger_generate', args: {} });
    toolNarrate = args.rationale || '(PCG 参数更新)';
  } else if (tc.name === 'spawn_object') {
    calls.push({ name: 'spawn_object', args });
    toolNarrate = `在 (${args.x}, ${args.y}) 放了一个 ${args.asset_name}`;
  } else if (tc.name === 'delete_object') {
    calls.push({ name: 'delete_object', args });
    toolNarrate = `删除 ${args.actor_handle}`;
  } else if (tc.name === 'modify_location') {
    calls.push({ name: 'modify_location', args });
    toolNarrate = `${args.actor_handle} 挪到 (${args.x}, ${args.y})`;
  } else if (tc.name === 'nudge_object') {
    calls.push({ name: 'nudge_object', args });
    const dx = args.dx ?? 0, dy = args.dy ?? 0;
    const parts = [];
    if (dx) parts.push(`${dx > 0 ? '+' : ''}${dx}m X`);
    if (dy) parts.push(`${dy > 0 ? '+' : ''}${dy}m Y`);
    toolNarrate = `${args.actor_handle} ${parts.join(' / ') || '0'}`;
  } else if (tc.name === 'list_objects') {
    calls.push({ name: 'list_objects', args: {} });
    toolNarrate = '列出当前 actor';
  } else if (tc.name === 'spawn_batch') {
    const items = Array.isArray(args.items) ? args.items : [];
    items.forEach((it, idx) => calls.push({ name: `spawn ${idx + 1}`, args: it }));
    toolNarrate = `批量 spawn ${items.length} 个物件`;
  } else if (tc.name === 'generate_warehouse_layout') {
    calls.push({ name: 'generate_warehouse_layout', args });
    toolNarrate = '生成仓库布局';
  } else if (tc.name === 'clear_demo_objects') {
    calls.push({ name: 'clear_demo_objects', args: {} });
    toolNarrate = '清空场景';
  } else {
    calls.push({ name: tc.name, args });
    toolNarrate = `(执行) ${tc.name}`;
  }

  // MCP relay status — synthesise a useful summary per tool family.
  let relayLine = '';
  if (relay) {
    if (relay.ok) {
      let target = relay.tool || '';
      const res = relay.result || {};
      if (relay.tool === 'spawn_object' && res.actor_handle) target = `spawn → ${res.actor_handle}`;
      else if (relay.tool === 'delete_object' && res.deleted) target = `delete ${res.deleted}`;
      else if (relay.tool === 'modify_location' && res.actor_handle) target = `move ${res.actor_handle}`;
      else if (relay.tool === 'nudge_object' && res.actor_handle) target = `nudge ${res.actor_handle}`;
      else if (relay.tool === 'list_objects' && Array.isArray(res.objects)) target = `${res.objects.length} actors`;
      else if (relay.tool === 'spawn_batch' && res.total) target = `batch · ${res.total} actors`;
      else if (relay.tool === 'generate_warehouse_layout' && res.total) target = `layout · ${res.total} actors`;
      else if (relay.tool === 'clear_demo_objects' && res.cleared !== undefined) target = `cleared ${res.cleared}`;
      else if (!relay.tool && relay.pcg_component) target = (relay.pcg_component.split('.').pop() || 'PCG');
      relayLine = `  ·  ✓ MCP → UE: ${target}`;
      if (res.error) relayLine = `  ·  ✗ MCP → UE: ${res.error}`;
    } else if (relay.skipped) {
      relayLine = `  ·  ◌ MCP skipped (${relay.reason})`;
    } else {
      relayLine = `  ·  ✗ MCP error: ${relay.reason}`;
    }
  }
  const narrate = `${toolNarrate}  ·  ${data.provider}/${data.model} · ${data.elapsed_ms}ms${relayLine}`;
  return { narrate, calls, relayMeta: relay };
}

// ─── SSE stream for /api/demo/generate_warehouse_stream ────────────────────
// EventSource only supports GET; we POST + manually parse the text/event-stream
// body. Block-by-block: events are separated by "\n\n", lines inside an event
// are "event: <name>" / "data: <json>".
async function runWarehouseStream(args, cb) {
  let resp;
  try {
    resp = await fetch('/api/demo/generate_warehouse_stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(args || {}),
    });
  } catch (err) {
    cb.onError && cb.onError({ message: `network: ${err.message}` });
    return;
  }
  if (!resp.ok || !resp.body) {
    cb.onError && cb.onError({ message: `stream HTTP ${resp.status}` });
    return;
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buf = '';
  while (true) {
    let chunk;
    try {
      chunk = await reader.read();
    } catch (err) {
      cb.onError && cb.onError({ message: `read: ${err.message}` });
      return;
    }
    if (chunk.done) break;
    buf += decoder.decode(chunk.value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = 'message';
      const dataLines = [];
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) continue;
      let data;
      try { data = JSON.parse(dataLines.join('\n')); }
      catch { continue; }
      if (event === 'plan')    cb.onPlan    && cb.onPlan(data);
      else if (event === 'spawn')   cb.onSpawn   && cb.onSpawn(data);
      else if (event === 'done')    cb.onDone    && cb.onDone(data);
      else if (event === 'summary') cb.onSummary && cb.onSummary(data);
      else if (event === 'error')   cb.onError   && cb.onError(data);
    }
  }
}

// ─── Helpers ────────────────────────────────────────────────────────────────
function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

async function animateProgress(setter, ms) {
  const start = performance.now();
  while (performance.now() - start < ms) {
    const t = Math.min(1, (performance.now() - start) / ms);
    setter(t);
    await sleep(50);
  }
  setter(1);
}

function applyToolCallSideEffects(tc, { updateParam, setTweak, setMrqSubdir, setRightTab }) {
  const { name, args } = tc;
  if (name === 'load_scene') {
    if (args.scene) setTweak('scene', args.scene);
    return;
  }
  if (name === 'spawn_robot') {
    const r = args.urdf || args.robot;
    if (r === 'franka_panda' || r === 'unitree_h1' || r === 'ur5') setTweak('robot', r);
    return;
  }
  if (name === 'trigger_generate') {
    // no-op; handled by stage transition
    return;
  }
  if (name === 'trigger_mrq_render') {
    if (args.subdir) setMrqSubdir(args.subdir);
    return;
  }
  // set_<key>(value)
  const key = toolCallToParamKey(name);
  if (key) {
    const val = args.value !== undefined ? args.value : args[key];
    if (val !== undefined) updateParam(key, val, true);
  }
}

// ─── Render ─────────────────────────────────────────────────────────────────
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
