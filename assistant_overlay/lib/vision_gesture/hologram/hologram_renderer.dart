import '../transform_state.dart';

/// 全息渲染器抽象接口。
///
/// Gesture 链路只产出 [TransformState]，渲染器负责消费：
/// - [loadModel]：创建 GPU 资源并挂载模型；
/// - [removeModel]：卸载模型、释放纹理/几何；
/// - [updateTransform]：接收手势变换目标（渲染循环内做 60fps 阻尼插值）；
/// - [dispose]：Vision OFF 时释放渲染器全部资源。
abstract class HologramRenderer {
  Future<void> loadModel();
  void removeModel();
  void updateTransform(TransformState state);
  void dispose();
}
