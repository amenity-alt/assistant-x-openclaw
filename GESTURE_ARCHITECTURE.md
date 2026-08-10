# GESTURE_ARCHITECTURE.md — Jarvis 手势交互系统（方案设计）

> 状态：待确认（本阶段仅分析，未修改任何代码）
> 分支：`codex/chat-panel-merged`（本次只读分析，无提交）

---

## 1. 当前视觉架构（现状）

Vision Mode 是「能力（Capability）」，不是独立 Agent。Python 后端负责摄像头与手部推理，
Flutter overlay 负责 HUD 渲染，两者通过 TCP `127.0.0.1:17889` 文本行协议通信。

```
src/vision.py  VisionManager（单例）
  ├─ ffmpeg avfoundation 采集（640x480@30fps，yuyv422）
  ├─ 帧泵（10fps）：切 MJPEG → vision:frame <base64-jpeg>
  └─ MediaPipe 手部推理（同帧率）→ vision:hand <json>

src/vision_hands_mediapipe.py  MediaPipeHandTracker
  └─ HandLandmarker Tasks API（num_hands=2，conf≥0.5）
     → {"hands":[{"label":"Left/Right","score":0.9,
                  "landmarks":[[x,y,z]×21]}]}（归一化 0~1）

assistant_overlay/lib/vision_overlay.dart  VisionHudController + VisionHudOverlay
  ├─ VisionMode 状态机（OFF/INITIALIZING/SCANNING/HAND_DETECTED/…/ERROR）
  ├─ 渲染层（全 CustomPaint，无 WebGL/Three.js）：
  │   _VisionBackdropPainter 摄像头底+青色染色+暗角
  │   _ScanGridPainter       透视网格+扫描线
  │   _CenterHudPainter      中央聚焦环/扫描弧/角标
  │   _HandOverlayPainter    手部 21 点骨骼+掌心波纹
  ├─ 信息面板：SYSTEM STATUS（左）/ VISION DATA（右）/ 状态大字 / 进度条
  └─ 动画：fade / scanline / sweep / progress 四个 AnimationController
```

### 技术栈结论（对照需求清单）

| 需求中提到 | 项目现状 |
|---|---|
| MediaPipe Hands | ✅ 已用（Tasks API，Python 侧） |
| Three.js / WebGL | ❌ 项目是 Flutter，**没有** Three.js/WebGL；地图模块的 3D 地球也是 CustomPaint 伪 3D |
| Flutter CustomPaint | ✅ 全部视觉层均为 CustomPaint |
| Flutter 3D | ❌ 无原生 3D 引擎；现有 3D 效果（地球/聚焦环）均为 2D 投影绘制 |

**关键事实：Vision HUD 目前没有可被手势控制的「3D 全息模型」**——中央聚焦环是纯装饰
（旋转扫描弧），不可被缩放/旋转/移动。需求中的「3D 全息模型」需要新建一个轻量
Hologram 渲染对象（2.5D：顶点数组 + 线框投影 + 透视），不引入 Three.js。

---

## 2. 当前手部数据流

```
ffmpeg 帧 → vision.py 帧泵(10fps)
              └→ MediaPipeHandTracker.process(jpeg)
                    └→ {"hands":[{label,score,landmarks[21][x,y,z]}]}
                          └→ TCP 17889:  vision:hand <json>
                                └→ VisionHudController.setHands()
                                      └→ hands: List<VisionHand>  （ChangeNotifier 通知）
                                            └→ _HandOverlayPainter 直接绘制
```

- 坐标：归一化 0~1（相对 640x480 画面）
- 频率：手部事件与帧泵同频（约 10fps）
- 现状：overlay 拿到 landmark 后**直接绘制**，没有过滤、没有手势语义层

## 3. 当前 3D 模型控制方式

**不存在。** 中央 HUD 环的 sweep 动画由固定 AnimationController 驱动，与手无关。
手势控制需要新增「Transform 数据 + Hologram 渲染」两条链路。

---

## 4. 手势接入位置（推荐方案）

**手势识别放在 Flutter overlay（Dart）**，理由：

1. 手部数据（`vision:hand`）已经以 10fps 到达 overlay，无需新增协议/Python 改动
   → 符合「不重写 Vision 系统、不碰 Python 后端、最小风险」
2. 60fps 动画控制器在 Flutter，平滑/惯性/阻尼自然在该层完成
3. Python 侧继续只做「采集+推理」，职责不变

数据流（满足「UI 不直接处理 landmark」）：

```
vision:hand (10fps)
   └→ GestureRecognizer（消费平滑后的 landmark，产出 GestureEvent）
         └→ GestureController（状态机 + 派发）
               └→ ModelTransformController（scale/rotation/position + 平滑插值）
                     └→ Hologram 渲染层（HUD 效果同步）
```

备选方案（不推荐，仅记录）：Python 侧识别后新增 `vision:gesture` 协议消息。
优点：逻辑可 Python 单测；缺点：改协议+改后端+多一跳，风险高于收益。

---

## 5. 新增模块设计

全部为 Dart，新增目录 `assistant_overlay/lib/vision_gesture/`：

```
vision_gesture/
├── gesture_state.dart          GestureState / GestureEvent / GestureType
├── landmark_filter.dart        EMA 平滑 + 置信度门控
├── gesture_recognizer.dart     捏合/旋转/移动 识别（含迟滞）
├── gesture_controller.dart     状态机 + 与 VisionHudController 双向绑定
└── transform_controller.dart   模型变换状态 + 阻尼插值
```

另新增 Hologram 渲染（放在 vision_overlay.dart 内或独立文件）：
`_HologramPainter`：线框多面体（顶点+棱），透视投影，接收 TransformState；
按手势类型叠加效果：Energy Ring（缩放）/ Rotation Grid（旋转）/ Motion Trail（移动）。

### 5.1 数据结构

```dart
enum GestureType { idle, zoom, rotate, move }

class GestureEvent {
  final GestureType type;
  final double scaleDelta;        // 相对基准的比例
  final double rotationDelta;     // 弧度（Y 主轴，X 为副轴）
  final Offset positionDelta;     // 归一化位移
  final double confidence;        // 0~1
}

class TransformState {
  double scale;        // 模型缩放，clamp [0.5, 3.0]
  double rotationY;    // 水平旋转
  double rotationX;    // 垂直旋转
  Offset position;     // 相对屏幕中心的偏移
  // 含 velocity / 阻尼系数，供插值使用
}
```

### 5.2 手势识别算法

复用现有 21 点（MediaPipe 标准索引）：

| 手势 | 关键点 | 算法 |
|---|---|---|
| 捏合缩放 | 拇指尖(4) + 食指尖(8) | `dist = |p4−p8|`；用 `|p0−p9|`（腕部到中指 MCP）归一化，抗距离/分辨率变化；`scale = currentDist / startDist`，配 EMA 平滑 |
| 捏合旋转 | 同两指向量 | `angle = atan2(y8−y4, x8−x4)`；`delta = wrap(angle−prevAngle, ±π)`；delta 主映射 `rotationY`，捏合点垂直位移映射 `rotationX` |
| 手掌移动 | 腕(0) + 中指MCP(9) | `palm = (p0+p9)/2`；开放手掌（非捏合）时 `positionDelta = palm 位移 × 灵敏度`，屏幕偏移 clamp 在可视区 |

**防同时触发**：捏合成立时在 ZOOMING / ROTATING 间按「主导变化量」仲裁
（距离变化占比大→ZOOMING，角度变化占比大→ROTATING），带迟滞避免抖动；
未捏合且掌心移动→MOVING。状态机：

```
IDLE → HAND_DETECTED → PINCH_READY → ZOOMING ⇄ ROTATING（仲裁）
                              ↘ MOVING（开放手掌）
```

### 5.3 防抖 / 平滑 / 性能

- **Landmark 平滑**：`LandmarkFilter` 对 21 点逐坐标 EMA（alpha≈0.3，按帧率 10fps 折算），
  双手独立实例
- **误触门控**：`score ≥ 0.8` 才进入识别；捏合进入阈值 <0.35、退出阈值 >0.45（迟滞）
- **平滑插值**：TransformState 用临界阻尼弹簧（或 lerp+阻尼）在 60fps tick 中逼近目标值，
  手部事件 10fps 不影响渲染流畅度
- **不新增 Timer**：复用现有 TickerProvider/AnimatedBuilder；手势事件驱动目标值，渲染走
  既有动画帧
- **资源释放**：`GestureController.dispose()` 取消订阅/置空引用；
  `TransformState` 复位；`_HologramPainter` 不持外部资源；在
  `VisionHudOverlay.dispose()` 与 `onExitDone()` 两处确保释放（满足「关闭 Vision 必须释放」）

### 5.4 HUD 效果（Jarvis 风格）

| 手势 | 效果 |
|---|---|
| ZOOMING | 模型外 Energy Ring（随 scale 扩缩）+ 中央环半径同步 |
| ROTATING | Rotation Grid（经纬线网格随 rotationY/X 旋转）+ 扫描弧跟随 |
| MOVING | Motion Trail（最近 N 个位置淡出连线）+ 位置网格线 |
| 通用 | 左下角新增 `GESTURE` 状态灯（IDLE/PINCH/ZOOM/ROTATE/MOVE） |

全部复用现有 CustomPaint 风格（#64D8FF 主色 / #FFB347 强调色），不引入新依赖。

---

## 6. 数据流设计（完整链路）

```
Python                          Flutter overlay
────────                        ──────────────
ffmpeg 帧 ──10fps──► vision:frame ──► Backdrop
MediaPipe ──10fps──► vision:hand ──► VisionHudController.hands
                                        │
                                        ▼
                                  LandmarkFilter (EMA)
                                        ▼
                                  GestureRecognizer
                                        │  GestureEvent
                                        ▼
                                  GestureController（状态机/仲裁/门控）
                                        │
                                        ▼
                                  ModelTransformController（阻尼插值, 60fps）
                                        │ TransformState
                                        ▼
                                  _HologramPainter + HUD 效果层
```

---

## 7. 修改 / 新增文件清单（确认后执行）

**新增**
- `assistant_overlay/lib/vision_gesture/gesture_state.dart`
- `assistant_overlay/lib/vision_gesture/landmark_filter.dart`
- `assistant_overlay/lib/vision_gesture/gesture_recognizer.dart`
- `assistant_overlay/lib/vision_gesture/gesture_controller.dart`
- `assistant_overlay/lib/vision_gesture/transform_controller.dart`
- `assistant_overlay/lib/vision_gesture/hologram_object.dart`（线框模型+投影，可选并入渲染层）

**修改**
- `assistant_overlay/lib/vision_overlay.dart`
  - 中央区挂载 Hologram 层 + Transform 动画
  - 左右面板 / 状态区新增 GESTURE 指标
  - `initState/dispose/onExitDone` 接入 GestureController 生命周期

**不改**
- `scripts/start.sh`、launchd、进程保护逻辑
- `src/vision.py`、`src/vision_hands_mediapipe.py`、`src/main.py`（协议与后端零改动）
- 已有 HUD 各渲染层行为（只叠加，不重写）

---

## 8. 验证计划

1. `flutter analyze`（新增文件 0 告警；存量告警不新增）
2. 纯 Dart 逻辑验证：用固定 landmark 序列（合成捏合/旋转/移动数据）跑
   Recognizer/Transform，断言状态转换与目标值（`dart run` 临时脚本，不落库测试）
3. 端到端冒烟：经 TCP 注入 `vision:hand` 模拟帧 → 观察 HUD 手势状态灯与模型变换
4. 手动实测：手进入 → 捏合缩放 → 旋转 → 手掌移动 → 退出 Vision 确认无泄漏（进程内存不增长）
5. `git diff --check`、确认未触碰禁用清单

## 9. 风险与决策点

| 风险 | 决策 |
|---|---|
| 无现成 3D 模型 | 用线框多面体（2.5D CustomPaint）作为全息模型，后续可换任意顶点模型 |
| 单摄像头+10fps 手部事件 | 足够捏合/旋转/移动；双手扩展接口预留，识别层隔离 |
| 手势误触 | 置信度 ≥0.8 + 迟滞 + 死区；状态仲裁防并发触发 |
| 性能 | 无新依赖、无新 Timer；手部事件 10fps 与渲染 60fps 解耦 |

**双手扩展（预留）**：`GestureRecognizer` 输出接口预留 `TwoHandGestureEvent`，
未来双手展开/靠近/旋转空间时，仅需扩展 Recognizer + TransformController，不动渲染层。
