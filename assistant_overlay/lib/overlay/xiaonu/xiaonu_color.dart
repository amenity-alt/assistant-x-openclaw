import 'package:flutter/material.dart';

/// 小努特效统一配色。
///
/// 将 [Xiaonupet] 的主题色与终端背景色集中封装，便于统一调整与外部配置。
/// 贴合黑白猫形象：暖奶白底 + 炭灰描边。
class XiaonuColor {
  const XiaonuColor({
    this.themeColor = const Color(0xFF3A3A3A),
    this.terminalBackground = const Color(0xFFFFF6E9),
  });

  /// 主题色（炭灰描边/强调）。
  final Color themeColor;

  /// 终端面板背景色（暖奶白）。
  final Color terminalBackground;

  /// 默认配色。
  static const XiaonuColor defaults = XiaonuColor();
}
