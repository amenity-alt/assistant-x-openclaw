import 'package:flutter/material.dart';

import '../transform_controller.dart';
import 'three_js_renderer.dart';

/// Vision HUD 中央全息核心的宿主组件（three_js 3D）。
///
/// 只负责渲染器生命周期与挂载，手势 → 变换由 [TransformController] 驱动，
/// 本组件不直接处理任何手势。
class ThreeJsHologramView extends StatefulWidget {
  const ThreeJsHologramView({super.key, required this.transform});

  final TransformController transform;

  @override
  State<ThreeJsHologramView> createState() => _ThreeJsHologramViewState();
}

class _ThreeJsHologramViewState extends State<ThreeJsHologramView> {
  ThreeJsRenderer? _renderer;

  @override
  void initState() {
    super.initState();
    _renderer = ThreeJsRenderer(
      transform: widget.transform,
      onReady: () {
        if (mounted) setState(() {});
      },
    );
    _renderer!.loadModel();
  }

  @override
  Widget build(BuildContext context) {
    final r = _renderer;
    if (r == null) return const SizedBox.shrink();
    return r.build();
  }

  @override
  void dispose() {
    _renderer?.dispose();
    _renderer = null;
    super.dispose();
  }
}
