import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const LIGHTING = {
  warehouse_sodium: { color: 0xffb84d, intensity: 1.2, ambient: 0x6b4a20 },
  cool_white:      { color: 0xe4ecff, intensity: 1.4, ambient: 0x202a3a },
  mixed:           { color: 0xffd99a, intensity: 1.1, ambient: 0x3a2f1f },
  indoor_tungsten: { color: 0xffcc88, intensity: 1.3, ambient: 0x3a2820 },
  cool_daylight:   { color: 0xdceaff, intensity: 1.4, ambient: 0x1c2230 },
  evening_warm:    { color: 0xff9a55, intensity: 1.3, ambient: 0x3a2010 },
  halogen_spot:    { color: 0xfff0c2, intensity: 1.6, ambient: 0x1f1c14 },
};

const SOFA_DIM = {
  sectional:    { w: 3.2, d: 1.1 },
  loveseat:     { w: 1.7, d: 0.9 },
  chesterfield: { w: 2.6, d: 1.0 },
};

export class SceneStage {
  constructor(canvas) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.shadowMap.enabled = false;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x060810);
    this.scene.fog = new THREE.Fog(0x060810, 30, 90);

    this.camera = new THREE.PerspectiveCamera(50, 1, 0.1, 200);
    this.camera.position.set(12, 7, 16);

    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.target.set(0, 1, 0);

    this.sceneGroup = new THREE.Group();
    this.scene.add(this.sceneGroup);

    this.thumbnailMarker = this._makeThumbnailMarker();
    this.scene.add(this.thumbnailMarker);
    this.thumbnailMarker.visible = false;

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
    return this._instanceCount;
  }

  flyThumbnailCamera(sceneCfg) {
    if (!sceneCfg || !sceneCfg.thumbnail_camera) return;
    const tc = sceneCfg.thumbnail_camera;
    const scale = sceneCfg.scene_type === 'warehouse' ? 0.5 : 1;
    this.camera.position.set(tc.pos[0] * scale, tc.pos[2], tc.pos[1] * scale);
    this.controls.target.set(tc.look_at[0] * scale, tc.look_at[2], tc.look_at[1] * scale);
  }

  _defaultLight(s) {
    return s === 'warehouse' ? 'warehouse_sodium'
         : s === 'industrial_corner' ? 'indoor_tungsten'
         : 'indoor_tungsten';
  }

  _applyLighting(preset) {
    if (this._lights) this._lights.forEach(l => this.scene.remove(l));
    const cfg = LIGHTING[preset] || LIGHTING.warehouse_sodium;
    const ambient = new THREE.AmbientLight(cfg.ambient, 0.6);
    const key = new THREE.DirectionalLight(cfg.color, cfg.intensity);
    key.position.set(8, 20, 6);
    const fill = new THREE.HemisphereLight(cfg.color, 0x101820, 0.4);
    this.scene.add(ambient, key, fill);
    this._lights = [ambient, key, fill];
  }

  _buildWarehouse(p, cfg) {
    const sizeX = (cfg.size_m && cfg.size_m[0] || 50) * 0.5;
    const sizeZ = (cfg.size_m && cfg.size_m[1] || 50) * 0.5;
    const halfX = sizeX / 2;
    const halfZ = sizeZ / 2;

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(sizeX, sizeZ),
      new THREE.MeshStandardMaterial({ color: 0x4a4a52, roughness: 0.85 })
    );
    floor.rotation.x = -Math.PI / 2;
    this.sceneGroup.add(floor);
    this._addRoof(sizeX, sizeZ, 0x1f1f24, 6);

    const wallMat = new THREE.MeshStandardMaterial({ color: 0x2a2a32, roughness: 0.9 });
    for (const [x, z, w, d] of [
      [0, -halfZ, sizeX, 0.2],
      [0,  halfZ, sizeX, 0.2],
      [-halfX, 0, 0.2, sizeZ],
      [ halfX, 0, 0.2, sizeZ],
    ]) {
      const wall = new THREE.Mesh(new THREE.BoxGeometry(w, 5, d), wallMat);
      wall.position.set(x, 2.5, z);
      this.sceneGroup.add(wall);
    }

    const density = p.shelf_density ?? 0.7;
    const alley = (p.alley_width_m ?? 2.4) * 0.5;
    const rows = Math.max(2, Math.floor(density * 7));
    const cols = Math.max(3, Math.floor(density * 9));
    const cellW = (sizeX - 4) / cols;
    const cellD = (sizeZ - alley * 2 - 3) / rows;
    const shelfMat = new THREE.MeshStandardMaterial({ color: 0x6b5239, roughness: 0.7 });
    const shelfGeo = new THREE.BoxGeometry(cellW * 0.85, 3.2, cellD * 0.55);
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const m = new THREE.Mesh(shelfGeo, shelfMat);
        m.position.set(
          -halfX + 2 + c * cellW + cellW * 0.5,
          1.6,
          -halfZ + 1.5 + r * (cellD + 0.3)
        );
        this.sceneGroup.add(m);
        this._instanceCount++;
      }
    }

    const palletGeo = new THREE.BoxGeometry(0.9, 0.18, 0.9);
    const palletMat = new THREE.MeshStandardMaterial({ color: 0x7a5430, roughness: 0.9 });
    const loadFactor = p.pallet_load_factor ?? 0.6;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        if (Math.random() > loadFactor) continue;
        const m = new THREE.Mesh(palletGeo, palletMat);
        m.position.set(
          -halfX + 2 + c * cellW + cellW * 0.5,
          0.1,
          -halfZ + 1.5 + r * (cellD + 0.3) + cellD * 0.55
        );
        this.sceneGroup.add(m);
        this._instanceCount++;
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
      this.sceneGroup.add(fk);
      this._instanceCount++;
    }

    for (let i = 0; i < 6; i++) {
      const lamp = new THREE.Mesh(
        new THREE.BoxGeometry(1.4, 0.2, 0.4),
        new THREE.MeshStandardMaterial({
          color: 0xfff0c0, emissive: 0xffb84d, emissiveIntensity: 1.2
        })
      );
      lamp.position.set(
        -halfX + sizeX * (i / 5),
        5.7,
        (i % 2 === 0 ? -1 : 1) * (sizeZ * 0.3)
      );
      this.sceneGroup.add(lamp);
    }
  }

  _buildLivingRoom(p, cfg) {
    const sizeX = cfg.size_m && cfg.size_m[0] || 5;
    const sizeZ = cfg.size_m && cfg.size_m[1] || 7;
    const halfX = sizeX / 2;
    const halfZ = sizeZ / 2;

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(sizeX, sizeZ),
      new THREE.MeshStandardMaterial({ color: 0x6b5a48, roughness: 0.55 })
    );
    floor.rotation.x = -Math.PI / 2;
    this.sceneGroup.add(floor);
    this._addRoof(sizeX, sizeZ, 0x1c1a18, 2.7);

    const wallMat = new THREE.MeshStandardMaterial({ color: 0xa89070, roughness: 0.9 });
    for (const [x, z, w, d] of [
      [0, -halfZ, sizeX, 0.15],
      [0,  halfZ, sizeX, 0.15],
      [-halfX, 0, 0.15, sizeZ],
      [ halfX, 0, 0.15, sizeZ],
    ]) {
      const wall = new THREE.Mesh(new THREE.BoxGeometry(w, 2.7, d), wallMat);
      wall.position.set(x, 1.35, z);
      this.sceneGroup.add(wall);
    }

    if (p.rug_present !== false) {
      const rug = new THREE.Mesh(
        new THREE.PlaneGeometry(sizeX * 0.6, sizeZ * 0.4),
        new THREE.MeshStandardMaterial({ color: 0x8a3a2a, roughness: 0.92 })
      );
      rug.rotation.x = -Math.PI / 2;
      rug.position.y = 0.01;
      this.sceneGroup.add(rug);
      this._instanceCount++;
    }

    const sd = SOFA_DIM[p.sofa_style || 'sectional'];
    const sofa = new THREE.Mesh(
      new THREE.BoxGeometry(sd.w, 0.85, sd.d),
      new THREE.MeshStandardMaterial({ color: 0x4a5a6b, roughness: 0.7 })
    );
    sofa.position.set(0, 0.42, -halfZ + 0.8);
    this.sceneGroup.add(sofa);
    this._instanceCount++;
    const sofaBack = new THREE.Mesh(
      new THREE.BoxGeometry(sd.w, 0.4, 0.2),
      new THREE.MeshStandardMaterial({ color: 0x3a4a5b, roughness: 0.7 })
    );
    sofaBack.position.set(0, 1.05, -halfZ + 0.4);
    this.sceneGroup.add(sofaBack);

    const table = new THREE.Mesh(
      new THREE.BoxGeometry(1.2, 0.45, 0.6),
      new THREE.MeshStandardMaterial({ color: 0x4a3a2a, roughness: 0.5 })
    );
    table.position.set(0, 0.22, -halfZ + 2);
    this.sceneGroup.add(table);
    this._instanceCount++;

    const fdens = p.furniture_density ?? 0.55;
    if (fdens > 0.4) {
      const tv = new THREE.Mesh(
        new THREE.BoxGeometry(1.6, 0.9, 0.08),
        new THREE.MeshStandardMaterial({ color: 0x101010, emissive: 0x222a3a, emissiveIntensity: 0.6 })
      );
      tv.position.set(0, 1.4, halfZ - 0.2);
      this.sceneGroup.add(tv);
      this._instanceCount++;
    }
    if (fdens > 0.6) {
      const chair = new THREE.Mesh(
        new THREE.BoxGeometry(0.8, 0.85, 0.8),
        new THREE.MeshStandardMaterial({ color: 0x6a5a4a, roughness: 0.7 })
      );
      chair.position.set(halfX - 1, 0.42, 0);
      this.sceneGroup.add(chair);
      this._instanceCount++;
    }

    const decor = p.decor_variety ?? 5;
    const clutter = p.clutter_level ?? 0.3;
    for (let i = 0; i < decor; i++) {
      const a = (i / decor) * Math.PI * 2;
      const r = 1.2 + Math.random() * 1.2;
      const x = Math.cos(a) * r;
      const z = Math.sin(a) * r * 0.6 - halfZ + 2;
      const item = new THREE.Mesh(
        new THREE.SphereGeometry(0.1 + Math.random() * 0.15, 8, 6),
        new THREE.MeshStandardMaterial({ color: 0xffcc88, roughness: 0.4 })
      );
      item.position.set(x, 0.5 + Math.random() * clutter * 0.5, z);
      this.sceneGroup.add(item);
      this._instanceCount++;
    }

    const lamp = new THREE.PointLight(0xffcc88, 1.5, 8);
    lamp.position.set(halfX - 0.8, 1.8, -halfZ + 1);
    this.sceneGroup.add(lamp);
  }

  _buildIndustrial(p, cfg) {
    const sizeX = cfg.size_m && cfg.size_m[0] || 8;
    const sizeZ = cfg.size_m && cfg.size_m[1] || 8;
    const halfX = sizeX / 2;
    const halfZ = sizeZ / 2;

    const oil = p.oil_stain_amount ?? 0.25;
    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(sizeX, sizeZ),
      new THREE.MeshStandardMaterial({
        color: new THREE.Color().setHSL(0.05, 0.05, 0.18 - oil * 0.07),
        roughness: 0.95,
      })
    );
    floor.rotation.x = -Math.PI / 2;
    this.sceneGroup.add(floor);
    this._addRoof(sizeX, sizeZ, 0x14141a, 4);

    const wallMat = new THREE.MeshStandardMaterial({ color: 0x3a3a44, roughness: 0.85 });
    for (const [x, z, w, d] of [
      [0, -halfZ, sizeX, 0.15],
      [0,  halfZ, sizeX, 0.15],
      [-halfX, 0, 0.15, sizeZ],
      [ halfX, 0, 0.15, sizeZ],
    ]) {
      const wall = new THREE.Mesh(new THREE.BoxGeometry(w, 4, d), wallMat);
      wall.position.set(x, 2, z);
      this.sceneGroup.add(wall);
    }

    const machineCount = p.machine_count ?? 2;
    const machColors = [0x4a4a52, 0x5a4a3a, 0x4a5a52, 0x603a4a];
    for (let i = 0; i < machineCount; i++) {
      const m = new THREE.Mesh(
        new THREE.BoxGeometry(1.4, 1.6, 1.2),
        new THREE.MeshStandardMaterial({ color: machColors[i % 4], roughness: 0.55 })
      );
      m.position.set(
        -halfX + 1 + (sizeX - 2) * ((i + 0.5) / machineCount),
        0.8,
        -halfZ + 1.2
      );
      this.sceneGroup.add(m);
      const head = new THREE.Mesh(
        new THREE.BoxGeometry(0.7, 0.4, 0.5),
        new THREE.MeshStandardMaterial({ color: 0x2a2a32, roughness: 0.5 })
      );
      head.position.set(m.position.x, 1.85, m.position.z + 0.1);
      this.sceneGroup.add(head);
      this._instanceCount += 2;
    }

    const toolboard = new THREE.Mesh(
      new THREE.BoxGeometry(sizeX * 0.5, 1.2, 0.08),
      new THREE.MeshStandardMaterial({ color: 0x6b3a2a, roughness: 0.6 })
    );
    toolboard.position.set(0, 1.5, -halfZ + 0.1);
    this.sceneGroup.add(toolboard);
    const tDens = p.toolboard_density ?? 0.7;
    const toolCount = Math.floor(tDens * 14);
    for (let i = 0; i < toolCount; i++) {
      const t = new THREE.Mesh(
        new THREE.BoxGeometry(0.12, 0.3 + Math.random() * 0.2, 0.04),
        new THREE.MeshStandardMaterial({ color: 0xc0c0c0, metalness: 0.6, roughness: 0.4 })
      );
      t.position.set(
        -sizeX * 0.22 + (sizeX * 0.44) * (i / Math.max(1, toolCount - 1)),
        1.4 + (i % 2 === 0 ? 0.2 : -0.1),
        -halfZ + 0.18
      );
      this.sceneGroup.add(t);
      this._instanceCount++;
    }

    const pipeCount = p.pipe_complexity ?? 3;
    const pipeMat = new THREE.MeshStandardMaterial({ color: 0x6a5a4a, metalness: 0.7, roughness: 0.5 });
    for (let i = 0; i < pipeCount; i++) {
      const pipe = new THREE.Mesh(
        new THREE.CylinderGeometry(0.08, 0.08, sizeX, 8),
        pipeMat
      );
      pipe.rotation.z = Math.PI / 2;
      pipe.position.set(0, 3.4 + i * 0.15, -halfZ + 0.5 + i * 0.4);
      this.sceneGroup.add(pipe);
      this._instanceCount++;
    }

    const crateCount = p.crate_count ?? 3;
    for (let i = 0; i < crateCount; i++) {
      const c = new THREE.Mesh(
        new THREE.BoxGeometry(0.6, 0.5, 0.6),
        new THREE.MeshStandardMaterial({ color: 0x7a5a3a, roughness: 0.85 })
      );
      const r = Math.random();
      c.position.set(
        halfX - 1.2 - r * 0.8,
        0.25 + (i % 2 === 0 ? 0.5 : 0),
        halfZ - 1 - i * 0.7
      );
      c.rotation.y = Math.random() * 0.4 - 0.2;
      this.sceneGroup.add(c);
      this._instanceCount++;
    }
  }

  _addRoof(sizeX, sizeZ, color, height) {
    const roof = new THREE.Mesh(
      new THREE.PlaneGeometry(sizeX, sizeZ),
      new THREE.MeshStandardMaterial({ color, roughness: 0.9, side: THREE.DoubleSide })
    );
    roof.rotation.x = Math.PI / 2;
    roof.position.y = height;
    this.sceneGroup.add(roof);
  }

  _makeForklift() {
    const g = new THREE.Group();
    const body = new THREE.Mesh(
      new THREE.BoxGeometry(1, 0.8, 1.6),
      new THREE.MeshStandardMaterial({ color: 0xf0b938, roughness: 0.5 })
    );
    body.position.y = 0.5;
    g.add(body);
    const cab = new THREE.Mesh(
      new THREE.BoxGeometry(0.9, 0.9, 0.7),
      new THREE.MeshStandardMaterial({ color: 0xc89028, roughness: 0.5 })
    );
    cab.position.set(0, 1.35, -0.3);
    g.add(cab);
    const mast = new THREE.Mesh(
      new THREE.BoxGeometry(0.15, 2, 0.15),
      new THREE.MeshStandardMaterial({ color: 0x222226, metalness: 0.4 })
    );
    mast.position.set(0, 1, 0.85);
    g.add(mast);
    for (const x of [-0.45, 0.45]) {
      for (const z of [-0.6, 0.6]) {
        const wheel = new THREE.Mesh(
          new THREE.CylinderGeometry(0.2, 0.2, 0.2, 12),
          new THREE.MeshStandardMaterial({ color: 0x181820, roughness: 0.9 })
        );
        wheel.rotation.z = Math.PI / 2;
        wheel.position.set(x, 0.2, z);
        g.add(wheel);
      }
    }
    return g;
  }

  _makeThumbnailMarker() {
    const g = new THREE.Group();
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(0.4, 0.04, 8, 24),
      new THREE.MeshBasicMaterial({ color: 0xfb923c })
    );
    g.add(ring);
    const dot = new THREE.Mesh(
      new THREE.SphereGeometry(0.12, 12, 8),
      new THREE.MeshBasicMaterial({ color: 0xfb923c })
    );
    g.add(dot);
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
    }
    this.renderer.render(this.scene, this.camera);
  }
}
