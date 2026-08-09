import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'hud_terminal_shell.dart';

/// 地图态势卡片（左上角悬浮）
///
/// Flutter 原生绘制的 JARVIS 全球态势图（正射投影，亚洲为中心）：
/// 深蓝玻璃底 + 经纬网格 + 全球节点（hub/node/hot）+ 数据弧线流动 +
/// 扫描环 + 轨道粒子 + 热点脉冲。随唤醒显示 / 待机隐藏（wake/hide 命令）。
///
/// 实现说明：不依赖 WebView（macOS 透明 overlay 窗口上 WKWebView 内容不合成，
/// 且页面 JS 会被冻结），改用 CustomPainter 全原生绘制，动画走 Flutter 引擎，
/// 与环形特效/聊天面板同一渲染管线，稳定可靠。

enum CityType { hub, node, hot }

class _City {
  final String name;
  final double lat;
  final double lon;
  final CityType type;
  const _City(this.name, this.lat, this.lon, this.type);
}

const List<_City> _cities = [
  _City('Shanghai', 31.23, 121.47, CityType.hub),
  _City('Beijing', 39.9, 116.4, CityType.hub),
  _City('Shenzhen', 22.54, 114.06, CityType.hot),
  _City('Hong Kong', 22.32, 114.17, CityType.hot),
  _City('Tokyo', 35.68, 139.69, CityType.hub),
  _City('Seoul', 37.57, 126.98, CityType.node),
  _City('Singapore', 1.35, 103.82, CityType.hot),
  _City('Mumbai', 19.08, 72.88, CityType.hot),
  _City('Bengaluru', 12.97, 77.59, CityType.node),
  _City('Dubai', 25.2, 55.27, CityType.hub),
  _City('Bangkok', 13.76, 100.5, CityType.node),
  _City('Jakarta', -6.21, 106.85, CityType.node),
  _City('Manila', 14.6, 120.98, CityType.node),
  _City('Taipei', 25.03, 121.57, CityType.node),
  _City('Sydney', -33.87, 151.21, CityType.hub),
  _City('Melbourne', -37.81, 144.96, CityType.node),
  _City('Auckland', -36.85, 174.76, CityType.node),
  _City('London', 51.51, -0.13, CityType.hub),
  _City('Frankfurt', 50.11, 8.68, CityType.hub),
  _City('Paris', 48.86, 2.35, CityType.node),
  _City('Berlin', 52.52, 13.4, CityType.node),
  _City('Moscow', 55.76, 37.62, CityType.hot),
  _City('Madrid', 40.42, -3.7, CityType.node),
  _City('Stockholm', 59.33, 18.07, CityType.node),
  _City('New York', 40.71, -74.01, CityType.hub),
  _City('San Francisco', 37.77, -122.42, CityType.hub),
  _City('Seattle', 47.61, -122.33, CityType.node),
  _City('Toronto', 43.65, -79.38, CityType.node),
  _City('Chicago', 41.88, -87.63, CityType.node),
  _City('Mexico City', 19.43, -99.13, CityType.hot),
  _City('Los Angeles', 34.05, -118.24, CityType.node),
  _City('Sao Paulo', -23.55, -46.63, CityType.hot),
  _City('Buenos Aires', -34.6, -58.38, CityType.node),
  _City('Santiago', -33.45, -70.67, CityType.node),
  _City('Bogota', 4.71, -74.07, CityType.node),
  _City('Lagos', 6.52, 3.38, CityType.hot),
  _City('Cairo', 30.04, 31.24, CityType.node),
  _City('Johannesburg', -26.2, 28.05, CityType.node),
  _City('Nairobi', -1.29, 36.82, CityType.node),
  _City('Cape Town', -33.92, 18.42, CityType.node),
];

const List<(String, String)> _arcs = [
  ('Shanghai', 'Tokyo'),
  ('Shanghai', 'Singapore'),
  ('Shanghai', 'London'),
  ('Shanghai', 'San Francisco'),
  ('Beijing', 'Moscow'),
  ('Beijing', 'Frankfurt'),
  ('Tokyo', 'Seoul'),
  ('Singapore', 'Sydney'),
  ('Singapore', 'Mumbai'),
  ('Mumbai', 'Dubai'),
  ('Dubai', 'London'),
  ('London', 'New York'),
  ('London', 'Lagos'),
  ('New York', 'San Francisco'),
  ('New York', 'Sao Paulo'),
  ('San Francisco', 'Sydney'),
  ('Frankfurt', 'Nairobi'),
  ('Tokyo', 'New York'),
];

/// 正射投影：经纬度 → 画布坐标（亚洲为中心 lat0=20, lon0=105）
class _OrthoProjector {
  final double lat0;
  final double lon0;
  final double radius;
  final Offset center;

  _OrthoProjector({required this.radius, required this.center})
      : lat0 = 20.0 * math.pi / 180.0,
        lon0 = 105.0 * math.pi / 180.0;

  double _rad(double d) => d * math.pi / 180.0;

  /// 返回屏幕坐标；背面（z<0）返回 null
  Offset? project(double lat, double lon) {
    final phi = _rad(lat);
    final lambda = _rad(lon);
    final x = radius * math.cos(phi) * math.sin(lambda - lon0);
    final y = radius *
        (math.cos(lat0) * math.sin(phi) -
            math.sin(lat0) * math.cos(phi) * math.cos(lambda - lon0));
    final z = radius *
        (math.sin(lat0) * math.sin(phi) +
            math.cos(lat0) * math.cos(phi) * math.cos(lambda - lon0));
    if (z < 0) return null;
    return Offset(center.dx + x, center.dy - y);
  }
}

class _GlobePainter extends CustomPainter {
  final double time; // 0..1 循环时间源
  final List<double> stats;

  _GlobePainter({required this.time, required this.stats});

  static const _cyan = Color(0xFF35D0FF);
  static const _cyanDim = Color(0xFF2F8CFF);
  static const _hubColor = Color(0xFF66E0FF);
  static const _nodeColor = Color(0xFF4F9DFF);
  static const _hotColor = Color(0xFFFFB347);

  @override
  void paint(Canvas canvas, Size size) {
    final c = size.center(Offset.zero);
    final R = math.min(size.width, size.height) * 0.42;
    final proj = _OrthoProjector(radius: R, center: c);

    _paintEarth(canvas, c, R);
    _paintGrid(canvas, proj);
    _paintArcs(canvas, proj, time);
    _paintNodes(canvas, proj, time);
    _paintScanRing(canvas, c, R, time);
    _paintParticles(canvas, c, R, time);
  }

  void _paintEarth(Canvas canvas, Offset c, double R) {
    // 地球本体：径向渐变（中心亮蓝 → 边缘深蓝黑）
    final rect = Rect.fromCircle(center: c, radius: R);
    final shade = Paint()
      ..shader = RadialGradient(
        center: const Alignment(-0.35, -0.3),
        radius: 1.2,
        colors: [
          const Color(0xFF2A5F9E),
          const Color(0xFF123A6E),
          const Color(0xFF081C38),
          const Color(0xFF040D1C),
        ],
        stops: const [0.0, 0.45, 0.8, 1.0],
      ).createShader(rect);
    canvas.drawCircle(c, R, shade);

    // 大气辉光
    final glow = Paint()
      ..shader = RadialGradient(
        colors: [
          const Color(0x553F8DFF),
          const Color(0x221A4F8A),
          const Color(0x00000000),
        ],
        stops: const [0.0, 0.6, 1.0],
      ).createShader(Rect.fromCircle(center: c, radius: R * 1.28));
    canvas.drawCircle(c, R * 1.28, glow);

    // 外圈细线
    canvas.drawCircle(
      c,
      R * 1.03,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1
        ..color = _cyanDim.withValues(alpha: 0.35),
    );
  }

  void _paintGrid(Canvas canvas, _OrthoProjector proj) {
    final gridPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 0.7
      ..color = _cyanDim.withValues(alpha: 0.30);
    // 经线（每 30°）
    for (int lon = -150; lon <= 150; lon += 30) {
      final path = Path();
      bool started = false;
      for (int lat = -80; lat <= 80; lat += 4) {
        final p = proj.project(lat.toDouble(), lon.toDouble());
        if (p != null) {
          started ? path.lineTo(p.dx, p.dy) : path.moveTo(p.dx, p.dy);
          started = true;
        } else {
          started = false;
        }
      }
      canvas.drawPath(path, gridPaint);
    }
    // 纬线（每 30°）
    for (int lat = -60; lat <= 60; lat += 30) {
      final path = Path();
      bool started = false;
      for (int lon = -180; lon <= 180; lon += 4) {
        final p = proj.project(lat.toDouble(), lon.toDouble());
        if (p != null) {
          started ? path.lineTo(p.dx, p.dy) : path.moveTo(p.dx, p.dy);
          started = true;
        } else {
          started = false;
        }
      }
      canvas.drawPath(path, gridPaint);
    }
  }

  void _paintArcs(Canvas canvas, _OrthoProjector proj, double time) {
    final byName = {for (final c in _cities) c.name: c};
    for (final (aName, bName) in _arcs) {
      final a = byName[aName];
      final b = byName[bName];
      if (a == null || b == null) continue;
      final pa = proj.project(a.lat, a.lon);
      final pb = proj.project(b.lat, b.lon);
      if (pa == null || pb == null) continue;

      // 弧线控制点：中点向观察者抬高
      final mid = Offset((pa.dx + pb.dx) / 2, (pa.dy + pb.dy) / 2);
      final lift = (pa - pb).distance * 0.28 + 6.0;
      final control = mid + const Offset(0, -1) * lift;

      final path = Path()
        ..moveTo(pa.dx, pa.dy)
        ..quadraticBezierTo(control.dx, control.dy, pb.dx, pb.dy);

      // 流动虚线：dash 偏移随时间滚动
      final dash = 4.0 + (aName.hashCode % 3) * 1.5;
      final gap = 3.5;
      final total = dash + gap;
      final offset = (time * 90.0 + (aName.hashCode % 20)) % total;
      final metric = path.computeMetrics().first;
      final dashPaint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.3
        ..color = _cyan.withValues(alpha: 0.85);
      for (double d = -offset; d < metric.length; d += total) {
        canvas.drawPath(
          metric.extractPath(d.clamp(0.0, metric.length),
              (d + dash).clamp(0.0, metric.length)),
          dashPaint,
        );
      }

      // 移动光点
      final t = (time * 1.7 + (aName.hashCode % 7) / 7.0) % 1.0;
      final pos = _quadPoint(pa, control, pb, t);
      _glowDot(canvas, pos, 3.6, _cyan, 0.95);
    }
  }

  Offset _quadPoint(Offset a, Offset ctrl, Offset b, double t) {
    final u = 1 - t;
    return Offset(
      u * u * a.dx + 2 * u * t * ctrl.dx + t * t * b.dx,
      u * u * a.dy + 2 * u * t * ctrl.dy + t * t * b.dy,
    );
  }

  void _paintNodes(Canvas canvas, _OrthoProjector proj, double time) {
    for (final c in _cities) {
      final p = proj.project(c.lat, c.lon);
      if (p == null) continue;
      final pulse = 0.5 + 0.5 * math.sin(time * 2 * math.pi * 2 + c.lat);
      switch (c.type) {
        case CityType.hub:
          _glowDot(canvas, p, 3.6, _hubColor, 0.95);
          break;
        case CityType.node:
          _glowDot(canvas, p, 2.6, _nodeColor, 0.85);
          break;
        case CityType.hot:
          // 热点：橙色核心 + 脉冲光晕 + 描边定位环（醒目）
          _glowDot(canvas, p, 4.6, _hotColor, 1.0);
          _glowDot(canvas, p, 9.0 + pulse * 4.5, _hotColor, 0.42);
          canvas.drawCircle(
            p,
            6.2 + pulse * 2.2,
            Paint()
              ..style = PaintingStyle.stroke
              ..strokeWidth = 1.1
              ..color = _hotColor.withValues(alpha: 0.75)
              ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 2),
          );
          break;
      }
    }
  }

  void _glowDot(Canvas canvas, Offset p, double r, Color color, double alpha) {
    canvas.drawCircle(
      p,
      r,
      Paint()
        ..shader = RadialGradient(
          colors: [
            color.withValues(alpha: alpha),
            color.withValues(alpha: alpha * 0.25),
            color.withValues(alpha: 0.0),
          ],
          stops: const [0.0, 0.5, 1.0],
        ).createShader(Rect.fromCircle(center: p, radius: r)),
    );
  }

  void _paintScanRing(Canvas canvas, Offset c, double R, double time) {
    final a = time * 2 * math.pi;
    final ringR = R * 1.18;
    // 整圈淡色环
    canvas.drawCircle(
      c,
      ringR,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.2
        ..color = _cyanDim.withValues(alpha: 0.30),
    );
    // 扫描亮弧（跟随时间旋转）
    final sweep = 0.9;
    canvas.drawArc(
      Rect.fromCircle(center: c, radius: ringR),
      a,
      sweep,
      false,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.4
        ..strokeCap = StrokeCap.round
        ..color = _cyan.withValues(alpha: 0.8)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 3),
    );
    // 扫描亮点
    final tip = Offset(c.dx + ringR * math.cos(a), c.dy + ringR * math.sin(a));
    _glowDot(canvas, tip, 4.0, _cyan, 0.9);
  }

  void _paintParticles(Canvas canvas, Offset c, double R, double time) {
    final rand = math.Random(42);
    for (int i = 0; i < 36; i++) {
      final r0 = R * (1.35 + rand.nextDouble() * 1.1);
      final ang0 = rand.nextDouble() * 2 * math.pi;
      final ang = ang0 + time * 2 * math.pi * (0.15 + rand.nextDouble() * 0.1);
      final p = Offset(c.dx + r0 * math.cos(ang), c.dy + r0 * math.sin(ang) * 0.86);
      final a = 0.18 + rand.nextDouble() * 0.4;
      canvas.drawCircle(
        p,
        0.9 + rand.nextDouble(),
        Paint()..color = const Color(0xFF8FC8FF).withValues(alpha: a),
      );
    }
  }

  @override
  bool shouldRepaint(covariant _GlobePainter old) => old.time != time;
}

class MapGlobeCard extends StatefulWidget {
  final double width;
  final double height;

  const MapGlobeCard({super.key, required this.width, required this.height});

  @override
  State<MapGlobeCard> createState() => _MapGlobeCardState();
}

class _MapGlobeCardState extends State<MapGlobeCard>
    with SingleTickerProviderStateMixin {
  late final AnimationController _anim;
  int _flow = 9;
  int _agents = 6;
  String _risk = 'LOW';

  @override
  void initState() {
    super.initState();
    _anim = AnimationController(vsync: this, duration: const Duration(seconds: 10))
      ..repeat();
    _startStatsTimer();
  }

  void _startStatsTimer() {
    Timer.periodic(const Duration(seconds: 2), (_) {
      if (!mounted) return;
      setState(() {
        _flow = 8 + (_anim.value * 5).round() % 5;
        _agents = 6 + (DateTime.now().second % 3);
        _risk = ['LOW', 'LOW', 'MODERATE'][DateTime.now().second % 3];
      });
    });
  }

  @override
  void dispose() {
    _anim.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return HudTerminalShell(
      title: 'GLOBAL SATCOM',
      width: widget.width,
      maxHeight: widget.height,
      child: SizedBox(
        width: widget.width - 32,
        height: widget.height - 84,
        child: Column(
          children: [
            Expanded(
              child: AnimatedBuilder(
                animation: _anim,
                builder: (context, child) {
                  return CustomPaint(
                    painter: _GlobePainter(time: _anim.value, stats: const []),
                    size: Size.infinite,
                  );
                },
              ),
            ),
            const SizedBox(height: 6),
            _StatsRow(flow: _flow, agents: _agents, risk: _risk),
          ],
        ),
      ),
    );
  }
}

class _StatsRow extends StatelessWidget {
  final int flow;
  final int agents;
  final String risk;

  const _StatsRow({required this.flow, required this.agents, required this.risk});

  @override
  Widget build(BuildContext context) {
    Color riskColor = const Color(0xFF3DFF8A);
    if (risk == 'MODERATE') riskColor = const Color(0xFFFFB347);
    return Row(
      children: [
        _stat('NODES', '${_cities.length}'),
        _stat('FLOW', '$flow'),
        _stat('AGENTS', '$agents'),
        _stat('RISK', risk, riskColor),
      ],
    );
  }

  Widget _stat(String label, String value, [Color? valueColor]) {
    return Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: TextStyle(
              color: const Color(0xFF5F87B8).withValues(alpha: 0.9),
              fontSize: 6.5,
              letterSpacing: 1.2,
            ),
          ),
          Text(
            value,
            style: TextStyle(
              color: valueColor ?? const Color(0xFF35D0FF),
              fontSize: 11,
              fontWeight: FontWeight.w600,
              letterSpacing: 0.5,
            ),
          ),
        ],
      ),
    );
  }
}
