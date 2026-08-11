# CODEX_AGENT_ARCHITECTURE.md — Jarvis Coding Agent（Codex CLI 接入）架构设计

> 状态：待确认（本阶段仅分析，未修改任何代码）
> 分支：`codex/chat-panel-merged`
> 目标：让 Jarvis 通过语音/文本调用**本机 Codex CLI**，完成代码分析、修改、测试、审查与工程任务，
> 作为独立能力模块接入，不污染 Jarvis 核心、不碰启动监督与既有 Vision/地图/Computer 系统。

---

## 1. 当前 Jarvis 架构（现状核查）

```
唤醒词(本地 sherpa-onnx) → ASR → 主循环识别结果
   ├─ 系统级关键词（退出/重启/打断）
   ├─ 地图指令   _handle_map_command      （本地拦截）
   ├─ 视觉指令   _handle_vision_command   （本地拦截）
   ├─ 电脑指令   _handle_computer_command （本地拦截，Phase 1-5 已完成）
   └─ 普通对话   → bridge（engine=hermes）→ 大模型 → TTS（角色 voice）
```

- 本地能力模块既有范式（Coding Agent 镜像）：
  - `src/vision.py` / `src/computer/`：单例 + 后台 worker 线程 + 主循环拦截钩子
    （`_xxx_like()` 流式预判 + `_handle_xxx_command()` 消费后不进大模型 + 去重窗口）；
  - 角色语言口播：`_current_lang()`（贾维斯英文 / 林妹妹中文）+ `_map_speak()`；
  - 审计日志：JSON lines 落 `logs/`。
- **Codex CLI 环境实测**：
  - `codex` → `/Applications/ChatGPT.app/Contents/Resources/codex`，`codex-cli 0.147.0-alpha.6.5`；
  - `~/.codex/config.toml`：`model = "deepseek-v4-flash"`、provider `deepseek`、apikey 认证
    （即复用用户现有 DeepSeek key，无需额外配置）；
  - `codex exec` 非交互模式 ✅（`--json` 输出 JSONL 事件流，`-s` 沙箱、`-C` 工作目录）；
  - `codex review` 非交互代码审查 ✅（`--uncommitted` / `--base <branch>`）；
  - 实测：`-s read-only` 分析 ~2.5s；`-s workspace-write` 无交互修改临时 git 仓库成功
    （exit=0，事件含 `file_change`/`command_execution`，无需 `--approve-for-me`）；
  - 注意：stderr 有插件加载/远程目录同步 WARN 噪音（401 等），解析时需过滤。

## 2. Coding Agent 接入位置

**结论：`src/coding_agent/` 独立包 + main.py 主循环一个拦截钩子（第 4 处本地拦截），
与地图/视觉/电脑同级；不动 bridge、不动 Agent 系统、不碰 start.sh/launchd/进程保护。**

```
main.py 主循环
  ├─ _handle_map_command      （已有）
  ├─ _handle_vision_command   （已有）
  ├─ _handle_computer_command （已有）
  ├─ _handle_coding_command   （新增，Phase 2）：
  │     intent 预判(_coding_like) → CodingAgent.handle(text)
  │        ├─ 意图解析（分析/优化/修改/测试/审查/状态/提交）
  │        ├─ WorkspaceManager 选项目（默认当前项目，可语音指定）
  │        ├─ PermissionManager 确认（modify/test/commit → 语音确认；readonly 直行）
  │        ├─ TaskManager 入队（ThreadPoolExecutor(1) 异步，不阻塞语音主循环）
  │        │     └─ CodexClient.run(CodingTask) → ResultParser → CodingResult
  │        └─ 角色语言口播 + overlay 文本 + 审计日志
  └─ _on_recognized（普通对话，不进）
```

- **接入点最小化**：只在主循环加一个 `if self._handle_coding_command(...)` 分支（约 15 行，镜像电脑模式写法）；
  所有逻辑在 `src/coding_agent/` 内。
- **不新增 Agent**：Coding 是 Jarvis 的能力（Capability），不创建第三个角色，不写 `assistants.json`。

## 3. Tool 设计（中间层原则）

**原则：Jarvis/大脑永不直接执行 shell 修改代码。所有编码任务收敛为 `CodingTask`，
经 CodingAgent → CodexClient → Codex CLI 执行；Codex 在受控沙箱内工作。**

统一任务模型（`src/coding_agent/task.py`）：

```python
@dataclass
class CodingTask:
    id: str                 # uuid 短号（日志/幂等）
    project: str            # 目标项目绝对路径（git 仓库）
    task: str               # 自然语言任务描述
    mode: str               # "analyze" | "modify" | "test" | "review" | "git"
    permission: str         # "readonly" | "workspace-write"（由 mode 推导，禁止任务自定义）
    created_at: float
```

- mode → 沙箱映射（强制，不可被任务覆盖）：

| mode | 沙箱 | 说明 |
|---|---|---|
| analyze | `-s read-only` | 项目分析/问答，只读 |
| review | `-s read-only` + `codex review` | 代码审查（`--uncommitted`/`--base`） |
| test | `-s workspace-write` | 允许测试写产物（构建目录等，限工作区内） |
| modify | `-s workspace-write` | 代码修改，**必须用户确认** |
| git | 本机 `git` 只读命令 | status/diff/log；commit 需确认；**push 一律需确认** |

- 大脑可读 Tool 命名空间（Phase 3 预留，接入 computer 同款约束 JSON 解析）：
  `codex_execute(task, mode, project?)` / `codex_status()` / `codex_workspaces()`；
  输出仍是 `CodingTask`，执行仍走本地 Permission/Executor。
- **禁止**：任何情况下不传 `--dangerously-bypass-approvals-and-sandbox`、
  `--approve-for-me` 自动批准；任务文本黑名单（`rm -rf /`、`sudo`、系统目录写入等）先行拦截。

## 4. 调用流程（Codex CLI）

```
CodingAgent.handle(text)
  → intent（本地规则：分析/优化/修改/测试/审查/提交/状态/选择项目）
  → WorkspaceManager.resolve(project)   # 默认当前项目；校验为 git 仓库
  → PermissionManager.guard(task)       # readonly 直行；modify/test/commit → 语音确认（60s 超时拒绝）
  → TaskManager.submit(task)            # 异步线程
      → CodexClient.run(task)
          ├─ codex exec --json -s <sandbox> -C <project> --color never <prompt>
          │    （review 模式：codex review --json --uncommitted -C <project>）
          ├─ 超时（默认 300s）→ 杀进程并标记失败
          └─ stdout JSONL 事件流（stderr 只取错误，WARN 噪音过滤）
      → ResultParser.parse(jsonl)
          ├─ item.completed(agent_message) → summary
          ├─ file_change → files_changed[]
          ├─ command_execution → commands[]
          ├─ turn.completed → usage
          └─ error / 非零退出 → status=failed
      → GitManager.diff_summary(project)  # 修改后 git diff --stat 摘要
  → CodingResult{status, summary, files_changed, commands, git_diff, usage}
  → 角色语言口播 + overlay 文本 + logs/coding_agent.log
```

- 编码任务 prompt 构造：`<任务描述>\n\n约束：只修改当前工作区内的文件；不要执行破坏性命令；完成后用
  git diff --stat 总结改动。`
- 语言：任务描述传给 Codex 用原文（中文任务 Codex/DeepSeek 可理解）；结果汇报由 Jarvis 角色语言口播。

## 5. 权限设计

| 操作 | 权限 | 方式 |
|---|---|---|
| analyze / review | readonly（自动） | 直接执行，写日志 |
| test | workspace-write（自动） | 直接执行（运行测试），写日志 |
| modify | workspace-write（**确认**） | 语音/通知确认；未确认不执行；60s 超时自动拒绝 |
| git commit | 本机 git（**确认**） | 先展示 diff 摘要 → 确认后 commit |
| git push | 本机 git（**确认**） | 明确确认才 push；**默认永不自动 push** |
| 拒绝 | deny | 黑名单任务、sudo、系统目录、`--dangerously-*` 参数 |

- 确认交互复用 Computer Agent 的范式（主循环连续对话里 yes/no/确认/取消，60s 超时拒绝）；
- 所有任务 JSON lines 落 `logs/coding_agent.log`（含任务、沙箱、结果、耗时）。

## 6. 安全方案（必须）

1. **沙箱兜底**：Codex 在 `read-only` / `workspace-write` 沙箱内运行；工作区写限项目目录。
2. **参数白名单**：客户端只允许固定参数组合（`--json -s -C --color never`），不拼接用户输入进 shell。
3. **任务黑名单**：`rm -rf`、`sudo`、`shutdown`、写 `/etc`、下载即执行等先拦截。
4. **不自动批准**：不使用 `--approve-for-me` / bypass 参数；需要权限的写操作在 Jarvis 层确认。
5. **超时与资源**：单任务超时（默认 300s）后 kill 进程树；后台线程执行，绝不阻塞语音主循环。
6. **Git 约束**：`-C` 必须是 git 仓库；push 永远需确认；commit 前给 diff 摘要。

## 7. 文件结构设计

```
src/coding_agent/                 # 独立能力包（镜像 src/computer/ 单例+线程范式）
  __init__.py                     # CodingAgent 入口 + get_coding_agent() 单例
  task.py                         # CodingTask / CodingResult 数据模型 + mode→沙箱映射
  intent_parser.py                # 本地意图解析：分析/优化/修改/测试/审查/提交/状态/选项目
  codex_client.py                 # codex exec/review 调用（subprocess + 超时 + kill + JSONL 输出）
  result_parser.py                # JSONL 事件流 → CodingResult（含 WARN/插件噪音过滤）
  workspace_manager.py            # 项目发现（~/.openclaw/workspace、~/Documents/ChatGPT、~/workspace 等）
                                  # + git 校验 + 别名/中文名匹配
  permission_manager.py           # readonly 直行 / modify·test·commit·push 确认队列（60s 超时）
  git_manager.py                  # 只读 git status/diff/log 包装 + diff 摘要 + 确认后 commit/push
  task_manager.py                 # ThreadPoolExecutor(1) 任务队列 + 结果回调（口播/overlay/日志）
  action_log.py                   # 审计日志（JSON lines → logs/coding_agent.log）
```

- main.py 变更（Phase 2，约 15-25 行）：`_coding_like()` 流式预判 + `_handle_coding_command()` 拦截
  + 去重窗口（镜像电脑模式）+ `_coding_speak()` 角色语言汇报。
- 禁止触碰：`scripts/start.sh`、launchd、进程保护、`assistants.json`、Agent 系统、
  `src/vision.py`、地图模块、`src/computer/`、既有 bridge 协议。

## 8. 开发阶段（确认后执行，每阶段验证）

| Phase | 内容 | 验收（python -m py_compile + 功能） |
|---|---|---|
| 1 | 包骨架 + codex_client + result_parser + workspace_manager + task/permission/git 最小版 | 「分析当前项目」→ Codex 返回摘要；readonly 沙箱生效；结果解析正确 |
| 2 | main.py 语音钩子 + 确认流程 + overlay 文本 | 「帮我优化这个代码」→ 确认 → Codex 修改 → diff 汇报；「检查提交」→ review |
| 3 | 大脑 Tool 接入（`codex_execute` 约束 JSON）+ git commit/push 确认流 | 未知自然语言可解析为 CodingTask；commit/push 均需确认 |

- 测试清单：`codex --version`；analyze（read-only）不改文件；modify 需确认且改动限工作区；
  review 输出；git status/diff 只读；commit/push 确认；黑名单拦截；超时杀进程。

## 9. Git 与最终交付

- 全程在 `codex/chat-panel-merged`，**不创建新分支、不碰 main**。
- 最终提交：`feat: add jarvis codex coding agent` → push origin。
- 完成后生成 `CODEX_AGENT_IMPLEMENTATION_REPORT.md`（架构/文件修改/Codex 调用方式/Tool/权限/测试结果）。
- 与既有 Computer/Vision/地图能力完全并行，互不影响。
