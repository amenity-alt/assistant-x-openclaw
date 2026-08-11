import 'dart:math' as math;

import 'gesture_recognizer.dart';
import 'landmark_filter.dart';
import 'transform_controller.dart';

/// 手势状态机：IDLE → HAND_DETECTED → HOVER → GRAB → TRANSFORM → RELEASE。
///
/// 仲裁规则：
/// - HOVER：手掌稳定在画面内（无动作持续数帧）才进入可操作状态，防误触；
/// - GRAB：捏合进入（拇指-食指并拢，带滞回）→ 下一帧进入 TRANSFORM；
/// - TRANSFORM：捏合缩放 / 手掌滚转俯仰旋转 / 掌心平移，可多自由度并存；
/// - RELEASE：捏合退出或手丢失时的过渡帧。
enum GesturePhase {
  idle,
  handDetected,
  pinchReady,
  zooming,
  rotating,
  moving,
  hover,
  grab,
  transform,
  release,
}

/// 手势识别控制器：消费平滑后的手部数据，产出增量并驱动 [TransformController]。
class GestureController {
  GestureController({required this.transform});

  final TransformController transform;
  final LandmarkFilter _filter = LandmarkFilter();
  final GestureRecognizer _recognizer = GestureRecognizer();

  GesturePhase phase = GesturePhase.idle;

  static const double rotSens = 2.0;
  static const double pitchSens = 1.6;
  static const double moveSens = 1.4;
  static const double scaleSens = 2.0;
  // 单帧限幅：避免手部抖动造成模型跳变
  static const double maxRotDelta = 0.5;
  static const double maxScaleDelta = 0.06;
  static const double pinchEnter = 0.38;
  static const double pinchExit = 0.5;
  static const double rotDeadband = 0.012;
  static const double moveDeadband = 0.003;

  double _prevRoll = 0;
  double _prevPitch = 0;
  double _prevPalmX = 0;
  double _prevPalmY = 0;
  double _prevPinch = 1;
  bool _hasPrev = false;
  bool _pinching = false;
  int _hoverFrames = 0;
  bool _wasTracking = false;

  /// 进入 HOVER 所需的最小稳定帧数（~10fps 输入，3 帧 ≈ 0.3s）。
  static const int hoverFramesRequired = 3;

  /// 处理一帧手部数据（多手时取置信度最高者）。
  GesturePhase process(List<GestureHand> hands) {
    GestureHand? best;
    for (final h in hands) {
      if (h.landmarks.length >= GestureHand.pointCount * GestureHand.dims &&
          (best == null || h.score > best.score)) {
        best = h;
      }
    }
    if (best == null) {
      final was = _wasTracking;
      resetTracking();
      _wasTracking = false;
      return phase = was ? GesturePhase.release : GesturePhase.idle;
    }
    _wasTracking = true;

    final sample = _recognizer.sample(_filter.filter(best.landmarks));
    if (sample == null) {
      final was = _wasTracking;
      resetTracking();
      _wasTracking = false;
      return phase = was ? GesturePhase.release : GesturePhase.idle;
    }

    if (!_hasPrev) {
      _remember(sample);
      _hasPrev = true;
      _hoverFrames = 0;
      return phase = GesturePhase.handDetected;
    }

    // 捏合滞回 + 进入/退出边沿检测
    final wasPinching = _pinching;
    if (!_pinching && sample.pinchRatio < pinchEnter) {
      _pinching = true;
    } else if (_pinching && sample.pinchRatio > pinchExit) {
      _pinching = false;
    }
    final pinchEntered = !wasPinching && _pinching;
    final pinchExited = wasPinching && !_pinching;

    if (pinchEntered) {
      _remember(sample);
      return phase = GesturePhase.grab;
    }
    if (pinchExited) {
      _remember(sample);
      return phase = GesturePhase.release;
    }

    double dScale = 1.0;
    double dRotX = 0;
    double dRotY = 0;
    double dPosX = 0;
    double dPosY = 0;

    if (_pinching) {
      // 捏合缩放：距离比例变化 → 线性增量（尺骨长度无关，手前后移动不误触发）
      if (_prevPinch > 0.05) {
        dScale = (1 + (_prevPinch - sample.pinchRatio) * scaleSens)
            .clamp(1 - maxScaleDelta, 1 + maxScaleDelta);
      }
    } else {
      final dRoll = _angleDelta(sample.roll, _prevRoll);
      final dPitch = sample.pitch - _prevPitch;
      if (dRoll.abs() > rotDeadband) {
        dRotY = (dRoll * rotSens).clamp(-maxRotDelta, maxRotDelta);
      }
      if (dPitch.abs() > rotDeadband) {
        dRotX = (-dPitch * pitchSens).clamp(-maxRotDelta, maxRotDelta);
      }
    }

    final dX = sample.palmX - _prevPalmX;
    final dY = sample.palmY - _prevPalmY;
    if (dX.abs() > moveDeadband) dPosX = dX * moveSens;
    if (dY.abs() > moveDeadband) dPosY = dY * moveSens;

    if (dScale != 1.0 ||
        dRotX != 0 ||
        dRotY != 0 ||
        dPosX != 0 ||
        dPosY != 0) {
      _hoverFrames = 0;
      transform.apply(
        dScale: dScale,
        dRotX: dRotX,
        dRotY: dRotY,
        dPosX: dPosX,
        dPosY: dPosY,
      );
      _remember(sample);
      return phase = GesturePhase.transform;
    }

    // 稳定无动作 → 帧数达标后进入 HOVER（防误触）
    _hoverFrames++;
    _remember(sample);
    return phase = _hoverFrames >= hoverFramesRequired
        ? GesturePhase.hover
        : GesturePhase.handDetected;
  }

  void _remember(GestureSample s) {
    _prevRoll = s.roll;
    _prevPitch = s.pitch;
    _prevPalmX = s.palmX;
    _prevPalmY = s.palmY;
    _prevPinch = s.pinchRatio;
  }

  /// 手丢失 / 无效时清空滤波与参考量，避免下次出现时跳变。
  void resetTracking() {
    _filter.reset();
    _hasPrev = false;
    _pinching = false;
    _hoverFrames = 0;
  }

  static double _angleDelta(double a, double b) {
    var d = a - b;
    while (d > math.pi) {
      d -= 2 * math.pi;
    }
    while (d < -math.pi) {
      d += 2 * math.pi;
    }
    return d;
  }
}
