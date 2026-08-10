/// 全息渲染器开关。
///
/// 默认使用 three_js（ANGLE/Metal）3D 渲染器；
/// 置为 false 时回退到 CustomPainter 2.5D 视觉（仅中央聚焦环，即原版外观）。
const bool kUseThreeJsRenderer = true;
