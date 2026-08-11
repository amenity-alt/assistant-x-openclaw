import 'package:flutter/foundation.dart';

import 'transform_state.dart';

/// 手势变换控制器：持有目标 [TransformState]，手势帧（~10fps）增量更新。
///
/// 渲染层在动画循环（60fps）中对该目标做指数阻尼插值，实现
/// 「10fps 手势输入 → 60fps 平滑动画」。
class TransformController extends ValueNotifier<TransformState> {
  TransformController() : super(TransformState.identity);

  static const double minScale = 0.6;
  static const double maxScale = 4.0;
  static const double maxPos = 1.2;

  void apply({
    double dScale = 1.0,
    double dRotX = 0,
    double dRotY = 0,
    double dRotZ = 0,
    double dPosX = 0,
    double dPosY = 0,
  }) {
    final t = value;
    value = TransformState(
      scale: (t.scale * dScale).clamp(minScale, maxScale),
      rotX: t.rotX + dRotX,
      rotY: t.rotY + dRotY,
      rotZ: t.rotZ + dRotZ,
      posX: (t.posX + dPosX).clamp(-maxPos, maxPos),
      posY: (t.posY + dPosY).clamp(-maxPos, maxPos),
    );
  }

  void reset() => value = TransformState.identity;
}
