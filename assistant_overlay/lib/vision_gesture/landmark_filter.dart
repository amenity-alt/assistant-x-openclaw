/// 手部关键点低通滤波（EMA）。
///
/// `vision:hand` 约 10fps，坐标含抖动；用指数移动平均把噪声压下来，
/// 避免手势 delta 误触发。alpha 越大跟随越快、噪声越多。
class LandmarkFilter {
  LandmarkFilter({this.alpha = 0.45});

  final double alpha;
  List<double>? _smooth;

  List<double> filter(List<double> raw) {
    final s = _smooth;
    if (s == null || s.length != raw.length) {
      _smooth = List<double>.of(raw);
      return _smooth!;
    }
    for (var i = 0; i < raw.length; i++) {
      s[i] = s[i] + alpha * (raw[i] - s[i]);
    }
    return s;
  }

  void reset() => _smooth = null;
}
