import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:three_js/three_js.dart' as three;

/// Jarvis Vision 全息核心（three_js 3D 渲染）。
///
/// Phase 1 技术验证：程序化线框全息核心，验证透明合成 / 60fps / 生命周期。
/// Phase 2 起由 HologramRenderer 接口消费 TransformState（缩放/旋转/位移），
/// 本组件只负责渲染，不直接接收手势。
class ThreeJsHologramView extends StatefulWidget {
  const ThreeJsHologramView({super.key});

  @override
  State<ThreeJsHologramView> createState() => _ThreeJsHologramViewState();
}

class _ThreeJsHologramViewState extends State<ThreeJsHologramView> {
  three.ThreeJS? _threeJs;
  three.Mesh? _core;
  three.Mesh? _inner;
  three.LineSegments? _edges;
  three.Mesh? _ringX;
  three.Mesh? _ringY;
  three.Points? _particles;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_threeJs != null) return;
    final screen = MediaQuery.of(context).size;
    // 与 Vision HUD 中央聚焦环保持同一渲染尺寸
    final s = screen.height * 0.42 * 0.8;
    _threeJs = three.ThreeJS(
      size: Size(s, s),
      onSetupComplete: () {
        if (mounted) setState(() {});
      },
      loadingWidget: const Center(
        child: SizedBox(
          width: 26,
          height: 26,
          child: CircularProgressIndicator(
            strokeWidth: 2,
            color: Color(0xFF33E0FF),
          ),
        ),
      ),
      settings: three.Settings(
        alpha: true,
        clearAlpha: 0.0,
        clearColor: 0x000000,
        antialias: true,
        animate: true,
      ),
      setup: _setup,
    );
  }

  Future<void> _setup() async {
    final t = _threeJs!;
    t.camera = three.PerspectiveCamera(50, t.width / t.height, 0.1, 100);
    t.camera.position.setValues(0, 0, 4.4);
    t.scene = three.Scene();

    // 线框核心
    _core = three.Mesh(
      three.IcosahedronGeometry(1.15, 2),
      three.MeshBasicMaterial({
        three.MaterialProperty.color: 0x2fd8ff,
        three.MaterialProperty.wireframe: true,
        three.MaterialProperty.transparent: true,
        three.MaterialProperty.opacity: 0.55,
      }),
    );
    t.scene.add(_core!);

    // 内发光体
    _inner = three.Mesh(
      three.IcosahedronGeometry(0.62, 3),
      three.MeshBasicMaterial({
        three.MaterialProperty.color: 0x0b3d52,
        three.MaterialProperty.transparent: true,
        three.MaterialProperty.opacity: 0.4,
      }),
    );
    t.scene.add(_inner!);

    // 外轮廓线
    _edges = three.LineSegments(
      three.EdgesGeometry(three.IcosahedronGeometry(1.55, 1), null),
      three.LineBasicMaterial({
        three.MaterialProperty.color: 0x7df3ff,
        three.MaterialProperty.transparent: true,
        three.MaterialProperty.opacity: 0.35,
      }),
    );
    t.scene.add(_edges!);

    // 双轨道环
    final ringMat = three.MeshBasicMaterial({
      three.MaterialProperty.color: 0x22c8ff,
      three.MaterialProperty.transparent: true,
      three.MaterialProperty.opacity: 0.5,
      three.MaterialProperty.side: three.DoubleSide,
    });
    _ringX = three.Mesh(three.TorusGeometry(2.05, 0.006, 6, 120), ringMat)
      ..rotation.x = math.pi / 2.2;
    _ringY = three.Mesh(three.TorusGeometry(2.25, 0.004, 6, 120), ringMat)
      ..rotation.z = math.pi / 2.6;
    t.scene.add(_ringX!);
    t.scene.add(_ringY!);

    // 粒子云（球壳分布）
    _particles = _buildParticles(180);
    t.scene.add(_particles!);

    // 缓慢自转（克制节奏，与地图球体一致）
    t.addAnimationEvent((dt) {
      _core?.rotation.y += dt * 0.12;
      _core?.rotation.x += dt * 0.03;
      _inner?.rotation.y -= dt * 0.18;
      _edges?.rotation.y += dt * 0.05;
      _ringX?.rotation.z += dt * 0.06;
      _ringY?.rotation.x += dt * 0.05;
      _particles?.rotation.y -= dt * 0.02;
    });
  }

  three.Points _buildParticles(int count) {
    final pos = Float32List(count * 3);
    final rnd = math.Random(7);
    for (var i = 0; i < count; i++) {
      final theta = rnd.nextDouble() * math.pi * 2;
      final phi = math.acos(2 * rnd.nextDouble() - 1);
      final r = 1.9 + rnd.nextDouble() * 1.2;
      pos[i * 3] = r * math.sin(phi) * math.cos(theta);
      pos[i * 3 + 1] = r * math.sin(phi) * math.sin(theta);
      pos[i * 3 + 2] = r * math.cos(phi);
    }
    final geo = three.BufferGeometry()
      ..setAttributeFromString(
        'position',
        three.BufferAttribute.fromUnknown(pos, 3),
      );
    return three.Points(
      geo,
      three.PointsMaterial({
        three.MaterialProperty.color: 0x8ff7ff,
        three.MaterialProperty.size: 0.03,
        three.MaterialProperty.sizeAttenuation: true,
        three.MaterialProperty.transparent: true,
        three.MaterialProperty.opacity: 0.85,
      }),
    );
  }

  @override
  Widget build(BuildContext context) {
    final t = _threeJs;
    if (t == null) return const SizedBox.shrink();
    return t.build();
  }

  @override
  void dispose() {
    final t = _threeJs;
    _threeJs = null;
    t?.dispose();
    super.dispose();
  }
}
