import * as THREE from 'three';
import { GLOBE_RADIUS } from './createGlobe';

/** 扫描环 + 轨道环 + 卫星 + 粒子场 */
export function createRings(glowTex) {
  const group = new THREE.Group();
  group.name = 'rings';

  // ── 主扫描环（水平，缓慢旋转，带扫掠亮点）──
  const scan = new THREE.Group();
  const ringGeo = new THREE.RingGeometry(GLOBE_RADIUS * 1.22, GLOBE_RADIUS * 1.24, 128);
  const ringMat = new THREE.MeshBasicMaterial({
    color: 0x3f9dff,
    transparent: true,
    opacity: 0.42,
    side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const ring = new THREE.Mesh(ringGeo, ringMat);
  ring.rotation.x = -Math.PI / 2;
  scan.add(ring);

  // 内环细线
  const innerRingPts = [];
  for (let i = 0; i <= 128; i++) {
    const a = (i / 128) * Math.PI * 2;
    innerRingPts.push(new THREE.Vector3(Math.cos(a) * GLOBE_RADIUS * 1.14, 0, Math.sin(a) * GLOBE_RADIUS * 1.14));
  }
  const innerRing = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(innerRingPts),
    new THREE.LineBasicMaterial({ color: 0x4fa8ff, transparent: true, opacity: 0.5, depthWrite: false }),
  );
  scan.add(innerRing);

  // 扫掠亮点
  const sweep = new THREE.Points(
    new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(GLOBE_RADIUS * 1.23, 0, 0)]),
    new THREE.PointsMaterial({
      size: 0.38,
      map: glowTex,
      color: 0xbdf5ff,
      transparent: true,
      opacity: 1,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
  scan.add(sweep);

  // 外圈虚线轨道（倾斜）
  const orbitPts = [];
  for (let i = 0; i <= 200; i++) {
    const a = (i / 200) * Math.PI * 2;
    orbitPts.push(new THREE.Vector3(Math.cos(a) * GLOBE_RADIUS * 1.45, 0, Math.sin(a) * GLOBE_RADIUS * 1.45));
  }
  const orbit = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(orbitPts),
    new THREE.LineDashedMaterial({
      color: 0x369dff,
      transparent: true,
      opacity: 0.7,
      dashSize: 0.3,
      gapSize: 0.18,
      depthWrite: false,
    }),
  );
  orbit.computeLineDistances();
  orbit.rotation.x = 1.05;
  orbit.rotation.z = 0.25;
  scan.add(orbit);

  // 轨道卫星（小光点沿倾斜轨道运行）
  const sat = new THREE.Points(
    new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(GLOBE_RADIUS * 1.45, 0, 0)]),
    new THREE.PointsMaterial({
      size: 0.24,
      map: glowTex,
      color: 0xa8ecff,
      transparent: true,
      opacity: 1,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
  sat.rotation.x = 1.05;
  sat.rotation.z = 0.25;
  scan.add(sat);

  // 第二道倾斜小环（陀螺仪风格）
  const gyroPts = [];
  for (let i = 0; i <= 120; i++) {
    const a = (i / 120) * Math.PI * 2;
    gyroPts.push(new THREE.Vector3(Math.cos(a) * GLOBE_RADIUS * 1.3, Math.sin(a) * GLOBE_RADIUS * 0.24, 0));
  }
  const gyro = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(gyroPts),
    new THREE.LineBasicMaterial({ color: 0x2f84e8, transparent: true, opacity: 0.42, depthWrite: false }),
  );
  gyro.rotation.x = 0.4;
  scan.add(gyro);

  group.add(scan);

  // ── 粒子场（外层散点）──
  const N = 700;
  const pArr = [];
  for (let i = 0; i < N; i++) {
    const r = GLOBE_RADIUS * (1.45 + Math.random() * 1.9);
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    pArr.push(
      r * Math.sin(phi) * Math.cos(theta),
      r * Math.cos(phi),
      r * Math.sin(phi) * Math.sin(theta),
    );
  }
  const pGeo = new THREE.BufferGeometry();
  pGeo.setAttribute('position', new THREE.Float32BufferAttribute(pArr, 3));
  const pMat = new THREE.PointsMaterial({
    size: 0.09,
    color: 0x8fc8ff,
    transparent: true,
    opacity: 0.9,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    sizeAttenuation: true,
  });
  const particles = new THREE.Points(pGeo, pMat);
  particles.name = 'particles';
  group.add(particles);

  return { group, scan, orbit, sat, sweep, gyro, particles };
}
