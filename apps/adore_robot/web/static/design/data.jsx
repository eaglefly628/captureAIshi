// data.jsx — PCG params, scenes, robots, canned LLM responses

// ─── 21 PCG params, grouped per the doc's pcg_param_contract.md ──────────────
const PARAM_GROUPS = [
  {
    id: 'scene',
    label: 'Scene · Layout',
    params: [
      { key: 'shelf_density', label: '货架填充率', min: 0.2, max: 1.0, step: 0.01, def: 0.6, unit: '' },
      { key: 'alley_width_m', label: '主通道宽度', min: 1.5, max: 4.0, step: 0.1, def: 2.4, unit: 'm' },
      { key: 'room_w_m', label: '房间宽', min: 8, max: 40, step: 0.5, def: 18, unit: 'm' },
      { key: 'room_l_m', label: '房间长', min: 8, max: 60, step: 0.5, def: 28, unit: 'm' },
      { key: 'ceiling_h_m', label: '层高', min: 3.0, max: 9.0, step: 0.1, def: 5.5, unit: 'm' },
      { key: 'pallet_load_factor', label: '货架装载率', min: 0.0, max: 1.0, step: 0.01, def: 0.55, unit: '' },
      { key: 'prop_variety', label: '货物种类数', min: 1, max: 5, step: 1, def: 3, unit: '', integer: true },
    ],
  },
  {
    id: 'agents',
    label: 'Agents · Props',
    params: [
      { key: 'forklift_count', label: '叉车数量', min: 0, max: 5, step: 1, def: 1, unit: '', integer: true },
      { key: 'worker_count', label: '人员数量', min: 0, max: 8, step: 1, def: 0, unit: '', integer: true },
      { key: 'clutter_density', label: '杂物密度', min: 0.0, max: 1.0, step: 0.01, def: 0.2, unit: '' },
      { key: 'pallet_jack_count', label: '托盘车数', min: 0, max: 4, step: 1, def: 0, unit: '', integer: true },
    ],
  },
  {
    id: 'lighting',
    label: 'Lighting',
    params: [
      {
        key: 'lighting_preset', label: '灯光预设',
        type: 'enum', def: 'sodium',
        options: ['sodium', 'cool', 'mixed'],
      },
      { key: 'ambient_lux', label: '环境照度', min: 50, max: 800, step: 10, def: 320, unit: 'lx' },
      { key: 'window_count', label: '窗户数', min: 0, max: 12, step: 1, def: 4, unit: '', integer: true },
      { key: 'time_of_day', label: '时间', min: 0, max: 24, step: 0.25, def: 14.0, unit: 'h' },
    ],
  },
  {
    id: 'capture',
    label: 'Capture',
    params: [
      {
        key: 'camera_mode', label: '相机模式',
        type: 'enum', def: 'orbit',
        options: ['orbit', 'static', 'tracking'],
      },
      { key: 'camera_height_m', label: '相机高度', min: 0.8, max: 4.0, step: 0.1, def: 1.6, unit: 'm' },
      { key: 'frame_count', label: '帧数', min: 16, max: 240, step: 1, def: 30, unit: 'f', integer: true },
      { key: 'fps', label: '帧率', min: 12, max: 60, step: 1, def: 24, unit: 'fps', integer: true },
      { key: 'resolution', label: '分辨率', type: 'enum', def: '1920x1080',
        options: ['1280x720', '1920x1080', '2560x1440'] },
      { key: 'seed', label: '随机种子', min: 0, max: 9999, step: 1, def: 4271, unit: '', integer: true },
    ],
  },
];

// flatten for quick lookup
const ALL_PARAMS = PARAM_GROUPS.flatMap(g => g.params);
const PARAM_BY_KEY = Object.fromEntries(ALL_PARAMS.map(p => [p.key, p]));

const DEFAULT_PARAMS = Object.fromEntries(ALL_PARAMS.map(p => [p.key, p.def]));

// ─── Scenes ──────────────────────────────────────────────────────────────────
const SCENES = {
  warehouse: { id: 'warehouse', label: 'Warehouse', icon: '⌂', subtitle: 'BSP 切房间 → 货架 → 叉车 → 灯' },
  livingroom: { id: 'livingroom', label: 'Living Room', icon: '◊', subtitle: '家居布局 → 家具 → 杯具 → 软光' },
  factory: { id: 'factory', label: 'Factory', icon: '☰', subtitle: '工位 → 流水线 → 工具 → 工业灯' },
};

// ─── Robots ──────────────────────────────────────────────────────────────────
const ROBOTS = {
  franka_panda: { id: 'franka_panda', label: 'FRANKA Panda', kind: 'arm', dof: 7 },
  unitree_h1:   { id: 'unitree_h1',   label: 'Unitree H1',   kind: 'humanoid', dof: 19 },
  ur5:          { id: 'ur5',          label: 'UR5',          kind: 'arm', dof: 6 },
};

// ─── Canned LLM responses ────────────────────────────────────────────────────
// Each "response" is a tool_call sequence + an English-ish narration to show in chat.
// The keyword matcher picks the best one. Falls back to GENERIC.

function makeToolCall(name, args) {
  return { name, args };
}

const RESPONSE_LIBRARY = [
  {
    match: /密|多|满|挤|crowd|dense|pack/i,
    requireScene: 'warehouse',
    narrate: '收到。把仓库密度调高 — shelf_density → 0.9，装载率 → 0.85，加 2 台叉车，主通道留 2.0m，sodium 灯。然后让 FRANKA 在通道中央摆抓箱姿势，启动 PCG 重生成并触发 MRQ。',
    calls: [
      makeToolCall('load_scene', { scene: 'warehouse' }),
      makeToolCall('set_shelf_density', { value: 0.9 }),
      makeToolCall('set_pallet_load_factor', { value: 0.85 }),
      makeToolCall('set_alley_width_m', { value: 2.0 }),
      makeToolCall('set_forklift_count', { value: 2 }),
      makeToolCall('set_lighting_preset', { value: 'sodium' }),
      makeToolCall('spawn_robot', {
        urdf: 'franka_panda',
        pos: [0, 0, 0],
        joint_state: [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785],
      }),
      makeToolCall('trigger_generate', {}),
      makeToolCall('trigger_mrq_render', { preset: 'MRQ_MultiPassEXR', subdir: 'warehouse/v0_demo' }),
    ],
  },
  {
    match: /稀|空|少|sparse|empty|few/i,
    requireScene: 'warehouse',
    narrate: '降低密度 — shelf_density → 0.35，装载率 → 0.25，主通道拉宽到 3.5m，叉车归零，改 cool 灯光便于视觉对比。',
    calls: [
      makeToolCall('load_scene', { scene: 'warehouse' }),
      makeToolCall('set_shelf_density', { value: 0.35 }),
      makeToolCall('set_pallet_load_factor', { value: 0.25 }),
      makeToolCall('set_alley_width_m', { value: 3.5 }),
      makeToolCall('set_forklift_count', { value: 0 }),
      makeToolCall('set_lighting_preset', { value: 'cool' }),
      makeToolCall('spawn_robot', { urdf: 'franka_panda', pos: [0, 0, 0] }),
      makeToolCall('trigger_generate', {}),
      makeToolCall('trigger_mrq_render', { preset: 'MRQ_MultiPassEXR', subdir: 'warehouse/v1_sparse' }),
    ],
  },
  {
    match: /客厅|living|杯|cup|沙发|sofa/i,
    requireScene: 'livingroom',
    narrate: '切到客厅场景。设家具密度，茶几放杯组，Unitree H1 站在沙发前准备递杯。',
    calls: [
      makeToolCall('load_scene', { scene: 'livingroom' }),
      makeToolCall('set_clutter_density', { value: 0.4 }),
      makeToolCall('set_lighting_preset', { value: 'mixed' }),
      makeToolCall('set_time_of_day', { value: 17.5 }),
      makeToolCall('spawn_robot', { urdf: 'unitree_h1', pos: [-1.2, 0, 0.8] }),
      makeToolCall('trigger_generate', {}),
      makeToolCall('trigger_mrq_render', { preset: 'MRQ_MultiPassEXR', subdir: 'livingroom/cup_v0' }),
    ],
  },
  {
    match: /工厂|factory|流水|conveyor|扳手|wrench/i,
    requireScene: 'factory',
    narrate: '工厂场景。工位排布 + 流水线，UR5 在工位 3 准备扳手柄。',
    calls: [
      makeToolCall('load_scene', { scene: 'factory' }),
      makeToolCall('set_prop_variety', { value: 5 }),
      makeToolCall('set_worker_count', { value: 2 }),
      makeToolCall('set_lighting_preset', { value: 'cool' }),
      makeToolCall('spawn_robot', { urdf: 'ur5', pos: [0.5, 0, 0.9] }),
      makeToolCall('trigger_generate', {}),
      makeToolCall('trigger_mrq_render', { preset: 'MRQ_MultiPassEXR', subdir: 'factory/wrench_v0' }),
    ],
  },
  {
    match: /叉车|forklift/i,
    requireScene: 'warehouse',
    narrate: '加叉车。3 台分布在主通道两侧。',
    calls: [
      makeToolCall('set_forklift_count', { value: 3 }),
      makeToolCall('trigger_generate', {}),
    ],
  },
  {
    match: /种子|seed|不一样|变|random/i,
    narrate: '换一组种子，重新撒一遍程序化布置。其他参数不动。',
    calls: [
      makeToolCall('set_seed', { value: Math.floor(Math.random() * 9999) }),
      makeToolCall('trigger_generate', {}),
    ],
  },
];

// Fallback / default
const GENERIC_RESPONSE = {
  narrate: '理解为标准 warehouse 配置。中等密度，sodium 灯光，1 台叉车，FRANKA 在主通道。生成后渲 30 帧 multi-layer EXR。',
  calls: [
    makeToolCall('load_scene', { scene: 'warehouse' }),
    makeToolCall('set_shelf_density', { value: 0.6 }),
    makeToolCall('set_pallet_load_factor', { value: 0.55 }),
    makeToolCall('set_alley_width_m', { value: 2.4 }),
    makeToolCall('set_forklift_count', { value: 1 }),
    makeToolCall('set_lighting_preset', { value: 'sodium' }),
    makeToolCall('spawn_robot', { urdf: 'franka_panda', pos: [0, 0, 0] }),
    makeToolCall('trigger_generate', {}),
    makeToolCall('trigger_mrq_render', { preset: 'MRQ_MultiPassEXR', subdir: 'warehouse/v0_demo' }),
  ],
};

function chooseResponse(prompt, currentScene) {
  for (const r of RESPONSE_LIBRARY) {
    if (r.match.test(prompt)) {
      if (!r.requireScene || r.requireScene === currentScene || /仓库|warehouse|客厅|living|工厂|factory/i.test(prompt)) {
        return r;
      }
    }
  }
  return GENERIC_RESPONSE;
}

// Map tool_call name → param key (so a tool_call animates the corresponding slider)
function toolCallToParamKey(name) {
  if (!name.startsWith('set_')) return null;
  const stem = name.slice(4);
  // direct match first
  if (PARAM_BY_KEY[stem]) return stem;
  // some specials
  if (stem === 'lighting_preset') return 'lighting_preset';
  return null;
}

const PIPELINE_STAGES = [
  { id: 'parse',    t: 'T+0s',   name: 'Parse',     sub: 'DeepSeek-V3.2',     icon: '◔' },
  { id: 'dispatch', t: 'T+2s',   name: 'Dispatch',  sub: 'MCP → UE',          icon: '↗' },
  { id: 'generate', t: 'T+2.5s', name: 'Generate',  sub: 'PCG · spawn',       icon: '◈' },
  { id: 'render',   t: 'T+8s',   name: 'Render',    sub: 'MRQ · 30f EXR',     icon: '◉' },
  { id: 'package',  t: 'T+15m',  name: 'Package',   sub: 'Cosmos · LeRobot',  icon: '◆' },
];

const RENDER_LAYERS = [
  { name: 'FinalImage',   key: 'final',   color: 'var(--c-final)' },
  { name: 'WorldNormal',  key: 'normal',  color: 'var(--c-normal)' },
  { name: 'SceneDepth',   key: 'depth',   color: 'var(--c-depth)' },
  { name: 'ObjectId',     key: 'objid',   color: 'var(--c-objid)' },
  { name: 'GBufferA',     key: 'gbuffer', color: 'var(--c-gbuffer)' },
];

const SUGGESTIONS = {
  warehouse: [
    '货架密一点, 放 2 台叉车, FRANKA 摆抓箱姿势',
    '主通道宽一点, sparse 一些, 给 cool 灯光',
    '换个 seed 再来一遍',
    '加一台叉车',
  ],
  livingroom: [
    '客厅, 沙发前放杯组, H1 准备递杯',
    '昏黄一点, 傍晚 5 点',
  ],
  factory: [
    '工厂场景, UR5 在工位 3 扳手柄',
    '增加工人和工具种类',
  ],
};

// ─── Export ──────────────────────────────────────────────────────────────────
Object.assign(window, {
  PARAM_GROUPS, ALL_PARAMS, PARAM_BY_KEY, DEFAULT_PARAMS,
  SCENES, ROBOTS,
  RESPONSE_LIBRARY, GENERIC_RESPONSE, chooseResponse, toolCallToParamKey,
  PIPELINE_STAGES, RENDER_LAYERS, SUGGESTIONS,
});
