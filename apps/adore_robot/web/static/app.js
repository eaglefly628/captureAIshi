import { SceneStage } from './scene3d.js';

const PARAM_DEF = {
  warehouse: [
    { key: 'shelf_density', type: 'range', min: 0.2, max: 1.0, step: 0.05 },
    { key: 'alley_width_m', type: 'range', min: 1.5, max: 4.0, step: 0.1 },
    { key: 'forklift_count', type: 'range', min: 0, max: 5, step: 1 },
    { key: 'prop_variety', type: 'range', min: 1, max: 5, step: 1 },
    { key: 'pallet_load_factor', type: 'range', min: 0, max: 1, step: 0.05 },
    { key: 'lighting_preset', type: 'enum',
      options: ['warehouse_sodium', 'cool_white', 'mixed'] },
    { key: 'seed', type: 'number', min: 0, max: 99999, step: 1 },
  ],
  living_room: [
    { key: 'furniture_density', type: 'range', min: 0.3, max: 0.9, step: 0.05 },
    { key: 'sofa_style', type: 'enum',
      options: ['sectional', 'loveseat', 'chesterfield'] },
    { key: 'decor_variety', type: 'range', min: 2, max: 8, step: 1 },
    { key: 'clutter_level', type: 'range', min: 0, max: 1, step: 0.05 },
    { key: 'rug_present', type: 'bool' },
    { key: 'lighting_preset', type: 'enum',
      options: ['indoor_tungsten', 'cool_daylight', 'evening_warm'] },
    { key: 'seed', type: 'number', min: 0, max: 99999, step: 1 },
  ],
  industrial_corner: [
    { key: 'machine_count', type: 'range', min: 1, max: 4, step: 1 },
    { key: 'toolboard_density', type: 'range', min: 0.3, max: 1.0, step: 0.05 },
    { key: 'pipe_complexity', type: 'range', min: 1, max: 5, step: 1 },
    { key: 'oil_stain_amount', type: 'range', min: 0, max: 0.8, step: 0.05 },
    { key: 'crate_count', type: 'range', min: 0, max: 6, step: 1 },
    { key: 'lighting_preset', type: 'enum',
      options: ['indoor_tungsten', 'halogen_spot', 'mixed'] },
    { key: 'seed', type: 'number', min: 0, max: 99999, step: 1 },
  ],
};

const SCENE_LABEL = {
  warehouse: '仓储 Warehouse',
  living_room: '客厅 Living Room',
  industrial_corner: '工业一角 Industrial Corner',
};

const PARAM_LABEL = {
  shelf_density: '货架密度',
  alley_width_m: '主通道宽度(m)',
  forklift_count: '叉车数量',
  prop_variety: '货物种类',
  pallet_load_factor: '托盘载货率',
  lighting_preset: '灯光预设',
  seed: '随机种子',
  furniture_density: '家具密度',
  sofa_style: '沙发风格',
  decor_variety: '装饰种类',
  clutter_level: '杂物程度',
  rug_present: '是否铺地毯',
  machine_count: '机器数量',
  toolboard_density: '工具墙密度',
  pipe_complexity: '管道复杂度',
  oil_stain_amount: '油渍覆盖',
  crate_count: '工具箱数',
};

const state = {
  sceneType: 'warehouse',
  params: {},
  jobs: new Map(),
  activeStreams: new Set(),
  stage: null,
  chatMode: 'scene',
  freeHistory: [],
};

const SUGGESTIONS_BY_MODE = {
  scene: ['货架密一点', '加两台叉车', '切冷色调灯光', '货物种类多些'],
  free:  ['你是什么模型', '5+3=?', '介绍一下 PCG 是什么', '总结这个项目能做什么'],
};

const boot = window.__BOOT__ || { scenes: {}, llm_provider: 'keyword' };

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }
function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k === 'onclick') e.addEventListener('click', v);
    else if (k === 'oninput') e.addEventListener('input', v);
    else if (k === 'onchange') e.addEventListener('change', v);
    else if (k === 'innerHTML') e.innerHTML = v;
    else e.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null) continue;
    e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return e;
}

function init() {
  const canvas = $('#viewport');
  state.stage = new SceneStage(canvas);

  renderSceneList();
  selectScene('warehouse');

  $('#chat-send').addEventListener('click', sendChat);
  $('#chat-text').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendChat();
    }
  });
  $$('.mode-btn').forEach(b => b.addEventListener('click', () => switchChatMode(b.dataset.mode)));
  renderSuggestions();
  $('#btn-batch').addEventListener('click', () => submitBatch(5));
  $('#btn-clear').addEventListener('click', clearGallery);
}

function renderSceneList() {
  const root = $('#scene-list');
  root.innerHTML = '';
  for (const [stype, cfg] of Object.entries(boot.scenes)) {
    const sizeStr = (cfg.size_m || []).slice(0, 2).join('×') + 'm';
    const card = el('div', {
      class: 'scene-card' + (stype === state.sceneType ? ' active' : ''),
      onclick: () => selectScene(stype),
    },
      el('div', { class: 'name' }, SCENE_LABEL[stype] || stype),
      el('div', { class: 'meta' }, `${sizeStr} · ${cfg.algorithm || 'pcg'} · ${(cfg.asset_packs || []).join(',')}`)
    );
    root.appendChild(card);
  }
}

function selectScene(stype) {
  state.sceneType = stype;
  state.params = JSON.parse(JSON.stringify((boot.scenes[stype] || {}).pcg_params || {}));
  renderSceneList();
  renderParams();
  rebuildStage();
  $('#active-scene-name').textContent = SCENE_LABEL[stype] || stype;
  $('#ov-scene').textContent = stype;
  setTimeout(() => state.stage.flyThumbnailCamera(boot.scenes[stype]), 200);
}

function renderParams() {
  const root = $('#params');
  root.innerHTML = '';
  const defs = PARAM_DEF[state.sceneType] || [];
  for (const d of defs) {
    const val = state.params[d.key];
    const label = PARAM_LABEL[d.key] || d.key;
    const row = el('div', { class: 'param' });
    const head = el('div', { class: 'param-row' },
      el('label', {}, label),
      el('span', { class: 'val', id: `pv-${d.key}` }, String(val))
    );
    row.appendChild(head);

    if (d.type === 'range') {
      const input = el('input', {
        type: 'range', min: d.min, max: d.max, step: d.step,
        value: String(val ?? d.min),
        oninput: (e) => {
          let v = parseFloat(e.target.value);
          if (d.step >= 1) v = Math.round(v);
          state.params[d.key] = v;
          $(`#pv-${d.key}`).textContent = (d.step < 1 ? v.toFixed(2) : v);
          rebuildStage();
        },
      });
      row.appendChild(input);
    } else if (d.type === 'enum') {
      const sel = el('select', {
        onchange: (e) => { state.params[d.key] = e.target.value; rebuildStage(); },
      });
      for (const o of d.options) {
        const opt = el('option', { value: o }, o);
        if (o === val) opt.selected = true;
        sel.appendChild(opt);
      }
      row.appendChild(sel);
    } else if (d.type === 'bool') {
      const wrap = el('label', { class: 'toggle' });
      const cb = el('input', {
        type: 'checkbox',
        onchange: (e) => {
          state.params[d.key] = e.target.checked;
          $(`#pv-${d.key}`).textContent = String(e.target.checked);
          rebuildStage();
        },
      });
      if (val) cb.setAttribute('checked', 'checked');
      wrap.appendChild(cb);
      wrap.appendChild(el('span', { class: 'toggle-track' }));
      row.appendChild(wrap);
    } else if (d.type === 'number') {
      const input = el('input', {
        type: 'number', min: d.min, max: d.max, step: d.step,
        value: String(val ?? d.min),
        oninput: (e) => {
          state.params[d.key] = parseInt(e.target.value, 10) || 0;
          $(`#pv-${d.key}`).textContent = String(state.params[d.key]);
          rebuildStage();
        },
      });
      row.appendChild(input);
    }
    root.appendChild(row);
  }
}

function rebuildStage() {
  const cfg = boot.scenes[state.sceneType] || {};
  const cfgWithType = { ...cfg, scene_type: state.sceneType };
  const count = state.stage.setScene(state.sceneType, state.params, cfgWithType);
  $('#ov-count').textContent = count;
}

function setLabel(key, label) {
  const el = document.getElementById(`pv-${key}`);
  if (el) el.textContent = label;
}

function switchChatMode(mode) {
  state.chatMode = mode;
  $$('.mode-btn').forEach(b => {
    const on = b.dataset.mode === mode;
    b.classList.toggle('active', on);
    b.style.background = on ? 'var(--accent-soft)' : 'transparent';
    b.style.color = on ? 'var(--accent)' : 'var(--text-tertiary)';
  });
  if (mode === 'free') {
    $('#chat-title').textContent = '自由对话模式';
    $('#chat-sub').textContent = '裸调 LLM, 无 system prompt 无 tool. 用来验真模型 / 闲聊 / 测试 provider 切换.';
    $('#chat-text').placeholder = '例：你是什么模型？ / 5+3=?';
  } else {
    $('#chat-title').textContent = '自然语言场景编辑';
    $('#chat-sub').textContent = '用中文描述你想要的场景，AI 会调用 update_scene 工具修改参数。';
    $('#chat-text').placeholder = '例：仓库再多放几台叉车，灯光偏冷一点';
  }
  renderSuggestions();
}

function renderSuggestions() {
  const root = $('#suggestions');
  if (!root) return;
  root.innerHTML = '';
  for (const s of SUGGESTIONS_BY_MODE[state.chatMode] || []) {
    const b = el('button', { class: 'suggestion' }, s);
    b.addEventListener('click', () => {
      $('#chat-text').value = s;
      sendChat();
    });
    root.appendChild(b);
  }
}

async function sendChat() {
  const txt = $('#chat-text').value.trim();
  if (!txt) return;
  $('#chat-text').value = '';
  $('#chat-send').disabled = true;

  const modeBadge = state.chatMode === 'free' ? '自由' : '场景';
  appendMsg('user', `你 · ${modeBadge}`, txt);
  const thinking = appendMsg('ai', `AI · ${boot.llm_provider}`, '思考中...', { thinking: true });

  const payload = {
    text: txt,
    mode: state.chatMode,
    current_spec: { scene_id: state.sceneType, pcg_params: state.params },
    history: state.chatMode === 'free' ? state.freeHistory.slice(-10) : [],
  };
  console.log(`[chat:${state.chatMode}] POST /api/chat`, payload);
  const t0 = performance.now();

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    const dt = Math.round(performance.now() - t0);
    console.log(`[chat] response in ${dt}ms`, data);
    thinking.remove();

    if (!data.ok) {
      console.error('[chat] error response', data);
      appendMsg('ai', `AI · ${data.provider || boot.llm_provider}`,
        `调用失败: ${data.error || 'unknown'}`, { error: true });
      return;
    }
    if (data.provider === 'keyword') {
      console.warn('[chat] running in KEYWORD fallback mode -- DEEPSEEK_API_KEY or ANTHROPIC_API_KEY not set');
    }

    const tc = data.tool_call;
    if (!tc) {
      const elapsed = data.elapsed_ms || 0;
      const responseText = data.text || '(空响应)';
      appendMsg('ai', `AI · ${data.provider} · ${data.model}`,
        responseText.replace(/\n/g, '<br>'),
        { metaText: `text mode · ${elapsed}ms` });
      if (state.chatMode === 'free') {
        state.freeHistory.push({ role: 'user', content: txt });
        state.freeHistory.push({ role: 'assistant', content: responseText });
      }
      return;
    }

    const args = tc.arguments || {};
    const delta = args.pcg_params || {};
    const rationale = args.rationale || '(no rationale)';

    const sceneIdReturned = args.scene_id || state.sceneType;
    if (sceneIdReturned && sceneIdReturned !== state.sceneType
        && boot.scenes[sceneIdReturned]) {
      selectScene(sceneIdReturned);
    }

    const pills = [];
    const isReject = Object.keys(delta).length === 0;
    if (isReject) {
      pills.push(`<span class="delta-pill reject">未变更</span>`);
    } else {
      for (const [k, v] of Object.entries(delta)) {
        pills.push(`<span class="delta-pill">${k} = ${v}</span>`);
        state.params[k] = v;
        const lbl = document.getElementById(`pv-${k}`);
        if (lbl) lbl.textContent = String(v);
      }
    }

    const elapsed = data.elapsed_ms || 0;
    appendMsg('ai', `AI · ${data.provider} · ${data.model}`,
      rationale + '<div style="margin-top:6px;">' + pills.join(' ') + '</div>',
      { metaText: `tool: ${tc.name} · ${elapsed}ms` });

    renderParams();
    rebuildStage();

  } catch (e) {
    thinking.remove();
    appendMsg('ai', 'AI', `网络错误: ${e.message}`, { error: true });
  } finally {
    $('#chat-send').disabled = false;
  }
}

function appendMsg(role, who, body, opts = {}) {
  const m = document.createElement('div');
  m.className = 'msg ' + role;
  m.innerHTML = `
    <div class="who">${who}</div>
    <div class="body" style="${opts.error ? 'color:var(--err);' : ''}${opts.thinking ? 'opacity:0.6;font-style:italic;' : ''}">${body}</div>
    ${opts.metaText ? `<div class="meta">${opts.metaText}</div>` : ''}
  `;
  $('#messages').appendChild(m);
  $('#messages').scrollTop = $('#messages').scrollHeight;
  return m;
}

async function submitBatch(n) {
  $('#btn-batch').disabled = true;
  appendMsg('ai', 'System',
    `提交批量任务: ${SCENE_LABEL[state.sceneType]} × ${n} variant，每个 30 帧 multi-pass EXR (FinalImage / WorldNormal / SceneDepth / ObjectId / GBufferA)`);
  try {
    const resp = await fetch('/api/demo/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        scene_id: state.sceneType,
        pcg_params: state.params,
        variants: n,
        rationale: '批量演示任务',
      }),
    });
    const data = await resp.json();
    if (!data.ok) {
      appendMsg('ai', 'System', `提交失败: ${data.error}`, { error: true });
      return;
    }
    for (const j of data.jobs) {
      state.jobs.set(j.job_id, { ...j, frame_index: 0, frame_total: 30 });
      streamJob(j.job_id);
    }
    renderJobs();
  } finally {
    setTimeout(() => { $('#btn-batch').disabled = false; }, 2000);
  }
}

function streamJob(jobId) {
  if (state.activeStreams.has(jobId)) return;
  state.activeStreams.add(jobId);
  const es = new EventSource(`/api/demo/stream/${jobId}`);
  es.addEventListener('status', (ev) => {
    const d = JSON.parse(ev.data);
    const j = state.jobs.get(jobId);
    if (!j) return;
    Object.assign(j, d);
    renderJobs();
  });
  es.addEventListener('frame', (ev) => {
    const d = JSON.parse(ev.data);
    upsertGalleryCard(d, true);
  });
  es.addEventListener('done', (ev) => {
    const d = JSON.parse(ev.data);
    const j = state.jobs.get(jobId);
    if (j) { j.status = 'done'; }
    renderJobs();
    upsertGalleryCard({
      job_id: d.job_id,
      scene_id: d.scene_id,
      variant_id: d.variant_id,
      frame_index: d.frames,
      frame_total: d.frames,
      thumbnail_url: d.thumbnail_url,
    }, false);
    state.activeStreams.delete(jobId);
    es.close();
  });
  es.onerror = () => {
    state.activeStreams.delete(jobId);
    es.close();
  };
}

function renderJobs() {
  const root = $('#jobs-list');
  root.innerHTML = '';
  const arr = Array.from(state.jobs.values()).sort((a, b) => {
    const ord = { pcg: 0, mrq: 1, queued: 2, done: 3 };
    return (ord[a.status] ?? 9) - (ord[b.status] ?? 9);
  });
  if (arr.length === 0) {
    root.innerHTML = '<div style="font-size:11px;color:var(--text-tertiary);padding:10px 0;">无活跃任务</div>';
    return;
  }
  for (const j of arr) {
    const pct = j.frame_total ? Math.round(j.frame_index / j.frame_total * 100) : 0;
    const card = el('div', {
      class: 'job ' + (j.status || '') + (j.status === 'mrq' ? ' active' : ''),
    },
      el('div', { class: 'job-head' },
        el('span', { class: 'id' }, '#' + j.job_id),
        el('span', { class: 'scene' }, j.scene_id + ' · ' + j.variant_id)
      ),
      el('div', { class: 'stage' },
        el('span', {}, j.status || 'queued'),
        el('span', { class: 'frames' },
          j.status === 'pcg' ? 'PCG generate'
          : j.status === 'mrq' ? `${j.frame_index}/${j.frame_total}`
          : j.status === 'done' ? `${j.frame_total} 帧 ✓`
          : 'queued')
      ),
      el('div', { class: 'progress' },
        Object.assign(el('div', { class: 'fill' }),
          { style: `width:${j.status === 'done' ? 100 : pct}%` })
      )
    );
    card.querySelector('.progress .fill').style.width =
      (j.status === 'done' ? 100 : (j.status === 'pcg' ? 8 : pct)) + '%';
    root.appendChild(card);
  }
}

function upsertGalleryCard(d, live) {
  const cardId = `frame-${d.job_id}`;
  let card = document.getElementById(cardId);
  if (!card) {
    card = el('div', {
      class: 'frame-card', id: cardId,
      onclick: () => openChannelModal(d),
    });
    $('#gallery').appendChild(card);
    const emptyEl = $('#gallery .gallery-empty');
    if (emptyEl) emptyEl.remove();
  }
  const params = encodeURIComponent(JSON.stringify(state.params));
  const url = `/api/demo/thumbnail/${d.scene_id}?frame=${d.frame_index}&variant=${d.variant_id}&params=${params}`;
  card.innerHTML = `
    <img src="${url}" alt="${d.scene_id} ${d.variant_id}">
    <div class="label">${d.scene_id} · ${d.variant_id} · ${d.frame_index}/${d.frame_total}</div>
    ${live ? '<div class="live">LIVE</div>' : ''}
  `;
  card.dataset.frameData = JSON.stringify(d);
  card.onclick = () => openChannelModal(d);
}

function openChannelModal(d) {
  const params = encodeURIComponent(JSON.stringify(state.params));
  const base = `/api/demo/thumbnail/${d.scene_id}?frame=${d.frame_index || d.frame_total}&variant=${d.variant_id}&params=${params}`;
  const channels = [
    ['final', 'FinalImage (RGB)'],
    ['normal', 'WorldNormal'],
    ['depth', 'SceneDepth'],
    ['objectid', 'ObjectId Mask'],
  ];
  const root = $('#modal-root');
  root.innerHTML = `
    <div class="modal-back" id="modal-back">
      <div class="modal" onclick="event.stopPropagation()">
        <div class="modal-head">
          <h3>${d.scene_id} · ${d.variant_id} · 多通道 EXR 预览</h3>
          <div class="x">×</div>
        </div>
        <div class="modal-body">
          ${channels.map(([ch, label]) => `
            <div class="channel-card">
              <div class="title">${label}</div>
              <img src="${base}&channel=${ch}" alt="${label}">
            </div>`).join('')}
        </div>
      </div>
    </div>
  `;
  $('#modal-back').addEventListener('click', () => { root.innerHTML = ''; });
  $('#modal-back .x').addEventListener('click', () => { root.innerHTML = ''; });
}

function clearGallery() {
  $('#gallery').innerHTML = '<div class="gallery-empty">已清空。</div>';
  state.jobs.clear();
  state.activeStreams.forEach(jid => state.activeStreams.delete(jid));
  renderJobs();
}

window.addEventListener('DOMContentLoaded', init);
