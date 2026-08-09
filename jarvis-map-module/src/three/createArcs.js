import * as THREE from 'three';
import { GLOBE_RADIUS } from './createGlobe';
import { latLonToVec3, makeGlowTexture } from './geo';
import { CITIES, ARCS } from '../data/cities';

/**
 * 数据流弧线：贝塞尔弧线（青色虚线流动）+ 沿弧移动的光点（packets）
 */
export function createArcs(glowTex) {
  const group = new THREE.Group();
  group.name = 'arcs';

  const byName = new Map(CITIES.map((c) => [c.name, c]));
  const arcs = [];

  for (const [fromName, toName] of ARCS) {
    const a = byName.get(fromName);
    const b = byName.get(toName);
    if (!a || !b) continue;

    const va = latLonToVec3(a.lat, a.lon, GLOBE_RADIUS * 1.02);
    const vb = latLonToVec3(b.lat, b.lon, GLOBE_RADIUS * 1.02);

    // 弧线控制点：中点上抬
    const mid = va.clone().add(vb).multiplyScalar(0.5).normalize();
    const arcHeight = GLOBE_RADIUS * (0.28 + Math.random() * 0.22);
    const vc = mid.multiplyScalar(GLOBE_RADIUS * 1.02 + arcHeight);

    const curve = new THREE.QuadraticBezierCurve3(va, vc, vb);

    // 虚线弧
    const pts = curve.getPoints(64);
    const lineGeo = new THREE.BufferGeometry().setFromPoints(pts);
    const line = new THREE.Line(lineGeo, new THREE.LineDashedMaterial({
      color: 0x5fd0ff,
      transparent: true,
      opacity: 0.9,
      dashSize: 0.22,
      gapSize: 0.18,
      depthWrite: false,
    }));
    line.computeLineDistances();
    line.name = `arc-${fromName}-${toName}`;
    group.add(line);

    // 2 个流动光点
    const packetGeo = new THREE.BufferGeometry();
    const packetPos = new Float32Array(2 * 3);
    packetGeo.setAttribute('position', new THREE.BufferAttribute(packetPos, 3));
    const packetMat = new THREE.PointsMaterial({
      size: 0.44,
      map: glowTex,
      color: 0xc8f6ff,
      transparent: true,
      opacity: 1,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });
    const packets = new THREE.Points(packetGeo, packetMat);
    group.add(packets);

    arcs.push({
      curve,
      line,
      packets,
      packetPos,
      phase: Math.random() * 2,
      speed: 0.1 + Math.random() * 0.08,
    });
  }

  return { group, arcs };
}
