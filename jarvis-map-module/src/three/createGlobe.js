import * as THREE from 'three';
import { latLonToVec3 } from './geo';

export const GLOBE_RADIUS = 5;

/** 地球本体（深蓝黑 + 暗色纹理 + 大气辉光） */
export function createEarth(textureUrl) {
  const group = new THREE.Group();
  group.name = 'earth';

  const loader = new THREE.TextureLoader();
  const map = loader.load(textureUrl);
  map.colorSpace = THREE.SRGBColorSpace;

  const mesh = new THREE.Mesh(
    new THREE.SphereGeometry(GLOBE_RADIUS, 96, 96),
    new THREE.MeshPhongMaterial({
      map,
      color: 0x3a6b9e,          // 深蓝黑染色
      emissive: 0x1d3d6e,       // 暗部微光
      emissiveIntensity: 0.95,
      specular: 0x2a5a8a,
      shininess: 26,
    }),
  );
  group.add(mesh);

  // 大气辉光（菲涅尔，背面）
  const glow = new THREE.Mesh(
    new THREE.SphereGeometry(GLOBE_RADIUS * 1.16, 64, 64),
    new THREE.ShaderMaterial({
      uniforms: {
        c: { value: 0.42 },
        p: { value: 4.2 },
        glowColor: { value: new THREE.Color(0x3f8dff) },
      },
      vertexShader: `
        varying vec3 vNormal;
        void main() {
          vNormal = normalize(normalMatrix * normal);
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }`,
      fragmentShader: `
        uniform float c;
        uniform float p;
        uniform vec3 glowColor;
        varying vec3 vNormal;
        void main() {
          float intensity = pow(c - dot(vNormal, vec3(0.0, 0.0, 1.0)), p);
          intensity = clamp(intensity, 0.0, 1.0);
          gl_FragColor = vec4(glowColor, 1.0) * intensity * 0.9;
        }`,
      side: THREE.BackSide,
      blending: THREE.AdditiveBlending,
      transparent: true,
      depthWrite: false,
    }),
  );
  group.add(glow);

  // 外圈第二层淡辉光
  const halo = new THREE.Mesh(
    new THREE.SphereGeometry(GLOBE_RADIUS * 1.34, 48, 48),
    new THREE.MeshBasicMaterial({
      color: 0x1a4f8a,
      transparent: true,
      opacity: 0.08,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      side: THREE.BackSide,
    }),
  );
  group.add(halo);

  return group;
}

/** 国界细线（GeoJSON MultiPolygon → LineSegments） */
export function createBorders(countries) {
  const radius = GLOBE_RADIUS * 1.006;
  const positions = [];

  const pushRing = (ring) => {
    for (let i = 0; i < ring.length - 1; i++) {
      const a = latLonToVec3(ring[i][1], ring[i][0], radius);
      const b = latLonToVec3(ring[i + 1][1], ring[i + 1][0], radius);
      positions.push(a.x, a.y, a.z, b.x, b.y, b.z);
    }
  };

  for (const feature of countries.features || []) {
    const g = feature.geometry;
    if (!g) continue;
    if (g.type === 'Polygon') {
      g.coordinates.forEach(pushRing);
    } else if (g.type === 'MultiPolygon') {
      g.coordinates.forEach((poly) => poly.forEach(pushRing));
    }
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));

  const mat = new THREE.LineBasicMaterial({
    color: 0x5aa8ff,
    transparent: true,
    opacity: 0.8,
    depthWrite: false,
  });
  const lines = new THREE.LineSegments(geo, mat);
  lines.name = 'borders';
  return lines;
}

/** 经纬网格线 */
export function createGrid() {
  const radius = GLOBE_RADIUS * 1.014;
  const positions = [];
  const step = 15;

  for (let lat = -75; lat <= 75; lat += step) {
    const pts = [];
    for (let lon = -180; lon <= 180; lon += 4) pts.push(latLonToVec3(lat, lon, radius));
    for (let i = 0; i < pts.length - 1; i++) positions.push(pts[i].x, pts[i].y, pts[i].z, pts[i + 1].x, pts[i + 1].y, pts[i + 1].z);
  }
  for (let lon = -180; lon <= 180; lon += step) {
    const pts = [];
    for (let lat = -85; lat <= 85; lat += 4) pts.push(latLonToVec3(lat, lon, radius));
    for (let i = 0; i < pts.length - 1; i++) positions.push(pts[i].x, pts[i].y, pts[i].z, pts[i + 1].x, pts[i + 1].y, pts[i + 1].z);
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  const mat = new THREE.LineBasicMaterial({
    color: 0x3f8dff,
    transparent: true,
    opacity: 0.22,
    depthWrite: false,
  });
  const grid = new THREE.LineSegments(geo, mat);
  grid.name = 'grid';
  return grid;
}
