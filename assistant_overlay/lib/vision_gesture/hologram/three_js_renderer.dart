import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:three_js/three_js.dart' as three;
import 'package:three_js_advanced_loaders/three_js_advanced_loaders.dart'
    as loaders;

import '../transform_controller.dart';
import '../transform_state.dart';
import 'hologram_renderer.dart';

/// three_js（ANGLE/Metal）全息渲染器：默认 Three 渲染器。
///
/// 渲染树：scene → _root(Group，接收手势变换) → 线框核心/内发光体/外轮廓/
/// 双轨道环/粒子云（各部件保留自身微自转）。
/// 手势变换以指数阻尼逼近目标 [TransformState]，10fps 输入 → 60fps 平滑。
class ThreeJsRenderer implements HologramRenderer {
  ThreeJsRenderer({
    required this.transform,
    this.onReady,
    this.size = const Size(360, 360),
    this.glbPath,
  });

  final TransformController transform;
  final VoidCallback? onReady;

  /// 宿主区域尺寸（自适应：不再写死 360×360）。
  final Size size;

  /// 可选 GLB/GLTF 模型路径（earth.glb / robot.glb / object.glb）。
  /// 加载失败或为空时回退程序化全息地球（软失败）。
  final String? glbPath;

  three.ThreeJS? _threeJs;
  three.Group? _root;
  three.Group? _earth;
  three.Mesh? _core;
  three.Mesh? _inner;
  three.LineSegments? _latGrid;
  three.Points? _cityNodes;
  three.Mesh? _ringX;
  three.Mesh? _ringY;
  three.Points? _particles;
  three.Mesh? _glow;
  three.Mesh? _scanSweep;
  three.Mesh? _scanSlice;
  three.LineSegments? _grid;
  three.Object3D? _gltfRoot;
  double _sweepPhase = 0;
  double _viewScale = 1.0;

  // 阻尼插值当前值
  double _curScale = 1.0;
  double _curRotX = 0;
  double _curRotY = 0;
  double _curRotZ = 0;
  double _curPosX = 0;
  double _curPosY = 0;
  bool _loaded = false;

  bool get loaded => _loaded;

  /// 视觉会话开关：非激活时停帧（不渲染、释放 GPU 忙碌），渲染器保持常驻。
  void setActive(bool active) {
    final t = _threeJs;
    if (t == null) return;
    t.visible = active;
    if (active && !_loaded) {
      loadModel();
    }
  }

  @override
  Future<void> loadModel() async {
    if (_threeJs != null) return;
    final s = transform.value;
    _viewScale = (size.shortestSide / 360).clamp(0.9, 4.0);
    _curScale = s.scale;
    _curRotX = s.rotX;
    _curRotY = s.rotY;
    _curRotZ = s.rotZ;
    _curPosX = s.posX;
    _curPosY = s.posY;

    _threeJs = three.ThreeJS(
      size: size,
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
    t.camera.position.setValues(0, 0, 4.4 * _viewScale);
    t.scene = three.Scene();

    _root = three.Group();
    t.scene.add(_root!);

    // 全息地球组（程序化：线框球壳 + 深蓝内芯 + 经纬网格 + 城市节点；
    // 受手势变换整体控制；GLB 加载成功时整组隐藏）
    _earth = three.Group();
    _root!.add(_earth!);

    _core = three.Mesh(
      three.SphereGeometry(1.12, 24, 16),
      three.MeshBasicMaterial({
        three.MaterialProperty.color: 0x2fd8ff,
        three.MaterialProperty.wireframe: true,
        three.MaterialProperty.transparent: true,
        three.MaterialProperty.opacity: 0.5,
      }),
    );
    _earth!.add(_core!);

    _inner = three.Mesh(
      three.SphereGeometry(0.72, 16, 12),
      three.MeshBasicMaterial({
        three.MaterialProperty.color: 0x0b3d52,
        three.MaterialProperty.transparent: true,
        three.MaterialProperty.opacity: 0.45,
      }),
    );
    _earth!.add(_inner!);

    // 经纬网格线（球面经线 + 纬线）
    _latGrid = three.LineSegments(
      _buildLatLongGrid(1.125, 12),
      three.LineBasicMaterial({
        three.MaterialProperty.color: 0x7df3ff,
        three.MaterialProperty.transparent: true,
        three.MaterialProperty.opacity: 0.35,
      }),
    );
    _earth!.add(_latGrid!);

    // 城市节点（球面发光点）
    _cityNodes = _buildCityNodes(120, 1.13);
    _earth!.add(_cityNodes!);

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

    _particles = _buildParticles(200);
    _root!.add(_particles!);

    // 发光外壳（加色混合伪造辉光）
    _glow = three.Mesh(
      three.IcosahedronGeometry(1.55, 2),
      three.MeshBasicMaterial({
        three.MaterialProperty.color: 0x29c8ff,
        three.MaterialProperty.wireframe: true,
        three.MaterialProperty.transparent: true,
        three.MaterialProperty.opacity: 0.16,
        three.MaterialProperty.blending: three.AdditiveBlending,
        three.MaterialProperty.depthWrite: false,
      }),
    );
    _root!.add(_glow!);

    // 水平扫描环：沿模型上下往返扫描
    _scanSweep = three.Mesh(
      three.RingGeometry(1.38, 1.46, 96),
      three.MeshBasicMaterial({
        three.MaterialProperty.color: 0x37e6ff,
        three.MaterialProperty.transparent: true,
        three.MaterialProperty.opacity: 0.45,
        three.MaterialProperty.blending: three.AdditiveBlending,
        three.MaterialProperty.depthWrite: false,
        three.MaterialProperty.side: three.DoubleSide,
      }),
    )..rotation.x = math.pi / 2;
    _root!.add(_scanSweep!);

    // 垂直扫描切片：绕 Y 慢速旋转
    _scanSlice = three.Mesh(
      three.RingGeometry(0, 1.7, 96),
      three.MeshBasicMaterial({
        three.MaterialProperty.color: 0x33e0ff,
        three.MaterialProperty.transparent: true,
        three.MaterialProperty.opacity: 0.05,
        three.MaterialProperty.blending: three.AdditiveBlending,
        three.MaterialProperty.depthWrite: false,
        three.MaterialProperty.side: three.DoubleSide,
      }),
    );
    _root!.add(_scanSlice!);

    // 全息网格底座（固定在场景中，不随模型缩放）
    _grid = three.LineSegments(
      _buildGridGeometry(12, 3.0 * _viewScale),
      three.LineBasicMaterial({
        three.MaterialProperty.color: 0x1a9ec9,
        three.MaterialProperty.transparent: true,
        three.MaterialProperty.opacity: 0.35,
      }),
    )..position.y = -1.75 * _viewScale;
    t.scene.add(_grid!);

    // 全息地球缓慢自转（空闲也缓缓转动）+ 部件微自转 + 扫描动画 + 手势变换阻尼
    t.addAnimationEvent((dt) {
      _earth?.rotation.y += dt * 0.08;
      _earth?.rotation.x += dt * 0.012;
      _ringX?.rotation.z += dt * 0.06;
      _ringY?.rotation.x += dt * 0.05;
      _particles?.rotation.y -= dt * 0.02;
      _sweepPhase += dt * 1.1;
      _scanSweep?.position.y = math.sin(_sweepPhase) * 1.3 * _viewScale;
      _scanSlice?.rotation.y += dt * 0.35;
      _dampToTarget(dt);
    });

    _loaded = true;
    _tryLoadGlb();
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

    _root?.scale.setValues(
      _curScale * _viewScale,
      _curScale * _viewScale,
      _curScale * _viewScale,
    );
    _root?.rotation.set(_curRotX, _curRotY, _curRotZ);
    // 归一化位移 → 世界单位（相机距离随 _viewScale 自适应）
    _root?.position.setValues(
      _curPosX * 2.6 * _viewScale,
      _curPosY * 2.6 * _viewScale,
      0,
    );
  }

  /// 球面经纬网格（经线 + 纬线弧段）。
  three.BufferGeometry _buildLatLongGrid(double r, int steps) {
    final pts = <double>[];
    // 经线：每 15° 一条，从北极到南极
    for (var lon = 0; lon < 360; lon += 15) {
      final a = lon * math.pi / 180;
      for (var i = 0; i <= steps; i++) {
        final theta = i * math.pi / steps;
        pts.addAll([
          r * math.sin(theta) * math.cos(a),
          r * math.cos(theta),
          r * math.sin(theta) * math.sin(a),
        ]);
      }
    }
    // 纬线：每 15° 一条（赤道上下）
    for (var lat = -75; lat <= 75; lat += 15) {
      final theta = lat * math.pi / 180;
      final rr = r * math.cos(theta);
      final y = r * math.sin(theta);
      const n = 48;
      for (var i = 0; i <= n; i++) {
        final a = i * 2 * math.pi / n;
        pts.addAll([rr * math.cos(a), y, rr * math.sin(a)]);
      }
    }
    final geo = three.BufferGeometry()
      ..setAttributeFromString(
        'position',
        three.BufferAttribute.fromUnknown(Float32List.fromList(pts), 3),
      );
    return geo;
  }

  /// 球面城市节点（发光点）。
  three.Points _buildCityNodes(int count, double r) {
    final pos = Float32List(count * 3);
    final rnd = math.Random(42);
    for (var i = 0; i < count; i++) {
      final theta = rnd.nextDouble() * math.pi * 2;
      final phi = math.acos(2 * rnd.nextDouble() - 1);
      pos[i * 3] = r * math.sin(phi) * math.cos(theta);
      pos[i * 3 + 1] = r * math.cos(phi);
      pos[i * 3 + 2] = r * math.sin(phi) * math.sin(theta);
    }
    final geo = three.BufferGeometry()
      ..setAttributeFromString(
        'position',
        three.BufferAttribute.fromUnknown(pos, 3),
      );
    return three.Points(
      geo,
      three.PointsMaterial({
        three.MaterialProperty.color: 0x9df6ff,
        three.MaterialProperty.size: 0.045,
        three.MaterialProperty.sizeAttenuation: true,
        three.MaterialProperty.transparent: true,
        three.MaterialProperty.opacity: 0.9,
        three.MaterialProperty.blending: three.AdditiveBlending,
        three.MaterialProperty.depthWrite: false,
      }),
    );
  }

  /// 可选 GLB/GLTF 模型加载（软失败）：成功则替换程序化地球。
  Future<void> _tryLoadGlb() async {
    final path = glbPath;
    if (path == null || path.isEmpty) return;
    try {
      final f = File(path);
      if (!f.existsSync()) {
        print('[Hologram] GLB 不存在，使用程序化地球: $path');
        return;
      }
      final data = await loaders.GLTFLoader().fromPath(path);
      final scene = data?.scene;
      if (scene == null) {
        print('[Hologram] GLB 加载返回空，使用程序化地球');
        return;
      }
      _gltfRoot = scene;
      _earth?.visible = false;
      _root?.add(scene);
      print('[Hologram] GLB 模型已加载: $path');
    } catch (e) {
      print('[Hologram] GLB 加载失败（回退程序化地球）: $e');
    }
  }

  three.BufferGeometry _buildGridGeometry(int cells, double half) {
    final pts = <double>[];
    final step = (2 * half) / cells;
    for (var i = 0; i <= cells; i++) {
      final p = -half + i * step;
      pts.addAll([p, 0, -half, p, 0, half]);
      pts.addAll([-half, 0, p, half, 0, p]);
    }
    final geo = three.BufferGeometry()
      ..setAttributeFromString(
        'position',
        three.BufferAttribute.fromUnknown(Float32List.fromList(pts), 3),
      );
    return geo;
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
        three.MaterialProperty.blending: three.AdditiveBlending,
        three.MaterialProperty.depthWrite: false,
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
    final gltf = _gltfRoot;
    if (gltf != null) {
      gltf.traverse((o) {
        o.geometry?.dispose();
        o.material?.dispose();
      });
      _root!.remove(gltf);
      _gltfRoot = null;
    }
    t.scene.remove(_root!);
    for (final obj in _root!.children.toList()) {
      obj.geometry?.dispose();
      obj.material?.dispose();
    }
    _root = null;
    _earth = null;
    _core = null;
    _inner = null;
    _latGrid = null;
    _cityNodes = null;
    _ringX = null;
    _ringY = null;
    _particles = null;
    _glow = null;
    _scanSweep = null;
    _scanSlice = null;
    _grid?.geometry?.dispose();
    _grid?.material?.dispose();
    _grid = null;
    _loaded = false;
  }

  @override
  void dispose() {
    removeModel();
    _threeJs?.dispose();
    _threeJs = null;
  }
}
