// viewport.jsx — isometric SVG scene (warehouse / livingroom / factory)

const { useMemo } = React;

// ─── Iso projection ────────────────────────────────────────────────────────
// World axes: x → right-down, y → left-down, z → up
// Returns SVG coordinates.
function iso(x, y, z = 0) {
  const c = Math.cos(Math.PI / 6); // ≈ 0.866
  const s = Math.sin(Math.PI / 6); // 0.5
  return {
    x: (x - y) * c,
    y: (x + y) * s - z,
  };
}

function pts(arr) {
  return arr.map(p => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ');
}

// ─── Single 3D box ──────────────────────────────────────────────────────────
function IsoBox({
  x, y, z = 0, w, d, h,
  top = '#D9E1EB',
  left = '#A8B5C5',
  right = '#7E8DA0',
  stroke = 'rgba(20, 30, 45, 0.32)',
  strokeWidth = 0.6,
}) {
  const A = iso(x, y, z);
  const B = iso(x + w, y, z);
  const C = iso(x + w, y + d, z);
  const D = iso(x, y + d, z);
  const A2 = iso(x, y, z + h);
  const B2 = iso(x + w, y, z + h);
  const C2 = iso(x + w, y + d, z + h);
  const D2 = iso(x, y + d, z + h);
  return (
    <g>
      {/* Right face (visible) */}
      <polygon points={pts([B, C, C2, B2])} fill={right} stroke={stroke} strokeWidth={strokeWidth} strokeLinejoin="round" />
      {/* Front-left face (visible) */}
      <polygon points={pts([C, D, D2, C2])} fill={left} stroke={stroke} strokeWidth={strokeWidth} strokeLinejoin="round" />
      {/* Top face */}
      <polygon points={pts([A2, B2, C2, D2])} fill={top} stroke={stroke} strokeWidth={strokeWidth} strokeLinejoin="round" />
    </g>
  );
}

// ─── Shelf (vertical rack with crates) ──────────────────────────────────────
function Shelf({ x, y, w, d, loadFactor = 0.6, seed = 0 }) {
  const h = 2.4;
  const tiers = 3;
  return (
    <g>
      {/* frame uprights */}
      <IsoBox x={x} y={y} w={w} d={d} h={h}
        top="#E7ECF2" left="#B6C2D2" right="#8898AD"
      />
      {/* crates per tier */}
      {Array.from({ length: tiers }).map((_, ti) => {
        const tierZ = (ti + 1) * (h / (tiers + 1));
        // crate fill probability based on loadFactor
        const slots = 3;
        return Array.from({ length: slots }).map((__, si) => {
          const r = pseudoRand(seed + ti * 31 + si * 7);
          if (r > loadFactor) return null;
          const cw = w / slots * 0.85;
          const cd = d * 0.7;
          const cx = x + (w / slots) * si + (w / slots - cw) / 2;
          const cy = y + (d - cd) / 2;
          // crate color varies
          const palette = [
            { top: '#D9C088', left: '#A8915E', right: '#7C6843' },  // cardboard
            { top: '#B8C9DE', left: '#8A9DB6', right: '#647387' },  // plastic
            { top: '#C8B8A0', left: '#9A8A72', right: '#6F614E' },  // wood
          ];
          const col = palette[(seed + ti + si) % 3];
          return (
            <IsoBox key={`${ti}-${si}`}
              x={cx} y={cy} z={tierZ - 0.05} w={cw} d={cd} h={0.5}
              top={col.top} left={col.left} right={col.right}
            />
          );
        });
      })}
    </g>
  );
}

function pseudoRand(n) {
  const x = Math.sin(n * 9999.317) * 43758.5453;
  return x - Math.floor(x);
}

// ─── Forklift (very stylized) ───────────────────────────────────────────────
function Forklift({ x, y, rot = 0 }) {
  // Drawn as 1.2 × 2.0 footprint, body + cabin + forks
  const w = 1.2, d = 2.0;
  // rotate by swapping axes if rot=90
  const fwd = rot === 90 ? { x: 0, y: 1, d: w, w: d } : { x: 0, y: 0, d, w };
  return (
    <g>
      {/* body */}
      <IsoBox x={x} y={y} w={fwd.w} d={fwd.d} h={0.5}
        top="#E8A627" left="#B07A14" right="#7E5705" />
      {/* cabin */}
      <IsoBox x={x + 0.2} y={y + 0.2} z={0.5} w={fwd.w - 0.4} d={fwd.d * 0.4} h={1.2}
        top="#1F2A38" left="#0F1825" right="#08101A" />
      {/* mast */}
      <IsoBox x={x + fwd.w * 0.3} y={y + fwd.d - 0.15} z={0} w={fwd.w * 0.4} d={0.15} h={2.0}
        top="#33414F" left="#222C39" right="#161E29" />
      {/* forks */}
      <IsoBox x={x + 0.2} y={y + fwd.d} z={0.1} w={0.25} d={0.6} h={0.1}
        top="#9AA5B2" left="#6F7886" right="#4B5462" />
      <IsoBox x={x + fwd.w - 0.45} y={y + fwd.d} z={0.1} w={0.25} d={0.6} h={0.1}
        top="#9AA5B2" left="#6F7886" right="#4B5462" />
    </g>
  );
}

// ─── Robots ─────────────────────────────────────────────────────────────────
function FrankaArm({ x, y }) {
  // Mounted on a small base, 7-segment articulated arm bent in "grab box" pose
  const base = (
    <IsoBox x={x - 0.3} y={y - 0.3} w={0.6} d={0.6} h={0.4}
      top="#2F3845" left="#1B2230" right="#0E141E" />
  );
  // Arm segments (drawn as little stacked boxes — abstracted)
  return (
    <g>
      {base}
      <IsoBox x={x - 0.15} y={y - 0.15} z={0.4} w={0.3} d={0.3} h={0.4}
        top="#E8EBEF" left="#B0B5BD" right="#7C828B" />
      <IsoBox x={x - 0.1} y={y - 0.1} z={0.8} w={0.2} d={0.2} h={0.7}
        top="#E8EBEF" left="#B0B5BD" right="#7C828B" />
      {/* shoulder bend */}
      <IsoBox x={x - 0.1} y={y - 0.1} z={1.5} w={0.7} d={0.2} h={0.15}
        top="#E8EBEF" left="#B0B5BD" right="#7C828B" />
      {/* forearm */}
      <IsoBox x={x + 0.5} y={y - 0.1} z={1.2} w={0.15} d={0.15} h={0.3}
        top="#E8EBEF" left="#B0B5BD" right="#7C828B" />
      <IsoBox x={x + 0.5} y={y - 0.1} z={0.85} w={0.18} d={0.15} h={0.35}
        top="#E8EBEF" left="#B0B5BD" right="#7C828B" />
      {/* gripper */}
      <IsoBox x={x + 0.5} y={y - 0.1} z={0.75} w={0.18} d={0.15} h={0.1}
        top="#2E5C8A" left="#1F4670" right="#143052" />
      {/* base accent ring */}
      <ellipse cx={iso(x, y, 0.42).x} cy={iso(x, y, 0.42).y} rx={9} ry={4}
        fill="none" stroke="#2E5C8A" strokeWidth={1.2} strokeDasharray="2 2" opacity={0.5} />
    </g>
  );
}

function UnitreeH1({ x, y }) {
  // Humanoid: torso + head + arms + legs (stylized as stacked boxes)
  return (
    <g>
      {/* legs */}
      <IsoBox x={x - 0.18} y={y - 0.1} w={0.18} d={0.2} h={0.7}
        top="#E8EBEF" left="#9AA5B2" right="#6E7886" />
      <IsoBox x={x} y={y - 0.1} w={0.18} d={0.2} h={0.7}
        top="#E8EBEF" left="#9AA5B2" right="#6E7886" />
      {/* torso */}
      <IsoBox x={x - 0.25} y={y - 0.15} z={0.7} w={0.45} d={0.3} h={0.6}
        top="#2F3845" left="#1F2A38" right="#121A24" />
      {/* arms */}
      <IsoBox x={x - 0.35} y={y - 0.15} z={1.1} w={0.1} d={0.1} h={0.55}
        top="#E8EBEF" left="#9AA5B2" right="#6E7886" />
      <IsoBox x={x + 0.2} y={y - 0.15} z={1.1} w={0.1} d={0.1} h={0.55}
        top="#E8EBEF" left="#9AA5B2" right="#6E7886" />
      {/* head */}
      <IsoBox x={x - 0.12} y={y - 0.1} z={1.3} w={0.24} d={0.22} h={0.22}
        top="#1F2A38" left="#141A24" right="#0A0F17" />
      {/* visor */}
      <IsoBox x={x - 0.12} y={y + 0.07} z={1.38} w={0.24} d={0.04} h={0.08}
        top="#2E5C8A" left="#1F4670" right="#143052" />
    </g>
  );
}

function UR5({ x, y }) {
  return (
    <g>
      {/* base pillar */}
      <IsoBox x={x - 0.2} y={y - 0.2} w={0.4} d={0.4} h={0.9}
        top="#2F3845" left="#1B2230" right="#0E141E" />
      {/* first joint */}
      <IsoBox x={x - 0.15} y={y - 0.15} z={0.9} w={0.3} d={0.3} h={0.25}
        top="#4178B2" left="#2E5C8A" right="#1F4670" />
      {/* link 1 */}
      <IsoBox x={x - 0.1} y={y - 0.1} z={1.15} w={0.2} d={0.2} h={0.55}
        top="#E8EBEF" left="#B0B5BD" right="#7C828B" />
      {/* elbow */}
      <IsoBox x={x - 0.12} y={y - 0.12} z={1.7} w={0.25} d={0.6} h={0.15}
        top="#4178B2" left="#2E5C8A" right="#1F4670" />
      {/* forearm forward */}
      <IsoBox x={x - 0.08} y={y + 0.4} z={1.55} w={0.18} d={0.18} h={0.15}
        top="#E8EBEF" left="#B0B5BD" right="#7C828B" />
      {/* gripper */}
      <IsoBox x={x - 0.1} y={y + 0.4} z={1.4} w={0.2} d={0.18} h={0.15}
        top="#1F4670" left="#143052" right="#0A1F36" />
    </g>
  );
}

// ─── Sofa, coffee table, etc. for living room ───────────────────────────────
function Sofa({ x, y }) {
  return (
    <g>
      {/* base */}
      <IsoBox x={x} y={y} w={2.4} d={0.9} h={0.35}
        top="#D8C5A8" left="#9E8A6F" right="#6E5E48" />
      {/* seat cushions */}
      <IsoBox x={x + 0.05} y={y + 0.05} z={0.35} w={1.15} d={0.7} h={0.18}
        top="#E5D4B8" left="#B59E80" right="#806E55" />
      <IsoBox x={x + 1.2} y={y + 0.05} z={0.35} w={1.15} d={0.7} h={0.18}
        top="#E5D4B8" left="#B59E80" right="#806E55" />
      {/* backrest */}
      <IsoBox x={x} y={y} w={2.4} d={0.18} h={0.95}
        top="#C8B398" left="#947E62" right="#65543F" />
      {/* arms */}
      <IsoBox x={x} y={y} w={0.2} d={0.9} h={0.65}
        top="#C8B398" left="#947E62" right="#65543F" />
      <IsoBox x={x + 2.2} y={y} w={0.2} d={0.9} h={0.65}
        top="#C8B398" left="#947E62" right="#65543F" />
    </g>
  );
}

function CoffeeTable({ x, y, cups = 0 }) {
  return (
    <g>
      <IsoBox x={x} y={y} w={1.5} d={0.8} h={0.45}
        top="#3F352A" left="#28211A" right="#16110B" />
      <IsoBox x={x + 0.05} y={y + 0.05} z={0.45} w={1.4} d={0.7} h={0.05}
        top="#5A4F40" left="#3F362B" right="#241D14" />
      {/* cups */}
      {Array.from({ length: cups }).map((_, i) => {
        const cx = x + 0.3 + i * 0.32;
        const cy = y + 0.35;
        return (
          <g key={i}>
            <IsoBox x={cx} y={cy} z={0.5} w={0.12} d={0.12} h={0.13}
              top="#FAFAF8" left="#C8C8C4" right="#9D9D98" />
          </g>
        );
      })}
    </g>
  );
}

function Conveyor({ x, y, length = 8 }) {
  return (
    <g>
      <IsoBox x={x} y={y} w={length} d={1.0} h={0.9}
        top="#383E48" left="#23272F" right="#13161C" />
      <IsoBox x={x} y={y + 0.05} z={0.9} w={length} d={0.9} h={0.05}
        top="#5A6470" left="#3D4452" right="#222731" />
      {/* boxes on belt */}
      {[1, 3, 5, 7].map(i => (
        i < length - 0.5 && (
          <IsoBox key={i} x={x + i} y={y + 0.2} z={0.95}
            w={0.6} d={0.6} h={0.4}
            top="#D9C088" left="#A8915E" right="#7C6843" />
        )
      ))}
    </g>
  );
}

function Workstation({ x, y }) {
  return (
    <g>
      <IsoBox x={x} y={y} w={1.2} d={0.7} h={0.85}
        top="#A8B5C5" left="#7E8DA0" right="#566374" />
      <IsoBox x={x + 0.1} y={y + 0.1} z={0.85} w={1.0} d={0.5} h={0.03}
        top="#C8D2DD" left="#94A0AE" right="#65707E" />
    </g>
  );
}

// ─── Floor & room ───────────────────────────────────────────────────────────
function Floor({ w, d, color = '#EEF2F6', strokeColor = '#C5CCD6' }) {
  const A = iso(0, 0);
  const B = iso(w, 0);
  const C = iso(w, d);
  const D = iso(0, d);
  return (
    <g>
      <polygon points={pts([A, B, C, D])} fill={color} stroke={strokeColor} strokeWidth={1} strokeLinejoin="round" />
      {/* grid lines */}
      {Array.from({ length: Math.ceil(w) - 1 }).map((_, i) => {
        const p1 = iso(i + 1, 0);
        const p2 = iso(i + 1, d);
        return <line key={`gx-${i}`} x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y}
          stroke="rgba(46, 92, 138, 0.08)" strokeWidth={0.5} />;
      })}
      {Array.from({ length: Math.ceil(d) - 1 }).map((_, i) => {
        const p1 = iso(0, i + 1);
        const p2 = iso(w, i + 1);
        return <line key={`gy-${i}`} x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y}
          stroke="rgba(46, 92, 138, 0.08)" strokeWidth={0.5} />;
      })}
    </g>
  );
}

function Walls({ w, d, h, lightTint }) {
  // two back walls (the ones away from camera in iso are at x=w and y=d)
  // We want the walls behind the camera viewpoint hidden — show only the wall at x=0 (back-right) and y=0 (back-left)
  // But it's nicer to show as low strips so we see the scene clearly. Use h=0.3.
  const wallH = 0.25;
  return (
    <g opacity={0.85}>
      {/* back-left wall (along x axis at y=0) */}
      <IsoBox x={0} y={0} w={w} d={0.12} h={wallH}
        top={lightTint.wallTop} left={lightTint.wallLeft} right={lightTint.wallLeft} />
      {/* back-right wall (along y axis at x=0) */}
      <IsoBox x={0} y={0} w={0.12} d={d} h={wallH}
        top={lightTint.wallTop} left={lightTint.wallLeft} right={lightTint.wallLeft} />
    </g>
  );
}

// ─── Lighting tints ─────────────────────────────────────────────────────────
const LIGHTING_TINTS = {
  sodium: { floor: '#F2EBD8', floorStroke: '#D4C696', wallTop: '#E8D9A8', wallLeft: '#B8A47A', overlay: 'rgba(238, 180, 80, 0.07)' },
  cool:   { floor: '#E8EEF4', floorStroke: '#B7C5D6', wallTop: '#D5DEE8', wallLeft: '#9FAEC0', overlay: 'rgba(70, 130, 200, 0.07)' },
  mixed:  { floor: '#EFEDE8', floorStroke: '#C7C2B7', wallTop: '#E0DACC', wallLeft: '#A89F8C', overlay: 'rgba(180, 150, 110, 0.06)' },
};

// ─── Warehouse layout generator ─────────────────────────────────────────────
function buildWarehouseLayout(p) {
  const w = p.room_w_m;
  const d = p.room_l_m;
  const alley = p.alley_width_m;

  // Shelves arranged in rows parallel to room length.
  // Each "row pair" = 2 shelves back-to-back, 0.8m × shelfLen
  const shelfDepth = 0.8;
  const shelfLen = 2.0;
  const pairWidth = shelfDepth * 2; // 1.6m
  const cellSpace = pairWidth + alley;

  // Number of row pairs fitting in width
  const margin = 1.5;
  const usableW = w - margin * 2;
  const rows = Math.max(1, Math.floor(usableW / cellSpace));
  const xPad = (w - rows * cellSpace + alley) / 2; // center

  const shelves = [];
  for (let r = 0; r < rows; r++) {
    const xBase = xPad + r * cellSpace;
    // shelves along length, length-direction
    const slotsPerRow = Math.floor((d - margin * 2) / (shelfLen + 0.1));
    const yPad = (d - slotsPerRow * (shelfLen + 0.1)) / 2;
    for (let s = 0; s < slotsPerRow; s++) {
      const ys = yPad + s * (shelfLen + 0.1);
      // skip middle row for main alley
      const mid = (slotsPerRow - 1) / 2;
      const isInMidAlley = Math.abs(s - mid) < 1.5;
      if (isInMidAlley) continue;
      // density-based skipping
      const seedKey = r * 100 + s + Math.floor(p.seed);
      if (pseudoRand(seedKey) > p.shelf_density) continue;

      // back-to-back pair: shelf A and shelf B
      shelves.push({
        id: `r${r}s${s}A`,
        x: xBase, y: ys,
        w: shelfDepth, d: shelfLen,
        loadFactor: p.pallet_load_factor,
        seed: seedKey,
      });
      shelves.push({
        id: `r${r}s${s}B`,
        x: xBase + shelfDepth, y: ys,
        w: shelfDepth, d: shelfLen,
        loadFactor: p.pallet_load_factor,
        seed: seedKey + 50,
      });
    }
  }

  // Forklifts placed along central alley
  const forklifts = [];
  const fc = p.forklift_count;
  for (let i = 0; i < fc; i++) {
    const fx = w / 2 - 0.6;
    const spread = d / (fc + 1);
    const fy = spread * (i + 1) - 1.0;
    forklifts.push({ id: `f${i}`, x: fx, y: fy });
  }

  // Workers (humans, as little boxes)
  const workers = [];
  for (let i = 0; i < p.worker_count; i++) {
    const wx = 1.5 + pseudoRand(p.seed + i * 13) * (w - 3);
    const wy = 1.5 + pseudoRand(p.seed + i * 17) * (d - 3);
    workers.push({ id: `w${i}`, x: wx, y: wy });
  }

  return { shelves, forklifts, workers, robotPos: { x: w / 2, y: d / 2 } };
}

function buildLivingLayout(p) {
  const w = Math.min(p.room_w_m, 8);
  const d = Math.min(p.room_l_m, 7);
  return {
    sofa: { x: w / 2 - 1.2, y: 0.5 },
    table: { x: w / 2 - 0.75, y: 2.0, cups: Math.min(p.prop_variety, 4) },
    tvstand: { x: 0.5, y: d - 1.5 },
    robotPos: { x: 1.5, y: d - 3 },
    w, d,
  };
}

function buildFactoryLayout(p) {
  const w = Math.min(p.room_w_m, 16);
  const d = Math.min(p.room_l_m, 18);
  const stations = [];
  const count = Math.max(3, p.prop_variety);
  for (let i = 0; i < count; i++) {
    stations.push({ x: 1.0, y: 1 + i * 2.2 });
    stations.push({ x: w - 2.2, y: 1 + i * 2.2 });
  }
  return {
    stations,
    conveyorY: d / 2 - 0.5,
    conveyorLen: w - 4,
    robotPos: { x: w - 3.5, y: d / 2 - 1.4 },
    workerCount: p.worker_count,
    w, d,
  };
}

// ─── Main scene component ───────────────────────────────────────────────────
function Scene({ params, scene, robot, generating, generateProgress }) {
  const tint = LIGHTING_TINTS[params.lighting_preset] || LIGHTING_TINTS.sodium;

  const layout = useMemo(() => {
    if (scene === 'warehouse') return { kind: 'warehouse', ...buildWarehouseLayout(params) };
    if (scene === 'livingroom') return { kind: 'living', ...buildLivingLayout(params) };
    if (scene === 'factory') return { kind: 'factory', ...buildFactoryLayout(params) };
    return { kind: 'warehouse', ...buildWarehouseLayout(params) };
  }, [params, scene]);

  const roomW = scene === 'warehouse' ? params.room_w_m
              : scene === 'livingroom' ? Math.min(params.room_w_m, 8)
              : Math.min(params.room_w_m, 16);
  const roomD = scene === 'warehouse' ? params.room_l_m
              : scene === 'livingroom' ? Math.min(params.room_l_m, 7)
              : Math.min(params.room_l_m, 18);

  // Camera: center the iso projection on the room center
  const center = iso(roomW / 2, roomD / 2);
  const TILE = scene === 'warehouse' ? 13 : 32;
  const offsetX = -center.x * TILE;
  const offsetY = -center.y * TILE + 30;

  // total bounding box for items to animate in
  const renderRobot = () => {
    const { x, y } = layout.robotPos;
    if (robot === 'franka_panda') return <FrankaArm x={x} y={y} />;
    if (robot === 'unitree_h1') return <UnitreeH1 x={x} y={y} />;
    if (robot === 'ur5') return <UR5 x={x} y={y} />;
    return null;
  };

  // Generation reveal: each item appears at a fraction of the progress
  const reveal = (i, total) => generating
    ? (generateProgress * total > i ? 1 : 0)
    : 1;
  const itemStyle = (i, total) => ({
    opacity: reveal(i, total),
    transform: reveal(i, total) ? 'translateY(0) scale(1)' : 'translateY(8px) scale(0.7)',
    transformOrigin: 'center',
    transition: 'opacity 0.35s ease, transform 0.35s ease',
  });

  // Counts for staggering
  const itemTotal =
    layout.kind === 'warehouse' ? (layout.shelves.length + layout.forklifts.length + 3)
    : layout.kind === 'living' ? 6
    : (layout.stations.length + 4);

  return (
    <svg className="viewport-svg" viewBox="-360 -240 720 480" preserveAspectRatio="xMidYMid meet">
      <defs>
        <filter id="softShadow" x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur in="SourceAlpha" stdDeviation="3" />
          <feOffset dx="0" dy="2" result="off" />
          <feComponentTransfer result="alpha"><feFuncA type="linear" slope="0.18" /></feComponentTransfer>
          <feMerge><feMergeNode /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
        <linearGradient id="lightOverlay" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="white" stopOpacity="0.0" />
          <stop offset="100%" stopColor={tint.overlay} stopOpacity="0.7" />
        </linearGradient>
      </defs>

      <g transform={`translate(${offsetX}, ${offsetY}) scale(${TILE})`}>
        <Floor w={roomW} d={roomD} color={tint.floor} strokeColor={tint.floorStroke} />
        <Walls w={roomW} d={roomD} h={params.ceiling_h_m} lightTint={tint} />

        {/* Items */}
        {layout.kind === 'warehouse' && (
          <>
            {layout.shelves.map((s, i) => (
              <g key={s.id} style={itemStyle(i, itemTotal)}>
                <Shelf x={s.x} y={s.y} w={s.w} d={s.d} loadFactor={s.loadFactor} seed={s.seed} />
              </g>
            ))}
            {layout.forklifts.map((f, i) => (
              <g key={f.id} style={itemStyle(layout.shelves.length + i, itemTotal)}>
                <Forklift x={f.x} y={f.y} />
              </g>
            ))}
            {layout.workers.map((wkr, i) => (
              <g key={wkr.id} style={itemStyle(layout.shelves.length + layout.forklifts.length + i, itemTotal)}>
                <IsoBox x={wkr.x - 0.15} y={wkr.y - 0.1} w={0.3} d={0.2} h={1.7}
                  top="#E8C8A8" left="#A88868" right="#75584A" />
              </g>
            ))}
            <g style={itemStyle(itemTotal - 1, itemTotal)}>
              {renderRobot()}
            </g>
          </>
        )}

        {layout.kind === 'living' && (
          <>
            <g style={itemStyle(0, itemTotal)}>
              <Sofa x={layout.sofa.x} y={layout.sofa.y} />
            </g>
            <g style={itemStyle(1, itemTotal)}>
              <CoffeeTable x={layout.table.x} y={layout.table.y} cups={layout.table.cups} />
            </g>
            <g style={itemStyle(2, itemTotal)}>
              {/* TV stand */}
              <IsoBox x={layout.tvstand.x} y={layout.tvstand.y} w={2.0} d={0.4} h={0.5}
                top="#22272E" left="#13171C" right="#080A0E" />
              <IsoBox x={layout.tvstand.x + 0.2} y={layout.tvstand.y} z={0.5} w={1.6} d={0.05} h={0.95}
                top="#0A0E14" left="#06090F" right="#040608" />
            </g>
            <g style={itemStyle(3, itemTotal)}>
              {renderRobot()}
            </g>
          </>
        )}

        {layout.kind === 'factory' && (
          <>
            <g style={itemStyle(0, itemTotal)}>
              <Conveyor x={2} y={layout.conveyorY} length={layout.conveyorLen} />
            </g>
            {layout.stations.map((st, i) => (
              <g key={i} style={itemStyle(1 + i, itemTotal)}>
                <Workstation x={st.x} y={st.y} />
              </g>
            ))}
            <g style={itemStyle(layout.stations.length + 1, itemTotal)}>
              {renderRobot()}
            </g>
          </>
        )}

        {/* lighting overlay on floor */}
        <rect x={iso(0, roomD).x} y={iso(0, 0).y - params.ceiling_h_m}
          width={Math.abs(iso(roomW, 0).x - iso(0, roomD).x)}
          height={iso(roomW, roomD).y - iso(0, 0).y + params.ceiling_h_m + 1}
          fill="url(#lightOverlay)" pointerEvents="none" />
      </g>
    </svg>
  );
}

// ─── Compass ────────────────────────────────────────────────────────────────
function Compass() {
  return (
    <div className="compass" title="Iso view · NW">
      <svg viewBox="0 0 56 56" width="40" height="40">
        <circle cx="28" cy="28" r="20" fill="none" stroke="rgba(46,92,138,0.2)" strokeWidth="1" />
        <line x1="28" y1="10" x2="28" y2="46" stroke="rgba(46,92,138,0.15)" strokeWidth="1" />
        <line x1="10" y1="28" x2="46" y2="28" stroke="rgba(46,92,138,0.15)" strokeWidth="1" />
        <polygon points="28,8 32,18 28,16 24,18" fill="var(--accent)" />
        <text x="28" y="6" textAnchor="middle" fontSize="6.5" fontFamily="var(--mono)" fill="var(--accent)" fontWeight="600">N</text>
      </svg>
    </div>
  );
}

Object.assign(window, { Scene, Compass });
