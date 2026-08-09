import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLOBE_RADIUS, createEarth, createBorders, createGrid } from './createGlobe';
import { createNodes } from './createNodes';
import { createArcs } from './createArcs';
import { createRings } from './createRings';
import { makeGlowTexture, latLonToVec3 } from './geo';

/**
 * 地球态势场景：渲染器 / 相机 / 灯光 / 地球 / 节点 / 弧线 / 扫描环 / 粒子
 * 支持拖拽旋转（OrbitControls）、滚轮缩放、自动旋转。
 */
export default class GlobeScene {
  constructor(container, { textureUrl, countries }) {
    this.container = container;
    this.raf = 0;
    this.clock = new THREE.Clock();

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance',
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setClearColor(0x000000, 0);
    container.appendChild(renderer.domElement);
    this.renderer = renderer;

    this.scene = new THREE.Scene();

    const camera = new THREE.PerspectiveCamera(
      42,
      container.clientWidth / container.clientHeight,
      0.1,
      100,
    );
    // 初始视角：以亚洲（约 20°N 105°E）为中心
    const asiaDir = latLonToVec3(20, 105, 1).normalize();
    camera.position.copy(asiaDir).multiplyScalar(GLOBE_RADIUS * 3.7);
    camera.position.y += 0.6;
    camera.lookAt(0, 0, 0);
    this.camera = camera;

    // 灯光
    this.scene.add(new THREE.AmbientLight(0x3a5a8a, 1.15));
    const key = new THREE.DirectionalLight(0xd8e8ff, 2.2);
    key.position.set(12, 6, 10);
    this.scene.add(key);
    const rim = new THREE.DirectionalLight(0x3f8dff, 0.95);
    rim.position.set(-8, -4, -10);
    this.scene.add(rim);

    // 控制：拖拽旋转 / 滚轮缩放 / 自动旋转
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.rotateSpeed = 0.55;
    controls.zoomSpeed = 0.8;
    controls.minDistance = GLOBE_RADIUS * 2.3;
    controls.maxDistance = GLOBE_RADIUS * 6.5;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.55;
    controls.enablePan = false;
    this.controls = controls;

    // 组建场景
    this.glowTex = makeGlowTexture(64);
    this.group = new THREE.Group();
    this.scene.add(this.group);

    const earth = createEarth(textureUrl);
    this.group.add(earth);

    if (countries) {
      this.group.add(createBorders(countries));
    }
    this.group.add(createGrid());

    const nodes = createNodes(this.glowTex);
    this.group.add(nodes.group);
    this.hotPts = nodes.group.getObjectByName('nodes-hot');
    this.hotBase = this.hotPts?.material.size ?? 0.42;

    const arcs = createArcs(this.glowTex);
    this.group.add(arcs.group);
    this.arcs = arcs.arcs;

    const rings = createRings(this.glowTex);
    this.group.add(rings.group);
    this.scan = rings.scan;
    this.gyro = rings.gyro;
    this.particles = rings.particles;

    // 自适应尺寸
    this.ro = new ResizeObserver(() => this._resize());
    this.ro.observe(container);

    // dev 调试钩子（生产构建会被摇树移除）
    if (import.meta.env?.DEV) {
      window.__globe = this;
      window.__THREE = THREE;
    }

    this._start();
  }

  _resize() {
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    if (!w || !h) return;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  }

  _start() {
    const loop = () => {
      this.raf = requestAnimationFrame(loop);
      const dt = Math.min(this.clock.getDelta(), 0.05);
      const t = this.clock.elapsedTime;

      // 扫描环 / 陀螺环 / 粒子场
      this.scan.rotation.y += dt * 0.18;
      this.gyro.rotation.z += dt * 0.32;
      this.particles.rotation.y += dt * 0.02;
      this.particles.rotation.x = Math.sin(t * 0.05) * 0.03;

      // 热点脉冲
      if (this.hotPts) {
      this.hotPts.material.opacity = 0.72 + 0.28 * (0.5 + 0.5 * Math.sin(t * 2.1));
        this.hotPts.material.size = this.hotBase * (1 + 0.22 * Math.sin(t * 1.6 + 1.0));
      }

      // 数据流弧线：虚线滚动 + 光点移动
      for (const arc of this.arcs) {
        arc.line.material.dashOffset -= dt * arc.speed * 1.6;
        const posAttr = arc.packets.geometry.attributes.position;
        for (let k = 0; k < 2; k++) {
          const tt = (t * arc.speed * 0.7 + arc.phase + k * 0.5) % 1;
          const p = arc.curve.getPoint(tt);
          posAttr.setXYZ(k, p.x, p.y, p.z);
        }
        posAttr.needsUpdate = true;
      }

      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    };
    loop();
  }

  dispose() {
    cancelAnimationFrame(this.raf);
    this.ro?.disconnect();
    this.controls.dispose();
    this.scene.traverse((obj) => {
      if (obj.geometry) obj.geometry.dispose();
      if (obj.material) {
        const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
        mats.forEach((m) => {
          Object.values(m).forEach((v) => {
            if (v && v.isTexture) v.dispose();
          });
          m.dispose();
        });
      }
    });
    this.renderer.dispose();
    if (this.renderer.domElement.parentNode === this.container) {
      this.container.removeChild(this.renderer.domElement);
    }
  }
}
