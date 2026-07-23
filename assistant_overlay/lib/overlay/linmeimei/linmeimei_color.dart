import 'package:flutter/material.dart';

/// 林美美特效统一配色。
///
/// 将 [LinMeimeiPet] 的主题色与终端背景色集中封装，便于统一调整与外部配置。
class LinmeimeiColor {
  const LinmeimeiColor({
    this.themeColor = const Color(0xFFFFB6C1),
    this.terminalBackground = const Color(0xFFFFE4E1),
  });

  /// 主题色（粉色描边/强调）。
  final Color themeColor;

  /// 终端面板背景色。
  final Color terminalBackground;

  /// 默认配色。
  static const LinmeimeiColor defaults = LinmeimeiColor();
}
