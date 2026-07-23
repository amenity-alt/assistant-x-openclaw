#version 320 es

precision highp float;

layout(location = 0) out vec4 fragColor;

layout(location = 0) uniform vec2 resolution;
layout(location = 1) uniform vec4 rotations;
layout(location = 2) uniform float pulseValue;
layout(location = 3) uniform float speakingScale;
layout(location = 4) uniform vec3 primaryColor;
layout(location = 5) uniform vec3 dimColor;
layout(location = 6) uniform vec3 lightColor;
layout(location = 7) uniform float lineWidthScale;

const float PI = 3.141592653589793;
const float TAU = 6.283185307179586;

float aa() {
  return 1.8 / min(resolution.x, resolution.y);
}

float ring(float radius, float target, float width) {
  return smoothstep(width + aa(), width - aa(), abs(radius - target));
}

float sector(float angle, float center, float halfWidth) {
  float d = abs(atan(sin(angle - center), cos(angle - center)));
  return smoothstep(halfWidth + aa() * 3.0, halfWidth - aa() * 3.0, d);
}

float repeatingSector(float angle, float count, float rotation, float halfWidth) {
  float cell = TAU / count;
  float local = mod(angle - rotation + cell * 0.5, cell) - cell * 0.5;
  return smoothstep(halfWidth + aa() * 3.0, halfWidth - aa() * 3.0, abs(local));
}

float angularBand(float angle, float count, float rotation, float duty) {
  float cell = TAU / count;
  float local = mod(angle - rotation, cell) / cell;
  float edge = aa() * 12.0;
  return smoothstep(0.0, edge, local) * smoothstep(duty, duty - edge, local);
}

float radialLine(float radius, float angle, float count, float rotation, float innerR, float outerR, float halfWidth) {
  float radial = smoothstep(innerR - aa(), innerR + aa(), radius)
    * smoothstep(outerR + aa(), outerR - aa(), radius);
  return radial * repeatingSector(angle, count, rotation, halfWidth);
}

float dotOnRing(vec2 uv, float angle, float radius, float size) {
  vec2 p = vec2(cos(angle), sin(angle)) * radius;
  return 1.0 - smoothstep(size, size + aa() * 6.0, length(uv - p));
}

vec3 blendLight(vec3 base, vec3 add, float amount) {
  return base + add * amount;
}

void main() {
  vec2 uv = (gl_FragCoord.xy * 2.0 - resolution.xy)
    / min(resolution.x, resolution.y);
  float radius = length(uv);
  float angle = atan(uv.y, uv.x);

  float outerRot = rotations.x;
  float arcsRot = rotations.y;
  float dataRot = rotations.z;
  float innerRot = rotations.w;
  float speak = clamp(speakingScale, 0.0, 1.0);
  float pulse = clamp(pulseValue, 0.0, 1.0);

  // 线宽加粗时整体向内收缩，避免裁切。
  float radiusScale = clamp((0.96 - 0.010 * lineWidthScale) / 0.95, 0.75, 1.0);

  vec3 color = vec3(0.0);
  float alpha = 0.0;

  // === 外壳金属环（双线 + 辉光），低亮度 HUD 感 ===
  float outerR = .92 * radiusScale;
  float shellGlow = ring(radius, outerR, (0.008 + speak * 0.00) * lineWidthScale);
  color = blendLight(color, primaryColor, shellGlow * (0.14 + pulse * 0.36 + speak * 0.22));
  alpha = max(alpha, shellGlow * (0.13 + pulse * 0.05 + speak * 0.20));

  float shellBase = ring(radius, 0.88 * radiusScale, 0.020 * lineWidthScale);
  color = blendLight(color, dimColor, shellBase * 0.42);
  alpha = max(alpha, shellBase * 0.20);

  // 外环刻度（细密 60 + 粗 12），克制
  float minorTicks = radialLine(radius, angle, 60.0, outerRot, 0.85 * radiusScale, radiusScale, 0.005 * lineWidthScale);
  color = blendLight(color, dimColor, minorTicks * 0.58);
  alpha = max(alpha, minorTicks * 0.54);

  float majorTicks = radialLine(radius, angle, 12.0, outerRot, 0.82 * radiusScale, radiusScale, 0.008 * lineWidthScale);
  color = blendLight(color, primaryColor, majorTicks * 0.40);
  alpha = max(alpha, majorTicks * 0.32);

  // === 线圈层（反应堆标志性环形线圈段）===
  // 8 段主线圈，缓慢旋转
  float coil1 = ring(radius, 0.74 * radiusScale, 0.012 * lineWidthScale) * angularBand(angle, 8.0, arcsRot, 0.085);
  // 16 段细线圈，反向慢转
  float coil2 = ring(radius, 0.68 * radiusScale, 0.007 * lineWidthScale) * angularBand(angle, 16.0, -arcsRot * 0.5, 0.05);
  color = blendLight(color, dimColor, coil1 * 0.34);
  color = blendLight(color, primaryColor, coil2 * 0.30);
  alpha = max(alpha, coil1 * 0.26);
  alpha = max(alpha, coil2 * 0.24);

  // === 中部数据环（低亮度脉动）===
  float dataBase = ring(radius, 0.56 * radiusScale, 0.006 * lineWidthScale);
  float dataTicks = radialLine(radius, angle, 36.0, dataRot, 0.52 * radiusScale, 0.565 * radiusScale, 0.005 * lineWidthScale);
  color = blendLight(color, primaryColor, dataBase * 0.26 + dataTicks * 0.30);
  alpha = max(alpha, dataBase * 0.22);
  alpha = max(alpha, dataTicks * 0.24);

  // 数据环上的发光节点（12 个），亮度随旋转呼吸
  for (int i = 0; i < 12; i++) {
    float fi = float(i);
    float bright = (sin(dataRot * 3.0 + fi) + 1.0) * 0.5;
    float dotMask = dotOnRing(uv, fi / 12.0 * TAU + dataRot, 0.515 * radiusScale, (0.010 + bright * 0.004) * lineWidthScale);
    color = blendLight(color, primaryColor, dotMask * (0.18 + bright * 0.22));
    alpha = max(alpha, dotMask * (0.16 + bright * 0.18));
  }

  // 脉动环（跟随 pulse/speak 微扩）
  float pulseRing = ring(radius, 0.56 * radiusScale * (1.02 + pulse * 0.02 + speak * 0.04), (0.008 + speak * 0.008) * lineWidthScale);
  color = blendLight(color, primaryColor, pulseRing * (0.16 + pulse * 0.08 + speak * 0.24));
  alpha = max(alpha, pulseRing * (0.12 + pulse * 0.06 + speak * 0.22));

  // === 内环（双线，低亮度）===
  float innerBase = ring(radius, 0.40 * radiusScale, 0.008 * lineWidthScale);
  float innerFine = ring(radius, 0.34 * radiusScale, 0.004 * lineWidthScale);
  color = blendLight(color, primaryColor, innerBase * 0.40 + innerFine * 0.26);
  alpha = max(alpha, innerBase * 0.30);
  alpha = max(alpha, innerFine * 0.22);

  // 内环装饰条带（8 段径向，非常克制）
  for (int i = 0; i < 8; i++) {
    float center = float(i) / 8.0 * TAU + innerRot;
    float chevron = sector(angle, center, 0.020 * lineWidthScale)
      * smoothstep(0.245 * radiusScale, 0.315 * radiusScale, radius)
      * smoothstep(0.345 * radiusScale, 0.320 * radiusScale, radius);
    color = blendLight(color, primaryColor, chevron * 0.18);
    alpha = max(alpha, chevron * 0.16);
  }

  // 内环节点（4 个）
  for (int i = 0; i < 4; i++) {
    float dotMask = dotOnRing(uv, float(i) / 4.0 * TAU + innerRot * 0.5, 0.45 * radiusScale, 0.012 * lineWidthScale);
    color = blendLight(color, primaryColor, dotMask * 0.30);
    alpha = max(alpha, dotMask * 0.24);
  }

  // === 中心反应堆核心（柔和发光，不刺眼）===
  float coreGlow = 1.0 - smoothstep((0.06 + speak * 0.008) * radiusScale, (0.22 + speak * 0.06) * radiusScale, radius);
  float coreFill = 1.0 - smoothstep(0.12 * radiusScale, 0.123 * radiusScale + aa(), radius);
  float coreRing = ring(radius, 0.12 * radiusScale, 0.006 * lineWidthScale);
  float innerCore = 1.0 - smoothstep(0.06 * radiusScale, 0.064 * radiusScale + aa(), radius);
  color = blendLight(color, primaryColor, coreGlow * (0.05 + pulse * 0.03 + speak * 0.12));
  color = mix(color, color + primaryColor * 0.10, coreFill * 0.22);
  color = blendLight(color, primaryColor, coreRing * 0.42);
  color = blendLight(color, lightColor, innerCore * 0.30);
  alpha = max(alpha, coreGlow * (0.07 + pulse * 0.03 + speak * 0.12));
  alpha = max(alpha, coreFill * 0.16);
  alpha = max(alpha, coreRing * 0.34);
  alpha = max(alpha, innerCore * 0.28);

  // 扫描微光（极弱）
  float scan = pow(max(0.0, sin(angle * 18.0 + radius * 30.0 + dataRot * 2.0)), 24.0);
  color = blendLight(color, primaryColor, scan * ring(radius, 0.60 * radiusScale, 0.28) * 0.03);

  alpha = clamp(alpha, 0.0, 0.92);
  fragColor = vec4(color, alpha);
}
