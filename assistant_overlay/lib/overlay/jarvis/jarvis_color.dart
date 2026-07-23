import 'package:flutter/material.dart';

/// JARVIS 特效统一配色。
///
/// 将圆环（`JarvisRingsShader`）、光球（`GravitationalLightOrb`）与
/// 3D 模型（`IronManModelView`）等所有 JARVIS 视觉组件的配色集中到一处，
/// 保证整体色调一致。通过 [JarvisColor.forEffect] 按当前 effect 取色。
class JarvisColor {
  const JarvisColor({
    required this.primary,
    required this.dim,
    required this.light,
    required this.orbCore,
    required this.orbGlow,
    required this.orbAccent,
    required this.orbMist,
    required this.orbHighlight,
    required this.modelGlow,
    this.labelColor = const Color(0xFFFFFFFF),
  });

  /// 圆环主色调：外环光晕、主刻度、数据环、内环、核心等。
  final Color primary;

  /// 圆环暗色调：外环基线、次刻度、外层弧线等。
  final Color dim;

  /// 圆环高亮色调：内层弧线、chevron、核心亮点等。
  final Color light;

  /// 光球核心色。
  final Color orbCore;

  /// 光球辉光色。
  final Color orbGlow;

  /// 光球点缀色。
  final Color orbAccent;

  /// 光球雾气色。
  final Color orbMist;

  /// 3D 模型调色板中的中间高亮色（`IronManModelView.style.palette`）。
  final Color orbHighlight;

  /// 3D 模型辉光色（`IronManModelView.style.glowColor`）。
  final Color modelGlow;

  /// 圆环中央文字（J.A.R.V.I.S.）颜色。
  final Color labelColor;

  /// 稳定 UI 文字色（不随 effect 变化）。
  static const ColortextColor = Color(0xFFFFFFFF);

  /// 系统状态面板强调色（青）。
  static const ColorstatusAccent = Color(0xFF66FFFF);

  /// 系统状态面板标签色（浅青）。
  static const ColorstatusLabel = Color(0xFF8CF6FF);

  /// 按 effect 取统一配色。
  ///
  /// - default：青蓝系
  /// - success：翠绿系
  /// - error：赤红系
  static JarvisColor forEffect(String effect) {
    switch (effect) {
      case 'success':
        return const JarvisColor(
          primary: Color(0xFF00FF66),
          dim: Color(0xFF0E9C45),
          light: Color(0xFFC8FFD9),
          orbCore: Color(0xFFC8FFD9),
          orbGlow: Color(0xFF0E9C45),
          orbAccent: Color(0xFF7BE0A0),
          orbMist: Color(0xFF0A7A35),
          orbHighlight: Color(0xFF7BE0A0),
          modelGlow: Color(0xFFAAFFBB),
        );
      case 'error':
        return const JarvisColor(
          primary: Color(0xFFFF4444),
          dim: Color(0xFFB81E1E),
          light: Color(0xFFFFD4D4),
          orbCore: Color(0xFFFFD4D4),
          orbGlow: Color(0xFFB81E1E),
          orbAccent: Color(0xFFFF9A9A),
          orbMist: Color(0xFF8A1414),
          orbHighlight: Color(0xFFFF9A9A),
          modelGlow: Color(0xFFFFD4D4),
        );
      default:
        return const JarvisColor(
          primary: Color(0xFF0D67BC),
          dim: Color(0xFF0A4F91),
          light: Color(0xFFBFE7FF),
          orbCore: Color(0xFFBFE7FF),
          orbGlow: Color(0xFF0D67BC),
          orbAccent: Color(0xFF8CC1FA),
          orbMist: Color(0xFF0A4F91),
          orbHighlight: Color(0xFF6EB9FF),
          modelGlow: Color(0xFF79D9FF),
        );
    }
  }
}
