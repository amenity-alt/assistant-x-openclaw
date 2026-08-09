import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'hud_terminal_shell.dart';

/// 地图态势卡片（左上角悬浮）
///
/// Flutter 原生绘制的 JARVIS 全球态势图（正射投影，亚洲为中心）：
/// 深蓝玻璃底 + 经纬网格 + 全球节点（hub/node/hot）+ 数据弧线流动 +
/// 扫描环 + 轨道粒子 + 热点脉冲。
///
/// 扩展能力（本版本新增）：
///  - 缩放：voice 指令 `map_zoom +|-|reset`（overlay 点击穿透，交互走语音）
///  - 定位：voice 指令 `map_locate <城市>` → 自动飞行到目标城市并放大
///  - 资讯：voice 定位后 Python 侧抓取城市热点，`map_news {json}` 推送展示
///  - 信息栏位：Memory Log（记忆中心）+ 快捷按钮（UPLOAD/ARCHIVE/SUMMARY）
///
/// 实现说明：不依赖 WebView（macOS 透明 overlay 窗口上 WKWebView 内容不合成），
/// 使用 CustomPainter 全原生绘制，动画走 Flutter 引擎。

enum CityType { hub, node, hot }

class _City {
  final String name;
  final String zh;
  final double lat;
  final double lon;
  final CityType type;
  const _City(this.name, this.zh, this.lat, this.lon, this.type);
}

const List<_City> _cities = [
  _City('Shanghai', '上海', 31.23, 121.47, CityType.hub),
  _City('Beijing', '北京', 39.9, 116.4, CityType.hub),
  _City('Guangzhou', '广州', 23.13, 113.26, CityType.hot),
  _City('Shenzhen', '深圳', 22.54, 114.06, CityType.hot),
  _City('Hong Kong', '香港', 22.32, 114.17, CityType.hot),
  _City('Hangzhou', '杭州', 30.27, 120.16, CityType.hub),
  _City('Chengdu', '成都', 30.57, 104.07, CityType.hub),
  _City('Wuhan', '武汉', 30.59, 114.31, CityType.node),
  _City('Xian', '西安', 34.34, 108.94, CityType.node),
  _City('Nanjing', '南京', 32.06, 118.8, CityType.node),
  _City('Chongqing', '重庆', 29.56, 106.55, CityType.hot),
  _City('Tianjin', '天津', 39.13, 117.2, CityType.node),
  _City('Suzhou', '苏州', 31.3, 120.58, CityType.node),
  _City('Qingdao', '青岛', 36.07, 120.38, CityType.node),
  _City('Xiamen', '厦门', 24.48, 118.09, CityType.node),
  _City('Changsha', '长沙', 28.23, 112.94, CityType.node),
  _City('Zhengzhou', '郑州', 34.75, 113.63, CityType.node),
  _City('Hefei', '合肥', 31.82, 117.23, CityType.node),
  _City('Kunming', '昆明', 25.04, 102.71, CityType.node),
  _City('Dalian', '大连', 38.91, 121.61, CityType.node),
  _City('Haikou', '海口', 20.04, 110.32, CityType.node),
  _City('Harbin', '哈尔滨', 45.8, 126.53, CityType.node),
  _City('Taipei', '台北', 25.03, 121.57, CityType.node),
  _City('Tokyo', '东京', 35.68, 139.69, CityType.hub),
  _City('Seoul', '首尔', 37.57, 126.98, CityType.node),
  _City('Singapore', '新加坡', 1.35, 103.82, CityType.hot),
  _City('Mumbai', '孟买', 19.08, 72.88, CityType.hot),
  _City('Bengaluru', '班加罗尔', 12.97, 77.59, CityType.node),
  _City('Dubai', '迪拜', 25.2, 55.27, CityType.hub),
  _City('Bangkok', '曼谷', 13.76, 100.5, CityType.node),
  _City('Jakarta', '雅加达', -6.21, 106.85, CityType.node),
  _City('Manila', '马尼拉', 14.6, 120.98, CityType.node),
  _City('Sydney', '悉尼', -33.87, 151.21, CityType.hub),
  _City('Melbourne', '墨尔本', -37.81, 144.96, CityType.node),
  _City('Auckland', '奥克兰', -36.85, 174.76, CityType.node),
  _City('London', '伦敦', 51.51, -0.13, CityType.hub),
  _City('Frankfurt', '法兰克福', 50.11, 8.68, CityType.hub),
  _City('Paris', '巴黎', 48.86, 2.35, CityType.node),
  _City('Berlin', '柏林', 52.52, 13.4, CityType.node),
  _City('Moscow', '莫斯科', 55.76, 37.62, CityType.hot),
  _City('Madrid', '马德里', 40.42, -3.7, CityType.node),
  _City('Stockholm', '斯德哥尔摩', 59.33, 18.07, CityType.node),
  _City('New York', '纽约', 40.71, -74.01, CityType.hub),
  _City('San Francisco', '旧金山', 37.77, -122.42, CityType.hub),
  _City('Seattle', '西雅图', 47.61, -122.33, CityType.node),
  _City('Toronto', '多伦多', 43.65, -79.38, CityType.node),
  _City('Chicago', '芝加哥', 41.88, -87.63, CityType.node),
  _City('Mexico City', '墨西哥城', 19.43, -99.13, CityType.hot),
  _City('Los Angeles', '洛杉矶', 34.05, -118.24, CityType.node),
  _City('Sao Paulo', '圣保罗', -23.55, -46.63, CityType.hot),
  _City('Buenos Aires', '布宜诺斯艾利斯', -34.6, -58.38, CityType.node),
  _City('Santiago', '圣地亚哥', -33.45, -70.67, CityType.node),
  _City('Bogota', '波哥大', 4.71, -74.07, CityType.node),
  _City('Lagos', '拉各斯', 6.52, 3.38, CityType.hot),
  _City('Cairo', '开罗', 30.04, 31.24, CityType.node),
  _City('Johannesburg', '约翰内斯堡', -26.2, 28.05, CityType.node),
  _City('Nairobi', '内罗毕', -1.29, 36.82, CityType.node),
  _City('Cape Town', '开普敦', -33.92, 18.42, CityType.node),
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
  ('Shenzhen', 'Beijing'),
  ('Shenzhen', 'Shanghai'),
  ('Hangzhou', 'Chengdu'),
  ('Wuhan', 'Shanghai'),
  ('Guangzhou', 'Shenzhen'),
  ('Chongqing', 'Chengdu'),
];

/// 资讯条目（Python 侧 map_news 推送）
class MapNewsItem {
  final String title;
  final String source;
  final String time;
  const MapNewsItem({required this.title, this.source = '', this.time = ''});
}

/// 地图视图控制器：overlay 通过 TCP 命令驱动（缩放 / 定位 / 资讯）
class MapGlobeController extends ChangeNotifier {
  double targetZoom = 1.0;
  double targetLat = 20.0;
  double targetLon = 105.0;
  String? locatedCity;
  List<MapNewsItem> news = const [];

  void zoomIn() {
    targetZoom = (targetZoom + 0.35).clamp(1.0, 3.0);
    notifyListeners();
  }

  void zoomOut() {
    targetZoom = (targetZoom - 0.35).clamp(1.0, 3.0);
    notifyListeners();
  }

  void reset() {
    targetZoom = 1.0;
    targetLat = 20.0;
    targetLon = 105.0;
    locatedCity = null;
    news = const [];
    notifyListeners();
  }

  void locateTo(double lat, double lon, String city) {
    targetLat = lat;
    targetLon = lon;
    targetZoom = 2.4;
    locatedCity = city;
    notifyListeners();
  }

  void setNews(String city, List<MapNewsItem> items) {
    news = items;
    locatedCity = city;
    notifyListeners();
  }
}

/// 中文城市名 → 坐标（定位用；支持简称/带市后缀/英文名）
({double lat, double lon})? locateCityZh(String query) {
  final q = query.trim().replaceAll('市', '').toLowerCase();
  if (q.isEmpty) return null;
  _City? best;
  var bestLen = 0;
  for (final c in _cities) {
    final zh = c.zh.toLowerCase();
    final en = c.name.toLowerCase();
    if (zh == q || en == q) {
      return (lat: c.lat, lon: c.lon);
    }
    if (q.contains(zh) && zh.length > bestLen) {
      best = c;
      bestLen = zh.length;
    }
  }
  if (best != null) return (lat: best.lat, lon: best.lon);
  return null;
}

/// 正射投影：经纬度 → 画布坐标（中心 lat0/lon0，半径随 zoom 缩放）
class _OrthoProjector {
  final double lat0;
  final double lon0;
  final double radius;
  final Offset center;

  _OrthoProjector({
    required this.radius,
    required this.center,
    required this.lat0,
    required this.lon0,
  });

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
  final double zoom; // 1.0~3.0
  final double lat0;
  final double lon0;

  _GlobePainter({
    required this.time,
    required this.zoom,
    required this.lat0,
    required this.lon0,
  });

  static const _cyan = Color(0xFF35D0FF);
  static const _cyanDim = Color(0xFF2F8CFF);
  static const _hubColor = Color(0xFF66E0FF);
  static const _nodeColor = Color(0xFF4F9DFF);
  static const _hotColor = Color(0xFFFFB347);

  @override
  void paint(Canvas canvas, Size size) {
    final c = size.center(Offset.zero);
    final R = math.min(size.width, size.height) * 0.42 * zoom;
    final proj = _OrthoProjector(radius: R, center: c, lat0: lat0, lon0: lon0);

    _paintEarth(canvas, c, R);
    _paintGrid(canvas, proj, zoom);
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

  void _paintGrid(Canvas canvas, _OrthoProjector proj, double zoom) {
    // 放大时加密经纬网格
    final step = zoom > 1.6 ? 10.0 : 30.0;
    final gridPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 0.7
      ..color = _cyanDim.withValues(alpha: zoom > 1.6 ? 0.22 : 0.30);
    for (double lon = -180; lon <= 180; lon += step) {
      final path = Path();
      bool started = false;
      for (double lat = -80; lat <= 80; lat += 4) {
        final p = proj.project(lat, lon);
        if (p != null) {
          started ? path.lineTo(p.dx, p.dy) : path.moveTo(p.dx, p.dy);
          started = true;
        } else {
          started = false;
        }
      }
      canvas.drawPath(path, gridPaint);
    }
    for (double lat = -80; lat <= 80; lat += step) {
      final path = Path();
      bool started = false;
      for (double lon = -180; lon <= 180; lon += 4) {
        final p = proj.project(lat, lon);
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
  bool shouldRepaint(covariant _GlobePainter old) =>
      old.time != time || old.zoom != zoom || old.lat0 != lat0 || old.lon0 != lon0;
}

class MapGlobeCard extends StatefulWidget {
  final double width;
  final double height;
  final MapGlobeController controller;

  const MapGlobeCard({
    super.key,
    required this.width,
    required this.height,
    required this.controller,
  });

  @override
  State<MapGlobeCard> createState() => _MapGlobeCardState();
}

class _MapGlobeCardState extends State<MapGlobeCard>
    with TickerProviderStateMixin {
  late final AnimationController _anim;
  late final AnimationController _view;
  late final CurvedAnimation _viewCurve;
  late MapGlobeController _controller;

  late Tween<double> _zoomTween;
  late Tween<double> _latTween;
  late Tween<double> _lonTween;

  int _flow = 9;
  int _agents = 6;
  String _risk = 'LOW';

  @override
  void initState() {
    super.initState();
    _controller = widget.controller;
    _anim = AnimationController(vsync: this, duration: const Duration(seconds: 10))
      ..repeat();
    _view = AnimationController(
        vsync: this, duration: const Duration(milliseconds: 900));
    _viewCurve = CurvedAnimation(parent: _view, curve: Curves.easeInOutCubic);
    _zoomTween = Tween(begin: 1.0, end: _controller.targetZoom);
    _latTween = Tween(begin: 20.0, end: _controller.targetLat);
    _lonTween = Tween(begin: 105.0, end: _controller.targetLon);
    _controller.addListener(_onViewChanged);
    _startStatsTimer();
  }

  void _onViewChanged() {
    if (!mounted) return;
    setState(() {
      final z = _zoomTween.evaluate(_viewCurve);
      final la = _latTween.evaluate(_viewCurve);
      final lo = _lonTween.evaluate(_viewCurve);
      _zoomTween = Tween(begin: z, end: _controller.targetZoom);
      _latTween = Tween(begin: la, end: _controller.targetLat);
      _lonTween = Tween(begin: lo, end: _controller.targetLon);
      _view.forward(from: 0);
    });
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
    _controller.removeListener(_onViewChanged);
    _view.dispose();
    _viewCurve.dispose();
    _anim.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final zoom = _zoomTween.evaluate(_viewCurve);
    final lat = _latTween.evaluate(_viewCurve);
    final lon = _lonTween.evaluate(_viewCurve);

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
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Expanded(
                    flex: 56,
                    child: AnimatedBuilder(
                      animation: Listenable.merge([_anim, _view]),
                      builder: (context, child) {
                        return CustomPaint(
                          painter: _GlobePainter(
                            time: _anim.value,
                            zoom: zoom,
                            lat0: lat,
                            lon0: lon,
                          ),
                          size: Size.infinite,
                        );
                      },
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    flex: 44,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Expanded(
                          flex: 2,
                          child: _MemoryLog(),
                        ),
                        const SizedBox(height: 6),
                        Expanded(
                          flex: 3,
                          child: _NewsPanel(
                            controller: _controller,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 6),
            _StatsRow(flow: _flow, agents: _agents, risk: _risk, zoom: zoom),
            const SizedBox(height: 6),
            const _QuickButtons(),
          ],
        ),
      ),
    );
  }
}

/// Memory Log（记忆中心）— 彩色状态点 + 状态图标 + 时间
class _MemoryLog extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    String hm(int s) {
      final t = DateTime.fromMillisecondsSinceEpoch(
          now.millisecondsSinceEpoch - s * 1000);
      return '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
    }

    return Container(
      decoration: BoxDecoration(
        color: const Color(0x140D67BC),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFF35D0FF).withValues(alpha: 0.22)),
      ),
      padding: const EdgeInsets.all(8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _MiniHeader('MEMORY LOG'),
          const SizedBox(height: 4),
          Expanded(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.spaceEvenly,
              children: [
                _LogRow(
                  label: 'User Analysis Completed',
                  color: const Color(0xFF3DFF8A),
                  time: hm(12),
                  done: true,
                ),
                _LogRow(
                  label: 'Knowledge Graph Updated',
                  color: const Color(0xFF3DFF8A),
                  time: hm(48),
                  done: true,
                ),
                _LogRow(
                  label: 'SQL Optimization Finished',
                  color: const Color(0xFF35D0FF),
                  time: hm(126),
                  done: true,
                ),
                _LogRow(
                  label: 'Agent Task Running',
                  color: const Color(0xFFFFB347),
                  time: hm(2),
                  done: false,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _LogRow extends StatelessWidget {
  final String label;
  final Color color;
  final String time;
  final bool done;
  const _LogRow({
    required this.label,
    required this.color,
    required this.time,
    required this.done,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 6,
          height: 6,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: color,
            boxShadow: [
              BoxShadow(color: color.withValues(alpha: 0.7), blurRadius: 4),
            ],
          ),
        ),
        const SizedBox(width: 5),
        Expanded(
          child: Text(
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              color: const Color(0xFFB7D8F5).withValues(alpha: 0.95),
              fontSize: 8,
              letterSpacing: 0.2,
            ),
          ),
        ),
        const SizedBox(width: 4),
        Text(
          done ? '✓' : '◐',
          style: TextStyle(
            color: color,
            fontSize: 9,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(width: 4),
        Text(
          time,
          style: TextStyle(
            color: const Color(0xFF5F87B8),
            fontSize: 7.5,
          ),
        ),
      ],
    );
  }
}

/// 城市热点资讯面板（定位后显示）
class _NewsPanel extends StatelessWidget {
  final MapGlobeController controller;
  const _NewsPanel({required this.controller});

  @override
  Widget build(BuildContext context) {
    final city = controller.locatedCity;
    final items = controller.news;
    return Container(
      decoration: BoxDecoration(
        color: const Color(0x140D67BC),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
            color: const Color(0xFFFFB347).withValues(alpha: 0.35)),
      ),
      padding: const EdgeInsets.all(8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _MiniHeader(city == null ? 'HOT SIGNAL' : '📍 $city 热点'),
          const SizedBox(height: 4),
          Expanded(
            child: items.isEmpty
                ? Center(
                    child: Text(
                      city == null ? '未定位 · 说"定位到城市"' : '获取最新资讯中...',
                      style: TextStyle(
                        color: const Color(0xFF5F87B8).withValues(alpha: 0.9),
                        fontSize: 8,
                      ),
                    ),
                  )
                : ListView.builder(
                    padding: EdgeInsets.zero,
                    itemCount: items.length,
                    itemBuilder: (context, i) {
                      final it = items[i];
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 4),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '${i + 1}',
                              style: TextStyle(
                                color: const Color(0xFFFFB347),
                                fontSize: 8,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            const SizedBox(width: 4),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    it.title,
                                    maxLines: 2,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(
                                      color: Color(0xFFDCEEFF),
                                      fontSize: 8,
                                      height: 1.25,
                                    ),
                                  ),
                                  if (it.source.isNotEmpty || it.time.isNotEmpty)
                                    Text(
                                      [it.source, it.time]
                                          .where((s) => s.isNotEmpty)
                                          .join(' · '),
                                      style: TextStyle(
                                        color: const Color(0xFF5F87B8),
                                        fontSize: 6.5,
                                      ),
                                    ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}

class _MiniHeader extends StatelessWidget {
  final String text;
  const _MiniHeader(this.text);
  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(
        color: Color(0xFF6EB9FF),
        fontSize: 7.5,
        letterSpacing: 1.4,
        fontWeight: FontWeight.w600,
      ),
    );
  }
}

class _StatsRow extends StatelessWidget {
  final int flow;
  final int agents;
  final String risk;
  final double zoom;
  const _StatsRow({
    required this.flow,
    required this.agents,
    required this.risk,
    required this.zoom,
  });

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
        _stat('ZOOM', '${zoom.toStringAsFixed(1)}×', const Color(0xFF66E0FF)),
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

/// 快捷按钮（UPLOAD / ARCHIVE / SUMMARY）— 玻璃 + 蓝色发光边框，语音交互
class _QuickButtons extends StatelessWidget {
  const _QuickButtons();

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        for (final label in const ['UPLOAD', 'ARCHIVE', 'SUMMARY']) ...[
          Expanded(
            child: Container(
              height: 20,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: const Color(0x2235D0FF),
                borderRadius: BorderRadius.circular(5),
                border: Border.all(
                  color: const Color(0xFF35D0FF).withValues(alpha: 0.55),
                ),
                boxShadow: [
                  BoxShadow(
                    color: const Color(0xFF35D0FF).withValues(alpha: 0.25),
                    blurRadius: 6,
                  ),
                ],
              ),
              child: Text(
                label,
                style: const TextStyle(
                  color: Color(0xFF8CC1FA),
                  fontSize: 8,
                  letterSpacing: 1.2,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ),
          if (label != 'SUMMARY') const SizedBox(width: 6),
        ],
      ],
    );
  }
}
