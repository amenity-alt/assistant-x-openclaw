import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../jarvis_color.dart';

class JarvisRingsShader extends StatefulWidget {
  const JarvisRingsShader({
    super.key,
    required this.outerRingRotation,
    required this.arcsRotation,
    required this.dataRingRotation,
    required this.innerRingRotation,
    required this.pulseValue,
    required this.currentEffect,
    this.speakingScale = 0,
    this.showLabel = true,
    this.palette,
    this.lineWidthScale,
  });

  final double outerRingRotation;
  final double arcsRotation;
  final double dataRingRotation;
  final double innerRingRotation;
  final double pulseValue;
  final String currentEffect;
  final double speakingScale;
  final bool showLabel;

  /// 整体配色（含圆环三色、线条粗细），为 null 时按 [currentEffect]
  /// 使用 [JarvisColor.forEffect] 的内置配色，与光球等同源。
  final JarvisColor? palette;

  /// 圆环线条粗细缩放系数，1.0 为原始粗细。
  /// 为 null 时回退到 [JarvisColor.ringLineWidthScale]（默认 2.0，翻倍）。
  final double? lineWidthScale;

  @override
  State<JarvisRingsShader> createState() => _JarvisRingsShaderState();
}

class _JarvisRingsShaderState extends State<JarvisRingsShader> {
  static const _shaderAsset = 'shaders/jarvis_rings.frag';

  ui.FragmentProgram? _program;

  @override
  void initState() {
    super.initState();
    _loadShader();
  }

  Future<void> _loadShader() async {
    try {
      final program = await ui.FragmentProgram.fromAsset(_shaderAsset);
      if (!mounted) return;
      setState(() => _program = program);
    } catch (error, stackTrace) {
      debugPrint('Failed to load JARVIS rings shader: $error');
      debugPrintStack(stackTrace: stackTrace);
    }
  }

  @override
  Widget build(BuildContext context) {
    final program = _program;
    if (program == null || _effectOpacity(widget.currentEffect) == 0) {
      return const SizedBox.expand();
    }

    final palette =
        widget.palette ?? JarvisColor.forEffect(widget.currentEffect);
    final lineWidthScale =
        widget.lineWidthScale ?? 1.0;
    return RepaintBoundary(
      child: Stack(
        fit: StackFit.expand,
        children: [
          CustomPaint(
            painter: _JarvisRingsShaderPainter(
              program: program,
              outerRingRotation: widget.outerRingRotation,
              arcsRotation: widget.arcsRotation,
              dataRingRotation: widget.dataRingRotation,
              innerRingRotation: widget.innerRingRotation,
              pulseValue: widget.pulseValue,
              speakingScale: widget.speakingScale,
              lineWidthScale: lineWidthScale,
              primaryColor: palette.primary,
              dimColor: palette.dim,
              lightColor: palette.light,
            ),
          ),
          if (widget.showLabel)
            Center(
              child: Text(
                'J.A.R.V.I.S.',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: palette.labelColor,
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 2,
                  shadows: [
                    Shadow(color: palette.primary, blurRadius: 10),
                    Shadow(
                      color: palette.primary.withAlpha(150),
                      blurRadius: 20,
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }

  static double _effectOpacity(String currentEffect) {
    if (currentEffect == 'hide' || currentEffect == 'idle') return 0;
    return 1;
  }
}

class _JarvisRingsShaderPainter extends CustomPainter {
  const _JarvisRingsShaderPainter({
    required this.program,
    required this.outerRingRotation,
    required this.arcsRotation,
    required this.dataRingRotation,
    required this.innerRingRotation,
    required this.pulseValue,
    required this.speakingScale,
    required this.lineWidthScale,
    required this.primaryColor,
    required this.dimColor,
    required this.lightColor,
  });

  final ui.FragmentProgram program;
  final double outerRingRotation;
  final double arcsRotation;
  final double dataRingRotation;
  final double innerRingRotation;
  final double pulseValue;
  final double speakingScale;
  final double lineWidthScale;
  final Color primaryColor;
  final Color dimColor;
  final Color lightColor;

  static void _setColor(ui.FragmentShader shader, int index, Color color) {
    shader
      ..setFloat(index, color.r)
      ..setFloat(index + 1, color.g)
      ..setFloat(index + 2, color.b);
  }

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty) return;
    final shader = program.fragmentShader()
      ..setFloat(0, size.width)
      ..setFloat(1, size.height)
      ..setFloat(2, outerRingRotation % (math.pi * 2))
      ..setFloat(3, arcsRotation % (math.pi * 2))
      ..setFloat(4, dataRingRotation % (math.pi * 2))
      ..setFloat(5, innerRingRotation % (math.pi * 2))
      ..setFloat(6, pulseValue.clamp(0.0, 1.0))
      ..setFloat(7, speakingScale.clamp(0.0, 1.0));
    _setColor(shader, 8, primaryColor);
    _setColor(shader, 11, dimColor);
    _setColor(shader, 14, lightColor);
    shader.setFloat(17, lineWidthScale);

    canvas.drawRect(Offset.zero & size, Paint()..shader = shader);
  }

  @override
  bool shouldRepaint(covariant _JarvisRingsShaderPainter oldDelegate) {
    return oldDelegate.program != program ||
        oldDelegate.outerRingRotation != outerRingRotation ||
        oldDelegate.arcsRotation != arcsRotation ||
        oldDelegate.dataRingRotation != dataRingRotation ||
        oldDelegate.innerRingRotation != innerRingRotation ||
        oldDelegate.pulseValue != pulseValue ||
        oldDelegate.speakingScale != speakingScale ||
        oldDelegate.lineWidthScale != lineWidthScale ||
        oldDelegate.primaryColor != primaryColor ||
        oldDelegate.dimColor != dimColor ||
        oldDelegate.lightColor != lightColor;
  }
}
