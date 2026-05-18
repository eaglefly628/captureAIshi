import * as THREE from 'three';

const PI2 = Math.PI / 2;

export class FlyOrbitControls {
  constructor(camera, dom) {
    this.camera = camera;
    this.dom = dom;
    this.target = new THREE.Vector3(0, 1, 0);

    this.sphericalDamping = 0.08;
    this.zoomDamping = 0.12;
    this.flySpeed = 4.0;
    this.sprintMultiplier = 5.0;
    this.lookSensitivity = 0.0028;
    this.panSensitivity = 0.005;
    this.zoomFactor = 0.92;
    this.minDistance = 1.0;
    this.maxDistance = 200.0;
    this.minPolar = 0.05;
    this.maxPolar = Math.PI - 0.05;

    this._spherical = new THREE.Spherical();
    this._sphericalDelta = new THREE.Spherical();
    this._panDelta = new THREE.Vector3();
    this._zoomDelta = 0;

    this._flying = false;
    this._flyYaw = 0;
    this._flyPitch = 0;
    this._flyVelocity = new THREE.Vector3();
    this._keys = new Set();

    this._lastTime = performance.now();
    this._mouseDownX = 0;
    this._mouseDownY = 0;
    this._activeButton = -1;

    this._syncFromCamera();
    this._bind();
  }

  _syncFromCamera() {
    const offset = this.camera.position.clone().sub(this.target);
    this._spherical.setFromVector3(offset);
    this._flyYaw = this._spherical.theta;
    this._flyPitch = PI2 - this._spherical.phi;
  }

  _bind() {
    const d = this.dom;
    d.addEventListener('contextmenu', (e) => e.preventDefault());
    d.addEventListener('mousedown', this._onMouseDown);
    window.addEventListener('mouseup', this._onMouseUp);
    window.addEventListener('mousemove', this._onMouseMove);
    d.addEventListener('wheel', this._onWheel, { passive: false });
    window.addEventListener('keydown', this._onKeyDown);
    window.addEventListener('keyup', this._onKeyUp);
    d.addEventListener('mouseleave', this._onMouseLeave);
  }

  dispose() {
    const d = this.dom;
    d.removeEventListener('contextmenu', (e) => e.preventDefault());
    d.removeEventListener('mousedown', this._onMouseDown);
    window.removeEventListener('mouseup', this._onMouseUp);
    window.removeEventListener('mousemove', this._onMouseMove);
    d.removeEventListener('wheel', this._onWheel);
    window.removeEventListener('keydown', this._onKeyDown);
    window.removeEventListener('keyup', this._onKeyUp);
    d.removeEventListener('mouseleave', this._onMouseLeave);
  }

  focus(point, distance = 12) {
    this.target.copy(point);
    const offset = this.camera.position.clone().sub(point).normalize().multiplyScalar(distance);
    this.camera.position.copy(point).add(offset);
    this._syncFromCamera();
  }

  _onMouseDown = (e) => {
    this._activeButton = e.button;
    this._mouseDownX = e.clientX;
    this._mouseDownY = e.clientY;
    if (e.button === 2) {
      this._flying = true;
      this._syncFromCamera();
      this.dom.style.cursor = 'crosshair';
    } else if (e.button === 0) {
      this.dom.style.cursor = 'grabbing';
    } else if (e.button === 1) {
      this.dom.style.cursor = 'move';
      e.preventDefault();
    }
  };

  _onMouseUp = (e) => {
    if (e.button === this._activeButton) {
      this._activeButton = -1;
    }
    if (e.button === 2) {
      this._flying = false;
    }
    this.dom.style.cursor = '';
  };

  _onMouseLeave = () => {
    this._activeButton = -1;
    this._flying = false;
    this.dom.style.cursor = '';
  };

  _onMouseMove = (e) => {
    if (this._activeButton < 0) return;
    const dx = e.movementX || 0;
    const dy = e.movementY || 0;
    if (this._activeButton === 2) {
      this._flyYaw -= dx * this.lookSensitivity;
      this._flyPitch -= dy * this.lookSensitivity;
      this._flyPitch = Math.max(-PI2 + 0.05, Math.min(PI2 - 0.05, this._flyPitch));
    } else if (this._activeButton === 0) {
      this._sphericalDelta.theta -= dx * 0.005;
      this._sphericalDelta.phi -= dy * 0.005;
    } else if (this._activeButton === 1) {
      this._panBy(-dx, dy);
    }
  };

  _onWheel = (e) => {
    e.preventDefault();
    const dir = Math.sign(e.deltaY);
    this._zoomDelta += dir;
  };

  _onKeyDown = (e) => {
    const k = e.key.toLowerCase();
    this._keys.add(k);
    if (k === 'f') {
      this.target.set(0, 1, 0);
      this._spherical.radius = 14;
      this._spherical.phi = Math.PI / 3;
      this._spherical.theta = Math.PI / 4;
      this._applySpherical();
    }
  };

  _onKeyUp = (e) => {
    this._keys.delete(e.key.toLowerCase());
  };

  _panBy(dx, dy) {
    const distance = this.camera.position.distanceTo(this.target);
    const factor = distance * this.panSensitivity;
    const xAxis = new THREE.Vector3();
    const yAxis = new THREE.Vector3();
    this.camera.matrix.extractBasis(xAxis, yAxis, new THREE.Vector3());
    this._panDelta.addScaledVector(xAxis, dx * factor);
    this._panDelta.addScaledVector(yAxis, dy * factor);
  }

  _applySpherical() {
    this._spherical.phi = Math.max(this.minPolar, Math.min(this.maxPolar, this._spherical.phi));
    this._spherical.radius = Math.max(this.minDistance, Math.min(this.maxDistance, this._spherical.radius));
    const offset = new THREE.Vector3().setFromSpherical(this._spherical);
    this.camera.position.copy(this.target).add(offset);
    this.camera.lookAt(this.target);
  }

  update() {
    const now = performance.now();
    const dt = Math.min(0.1, (now - this._lastTime) / 1000);
    this._lastTime = now;

    if (this._flying) {
      this._flyVelocity.set(0, 0, 0);
      const speed = this.flySpeed * (this._keys.has('shift') ? this.sprintMultiplier : 1);
      const forward = new THREE.Vector3();
      const right = new THREE.Vector3();
      this.camera.getWorldDirection(forward);
      right.crossVectors(forward, this.camera.up).normalize();
      if (this._keys.has('w')) this._flyVelocity.addScaledVector(forward, speed);
      if (this._keys.has('s')) this._flyVelocity.addScaledVector(forward, -speed);
      if (this._keys.has('d')) this._flyVelocity.addScaledVector(right, speed);
      if (this._keys.has('a')) this._flyVelocity.addScaledVector(right, -speed);
      if (this._keys.has('e')) this._flyVelocity.y += speed;
      if (this._keys.has('q')) this._flyVelocity.y -= speed;
      this.camera.position.addScaledVector(this._flyVelocity, dt);

      const quat = new THREE.Quaternion().setFromEuler(
        new THREE.Euler(this._flyPitch, this._flyYaw, 0, 'YXZ')
      );
      this.camera.quaternion.copy(quat);
      const look = new THREE.Vector3(0, 0, -1).applyQuaternion(quat);
      this.target.copy(this.camera.position).addScaledVector(look, 6);
      return true;
    }

    let dirty = false;
    if (this._sphericalDelta.theta || this._sphericalDelta.phi) {
      this._spherical.theta += this._sphericalDelta.theta * (1 - this.sphericalDamping);
      this._spherical.phi += this._sphericalDelta.phi * (1 - this.sphericalDamping);
      this._sphericalDelta.theta *= this.sphericalDamping;
      this._sphericalDelta.phi *= this.sphericalDamping;
      if (Math.abs(this._sphericalDelta.theta) < 1e-5) this._sphericalDelta.theta = 0;
      if (Math.abs(this._sphericalDelta.phi) < 1e-5) this._sphericalDelta.phi = 0;
      dirty = true;
    }
    if (this._zoomDelta) {
      const factor = this._zoomDelta > 0 ? 1 / this.zoomFactor : this.zoomFactor;
      this._spherical.radius *= Math.pow(factor, Math.abs(this._zoomDelta));
      this._zoomDelta = 0;
      dirty = true;
    }
    if (this._panDelta.lengthSq() > 1e-8) {
      this.target.add(this._panDelta);
      this.camera.position.add(this._panDelta);
      this._panDelta.set(0, 0, 0);
      dirty = true;
    }
    if (dirty) {
      this._applySpherical();
      return true;
    }
    return false;
  }
}
