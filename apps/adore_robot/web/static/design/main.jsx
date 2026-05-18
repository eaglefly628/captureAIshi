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

  const busyRef = useRef(false);
  const animFrameRef = useRef(null);

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

      await sleep(220 + Math.random() * 120);

      // mark done
      setToolCalls(prev => prev.map((c, idx) => idx === i ? { ...c, status: 'done' } : c));
      setMessages(prev => prev.map((m, mi) => mi === assistantIdx
        ? { ...m, actions: m.actions.map((a, ai) => ai === i ? { ...a, status: 'done' } : a) }
        : m));

      setStageProgress((i + 1) / callTotal);
    }

    // GENERATE stage
    setRunStatus('generate');
    setStageProgress(0);
    // auto-switch right tab to viewport-relevant params (already there) — but show generation through scene anim
    await animateProgress(setStageProgress, STAGE_DURATIONS.generate);

    // Only render if a trigger_mrq_render was in the calls
    const willRender = resp.calls.some(c => c.name === 'trigger_mrq_render');

    if (willRender) {
      // RENDER stage
      setRunStatus('render');
      setStageProgress(0);
      setRightTab('render');
      const frameCount = params.frame_count;
      const dur = STAGE_DURATIONS.render;
      const startR = performance.now();
      while (performance.now() - startR < dur) {
        const t = Math.min(1, (performance.now() - startR) / dur);
        setStageProgress(t);
        setCurrentFrame(Math.round(t * frameCount));
        await sleep(80);
      }
      setStageProgress(1);
      setCurrentFrame(frameCount);

      // PACKAGE stage
      setRunStatus('package');
      setStageProgress(0);
      await animateProgress(setStageProgress, STAGE_DURATIONS.package);

      // DONE
      const subdir = (resp.calls.find(c => c.name === 'trigger_mrq_render') || {}).args?.subdir || 'warehouse/v0_demo';
      const ds = {
        path: subdir,
        parquet: `${subdir.replace('/', '_')}.parquet`,
        parquetSize: '184 KB',
        video: `${subdir.replace('/', '_')}.mp4`,
        videoSize: '12.4 MB',
        exrs: frameCount,
        exrSize: `${(frameCount * 8.2).toFixed(1)} MB`,
        size: `${(frameCount * 8.2 + 12.4 + 0.18).toFixed(1)} MB`,
      };
      setDataset(ds);
      setMessages(prev => prev.map((m, i) => i === assistantIdx
        ? { ...m, dataset: ds }
        : m));
      setRunStatus('done');
    } else {
      // No render — just done
      setRunStatus('done');
    }

    setStageProgress(1);
    cancelAnimationFrame(animFrameRef.current);
    busyRef.current = false;
  }, [scene, params.frame_count, setTweak, updateParam]);

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

  return (
    <>
      <div className="app">
        <TopBar projectName="adore-data" jobName={`${scene} · ${mrqSubdir.split('/')[1] || 'v0_demo'}`}
          runStatus={runStatus} runtimeS={runtimeMs} />

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
            />
            <div className="viewport-overlay">
              <div className="vp-stat"><span className="k">scene</span><span className="v">{scene}</span></div>
              <div className="vp-stat"><span className="k">robot</span><span className="v">{ROBOTS[robot].label}</span><span className="k">·</span><span className="v">{ROBOTS[robot].dof} DoF</span></div>
              <div className="vp-stat"><span className="k">room</span><span className="v">{params.room_w_m.toFixed(1)} × {params.room_l_m.toFixed(1)} × {params.ceiling_h_m.toFixed(1)} m</span></div>
            </div>
            <div className="viewport-overlay right">
              <div className="vp-stat"><span className="k">tris</span><span className="v">~{Math.round((118 + params.shelf_density * 240 + params.forklift_count * 30) * 1000).toLocaleString()}</span></div>
              <div className="vp-stat"><span className="k">lumen</span><span className="v">on</span><span className="k">·</span><span className="v">path-tracer ready</span></div>
            </div>
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
  const pcgParams = args.pcg_params || {};
  const rationale = args.rationale || '';

  // Expand per-param into individual set_<key> calls so the timeline shows N steps
  const calls = [];
  if (args.scene_id && args.scene_id !== scene) {
    calls.push({ name: 'load_scene', args: { scene: args.scene_id } });
  }
  for (const [k, v] of Object.entries(pcgParams)) {
    calls.push({ name: `set_${k}`, args: { value: v } });
  }
  if (calls.length === 0) {
    calls.push({ name: 'no_op', args: {} });
  } else {
    calls.push({ name: 'trigger_generate', args: {} });
  }

  const narrate = `${rationale}  ·  ${data.provider}/${data.model} · ${data.elapsed_ms}ms`;
  return { narrate, calls };
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
