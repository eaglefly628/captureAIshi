import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { FlyOrbitControls } from './fly_orbit_controls.js';

const LIGHTING = {
  warehouse_sodium: { sun: 0xffcc88, sunI: 1.4, fill: 0xffaa55, fillI: 0.5, ambient: 0x6b4a20, ambientI: 0.35, sky: 0x4a3a20 },
  cool_white:      { sun: 0xeef4ff, sunI: 1.5, fill: 0xb8c8e0, fillI: 0.45, ambient: 0x2a3242, ambientI: 0.4,  sky: 0x202838 },
  mixed:           { sun: 0xffe0b0, sunI: 1.3, fill: 0xfff0c0, fillI: 0.5, ambient: 0x4a3828, ambientI: 0.35, sky: 0x382818 },
  indoor_tungsten: { sun: 0xffd8a0, sunI: 1.3, fill: 0xfff0b0, fillI: 0.5, ambient: 0x4a3018, ambientI: 0.4,  sky: 0x2a1a0a },
  cool_daylight:   { sun: 0xe8f0ff, sunI: 1.6, fill: 0xccdaff, fillI: 0.5, ambient: 0x1a2030, ambientI: 0.5,  sky: 0x101824 },
  evening_warm:    { sun: 0xff7a35, sunI: 1.4, fill: 0xffb070, fillI: 0.55, ambient: 0x3a1808, ambientI: 0.4, sky: 0x281008 },
  halogen_spot:    { sun: 0xfff5d0, sunI: 1.8, fill: 0xfff0a0, fillI: 0.4, ambient: 0x1f1a10, ambientI: 0.3,  sky: 0x0a0a0a },
};

const SOFA_DIM = {
  sectional:    { w: 3.2, d: 1.1, h: 0.85, cushions: 3 },
  loveseat:     { w: 1.8, d: 0.95, h: 0.78, cushions: 2 },
  chesterfield: { w: 2.6, d: 1.05, h: 0.95, cushions: 2 },
};

const MAT_CACHE = {};
function mat(key, opts) {
  if (!MAT_CACHE[key]) {
    MAT_CACHE[key] = new THREE.MeshStandardMaterial(opts);
  }
  return MAT_CACHE[key];
}

export class SceneStage {
  constructor(canvas) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.1;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0a0c12);
    this.scene.fog = new THREE.Fog(0x0a0c12, 50, 140);

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(this.renderer), 0.04).texture;

    this.camera = new THREE.PerspectiveCamera(50, 1, 0.1, 200);
    this.camera.position.set(12, 7, 16);

    this.controls = new FlyOrbitControls(this.camera, canvas);
    this.controls.target.set(0, 1, 0);

    this.sceneGroup = new THREE.Group();
    this.scene.add(this.sceneGroup);

    this.thumbnailMarker = this._makeThumbnailMarker();
    this.scene.add(this.thumbnailMarker);
    this.thumbnailMarker.visible = false;

    this._lights = [];
    this._instanceCount = 0;
    this._handleResize();
    window.addEventListener('resize', () => this._handleResize());
    this._loop();
  }

  setScene(sceneType, params, sceneCfg) {
    this.sceneGroup.clear();
    this._instanceCount = 0;
    this._applyLighting(params.lighting_preset || this._defaultLight(sceneType));

    if (sceneType === 'warehouse') this._buildWarehouse(params, sceneCfg);
    else if (sceneType === 'living_room') this._buildLivingRoom(params, sceneCfg);
    else if (sceneType === 'industrial_corner') this._buildIndustrial(params, sceneCfg);

    if (sceneCfg && sceneCfg.thumbnail_camera) {
      const tc = sceneCfg.thumbnail_camera;
      const scale = sceneType === 'warehouse' ? 0.5 : 1;
      this.thumbnailMarker.position.set(tc.pos[0] * scale, tc.pos[2], tc.pos[1] * scale);
      this.thumbnailMarker.visible = true;
    } else {
      this.thumbnailMarker.visible = false;
    }

    this._setDefaultIsoCamera(sceneType, sceneCfg);
    return this._instanceCount;
  }

  _setDefaultIsoCamera(sceneType, sceneCfg) {
    const scale = sceneType === 'warehouse' ? 0.5 : 1;
    const sx = (sceneCfg.size_m && sceneCfg.size_m[0] || 10) * scale;
    const sz = (sceneCfg.size_m && sceneCfg.size_m[1] || 10) * scale;
    const maxDim = Math.max(sx, sz);
    const dist = maxDim * 0.85;
    this.controls.target.set(0, 0.6, 0);
    this.camera.position.set(dist * 0.55, dist * 0.95, dist * 0.55);
    this.controls._syncFromCamera();
  }

  flyThumbnailCamera(sceneCfg) {
    if (!sceneCfg || !sceneCfg.thumbnail_camera) return;
    const tc = sceneCfg.thumbnail_camera;
    const scale = sceneCfg.scene_type === 'warehouse' ? 0.5 : 1;
    const lookAt = new THREE.Vector3(tc.look_at[0] * scale, tc.look_at[2], tc.look_at[1] * scale);
    this.controls.focus(lookAt, 14);
    this.camera.position.set(tc.pos[0] * scale, tc.pos[2], tc.pos[1] * scale);
    this.controls._syncFromCamera();
  }

  _defaultLight(s) {
    return s === 'warehouse' ? 'warehouse_sodium'
         : s === 'industrial_corner' ? 'indoor_tungsten'
         : 'indoor_tungsten';
  }

  _applyLighting(preset) {
    this._lights.forEach(l => this.scene.remove(l));
    this._lights = [];
    const cfg = LIGHTING[preset] || LIGHTING.warehouse_sodium;
    const ambient = new THREE.HemisphereLight(cfg.sun, cfg.sky, cfg.ambientI);
    const sun = new THREE.DirectionalLight(cfg.sun, cfg.sunI);
    sun.position.set(10, 22, 8);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.camera.left = -25;
    sun.shadow.camera.right = 25;
    sun.shadow.camera.top = 25;
    sun.shadow.camera.bottom = -25;
    sun.shadow.camera.near = 0.5;
    sun.shadow.camera.far = 80;
    sun.shadow.bias = -0.0008;
    sun.shadow.normalBias = 0.02;
    const fill = new THREE.DirectionalLight(cfg.fill, cfg.fillI);
    fill.position.set(-8, 14, -10);
    const rim = new THREE.DirectionalLight(cfg.fill, cfg.fillI * 0.5);
    rim.position.set(-4, 6, 12);
    this.scene.add(ambient, sun, fill, rim);
    this._lights = [ambient, sun, fill, rim];
    this.scene.background = new THREE.Color(cfg.sky).lerp(new THREE.Color(0x000000), 0.65);
  }

  _addFloorWalls(sizeX, sizeZ, wallHeight, floorColor, wallColor, _ceilingColorIgnored, accentColor) {
    const halfX = sizeX / 2;
    const halfZ = sizeZ / 2;

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(sizeX, sizeZ),
      new THREE.MeshStandardMaterial({ color: floorColor, roughness: 0.78, metalness: 0.0 })
    );
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    this.sceneGroup.add(floor);

    if (accentColor) {
      for (let i = -halfX + 2; i < halfX; i += 4) {
        const stripe = new THREE.Mesh(
          new THREE.PlaneGeometry(0.12, sizeZ - 1),
          new THREE.MeshStandardMaterial({ color: accentColor, roughness: 0.55, emissive: accentColor, emissiveIntensity: 0.05 })
        );
        stripe.rotation.x = -Math.PI / 2;
        stripe.position.set(i, 0.011, 0);
        this.sceneGroup.add(stripe);
      }
    }

    const lowWallH = Math.min(wallHeight, 1.2);
    const wallMat = new THREE.MeshStandardMaterial({ color: wallColor, roughness: 0.92, metalness: 0.02 });
    const wallThick = 0.18;
    for (const [x, z, w, d] of [
      [0, -halfZ, sizeX, wallThick],
      [0,  halfZ, sizeX, wallThick],
      [-halfX, 0, wallThick, sizeZ],
      [ halfX, 0, wallThick, sizeZ],
    ]) {
      const wall = new THREE.Mesh(new THREE.BoxGeometry(w, lowWallH, d), wallMat);
      wall.position.set(x, lowWallH / 2, z);
      wall.castShadow = true;
      wall.receiveShadow = true;
      this.sceneGroup.add(wall);
    }
  }

  _buildWarehouse(p, cfg) {
    const sizeX = (cfg.size_m && cfg.size_m[0] || 50) * 0.5;
    const sizeZ = (cfg.size_m && cfg.size_m[1] || 50) * 0.5;
    const halfX = sizeX / 2;
    const halfZ = sizeZ / 2;

    this._addFloorWalls(sizeX, sizeZ, 6, 0x3a3a40, 0x46484e, 0x1a1a1f, 0xf5b942);

    const density = p.shelf_density ?? 0.7;
    const alley = (p.alley_width_m ?? 2.4) * 0.5;
    const rows = Math.max(2, Math.floor(density * 6 + 1));
    const cols = Math.max(3, Math.floor(density * 8 + 1));
    const groupW = (sizeX - 4) / cols;
    const groupD = (sizeZ - alley * 2 - 3) / rows;
    const shelfW = groupW * 0.82;
    const shelfD = groupD * 0.55;
    const shelfH = 3.2;

    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const x = -halfX + 2 + c * groupW + groupW * 0.5;
        const z = -halfZ + 1.5 + r * (groupD + 0.3);
        const rack = this._makeShelfRack(shelfW, shelfH, shelfD, 4, p.pallet_load_factor ?? 0.6);
        rack.position.set(x, 0, z);
        this.sceneGroup.add(rack);
        this._instanceCount += 1;
      }
    }

    const forkliftCount = p.forklift_count ?? 1;
    for (let i = 0; i < forkliftCount; i++) {
      const fk = this._makeForklift();
      fk.position.set(
        -halfX + 4 + (i * (sizeX - 8)) / Math.max(1, forkliftCount - 1 || 1),
        0,
        alley * (i % 2 === 0 ? 1.5 : -1.5)
      );
      fk.rotation.y = (i % 2 === 0 ? 0.2 : -0.2) + (i / forkliftCount) * 0.5;
      this.sceneGroup.add(fk);
      this._instanceCount += 1;
    }

    for (let i = 0; i < 8; i++) {
      const lamp = this._makeCeilingLamp(0xfff0c0, 0xffb84d);
      lamp.position.set(
        -halfX + sizeX * ((i + 0.5) / 8),
        5.7,
        (i % 2 === 0 ? -1 : 1) * (sizeZ * 0.3)
      );
      this.sceneGroup.add(lamp);
    }
  }

  _makeShelfRack(w, h, d, levels, loadFactor) {
    const g = new THREE.Group();
    const postR = 0.06;
    const postMat = new THREE.MeshStandardMaterial({ color: 0xd97b1a, roughness: 0.45, metalness: 0.5 });
    const beamMat = new THREE.MeshStandardMaterial({ color: 0xc66614, roughness: 0.5, metalness: 0.55 });
    const palletMat = new THREE.MeshStandardMaterial({ color: 0x8a5e3a, roughness: 0.88, metalness: 0.0 });
    const cargoColors = [0x9b6d3a, 0x6b5a4a, 0x5e4a32, 0x8a7050, 0x755b3a];

    for (const [px, pz] of [[-w/2, -d/2], [w/2, -d/2], [-w/2, d/2], [w/2, d/2]]) {
      const post = new THREE.Mesh(new THREE.BoxGeometry(postR * 2, h, postR * 2), postMat);
      post.position.set(px, h / 2, pz);
      post.castShadow = true;
      g.add(post);
    }

    for (let lv = 0; lv < levels; lv++) {
      const y = (h - 0.3) * ((lv + 0.5) / levels) + 0.05;
      const shelf = new THREE.Mesh(
        new THREE.BoxGeometry(w + 0.04, 0.06, d),
        beamMat
      );
      shelf.position.y = y;
      shelf.castShadow = true;
      shelf.receiveShadow = true;
      g.add(shelf);

      const cellsX = 2;
      for (let cx = 0; cx < cellsX; cx++) {
        if (Math.random() > loadFactor) continue;
        const pallet = new THREE.Mesh(
          new THREE.BoxGeometry(w / cellsX - 0.1, 0.14, d - 0.1),
          palletMat
        );
        pallet.position.set(-w/2 + (cx + 0.5) * (w / cellsX), y + 0.1, 0);
        pallet.castShadow = true;
        pallet.receiveShadow = true;
        g.add(pallet);

        const cargoH = 0.4 + Math.random() * 0.6;
        const cargo = new THREE.Mesh(
          new THREE.BoxGeometry(w / cellsX - 0.25, cargoH, d - 0.25),
          new THREE.MeshStandardMaterial({
            color: cargoColors[Math.floor(Math.random() * cargoColors.length)],
            roughness: 0.85,
          })
        );
        cargo.position.set(pallet.position.x, y + 0.14 + cargoH / 2, 0);
        cargo.castShadow = true;
        g.add(cargo);
      }
    }
    return g;
  }

  _makeForklift() {
    const g = new THREE.Group();
    const yellow = new THREE.MeshStandardMaterial({ color: 0xf5b91f, roughness: 0.45, metalness: 0.35 });
    const yellowDark = new THREE.MeshStandardMaterial({ color: 0xc89218, roughness: 0.5, metalness: 0.3 });
    const black = new THREE.MeshStandardMaterial({ color: 0x16181c, roughness: 0.85 });
    const steel = new THREE.MeshStandardMaterial({ color: 0x4a4a52, metalness: 0.7, roughness: 0.4 });
    const glass = new THREE.MeshStandardMaterial({ color: 0x9bbfd9, metalness: 0.1, roughness: 0.05, transparent: true, opacity: 0.5 });

    const body = new THREE.Mesh(new THREE.BoxGeometry(1.05, 0.85, 1.8), yellow);
    body.position.y = 0.55;
    body.castShadow = true;
    g.add(body);

    const counterweight = new THREE.Mesh(new THREE.BoxGeometry(1.0, 0.5, 0.45), yellowDark);
    counterweight.position.set(0, 0.55, -0.95);
    counterweight.castShadow = true;
    g.add(counterweight);

    const cabBase = new THREE.Mesh(new THREE.BoxGeometry(0.95, 0.85, 0.85), yellow);
    cabBase.position.set(0, 1.35, -0.25);
    cabBase.castShadow = true;
    g.add(cabBase);

    const windshield = new THREE.Mesh(new THREE.PlaneGeometry(0.85, 0.55), glass);
    windshield.position.set(0, 1.5, 0.18);
    windshield.rotation.x = -0.18;
    g.add(windshield);

    const cabRoof = new THREE.Mesh(new THREE.BoxGeometry(1.0, 0.06, 0.95), yellowDark);
    cabRoof.position.set(0, 1.85, -0.25);
    cabRoof.castShadow = true;
    g.add(cabRoof);
    for (const [x, z] of [[-0.45, 0.15], [0.45, 0.15], [-0.45, -0.65], [0.45, -0.65]]) {
      const pillar = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.5, 0.06), steel);
      pillar.position.set(x, 1.6, z);
      g.add(pillar);
    }

    const mast = new THREE.Group();
    for (const x of [-0.18, 0.18]) {
      const rail = new THREE.Mesh(new THREE.BoxGeometry(0.08, 2.4, 0.08), steel);
      rail.position.set(x, 1.2, 0);
      rail.castShadow = true;
      mast.add(rail);
    }
    const carriage = new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.4, 0.12), steel);
    carriage.position.set(0, 0.5, 0.08);
    mast.add(carriage);
    for (const x of [-0.2, 0.2]) {
      const fork = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.05, 0.75), steel);
      fork.position.set(x, 0.3, 0.45);
      fork.castShadow = true;
      mast.add(fork);
    }
    mast.position.set(0, 0, 0.95);
    g.add(mast);

    for (const [x, z] of [[-0.6, 0.65], [0.6, 0.65], [-0.5, -0.7], [0.5, -0.7]]) {
      const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 0.18, 16), black);
      wheel.rotation.z = Math.PI / 2;
      wheel.position.set(x, 0.22, z);
      wheel.castShadow = true;
      g.add(wheel);
    }

    const headlight = new THREE.Mesh(
      new THREE.CircleGeometry(0.08, 12),
      new THREE.MeshStandardMaterial({ color: 0xfff8d0, emissive: 0xfff0a0, emissiveIntensity: 0.8 })
    );
    headlight.position.set(0.3, 0.65, 0.91);
    g.add(headlight);
    const headlight2 = headlight.clone();
    headlight2.position.x = -0.3;
    g.add(headlight2);

    return g;
  }

  _makeCeilingLamp(housing, emissive) {
    const g = new THREE.Group();
    const shell = new THREE.Mesh(
      new THREE.BoxGeometry(1.6, 0.18, 0.5),
      new THREE.MeshStandardMaterial({ color: 0x9a9aa0, metalness: 0.7, roughness: 0.4 })
    );
    g.add(shell);
    const tube = new THREE.Mesh(
      new THREE.BoxGeometry(1.4, 0.08, 0.32),
      new THREE.MeshStandardMaterial({
        color: housing, emissive: emissive, emissiveIntensity: 2.2,
      })
    );
    tube.position.y = -0.05;
    g.add(tube);
    return g;
  }

  _buildLivingRoom(p, cfg) {
    const sizeX = (cfg.size_m && cfg.size_m[0]) || 5;
    const sizeZ = (cfg.size_m && cfg.size_m[1]) || 7;
    const halfX = sizeX / 2;
    const halfZ = sizeZ / 2;

    this._addFloorWalls(sizeX, sizeZ, 2.7, 0x8a6f4a, 0xc4a987, 0xe8dcc4);

    if (p.rug_present !== false) {
      const rug = new THREE.Mesh(
        new THREE.PlaneGeometry(sizeX * 0.65, sizeZ * 0.42),
        new THREE.MeshStandardMaterial({ color: 0x8a3d2a, roughness: 0.95 })
      );
      rug.rotation.x = -Math.PI / 2;
      rug.position.set(0, 0.012, 0.2);
      rug.receiveShadow = true;
      this.sceneGroup.add(rug);
      const rugInner = new THREE.Mesh(
        new THREE.PlaneGeometry(sizeX * 0.55, sizeZ * 0.32),
        new THREE.MeshStandardMaterial({ color: 0xc25a3a, roughness: 0.93 })
      );
      rugInner.rotation.x = -Math.PI / 2;
      rugInner.position.set(0, 0.013, 0.2);
      this.sceneGroup.add(rugInner);
      this._instanceCount += 1;
    }

    const sd = SOFA_DIM[p.sofa_style || 'sectional'];
    const sofa = this._makeSofa(sd);
    sofa.position.set(0, 0, -halfZ + sd.d / 2 + 0.2);
    this.sceneGroup.add(sofa);
    this._instanceCount += 1;

    const table = this._makeCoffeeTable(1.3, 0.42, 0.65);
    table.position.set(0, 0, -halfZ + 2.1);
    this.sceneGroup.add(table);
    this._instanceCount += 1;

    const fdens = p.furniture_density ?? 0.55;
    if (fdens > 0.4) {
      const tvUnit = new THREE.Mesh(
        new THREE.BoxGeometry(2.0, 0.5, 0.4),
        new THREE.MeshStandardMaterial({ color: 0x2a1f15, roughness: 0.4, metalness: 0.1 })
      );
      tvUnit.position.set(0, 0.25, halfZ - 0.4);
      tvUnit.castShadow = true;
      this.sceneGroup.add(tvUnit);
      const tv = new THREE.Mesh(
        new THREE.BoxGeometry(1.7, 1.0, 0.06),
        new THREE.MeshStandardMaterial({ color: 0x0a0a0d, emissive: 0x2a3a55, emissiveIntensity: 0.6, roughness: 0.2 })
      );
      tv.position.set(0, 1.3, halfZ - 0.3);
      this.sceneGroup.add(tv);
      this._instanceCount += 2;
    }
    if (fdens > 0.6) {
      const chair = this._makeArmchair();
      chair.position.set(halfX - 0.9, 0, -0.5);
      chair.rotation.y = -Math.PI / 4;
      this.sceneGroup.add(chair);
      this._instanceCount += 1;
    }

    const decor = p.decor_variety ?? 5;
    const clutter = p.clutter_level ?? 0.3;
    for (let i = 0; i < decor; i++) {
      const item = this._makeDecorItem(i, clutter);
      const a = (i / decor) * Math.PI * 2 + 0.5;
      const r = 1.4 + Math.random() * 1.2;
      item.position.set(Math.cos(a) * r, 0.42, Math.sin(a) * r * 0.7 - halfZ + 2.1);
      this.sceneGroup.add(item);
      this._instanceCount += 1;
    }

    const lampPos = [
      [halfX - 0.4, 1.8, -halfZ + 0.8, 0xffcc88, 2.5],
      [-halfX + 0.4, 1.8, halfZ - 0.8, 0xffcc88, 1.8],
    ];
    for (const [x, y, z, color, intensity] of lampPos) {
      const pl = new THREE.PointLight(color, intensity, 8, 1.5);
      pl.position.set(x, y, z);
      pl.castShadow = false;
      this.scene.add(pl);
      this._lights.push(pl);
      const shade = new THREE.Mesh(
        new THREE.ConeGeometry(0.22, 0.3, 16, 1, true),
        new THREE.MeshStandardMaterial({ color: 0xf0d8a8, emissive: 0xfff0c0, emissiveIntensity: 0.7, side: THREE.DoubleSide })
      );
      shade.position.set(x, y, z);
      shade.rotation.x = Math.PI;
      this.sceneGroup.add(shade);
    }
  }

  _makeSofa(sd) {
    const g = new THREE.Group();
    const fabric = new THREE.MeshStandardMaterial({ color: 0x5a6878, roughness: 0.85 });
    const fabricDark = new THREE.MeshStandardMaterial({ color: 0x4a5868, roughness: 0.88 });
    const woodMat = new THREE.MeshStandardMaterial({ color: 0x3a2618, roughness: 0.7 });

    const base = new THREE.Mesh(new THREE.BoxGeometry(sd.w, 0.35, sd.d), fabric);
    base.position.y = 0.2;
    base.castShadow = true;
    base.receiveShadow = true;
    g.add(base);

    const back = new THREE.Mesh(new THREE.BoxGeometry(sd.w, sd.h - 0.35, 0.22), fabricDark);
    back.position.set(0, 0.2 + (sd.h - 0.35) / 2, -sd.d / 2 + 0.11);
    back.castShadow = true;
    g.add(back);

    for (const dx of [-1, 1]) {
      const arm = new THREE.Mesh(new THREE.BoxGeometry(0.22, sd.h * 0.6, sd.d), fabricDark);
      arm.position.set(dx * (sd.w / 2 - 0.11), 0.2 + sd.h * 0.3, 0);
      arm.castShadow = true;
      g.add(arm);
    }

    const cushionW = (sd.w - 0.5) / sd.cushions;
    for (let i = 0; i < sd.cushions; i++) {
      const cushion = new THREE.Mesh(
        new THREE.BoxGeometry(cushionW - 0.05, 0.18, sd.d - 0.3),
        fabric
      );
      cushion.position.set(
        -sd.w / 2 + 0.25 + (i + 0.5) * cushionW,
        0.45,
        0.05
      );
      cushion.castShadow = true;
      g.add(cushion);
    }

    for (const dx of [-0.7, 0.7]) {
      const pillow = new THREE.Mesh(
        new THREE.BoxGeometry(0.32, 0.12, 0.32),
        new THREE.MeshStandardMaterial({ color: 0xd4a574, roughness: 0.8 })
      );
      pillow.position.set(dx, 0.66, -sd.d / 2 + 0.4);
      pillow.rotation.z = dx > 0 ? -0.15 : 0.15;
      pillow.castShadow = true;
      g.add(pillow);
    }

    for (const [dx, dz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
      const leg = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.08, 0.07), woodMat);
      leg.position.set(dx * (sd.w / 2 - 0.15), 0.04, dz * (sd.d / 2 - 0.12));
      g.add(leg);
    }

    return g;
  }

  _makeCoffeeTable(w, h, d) {
    const g = new THREE.Group();
    const wood = new THREE.MeshStandardMaterial({ color: 0x3a2818, roughness: 0.45, metalness: 0.05 });
    const top = new THREE.Mesh(new THREE.BoxGeometry(w, 0.04, d), wood);
    top.position.y = h;
    top.castShadow = true;
    top.receiveShadow = true;
    g.add(top);
    for (const [dx, dz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
      const leg = new THREE.Mesh(new THREE.BoxGeometry(0.04, h, 0.04), wood);
      leg.position.set(dx * (w / 2 - 0.06), h / 2, dz * (d / 2 - 0.06));
      leg.castShadow = true;
      g.add(leg);
    }
    return g;
  }

  _makeArmchair() {
    const g = new THREE.Group();
    const fabric = new THREE.MeshStandardMaterial({ color: 0x6b5a48, roughness: 0.85 });
    const base = new THREE.Mesh(new THREE.BoxGeometry(0.85, 0.4, 0.85), fabric);
    base.position.y = 0.22;
    base.castShadow = true;
    g.add(base);
    const back = new THREE.Mesh(new THREE.BoxGeometry(0.85, 0.7, 0.18), fabric);
    back.position.set(0, 0.55, -0.34);
    back.castShadow = true;
    g.add(back);
    for (const dx of [-1, 1]) {
      const arm = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.4, 0.85), fabric);
      arm.position.set(dx * 0.34, 0.42, 0);
      arm.castShadow = true;
      g.add(arm);
    }
    return g;
  }

  _makeDecorItem(seed, clutter) {
    const types = ['vase', 'book', 'plant', 'sculpture'];
    const type = types[seed % types.length];
    const mat1 = new THREE.MeshStandardMaterial({
      color: [0xd4a574, 0x9a5a3a, 0x6a8a5a, 0xc8c0a8][seed % 4],
      roughness: 0.5,
    });
    if (type === 'vase') {
      return new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.05, 0.22, 12), mat1);
    } else if (type === 'book') {
      return new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.04, 0.22), mat1);
    } else if (type === 'plant') {
      const g = new THREE.Group();
      const pot = new THREE.Mesh(
        new THREE.CylinderGeometry(0.08, 0.06, 0.12, 12),
        new THREE.MeshStandardMaterial({ color: 0x5a3a28, roughness: 0.7 })
      );
      g.add(pot);
      const leaves = new THREE.Mesh(
        new THREE.SphereGeometry(0.13, 8, 6),
        new THREE.MeshStandardMaterial({ color: 0x4a7a3a, roughness: 0.85 })
      );
      leaves.position.y = 0.18;
      g.add(leaves);
      return g;
    } else {
      return new THREE.Mesh(new THREE.IcosahedronGeometry(0.1, 0), mat1);
    }
  }

  _buildIndustrial(p, cfg) {
    const sizeX = (cfg.size_m && cfg.size_m[0]) || 8;
    const sizeZ = (cfg.size_m && cfg.size_m[1]) || 8;
    const halfX = sizeX / 2;
    const halfZ = sizeZ / 2;

    const oil = p.oil_stain_amount ?? 0.25;
    const floorColor = new THREE.Color().setHSL(0.05, 0.08, 0.22 - oil * 0.08).getHex();
    this._addFloorWalls(sizeX, sizeZ, 4, floorColor, 0x4a4a52, 0x1f1f24, 0xc4a230);

    for (let i = 0; i < Math.floor(oil * 8); i++) {
      const stain = new THREE.Mesh(
        new THREE.CircleGeometry(0.2 + Math.random() * 0.3, 10),
        new THREE.MeshStandardMaterial({ color: 0x14140a, roughness: 0.95, transparent: true, opacity: 0.7 })
      );
      stain.rotation.x = -Math.PI / 2;
      stain.position.set((Math.random() - 0.5) * sizeX * 0.8, 0.015, (Math.random() - 0.5) * sizeZ * 0.8);
      this.sceneGroup.add(stain);
    }

    const machineCount = p.machine_count ?? 2;
    for (let i = 0; i < machineCount; i++) {
      const m = this._makeMachine(i);
      m.position.set(
        -halfX + 1.4 + (sizeX - 2.8) * ((i + 0.5) / machineCount),
        0,
        -halfZ + 1.5
      );
      this.sceneGroup.add(m);
      this._instanceCount += 1;
    }

    const board = this._makeToolboard(sizeX * 0.55, 1.3, p.toolboard_density ?? 0.7);
    board.position.set(0, 1.45, -halfZ + 0.18);
    this.sceneGroup.add(board);
    this._instanceCount += 1;

    const pipeCount = p.pipe_complexity ?? 3;
    const pipeMat = new THREE.MeshStandardMaterial({ color: 0x8a7050, metalness: 0.65, roughness: 0.45 });
    for (let i = 0; i < pipeCount; i++) {
      const pipe = new THREE.Mesh(
        new THREE.CylinderGeometry(0.075, 0.075, sizeX, 12),
        pipeMat
      );
      pipe.rotation.z = Math.PI / 2;
      pipe.position.set(0, 3.4 + i * 0.18, -halfZ + 0.6 + i * 0.42);
      pipe.castShadow = true;
      this.sceneGroup.add(pipe);

      for (let bracket = -halfX + 1; bracket < halfX; bracket += 2.5) {
        const br = new THREE.Mesh(
          new THREE.BoxGeometry(0.04, 0.18, 0.1),
          pipeMat
        );
        br.position.set(bracket, pipe.position.y - 0.08, pipe.position.z);
        this.sceneGroup.add(br);
      }
    }

    const crateCount = p.crate_count ?? 3;
    for (let i = 0; i < crateCount; i++) {
      const c = this._makeCrate();
      c.position.set(
        halfX - 1.2 - Math.random() * 0.8,
        i % 2 === 0 ? 0.3 : 0.92,
        halfZ - 1.2 - i * 0.75
      );
      c.rotation.y = Math.random() * 0.4 - 0.2;
      this.sceneGroup.add(c);
      this._instanceCount += 1;
    }

    const spot = new THREE.SpotLight(0xfff0d0, 1.5, 12, Math.PI / 5, 0.4, 1.5);
    spot.position.set(0, 3.6, -halfZ + 1);
    spot.target.position.set(0, 0.5, -halfZ + 1.5);
    spot.castShadow = true;
    spot.shadow.mapSize.set(1024, 1024);
    this.scene.add(spot, spot.target);
    this._lights.push(spot, spot.target);
  }

  _makeMachine(seed) {
    const g = new THREE.Group();
    const palette = [
      [0x4a5260, 0x2a323a, 0xffaa28],
      [0x5e5a50, 0x3e3a30, 0x40c878],
      [0x42504a, 0x222a26, 0xff6a28],
      [0x504448, 0x302428, 0xffd040],
    ];
    const [bodyC, dark, light] = palette[seed % palette.length];
    const body = new THREE.Mesh(
      new THREE.BoxGeometry(1.3, 1.5, 1.1),
      new THREE.MeshStandardMaterial({ color: bodyC, roughness: 0.55, metalness: 0.4 })
    );
    body.position.y = 0.75;
    body.castShadow = true;
    g.add(body);

    const base = new THREE.Mesh(
      new THREE.BoxGeometry(1.5, 0.12, 1.3),
      new THREE.MeshStandardMaterial({ color: dark, roughness: 0.7 })
    );
    base.position.y = 0.06;
    base.castShadow = true;
    g.add(base);

    const head = new THREE.Mesh(
      new THREE.BoxGeometry(0.7, 0.4, 0.5),
      new THREE.MeshStandardMaterial({ color: dark, roughness: 0.5 })
    );
    head.position.set(0, 1.7, 0.05);
    head.castShadow = true;
    g.add(head);

    const tool = new THREE.Mesh(
      new THREE.CylinderGeometry(0.04, 0.03, 0.35, 8),
      new THREE.MeshStandardMaterial({ color: 0xc0c0c8, metalness: 0.85, roughness: 0.25 })
    );
    tool.position.set(0, 1.32, 0.3);
    g.add(tool);

    const panel = new THREE.Mesh(
      new THREE.BoxGeometry(0.45, 0.32, 0.04),
      new THREE.MeshStandardMaterial({ color: 0x14181c, roughness: 0.3 })
    );
    panel.position.set(0.5, 1.1, 0.56);
    g.add(panel);
    const led = new THREE.Mesh(
      new THREE.BoxGeometry(0.04, 0.04, 0.02),
      new THREE.MeshStandardMaterial({ color: light, emissive: light, emissiveIntensity: 1.5 })
    );
    led.position.set(0.62, 1.22, 0.59);
    g.add(led);

    return g;
  }

  _makeToolboard(w, h, density) {
    const g = new THREE.Group();
    const board = new THREE.Mesh(
      new THREE.BoxGeometry(w, h, 0.05),
      new THREE.MeshStandardMaterial({ color: 0x6b3a22, roughness: 0.7 })
    );
    board.castShadow = true;
    g.add(board);

    const toolCount = Math.floor(density * 16);
    for (let i = 0; i < toolCount; i++) {
      const len = 0.18 + Math.random() * 0.22;
      const tool = new THREE.Mesh(
        new THREE.BoxGeometry(0.06, len, 0.04),
        new THREE.MeshStandardMaterial({ color: 0xc0c0c8, metalness: 0.7, roughness: 0.35 })
      );
      tool.position.set(
        -w / 2 + 0.25 + (w - 0.5) * (i / Math.max(1, toolCount - 1)),
        0.05 - (i % 2) * 0.18,
        0.05
      );
      g.add(tool);

      const hook = new THREE.Mesh(
        new THREE.BoxGeometry(0.025, 0.05, 0.04),
        new THREE.MeshStandardMaterial({ color: 0x4a4a4a, metalness: 0.6 })
      );
      hook.position.set(tool.position.x, tool.position.y + len / 2 + 0.04, 0.05);
      g.add(hook);
    }
    return g;
  }

  _makeCrate() {
    const g = new THREE.Group();
    const wood = new THREE.MeshStandardMaterial({ color: 0x8a5e34, roughness: 0.85 });
    const woodDark = new THREE.MeshStandardMaterial({ color: 0x603e20, roughness: 0.88 });
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.5, 0.6), wood);
    body.castShadow = true;
    g.add(body);
    for (const y of [-0.18, 0.18]) {
      for (const sign of [-1, 1]) {
        const plank = new THREE.Mesh(new THREE.BoxGeometry(0.62, 0.04, 0.04), woodDark);
        plank.position.set(0, y, sign * 0.31);
        g.add(plank);
      }
    }
    return g;
  }

  _makeThumbnailMarker() {
    const g = new THREE.Group();
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(0.4, 0.05, 12, 32),
      new THREE.MeshBasicMaterial({ color: 0xfb923c })
    );
    g.add(ring);
    const dot = new THREE.Mesh(
      new THREE.SphereGeometry(0.13, 16, 12),
      new THREE.MeshBasicMaterial({ color: 0xfb923c })
    );
    g.add(dot);
    const halo = new THREE.Mesh(
      new THREE.TorusGeometry(0.55, 0.015, 8, 32),
      new THREE.MeshBasicMaterial({ color: 0xfb923c, transparent: true, opacity: 0.4 })
    );
    g.add(halo);
    return g;
  }

  _handleResize() {
    const c = this.canvas;
    const w = c.clientWidth || c.parentElement.clientWidth;
    const h = c.clientHeight || c.parentElement.clientHeight;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  _loop() {
    requestAnimationFrame(() => this._loop());
    this.controls.update();
    if (this.thumbnailMarker.visible) {
      this.thumbnailMarker.rotation.y += 0.012;
      this.thumbnailMarker.children[2].scale.setScalar(1 + Math.sin(performance.now() * 0.003) * 0.15);
    }
    this.renderer.render(this.scene, this.camera);
  }
}
