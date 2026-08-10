import 'package:flutter/foundation.dart';

/// 全息模型变换状态（渲染器无关，弧度 + 归一化位移）。
///
/// Gesture 链路只产出/消费 [TransformState]，渲染器负责消费并 60fps 阻尼逼近。
@immutable
class TransformState {
  final double scale;
  final double rotX;
  final double rotY;
  final double rotZ;
  final double posX;
  final double posY;

  const TransformState({
    this.scale = 1.0,
    this.rotX = 0,
    this.rotY = 0,
    this.rotZ = 0,
    this.posX = 0,
    this.posY = 0,
  });

  static const TransformState identity = TransformState();

  @override
  String toString() =>
      'TransformState(scale: ${scale.toStringAsFixed(2)}, rot: '
      '${rotX.toStringAsFixed(2)}/${rotY.toStringAsFixed(2)}/${rotZ.toStringAsFixed(2)}, '
      'pos: ${posX.toStringAsFixed(2)}/${posY.toStringAsFixed(2)})';
}
