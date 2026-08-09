import 'dart:async';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

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

/// 地图展示模式：globe=3D 地球（默认），tianditu=天地图瓦片（定位时）
enum MapMode { globe, tianditu }

/// 地图视图控制器：overlay 通过 TCP 命令驱动（缩放 / 定位 / 资讯）
class MapGlobeController extends ChangeNotifier {
  MapMode mode = MapMode.globe;
  double targetZoom = 1.0;
  double targetLat = 20.0;
  double targetLon = 105.0;
  int tiandituZoom = 10; // 天地图瓦片级别（5~16）
  String? locatedCity;
  List<MapNewsItem> news = const [];

  void zoomIn() {
    if (mode == MapMode.tianditu) {
      tiandituZoom = (tiandituZoom + 1).clamp(5, 16);
    } else {
      targetZoom = (targetZoom + 0.35).clamp(1.0, 3.0);
    }
    notifyListeners();
  }

  void zoomOut() {
    if (mode == MapMode.tianditu) {
      tiandituZoom = (tiandituZoom - 1).clamp(5, 16);
    } else {
      targetZoom = (targetZoom - 0.35).clamp(1.0, 3.0);
    }
    notifyListeners();
  }

  void reset() {
    mode = MapMode.globe;
    targetZoom = 1.0;
    targetLat = 20.0;
    targetLon = 105.0;
    tiandituZoom = 10;
    locatedCity = null;
    news = const [];
    notifyListeners();
  }

  void locateTo(double lat, double lon, String city) {
    mode = MapMode.tianditu;
    targetLat = lat;
    targetLon = lon;
    targetZoom = 2.4;
    tiandituZoom = 10;
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
    // 绘制异常兜底：绝不抛给渲染管线，避免整卡变黑或动画中断
    try {
      final c = size.center(Offset.zero);
      final R = math.min(size.width, size.height) * 0.42 * zoom;
      final proj = _OrthoProjector(radius: R, center: c, lat0: lat0, lon0: lon0);

      _paintEarth(canvas, c, R);
      _paintGrid(canvas, proj, zoom);
      _paintArcs(canvas, proj, time);
      _paintNodes(canvas, proj, time);
      _paintScanRing(canvas, c, R, time);
      _paintParticles(canvas, c, R, time);
    } catch (e) {
      debugPrint('[Globe] paint error: $e');
    }
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
      final metrics = path.computeMetrics();
      if (metrics.isEmpty) continue;
      final metric = metrics.first;
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

/// ── 天地图（Tianditu）瓦片地图 ───────────────────────────────────────
/// 定位时展示：vec_w（矢量底图）+ cva_w（矢量注记）两层 WMTS 瓦片。
const String _tdtKey = 'f6eff7213d1409c324f32588057ff535';
const int _tdtTileSize = 256;

class _Tdt {
  static double worldPx(int zoom) => _tdtTileSize * math.pow(2, zoom).toDouble();

  /// Web Mercator：经纬度 → 世界像素坐标
  static ({double x, double y}) latLonToPx(double lat, double lon, int zoom) {
    final w = worldPx(zoom);
    final latRad = lat * math.pi / 180.0;
    final x = (lon + 180.0) / 360.0 * w;
    final y =
        (1.0 - math.log(math.tan(latRad) + 1.0 / math.cos(latRad)) / math.pi) /
            2.0 *
            w;
    return (x: x, y: y);
  }

  static String url(String layer, int z, int x, int y) {
    final sub = (x + y + z) % 8; // t0~t7 轮询，避免单域名限流
    return 'https://t$sub.tianditu.gov.cn/${layer}_w/wmts'
        '?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0'
        '&LAYER=$layer&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles'
        '&TILEMATRIX=$z&TILEROW=$y&TILECOL=$x&tk=$_tdtKey';
  }
}

/// 天地图瓦片画笔：绘制底图+注记两层，居中于定位城市，保留定位标记/扫描动画
class _TileMapPainter extends CustomPainter {
  final double lat0;
  final double lon0;
  final int zoom;
  final double time; // 0..1 循环时间源（定位标记脉冲）
  final Map<String, ui.Image> tiles; // key: layer/z/x/y
  final int tilesVersion;

  _TileMapPainter({
    required this.lat0,
    required this.lon0,
    required this.zoom,
    required this.time,
    required this.tiles,
    required this.tilesVersion,
  });

  static const _cyan = Color(0xFF35D0FF);
  static const _hotColor = Color(0xFFFFB347);

  @override
  void paint(Canvas canvas, Size size) {
    try {
      final c = size.center(Offset.zero);
      final center = _Tdt.latLonToPx(lat0, lon0, zoom);
      final halfW = size.width / 2;
      final halfH = size.height / 2;

      // 暗色底（瓦片未加载前也有底）
      canvas.drawRect(
        Offset.zero & size,
        Paint()..color = const Color(0xFF0A1B33),
      );

      final x0 = ((center.x - halfW) / _tdtTileSize).floor();
      final x1 = ((center.x + halfW) / _tdtTileSize).floor();
      final y0 = ((center.y - halfH) / _tdtTileSize).floor();
      final y1 = ((center.y + halfH) / _tdtTileSize).floor();
      final maxTile = (math.pow(2, zoom).toDouble() - 1).toInt();

      for (var ty = y0; ty <= y1; ty++) {
        if (ty < 0 || ty > maxTile) continue;
        for (var tx = x0; tx <= x1; tx++) {
          if (tx < 0 || tx > maxTile) continue;
          final dx = tx * _tdtTileSize - center.x + halfW;
          final dy = ty * _tdtTileSize - center.y + halfH;
          final rect = Rect.fromLTWH(dx, dy, _tdtTileSize + 1, _tdtTileSize + 1);
          // 底图层
          final base = tiles['vec/$zoom/$tx/$ty'];
          if (base != null) {
            canvas.drawImageRect(
                base, Rect.fromLTWH(0, 0, base.width.toDouble(), base.height.toDouble()), rect, Paint());
          } else {
            _placeholder(canvas, rect, tx, ty);
          }
          // 注记层（城市/道路名）
          final ann = tiles['cva/$zoom/$tx/$ty'];
          if (ann != null) {
            canvas.drawImageRect(
                ann, Rect.fromLTWH(0, 0, ann.width.toDouble(), ann.height.toDouble()), rect, Paint());
          }
        }
      }

      // 定位城市标记：橙色脉冲环 + 光点（居中）
      final pulse = 0.5 + 0.5 * math.sin(time * 2 * math.pi * 2);
      _glowDot(canvas, c, 5.0 + pulse * 3.0, _hotColor, 1.0);
      canvas.drawCircle(
        c,
        7.0 + pulse * 5.0,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.4
          ..color = _hotColor.withValues(alpha: 0.85)
          ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 2),
      );
      canvas.drawCircle(
        c,
        14.0 + pulse * 6.0,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 0.8
          ..color = _hotColor.withValues(alpha: 0.4),
      );

      // 外框扫描环
      canvas.drawCircle(
        c,
        math.min(size.width, size.height) * 0.48,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.2
          ..color = _cyan.withValues(alpha: 0.30),
      );
      final a = time * 2 * math.pi;
      final ringR = math.min(size.width, size.height) * 0.48;
      canvas.drawArc(
        Rect.fromCircle(center: c, radius: ringR),
        a,
        0.9,
        false,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2.2
          ..strokeCap = StrokeCap.round
          ..color = _cyan.withValues(alpha: 0.75)
          ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 3),
      );
      final tip =
          Offset(c.dx + ringR * math.cos(a), c.dy + ringR * math.sin(a));
      _glowDot(canvas, tip, 4.0, _cyan, 0.9);

      // 左上角标注
      final label = 'TIANDITU · Z$zoom';
      final tp = TextPainter(
        text: TextSpan(
          text: label,
          style: TextStyle(
            color: _cyan.withValues(alpha: 0.7),
            fontSize: 7,
            letterSpacing: 1.2,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, const Offset(6, 4));
    } catch (e) {
      debugPrint('[TDT] paint error: $e');
    }
  }

  void _placeholder(Canvas canvas, Rect rect, int tx, int ty) {
    canvas.drawRect(rect, Paint()..color = const Color(0xFF0E2340));
    canvas.drawRect(
      rect.deflate(0.5),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 0.6
        ..color = const Color(0xFF2F8CFF).withValues(alpha: 0.18),
    );
    final center = rect.center;
    canvas.drawLine(
      Offset(rect.left, center.dy),
      Offset(rect.right, center.dy),
      Paint()
        ..strokeWidth = 0.5
        ..color = const Color(0xFF2F8CFF).withValues(alpha: 0.12),
    );
    // 极简坐标标注，便于调试
    final tp = TextPainter(
      text: TextSpan(
        text: '$tx,$ty',
        style: TextStyle(
          color: const Color(0xFF5F87B8).withValues(alpha: 0.5),
          fontSize: 6,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(canvas, center + const Offset(2, 2));
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

  @override
  bool shouldRepaint(covariant _TileMapPainter old) =>
      old.lat0 != lat0 ||
      old.lon0 != lon0 ||
      old.zoom != zoom ||
      old.time != time ||
      old.tilesVersion != tilesVersion ||
      old.tiles != tiles;
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

  // 视图状态机（飞行动画）：begin=动画起点，target=目标。
  // 画笔参数在 AnimatedBuilder 的 builder 内每帧按 _viewCurve.value 计算，
  // 而不是在 build() 里算好再传进闭包（否则动画期间画笔始终用旧值，表现为"卡住"）。
  double _beginZoom = 1.0;
  double _beginLat = 20.0;
  double _beginLon = 105.0;
  double _targetZoom = 1.0;
  double _targetLat = 20.0;
  double _targetLon = 105.0;

  int _flow = 9;
  int _agents = 6;
  String _risk = 'LOW';

  // 天地图瓦片缓存（LRU）+ 加载中集合 + 版本号（驱动重绘）
  final HttpClient _http = HttpClient();
  final Map<String, ui.Image> _tiles = {};
  final List<String> _tileOrder = [];
  final Set<String> _loadingTiles = {};
  int _tilesVersion = 0;
  bool _tileDirty = true;
  Size _lastTileArea = Size.zero;
  static const int _maxTiles = 96;

  static double _lerp(double a, double b, double t) => a + (b - a) * t;

  @override
  void initState() {
    super.initState();
    _controller = widget.controller;
    _targetZoom = _controller.targetZoom;
    _targetLat = _controller.targetLat;
    _targetLon = _controller.targetLon;
    _anim = AnimationController(vsync: this, duration: const Duration(seconds: 10))
      ..repeat();
    _view = AnimationController(
        vsync: this, duration: const Duration(milliseconds: 800));
    _viewCurve = CurvedAnimation(parent: _view, curve: Curves.easeInOutCubic);
    _controller.addListener(_onViewChanged);
    _startStatsTimer();
  }

  void _onViewChanged() {
    if (!mounted) return;
    try {
      // 命令到达瞬间的当前显示值 = 下一段动画的起点（动画中也能平滑改道）
      final t = _viewCurve.value;
      final z = _lerp(_beginZoom, _targetZoom, t);
      final la = _lerp(_beginLat, _targetLat, t);
      final lo = _lerp(_beginLon, _targetLon, t);
      final tz = _controller.targetZoom;
      final tla = _controller.targetLat;
      final tlo = _controller.targetLon;
      final moved = tz != _targetZoom || tla != _targetLat || tlo != _targetLon;
      setState(() {
        _beginZoom = z;
        _beginLat = la;
        _beginLon = lo;
        _targetZoom = tz;
        _targetLat = tla;
        _targetLon = tlo;
      });
      // 仅视图变化（定位/缩放/重置）才重启飞行；map_news 只刷新资讯面板不动地图
      if (moved) {
        _view.forward(from: 0);
      }
      // 天地图模式：中心/级别变化后重新拉取可见瓦片
      if (_controller.mode == MapMode.tianditu) {
        _tileDirty = true;
      }
    } catch (e) {
      debugPrint('[Globe] view change error: $e');
    }
  }

  /// 天地图：计算当前中心/级别下可见瓦片并异步加载（缓存+LRU）
  void _refreshTiles(Size area) {
    if (_controller.mode != MapMode.tianditu) return;
    _tileDirty = false;
    final z = _controller.tiandituZoom;
    final center =
        _Tdt.latLonToPx(_controller.targetLat, _controller.targetLon, z);
    final halfW = area.width / 2 + _tdtTileSize;
    final halfH = area.height / 2 + _tdtTileSize;
    final x0 = ((center.x - halfW) / _tdtTileSize).floor();
    final x1 = ((center.x + halfW) / _tdtTileSize).floor();
    final y0 = ((center.y - halfH) / _tdtTileSize).floor();
    final y1 = ((center.y + halfH) / _tdtTileSize).floor();
    final maxTile = (math.pow(2, z).toDouble() - 1).toInt();
    for (var ty = y0; ty <= y1; ty++) {
      if (ty < 0 || ty > maxTile) continue;
      for (var tx = x0; tx <= x1; tx++) {
        if (tx < 0 || tx > maxTile) continue;
        for (final layer in const ['vec', 'cva']) {
          final key = '$layer/$z/$tx/$ty';
          if (!_tiles.containsKey(key) && !_loadingTiles.contains(key)) {
            _loadTile(layer, z, tx, ty);
          }
        }
      }
    }
  }

  Future<void> _loadTile(String layer, int z, int x, int y) async {
    final key = '$layer/$z/$x/$y';
    _loadingTiles.add(key);
    try {
      final req = await _http.getUrl(Uri.parse(_Tdt.url(layer, z, x, y)));
      final res = await req.close();
      if (res.statusCode != 200) throw Exception('HTTP ${res.statusCode}');
      final builder = BytesBuilder();
      await for (final chunk in res) {
        builder.add(chunk);
      }
      final codec = await ui.instantiateImageCodec(builder.takeBytes());
      final frame = await codec.getNextFrame();
      if (!mounted) {
        frame.image.dispose();
        return;
      }
      setState(() {
        final old = _tiles[key];
        if (old != null) {
          old.dispose();
          _tileOrder.remove(key);
        }
        _tiles[key] = frame.image;
        _tileOrder.add(key);
        _tilesVersion++;
        _trimTiles();
      });
    } catch (e) {
      debugPrint('[TDT] tile load error $key: $e');
    } finally {
      _loadingTiles.remove(key);
    }
  }

  void _trimTiles() {
    while (_tileOrder.length > _maxTiles) {
      final k = _tileOrder.removeAt(0);
      _tiles.remove(k)?.dispose();
      _tilesVersion++;
    }
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
    _http.close(force: true);
    for (final img in _tiles.values) {
      img.dispose();
    }
    _tiles.clear();
    _view.dispose();
    _viewCurve.dispose();
    _anim.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // 供底部 ZOOM 读数使用的当前值（随卡片级 setState 更新即可）
    final t = _viewCurve.value;
    final zoom = _lerp(_beginZoom, _targetZoom, t);
    final zoomLabel = _controller.mode == MapMode.tianditu
        ? 'Z${_controller.tiandituZoom}'
        : '${zoom.toStringAsFixed(1)}×';

    return HudTerminalShell(
      title: 'GLOBAL SATCOM',
      width: widget.width,
      maxHeight: widget.height,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(16),
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
                      flex: 54,
                      // 硬裁剪：地球绘制（辉光/扫描环/粒子/放大）严格限制在
                      // 地图区域内，绝不溢出到资讯栏或卡片外。
                      child: ClipRect(
                        child: AnimatedBuilder(
                          animation: Listenable.merge([_anim, _view]),
                          builder: (context, child) {
                            // 定位 → 天地图瓦片；未定位 → 3D 地球
                            if (_controller.mode == MapMode.tianditu) {
                              return LayoutBuilder(
                                builder: (context, cons) {
                                  if (_tileDirty ||
                                      cons.biggest != _lastTileArea) {
                                    _lastTileArea = cons.biggest;
                                    _refreshTiles(cons.biggest);
                                  }
                                  return CustomPaint(
                                    painter: _TileMapPainter(
                                      lat0: _controller.targetLat,
                                      lon0: _controller.targetLon,
                                      zoom: _controller.tiandituZoom,
                                      time: _anim.value,
                                      tiles: _tiles,
                                      tilesVersion: _tilesVersion,
                                    ),
                                    size: Size.infinite,
                                  );
                                },
                              );
                            }
                            // 画笔参数在每帧 tick 内计算，飞行动画才真正动起来
                            final vt = _viewCurve.value;
                            return CustomPaint(
                              painter: _GlobePainter(
                                time: _anim.value,
                                zoom: _lerp(_beginZoom, _targetZoom, vt),
                                lat0: _lerp(_beginLat, _targetLat, vt),
                                lon0: _lerp(_beginLon, _targetLon, vt),
                              ),
                              size: Size.infinite,
                            );
                          },
                        ),
                      ),
                    ),
                    const SizedBox(width: 10),
                    // 资讯面板与球体并行（同高右侧栏），比之前更大
                    Expanded(
                      flex: 46,
                      child: _NewsPanel(
                        controller: _controller,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 6),
              const _MemoryLogStrip(),
              const SizedBox(height: 6),
              _StatsRow(
                flow: _flow,
                agents: _agents,
                risk: _risk,
                zoom: zoom,
                zoomLabel: zoomLabel,
              ),
              const SizedBox(height: 6),
              const _QuickButtons(),
            ],
          ),
        ),
      ),
    );
  }
}

/// Memory Log（记忆中心）— 卡片底部紧凑横条（2×2 状态点 + 记录 + 时间）
class _MemoryLogStrip extends StatelessWidget {
  const _MemoryLogStrip();

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    String hm(int s) {
      final t = DateTime.fromMillisecondsSinceEpoch(
          now.millisecondsSinceEpoch - s * 1000);
      return '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
    }

    const entries = [
      ('User Analysis Completed', Color(0xFF3DFF8A), 12, true),
      ('Knowledge Graph Updated', Color(0xFF3DFF8A), 48, true),
      ('SQL Optimization Finished', Color(0xFF35D0FF), 126, true),
      ('Agent Task Running', Color(0xFFFFB347), 2, false),
    ];

    Widget cell(int idx) {
      final (label, color, secs, done) = entries[idx];
      return Row(
        children: [
          Container(
            width: 5,
            height: 5,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: color,
              boxShadow: [
                BoxShadow(color: color.withValues(alpha: 0.7), blurRadius: 3),
              ],
            ),
          ),
          const SizedBox(width: 4),
          Expanded(
            child: Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: const Color(0xFFB7D8F5).withValues(alpha: 0.95),
                fontSize: 7.5,
                letterSpacing: 0.2,
              ),
            ),
          ),
          const SizedBox(width: 4),
          Text(
            done ? '✓' : '◐',
            style: TextStyle(
              color: color,
              fontSize: 8,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(width: 3),
          Text(
            hm(secs),
            style: TextStyle(
              color: const Color(0xFF5F87B8),
              fontSize: 7,
            ),
          ),
        ],
      );
    }

    return Container(
      decoration: BoxDecoration(
        color: const Color(0x140D67BC),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
            color: const Color(0xFF35D0FF).withValues(alpha: 0.22)),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      child: Column(
        children: [
          Row(
            children: [
              const _MiniHeader('MEMORY LOG'),
              const SizedBox(width: 10),
              Expanded(child: cell(0)),
              const SizedBox(width: 10),
              Expanded(child: cell(1)),
            ],
          ),
          const SizedBox(height: 3),
          Row(
            children: [
              Expanded(child: cell(2)),
              const SizedBox(width: 10),
              Expanded(child: cell(3)),
            ],
          ),
        ],
      ),
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
      padding: const EdgeInsets.all(10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _MiniHeader(city == null ? 'HOT SIGNAL' : '📍 $city 热点'),
          const SizedBox(height: 6),
          Expanded(
            child: items.isEmpty
                ? Center(
                    child: Text(
                      city == null ? '未定位 · 说"定位到城市"' : '获取最新资讯中...',
                      style: TextStyle(
                        color: const Color(0xFF5F87B8).withValues(alpha: 0.9),
                        fontSize: 9,
                      ),
                    ),
                  )
                : ListView.builder(
                    padding: EdgeInsets.zero,
                    itemCount: items.length,
                    itemBuilder: (context, i) {
                      final it = items[i];
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 6),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '${i + 1}',
                              style: TextStyle(
                                color: const Color(0xFFFFB347),
                                fontSize: 9,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            const SizedBox(width: 5),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    it.title,
                                    maxLines: 3,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(
                                      color: Color(0xFFDCEEFF),
                                      fontSize: 10,
                                      height: 1.3,
                                    ),
                                  ),
                                  if (it.source.isNotEmpty || it.time.isNotEmpty)
                                    Text(
                                      [it.source, it.time]
                                          .where((s) => s.isNotEmpty)
                                          .join(' · '),
                                      style: TextStyle(
                                        color: const Color(0xFF5F87B8),
                                        fontSize: 8,
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
  final String zoomLabel;
  const _StatsRow({
    required this.flow,
    required this.agents,
    required this.risk,
    required this.zoom,
    required this.zoomLabel,
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
        _stat('ZOOM', zoomLabel, const Color(0xFF66E0FF)),
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
