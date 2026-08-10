import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:three_js/three_js.dart' as three;

import '../transform_controller.dart';
import '../transform_state.dart';
import 'hologram_renderer.dart';

/// three_js（ANGLE/Metal）全息渲染器：默认 Three 渲染器。
///
/// 渲染树：scene → _root(Group，接收手势变换) → 线框核心/内发光体/外轮廓/
/// 双轨道环/粒子云（各部件保留自身微自转）。
/// 手势变换以指数阻尼逼近目标 [TransformState]，10fps 输入 → 60fps 平滑。
class ThreeJsRenderer implements HologramRenderer {
  ThreeJsRenderer({required this.transform, this.onReady});

  final TransformController transform;
  final VoidCallback? onReady;

  three.ThreeJS? _threeJs;
  three.Group? _root;
  three.Mesh? _core;
  three.Mesh? _inner;
  three.LineSegments? _edges;
  three.Mesh? _ringX;
  three.Mesh? _ringY;
  three.Points? _particles;

  // 阻尼插值当前值
  double _curScale = 1.0;
  double _curRotX = 0;
  double _curRotY = 0;
  double _curRotZ = 0;
  double _curPosX = 0;
  double _curPosY = 0;
  bool _loaded = false;

  bool get loaded => _loaded;

  @override
  Future<void> loadModel() async {
    if (_threeJs != null) return;
    final s = transform.value;
    _curScale = s.scale;
    _curRotX = s.rotX;
    _curRotY = s.rotY;
    _curRotZ = s.rotZ;
    _curPosX = s.posX;
    _curPosY = s.posY;

    _threeJs = three.ThreeJS(
      size: const Size(360, 360),
      onSetupComplete: () => onReady?.call(),
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

  Widget build() => _threeJs?.build() ?? const SizedBox.shrink();

  Future<void> _setup() async {
    final t = _threeJs!;
    t.camera = three.PerspectiveCamera(50, t.width / t.height, 0.1, 100);
    t.camera.position.setValues(0, 0, 4.4);
    t.scene = three.Scene();

    _root = three.Group();
    t.scene.add(_root!);

    _core = three.Mesh(
      three.IcosahedronGeometry(1.15, 2),
      three.MeshBasicMaterial({
        three.MaterialProperty.color: 0x2fd8ff,
        three.MaterialProperty.wireframe: true,
        three.MaterialProperty.transparent: true,
        three.MaterialProperty.opacity: 0.55,
      }),
    );
    _root!.add(_core!);

    _inner = three.Mesh(
      three.IcosahedronGeometry(0.62, 3),
      three.MeshBasicMaterial({
        three.MaterialProperty.color: 0x0b3d52,
        three.MaterialProperty.transparent: true,
        three.MaterialProperty.opacity: 0.4,
      }),
    );
    _root!.add(_inner!);

    _edges = three.LineSegments(
      three.EdgesGeometry(three.IcosahedronGeometry(1.55, 1), null),
      three.LineBasicMaterial({
        three.MaterialProperty.color: 0x7df3ff,
        three.MaterialProperty.transparent: true,
        three.MaterialProperty.opacity: 0.35,
      }),
    );
    _root!.add(_edges!);

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
    _root!.add(_ringX!);
    _root!.add(_ringY!);

    _particles = _buildParticles(180);
    _root!.add(_particles!);

    // 部件微自转 + 手势变换阻尼
    t.addAnimationEvent((dt) {
      _core?.rotation.y += dt * 0.12;
      _core?.rotation.x += dt * 0.03;
      _inner?.rotation.y -= dt * 0.18;
      _edges?.rotation.y += dt * 0.05;
      _ringX?.rotation.z += dt * 0.06;
      _ringY?.rotation.x += dt * 0.05;
      _particles?.rotation.y -= dt * 0.02;
      _dampToTarget(dt);
    });

    _loaded = true;
  }

  void _dampToTarget(double dt) {
    final target = transform.value;
    final k = 1 - math.exp(-dt / 0.12);
    _curScale += (target.scale - _curScale) * k;
    _curRotX += (target.rotX - _curRotX) * k;
    _curRotY += (target.rotY - _curRotY) * k;
    _curRotZ += (target.rotZ - _curRotZ) * k;
    _curPosX += (target.posX - _curPosX) * k;
    _curPosY += (target.posY - _curPosY) * k;

    _root?.scale.setValues(_curScale, _curScale, _curScale);
    _root?.rotation.set(_curRotX, _curRotY, _curRotZ);
    // 归一化位移 → 世界单位（相机 z=4.4，模型半径 ~1.15）
    _root?.position.setValues(_curPosX * 2.6, _curPosY * 2.6, 0);
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
  void updateTransform(TransformState state) {
    // 目标已由 transform 控制器持有，动画循环直接读取。
  }

  @override
  void removeModel() {
    final t = _threeJs;
    if (t == null || _root == null) return;
    t.scene.remove(_root!);
    for (final obj in _root!.children.toList()) {
      obj.geometry?.dispose();
      obj.material?.dispose();
    }
    _root = null;
    _core = null;
    _inner = null;
    _edges = null;
    _ringX = null;
    _ringY = null;
    _particles = null;
    _loaded = false;
  }

  @override
  void dispose() {
    removeModel();
    _threeJs?.dispose();
    _threeJs = null;
  }
}
