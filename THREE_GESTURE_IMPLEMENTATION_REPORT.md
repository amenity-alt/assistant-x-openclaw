# THREE_GESTURE_IMPLEMENTATION_REPORT.md — Jarvis Vision 3D 手势交互落地报告

> 分支：`codex/chat-panel-merged`
> 提交：`3b0d6f4`（Phase 1 引擎接入）→ `fee236c`（Phase 2 手势控制）→ `e203868`（Phase 3-4 HUD 效果 + 渲染器开关）→ `91755a3`（常驻渲染器，泄漏规避）
> 前置文档：`GESTURE_ARCHITECTURE.md`、`THREE_ENGINE_INTEGRATION.md`

---

## 1. three.dart 集成方案

- 用户指定的 `wasabigeek/three.dart` 仓库 404 不存在；`pub.dev/packages/three` 是 2013 年死代码。
- 最终采用 **`three_js` 0.3.0**（Knightro63，纯 Dart 的 three.js 移植）+ **`flutter_angle` 0.4.1** 渲染后端。
- macOS 渲染路径：**ANGLE → Metal**（`MetalANGLE` 以 `libEGL.framework` / `libGLESv2.framework` 打包），规避 Apple 已废弃的原生 OpenGL。
- 合成方式：**Flutter 外部纹理**（`Texture(textureId:)`），**无需 Platform View、无需 WebGL**；可叠在透明玻璃 HUD 上（`Settings(alpha: true, clearAlpha: 0)`）。
- 兼容性：项目 Podfile 已是 `platform :osx, 10.15`；Dart 3.12.2 / Flutter 3.44.9 均满足三方 SDK 约束；CI（macos-latest）可完成原生构建（本地无 Xcode 不受影响）。

## 2. Renderer 架构

```
HologramRenderer（抽象接口）
  ├─ loadModel() / removeModel() / updateTransform() / dispose()
  ├─ ThreeJsRenderer（默认，three_js + flutter_angle）
  └─ CustomPainter 2.5D 回退（kUseThreeJsRenderer = false 时仅保留中央聚焦环，即原版外观）
```

- `assistant_overlay/lib/vision_gesture/hologram/`：
  - `hologram_renderer.dart` — 渲染器接口
  - `three_js_renderer.dart` — Three 渲染器（模型组、扫描效果、变换阻尼、释放）
  - `three_js_hologram_view.dart` — 宿主 StatefulWidget（只管理渲染器生命周期）
  - `renderer_config.dart` — `kUseThreeJsRenderer` 开关
- 场景结构：`scene → _root(Group，接收手势变换) → 线框核心/内发光体/外轮廓/双轨道环/粒子云/发光壳/扫描环/扫描切片`；网格底座固定在场景中。

## 3. Gesture 流程

```
vision:hand（TCP 17889，~10fps，21 点 xyz 归一化）
  └→ GestureHand（手势层数据，与渲染层解耦）
        └→ LandmarkFilter（EMA α=0.45 降噪）
              └→ GestureRecognizer（掌心位置 / 手掌滚转 roll / 俯仰 pitch / 捏合比例）
                    └→ GestureController（状态机 + 仲裁 + 死区 + 单帧限幅）
                          └→ TransformController.apply(dScale/dRot/dPos)
```

- 状态机：`IDLE → HAND_DETECTED → (PINCH_READY) → ZOOMING / ROTATING / MOVING`。
- 仲裁：捏合优先于旋转；旋转优先于移动（位移照常应用，仅标签按主手势展示）。
- 死区：旋转 `0.012 rad`、位移 `0.003`；单帧限幅：旋转 `0.5 rad`、缩放 `±6%`。
- 手势语义：
  - **手掌滚转 → 模型绕 Y 旋转**（用户「转动手」即此手势）
  - **手掌俯仰 → 模型绕 X 旋转**
  - **掌心平移 → 模型位移**
  - **捏合（拇指+食指并拢）→ 放大；张开 → 缩小**（钳制 0.8x~3.0x）

## 4. Transform 设计

- `TransformState`（渲染器无关）：`scale / rotX / rotY / rotZ / posX / posY`。
- `TransformController extends ValueNotifier<TransformState>`：10fps 手势增量累积目标态，`scale ∈ [0.8, 3.0]`、位移钳制 ±1.0。
- `ThreeJsRenderer` 动画循环（60fps）对目标做**指数阻尼插值**（τ=0.12s）：`10fps 输入 → 60fps 平滑`。
- 应用：`_root.scale.setValues(s,s,s)`、`_root.rotation.set(rx,ry,rz)`、`_root.position.setValues(px*2.6, py*2.6, 0)`。

## 5. 3D 模型加载方案

- **当前默认：程序化几何**（无外部资产、包体小）：
  - 线框二十面体核心（IcosahedronGeometry, wireframe）
  - 内发光体 + 发光外壳（AdditiveBlending 伪造辉光）
  - 外轮廓线（EdgesGeometry + LineSegments）
  - 双轨道环（TorusGeometry）
  - 粒子云（BufferGeometry + Points，加色混合）
  - 水平扫描环（RingGeometry，sin 往返扫描）+ 垂直扫描切片（旋转）+ 网格底座
- **GLB 预留**：`three_js_advanced_loaders` 提供 `GLTFLoader`（.gltf/.glb），官方仓库自带 `BoomBox.glb` 等验证资产；按需在 `_setup()` 中 `loader.load(...)` 加入场景即可，当前未启用。

## 6. 性能测试

- 渲染：ANGLE/Metal 硬件加速 + 外部纹理合成，目标 60fps；场景规模（<1 万线/点）对桌面 GPU 压力极小。
- 包体积：app 128MB（MetalANGLE `libEGL`+`libGLESv2` 约 9MB，其余为 App/Flutter 框架），与预估一致。
- 生命周期：渲染器**常驻**（首次 Vision 激活时初始化）；Vision OFF → 停帧（`visible=false`，不渲染、不释放）；Vision ON → 恢复渲染；应用退出时才 `dispose()` 释放 GPU/纹理。
- **上游泄漏规避（已实现）**：three_js issue #84（macOS/iOS 反复 dispose+create 内存泄漏，open）。`ThreeJsHologramView` 已挂在**常驻**的 `VisionHudOverlay`（不再随会话卸载），首次激活才初始化 GPU；会话间仅切换 `ThreeJS.visible`（停帧、不渲染），**不再每次 dispose/create**，模型姿态与缩放/旋转跨会话保留；应用退出时才整体释放。
- 自适应降级（samples/分辨率/粒子数）未实现，作为后续优化项（当前负载远低于阈值）。

## 7. 修改文件

| 文件 | 说明 |
|---|---|
| `assistant_overlay/pubspec.yaml` / `pubspec.lock` | 新增 `three_js: ^0.3.0`（含 flutter_angle 传递依赖） |
| `assistant_overlay/lib/vision_gesture/transform_state.dart` | 变换状态 |
| `assistant_overlay/lib/vision_gesture/transform_controller.dart` | 手势目标态 + 钳制 |
| `assistant_overlay/lib/vision_gesture/landmark_filter.dart` | EMA 降噪 |
| `assistant_overlay/lib/vision_gesture/gesture_recognizer.dart` | 特征提取（掌心/roll/pitch/捏合） |
| `assistant_overlay/lib/vision_gesture/gesture_controller.dart` | 状态机 + 仲裁 |
| `assistant_overlay/lib/vision_gesture/hologram/hologram_renderer.dart` | 渲染器接口 |
| `assistant_overlay/lib/vision_gesture/hologram/three_js_renderer.dart` | Three 渲染器（模型 + 效果 + 阻尼 + 释放） |
| `assistant_overlay/lib/vision_gesture/hologram/three_js_hologram_view.dart` | HUD 宿主组件 |
| `assistant_overlay/lib/vision_gesture/hologram/renderer_config.dart` | `kUseThreeJsRenderer` 开关 |
| `assistant_overlay/lib/vision_overlay.dart` | `vision:hand` 解析 z、接线手势管线、挂载全息层、HUD 手势状态文案 |
| `assistant_overlay/macos|linux|windows/.../generated_plugin_registrant*` | flutter_angle 插件注册（pub get 自动生成） |
| `GESTURE_ARCHITECTURE.md` / `THREE_ENGINE_INTEGRATION.md` | 设计文档 |

## 8. 测试结果

- `flutter analyze`：**0 新增**（存量 64 项 warning/info 均为既有文件，未触碰）。
- 手势逻辑临时单测（验证后未入库）：旋转累积 rotY ✅ / 捏合缩放方向与钳制 ✅ / 无手回稳停止累积 ✅ / scale 范围钳制 ✅ —— 4/4 通过。
- CI 构建（`build-overlay.yml`, macos-latest + Flutter 3.44.9）：Phase 1/2/3-4 三次均 **success**。
- 部署：三次产物安装至 `/Applications/assistant_overlay.app`（旧版备份 `.bak.<ts>`），`codesign --force --deep --sign -` 通过，TCP 17889 正常监听。
- 手动验证待用户完成：开启视觉扫描 → 全息核心显示（自转 + 扫描环/切片/网格）；转动手 → 模型旋转；捏合 → 缩放；移动手掌 → 平移；关闭视觉 → 正常退出。

## 9. Git

- 提交：`3b0d6f4` / `fee236c` / `e203868`，均已在 `codex/chat-panel-merged`，已 push 到 `origin`（amenity-alt/assistant-x-openclaw）。
- 未创建新分支、未碰 main；`scripts/start.sh`、launchd、进程保护、Python 视觉数据流与 `vision:hand` 协议均未改动。
