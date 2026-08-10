# COMPUTER_AGENT_ARCHITECTURE.md — Jarvis Computer Control System 架构设计

> 状态：待确认（本阶段仅分析，未修改任何代码）
> 分支：`codex/chat-panel-merged`
> 目标：让 Jarvis 用自然语言安全控制 macOS（应用/键盘/鼠标/截图/文件），
> 作为**独立能力模块**接入，不污染 Jarvis 核心、不碰启动监督与 Vision。

---

## 1. 当前 Agent 架构（现状核查）

```
唤醒词(本地 sherpa-onnx) → ASR(sense-voice/离线) → 主循环识别结果
   ├─ 系统级关键词：退出/重启/打断（本地消费）
   ├─ 地图指令  → _handle_map_command   （本地拦截，不进大模型）
   ├─ 视觉指令  → _handle_vision_command（本地拦截，不进大模型）
   └─ 普通对话  → _on_recognized
         └─ bridge（engine=hermes，OpenAI 兼容流式 chat）
              → 增量 TTS 合成 → 角色 voice（Jarvis 英音 / 林妹妹中音）
```

- 主脑：`assistants.json` 顶层 `engine: hermes`；`src/hermes_bridge.py`（或 `openclaw_bridge.py`）提供 **流式 chat，无工具调用机制**；角色提示词/记忆由 Hermes profile 管理，项目不持有。
- 角色系统：`src/assistants/` 提供 `visual / tts / feedback` 三组件，`get_manager()` 单例；当前 Jarvis / Lin Meimei。
- 本地能力模块的既有范式（Computer Agent 应镜像）：
  - `src/vision.py`：`VisionManager` 单例 + 后台 worker 线程 + `bind_visual(visual)` + 经角色 visual 的 TCP `17889` 推送 `vision:*`；
  - `main.py` 主循环：`_xxx_like()` 流式预判 + `_handle_xxx_command()` 本地拦截（消费后不进大模型）+ 角色语言确认口播 + 去重窗口。
- 环境事实：venv **未装** pyobjc / pyautogui（`Quartz/ApplicationServices/Vision/objc` 均 MISSING）；DeepSeek API 无图像输入；本机无 Xcode（原生编译仅 CI，但 `swiftc` 走 Command Line Tools 可用）。

## 2. Computer Agent 接入位置

**结论：`src/computer/` 独立包 + main.py 主循环一个拦截钩子（第 3 处本地拦截），与地图/视觉同级，不动 bridge、不动 Agent 系统。**

```
main.py 主循环
  ├─ _handle_map_command    （已有）
  ├─ _handle_vision_command （已有）
  ├─ _handle_computer_command（新增，Phase 5）：
  │     intent 预判(_computer_like) → ComputerAgent.handle(text)
  │        ├─ 权限检查（PermissionManager）
  │        ├─ 风险确认（高风险 → 语音/通知确认，等用户确认）
  │        ├─ CommandExecutor（异步 worker 线程，不阻塞语音主循环）
  │        └─ 结果 → 角色语言口播 + overlay 文本 + 操作日志
  └─ _on_recognized（普通对话，不进）
```

- 接入点最小化：只在主循环加一个 `if self._handle_computer_command(...)` 分支（约 15 行，参照视觉模式写法）；所有逻辑在 `src/computer/` 内。
- **不新增 Agent**：Computer 是 Jarvis 的「能力（Capability）」，不创建第三个角色，不写 `assistants.json`。
- **异步**：`ComputerAgent.handle()` 只做意图解析与入队，实际执行放 `ThreadPoolExecutor(max_workers=1)` 后台线程；语音/视觉/HUD 完全不受影响。

## 3. Tool 调用设计

**原则：Jarvis 大脑（LLM）不能直接碰系统；所有系统操作收敛到 Tool 层，统一 Action 格式。**

统一 Action（`src/computer/action.py`）：

```python
Action(
    action: str,        # "open_app" | "close_app" | "switch_app" | "type_text"
                        # "press_keys" | "mouse_click" | "mouse_double_click" |
                        # "mouse_move" | "scroll" | "take_screenshot" |
                        # "file_read" | "file_create" | "file_move" | "file_rename" |
                        # "search" | "get_screen_state" | "exec_command"(受限)
    target: str|dict,   # 语义目标：app 名 / UI 元素描述 / 文件路径 / 文本 / 快捷键
    params: dict,       # 附加参数（如 double_click、scroll_amount、confirm 等）
    risk: Risk,         # auto | confirm | deny
    id: str,            # 幂等/日志追踪
)
```

- **语义目标优先，坐标兜底**：`target` 是「描述」，不是坐标。坐标只在「元素定位 → 命中后」由 Screen Understanding Layer 算出。
- Tool 命名空间（大脑可读）：`computer.open_application / computer.close_application / computer.type_text / computer.press_keys / computer.click / computer.take_screenshot / computer.execute_action / computer.list_apps / computer.screen_state`。
- **Phase 4 大脑接入（两种路径，推荐 A）**：
  - A（最小风险，与项目风格一致）：`ComputerAgent.parse()` 本地意图解析兜底 + 「未知指令」时向现有 bridge 发一次**约束性解析请求**（system 提示：只输出 JSON Action），拿 JSON 后仍走本地 Permission/Executor。不修改 bridge 协议。
  - B（预留）：若后续 Hermes/OpenClaw 支持 function calling，给 bridge 增加可插拔 tool 描述；不动现有流式对话链路。本阶段只留接口。

## 4. 权限设计（Permission Manager）

macOS TCC 权限与用途：

| 权限 | 用途 | 获取方式 |
|---|---|---|
| **辅助功能 Accessibility** | UI 元素树读取、系统级键鼠事件 | 系统设置→隐私与安全→辅助功能（AXIsProcessTrusted） |
| **屏幕录制 Screen Recording** | 截图/屏幕内容 | 系统设置→隐私与安全→屏幕录制 |
| **自动化 Automation** | AppleScript 控制各目标 App | macOS 首次控制某 App 时弹窗授权（按 App 授权） |

- `permission_manager.py` 职责：
  1. **状态探测**：启动/每次指令前探测三类权限（`osascript` 探测 System Events、`screencapture` 试写、TCC 服务查询），输出结构化状态；
  2. **引导**：未授权时给用户语音 + overlay 提示 + `open "x-apple.systempreferences:..."` 直达设置页；
  3. **风险确认队列**：高风险 Action 挂起，等待用户确认（确认接口 `approve(id)` / `deny(id)`，Phase 5 由语音循环或 overlay 按钮消费；本模块内先提供阻塞式 CLI/回调 + notify_control_center 通知）。

## 5. macOS 控制方案（技术选型）

对候选方案的评估：

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| **AppleScript/osascript**（System Events） | 零依赖、应用/窗口/键盘/点击/UI 元素树全支持；权限按 App 弹窗 | 元素遍历较慢；部分 App 不暴露 AX 树 | **主方案**（默认零新依赖） |
| **Accessibility API（AXUIElement）** | 语义定位最标准（role+title+position） | 需 PyObjC（未安装）或走 System Events 桥 | 语义层首选；本阶段经 System Events 暴露，**PyObjC 作可选增强** |
| **PyAutoGUI** | 简单 | 纯坐标、同样要辅助权限、多一层依赖 | 仅作**兜底**（不默认引入） |
| **PyObjC** | AX + CGEvent + Vision OCR 最完整 | 依赖较大（需安装 pyobjc） | 可选增强；OCR 阶段再评估 |
| `open` / `osascript` 应用控制 | 打开/关闭/切换窗口稳定 | - | 应用控制直接用 |

**默认组合（不新增任何依赖）**：
- 应用控制：`open -a <app>` / `osascript`（quit、activate、窗口切换、frontmost）；
- 键盘：System Events `keystroke` / `key code`（组合键如 `command down` + key）；
- 鼠标：System Events `click at {x,y}`（坐标由语义定位产出）+ 必要时 `cliclick`-类兜底（不引入，先用 System Events）；
- 截图：系统自带 `screencapture -x`；
- 屏幕理解：System Events **AX 元素树**（按钮/窗口/输入框/菜单，取 role+title+position）作为主通道；OCR 为增强（见 §6）。

## 6. Vision 融合（Screen Understanding Layer）

**核心原则：不做 `click(300,500)`，做「语义目标 → 实时解析 → 坐标」。**

```
Voice/Text intent
   → Action(target="发送按钮")
        → ScreenAnalyzer.locate(target)
             ├─ 主通道：AX 元素树（当前前台 App 的 UI 元素，按 role/title/描述匹配）
             │     命中 → 取 position/size 中心 → 交给 Mouse/Keyboard Controller
             └─ 备用：截屏 + 本地 OCR（macOS Vision VNRecognizeTextRequest，
                     走一次性编译的 Swift 助手，参照 notify 桥的独立小助手思路；
                     或可选 pyobjc-framework-Vision）→ 文本框命中 → 坐标
   → CommandExecutor 执行 → 结果校验（可选：二次 AX 快照比对）
```

- **与现有 Camera Vision 完全隔离**：新增 `computer` 命名空间（`computer:*`），不改 `vision:*` 协议、不改 `src/vision.py`、不碰摄像头链路。
- **OCR 现状说明**：DeepSeek 无图像输入，无法用现有 API 做图片理解；因此屏幕理解**本地化**（AX 树 + 本地 OCR）。架构上预留 `ScreenUnderstandingBackend` 接口，未来接入支持图像的模型（如 GPT-4o 视觉 / 本地 VL）时只换实现。
- **overlay 展示（可选，Phase 3+）**：截图可经 control_center 或新增 overlay 面板显示，点击目标可画框高亮；协议沿用「一行 JSON」风格，但挂 `computer:` 前缀。

## 7. 安全方案（必须）

- **风险分级**：

| 级别 | 示例 | 策略 |
|---|---|---|
| `auto`（低风险） | 打开/关闭应用、切换窗口、截图、搜索、输入文字、移动鼠标/单击 | 直接执行，写日志 |
| `confirm`（高风险） | **删除/覆盖文件**、执行 `sudo`/shell、修改系统设置、发送邮件、退出未保存应用、批量文件移动 | **必须语音/通知确认**；未确认不执行 |
| `deny`（默认拒绝） | 未知危险命令、写系统目录、下载执行、提权操作 | 直接拒绝并解释 |

- 黑名单：`rm -rf` 根目录、`/etc`、`sudo` 无确认、`shutdown/reboot`、任意 URL 下载即执行。
- **确认交互**：高风险 Action → `notify_control_center` 弹通知 + 语音询问（角色语言）→ 用户在连续对话里回答 yes/no/确认/取消 → `approve/deny` 回调继续/终止。确认状态带 60s 超时自动拒绝。
- **可撤销/可审计**：文件操作先做 dry-run 输出目标路径清单再确认；所有操作 JSON 落盘（§8 日志）。
- **权限最小化**：Computer Agent 只以当前用户权限运行；禁止提权自启。

## 8. 文件结构设计

```
src/computer/                     # 独立能力包（镜像 src/vision.py 的单例+线程范式）
  __init__.py                     # get_computer_agent() 单例 + 常量
  action.py                       # Action 数据类 / Risk 枚举 / 序列化
  intent_parser.py                # 自然语言 → Action（本地规则；Phase 4 接大脑 JSON）
  permission_manager.py           # TCC 状态探测 / 引导 / 风险确认队列
  command_executor.py             # Action 派发 + ThreadPoolExecutor(1) 异步执行
  application_controller.py       # 打开/关闭/切换/置前（open + osascript）
  keyboard_controller.py          # 输入文字 / 快捷键 / 组合键（System Events）
  mouse_controller.py             # 移动 / 单击 / 双击 / 滚动（System Events，坐标由分析层给出）
  screen_capture.py               # screencapture 封装 + 截图目录 + 状态
  screen_analyzer.py              # 语义定位：AX 元素树匹配 + OCR 备用（后端接口预留）
  file_manager.py                 # 读 / 建 / 移 / 重命名（shutil + 确认 + dry-run）
  action_log.py                   # 操作日志（JSON lines → logs/computer_agent.log）
  apple_script.py                 # osascript 封装（System Events 统一入口，带超时/降级）
```

- main.py 变更（Phase 5，约 15 行）：`_computer_like()` 流式预判 + `_handle_computer_command()` 拦截 + 去重窗口（复用视觉模式范式）。
- **禁止触碰**：`scripts/start.sh`、launchd、进程保护、`src/main.py` 的既有功能路径、`src/vision.py`、`assistants.json`、Agent 系统。

## 9. 开发阶段（确认后执行，每阶段验证）

| Phase | 内容 | 验收（python -m py_compile + 功能） |
|---|---|---|
| 1 | 包骨架 + `application_controller`：打开/关闭 App、切换窗口；Action/日志/权限探测最小版 | 「打开Chrome」→ Chrome 启动；「关闭Chrome」→ 退出；日志有记录 |
| 2 | `keyboard_controller` + `mouse_controller` + 语义定位（AX 元素树定位前台 App 按钮/输入框） | 「输入xxx」「按 Command+Space」；点击「发送」按钮（语义命中，非写死坐标） |
| 3 | `screen_capture` + `screen_analyzer`（截图 + AX 树 + OCR 备用） | 截图成功；「查看屏幕」→ 截图并可描述前台窗口元素 |
| 4 | 大脑 Tool 接入（路径 A：约束 JSON 解析；路径 B 预留） | 未知自然语言指令可被解析成合法 Action 并执行 |
| 5 | 语音接线（main.py 拦截钩子）+ 风险确认交互 + overlay 文本 | 语音全流程：打开/输入/点击/文件移动/高危确认 |

- 测试清单（每阶段）：打开 Chrome / 打开 Terminal / 输入文字 / 快捷键 / 截图 / 点击语义按钮 / 文件移动确认 / 权限未授权引导。
- 异步与性能：所有执行在后台线程；单 Action 有超时（默认 20s）；失败不阻塞语音主循环。

## 10. Git 与最终交付

- 全程在 `codex/chat-panel-merged`，**不创建新分支、不碰 main**。
- 最终提交：`feat: add jarvis computer control agent` → push origin。
- 完成后生成 `COMPUTER_AGENT_FINAL_REPORT.md`（架构/文件修改/macOS 方案/Tool/权限/Vision 融合/测试结果/提交记录）。
- 与既有 Vision/地图能力完全并行，互不影响；若 Phase 验证发现需动 `scripts/start.sh` 等禁止项 → 停下来与用户确认，不擅自改。
