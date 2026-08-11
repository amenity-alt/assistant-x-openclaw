import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import 'hud_terminal_shell.dart';
import 'vision_gesture/gesture_controller.dart';
import 'vision_gesture/gesture_recognizer.dart';
import 'vision_gesture/hologram/renderer_config.dart';
import 'vision_gesture/hologram/three_js_hologram_view.dart';
import 'vision_gesture/transform_controller.dart';

/// Jarvis Vision Mode 全屏 HUD（Capability，非 Agent）
///
/// 层级（自下而上）：摄像头背景 → 扫描网格/扫描线 → 中央聚焦环 → 手部层 →
/// 信息面板（左 SYSTEM STATUS / 右 VISION DATA）→ 顶栏 → 状态大字 → 底部进度。
///
/// 协议（Python src/vision.py 推送，经 TCP 17889 文本行）：
///   `vision:start` / `vision:stop` / `vision:status <STATE>` /
///   `vision:frame <base64-jpeg>` / `vision:hand <json>`
///
/// 动画三态：进入（淡入+环缩放展开）／运行（扫描线/弧/进度 60fps 循环，
/// 与摄像头帧率解耦）／退出（收缩淡出后组件移除、帧释放）。

/// Vision 状态机（与 Python 对齐）
enum VisionMode {
  off,
  initializing,
  scanning,
  handDetected,
  analyzing,
  completed,
  error,
}

/// 手部数据模型（Phase 1 渲染层 + 接口预留；坐标为归一化 0~1）
class VisionHand {
  final String label;
  final double score;
  final List<Offset> landmarks; // 21 点 (x, y)
  final List<double> depths; // 21 点深度 z（手势识别用）
  const VisionHand({
    required this.label,
    required this.score,
    required this.landmarks,
    this.depths = const [],
  });
}

/// MediaPipe 21 点骨骼连接表（标准拓扑）
const List<(int, int)> _handBones = [
  (0, 1), (1, 2), (2, 3), (3, 4), // 拇指
  (0, 5), (5, 6), (6, 7), (7, 8), // 食指
  (5, 9), (9, 10), (10, 11), (11, 12), // 中指
  (9, 13), (13, 14), (14, 15), (15, 16), // 无名指
  (13, 17), (17, 18), (18, 19), (19, 20), // 小指
  (0, 17), // 掌部
];

/// Vision HUD 控制器：状态机 + 摄像头帧 + 手部数据 + 进入/退出标志
class VisionHudController extends ChangeNotifier {
  VisionMode mode = VisionMode.off;
  bool animatingOut = false;
  ui.Image? frame;
  List<VisionHand> hands = const [];
  String error = '';
  GesturePhase gesturePhase = GesturePhase.idle;
  /// 物体识别结果（vision:object <json>）：label/category/confidence/info/bbox
  Map<String, dynamic>? objectResult;
  /// 物体扫描模式是否激活（vision:scan on/off）
  bool objectScanning = false;

  /// 手势 → 变换链路（跨 Vision 会话常驻，退出视觉后保持模型姿态）
  late final TransformController transform = TransformController();
  late final GestureController gesture = GestureController(transform: transform);

  /// 是否应挂载 HUD（运行中或正在退出动画）
  bool get showHud => mode != VisionMode.off || animatingOut;

  void onStart() {
    mode = VisionMode.initializing;
    animatingOut = false;
    error = '';
    notifyListeners();
  }

  void onStop() {
    if (mode == VisionMode.off && !animatingOut) return;
    animatingOut = true;
    notifyListeners();
  }

  /// 退出动画完成后调用（由 VisionHudOverlay 驱动）
  void onExitDone() {
    mode = VisionMode.off;
    animatingOut = false;
    _releaseFrame();
    hands = const [];
    error = '';
    objectResult = null;
    objectScanning = false;
    gesture.resetTracking();
    gesturePhase = GesturePhase.idle;
    notifyListeners();
  }

  void setObjectScan(bool on) {
    if (objectScanning == on) return;
    objectScanning = on;
    if (!on) objectResult = null;
    notifyListeners();
  }

  void setObject(String jsonStr) {
    try {
      final data = jsonDecode(jsonStr) as Map<String, dynamic>;
      objectResult = data;
      if (mode == VisionMode.analyzing || mode == VisionMode.scanning) {
        mode = VisionMode.completed;
      }
      notifyListeners();
    } catch (_) {}
  }

  void setStatus(String raw) {
    switch (raw.trim().toUpperCase()) {
      case 'INITIALIZING':
        mode = VisionMode.initializing;
        break;
      case 'SCANNING':
        mode = VisionMode.scanning;
        break;
      case 'HAND_DETECTED':
        mode = VisionMode.handDetected;
        break;
      case 'ANALYZING':
        mode = VisionMode.analyzing;
        break;
      case 'COMPLETED':
        mode = VisionMode.completed;
        break;
      case 'ERROR':
        mode = VisionMode.error;
        if (error.isEmpty) error = 'CAMERA OFFLINE · CHECK PERMISSION';
        break;
    }
    notifyListeners();
  }

  bool _decoding = false;

  void setFrame(String b64) {
    if (_decoding) return; // 丢帧保护：解码中则跳过，永远只保留最新帧
    _decoding = true;
    try {
      final bytes = base64Decode(b64);
      ui.instantiateImageCodec(bytes).then((codec) async {
        try {
          final f = await codec.getNextFrame();
          codec.dispose();
          final old = frame;
          frame = f.image;
          old?.dispose();
          notifyListeners();
        } catch (_) {
        } finally {
          _decoding = false;
        }
      }).catchError((_) {
        _decoding = false;
      });
    } catch (_) {
      _decoding = false;
    }
  }

  void setHands(String jsonStr) {
    try {
      final data = jsonDecode(jsonStr) as Map<String, dynamic>;
      final list = (data['hands'] as List?) ?? const [];
      final parsed = list.map((e) {
        final m = e as Map<String, dynamic>;
        final lms = <Offset>[];
        final depths = <double>[];
        for (final p in ((m['landmarks'] as List?) ?? const [])) {
          final pt = p as List;
          lms.add(Offset(
            (pt[0] as num).toDouble(),
            (pt[1] as num).toDouble(),
          ));
          depths.add(pt.length > 2 ? (pt[2] as num).toDouble() : 0);
        }
        return VisionHand(
          label: m['label']?.toString() ?? 'HAND',
          score: (m['score'] as num?)?.toDouble() ?? 0,
          landmarks: lms,
          depths: depths,
        );
      }).toList();
      hands = parsed;
      if (hands.isNotEmpty && mode == VisionMode.scanning) {
        mode = VisionMode.handDetected;
      }
      // 手势管线：手势帧 → 状态机 → TransformController（~10fps）
      final gestureHands = <GestureHand>[];
      for (final h in parsed) {
        if (h.landmarks.length != 21 || h.depths.length != 21) continue;
        final flat = <double>[];
        for (var i = 0; i < 21; i++) {
          flat.add(h.landmarks[i].dx);
          flat.add(h.landmarks[i].dy);
          flat.add(h.depths[i]);
        }
        gestureHands.add(GestureHand(score: h.score, landmarks: flat));
      }
      gesturePhase = gesture.process(gestureHands);
      notifyListeners();
    } catch (_) {}
  }

  void _releaseFrame() {
    frame?.dispose();
    frame = null;
  }

  @override
  void dispose() {
    _releaseFrame();
    gesture.resetTracking();
    transform.dispose();
    super.dispose();
  }
}

/// 全屏 Vision HUD 容器
class VisionHudOverlay extends StatefulWidget {
  final VisionHudController controller;
  const VisionHudOverlay({super.key, required this.controller});

  @override
  State<VisionHudOverlay> createState() => _VisionHudOverlayState();
}

class _VisionHudOverlayState extends State<VisionHudOverlay>
    with TickerProviderStateMixin {
  late final AnimationController _fade;
  late final AnimationController _scanline;
  late final AnimationController _sweep;
  late final AnimationController _progress;
  Timer? _exitFallback;

  @override
  void initState() {
    super.initState();
    _fade = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 400),
      value: 0,
    );
    _scanline = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 3),
    );
    _sweep = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2400),
    );
    _progress = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 4),
    );
    widget.controller.addListener(_sync);
    _sync();
  }

  /// 跟随控制器状态驱动进入/运行/退出动画
  void _sync() {
    final c = widget.controller;
    if (!mounted) return;
    if (c.showHud) {
      if (c.animatingOut) {
        // 兜底：动画链路任何异常都保证 2.5s 内强制退出
        _exitFallback ??= Timer(const Duration(milliseconds: 2500), () {
          if (mounted && c.animatingOut) c.onExitDone();
        });
        if (_fade.value == 0) {
          c.onExitDone();
        } else if (_fade.isAnimating) {
          // 淡入进行中收到退出 → 打断当前动画，从当前位置反向淡出
          _fade.stop();
          _fade.reverse().whenCompleteOrCancel(() {
            if (mounted && c.animatingOut) c.onExitDone();
          });
        } else {
          _fade.reverse().whenCompleteOrCancel(() {
            if (mounted && c.animatingOut) c.onExitDone();
          });
        }
      } else {
        _exitFallback?.cancel();
        _exitFallback = null;
        if (_fade.value < 1.0 && !_fade.isAnimating) _fade.forward();
        if (!_scanline.isAnimating) _scanline.repeat();
        if (!_sweep.isAnimating) _sweep.repeat();
        if (!_progress.isAnimating) _progress.repeat();
      }
    } else {
      _exitFallback?.cancel();
      _exitFallback = null;
      _scanline.stop();
      _sweep.stop();
      _progress.stop();
    }
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: widget.controller,
      builder: (context, child) {
        final c = widget.controller;
        final screen = MediaQuery.of(context).size;
        // Spatial Vision：中央全息空间占屏幕主要区域（宽 60% × 高 55%）
        final hologramSize = Size(
          screen.width * 0.60,
          screen.height * 0.55,
        );
        final ringSize =
            math.max(hologramSize.width, hologramSize.height) * 1.12;
        return FadeTransition(
          opacity: _fade,
          child: RepaintBoundary(
            child: Stack(
              fit: StackFit.expand,
              children: [
                // 1. 摄像头背景 + 暗色 HUD 底 + 扫描网格（会话内绘制）
                if (c.showHud) ...[
                CustomPaint(painter: _VisionBackdropPainter(frame: c.frame)),
                AnimatedBuilder(
                  animation: _scanline,
                  builder: (context, child) => CustomPaint(
                    painter: _ScanGridPainter(progress: _scanline.value),
                  ),
                ),
                ],
                // 2. 全息核心：常驻挂载（在背景之上、聚焦环之下；
                //    跨会话复用 three_js 渲染器，隐藏时停帧不渲染）
                if (kUseThreeJsRenderer)
                  IgnorePointer(
                    ignoring: !c.showHud,
                    child: Offstage(
                      offstage: !c.showHud,
                      child: Center(
                        child: SizedBox(
                          width: hologramSize.width,
                          height: hologramSize.height,
                          child: ThreeJsHologramView(
                            transform: c.transform,
                            active: c.showHud,
                            size: hologramSize,
                            glbPath: kHologramGlbPath,
                          ),
                        ),
                      ),
                    ),
                  ),
                // 3. 中央聚焦环
                if (c.showHud) ...[
                Center(
                  child: AnimatedBuilder(
                    animation: Listenable.merge([_sweep, _fade]),
                    builder: (context, child) => SizedBox(
                      width: ringSize,
                      height: ringSize,
                      child: CustomPaint(
                        painter: _CenterHudPainter(
                          sweep: _sweep.value,
                          enter: _fade.value,
                          mode: c.mode,
                        ),
                      ),
                    ),
                  ),
                ),
                // 4. 手部层（Phase 1 无真实数据时不绘制）
                if (c.hands.isNotEmpty)
                  AnimatedBuilder(
                    animation: _sweep,
                    builder: (context, child) => CustomPaint(
                      painter: _HandOverlayPainter(
                        hands: c.hands,
                        pulse: _sweep.value,
                      ),
                    ),
                  ),
                // 5. 信息面板
                _buildTopBar(c, screen),
                _buildLeftPanel(c, screen),
                _buildRightPanel(c, screen),
                _buildObjectPanel(c, screen),
                _buildStatusLine(c, screen),
                _buildBottomProgress(c, screen),
                ],
              ],
            ),
          ),
        );
      },
    );
  }

  // ── 顶栏 ─────────────────────────────────────────────
  Widget _buildTopBar(VisionHudController c, Size screen) {
    final color = _modeColor(c.mode);
    return Positioned(
      top: screen.height * 0.045,
      left: 0,
      right: 0,
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Text(
            'JARVIS VISION SYSTEM',
            style: TextStyle(
              color: Color(0xFF6EB9FF),
              fontSize: 13,
              letterSpacing: 4,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(width: 14),
          AnimatedContainer(
            duration: const Duration(milliseconds: 300),
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              color: color,
              shape: BoxShape.circle,
              boxShadow: [
                BoxShadow(color: color.withValues(alpha: 0.8), blurRadius: 8),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // ── 左面板 SYSTEM STATUS ─────────────────────────────
  Widget _buildLeftPanel(VisionHudController c, Size screen) {
    return Positioned(
      left: 60,
      top: screen.height * 0.16,
      child: HudTerminalShell(
        title: 'SYSTEM STATUS',
        width: screen.width / 7,
        maxHeight: screen.height * 0.32,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _metric('CAMERA', c.frame != null ? 'LIVE' : 'OK', c.frame != null),
            _metric('FPS', '10', true),
            _metric('STATE', _modeShort(c.mode), true),
            _metric(
              'HANDS',
              c.hands.isNotEmpty ? '${c.hands.length} LOCKED' : 'STANDBY',
              c.hands.isNotEmpty,
            ),
          ],
        ),
      ),
    );
  }

  // ── 右面板 VISION DATA ───────────────────────────────
  Widget _buildRightPanel(VisionHudController c, Size screen) {
    return Positioned(
      right: 60,
      top: screen.height * 0.16,
      child: HudTerminalShell(
        title: 'VISION DATA',
        width: screen.width / 7,
        maxHeight: screen.height * 0.32,
        child: AnimatedBuilder(
          animation: _progress,
          builder: (context, child) => Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _metric('SCAN', '${(_progress.value * 100).round()}%', true),
              _metric('RES', '640×360', true),
              _metric('MODEL', 'PENDING', false),
              _metric(
                'FEED',
                c.frame != null ? 'STREAMING' : 'WAIT',
                c.frame != null,
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _metric(String k, String v, bool ok) {
    final color = ok
        ? const Color(0xFF64D8FF)
        : const Color(0xFFB0B7C3);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            k,
            style: const TextStyle(
              color: Color(0xFF6EB9FF),
              fontSize: 10,
              letterSpacing: 1.5,
            ),
          ),
          Text(
            v,
            style: TextStyle(
              color: color,
              fontSize: 11,
              fontWeight: FontWeight.w600,
              letterSpacing: 1,
            ),
          ),
        ],
      ),
    );
  }

  // ── 物体识别结果面板（右侧，VISION DATA 下方）────────────
  Widget _buildObjectPanel(VisionHudController c, Size screen) {
    if (!c.objectScanning && c.objectResult == null) {
      return const SizedBox.shrink();
    }
    final r = c.objectResult;
    final label = r?['label']?.toString() ?? '';
    final category = r?['category']?.toString() ?? '';
    final conf = (r?['confidence'] as num?)?.toDouble() ?? 0.0;
    final info = r?['info']?.toString() ?? '';
    return Positioned(
      right: 60,
      top: screen.height * 0.16 + screen.height * 0.36,
      width: screen.width / 7,
      child: HudTerminalShell(
        title: 'OBJECT FOUND',
        width: screen.width / 7,
        maxHeight: screen.height * 0.22,
        child: AnimatedBuilder(
          animation: _sweep,
          builder: (context, child) {
            if (r == null) {
              return const Padding(
                padding: EdgeInsets.symmetric(vertical: 8),
                child: Text(
                  'SCANNING…',
                  style: TextStyle(
                    color: Color(0xFFFFB347),
                    fontSize: 11,
                    letterSpacing: 2,
                  ),
                ),
              );
            }
            final pct = (conf * 100).round();
            return Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _metric('OBJECT', label.isEmpty ? 'UNKNOWN' : label, conf >= 0.3),
                _metric('CATEGORY', category.isEmpty ? '-' : category, true),
                _metric('CONFIDENCE', '$pct%', conf >= 0.5),
                if (info.isNotEmpty) ...[
                  const SizedBox(height: 6),
                  Text(
                    info,
                    maxLines: 4,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: Color(0xFF9FB4C8),
                      fontSize: 10,
                      height: 1.4,
                    ),
                  ),
                ],
              ],
            );
          },
        ),
      ),
    );
  }

  // ── 中央底部状态大字 ─────────────────────────────────
  Widget _buildStatusLine(VisionHudController c, Size screen) {
    final color = _modeColor(c.mode);
    return Positioned(
      bottom: screen.height * 0.18,
      left: 0,
      right: 0,
      child: Column(
        children: [
          Text(
            _mainLabel(c.mode),
            textAlign: TextAlign.center,
            style: TextStyle(
              color: color,
              fontSize: 22,
              letterSpacing: 5,
              fontWeight: FontWeight.w700,
              shadows: [
                Shadow(color: color.withValues(alpha: 0.7), blurRadius: 12),
              ],
            ),
          ),
          const SizedBox(height: 6),
          Text(
            _subLabel(c),
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: Color(0xFF9FB4C8),
              fontSize: 12,
              letterSpacing: 3,
            ),
          ),
        ],
      ),
    );
  }

  // ── 底部 AI PROCESSING 进度条 ────────────────────────
  Widget _buildBottomProgress(VisionHudController c, Size screen) {
    return Positioned(
      bottom: screen.height * 0.07,
      left: screen.width * 0.30,
      width: screen.width * 0.40,
      child: AnimatedBuilder(
        animation: _progress,
        builder: (context, child) => Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                const Text(
                  'AI PROCESSING',
                  style: TextStyle(
                    color: Color(0xFF6EB9FF),
                    fontSize: 10,
                    letterSpacing: 2,
                  ),
                ),
                const Spacer(),
                Text(
                  '${(_progress.value * 100).round().toString().padLeft(3, '0')}%',
                  style: const TextStyle(
                    color: Color(0xFF64D8FF),
                    fontSize: 10,
                    letterSpacing: 1,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            ClipRRect(
              borderRadius: BorderRadius.circular(2),
              child: LinearProgressIndicator(
                value: _progress.value,
                minHeight: 4,
                backgroundColor: const Color(0x336EB9FF),
                valueColor: const AlwaysStoppedAnimation(Color(0xFF64D8FF)),
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  void dispose() {
    _exitFallback?.cancel();
    _exitFallback = null;
    widget.controller.removeListener(_sync);
    _fade.dispose();
    _scanline.dispose();
    _sweep.dispose();
    _progress.dispose();
    super.dispose();
  }
}

// ── 文案/颜色辅助 ──────────────────────────────────────
String _mainLabel(VisionMode m) {
  switch (m) {
    case VisionMode.initializing:
      return 'INITIALIZING...';
    case VisionMode.scanning:
      return 'VISION ACTIVE';
    case VisionMode.handDetected:
      return 'HAND DETECTED';
    case VisionMode.analyzing:
      return 'ANALYZING';
    case VisionMode.completed:
      return 'COMPLETED';
    case VisionMode.error:
      return 'VISION ERROR';
    case VisionMode.off:
      return '';
  }
}

String _subLabel(VisionHudController c) {
  switch (c.mode) {
    case VisionMode.initializing:
      return 'CAMERA CONNECTED · VISION MODEL READY';
    case VisionMode.scanning:
      return c.hands.isNotEmpty
          ? 'SCANNING ENVIRONMENT'
          : 'HAND TRACKING STANDBY';
    case VisionMode.handDetected:
      return _gestureText(c);
    case VisionMode.analyzing:
      return 'AI PROCESSING FEED';
    case VisionMode.completed:
      return 'SCAN FINALIZED';
    case VisionMode.error:
      return c.error.isNotEmpty ? c.error : 'CAMERA OFFLINE · RETRY';
    case VisionMode.off:
      return '';
  }
}

String _gestureText(VisionHudController c) {
  switch (c.gesturePhase) {
    case GesturePhase.zooming:
      return 'PINCH ZOOM · SCALE x${c.transform.value.scale.toStringAsFixed(2)}';
    case GesturePhase.rotating:
      return 'GESTURE ROTATE · ROLL/PITCH';
    case GesturePhase.moving:
      return 'GESTURE MOVE · TRACKING';
    case GesturePhase.pinchReady:
      return 'PINCH READY';
    case GesturePhase.hover:
      return 'HOVER · GESTURE READY';
    case GesturePhase.grab:
      return 'GRAB · PINCH LOCKED';
    case GesturePhase.transform:
      return 'TRANSFORM · SCALE x${c.transform.value.scale.toStringAsFixed(2)}';
    case GesturePhase.release:
      return 'RELEASE · RESETTING';
    case GesturePhase.idle:
      return 'TRACKING IDLE';
    case GesturePhase.handDetected:
      return 'TRACKING ACTIVE · GESTURE READY';
  }
}

String _modeShort(VisionMode m) {
  switch (m) {
    case VisionMode.initializing:
      return 'INIT';
    case VisionMode.scanning:
      return 'SCAN';
    case VisionMode.handDetected:
      return 'HAND';
    case VisionMode.analyzing:
      return 'AI';
    case VisionMode.completed:
      return 'DONE';
    case VisionMode.error:
      return 'ERR';
    case VisionMode.off:
      return 'OFF';
  }
}

Color _modeColor(VisionMode m) {
  switch (m) {
    case VisionMode.error:
      return const Color(0xFFFF5252);
    case VisionMode.handDetected:
    case VisionMode.analyzing:
      return const Color(0xFFFFB347);
    case VisionMode.completed:
      return const Color(0xFF4ADE80);
    default:
      return const Color(0xFF64D8FF);
  }
}

// ── 画笔 ───────────────────────────────────────────────
class _VisionBackdropPainter extends CustomPainter {
  final ui.Image? frame;
  _VisionBackdropPainter({this.frame});

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    canvas.drawRect(
      rect,
      Paint()
        ..shader = ui.Gradient.linear(
          Offset.zero,
          Offset(0, size.height),
          const [Color(0xF214161B), Color(0xF20A0D14)],
        ),
    );
    final f = frame;
    if (f != null) {
      final fw = f.width.toDouble();
      final fh = f.height.toDouble();
      if (fw > 0 && fh > 0) {
        final scale = math.max(size.width / fw, size.height / fh);
        final dw = fw * scale;
        final dh = fh * scale;
        final dst = Rect.fromLTWH(
          (size.width - dw) / 2,
          (size.height - dh) / 2,
          dw,
          dh,
        );
        canvas.drawImageRect(
          f,
          Rect.fromLTWH(0, 0, fw, fh),
          dst,
          Paint()..filterQuality = ui.FilterQuality.medium,
        );
        // 压暗 + 青色染色 → HUD 感
        canvas.drawRect(rect, Paint()..color = const Color(0x9904141F));
      }
    }
    // 四周渐晕（暗角），聚焦中央
    canvas.drawRect(
      rect,
      Paint()
        ..shader = ui.Gradient.radial(
          rect.center,
          size.shortestSide * 0.7,
          const [Color(0x00000000), Color(0x66000000)],
          [0.55, 1.0],
        ),
    );
  }

  @override
  bool shouldRepaint(covariant _VisionBackdropPainter old) =>
      old.frame != frame;
}

class _ScanGridPainter extends CustomPainter {
  final double progress; // 0..1 扫描线位置
  _ScanGridPainter({required this.progress});

  @override
  void paint(Canvas canvas, Size size) {
    final gridPaint = Paint()
      ..color = const Color(0xFF64D8FF).withValues(alpha: 0.10)
      ..strokeWidth = 0.6;
    // 水平线：越靠下越密（透视）
    for (var i = 1; i <= 10; i++) {
      final t = i / 10.0;
      final y = size.height * math.pow(t, 1.5).toDouble();
      canvas.drawLine(Offset(0, y), Offset(size.width, y), gridPaint);
    }
    // 垂直线：向中心汇聚（伪透视）
    final cx = size.width / 2;
    for (var i = -6; i <= 6; i++) {
      final x = cx + i * (size.width / 12);
      final x2 = cx + i * (size.width / 36);
      canvas.drawLine(Offset(x, 0), Offset(x2, size.height), gridPaint);
    }
    // 扫描线：横向移动 + 辉光拖尾
    final y = size.height * progress;
    canvas.drawLine(
      Offset(0, y),
      Offset(size.width, y),
      Paint()
        ..shader = ui.Gradient.linear(
          Offset(0, y - 60),
          Offset(0, y),
          [
            const Color(0x0064D8FF),
            const Color(0xFF64D8FF).withValues(alpha: 0.5),
          ],
        )
        ..strokeWidth = 2.0,
    );
    canvas.drawLine(
      Offset(0, y),
      Offset(size.width, y),
      Paint()
        ..color = const Color(0xFF64D8FF).withValues(alpha: 0.9)
        ..strokeWidth = 1.2,
    );
  }

  @override
  bool shouldRepaint(covariant _ScanGridPainter old) =>
      old.progress != progress;
}

class _CenterHudPainter extends CustomPainter {
  final double sweep; // 0..1 旋转
  final double enter; // 0..1 进入缩放
  final VisionMode mode;
  _CenterHudPainter({
    required this.sweep,
    required this.enter,
    required this.mode,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final c = size.center(Offset.zero);
    final r = size.shortestSide / 2 * (0.82 + 0.18 * enter);
    final accent = _modeColor(mode);
    const base = Color(0xFF64D8FF);

    // 外圈刻度环（随 sweep 缓转）
    canvas.save();
    canvas.translate(c.dx, c.dy);
    canvas.rotate(sweep * 2 * math.pi);
    for (var i = 0; i < 72; i++) {
      final a = i * 2 * math.pi / 72;
      final major = i % 6 == 0;
      final r1 = r - (major ? 10 : 5);
      canvas.drawLine(
        Offset(math.cos(a) * r1, math.sin(a) * r1),
        Offset(math.cos(a) * r, math.sin(a) * r),
        Paint()
          ..color = (major ? accent : base).withValues(alpha: 0.5)
          ..strokeWidth = 1.0,
      );
    }
    canvas.restore();

    // 主环
    canvas.drawCircle(
      c,
      r,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.4
        ..color = base.withValues(alpha: 0.75),
    );

    // 旋转扫描弧（橙色高亮 + 拖尾）
    final arcStart = sweep * 2 * math.pi;
    canvas.save();
    canvas.translate(c.dx, c.dy);
    canvas.drawArc(
      Rect.fromCircle(center: Offset.zero, radius: r + 8),
      arcStart,
      0.9,
      false,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3.0
        ..strokeCap = StrokeCap.round
        ..shader = ui.Gradient.sweep(
          Offset.zero,
          const [Color(0x00FFB347), Color(0xFFFFB347)],
        ),
    );
    canvas.restore();

    // 内环（反向缓转）
    canvas.save();
    canvas.translate(c.dx, c.dy);
    canvas.rotate(-sweep * 2 * math.pi * 0.5);
    canvas.drawCircle(
      Offset.zero,
      r * 0.78,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 0.8
        ..color = base.withValues(alpha: 0.35),
    );
    canvas.restore();

    // 十字瞄准线
    final cross = Paint()
      ..color = base.withValues(alpha: 0.5)
      ..strokeWidth = 0.8;
    canvas.drawLine(
        Offset(c.dx, c.dy - r * 0.72), Offset(c.dx, c.dy - r * 0.9), cross);
    canvas.drawLine(
        Offset(c.dx, c.dy + r * 0.72), Offset(c.dx, c.dy + r * 0.9), cross);
    canvas.drawLine(
        Offset(c.dx - r * 0.72, c.dy), Offset(c.dx - r * 0.9, c.dy), cross);
    canvas.drawLine(
        Offset(c.dx + r * 0.72, c.dy), Offset(c.dx + r * 0.9, c.dy), cross);

    // 四角角标框
    final b = r * 0.5;
    final bracket = Paint()
      ..color = accent.withValues(alpha: 0.9)
      ..strokeWidth = 2.0;
    const len = 22.0;
    canvas.drawLine(
        Offset(c.dx - b, c.dy - b), Offset(c.dx - b + len, c.dy - b), bracket);
    canvas.drawLine(
        Offset(c.dx - b, c.dy - b), Offset(c.dx - b, c.dy - b + len), bracket);
    canvas.drawLine(
        Offset(c.dx + b, c.dy - b), Offset(c.dx + b - len, c.dy - b), bracket);
    canvas.drawLine(
        Offset(c.dx + b, c.dy - b), Offset(c.dx + b, c.dy - b + len), bracket);
    canvas.drawLine(
        Offset(c.dx - b, c.dy + b), Offset(c.dx - b + len, c.dy + b), bracket);
    canvas.drawLine(
        Offset(c.dx - b, c.dy + b), Offset(c.dx - b, c.dy + b - len), bracket);
    canvas.drawLine(
        Offset(c.dx + b, c.dy + b), Offset(c.dx + b - len, c.dy + b), bracket);
    canvas.drawLine(
        Offset(c.dx + b, c.dy + b), Offset(c.dx + b, c.dy + b - len), bracket);

    // 中心小圆 + 状态色点
    canvas.drawCircle(c, 3, Paint()..color = accent);
    canvas.drawCircle(
      c,
      6,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1
        ..color = accent.withValues(alpha: 0.6),
    );
  }

  @override
  bool shouldRepaint(covariant _CenterHudPainter old) =>
      old.sweep != sweep || old.enter != enter || old.mode != mode;
}

class _HandOverlayPainter extends CustomPainter {
  final List<VisionHand> hands;
  final double pulse; // 0..1 波纹相位
  _HandOverlayPainter({required this.hands, required this.pulse});

  @override
  void paint(Canvas canvas, Size size) {
    for (final hand in hands) {
      final pts = hand.landmarks
          .map((p) => Offset(p.dx * size.width, p.dy * size.height))
          .toList();
      if (pts.length < 21) continue;
      // 骨骼连线：先粗 glow 后细线
      final glow = Paint()
        ..color = const Color(0xFF64D8FF).withValues(alpha: 0.18)
        ..strokeWidth = 4.0
        ..strokeCap = StrokeCap.round;
      final line = Paint()
        ..color = const Color(0xFF64D8FF).withValues(alpha: 0.9)
        ..strokeWidth = 1.6
        ..strokeCap = StrokeCap.round;
      for (final (a, b) in _handBones) {
        canvas.drawLine(pts[a], pts[b], glow);
        canvas.drawLine(pts[a], pts[b], line);
      }
      // 关键点：发光圆点
      for (final p in pts) {
        canvas.drawCircle(p, 4.5, Paint()..color = const Color(0x2264D8FF));
        canvas.drawCircle(p, 2.2, Paint()..color = const Color(0xFFBFF4FF));
      }
      // 掌心检测波纹（pulse 相位扩散）
      final wrist = pts[0];
      final rippleR = 8 + pulse * 46;
      canvas.drawCircle(
        wrist,
        rippleR,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.2
          ..color = const Color(0xFFFFB347).withValues(alpha: (1 - pulse) * 0.8),
      );
    }
  }

  @override
  bool shouldRepaint(covariant _HandOverlayPainter old) =>
      old.hands != hands || old.pulse != pulse;
}
