# VISION_UPGRADE_PLAN.md — Jarvis Spatial Vision Mode 升级方案

> 状态：Phase 1 分析完成，待确认（本阶段未修改任何代码）
> 分支：`codex/chat-panel-merged`
> 关联文档：`VISION_ARCHITECTURE.md`、`VISION_UI_DESIGN.md`、`VISION_FINAL_REPORT.md`、
> `GESTURE_ARCHITECTURE.md`、`THREE_ENGINE_INTEGRATION.md`、`THREE_GESTURE_IMPLEMENTATION_REPORT.md`

---

## 0. 结论摘要（TL;DR）

1. **3D 全息空间**：沿用已确认的 **three_js 0.3.0（ANGLE→Metal）** 方案，不引入新引擎；
   当前中央全息区域太小（`ringSize = 屏高×0.42`，渲染器固定 360×360）且用户反馈「转动手没效果 / 打开后没有球体」。
   Phase 2 将放大到屏幕约 55% 高度、保留常驻渲染器生命周期策略、升级手势状态机（IDLE→HOVER→GRAB→TRANSFORM→RELEASE），
   并新增**鼠标/触控板回退交互**（拖拽/滚轮缩放/双指旋转），确保「一定能操作」。
2. **物体识别**：**默认走现有 Hermes 网关（OpenAI 兼容 `/v1/chat/completions` + `image_url`）**——复用现有 API Key 与网关架构，零新依赖；
   同时实现 **MediaPipe ImageClassifier（EfficientNet-Lite0，离线兜底）** 与 **YOLO/MobileSAM 预留接口** 三层后端。
   `three_js_advanced_loaders` 已在 `pubspec.lock`（three_js 传递依赖），GLTF/GLB 加载无需新增包。
3. **vision-agent**：作为 **Capability 模块**（`src/assistants/vision_agent/`），不注册独立唤醒词 Agent、不写入 Jarvis 核心；
   由 `main.py` 语音拦截层触发（“扫描这个 / 识别一下 / 这是什么 / 详细介绍一下”）。
4. **禁止事项**全部遵守：不动 `scripts/start.sh`、launchd、第二启动器、`vision:hand` 协议与 TCP 17889 文本行协议、不大规模重构。

---

## 1. 当前架构分析（现状）

### 1.1 Python 后端（`src/`）

| 模块 | 职责 | 关键事实 |
|---|---|---|
| `vision.py` | VisionManager 单例：生命周期 + 帧流 | 640×480@10fps 推 `vision:frame`；状态机 `INITIALIZING→SCANNING→HAND_DETECTED→ANALYZING→COMPLETED/ERROR`；ffmpeg avfoundation 长驻 MJPEG 管线；软失败 |
| `vision_hands_mediapipe.py` | MediaPipe HandLandmarker | 21 关键点 xyz 归一化；`models/hand_landmarker.task` 已就位；手部 10fps |
| `camera.py` | 按需抓帧 | `/camera/snapshot` HTTP 接口（Hermes 用）；复用 imageio-ffmpeg 静态二进制 |
| `main.py` | 语音主循环 | `_handle_vision_command`（开启/关闭视觉扫描，15s 去重）、`_vision_like` 流式预判；角色语言口播（Jarvis 英文 / 林妹妹中文） |

### 1.2 Flutter Overlay（`assistant_overlay/`）

| 文件 | 职责 | 关键事实 |
|---|---|---|
| `vision_overlay.dart` | VisionHudController + VisionHudOverlay | 全屏 HUD：摄像头底/扫描网格/中央聚焦环/手部骨骼/左右信息面板/顶栏/底部进度；**中央区域 `ringSize = 屏高×0.42`，内嵌 three_js 渲染器 360×360** |
| `vision_gesture/` | 手势链路 | `GestureRecognizer`（掌心/roll/pitch/捏合）→ `GestureController`（IDLE→HAND_DETECTED→PINCH_READY→ZOOMING/ROTATING/MOVING，带滞回+死区+限幅）→ `TransformController`（scale 0.8~3.0，pos ±1.0） |
| `vision_gesture/hologram/` | 渲染器抽象 | `HologramRenderer` 接口 + `ThreeJsRenderer`（程序化二十面体线框+内发光+双轨道环+粒子云+扫描环/切片+网格底座；阻尼插值 10fps→60fps）+ `renderer_config.kUseThreeJsRenderer` 开关 |
| `jarvis_overlay.dart` | TCP 分发 | 已解析 `vision:start/stop/status/frame/hand`；**`agent_overlay.dart`（林妹妹链路）未挂 Vision HUD** |

### 1.3 TCP 协议（127.0.0.1:17889，文本行 `\n` 分隔）

```
vision:start / vision:stop / vision:status <STATE> /
vision:frame <base64-jpeg> / vision:hand <json>
```

### 1.4 与目标差距

| 目标 | 现状 | 差距 |
|---|---|---|
| 大型 3D 全息空间（占屏幕主要区域） | 中央约 34% 屏高、渲染器固定 360×360 | 区域小；无鼠标回退 |
| 拖拽/缩放/旋转/聚焦 | 手势链路已存在，但用户反馈「转动手无效果 / 打开后无球体」 | 需调试 + 可见性兜底 + 鼠标交互 |
| 手持物体识别 | 无 | 全新 |
| vision-agent | 无 | 全新 |
| 识别结果面板（右侧） | 右侧仅 VISION DATA 静态面板 | 新增 OBJECT FOUND 面板 |

---

## 2. Phase 2 — 3D 全息空间升级（Flutter 侧为主）

### 2.1 布局：中央空间放大

- `vision_overlay.dart`：中央全息区域由 `屏高×0.42` 提升到 **宽 = 屏宽×0.60、高 = 屏高×0.55**（可配置常量）；
  保持左 SYSTEM STATUS / 右 VISION DATA 面板不重叠，识别结果面板放右侧下部（见 2.5）。
- `ThreeJsRenderer.loadModel()` 的 `size` 跟随宿主 SizedBox（不再写死 360×360），相机 FOV/位置按比例适配。

### 2.2 渲染器增强（`three_js_renderer.dart`）

- **模型层**：
  - 默认程序化「全息地球」：`SphereGeometry` + 线框球壳 + 发光核心 + 双轨道环 + 粒子云 + 经纬网格 + 扫描环/切片（无外部资产，保证可见）。
  - **GLB/GLTF 预留**：`three_js_advanced_loaders.GLTFLoader` 已随 `three_js` 传递依赖可用；
    若用户放入 `earth.glb / robot.glb / object.glb`（`assistant_overlay/assets/` 或运行时路径），`loadModel` 尝试加载并**失败自动回退程序化模型**（软失败原则）。
- **效果层**：Wireframe + AdditiveBlending 辉光 + Scan Line + Grid + Particle 全部保留；增加**空闲自转**（无手势时缓慢公转，速度可调）与**聚焦动画**（进入 Vision 时模型从中心展开，退出时收缩）。
- **生命周期**：维持「常驻渲染器」策略（首次激活初始化 GPU，会话间仅切 `visible`，应用退出才 `dispose`），规避 three_js #84 泄漏。

### 2.3 手势状态机升级（`gesture_controller.dart`）

目标状态机（对齐用户要求，避免误触）：

```
IDLE → HOVER（掌心进入画面且稳定 ≥ 0.3s，不立即响应）
     → GRAB（捏合进入，或鼠标按下）
     → TRANSFORM（缩放/旋转/位移按现有仲裁执行）
     → RELEASE（捏合退出 / 手丢失 / 鼠标松开）→ IDLE
```

- 保留现有滞回/死区/单帧限幅；新增 **HOVER 稳定计时**（防手一闪就触发）与 **RELEASE 阻尼回稳**。
- 手势→变换仍只产出 `TransformState`，渲染器独立消费（架构不变）。

### 2.4 鼠标/触控板回退交互（`three_js_hologram_view.dart` 新增）

- **拖拽**：左键按下拖动 → 模型绕 X/Y 旋转（GRAB 语义）；双击 → 复位。
- **滚轮**：缩放（对应捏合）；**触控板双指**：旋转+缩放。
- 目的：手部跟踪不可用 / 用户不便挥手时，3D 空间依然可操作（解决「没有球体给我操作」）。

### 2.5 右侧识别结果面板（`vision_overlay.dart`）

- 新增 `vision:object <json>` 解析 + `OBJECT FOUND` 面板（右侧 VISION DATA 下方）：
  显示 物体名 / 类别 / 置信度 / 简述；状态文案 `SCANNING… → OBJECT FOUND → ANALYZING…` 复用现有状态机。

---

## 3. Phase 3 — 手持物体视觉识别（Python 侧）

### 3.1 方案评估

| 方案 | 依赖 | 离线 | 精度/能力 | 适配度 |
|---|---|---|---|---|
| **A. 视觉 LLM（现有 Hermes 网关，`image_url` base64）** | 无新增 | ✗ | 高（自由描述：型号/用途/特点） | ✅ 复用现有 Key/网关/架构，零依赖 |
| B. MediaPipe ImageClassifier（EfficientNet-Lite0） | mediapipe 已装，模型 ~9MB 自动下载 | ✅ | 中（ImageNet 1000 类粗分类） | ✅ 离线兜底，10ms~50ms/帧 |
| C. YOLO / MobileSAM | torch/ultralytics（未安装，数百 MB） | ✅ | 高（检测框/分割） | ⚠️ 依赖重，仅预留接口 |

**推荐：A 为主、B 兜底、C 预留**。A 是否可用取决于网关模型是否支持图像输入——Phase 3 第一步做连通性实测（发一张测试图），失败自动切 B。

### 3.2 模块设计（新增 `src/vision_object.py`）

```
VisionObjectRecognizer（抽象接口）
  ├─ HermesVisionBackend    # 默认：网关 chat/completions + image_url(base64) → JSON
  ├─ MediaPipeClassifier    # 兜底：本地 ImageClassifier（EfficientNet-Lite0，2-5FPS 低频）
  └─ YoloBackend（预留）    # 未来 torch 环境启用
识别结果统一结构：
  {"label":"MacBook Pro","category":"Laptop","confidence":0.95,
   "info":"…型号/用途/特点…","bbox":[x,y,w,h]}
```

- 帧来源：直接复用 `vision.py` 帧管线里的当前 JPEG（不重复开摄像头、不新增授权）。
- 频率：手部跟踪 10fps 不变；物体识别**按需触发** + 扫描模式下低频轮询（约 2s/次），全部在独立线程池执行，不阻塞语音主循环。

### 3.3 协议扩展（保持现有文本行风格，不破坏旧指令）

```
vision:scan <on|off>                 # 物体扫描模式开关（复用 SCANNING/ANALYZING 状态）
vision:object <json>                 # 识别结果（label/category/confidence/info/bbox）
```

### 3.4 vision-agent（新增 `src/assistants/vision_agent/`）

```
src/assistants/vision_agent/
  __init__.py        # VisionAgent capability：scan() / describe() / status()
  prompt.py          # 系统提示词（物体识别 + 详细介绍），角色语言由调用方注入
  vision_tools/
    __init__.py
    capture.py       # 从 VisionManager 取当前帧 / camera.py 抓帧
    classify.py      # 后端选择与调用（Hermes / MediaPipe / YOLO 预留）
    describe.py      # “详细介绍一下” → 网关自由文本描述
```

- 不注册进 `assistants.json`（不占唤醒词、不改变角色切换）；作为 capability 由 main.py 拦截层调用。
- 识别结果经 `visual.send("vision:object …")` 推给 overlay 右侧面板，口播走 `_map_speak`（角色语言）。

---

## 4. Phase 4 — 语音整合（`src/main.py`）

扩展 `_vision_like` / `_handle_vision_command`（同地图/电脑控制同级拦截，不进大模型）：

| 用户话术 | 行为 |
|---|---|
| “开启视觉扫描 / 打开视觉模式” | 现有：Vision ON（全息空间展开） |
| “关闭视觉扫描 / 退出视觉模式” | 现有：Vision OFF |
| “扫描这个 / 识别一下 / 这是什么” | Object Scan ON：抓帧 → 识别 → 口播 + 右侧面板 |
| “详细介绍一下” | 复用最近识别帧 → `describe()` → 口播详情 |
| “关闭扫描 / 停止识别” | Object Scan OFF（Vision 保持或随模式退出） |

- 语言跟随角色：Jarvis 英文 / 林妹妹中文（复用 `_current_lang()`）。
- 去重窗口沿用 15s TTL 模式；口播期间 `_is_processing` 标记，防回声。

---

## 5. 性能与约束

- 物体识别独立线程（`ThreadPoolExecutor(max_workers=1)`），绝不阻塞语音主循环/VAD/ASR/TTS。
- 帧流：摄像头采集 30fps → 推送 10fps（不变）；识别低频（按需 + 2s 轮询）。
- 渲染：常驻渲染器 + 停帧策略；若 FPS 压力高，按 `renderer_config` 降粒子数/分辨率（预留开关）。
- 资源释放：Vision OFF → 停帧、清识别结果、取消定时器/线程；应用退出 → 渲染器 `dispose`。
- **禁止修改**：`scripts/start.sh`、launchd、第二启动器、TCP 17889 协议既有指令、`vision:hand` 载荷、`start.sh` 守护逻辑。

---

## 6. 分阶段交付与验证

| 阶段 | 内容 | 验证 |
|---|---|---|
| **2a** | 中央区域放大 + 渲染器尺寸自适应 + 程序化地球 + GLB 预留 | `flutter analyze`；开启视觉扫描 → 大型球体可见、空闲自转 |
| **2b** | 手势状态机升级 + 鼠标回退交互 | 转手/捏合/拖动/滚轮均可操作；复位双击 |
| **3a** | `vision_object.py` + 后端连通性实测（Hermes 图输入） | `python -m py_compile`；发测试图看是否返回识别 JSON；失败切本地 |
| **3b** | MediaPipe Classifier 兜底 + `vision:object` 协议 + overlay 面板 | 扫描模式低频识别、右侧面板显示结果 |
| **3c** | `vision_agent` 模块 + describe | `python -m py_compile`；识别 + 详情口播 |
| **4** | main.py 语音接线（扫描/识别/详细介绍/关闭扫描） | 全链路语音实测；确认无回归（唤醒/对话/地图/电脑控制） |

每阶段收尾：`python -m py_compile`（改动 Python）、`flutter analyze`（改动 Dart）、不改 `start.sh`/launchd。

---

## 7. 风险与对策

| 风险 | 对策 |
|---|---|
| 网关（DeepSeek 等）不支持 `image_url` | Phase 3a 先连通性实测；失败自动切 MediaPipe 本地后端 |
| 本地无 Xcode，macOS 原生产物依赖 CI | 与现有一致：改动后 `flutter build macos --release` 走 CI，安装 artifact |
| three_js 生态年轻（#84 泄漏等） | 维持常驻渲染器策略，会话间不 dispose/create |
| 摄像头授权 / 多 App 抢占 | 复用现有 ffmpeg 授权路径；识别只读当前帧，不重开设备 |
| 手势误触 / 抖动 | HOVER 稳定计时 + 滞回 + 死区 + 单帧限幅（沿用并增强） |

---

## 8. 修改文件清单（预估）

**Flutter（`assistant_overlay/lib/`）**
- `vision_overlay.dart`：中央区域放大、`vision:object` 解析、右侧 OBJECT FOUND 面板
- `vision_gesture/hologram/three_js_renderer.dart`：尺寸自适应、程序化地球、GLB 加载预留、空闲自转
- `vision_gesture/hologram/three_js_hologram_view.dart`：鼠标/触控板交互、聚焦动画
- `vision_gesture/gesture_controller.dart`：状态机升级（HOVER/GRAB/RELEASE）
- `vision_gesture/transform_controller.dart` / `transform_state.dart`：边界放宽（scale 0.6~4.0 等，按需）
- `jarvis_overlay.dart`：`vision:scan` / `vision:object` 分发（若林妹妹 overlay 需要，`agent_overlay.dart` 同步）

**Python（`src/`）**
- `vision_object.py`（新增）：识别抽象 + 三后端
- `vision.py`：帧管线暴露当前帧、`vision:scan` / `vision:object` 发送（不破坏现有指令）
- `assistants/vision_agent/`（新增）：capability 模块 + `vision_tools/`
- `main.py`：语音拦截扩展（扫描/识别/详细介绍/关闭扫描）

**文档**
- `VISION_OBJECT_RECOGNITION_DESIGN.md`（模型选择/接口/性能，Phase 3 交付）
- `JARVIS_SPATIAL_VISION_REPORT.md`（最终交付报告）
