# VISION_UI_DESIGN.md

> Jarvis Vision Mode 视觉设计 — PHASE 2 输出
> 分支：`codex/chat-panel-merged` ｜ 设计基于实际 Flutter 组件（CustomPainter 原生绘制）

---

## 1. 设计语言

- **基调**：Iron Man Jarvis 全息 HUD —— 深黑玻璃、青色主光（`#64D8FF` 系）、橙色高亮（`#FFB347`）、克制机械感。
- **与现有体系一致**：复用 `HudTerminalShell`（SYSTEM STATUS 同款玻璃面板）、`CustomPainter` 原生绘制（同地图卡片），不引入 WebView/three.js。
- **空间层次**（自下而上）：Camera 背景 → 扫描网格 → 中央聚焦环 → 手部层 → 信息面板 → 状态文字。

## 2. 屏幕布局（全屏 16:9）

```
┌────────────────────────────────────────────────────┐
│  JARVIS VISION SYSTEM          ● VISION ACTIVE    │  ← 顶栏：标题 + 状态灯
│                                                   │
│  ┌─────────────┐         ◯          ┌───────────┐ │
│  │ SYSTEM      │    中央 Vision      │ VISION    │ │
│  │ STATUS      │    Focus Area       │ DATA      │ │
│  │ CAMERA  OK  │   (环形扫描HUD)      │ SCAN 47%  │ │
│  │ FPS 10      │                    │ RES 640x360│ │
│  │ STATE SCAN  │                    │ HANDS -    │ │
│  │ HANDS -     │                    │ MODEL -    │ │
│  └─────────────┘                    └───────────┘ │
│                                                   │
│        SCANNING · HAND TRACKING STANDBY           │  ← 中央底部状态大字
│                                                   │
│  AI PROCESSING  ████████████░░░░░░░░  87%         │  ← 底部处理进度条
└────────────────────────────────────────────────────┘
```

- 左面板（固定宽 `screenWidth/7`，左 60px，垂直居中偏上）：`HudTerminalShell(title: 'SYSTEM STATUS')`。
- 右面板（同宽，右 60px）：`HudTerminalShell(title: 'VISION DATA')`。
- 中央 Focus Area：直径 `screenHeight * 0.42`，屏幕中心。
- 底部进度条：屏幕宽 40%，底部 8%，渐变青色填充。
- 顶栏：标题 + 右上状态灯（呼吸动画）。

## 3. 状态机与文案

| 状态 | 主文案 | 副文案 |
|---|---|---|
| INITIALIZING | `INITIALIZING...` | `CAMERA CONNECTED` → `VISION MODEL READY` |
| SCANNING | `VISION ACTIVE` | `SCANNING ENVIRONMENT` |
| HAND_DETECTED | `HAND DETECTED` | `LEFT/RIGHT HAND LOCKED` |
| ANALYZING | `ANALYZING` | `AI PROCESSING FEED` |
| COMPLETED | `COMPLETED` | `SCAN FINALIZED` |
| ERROR | `VISION ERROR` | `CAMERA OFFLINE · RETRY` |

Phase 1 无真实手部数据时，SCANNING 副文案显示 `HAND TRACKING STANDBY`（接口已预留）。

## 4. 动画设计（三态）

- **进入**（`vision:start`）：全屏黑底 opacity 0→0.92（400ms easeOut）+ 中央环 scale 0.8→1 + 扫描线从顶部扫下 → 面板左右滑入（250ms，错峰 50ms）。
- **运行**（60fps Ticker，与摄像头帧率解耦）：
  - 外环刻度旋转 30s/圈（复用地图「缓缓」节奏）、内环 8s/圈反向；
  - 扫描弧 2.4s/圈 顺时针，中央十字瞄准线脉动；
  - 横向扫描线 3s 上下往返 + 拖尾辉光；
  - 透视网格横向漂移（模拟空间感）；
  - 底部 AI PROCESSING 进度条 4s 循环（0→100%）。
- **退出**（`vision:stop`）：反向收缩（250ms easeIn）+ 扫描线停 → opacity 归零 → 组件从树中移除，摄像头释放。

## 5. 组件拆分（Flutter）

| 组件 | 类型 | 职责 |
|---|---|---|
| `VisionMode` | enum | off/initializing/scanning/handDetected/analyzing/completed/error |
| `VisionHudController` | ChangeNotifier | 状态机、摄像头帧（`ui.Image`）、手部数据、进入/退出动画标志；`applyCommand()` 消费 `vision:*` |
| `VisionHudOverlay` | StatefulWidget | 全屏容器 + 进入/退出动画 + 组装各层 |
| `_VisionBackdropPainter` | CustomPainter | 暗色渐变底 + 透视扫描网格 |
| `_ScanLinePainter` | CustomPainter | 横向扫描线 + 辉光拖尾 |
| `_CenterHudPainter` | CustomPainter | 中央环：刻度环、旋转弧、十字线、角标框 |
| `_HandOverlayPainter` | CustomPainter | 21 关键点 + 骨骼连线 + glow（数据驱动，Phase 1 常空） |
| `_StatusLine` | StatelessWidget | 主/副文案大字 |
| 面板 | `HudTerminalShell` | 左 SYSTEM STATUS / 右 VISION DATA |

## 6. 手部渲染（Phase 1 渲染层 + 接口）

- 数据模型 `VisionHand { label, score, landmarks: List<Offset> (21) }`，坐标归一化（0~1）。
- 骨骼拓扑使用 MediaPipe 标准 21 点连接表（拇指/食指/中指/无名指/小指 + 掌部）。
- 渲染：连线 `#64D8FF` alpha 0.9（粗 1.5 + glow 粗 4 alpha 0.2）；关键点实心圆 + 外发光；检测到瞬间在掌心打一个扩散波纹。
- 数据为空 → 不绘制，副文案显示 `HAND TRACKING STANDBY`。

## 7. 关闭释放

- `VisionHudController.dispose()`：释放 `ui.Image` 帧、取消未完成解码。
- `VisionHudOverlay.dispose()`：释放全部 AnimationController/Ticker。
- 退出动画完成后 `controller.onExitDone()` → mode=off → 组件移除。
