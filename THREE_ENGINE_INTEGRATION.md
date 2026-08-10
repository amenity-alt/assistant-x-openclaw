# THREE_ENGINE_INTEGRATION.md — Jarvis Vision 3D 引擎接入方案

> 状态：调研完成，待确认（本阶段仅分析，未修改任何代码）
> 分支：`codex/chat-panel-merged`
> 关联文档：`GESTURE_ARCHITECTURE.md`（手势架构，已确认）

---

## 0. 结论摘要（TL;DR）

1. **用户指定的 `wasabigeek/three.dart` 不存在**：GitHub API 返回 404。生态中同名/近名包如下：
   - `pub.dev/packages/three`：2013 年死代码（three.js r47 时代），`is:dart3-incompatible`，不可用。
   - `wasabia/three_dart`（three_dart 0.0.16）：真正的 three.dart 精神续作，但 2022 年后基本停更，macOS 走 **已废弃的原生 OpenGL**。
   - `Knightro63/three_js`（three_js 0.3.0）：**当前推荐**。2026-05 发布、2026-08 仍在活跃提交，macOS 通过 **ANGLE → Metal** 渲染，含 GLTF/GLB 加载器。
2. **推荐方案**：`three_js`（+ `flutter_angle` 渲染后端）作为默认 Three 渲染器；保留 CustomPainter 2.5D 渲染器作为 fallback（架构上已是双实现）。
3. **不需要 Platform View，不需要 WebGL**：three_js 通过 Flutter **外部纹理（Texture widget）** 合成画面，可直接叠在透明玻璃 HUD 上；macOS 上底层是 ANGLE（Metal）。
4. **macOS 兼容性成立**：overlay 的 Podfile 已是 `platform :osx, '10.15'`，满足 three_js（10.15）/ flutter_angle（10.14）要求；CI（macos-latest + Flutter 3.44.9）可完成原生构建；本地无 Xcode 不影响（项目本就走 CI 构建）。
5. **最大风险**：three_js 生态年轻，上游存在「macOS/iOS 反复 dispose/create 内存泄漏」（issue #84，open）与 flutter_angle 的 double-free 报告。Phase 1 技术验证必须实测「Vision 开关循环」的内存曲线，并以此决定生命周期策略。

---

## 1. 当前 Flutter 渲染架构

### 1.1 Overlay 窗口

- 技术栈：Flutter macOS 透明悬浮窗（`window_manager` + `flutter_acrylic`），TCP `127.0.0.1:17889` 与 Python 后端通信。
- 渲染：全部视觉均为 **CustomPaint 2D**（Jarvis 环、地图地球、Vision HUD 的扫描网格/手部骨骼），无任何 3D 引擎、无 WebGL。
- 构建：`scripts/start.sh` → CI（`.github/workflows/build-overlay.yml`，macos-latest + Flutter 3.44.9 + `flutter build macos --release`）→ 下载 artifact 安装。**本地无 Xcode，macOS 原生产物只能靠 CI**（新增原生插件后仍成立，因为 CI 有完整 Xcode 工具链）。
- Podfile：`platform :osx, '10.15'`，CocoaPods 已启用（window_manager/flutter_acrylic 等已是原生插件）。

### 1.2 Vision HUD 层

```
assistant_overlay/lib/vision_overlay.dart
  VisionHudController（状态机 OFF/INITIALIZING/SCANNING/HAND_DETECTED/…/ERROR）
  ├─ _VisionBackdropPainter   摄像头底 + 青色染色 + 暗角（CustomPaint）
  ├─ _ScanGridPainter         透视网格 + 扫描线（CustomPaint）
  ├─ _CenterHudPainter        中央聚焦环/扫描弧/角标（CustomPaint）
  ├─ _HandOverlayPainter      手部 21 点骨骼 + 掌心波纹（CustomPaint）
  └─ 信息面板：SYSTEM STATUS（左）/ VISION DATA（右）/ 状态大字 / 进度条
```

### 1.3 结论

- 当前没有「可被手势控制的 3D 全息模型」：中央聚焦环是纯装饰动画，与手势无关。
- 接入 3D 渲染器属于**新增一个渲染图层**（Hologram 区域），不替换现有 HUD 结构 → 符合「不推翻现有架构」。
- Flutter 引擎自身（含 Impeller）与第三方 3D 插件通过 **外部纹理** 合成，二者不冲突；无需改动窗口/透明度机制。

---

## 2. three.dart 生态调研（事实核对）

| 包 | 最新版本/发布 | 维护状态 | macOS 渲染后端 | 关键问题 |
|---|---|---|---|---|
| `three`（pub.dev） | 0.2.5+1 / 2013-04 | 死亡 | - | r47 时代古董，dart3 不兼容 |
| `wasabigeek/three.dart`（GitHub） | **404 不存在** | - | - | 用户指定链接失效 |
| `three_dart`（wasabia） | 0.0.16 / 2022-11 | 停更（repo 最后推送 2024-02） | **原生 OpenGL**（flutter_gl_macos 0.0.5，2022-07） | Apple 自 10.14 起弃用 OpenGL，无未来保障；493 stars 但下载量低（238/30d） |
| `three_dart_flutterflow` | 0.0.17 / 2025-07 | 个人兼容 fork | 仍走 OpenGL（flutter_gl_flutterflow） | 仅修了 platformViewRegistry 弃用；下载 9/30d，采纳度极低 |
| `three_js`（Knightro63） | **0.3.0 / 2026-05** | **活跃**（repo 2026-08-07 仍有提交；91 stars，5210 下载/30d） | **ANGLE → Metal**（flutter_angle 0.4.1，2026-06 发布） | 见 §7 风险；macOS 官方列 Known Issues: N/A |
| `flutter_angle` | 0.4.1 / 2026-06-30 | 活跃 | MetalANGLE（macOS）/ D3D11（Windows）/ GLES（iOS/Android） | 见 §7 风险 |

**为什么排除 three_dart 系：**
- macOS 上 flutter_gl 走的是 **原生 OpenGL（CGL）**。macOS 10.14 起 Apple 标记 OpenGL 为弃用，后续系统版本存在移除/兼容性风险；且 flutter_gl/flutter_gl_macos 自 2022 年起未更新，与 Flutter 3.44.9 的兼容性无保障。
- three_dart_flutterflow 只是「让旧库能跑」的补丁，不改变底层风险。

**为什么选 three_js：**
- 纯 Dart 实现的 three.js 移植，API 风格与 three.js 一致（Scene/Camera/Mesh/GLTFLoader…）。
- macOS 走 ANGLE（Google 官方 GLES→Metal 翻译层），**避开已废弃的 OpenGL 路径**；官方 README 明确 macOS 支持（10.15+/Metal，Known Issues: N/A）。
- `three_js_advanced_loaders` 提供 **GLTFLoader（.gltf/.glb）**，满足「GLTF/GLB 模型」需求；官方仓库自带 BoomBox.glb / DragonAttenuation.glb 等测试模型。
- 方向与上游一致：three_js main 分支正在迁移到 Impeller renderer（未发布），说明生态在向前演进。

---

## 3. three_js 接入方式

### 3.1 依赖（加入 `assistant_overlay/pubspec.yaml`）

```yaml
dependencies:
  three_js: ^0.3.0        # 自动带入 three_js_angle_renderer → flutter_angle ^0.4.0
```

- SDK 兼容：项目 Dart 3.12.2 / Flutter 3.44.9；three_js 要求 `sdk >=3.5.0`，flutter_angle 要求 `sdk ^3.8.1` → ✅
- macOS 部署目标：three_js 要求 10.15，flutter_angle 要求 10.14；项目 Podfile 已是 10.15 → ✅
- 平台插件：flutter_angle 是标准 Flutter plugin（macOS Swift + `FlutterAngle` CocoaPods pod，内置 MetalANGLE framework），CI 的 `flutter build macos --release` 会自动执行 pod install → ✅（仅首次构建更慢）

### 3.2 最小接入骨架（Phase 1 验证用）

```dart
final threeJs = three.ThreeJS(
  onSetupComplete: () => setState((){}),
  settings: three.Settings(
    alpha: true,          // 透明背景，叠在 HUD 上
    clearAlpha: 0.0,
    antialias: true,
  ),
  setup: () async {
    threeJs.camera = three.PerspectiveCamera(45, w/h, 0.1, 1000);
    threeJs.scene = three.Scene();
    final geo = three.IcosahedronGeometry(1.2, 2);      // 全息核心（程序化几何，无需 GLB）
    final mat = three.MeshBasicMaterial(…wireframe: true, emissive 青色…);
    threeJs.scene.add(three.Mesh(geo, mat));
  },
);
// 渲染进 widget 树（外部纹理，非 Platform View）：
threeJs.build();
```

GLB 加载（备用能力）：

```dart
final loader = three.GLTFLoader();
final obj = await loader.load('assets/hologram/core.glb');  // 或从 bytes 解析
threeJs.scene.add(obj);
```

### 3.3 渲染器抽象（不推翻 GESTURE_ARCHITECTURE 的分层）

```
Hand Landmark (vision:hand, 10fps)
   └→ GestureRecognizer → GestureController → TransformController
         └→ TransformState{scale(0.8~3.0), rotation(Vector3), position}
               └→ HologramRenderer（接口）
                     ├─ ThreeJsRenderer（默认，three_js + flutter_angle）
                     └─ CustomPainterRenderer（fallback，现有 2.5D）
```

- GestureController / TransformController **不直接持有 three_js 对象**，只产出 `TransformState`；渲染器消费它。
- 新增目录 `assistant_overlay/lib/vision_gesture/`（与 GESTURE_ARCHITECTURE.md 一致）：
  - `hologram/hologram_renderer.dart`（接口：`loadModel/removeModel/updateTransform/dispose`）
  - `hologram/three_js_renderer.dart`
  - `hologram/custom_painter_renderer.dart`
  - `transform/transform_controller.dart`（EMA 滤波 + 阻尼，10fps 手势 → 60fps 平滑）
  - `gesture/…`（既有设计）

---

## 4. 是否需要 Platform View

**不需要。**

- three_js 的 `ThreeJS` widget 通过 `Texture(textureId:)`（Flutter 外部纹理）把 ANGLE 渲染结果合成进 Flutter 渲染树：
  - 可以正常叠加在透明窗口上（Settings 支持 `alpha:true/clearAlpha:0.0`，需在 Phase 1 实测半透明叠层效果）；
  - 可以随 widget 缩放/裁剪/位移，无需原生窗口协调；
  - 与 Impeller / 现有 CustomPaint 层共存无冲突。
- 风险点（Phase 1 必测）：透明窗口（flutter_acrylic 毛玻璃）+ GL 纹理的 alpha 混合（premultipliedAlpha）在 macOS 上的合成表现；若出现黑底/边缘锯齿，需调整 `Settings.premultipliedAlpha` 或渲染区域圆角遮罩。

---

## 5. 是否需要 WebGL 层

**macOS 原生不需要；Web 才需要。**

- 本项目目标平台是 **macOS 桌面**，three_js 走 `three_js_angle_renderer` → flutter_angle → MetalANGLE（Metal），全程无浏览器/WebGL。
- flutter_angle 的 Web 实现（`flutter_angle_web`，WebGL2）与本项目无关，不会被拉入 macOS 构建。
- 若未来做 Web 版（如控制台预览），需在 index.html 加 `gles_bindings.js`（three_js README 有说明），但**不在本次范围**。

---

## 6. 性能评估

### 6.1 预期

- ANGLE + Metal 是硬件加速路径；Hologram 场景（几千三角形、线框+发光材质、少量粒子）**60fps 可达**。
- 渲染走纹理合成：每帧一次 GPU 拷贝，开销可控；渲染分辨率可独立于窗口设置（`renderOptions.samples`、`screenResolution`）。
- 与现有 HUD 动画并行：CustomPaint 层照常，3D 层独立 ticker；Vision 开启时才有 3D 开销。

### 6.2 自适应降级（Phase 3 实现）

```
VisionPerformanceMonitor（每秒采样渲染耗时）
  ├─ 60fps 稳定 → 保持
  ├─ <45fps   → samples 4→1、关闭 antialias、粒子减半
  └─ <30fps   → 渲染分辨率降 50%（screenResolution）、禁用扫描环后处理
```

### 6.3 已知上游性能/稳定性问题（必须写进风险表）

| 问题 | 影响 | 缓解 |
|---|---|---|
| three_js #84（open）：macOS/iOS 反复 dispose+create ThreeJS → 内存持续上涨 | Vision 频繁开关可能泄漏 | **Phase 1 实测**；若确认泄漏，改为「渲染器单例常驻、Vision OFF 只 removeModel + 停帧，不销毁 renderer」，退出应用时统一 dispose；并跟踪上游修复 |
| flutter_angle：`getUniformBlockIndex` double-free 导致堆损坏/随机崩溃（2026-07 报告，open） | 极端情况崩溃 | 规避：不共享 EGL 上下文、不用多实例；崩溃上报监控 |
| three_js：dispose 时序（先移除 mesh 再 dispose）有边界 bug | 释放顺序错误 | 封装 `disposeSafe()`：先停 ticker → 清 scene → dispose 纹理/几何 → 再 dispose 渲染器 |
| flutter_angle Web 0.4.1 不显示（已修） | 与本项目无关 | 忽略（macOS 不涉及） |

---

## 7. 包大小影响

- Dart 侧：three_js 全家桶为纯 Dart，发布包约 1~2 MB 量级（含各子包源码）。
- **原生侧（主要增量）**：flutter_angle 通过 CocoaPods 引入 `FlutterAngle` pod（内置 **MetalANGLE.framework**，含 arm64 + x86_64 双架构），预估 **+15~40 MB**（最终以 Phase 1 CI 产物实测为准；压缩 zip 会更小）。
- 模型资产：优先**程序化几何**（Icosahedron/Wireframe/粒子），不依赖 GLB 文件 → 不增加资产体积；GLB 加载能力保留，后续按需加入（单个低模 GLB 通常 <1 MB）。
- 结论：对本地安装包 +10~40MB 属可接受范围（当前 app 已是特效组件较多的 overlay）。

---

## 8. macOS 兼容性

| 检查项 | 结论 |
|---|---|
| 系统版本 | overlay Podfile `10.15`；three_js 需 10.15，flutter_angle 需 10.14 → ✅ |
| GPU | 要求 Metal：2012 年后所有 Mac 均支持 → ✅ |
| Xcode 工具链 | 本机无 Xcode，但构建走 CI（macos-latest 自带 Xcode + CocoaPods）→ ✅（与现状一致，无需新增基础设施） |
| Flutter/Dart | 3.44.9 / 3.12.2，满足三方约束 → ✅ |
| 透明窗口叠加 | 需 Phase 1 实测 alpha 合成（§4 风险点） |
| App Store / 公证 | 本地 `codesign --force --deep --sign -` 流程不受影响；MetalANGLE framework 会被一并签名 → ✅ |

---

## 9. 生命周期与内存策略（Vision OFF 必须释放）

原则：**Vision OFF 时释放一切可释放资源，但以实测泄漏曲线为准调整策略。**

```
Vision ON:
  renderer.init()（首次惰性创建）
   ├─ ThreeJS widget 挂载（alpha 透明）
   ├─ loadModel()：程序化全息核心（或 GLB）
   └─ 启动 60fps ticker（由 TransformState 驱动，非手势直接驱动）

Vision OFF（正常路径）:
  stopTicker() → removeModel()（scene.clear + 纹理/几何 dispose）
  ├─ 策略 A（默认）：renderer.dispose()，完全释放 GPU 上下文
  └─ 策略 B（若 Phase 1 复现上游 #84 泄漏）：renderer 常驻但 detach widget、停帧、清 scene
       → 退出应用时统一 dispose（单例）

应用退出:
  ThreeJS.dispose() → flutter_angle 释放 MetalANGLE 上下文
```

- 所有 `AnimationController` / ticker / TCP 监听与现有 Vision 模块同一套生命周期管理，不新增悬挂资源。
- Phase 1 验收标准之一：**连续 10 次「Vision ON 5s → OFF」循环，app 内存增量 < 50MB 且趋于平稳**（Activity Monitor 观测）。

---

## 10. 开发阶段（确认后执行，每阶段 `flutter analyze` + CI 构建验证）

| Phase | 内容 | 验收 |
|---|---|---|
| 1 | 技术验证：加 `three_js` 依赖；Vision HUD 中心挂载 `ThreeJS` 渲染一个程序化线框核心；验证透明合成、60fps、内存循环、GLB 加载（用官方 BoomBox.glb 或自建低模） | CI 构建通过；真机（overlay）显示、开关循环内存稳定 |
| 2 | 接入 TransformController：`TransformState` → ThreeJsRenderer（scale 0.8~3.0 / rotation xyz / position），捏合/旋转/移动手势驱动 | 手势可平滑控制模型 |
| 3 | Jarvis HUD 效果：wireframe + glow + scan line + grid + particle + rotation ring（three_js 材质/粒子系统） | 视觉达标，60fps |
| 4 | 替换 2.5D Hologram 为默认 Three 渲染；CustomPainter 作为 fallback 保留（`--renderer=custom` 开关） | 回归：Jarvis/Lin Meimei/地图/语音全部正常 |

产出：`THREE_GESTURE_IMPLEMENTATION_REPORT.md`，commit `feat: add jarvis gesture interaction control`，push `codex/chat-panel-merged`。

---

## 11. 禁止事项（复核）

- ✅ 不改 `scripts/start.sh`、launchd、进程保护
- ✅ 不改 Python Vision 数据流、`vision:hand` 协议
- ✅ 不改现有 HUD / 地图 / 语音 / Agent 逻辑
- ✅ 不引入 Unity / 大型游戏引擎
- ✅ 不创建新分支、不碰 main
- ✅ 不把 GL 渲染做成独立窗口（保持悬浮 overlay 内嵌）
