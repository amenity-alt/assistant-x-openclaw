import 'dart:math' as math;

/// 手势层手部数据（与渲染层解耦；landmarks 为 21 点 × (x,y,z)，z 为深度）。
class GestureHand {
  final double score;
  final List<double> landmarks;
  const GestureHand({required this.score, required this.landmarks});

  static const int pointCount = 21;
  static const int dims = 3;
}

/// 由一帧平滑后的关键点提取的手势特征。
class GestureSample {
  final double palmX;
  final double palmY;
  final double roll;
  final double pitch;
  final double pinchRatio;

  const GestureSample({
    required this.palmX,
    required this.palmY,
    required this.roll,
    required this.pitch,
    required this.pinchRatio,
  });
}

/// 手势特征提取：21 点 → 掌心位置 / 手掌滚转 / 俯仰 / 捏合比例。
///
/// 关键点索引（MediaPipe 标准）：
///   0 腕部 · 4 拇指尖 · 8 食指尖 · 9 中指MCP · 12 中指尖
class GestureRecognizer {
  static const int _wrist = 0;
  static const int _thumbTip = 4;
  static const int _indexTip = 8;
  static const int _middleMcp = 9;

  /// 无效输入（点数不足 / 手掌尺寸过小）返回 null。
  GestureSample? sample(List<double> lms) {
    if (lms.length < GestureHand.pointCount * GestureHand.dims) return null;
    double x(int i) => lms[i * 3];
    double y(int i) => lms[i * 3 + 1];
    double z(int i) => lms[i * 3 + 2];

    final palmX = (x(_wrist) + x(_middleMcp)) / 2;
    final palmY = (y(_wrist) + y(_middleMcp)) / 2;

    final dx = x(_middleMcp) - x(_wrist);
    final dy = y(_middleMcp) - y(_wrist);
    final palmSize = math.sqrt(dx * dx + dy * dy);
    if (palmSize < 0.02) return null;

    final roll = math.atan2(dy, dx);
    final pitch = math.atan2(z(_middleMcp) - z(_wrist), palmSize);

    final pinDx = x(_indexTip) - x(_thumbTip);
    final pinDy = y(_indexTip) - y(_thumbTip);
    final pinchRatio = math.sqrt(pinDx * pinDx + pinDy * pinDy) / palmSize;

    return GestureSample(
      palmX: palmX,
      palmY: palmY,
      roll: roll,
      pitch: pitch,
      pinchRatio: pinchRatio,
    );
  }
}
