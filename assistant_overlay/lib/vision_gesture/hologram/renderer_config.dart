/// 全息渲染器开关。
///
/// 默认使用 three_js（ANGLE/Metal）3D 渲染器；
/// 置为 false 时回退到 CustomPainter 2.5D 视觉（仅中央聚焦环，即原版外观）。
const bool kUseThreeJsRenderer = true;

/// 可选 GLB/GLTF 模型路径（全息空间展示用）。
/// 留空则使用程序化全息地球；放入 earth.glb / robot.glb 后重启 overlay 生效。
/// 例如：`/Users/<you>/assistant-x-openclaw/assistant_overlay/assets/hologram/earth.glb`
const String kHologramGlbPath = '';
