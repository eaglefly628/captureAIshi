// panels.jsx — TopBar, Status bar, Composer, Chat, Params, Timeline, Tool calls, Render panel

const { useState, useEffect, useRef } = React;

// ─── Top bar ─────────────────────────────────────────────────────────────────
function TopBar({ projectName, jobName, runStatus, runtimeS, mcpState, onMcpReconnect, onSyncFromUE, onClearAll, actorCount = 0 }) {
  const connecting = mcpState && mcpState.started && !mcpState.done;
  const ok = mcpState && mcpState.done && mcpState.ok === true;
  const err = mcpState && mcpState.done && mcpState.ok === false;
  let dotColor = 'var(--text-3)';
  let label = '— offline';
  let title = 'UE MCP 未初始化';
  if (connecting) {
    dotColor = '#f5b942';
    label = '· connecting';
    title = `挂载工具集 ${mcpState.current}/${mcpState.total}`;
  } else if (ok) {
    dotColor = 'var(--ok)';
    label = '● connected';
    title = `UE MCP 在线 · ${((mcpState.elapsed_ms || 0) / 1000).toFixed(1)}s`;
  } else if (err) {
    dotColor = '#ff6b6b';
    label = '● disconnected';
    title = mcpState.error || 'MCP 连接失败 — 点击重连';
  }
  return (
    <div className="topbar">
      <div className="brand">
        <div className="brand-mark">A</div>
        <div className="brand-name">ADORE</div>
      </div>
      <div className="crumb">
        <span>{projectName}</span>
        <span className="sep">/</span>
        <span className="active">{jobName}</span>
      </div>
      <div className="topbar-spacer" />
      {onSyncFromUE && (
        <button className="top-btn" title="从 UE Editor 重读 Demo/v0 actor 列表"
                onClick={onSyncFromUE}>
          <span style={{opacity: 0.6}}>SYNC</span>
          <span style={{fontFamily: 'var(--mono)', fontSize: 11}}>↻ {actorCount}</span>
        </button>
      )}
      {onClearAll && actorCount > 0 && (
        <button className="top-btn" title="删除所有 demo actor"
                onClick={onClearAll}
                style={{color: '#ff8080'}}>
          <span style={{opacity: 0.8}}>CLEAR</span>
        </button>
      )}
      <button className="top-btn" title={title} onClick={onMcpReconnect}>
        <span style={{opacity: 0.6}}>UE5.8</span>
        <span style={{ color: dotColor }}>{label}</span>
      </button>
      <button className="top-btn" title="点击重连 UE MCP" onClick={onMcpReconnect}>
        <span style={{opacity: 0.6}}>MCP</span>
        <span style={{fontFamily: 'var(--mono)', fontSize: 11, color: err ? '#ff6b6b' : 'inherit'}}>
          {err ? '重连' : ':8000'}
        </span>
      </button>
      <button className="top-btn">⌘K</button>
    </div>
  );
}

// ─── Status bar (bottom) ────────────────────────────────────────────────────
function StatusBar({ runStatus, runtimeS, params, dataset }) {
  const isBusy = runStatus !== 'idle' && runStatus !== 'done';
  return (
    <div className="statusbar">
      <span className="group">
        <span className={`dot ${runStatus === 'idle' ? 'idle' : isBusy ? 'busy' : ''}`} />
        <span style={{ color: 'var(--text-2)' }}>{
          runStatus === 'idle' ? 'idle'
          : runStatus === 'done' ? 'ready'
          : runStatus
        }</span>
      </span>
      <span style={{ color: 'var(--text-4)' }}>·</span>
      <span className="group">
        <span>seed</span><span style={{ color: 'var(--text-2)' }}>{params.seed}</span>
      </span>
      <span className="group">
        <span>res</span><span style={{ color: 'var(--text-2)' }}>{params.resolution}</span>
      </span>
      <span className="group">
        <span>frames</span><span style={{ color: 'var(--text-2)' }}>{params.frame_count}@{params.fps}fps</span>
      </span>
      <span className="spacer" />
      <span className="group">
        <span>runtime</span><span style={{ color: 'var(--text-2)' }}>{(runtimeS / 1000).toFixed(1)}s</span>
      </span>
      {dataset && (
        <>
          <span style={{ color: 'var(--text-4)' }}>·</span>
          <span className="group" style={{ color: 'var(--ok)' }}>● dataset ready · {dataset.size}</span>
        </>
      )}
      <span style={{ color: 'var(--text-4)' }}>·</span>
      <span>v0.3.3</span>
    </div>
  );
}

// ─── Chat / Composer ─────────────────────────────────────────────────────────
const FREE_SUGGESTIONS = [
  '你是什么模型',
  '5 + 3 等于多少?',
  '介绍一下 PCG 是什么',
  '总结一下这个项目能干嘛',
];

function ChatPanel({ messages, onSend, busy, scene, chatMode, setChatMode }) {
  const [text, setText] = useState('');
  const historyRef = useRef(null);

  useEffect(() => {
    if (historyRef.current) {
      historyRef.current.scrollTop = historyRef.current.scrollHeight;
    }
  }, [messages]);

  const submit = () => {
    if (!text.trim() || busy) return;
    onSend(text.trim());
    setText('');
  };

  const onKey = (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey || !e.shiftKey)) {
      e.preventDefault();
      submit();
    }
  };

  const isFree = chatMode === 'free';
  const suggs = isFree ? FREE_SUGGESTIONS : (SUGGESTIONS[scene] || SUGGESTIONS.warehouse);

  return (
    <div className="panel chat">
      <div className="panel-hd">
        <div className="tab active">
          <span>Console</span>
          <span className="count">{messages.length}</span>
        </div>
        <div className="vp-mode" style={{ marginLeft: 4 }}>
          <button className={`vp-mode-btn ${!isFree ? 'active' : ''}`}
                  onClick={() => setChatMode && setChatMode('scene')}>场景</button>
          <button className={`vp-mode-btn ${isFree ? 'active' : ''}`}
                  onClick={() => setChatMode && setChatMode('free')}>自由</button>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--text-4)', fontFamily: 'var(--mono)' }}>
          job_4271
        </div>
      </div>
      <div className="chat-history" ref={historyRef}>
        {messages.length === 0 ? (
          <div className="empty">
            <div className="em-title">{isFree ? '自由聊天' : '还没有任务'}</div>
            {isFree ? (
              <>
                <div>裸调 LLM, 无 system prompt 无 tool.</div>
                <div>用来验真模型 / 闲聊.</div>
              </>
            ) : (
              <>
                <div>用自然语言描述一个场景，</div>
                <div>系统会调 PCG + MRQ 出图。</div>
              </>
            )}
          </div>
        ) : messages.map((m, i) => (
          <Msg key={i} m={m} />
        ))}
      </div>
      <div className="composer">
        <div className="composer-frame">
          <textarea
            placeholder={isFree
              ? '例: 你是什么模型? 用一句话介绍一下 DeepSeek'
              : '例如：warehouse 仓库, 货架满一点, 放 2 台叉车, FRANKA 摆抓箱姿势'}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
            disabled={busy}
          />
          <div className="composer-bar">
            <span className="model-chip"><b>DeepSeek</b>-V4-Flash</span>
            <span className="cost">~$0.0001/call</span>
            <span className="grow" />
            <span className="kbd">⌘↵</span>
            <button className="send-btn" onClick={submit} disabled={!text.trim() || busy} aria-label="Send">
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                <path d="M2.5 8L13.5 8M13.5 8L9 3.5M13.5 8L9 12.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        </div>
        <div className="suggestions">
          {suggs.map((s, i) => (
            <span key={i} className="sugg" onClick={() => !busy && onSend(s)}>{s}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

function Msg({ m }) {
  if (m.role === 'user') {
    return (
      <div className="msg user">
        <div className="msg-hd">
          <span className="role user">You</span>
          <span style={{ opacity: 0.6 }}>{m.ts || '—'}</span>
        </div>
        <div className="msg-body">{m.text}</div>
      </div>
    );
  }
  return (
    <div className="msg assistant">
      <div className="msg-hd">
        <span className="role assistant">ADORE</span>
        <span style={{ opacity: 0.6 }}>{m.ts || '—'}</span>
        {m.thinking && <span className="dot-loader"><span /><span /><span /></span>}
      </div>
      <div className="msg-body" style={{ whiteSpace: 'pre-wrap' }}>{m.text}</div>
      {m.meta && (
        <div style={{ fontSize: 10.5, color: 'var(--text-4)', fontFamily: 'var(--mono)', marginTop: 2 }}>
          {m.meta}
        </div>
      )}
      {m.actions && m.actions.length > 0 && (
        <div className="msg-actions">
          {m.actions.map((a, i) => (
            <ActionPill key={i} action={a} />
          ))}
        </div>
      )}
      {m.dataset && <DatasetCard d={m.dataset} />}
    </div>
  );
}

function ActionPill({ action }) {
  const { name, args, status } = action;
  const compactArgs = args && Object.keys(args).length > 0
    ? Object.entries(args).slice(0, 2).map(([k, v]) =>
        `${k}=${formatVal(v)}`).join(' ')
    : '';
  return (
    <div className={`action-pill ${status || ''}`}>
      <span className="action-name">{name}</span>
      <span className="action-args">{compactArgs}</span>
      <span className="action-status">
        {status === 'done' && <span>✓ done</span>}
        {status === 'running' && <span>running…</span>}
        {status === 'pending' && <span>queued</span>}
      </span>
    </div>
  );
}

function formatVal(v) {
  if (Array.isArray(v)) return `[${v.length}]`;
  if (typeof v === 'number') return Number.isInteger(v) ? v : v.toFixed(2);
  if (typeof v === 'string') return v;
  return JSON.stringify(v);
}

function DatasetCard({ d }) {
  return (
    <div className="dataset-card">
      <div className="dh">
        <div className="ico">✓</div>
        <div className="title">数据集已就绪</div>
        <div className="ts">{d.path}</div>
      </div>
      <div className="files">
        <div className="f"><span>📄</span><span>{d.parquet}</span><span className="sz">{d.parquetSize}</span></div>
        <div className="f"><span>🎞</span><span>{d.video}</span><span className="sz">{d.videoSize}</span></div>
        <div className="f"><span>🖼</span><span>{d.exrs} × EXR (5 layer)</span><span className="sz">{d.exrSize}</span></div>
        <div className="f"><span>📋</span><span>manifest.json</span><span className="sz">3 KB</span></div>
      </div>
    </div>
  );
}

// ─── Parameters panel ───────────────────────────────────────────────────────
function ParametersPanel({ params, setParam, flashKey }) {
  return (
    <div className="params">
      {PARAM_GROUPS.map(g => (
        <div className="params-group" key={g.id}>
          <div className="params-group-hd">
            <span>{g.label}</span>
            <span className="ix">· {g.params.length}</span>
          </div>
          <div className="params-group-body">
            {g.params.map(p => (
              <ParamRow key={p.key}
                spec={p}
                value={params[p.key]}
                onChange={(v) => setParam(p.key, v)}
                flashing={flashKey === p.key} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function ParamRow({ spec, value, onChange, flashing }) {
  if (spec.type === 'enum') {
    return (
      <div className={`param-row ${flashing ? 'flashing' : ''}`}>
        <div className="param-key">{spec.key}</div>
        <div className="param-enum">
          {spec.options.map(opt => (
            <span key={opt}
              className={`enum-chip ${value === opt ? 'active' : ''}`}
              onClick={() => onChange(opt)}>
              {opt}
            </span>
          ))}
        </div>
        <div className="param-val enum" style={{ visibility: 'hidden' }}>—</div>
      </div>
    );
  }

  const pct = ((value - spec.min) / (spec.max - spec.min)) * 100;
  const formatted = spec.integer ? Math.round(value) : Number(value).toFixed(2);

  return (
    <div className={`param-row ${flashing ? 'flashing' : ''}`}>
      <div className="param-key">{spec.key}</div>
      <div className="param-slider" style={{ '--pct': `${pct}%` }}>
        <div className="track"><div className="fill" /></div>
        <input type="range"
          min={spec.min} max={spec.max} step={spec.step}
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))} />
      </div>
      <div className="param-val">
        {formatted}{spec.unit && <span style={{ color: 'var(--text-4)', marginLeft: 2 }}>{spec.unit}</span>}
      </div>
    </div>
  );
}

// ─── Timeline (below viewport) ──────────────────────────────────────────────
function Timeline({ currentStage, stageProgress, runtimeS }) {
  const stages = PIPELINE_STAGES;
  const currentIdx = stages.findIndex(s => s.id === currentStage);

  let displayStage = '空闲';
  let etaText = '—';
  if (currentStage === 'parse') { displayStage = '解析自然语言 → tool calls'; etaText = 'eta ~2s'; }
  else if (currentStage === 'dispatch') { displayStage = '调度 tool calls 到 UE MCP'; etaText = 'eta ~0.5s'; }
  else if (currentStage === 'generate') { displayStage = 'PCG · BSP → 货架 → 叉车 → 灯'; etaText = 'eta ~5s'; }
  else if (currentStage === 'render') { displayStage = 'MRQ · multi-layer EXR'; etaText = 'eta ~15min'; }
  else if (currentStage === 'package') { displayStage = 'Cosmos photoreal + LeRobot parquet'; etaText = 'eta ~30s'; }
  else if (currentStage === 'done') { displayStage = '完成，数据集已导出'; etaText = '✓'; }

  return (
    <div className="timeline">
      <div className="timeline-hd">
        <span className="tl-label">PIPELINE</span>
        <span className="tl-stage">{displayStage}</span>
        <span className="tl-eta"><b>{(runtimeS / 1000).toFixed(1)}s</b> · {etaText}</span>
      </div>
      <div className="timeline-body">
        {stages.map((st, i) => {
          const isActive = i === currentIdx;
          const isDone = currentStage === 'done' || (currentIdx >= 0 && i < currentIdx);
          const fillPct = isActive ? Math.round(stageProgress * 100) : (isDone ? 100 : 0);
          return (
            <div key={st.id} className={`tl-step ${isActive ? 'active' : ''} ${isDone ? 'done' : ''}`}>
              <div className="t">{st.t}</div>
              <div className="name">
                <span className="icon">{isDone ? '✓' : st.icon}</span>
                <span>{st.name}</span>
              </div>
              <div className="sub">{st.sub}</div>
              <div className="bar"><div className="fill" style={{ width: `${fillPct}%` }} /></div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Tool calls panel ───────────────────────────────────────────────────────
function ToolCallsPanel({ toolCalls }) {
  if (!toolCalls || toolCalls.length === 0) {
    return (
      <div className="empty">
        <div className="em-title">未触发</div>
        <div>LLM 还没有发出 tool_call。</div>
      </div>
    );
  }
  return (
    <div className="toolcalls">
      {toolCalls.map((tc, i) => (
        <div key={i} className={`tc ${tc.status || ''}`}>
          <div className="tc-hd">
            <span className="tc-idx">#{String(i + 1).padStart(2, '0')}</span>
            <span className="tc-name">{tc.name}</span>
            <span className="tc-status">{
              tc.status === 'done' ? '✓ 200 OK'
              : tc.status === 'running' ? 'POST →'
              : '· queued'
            }</span>
          </div>
          <div className="tc-body">{renderArgs(tc.args)}</div>
        </div>
      ))}
    </div>
  );
}

function renderArgs(args) {
  if (!args || Object.keys(args).length === 0) {
    return <span className="p">{'{}'}</span>;
  }
  return (
    <>
      <span className="p">{'{ '}</span>
      {Object.entries(args).map(([k, v], i, arr) => (
        <span key={k}>
          <span className="k">{k}</span>
          <span className="p">: </span>
          {typeof v === 'string'
            ? <span className="s">"{v}"</span>
            : typeof v === 'number'
            ? <span className="n">{v}</span>
            : Array.isArray(v)
            ? <span className="n">[{v.map(x => typeof x === 'number' ? x.toFixed(2) : x).join(', ')}]</span>
            : <span className="n">{JSON.stringify(v)}</span>}
          {i < arr.length - 1 && <span className="p">, </span>}
        </span>
      ))}
      <span className="p">{' }'}</span>
    </>
  );
}

// ─── Render layers panel ────────────────────────────────────────────────────
function RenderPanel({ params, frameCount, currentFrame, renderActive, mrqJobs }) {
  return (
    <div className="render-panel">
      <div className="render-meta">
        <div className="cell">
          <div className="k">Preset</div>
          <div className="v">MRQ_MultiPassEXR</div>
        </div>
        <div className="cell">
          <div className="k">Output</div>
          <div className="v">{mrqJobs.subdir}/</div>
        </div>
        <div className="cell">
          <div className="k">Resolution</div>
          <div className="v">{params.resolution}</div>
        </div>
        <div className="cell">
          <div className="k">Progress</div>
          <div className="v" style={{ color: renderActive ? 'var(--accent)' : 'var(--text)' }}>
            {currentFrame}/{frameCount} · {((currentFrame / frameCount) * 100).toFixed(0)}%
          </div>
        </div>
      </div>

      <div>
        <div style={{ fontSize: 10.5, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600, marginBottom: 6 }}>
          AOV Layers
        </div>
        <div className="layer-grid">
          {RENDER_LAYERS.map(L => (
            <LayerTile key={L.key} layer={L} active={renderActive} frame={currentFrame} />
          ))}
        </div>
      </div>

      <div>
        <div style={{ fontSize: 10.5, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600, marginBottom: 6 }}>
          Frames · {frameCount}f
        </div>
        <div className="frame-strip">
          {Array.from({ length: frameCount }).map((_, i) => (
            <div key={i} className={`frame ${i < currentFrame ? 'done' : ''} ${i === currentFrame - 1 ? 'current' : ''}`}>
              <span>{String(i + 1).padStart(4, '0')}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function LayerTile({ layer, active, frame }) {
  // Synthesize a tiny preview SVG specific to the AOV kind.
  // Mock previews always rendered so the gallery is never empty.
  const previews = {
    final: <FinalPreview />,
    normal: <NormalPreview />,
    depth: <DepthPreview />,
    objid: <ObjIdPreview />,
    gbuffer: <GBufferPreview />,
  };
  const hasFrames = frame > 0;
  return (
    <div className={`layer-tile ${active ? 'rendering' : ''}`}>
      <div className="lt-thumb" style={{ background: 'transparent' }}>
        {previews[layer.key]}
        {active && <div className="scanline" />}
      </div>
      <div className="lt-meta">
        <span className="name">
          <span className="swatch" style={{ background: layer.color }} />
          {layer.name}
        </span>
        <span className="sz">{hasFrames ? `EXR16 · ${frame}f` : 'EXR16 · preview'}</span>
      </div>
    </div>
  );
}

// Tiny synthesized AOV previews
function FinalPreview() {
  return (
    <svg viewBox="0 0 160 90" preserveAspectRatio="none" width="100%" height="100%">
      <defs>
        <linearGradient id="fp-floor" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor="#E8D9A8" />
          <stop offset="1" stopColor="#FAF3DC" />
        </linearGradient>
      </defs>
      <rect width="160" height="90" fill="url(#fp-floor)" />
      <polygon points="0,75 160,75 160,90 0,90" fill="#C8B47A" />
      <rect x="15" y="40" width="22" height="35" fill="#A8915E" stroke="#6E5E48" strokeWidth="0.5" />
      <rect x="42" y="38" width="22" height="37" fill="#B59E80" stroke="#6E5E48" strokeWidth="0.5" />
      <rect x="100" y="40" width="22" height="35" fill="#A8915E" stroke="#6E5E48" strokeWidth="0.5" />
      <rect x="125" y="38" width="22" height="37" fill="#B59E80" stroke="#6E5E48" strokeWidth="0.5" />
      <rect x="74" y="50" width="12" height="25" fill="#2F3845" />
      <circle cx="80" cy="48" r="2" fill="#5b8af0" />
    </svg>
  );
}
function NormalPreview() {
  return (
    <svg viewBox="0 0 160 90" preserveAspectRatio="none" width="100%" height="100%">
      <rect width="160" height="90" fill="#7E84D8" />
      <polygon points="0,75 160,75 160,90 0,90" fill="#8B92E8" />
      <rect x="15" y="40" width="22" height="35" fill="#D87E84" />
      <rect x="42" y="38" width="22" height="37" fill="#5587E8" />
      <rect x="100" y="40" width="22" height="35" fill="#D87E84" />
      <rect x="125" y="38" width="22" height="37" fill="#5587E8" />
      <rect x="74" y="50" width="12" height="25" fill="#7E84D8" />
    </svg>
  );
}
function DepthPreview() {
  return (
    <svg viewBox="0 0 160 90" preserveAspectRatio="none" width="100%" height="100%">
      <defs>
        <linearGradient id="dp" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#FFFFFF" />
          <stop offset="1" stopColor="#0A1018" />
        </linearGradient>
      </defs>
      <rect width="160" height="90" fill="url(#dp)" />
      <rect x="15" y="40" width="22" height="35" fill="#3A4654" />
      <rect x="42" y="38" width="22" height="37" fill="#525E6C" />
      <rect x="100" y="40" width="22" height="35" fill="#7C8696" />
      <rect x="125" y="38" width="22" height="37" fill="#929BAA" />
      <rect x="74" y="50" width="12" height="25" fill="#262C36" />
    </svg>
  );
}
function ObjIdPreview() {
  return (
    <svg viewBox="0 0 160 90" preserveAspectRatio="none" width="100%" height="100%">
      <rect width="160" height="90" fill="#22272F" />
      <polygon points="0,75 160,75 160,90 0,90" fill="#3D4452" />
      <rect x="15" y="40" width="22" height="35" fill="#E84A6F" />
      <rect x="42" y="38" width="22" height="37" fill="#E84A6F" />
      <rect x="100" y="40" width="22" height="35" fill="#FFB347" />
      <rect x="125" y="38" width="22" height="37" fill="#FFB347" />
      <rect x="74" y="50" width="12" height="25" fill="#5BE89A" />
      <rect x="78" y="46" width="3" height="3" fill="#5b8af0" />
    </svg>
  );
}
function GBufferPreview() {
  return (
    <svg viewBox="0 0 160 90" preserveAspectRatio="none" width="100%" height="100%">
      <rect width="160" height="90" fill="#383E48" />
      <polygon points="0,75 160,75 160,90 0,90" fill="#5A6470" />
      <rect x="15" y="40" width="22" height="35" fill="#888" />
      <rect x="42" y="38" width="22" height="37" fill="#9C9C9C" />
      <rect x="100" y="40" width="22" height="35" fill="#7B7B7B" />
      <rect x="125" y="38" width="22" height="37" fill="#8C8C8C" />
      <rect x="74" y="50" width="12" height="25" fill="#5B5B5B" />
    </svg>
  );
}

// ─── Exports ────────────────────────────────────────────────────────────────
Object.assign(window, {
  TopBar, StatusBar, ChatPanel, Msg, ActionPill, DatasetCard,
  ParametersPanel, ParamRow,
  Timeline, ToolCallsPanel, renderArgs, RenderPanel,
});
