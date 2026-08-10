# VISION_ARCHITECTURE.md

> Jarvis Vision Mode（视觉扫描模式）架构设计 — PHASE 1 输出
> 分支：`codex/chat-panel-merged` ｜ 只读分析，未修改任何代码

---

## 0. 结论摘要

Vision Mode 以 **Capability（能力模块）** 而非第三个 Agent 落地：

- **Python 侧**新增 `src/vision.py`（`VisionManager` 单例）：摄像头帧采集 + 状态机 + 向 overlay 推送事件；手部跟踪做成可插拔接口（Phase 1 渲染层 + 预留接口，Phase 2 可接入 MediaPipe）。
- **Flutter 侧**新增 `assistant_overlay/lib/vision_overlay.dart`（全屏 HUD 层 + `VisionHudController`），挂在现有 `JarvisAgentVisual`（及未来 `LinMeimeiPet`）内部，通过现有 `handleCommand` 接收 `vision:*` TCP 命令。
- **语音触发**在 `src/main.py` 断句分发处新增一个 `_handle_vision_command()`，与地图指令同级、本地拦截、不进大模型；回复语言跟随角色（Jarvis 英文 / 林妹妹中文）。
- **零大型依赖**：不引入 Three.js / WebGL / OpenCV / MediaPipe（Phase 1）；摄像头复用现有 `camera.py` 的 ffmpeg avfoundation 路径。
- **不修改**：`scripts/start.sh`、launchd、杀进程保护、地图核心逻辑、Hermes/OpenClaw 桥、TTS 引擎选择。

---

## 1. 当前架构

```
scripts/start.sh（唯一监督者，禁止改动）
   ├─ 合并 keywords/*.txt → keywords/global.txt
   ├─ 清理端口 17888/17889/18790（lsof kill）
   ├─ 拉起 assistant_overlay.app（Flutter 透明悬浮层，macOS borderless + ignoresMouseEvents）
   ├─ hermes_provision.py（engine=hermes 时自愈各角色网关）
   └─ 前台运行 venv/bin/python src/main.py --provider coreml|mps|cpu
```

- **Python 后端** `src/main.py`（3207 行）：
  - 唤醒词（sherpa-onnx KWS，`keywords/global.txt`）→ 声纹验证（唤醒/打断时）→ SenseVoice ASR（流式）→ 指令分发。
  - 指令分发位置：`VoiceAssistant._process_audio()` 断句分支（约 2051 行），当前顺序：退出 → 重启 → **地图指令 `_handle_map_command()`** → 进大模型（Hermes `send_and_wait_stream` 流式回包 + 增量 TTS）。
  - Agent 体系：`assistants.json` 定义 jarvis / lin-meimei；`src/assistants/__init__.py` 按 `components` 创建 feedback / visual / tts；`_switch_assistant()` 切换并 `set_tts()`。
  - TTS：`src/tts.py` 统一入口；`JarvisTTS`（`src/assistants/jarvis/tts.py`）按文本自动选引擎——**含 CJK → MeloTTS 女声，纯英文 → Piper 英音**。语言策略 `_current_lang()`：Jarvis=英文、林妹妹=中文。
  - 摄像头：`src/camera.py` `CameraController.capture()` 按需 ffmpeg 抓帧（avfoundation，JPEG），HTTP API `/camera/snapshot` 供 Hermes vision_analyze 使用。
- **Flutter overlay** `assistant_overlay/`（透明全屏、点击穿透、纯语音交互）：
  - `lib/main.dart` → `lib/agent_overlay.dart`（`AgentOverlay`，TCP 监听 17889，按 `agent:xxx` 切换 IndexedStack）→ 各 Agent Visual。
  - `lib/jarvis_overlay.dart`（1879 行）`JarvisAgentVisual`：环形动画、右下角合并聊天面板（`user:` / `ai:`）、左上角地图卡片（`MapGlobeCard`）、左下角 SYSTEM STATUS + 序列帧；`handleCommand` 处理 `wake/hide/map_zoom/map_locate/map_news/user:/ai:/audio_level/reset_scale`。
  - `lib/map_globe_card.dart`：CustomPainter 原生绘制的 3D 地球（慢速自转 0.3°/s、国家多色高亮、天地图定位、城市/全球资讯、Memory Log、UPLOAD/ARCHIVE/SUMMARY 按钮）。
  - 注意：`lib/overlay/` 子目录是一套**未启用的旧重构副本**（无任何 import），不要往里面写。
- **依赖现状（已核查）**：Python venv 仅 42 个包——sherpa-onnx / numpy / librosa / sounddevice / soundfile / piper-tts / onnxruntime / imageio-ffmpeg / requests / websocket-client 等。**无 MediaPipe、无 OpenCV、无 torch/ultralytics**。Flutter pubspec：无 camera 插件、无 WebView/three.js（透明层上 WKWebView 不合成，全部走 CustomPainter 原生绘制）。

---

## 2. Vision 应该放在哪里（Capability，不是 Agent）

| 层 | 位置 | 说明 |
|---|---|---|
| Python 能力 | 新增 `src/vision.py` | `VisionManager` 单例：摄像头帧流、状态机、事件推送、手部跟踪抽象接口 |
| Python 语音入口 | `src/main.py` `_process_audio` 断句分支 | 新增 `_handle_vision_command()`，与地图指令同级本地拦截 |
| Flutter 渲染 | 新增 `assistant_overlay/lib/vision_overlay.dart` | `VisionHudOverlay` 全屏 HUD + `VisionHudController` |
| Flutter 挂载 | `lib/jarvis_overlay.dart` | `handleCommand` 增加 `vision:*` 分支；`buildOtherOne` 的 Stack 顶层加全屏层；`dispose()` 释放 controller |
| 协议 | 沿用现有 17889 文本行协议 | 新增 `vision:start / vision:stop / vision:status / vision:hand / vision:frame` |

未来林妹妹：`lib/linmeimei_overlay.dart` 的 `LinMeimeiPet` 同样实现 `handleCommand`，届时只需把 Vision 层同样挂上去即可（接口不变）。

---

## 3. 需要修改的文件

| 文件 | 改动量 | 内容 |
|---|---|---|
| `src/main.py` | +30~50 行 | `_handle_vision_command()` + 常量（触发词）+ 断句分发处 2~3 行调用；语音确认走 `_map_speak` 同款模式（英文/中文跟随角色） |
| `assistant_overlay/lib/jarvis_overlay.dart` | +40~60 行 | `handleCommand` 加 `vision:*` 5 个分支；build Stack 顶层挂 `VisionHudOverlay`（仅 Vision 激活时）；`dispose()` 释放 |

## 4. 需要新增的文件

| 文件 | 内容 |
|---|---|
| `src/vision.py` | `VisionManager`：摄像头帧流（ffmpeg MJPEG 长驻进程，复用 avfoundation 授权路径）、帧推送线程、状态机、`vision:*` 事件发送、`VisionHandTracker` 抽象接口（Phase 1 为 Null/Simulated） |
| `assistant_overlay/lib/vision_overlay.dart` | `VisionMode` 枚举（off/initializing/scanning/handDetected/analyzing/completed/error）、`VisionHudController extends ChangeNotifier`、全屏 HUD 组件（背景帧/扫描网格/扫描线/中央圆环/信息面板/状态文字/手部渲染） |

可选（Phase 2，需用户批准引入依赖）：`src/vision_hands_mediapipe.py`（MediaPipe Hands 实现，约 150MB 依赖）。

---

## 5. Python ↔ Flutter 通信（协议扩展）

沿用 17889 文本行协议（`\n` 分隔，Python `visual.send()` / Flutter `handleCommand` 透传），新增命令：

| 命令 | 方向 | 说明 |
|---|---|---|
| `vision:start` | Python → Flutter | 进入 Vision 模式（全屏 HUD 展开动画） |
| `vision:stop` | Python → Flutter | 退出 Vision 模式（HUD 收缩动画，释放摄像头） |
| `vision:status <STATE>` | Python → Flutter | 状态机同步：`INITIALIZING / SCANNING / HAND_DETECTED / ANALYZING / COMPLETED / ERROR` |
| `vision:frame <base64-jpeg>` | Python → Flutter | 摄像头预览帧（默认 640×360@8~10fps，仅 Vision 激活时推送，覆盖式只留最新帧） |
| `vision:hand <json>` | Python → Flutter | 手部数据：`{"hands":[{"label":"Left","score":0.9,"landmarks":[[x,y,z],...21], ...}]}`，Phase 1 为空/演示 |

说明：
- 帧走 base64 行（约 20~40KB/帧），本地回环带宽 <1MB/s，安全。
- 发送端复用 `JarvisVisual.send()`（已有锁 + 断线重连）；Flutter 端在 TCP 线程解码后经 `VisionHudController` 通知重绘（`notifyListeners`），避免阻塞。
- 与地图协议风格一致：小写冒号前缀 + 空格参数。

---

## 6. Camera 方案

- **复用** `src/camera.py` 的 ffmpeg avfoundation 路径（摄像头 TCC 授权已在控制中心路径下授予，`/camera/snapshot` 可用）。
- `src/vision.py` 内实现**长驻 MJPEG 管线**（不动 `camera.py`）：
  `ffmpeg -f avfoundation -framerate 10 -video_size 640x360 -i 0 -f mjpeg -q:v 6 pipe:1`，Python 按 JPEG SOI/EOI 切帧 → base64 → `vision:frame`。
- **兜底**：管线启动失败 / 摄像头被占用 / 未授权 → 进入 `ERROR` 状态，HUD 显示 `CAMERA OFFLINE`，语音告知，不崩不挂。
- 锁：Vision 激活期间与 `/camera/snapshot` 串行（`VisionManager` 持锁，抓帧请求短暂等待或失败返回）。
- **关闭时**：`terminate()` + `wait(timeout)` + 兜底 `kill`，确保 ffmpeg 不残留。

---

## 7. Hand Tracking 方案

现状：**无 MediaPipe / OpenCV / torch**；Python 仅有 onnxruntime 1.28.0。

- **Phase 1（本次实现，推荐）**：只做**渲染层 + 数据接口预留**。Flutter 端完整实现 21 关键点 + 骨骼连接线 + Glow / 粒子 / 轨迹 / 扫描波纹渲染（CustomPainter）；数据源抽象为 `VisionHandTracker` 接口，Python 端 Phase 1 不推真实数据（HUD 显示 `HAND TRACKING STANDBY`），后续接入零改动。
- **Phase 2（已完成，用户已批准）**：`mediapipe==0.10.35`（官方 Tasks API `HandLandmarker`）→ `src/vision_hands_mediapipe.py` 实现同接口，`VisionManager` 每帧检测 → `vision:hand` 推送（检测到手 → `HAND_DETECTED`，消失回 `SCANNING`）。模型 `models/hand_landmarker.task` 缺失时自动限时下载。未来 OCR / 物检 / 脸检 / 手势控制（握拳→Pause、捏合→Select、指向→Execute）都走同一接口扩展。
- 建议在架构确认时一并决定：**是否接受 Phase 1 无真实手部数据（演示 HUD 完成）**，还是**批准引入 MediaPipe 直接上真实跟踪**。

---

## 8. HUD 方案

全屏暗色 HUD（透明窗口上画全屏半透明黑底，桌面被压暗），层级自下而上：

```
1 Camera Background     帧画面（无帧时暗色底 + 噪声网格）
2 Vision Processing     扫描网格（透视网格）+ 扫描线（上下循环）+ 扫描波纹
3 HUD Layer             中央圆形 Vision Focus Area：双环 + 刻度 + 旋转扫描弧
4 Hand Tracking         21 点 + 骨骼 + glow + trail + scan ripple（Phase 1 渲染层）
5 Information Panels    左 SYSTEM STATUS / 右 VISION DATA / 顶 JARVIS VISION SYSTEM / 底 AI PROCESSING 进度条
6 AI Status             OFF / INITIALIZING / SCANNING / HAND_DETECTED / ANALYZING / COMPLETED / ERROR
```

- 组件复用：`lib/hud_terminal_shell.dart` 的玻璃面板样式；`CustomPainter` 原生绘制（与地图卡片一致，不引入 WebView/three.js）。
- 动画三态：进入（HUD 中心展开：opacity 0→1 + scale 0.85→1）／运行（扫描环/线/粒子循环，60fps Ticker，与摄像头帧率解耦）／退出（收缩 + 释放）。
- 视觉配色沿用 Jarvis HUD：青色 `#64D8FF` 系 + 橙色 `#FFB347` 高亮 + 深黑玻璃。

---

## 9. 状态管理

**Flutter 侧**：
```
VisionMode { off, initializing, scanning, handDetected, analyzing, completed, error }
VisionHudController extends ChangeNotifier
   ├─ mode（状态机）
   ├─ latestFrame (ui.Image? 解码后的摄像头帧)
   ├─ hands（手部数据，Phase 1 空）
   ├─ scanProgress（扫描动画进度）
   └─ error（错误信息）
```
- TCP `vision:*` → `controller.apply(...)` → `ListenableBuilder` 重绘。
- 仅 Vision 激活时创建/挂载组件；`off` 时从 widget 树移除（防泄漏）。

**Python 侧**：`VisionManager` 状态机同步维护，`start() → INITIALIZING → SCANNING`；`stop() → 清理 → OFF`；失败 → `ERROR` + 语音告知。

---

## 10. 生命周期

```
开启视觉扫描/启动视觉模式/打开视觉扫描
  → _handle_vision_command()（本地拦截，不进大模型）
  → 语音确认（Jarvis: "Vision mode activated." 纯英文 Piper；林妹妹中文）
  → VisionManager.start()：起 ffmpeg 帧流 → 发 vision:start / INITIALIZING / SCANNING
  → Flutter 全屏 HUD 展开动画 → 扫描循环

关闭视觉扫描/退出视觉模式
  → 本地拦截 → VisionManager.stop()：停帧线程 → 杀 ffmpeg → 发 vision:stop
  → Flutter HUD 收缩动画 → 组件移除 → 资源释放

资源释放清单（关闭/退出/异常时）：
  ffmpeg 子进程 / 帧推送线程 / AnimationController / Timer / StreamSubscription /
  ui.Image 解码帧 / TCP 帧队列
```

- **打断与唤醒**：Vision 激活期间，唤醒词打断照常工作（主循环只在 `_is_processing` 时检测唤醒词）；Vision 不随打断自动退出，说「关闭视觉扫描」才退出。
- **进程退出**：`VisionManager` 注册 `atexit` 兜底清理。
- **与地图共存**：Vision 激活时隐藏左上角地图卡片与 SYSTEM STATUS 面板（全屏 HUD 场景更干净），退出后恢复——此为默认设计，可调整。

---

## 11. 性能风险与对策

| 风险 | 对策 |
|---|---|
| 摄像头帧带宽/CPU | 限制 640×360@8~10fps、JPEG q≈6；覆盖式只保留最新帧（队列上限 1~2）；Vision OFF 时零推送 |
| ffmpeg 进程泄漏 | `stop()` 必须 terminate+wait+timeout kill，幂等 |
| Flutter 全屏重绘拖累地图 | Vision 组件用 `RepaintBoundary` 隔离；地图卡片在 Vision 激活时隐藏 |
| 线程/回调泄漏 | Python 帧线程用 stop_event 幂等退出；Flutter `dispose()` 释放全部 controller/timer/subscription |
| 摄像头独占冲突 | `VisionManager` 持锁，与 `/camera/snapshot` 串行 |
| base64 解码阻塞 UI | 帧解码在 TCP 回调线程完成，仅 `notifyListeners` 交 UI 重绘 |
| 大模型误触发 | Vision 指令本地拦截，不进 Hermes，避免模型复读/乱接 |

---

## 12. 严格遵守的约束

- 只在 `codex/chat-panel-merged` 工作，不建新分支、不改 main。
- 不修改 `scripts/start.sh`、launchd、杀进程保护（`_enforce_single_instance` / `_is_voice_assistant_pid`）、Hermes/OpenClaw 桥、TTS 引擎选择、地图核心逻辑。
- 不引入大型依赖（Phase 1 零新依赖）。
- 每阶段验证：`python -m py_compile` + `flutter analyze` + 已有测试。

---

## 13. 实现阶段划分（确认后执行）

- **PHASE 2 视觉设计**：`VISION_UI_DESIGN.md`（布局/动画/状态/层级，结合 Flutter 组件）。
- **PHASE 3 Flutter 工程师**：`vision_overlay.dart`（HUD + 状态机 + 手部渲染层）→ 挂入 `jarvis_overlay.dart`。
- **PHASE 4 动画工程师**：进入/运行/退出三态动画、扫描线/环/粒子/波纹。
- **PHASE 5 Backend**：`src/vision.py` + `main.py` 指令入口。
- **PHASE 6 Integration**：语音触发 ↔ TCP ↔ overlay 全链路。
- **PHASE 7 QA**：py_compile / flutter analyze / 已有测试 / 资源释放检查。
- **PHASE 8 Code Review**：`git diff` / `git diff --check`，回滚越界改动。
- **PHASE 9 最终验证 + 提交**：commit `feat: add jarvis vision mode` → push `fork codex/chat-panel-merged`。

---

## 14. 待确认决策（请回复）

1. **手部跟踪 Phase 1**：接受「渲染层 + 接口预留（HUD 显示 STANDBY，无真实骨骼）」？还是批准安装 MediaPipe（约 150MB）直接上真实 21 点跟踪？
2. **摄像头预览**：默认 640×360@8~10fps 是否接受？（HUD 动画 60fps 不受影响）
3. **Vision 全屏形态**：默认「全屏暗色 HUD 覆盖，隐藏地图卡片与 SYSTEM STATUS」是否 OK？
4. **Vision 期间对话**：默认「Vision 激活期间照常对话，只有说关闭才退出」是否 OK？
