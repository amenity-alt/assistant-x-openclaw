# VISION_FINAL_REPORT.md

> Jarvis Vision Mode（视觉扫描模式）最终报告 — PHASE 9
> 分支：`codex/chat-panel-merged`

## 1. 当前架构
- Python 后端 `src/main.py`（唤醒词/声纹/SenseVoice ASR/指令分发/Hermes 桥/增量 TTS）+ Flutter 透明悬浮 Overlay（TCP 127.0.0.1:17889 文本行协议）+ `scripts/start.sh` 唯一监督者。
- Vision 以 **Capability** 落地：Python `VisionManager`（摄像头帧流 + 状态机 + 事件推送），Flutter `VisionHudOverlay`（全屏 HUD），挂载在现有 `JarvisAgentVisual` 内，不新增 Agent。

## 2. 新增模块
- `src/vision.py`：VisionManager 单例 + `VisionHandTracker` 抽象接口（Phase 1 空实现，Phase 2 可接入 MediaPipe）。
- `assistant_overlay/lib/vision_overlay.dart`：VisionMode 状态机、VisionHudController、全屏 HUD（扫描网格/扫描线/中央聚焦环/手部渲染/信息面板/状态文字/底部进度）、进入/运行/退出三态动画。

## 3. 修改文件
- `src/main.py`：`_handle_vision_command()` 本地拦截（开启/关闭视觉扫描，不进大模型）+ `_vision_like()` 流式防回声 + 角色切换时关闭/重绑 Vision。
- `src/assistants/jarvis/visual.py`、`src/assistants/custom_visual.py`：`send(message, quiet=False)` 支持帧推送不打日志。
- `assistant_overlay/lib/jarvis_overlay.dart`：`vision:*` 命令分发、全屏 HUD 顶层挂载、Vision 激活时隐藏地图卡片与 SYSTEM STATUS、dispose 释放。
- `assistant_overlay/lib/agent_overlay.dart`、`lib/tcp_server.dart`：大帧日志截断（防刷屏）。

## 4. Vision 工作流程
```
开启视觉扫描/启动视觉模式/打开视觉扫描
 → _handle_vision_command（本地拦截）→ VisionManager.start()（后台线程）
 → TCP: vision:start → INITIALIZING → SCANNING → vision:frame (640×360@10fps)
 → Flutter 全屏 HUD 展开 → 扫描循环 → 口播确认（Jarvis 英文 / 林妹妹中文）
关闭视觉扫描/退出视觉模式 → VisionManager.stop() → 杀 ffmpeg → vision:stop
 → HUD 收缩淡出 → 组件移除 → 摄像头/帧/线程全部释放
```

## 5. Voice 触发方式
- 触发词：`开启视觉扫描`、`启动视觉模式`、`打开视觉扫描`（含"视觉"）。关闭词：`关闭视觉扫描`、`退出视觉模式`。
- 与地图指令同级本地拦截，15s 去重防 ASR 回声；确认口播复用 `_map_speak` 模式（播报期间 `_is_processing` 防麦克风回声）。
- 语言跟随角色：Jarvis 纯英文（Piper 英音）、林妹妹中文（MeloTTS）。

## 6. Camera 方案
- 复用 `camera.py` 的 ffmpeg avfoundation 授权路径；`VisionManager` 内长驻 MJPEG 管线 `640×360@10fps`（`imageio-ffmpeg` 静态二进制）。
- 软失败：ffmpeg 缺失/摄像头不可用/未授权 → `vision:status ERROR` → 退出，不影响语音主流程。
- 关闭时 terminate+wait+timeout kill；start/stop/start 竞态用 ident 守卫 + 局部 proc 清理。

## 7. Hand Tracking 方案
- Phase 1：渲染层 + 接口预留。`VisionHandTracker` 抽象（`start/process/stop`），当前为空实现；HUD 显示 `HAND TRACKING STANDBY`。
- Flutter 已实现 21 关键点 + MediaPipe 标准骨骼拓扑 + glow + 掌心波纹渲染，`vision:hand` 协议已定义，Phase 2 接入 MediaPipe 只需实现 `process()` 返回同结构 payload。

## 8. HUD 方案
- 全屏暗色 HUD：摄像头背景（压暗 + 青色染色 + 暗角）→ 透视扫描网格 + 扫描线 → 中央圆形聚焦环（刻度环/旋转弧/十字线/角标框）→ 手部层 → 左 SYSTEM STATUS / 右 VISION DATA 玻璃面板 → 顶栏 JARVIS VISION SYSTEM → 状态大字 → 底部 AI PROCESSING 进度条。
- 配色沿用 Jarvis：青色 `#64D8FF` + 橙色 `#FFB347` 高亮；状态色：ERROR 红 / HAND 橙 / COMPLETED 绿。

## 9. Animation 方案
- 进入：淡入 400ms + 中央环缩放展开；运行：扫描线 3s、旋转弧 2.4s、进度 4s 循环（60fps Ticker，与帧率解耦）；退出：250ms 收缩淡出后移除组件。
- 全部 Flutter 原生 CustomPainter，无 WebView/three.js/新依赖。

## 10. Python ↔ Flutter 通信
- 沿用 17889 文本行协议，新增：`vision:start`、`vision:stop`、`vision:status <STATE>`、`vision:frame <base64-jpeg>`、`vision:hand <json>`。

## 11. 性能处理
- 帧 640×360@10fps、JPEG q6、覆盖式只留最新帧（Flutter 解码中丢帧）；帧推送 quiet 模式不打日志、TCP/overlay 日志截断。
- Vision OFF 时零推送；RepaintBoundary 隔离全屏层；退出/角色切换时释放 ffmpeg、帧线程、ui.Image、AnimationController、Listener。
- 摄像头与 `/camera/snapshot` 通过单例锁语义串行（Vision 独占期间 snapshot 软失败）。

## 12. 测试结果
- `python -m py_compile`：src/main.py、src/vision.py、两个 visual.py 全部通过。
- `flutter analyze`：无 error；64 项均为项目原有告警（avoid_print / 旧 lib/overlay 树 / 既有未用字段）；新文件 `vision_overlay.dart` 0 告警。
- Vision 指令逻辑测试（不触摄像头）：开启/关闭/重复去重/非视觉文本放行/中英文口播跟随，全部通过。
- 未改动 `scripts/start.sh`、launchd、杀进程保护、Hermes/OpenClaw 桥、TTS 引擎、地图核心逻辑（git diff 核对）。

## 13. Git commit
- 提交信息：`feat: add jarvis vision mode`

## 14. Git push
- `git push origin codex/chat-panel-merged`（fork: amenity-alt/assistant-x-openclaw）
