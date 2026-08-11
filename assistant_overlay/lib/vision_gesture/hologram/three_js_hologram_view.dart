import 'dart:math' as math;

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

import '../transform_controller.dart';
import 'three_js_renderer.dart';

/// Vision HUD 中央全息核心的宿主组件（three_js 3D）。
///
/// 只负责渲染器生命周期、尺寸与鼠标/触控板回退交互；
/// 手势 → 变换由 [TransformController] 驱动，本组件不直接处理手部手势。
///
/// 回退交互（手部跟踪不可用时仍可操作 3D 空间）：
///   - 左键拖动    → 模型旋转（GRAB 语义）
///   - 滚轮 / 双指 → 缩放（对应捏合）
///   - 触控板双指旋转 → 模型旋转
///   - 双击        → 复位（回到默认姿态）
class ThreeJsHologramView extends StatefulWidget {
  const ThreeJsHologramView({
    super.key,
    required this.transform,
    this.active = true,
    this.size = const Size(360, 360),
    this.glbPath,
  });

  final TransformController transform;

  /// 视觉会话是否激活：激活时创建/恢复渲染，非激活时停帧并保持渲染器常驻。
  final bool active;

  /// 宿主区域尺寸（自适应渲染器画布）。
  final Size size;

  /// 可选 GLB/GLTF 模型路径；失败自动回退程序化全息地球。
  final String? glbPath;

  @override
  State<ThreeJsHologramView> createState() => _ThreeJsHologramViewState();
}

class _ThreeJsHologramViewState extends State<ThreeJsHologramView> {
  ThreeJsRenderer? _renderer;

  // 鼠标拖动
  Offset? _dragLast;
  // 触控板双指（panZoom 事件为累积值，保存上一次读数算增量）
  bool _panZoomActive = false;
  double _pzLastScale = 1.0;
  double _pzLastRotation = 0.0;

  @override
  void initState() {
    super.initState();
    _renderer = ThreeJsRenderer(
      transform: widget.transform,
      size: widget.size,
      glbPath: widget.glbPath,
      onReady: () {
        if (mounted) setState(() {});
      },
    );
    // 延迟到首次激活才初始化 GPU 资源（应用启动时不预加载）
    if (widget.active) _renderer!.loadModel();
  }

  @override
  void didUpdateWidget(covariant ThreeJsHologramView oldWidget) {
    super.didUpdateWidget(oldWidget);
    final r = _renderer;
    if (r == null) return;
    if (widget.active && !r.loaded) {
      r.loadModel();
    } else if (oldWidget.active != widget.active) {
      r.setActive(widget.active);
    }
  }

  // ── 鼠标回退交互 ────────────────────────────────────
  void _onPointerDown(PointerDownEvent e) {
    if (e.buttons & kPrimaryMouseButton != 0) {
      _dragLast = e.position;
    }
  }

  void _onPointerMove(PointerMoveEvent e) {
    final last = _dragLast;
    if (last == null || e.buttons & kPrimaryMouseButton == 0) return;
    final dx = e.position.dx - last.dx;
    final dy = e.position.dy - last.dy;
    final w = widget.size.width;
    final sens = (math.pi * 1.5) / (w <= 0 ? 360 : w);
    widget.transform.apply(
      dRotY: -dx * sens,
      dRotX: dy * sens,
    );
    _dragLast = e.position;
  }

  void _onPointerUp(PointerUpEvent e) => _dragLast = null;
  void _onPointerCancel(PointerCancelEvent e) => _dragLast = null;

  void _onPanZoomStart(PointerPanZoomStartEvent e) {
    _panZoomActive = true;
    _pzLastScale = 1.0;
    _pzLastRotation = 0.0;
  }

  void _onPanZoomUpdate(PointerPanZoomUpdateEvent e) {
    if (!_panZoomActive) return;
    final dScale = e.scale / _pzLastScale;
    final dRot = e.rotation - _pzLastRotation;
    _pzLastScale = e.scale;
    _pzLastRotation = e.rotation;
    widget.transform.apply(
      dScale: dScale.clamp(0.9, 1.12),
      dRotY: dRot * 1.6,
    );
  }

  void _onPanZoomEnd(PointerPanZoomEndEvent e) {
    _panZoomActive = false;
  }

  void _onPointerSignal(PointerSignalEvent e) {
    if (e is PointerScrollEvent) {
      final factor = (1 - e.scrollDelta.dy * 0.002).clamp(0.85, 1.18);
      widget.transform.apply(dScale: factor);
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = _renderer;
    if (r == null) return const SizedBox.shrink();
    return Listener(
      behavior: HitTestBehavior.opaque,
      onPointerDown: _onPointerDown,
      onPointerMove: _onPointerMove,
      onPointerUp: _onPointerUp,
      onPointerCancel: _onPointerCancel,
      onPointerPanZoomStart: _onPanZoomStart,
      onPointerPanZoomUpdate: _onPanZoomUpdate,
      onPointerPanZoomEnd: _onPanZoomEnd,
      onPointerSignal: _onPointerSignal,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onDoubleTap: () => widget.transform.reset(),
        child: r.build(),
      ),
    );
  }

  @override
  void dispose() {
    _renderer?.dispose();
    _renderer = null;
    super.dispose();
  }
}
