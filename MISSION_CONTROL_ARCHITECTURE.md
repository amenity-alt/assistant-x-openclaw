# Jarvis Mission Control — 架构设计

> 状态：待确认 ｜ 分支：`codex/chat-panel-merged` ｜ 原则：不推翻现有架构，Mission Control 作为 **Capability（编排器）** 接入，而非独立唤醒 Agent。

---

## 1. 当前 Agent 架构分析

### 1.1 现有能力矩阵

| 能力 | 模块 | 入口 | 执行方式 | 权限模型 | 语音接入 |
|---|---|---|---|---|---|
| 对话 | `src/hermes_bridge.py` / `openclaw_bridge_websocket.py` | `main.py` 主循环默认分支 | LLM 网关（Hermes/OpenClaw） | — | 未拦截时进大模型 |
| 地图 | `src/map_dashboard.py`、`src/map_news.py` | `_handle_map_command` | 本地 TCP → overlay / 天地图 | 只读 | `定位到X / 关闭地图` |
| 视觉 | `src/vision.py` + `src/vision_object.py` + `src/assistants/vision_agent/` | `_handle_vision_command` | 本地摄像头 + MediaPipe / Hermes 视觉 | 只读 | `开启视觉扫描 / 扫描一下 / 这是什么` |
| 电脑控制 | `src/computer/`（intent→permission→executor→controllers） | `_handle_computer_command` | 本地 AppleScript / AX / 键鼠 | `Risk.AUTO/CONFIRM/DENY` | `打开Chrome / 截屏 / 点击xxx` |
| 编码 | `src/coding_agent/`（Codex CLI + 沙箱 + 确认） | `_handle_coding_command` | 本机 `codex exec/review` | mode→沙箱强制映射 + 确认 | `分析这个项目 / 优化xxx代码` |

### 1.2 共性模式（新模块必须复用）

- **Capability 而非 Agent**：不注册进 `assistants.json`、不占唤醒词、不写 Jarvis 核心；任何角色（jarvis / lin-meimei）共用。
- **单例 + worker 线程**：`get_xxx_agent()` + 后台线程执行，不阻塞语音主循环。
- **主循环一个拦截钩子**：`_handle_xxx_command(text) -> bool`，消费后不进大模型；流式预判 `_xxx_like(text)` 防回声。
- **去重窗口**：同指令 15s 内重复（ASR 回声/流式重发）忽略。
- **权限确认**：危险操作 `waiting_confirmation` → 语音"确认/取消"回调（`_handle_coding_confirm` 模式）。
- **角色语言口播**：`self._map_speak(msg)`（Jarvis 英文 / 林妹妹中文），防回声由 `_map_speak` 处理。
- **软失败**：任何后端不可用 → 降级/提示，绝不崩、不阻塞语音主流程。
- **审计日志**：`logs/` 下按模块 JSONL。

### 1.3 现有缺口

1. 每个能力都是**单指令**驱动，无法表达"目标 → 多步 → 依赖 → 汇总"。
2. 各 Agent 入口不统一（`agent.handle(text)` / `agent.run_sync(text)` / `agent.execute(action)`），无法被统一编排。
3. 没有跨 Agent 的进度跟踪、暂停/恢复、失败重试、汇总汇报。

---

## 2. Task 生命周期设计

Mission Control 引入两层：**Mission（目标）** 与 **Step（步骤）**。

```
用户目标
   │
   ▼
[1] PLANNED ──── 规划器把目标拆成有序步骤（Hermes LLM 输出结构化 JSON）
   │
   ▼
[2] AWAITING_CONFIRM ──── 语音/聊天展示计划，等待用户确认
   │   确认
   ▼
[3] RUNNING ──── 执行器按序调度 Step（可暂停/恢复/中止）
   │   全部成功
   ▼
[4] COMPLETED ──── 汇总汇报（每步结果 + 总结，角色语言口播 + HUD）
   │   任一失败且不可恢复
   ▼
[5] FAILED ──── 汇报失败步骤与原因，询问是否重试/跳过
```

生命周期规则：

- 每个 Mission 有唯一 `mission_id`（`uuid4().hex[:12]`，与 CodingTask 一致）。
- 每个 Step 有唯一 `step_id`，状态独立。
- 任一 Step 失败 → Mission 进入 `FAILED`（或按策略 `SKIP` 继续）；用户可命令"跳过这一步 / 重试 / 停止任务"。
- 用户说"暂停"→ `PAUSED`（当前 Step 允许中断时中断，否则等待 Step 完成后再停）；"继续"→ `RUNNING`。
- 用户说"取消/停止任务"→ `CANCELLED`（正在执行的 Step 走 Agent 的 `cancel` 通道，如 Codex 打断、Computer 任务取消）。

---

## 3. 状态机设计

### 3.1 Mission 状态机

```
             ┌────────────────────────────────────────────┐
             │                                            │
 PLANNED ──► AWAITING_CONFIRM ──确认──► RUNNING ──► COMPLETED
   │              │  ▲                  │  │
   │ 规划失败      │  │取消              │  │全部失败/不可恢复
   ▼              │  │                  │  ▼
 FAILED ◄─────────┘  │                  FAILED
                     │                  │用户指令
                     │                  ▼
                     └── 取消 ──────► CANCELLED
                                        ▲
                                        │
                              PAUSED ◄──┘（暂停/继续）
```

| 状态 | 含义 | 可转换到 |
|---|---|---|
| `PLANNED` | 规划完成，待展示 | `AWAITING_CONFIRM` / `FAILED` |
| `AWAITING_CONFIRM` | 等待用户确认计划 | `RUNNING` / `CANCELLED` / `FAILED` |
| `RUNNING` | 执行中 | `PAUSED` / `COMPLETED` / `FAILED` / `CANCELLED` |
| `PAUSED` | 用户暂停 | `RUNNING` / `CANCELLED` |
| `COMPLETED` | 全部步骤成功 | —（终态） |
| `FAILED` | 规划失败或不可恢复失败 | `RUNNING`（用户要求重试） |
| `CANCELLED` | 用户取消 | —（终态） |

### 3.2 Step 状态机

```
PENDING ──► READY ──► RUNNING ──► SUCCEEDED
   │          │          │
   │          │          ├──► FAILED ──►（重试→READY / 跳过→SKIPPED）
   │          ▼          └──► ABORTED（Mission 取消时）
   └────► SKIPPED（用户跳过 / 前置失败但策略=skip）
```

- `PENDING`：未到执行顺序。
- `READY`：前序步骤已满足（顺序模型下即"轮到它"）。
- `RUNNING`：已交给对应 Agent 执行。
- `SUCCEEDED / FAILED / SKIPPED / ABORTED`：终态。
- 失败策略：`abort`（默认）| `skip` | `retry(次数, 间隔)`，规划时由 Step 声明，用户确认时可见。

---

## 4. 数据模型设计

新增 `src/mission_control/mission.py`（与 `coding_agent/task.py` 同风格：dataclass + `to_dict`）。

```python
class MissionStatus(str, Enum):
    PLANNED = "planned"
    AWAITING_CONFIRM = "awaiting_confirm"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class StepStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    ABORTED = "aborted"

@dataclass
class MissionStep:
    id: str                      # uuid4().hex[:12]
    index: int                   # 执行顺序
    agent: str                   # "coding" | "computer" | "vision" | "map" | "llm" | "notify"
    action: str                  # Agent 语义动作："codex.analyze" / "computer.open_app" / ...
    params: dict                 # 动作参数（与对应 Agent 的入参对齐）
    requires_confirm: bool       # 该步是否需单独确认（沿用底层权限体系）
    on_failure: str              # "abort" | "skip" | "retry"
    retries: int = 0
    status: StepStatus = StepStatus.PENDING
    result: dict = field(default_factory=dict)   # AgentResult.to_dict()
    started_at: float = 0.0
    finished_at: float = 0.0

@dataclass
class MissionTask:
    id: str                      # mission_id
    role: str                    # "jarvis" | "lin-meimei"（口播语言来源）
    goal: str                    # 用户原始目标
    status: MissionStatus = MissionStatus.PLANNED
    steps: list                  # List[MissionStep]
    summary: str = ""            # 完成/失败总结
    created_at: float = field(default_factory=time.time)
    confirmed_at: float = 0.0
    finished_at: float = 0.0
    error: str = ""

@dataclass
class AgentResult:
    status: str                  # success | failed | denied | cancelled | waiting
    summary: str = ""            # 人类可读结果
    data: dict = field(default_factory=dict)   # Agent 特有数据（files_changed / screenshot / ...）
    task_id: str = ""
    elapsed: float = 0.0
    def to_dict(self) -> dict: ...
```

持久化：`logs/mission_<ts>.jsonl` 审计（创建/状态变更/步骤结果），不引入数据库。

---

## 5. Agent 调度方案

### 5.1 Agent 适配器注册表（`agent_registry.py`）

统一调度接口，每个 Agent 一个薄适配器（不修改 Agent 本体）：

```python
class AgentAdapter(Protocol):
    name: str
    def execute(self, step: MissionStep, ctx: MissionContext) -> AgentResult: ...
    def cancel(self, step: MissionStep) -> bool: ...
```

| adapter | 复用现有入口 | 说明 |
|---|---|---|
| `CodingAdapter` | `coding_agent.get_coding_agent().run_sync(text, project, timeout)` | 把 `params`（mode/task/project）转成 CodingTask；`requires_confirm` 走 `pending_confirmations` + 语音确认；**不自动 push** |
| `ComputerAdapter` | `computer.intent_parser.parse(text)` + `CommandExecutor().execute(action)` | 把语义动作转 Action；`Risk.CONFIRM` 步骤转确认 |
| `VisionAdapter` | `vision_agent.get_vision_agent().scan/describe` | 只读：抓帧 → 识别 → 结果；超时软失败 |
| `MapAdapter` | `map_dashboard` / `map_news` | 只读：定位 / 资讯，经现有 TCP 通道 |
| `LLMAdapter` | `hermes_bridge.send_and_wait` | 纯文本步骤（总结/翻译/生成），无副作用 |

调度器（`executor.py`）：

```python
class MissionExecutor:
    def start(self, mission): ...       # 后台线程按序执行
    def pause(self, mission_id): ...
    def resume(self, mission_id): ...
    def cancel(self, mission_id): ...
    def skip_step(self, mission_id, step_id): ...
    def retry_step(self, mission_id, step_id): ...
```

- 串行执行（Phase 1）；`agent` 相同且无副作用约束的连续步骤可合并。
- 每步执行前调 `permission_manager.guard(step)`：黑名单 → `DENY`；需确认 → `waiting_confirmation`。
- 并发上限 1 个 Mission 运行（语音助手单线程主循环约束）；新的 Mission 请求在已有运行时提示"已有任务运行中"。
- 执行结果写 `AgentResult`，Step 状态机推进；全部 `SUCCEEDED` → Mission `COMPLETED`。

### 5.2 规划器（`planner.py`）

- 首选：Hermes LLM（DeepSeek 文本能力足够），prompt 要求输出**固定 schema 的 JSON**（步骤列表：agent/action/params/on_failure/requires_confirm），`_extract_json` 容错解析，失败则本地模板规划。
- 本地 fallback：关键词模板（如"打开 X 并截屏" → `[computer.open_app, computer.take_screenshot]`；"分析项目 X" → `[coding.analyze]`）。
- 规划结果做**白名单校验**：agent 必须是已注册的 5 类之一；action 必须匹配 adapter 支持的动作；参数最大长度/数量限制，防止 prompt 注入。

---

## 6. 与 Voice / Vision / Codex / Computer Agent 的结合

### 6.1 语音接入（`main.py` 最小改动）

在现有拦截链（地图→视觉→编码→电脑控制）之后、进大模型之前，新增：

```python
# 任务指令（目标 → 规划 → 确认 → 执行）
if self._handle_mission_command(recognition_result):
    self.visual.show_user_text(recognition_result)
    recognition_result = ""
    recognition_stream = self.recognizer.create_stream()
    start_audio_stream()
    continue

# 任务确认/控制（确认 / 取消 / 暂停 / 继续 / 跳过 / 重试）
if self._handle_mission_control(recognition_result):
    recognition_result = ""
    ...
    continue
```

- `_mission_like(t)`：流式预判（`目标/任务/规划/执行计划/创建任务` 等触发词），防回声。
- `_handle_mission_command`：解析目标 → `get_mission_agent().plan_and_request(goal, role)` → 计划展示 + `_ask_mission_confirm()`（口播计划摘要 + HUD 面板）。
- `_handle_mission_control`：确认/取消/暂停/继续/跳过/重试/状态查询；复用 `_handle_coding_confirm` 的去重与超时模式。
- 口播统一 `self._map_speak`，跟随角色语言（Jarvis 英文 / 林妹妹中文）。
- 退出待机（`exit_standby`）时：不杀 Mission（后台任务继续），但清空待确认提示；新确认需重新唤醒。

### 6.2 HUD 联动（TCP 17889 协议扩展，沿用 `vision:*` 风格）

| 事件 | 载荷 | 用途 |
|---|---|---|
| `mission:plan <json>` | MissionTask 摘要 | 右侧/底部任务计划面板 |
| `mission:step <json>` | 单步状态 | 步骤进度（当前执行步骤高亮） |
| `mission:status <STATE>` | RUNNING/PAUSED/COMPLETED/FAILED/... | 状态机同步 |
| `mission:confirm` | 无 | 请求确认（复用现有确认音效/交互） |

旧 overlay 对未知命令安全忽略（已验证 `vision:object` 行为），协议扩展向后兼容；overlay 面板更新随下次 CI 构建发布。

### 6.3 安全边界（与现有体系一致）

- Mission 本身默认只读规划；`coding.modify` / 危险 computer 动作沿用各 Agent 的 `PermissionManager`，**每步单独确认**，Mission 级确认 ≠ 跳过步骤级确认。
- 黑名单（sudo/rm/删除大量文件等）在 Mission 规划校验层再兜底一次。
- 不自动 push；git 操作只读或需确认。
- 打断（唤醒词中断 Jarvis 播报）不影响 Mission 执行线程；Mission 汇报被打断可随时重听（"汇报任务进度"）。

### 6.4 交互示例

```
用户：帮我做一个任务：分析 assistant-x-openclaw 的代码，然后优化掉最明显的 3 个问题，最后跑一遍测试
Jarvis：Plan ready, sir. 3 steps:
 1. Analyze project structure (coding.analyze)
 2. Optimize top 3 issues (coding.modify, requires confirmation)
 3. Run tests (coding.test)
 Proceed?
用户：确认
Jarvis：Step 1 done: 12 files analyzed...  Step 2 requires your approval: ...
用户：确认修改
Jarvis：Step 2 done: 3 files changed.  Step 3: running tests...  All done, sir. 3 tests passed.
```

---

## 7. 文件结构（新增，不修改现有模块核心）

```
src/mission_control/
├── __init__.py            # MissionControlAgent 单例：plan_and_request / confirm / control / status
├── mission.py             # MissionTask / MissionStep / AgentResult + 状态枚举
├── planner.py             # 目标 → 步骤（Hermes LLM + 本地模板 fallback + 白名单校验）
├── state_machine.py       # Mission/Step 状态机 + 合法迁移校验
├── agent_registry.py      # 5 个 Agent 适配器（coding/computer/vision/map/llm）
├── executor.py            # 串行调度、暂停/恢复/取消/跳过/重试、失败策略
├── confirm.py             # 确认管理（复用 coding 模式：confirm_id + 超时）
├── permission_manager.py  # Mission 级黑名单 / 步骤确认 / 计划白名单
└── action_log.py          # logs/mission_*.jsonl 审计
```

`main.py` 仅新增：`_mission_like` / `_handle_mission_command` / `_handle_mission_control` / `_ask_mission_confirm` 四个方法 + 拦截链两个钩子（约 80-120 行）。

---

## 8. 开发阶段（确认后执行）

- **Phase 1**：数据模型 + 状态机 + 规划器（LLM+fallback）+ 串行执行器 + coding/computer/llm 三个 adapter + 语音确认/取消/停止 + 口播汇报 + 审计日志。
- **Phase 2**：vision/map adapter + 暂停/恢复/跳过/重试 + HUD `mission:*` 面板 + 步骤级多轮确认。
- **Phase 3**：依赖图（DAG）/并行步骤/条件分支 + 跨角色任务 + 持久化恢复。

每阶段：`python -m py_compile` + `flutter analyze` + 现有回归；不修改 `scripts/start.sh`、launchd、进程保护、`vision:hand` 协议。
