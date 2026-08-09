import * as THREE from 'three';
import { GLOBE_RADIUS } from './createGlobe';
import { latLonToVec3, makeGlowTexture } from './geo';
import { CITIES } from '../data/cities';

const COLOR = {
  hub: 0x7feaff,   // 青
  node: 0x5fb0ff,  // 淡蓝
  hot: 0xffb347,   // 橙
};

/** 城市节点（发光点）+ 热点脉冲 */
export function createNodes(glowTex) {
  const group = new THREE.Group();
  group.name = 'nodes';

  const byType = { hub: [], node: [], hot: [] };
  for (const c of CITIES) byType[c.type]?.push(c);

  const hotspots = [];
  for (const [type, list] of Object.entries(byType)) {
    const arr = [];
    for (const c of list) {
      const v = latLonToVec3(c.lat, c.lon, GLOBE_RADIUS * 1.025);
      arr.push(v.x, v.y, v.z);
      if (type === 'hot') hotspots.push({ ...c, vec: v });
    }
    if (!arr.length) continue;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(arr, 3));
    const mat = new THREE.PointsMaterial({
      size: type === 'hot' ? 0.72 : type === 'hub' ? 0.5 : 0.36,
      map: glowTex,
      color: COLOR[type],
      transparent: true,
      opacity: 1,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });
    const pts = new THREE.Points(geo, mat);
    pts.name = `nodes-${type}`;
    group.add(pts);

    // 热点额外叠加一层大面积柔和光晕
    if (type === 'hot') {
      const haloMat = new THREE.PointsMaterial({
        size: 1.9,
        map: glowTex,
        color: 0xff9040,
        transparent: true,
        opacity: 0.4,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        sizeAttenuation: true,
      });
      const halo = new THREE.Points(geo, haloMat);
      halo.name = 'nodes-hot-halo';
      group.add(halo);
    }
    if (type === 'hot') {
      pts.userData = { baseSize: 0.72 };
    }
  }

  return { group, hotspots };
}
