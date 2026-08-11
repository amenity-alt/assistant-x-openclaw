# JARVIS Spatial Vision Mode — 交付报告

> 分支：`codex/chat-panel-merged` ｜ 未创建新分支、未修改 main
> 目标：把视觉模式从「装饰性动画」升级为「可交互 3D 全息空间 + 手持物体视觉识别」

---

## 1. 总体架构

原有：

```
Hand Landmark → GestureRecognizer → GestureController → TransformController → CustomPainter Hologram
```

升级后（保留 Renderer 抽象层，默认 Three.js，可一键回退 CustomPainter）：

```
Hand Landmark → GestureRecognizer → GestureController → TransformController → Hologram Renderer Interface
                                                                                        │
                                                                        ┌───────────────┴───────────────┐
                                                                  ThreeJsRenderer               CustomRenderer(2.5D)
```

物体识别为独立 Capability（非第三个 Agent）：

```
Camera Frame → VisionObjectRecognizer(Hermes视觉LLM → MediaPipe本地分类 → YOLO预留)
                    │
      vision:object <json> ──TCP 17889──→ Overlay 右侧 OBJECT FOUND 面板
                    │
              on_object 回调 ──→ Jarvis/林妹妹 语音口播（跟随角色语言）
```

语音链路：用户说「扫描一下 / 识别这个 / 这是什么」→ `_handle_vision_command` 拦截（不进大模型）→ 低频扫描线程（~2s/次）→ 结果口播 + HUD 面板。

## 2. 修改文件

### Flutter（`assistant_overlay/`）
| 文件 | 变更 |
|---|---|
| `pubspec.yaml` / `pubspec.lock` | 新增 `three_js: ^0.3.0`、`three_js_advanced_loaders: ^0.3.0` |
| `lib/vision_overlay.dart` | 中央全息区域放大为 屏宽×0.60 / 屏高×0.55；新增 OBJECT FOUND 面板（VISION DATA 下方）；`VisionHudController` 增加 `objectResult` / `objectScanning` + `setObject()` / `setObjectScan()`；手势相位文案补齐 |
| `lib/vision_gesture/hologram/three_js_renderer.dart` | `size`/`glbPath` 接入 + `_viewScale` 自适应；程序化全息地球（线框核心 + 深蓝内芯 + 经纬网格 + 120 城市发光节点 + 慢速自转 `0.08 rad/s`）；GLB 加载预留 + 资源释放 `dispose()` |
| `lib/vision_gesture/hologram/three_js_hologram_view.dart` | 重写为鼠标/触控板回退交互：左键拖拽旋转、滚轮缩放、双指旋转+缩放、双击复位；保留手势控制器相位驱动 |
| `lib/vision_gesture/hologram/renderer_config.dart` | `kUseThreeJsRenderer` 开关、`kHologramGlbPath`（当前空→程序化地球） |
| `lib/vision_gesture/gesture_controller.dart` | 状态机升级：`IDLE→HAND_DETECTED→HOVER(3帧稳定)→GRAB(捏合单帧)→TRANSFORM→RELEASE`；手丢失 `_wasTracking` 平滑过渡 |
| `lib/vision_gesture/transform_controller.dart` | scale 钳制放宽 `0.6–4.0`、position `±1.2`；`TransformState` + lerp/damping |
| `lib/jarvis_overlay.dart` | TCP 分发新增 `vision:object` / `vision:scan` |

### Python（`src/`）
| 文件 | 变更 |
|---|---|
| `vision.py` | `last_frame()` 缓存 JPEG；`set_object_scan()` 低频扫描线程；`send_object()` 推 `vision:object`；`on_object` 回调；`set_role()`；`stop()` 同步关闭扫描 |
| `vision_object.py`（新增） | `HermesVisionBackend`（识别+describe）、`MediaPipeClassifier`（EfficientNet-Lite0，模型自动下载）、`YoloBackend`（预留）、`VisionObjectRecognizer` 统一入口 + 单例 |
| `hermes_bridge.py` | `send_image_and_wait(image_b64, prompt, timeout)` — OpenAI 兼容 `image_url`(data URL)，不写会话历史，软失败 |
| `assistants/vision_agent/`（新增） | `VisionAgent` 单例（scan/describe/status）+ `prompt.py` + `vision_tools/`（capture/classify/describe） |
| `main.py` | `_handle_vision_command` 扩展（扫描开/关/详细介绍）；`_on_vision_object` 角色语言口播；`_vision_like` 流式预判；角色切换绑定 `set_role()`；`exit_standby` 退下时强制关闭物体扫描 |

## 3. 3D 引擎方案

- **选择**：`three_js: ^0.3.0`（Flutter 上 WASM 编译，macOS ANGLE→Metal 后端），未引入游戏引擎。
- **渲染器**：`HologramRenderer` 抽象接口；默认 `ThreeJsRenderer`，`renderer_config.dart` 中 `kUseThreeJsRenderer=false` 可回退 CustomPainter 2.5D。
- **模型**：`GLTFLoader().fromPath()` 加载 GLB/GLTF；加载失败静默回退程序化全息地球（线框 + 深蓝内芯 + 经纬网格 + 城市节点 + 慢速自转），保证开箱即用。
- **模型生命周期**：`loadModel() / removeModel() / updateTransform() / dispose()`；Vision OFF 时遍历 `traverse` 释放 geometry/material，防止 GPU 泄漏。
- **性能**：`_viewScale = (size.shortestSide / 360).clamp(0.9, 4.0)` 自适应屏幕；地球自转 0.08 rad/s 慢速；识别扫描独立低频线程（~2s/次），不阻塞 60fps 动画与语音。

## 4. Gesture 方案

- 手势链路：`GestureRecognizer → GestureController(状态机) → TransformController(TransformState) → Renderer`，手势不直接碰 Three 对象。
- 状态机：`IDLE → HAND_DETECTED → HOVER(3帧稳定) → GRAB(捏合单帧) → TRANSFORM(缩放/旋转/位移) → RELEASE`，手丢失走 `_wasTracking` 过渡，避免误触与抖动。
- 桌面回退交互（无摄像头/手势不可用时）：左键拖拽旋转、滚轮缩放、触控板双指旋转+缩放、双击复位。
- Transform：scale `0.6–4.0`、rotation x/y/z、position `±1.2`；10fps 手势输入经 lerp/damping 平滑到 60fps 动画。

## 5. 物体识别模型方案

分层后端（默认 Hermes 优先，全部软失败，无 Key 时自动降级）：

1. **Hermes 视觉 LLM（默认）** — `hermes_bridge.send_image_and_wait()`，OpenAI 兼容 `image_url` data URL；返回结构化 JSON（label/confidence/description）；需角色 profile `.env` 配置视觉模型端点。
2. **MediaPipe 本地分类（兜底）** — EfficientNet-Lite0（`models/efficientnet_lite0.tflite`，首次自动下载）；纯本地离线。
3. **YOLO（预留）** — `YoloBackend` 接口已留，后续可接。

识别结果经 `vision:object <json>` 推送 Overlay 右侧 OBJECT FOUND 面板，同时 `on_object` 回调触发语音口播（Jarvis 英文 / 林妹妹中文，`_map_speak` 防回声）。

## 6. 语音指令

| 用户说 | 行为 |
|---|---|
| 开启视觉扫描 / 启动视觉模式 / 打开视觉 | Vision Mode 启动 |
| 关闭视觉扫描 / 退出视觉模式 | Vision Mode 关闭 |
| 扫描一下 / 识别这个 / 这是什么 | 物体扫描开（自动进入 Vision Mode） |
| 关闭扫描 / 停止识别 / 退出扫描 | 仅停止物体扫描，保留视觉模式 |
| 详细介绍一下 / 详细介绍 | 用当前帧调 vision-agent 详细描述 |
| 退下 | 退出连续对话 + 强制关闭物体扫描 |

修复：`scan_on` 正则改为必须带后缀（`扫描一下/这个/那个`、`识别一下/这个/那个`、`这是什么`），避免「开启视觉扫描/关闭视觉扫描」被误判为物体扫描。

## 7. 测试结果

- Python：`./venv/bin/python -m py_compile` 全部改动文件通过。
- Flutter：`flutter analyze` 通过，0 error / 69 issues（均为存量 info/warning，本轮无新增 error）。
- 指令解析冒烟：20 组话术全通过（start/stop/scan_on/scan_off/describe/不拦截）。
- 手势状态机单测（临时，已删除）：HOVER→GRAB→TRANSFORM→RELEASE、scale/pos 钳制、roll 旋转累积通过。

## 8. 遵守的边界

- 未修改 `scripts/start.sh`、launchd、杀进程保护。
- 未修改 `vision:hand` TCP 协议、未破坏 17889 既有指令。
- 未创建第三个唤醒 Agent；Vision 作为 Capability 供 Jarvis / 林妹妹共用。
- 未大规模重构 main.py（仅新增拦截分支与回调）。
