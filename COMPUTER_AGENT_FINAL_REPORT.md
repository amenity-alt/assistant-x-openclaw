# COMPUTER_AGENT_FINAL_REPORT — Jarvis Computer Control System

> 分支：`codex/chat-panel-merged` ｜ 状态：✅ 全部 5 个 Phase 完成、功能验证通过、已提交推送
> 目标：让 Jarvis 用自然语言安全控制 macOS（应用 / 键盘 / 鼠标 / 截图 / 屏幕理解 / 文件预留）

---

## 1. 架构

独立能力模块（Capability），不新增 Agent、不污染 Jarvis 核心、不碰启动监督：

```
语音识别 → main.py 主循环
   ├─ 系统级关键词（已有）
   ├─ 地图指令   _handle_map_command    （已有）
   ├─ 视觉指令   _handle_vision_command （已有）
   ├─ 电脑指令   _handle_computer_command（新增，Phase 5）
   │     _computer_like 流式预判 → ComputerAgent.handle(text)
   │        ├─ 本地意图解析 intent_parser（确定性规则）
   │        ├─ 兜底：大脑约束 JSON 解析 brain_parser（独立会话，不污染语音历史）
   │        ├─ 权限探测 PermissionManager（辅助功能 TCC）
   │        ├─ CommandExecutor（ThreadPoolExecutor(1) 异步执行，不阻塞语音主循环）
   │        └─ 结果 → 角色语言口播（贾维斯英文 / 林妹妹中文）+ overlay 文本 + JSON 日志
   └─ 普通对话 → 大模型（不进）
```

核心原则：**LLM 永远不能直接碰系统**——大脑只产出结构化 Action，执行一律走本地 Permission/Executor。

## 2. 文件修改

| 文件 | 说明 |
|---|---|
| `src/main.py` | 仅加 3 处：流式预判、主循环拦截分支、`_computer_like/_handle_computer_command/_computer_speak`（约 +124 行，镜像地图/视觉范式） |
| `src/computer/__init__.py` | `ComputerAgent` 入口：`handle()/bind_bridge()/execute_action()/permissions()` + 单例 |
| `src/computer/action.py` | `Action` 数据模型 / `Risk` 三级风险 / 动作→风险默认表 |
| `src/computer/intent_parser.py` | 本地意图解析：应用控制 / 输入 / 按键 / 语义点击 / 截图 / 查看屏幕 / 列表 |
| `src/computer/brain_parser.py` | 大脑约束 JSON 解析（Phase 4，独立 `computer-parse-*` 会话 + 白名单 + 20s 超时） |
| `src/computer/application_controller.py` | `open -a` + osascript：打开/关闭/切换；中文别名→真实应用名（微信→WeChat 等） |
| `src/computer/keyboard_controller.py` | 输入文字（ASCII 直打 / CJK 剪贴板粘贴并恢复）、组合键（key code + modifiers） |
| `src/computer/mouse_controller.py` | CGEvent（ctypes CoreGraphics）移动/单击/双击/滚动，System Events 兜底 |
| `src/computer/screen_analyzer.py` | AX 语义定位（前台 App 元素树，role+title+desc → 中心坐标），`describe_screen` |
| `src/computer/ax_walker.py` | Accessibility C API（AXUIElement）轻量封装——语义定位主通道，230 元素 ~0.1s |
| `src/computer/screen_capture.py` | 系统 `screencapture`，截图存 `logs/screenshots/`（已 gitignore） |
| `src/computer/screen_ocr.py` | 本地 OCR 备用：一次性 swiftc 编译 Vision 助手，缓存 `~/Library/Caches/jarvis-computer/ocr_helper` |
| `src/computer/permission_manager.py` | 辅助功能权限探测 + 引导（系统设置直达） |
| `src/computer/command_executor.py` | Action 派发 + 异步执行 + 操作日志 + 结果回调 |
| `src/computer/action_log.py` | JSON lines 审计日志 `logs/computer_agent.log` |
| `src/computer/apple_script.py` | osascript 统一封装（超时/转义/降级） |
| `.gitignore` | 追加 `logs/screenshots/` |

未修改：`scripts/start.sh`、launchd、杀进程保护、`assistants.json`、Agent 系统、Vision/地图模块、bridge 协议。

## 3. macOS 控制方案（零新依赖）

| 能力 | 方案 |
|---|---|
| 应用 | `open -a` / Apple Events `quit` / `activate`；System Events 菜单退出兜底 |
| 键盘 | System Events `keystroke` / `key code` + modifiers（Command/Shift/Option/Ctrl） |
| 鼠标 | CoreGraphics CGEvent（ctypes 直调系统框架）；`click at` 兜底 |
| 屏幕 | `screencapture -x` |
| 语义定位 | Accessibility C API（AXUIElement）批量取 role/title/desc/value/position/size → 中心坐标 |
| OCR 备用 | macOS Vision（VNRecognizeTextRequest，swiftc 一次编译缓存，中英双语） |

## 4. Tool 设计

统一 `Action(action, target, params, risk)`；语义目标优先，坐标只由语义定位层产出。

- 白名单动作：`open_app / close_app / switch_app / type_text / press_keys / click_element / double_click_element / take_screenshot / get_screen_state / list_apps / scroll / mouse_move`
- 大脑输出校验：动作名归一化 + 白名单；`exec_command` 等任意命令一律拒绝（单测覆盖）
- 风险分级：以上均为 `auto`（低风险，直接执行并写日志）；文件删除/sudo 等留 `confirm/deny` 占位（Phase 预留）

## 5. 权限设计

- 辅助功能（Accessibility）：启动/指令前探测（`UI elements enabled`），未授权给出中文引导 + 直达设置页，拒绝执行
- 屏幕录制（Screen Recording）：截图失败返回引导提示
- 自动化（Automation）：osascript 首次控制某 App 时由系统弹窗授权
- 权限最小化：只以当前用户权限运行，禁止提权

## 6. Vision 融合

- 与 Camera Vision 完全隔离：新增 `computer` 命名空间，不改 `vision:*` 协议、不碰 `src/vision.py`
- 屏幕理解本地化：AX 树为主通道 + 本地 OCR 备用（DeepSeek 无图像输入，不依赖外部视觉 API）
- 预留 `get_screen_state` 结构化输出（app/window/按钮/输入框/文字层），未来接图像模型只需换后端

## 7. 测试结果（本机实跑，全部通过）

| 项 | 结果 |
|---|---|
| `python -m py_compile`（全部改动文件 + main.py） | ✅ |
| 意图解析单测（中英/敬语/负例 40+ 条） | ✅ |
| 打开/关闭/切换 计算器、文本编辑、备忘录 | ✅（`pgrep` 验证进程状态） |
| 输入文字（ASCII + 中文）到 TextEdit 文档 | ✅（读回文档验证） |
| 组合键 `Command+A/C` 复制 | ✅（剪贴板验证） |
| 语义点击 Finder「种类/大小/名称」、双击「修改日期」 | ✅（日志 ok=True，真实坐标点击） |
| 不存在的按钮 → 优雅失败并提示 | ✅ |
| AX 语义定位性能 | ✅ 230 元素 0.11s |
| 截图 + 查看屏幕（AX 描述 + OCR 文字层） | ✅（截图 2MB，OCR 识别到菜单/系统设置等文字） |
| 列出运行中应用 | ✅ |
| 大脑解析「把计算器打开」→ 执行 | ✅（2.5s，独立会话） |
| 非指令「今天天气怎么样」→ 不消费 | ✅ |
| 大脑输出 `exec_command` 白名单拒绝 | ✅（单测） |
| 语音钩子（模拟）：英文口播 `Opened Calculator.` / 中文口播 `已打开 备忘录。` / 去重窗口 | ✅ |

## 8. Git 提交记录

| commit | 内容 |
|---|---|
| `eed48ea` | phase 1: application control（+架构文档） |
| `f04693d` | phase 2: keyboard, mouse & semantic click |
| `0731081` | phase 3: screenshot & screen understanding |
| `9165395` | phase 4: brain tool integration |
| `1ddea47` | phase 5: voice integration |

全部推送 `origin codex/chat-panel-merged`，未创建新分支、未动 main。

## 9. 使用说明

重启语音助手（`scripts/start.sh` 或现有重启指令）后生效：

- 「打开Chrome / 打开微信 / 打开终端」→ 打开应用
- 「关闭计算器」→ 退出应用
- 「输入 hello」「按下 Command+Space」「点击发送」「双击图标」
- 「截图」「查看屏幕」「现在开着什么」
- 未安装 Chrome 时会给出清晰失败提示；已装则同一条逻辑直接生效
