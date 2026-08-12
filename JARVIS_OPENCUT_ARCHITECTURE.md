# Jarvis × OpenCut — 语音 AI 视频剪辑 架构设计

> 状态：待确认 ｜ 分支：`codex/chat-panel-merged` ｜ 原则：Capability 而非新唤醒 Agent；不修改 Jarvis 核心 / Voice / Vision / 启动脚本；控制层收敛在 Python Adapter。
> 前置阅读：`OPENCUT_ANALYSIS.md`（OpenCut 全量分析）。

---

## 1. 总体架构

```
用户语音
  │  "Jarvis，帮我剪辑这个旅游视频"
  ▼
main.py 拦截层  _video_like / _handle_video_command        ← 新增（照抄 coding 模式）
  ▼
Video Agent（Capability）src/assistants/video_agent/       ← 新增（照抄 vision_agent 模式）
  ▼
Mission Control（可选编排）                                 ← 复用现有 mission_control
  ▼
src/video_agent/  OpenCut Adapter（Python）                ← 新增控制层
  ├─ opencut_client.py     REST 客户端（POST /render、轮询 /jobs/:id）
  ├─ project_manager.py    timeline.ts/config.ts 生成与维护
  ├─ asset_manager.py      素材拷贝到 public/jobs、上传 facecam
  ├─ job_manager.py        异步任务 + 轮询 + 超时 + 事件回调
  └─ export_manager.py     成品搬运 + 通知 Jarvis
  ▼
OpenCut REST API（127.0.0.1:3000，进程由本方案独立拉起）
  ▼
Remotion 渲染 → out/jobs/<jobId>/output.mp4 → 通知用户
```

关键约束：**Jarvis 不直接操作 OpenCut UI，不直接拼 shell 命令**；一切经 Python Adapter 调 REST API（CLI 仅作降级兜底）。

---

## 2. Video Agent 设计

### 2.1 定位
Capability（能力模块），与 vision_agent / coding_agent 同构：
- 不注册 `assistants.json`、不占唤醒词、Jarvis/林妹妹共用
- `get_video_agent()` 单例 + worker 线程，不阻塞语音主循环
- 主循环一个拦截钩子 `_handle_video_command(text) -> bool`

### 2.2 文件结构（建议）
```
src/assistants/video_agent/
  __init__.py        # VideoAgent: clip()/generate()/status() 单例
  prompt.py          # 剪辑规划提示词（唯一源）
src/video_agent/
  __init__.py        # get_video_agent()
  intent_parser.py   # 语音文本 → VideoIntent（模式/时长/格式/素材/需求）
  task.py            # VideoTask dataclass（照抄 coding_agent/task.py）
  task_manager.py    # 提交/查询/取消/去重（照抄 coding_agent/task_manager.py）
  permission_manager.py  # 白名单 + 素材路径校验（只读素材目录，禁止系统路径）
  opencut_client.py  # ★ REST 客户端（唯一允许访问 OpenCut 的地方）
  project_manager.py # 项目/时间线生成：模板 + 参数化 → timeline.ts
  asset_manager.py   # 素材管理：拷贝/校验/清理
  job_manager.py     # 轮询 + 超时 + 事件（on_job_done/on_job_progress）
  export_manager.py  # 成品移动、结果归一化（status/files/tests 风格 → result）
  result_parser.py   # job/CLI 输出 → 统一 dict
```

### 2.3 VideoIntent（intent_parser 输出）
```python
@dataclass
class VideoIntent:
    mode: str            # "text_only" | "facecam" | "project" | "status" | "cancel"
    prompt: str          # 用户原始需求（"1分钟深圳旅游短视频"）
    target_duration_sec: int | None
    format: str          # horizontal | vertical | square（默认 horizontal）
    voice: str | None    # ElevenLabs VoiceId，可空
    source_video: str | None  # 用户提供的本地视频路径（facecam 模式）
    project: str | None  # 已有 OpenCut 项目名（project 模式）
```

### 2.4 触发关键词（intent_parser，与 coding 同风格）
- `剪辑/剪一下/制作视频/做一个视频/生成视频/渲染视频/视频编辑`
- `帮我剪(一下|个)?(<内容>)`、`做一个(<时长>)?(<内容>)短视频`
- `把 <素材路径/视频> 剪成 <需求>`
- `视频进度/渲染好了吗` → status；`停止渲染/取消视频任务` → cancel

---

## 3. Mission Control 接入

现有 `src/mission_control/` 已具备规划器 + 执行器 + 权限 + 状态机，Phase 1 的 `vision/map` 还是占位。Video 按同样方式接入：

1. `src/mission_control/mission.py`：
   - `ALLOWED_AGENTS += ("video",)`
   - `ALLOWED_ACTIONS["video"] = ("clip", "generate", "render", "export", "status")`
2. `src/mission_control/agent_registry.py`：新增 `VideoAdapter`（`_get()` 懒加载 video_agent，`execute()` 按 step.action 分派，`cancel()` 调 task_manager.cancel）
3. `src/mission_control/planner.py`：
   - LLM 提示词 agents 列表追加 `video(actions: clip, generate, render, export, status)`
   - 本地模板 fallback 增加 `_CLIP_RE`（`剪辑|剪视频|制作视频|make a video`）
4. `src/main.py`：
   - `_step_label` 增加 video 分支：`clip→"Plan video clip"`, `generate→"Generate video"`, `render→"Render video"`, `export→"Export video"`
   - 拦截层顺序：编码确认 → Mission 确认 → 地图 → 视觉 → **视频** → 编码 → 电脑 → Mission 目标 → 大模型

---

## 4. OpenCut Adapter（控制层）设计

### 4.1 进程与生命周期
- OpenCut 作为独立 Node 进程常驻（由本模块首次使用时拉起）：`npm run api:dev`（ts-node 模式），`PORT=3100` 避免与 Jarvis 其他服务冲突，仅监听 127.0.0.1
- Adapter 启动时 `GET /health`（新增一个 3 行的健康检查路由）探测；失败 → 尝试拉起 → 仍失败 → 软失败口播提示，不阻塞语音
- Jarvis 退出时由本模块负责回收该子进程（不改 `scripts/start.sh`，不建第二启动器，本进程生命周期跟随 Jarvis 主进程）

### 4.2 REST 调用映射
| 用户需求 | OpenCut API | Adapter 方法 |
|---|---|---|
| 全 AI 文生视频 | `POST /generate` | `generate(prompt, duration, voice)` |
| 用户素材视频 | `POST /facecam`（multipart） | `facecam(video_path, playback_rate)` |
| 时间线项目渲染 | `POST /render` | `render(composition_id, entry_point, input_props)` |
| 进度查询 | `GET /jobs/:id` | `status(job_id)` |
| 成品下载 | `GET /jobs/:id/download` | `download(job_id, dest_dir)` |
| 降级兜底 | `npx ts-node src/cli/render.ts <project>` | `render_cli(project)`（仅当 API 不可用） |

### 4.3 时间线生成（“个性化剪辑”的关键）
- `project_manager` 提供参数化模板：`生成 1 分钟旅游视频 → VideoProjectConfig(format, segments, music...) → workflow/generator 生成 timeline.ts`（OpenCut 已有 `src/workflow/generator.ts` 可直接复用，Jarvis 侧只需拼 JSON/YAML 配置）
- 用户给素材：facecam 流水线（转写→字幕→气泡）足够；用户要"选精彩片段"：Video Agent 用 Hermes LLM 对转写文本打分选段 → 生成 `timeline.ts` 片段时间轴 → `POST /render`

### 4.4 权限与安全
- 素材读取白名单：`~/Movies`、`~/Desktop`、`~/Downloads`、`~/Documents` 及用户指定目录；拒绝 `/etc`、`/System`、`.ssh` 等
- 所有路径参数经 `path.resolve` + 前缀校验；禁用 shell 拼接（照 OpenCut 已修复的命令注入教训）
- API 仅 127.0.0.1；如 OpenCut 未来加鉴权（env token），Adapter 预留 `header` 注入位

---

## 5. 语音交互流程（示例）

```
用户: "Jarvis，帮我做一个1分钟的深圳旅游短视频"
Jarvis: "Planning a 1-minute Shenzhen travel video. Confirm? (分析素材→选择亮点→生成方案→渲染→导出)"
用户: "确认"
  Step1 llm.analyze   → 内容规划（Hermes/DeepSeek）
  Step2 video.clip    → 生成 VideoProjectConfig + timeline.ts
  Step3 video.generate→ POST /generate（或 /render）
  Step4 video.export  → 成品搬到 ~/Movies/Jarvis/，口播路径
用户: "渲染好了吗"      → job status 口播
用户: "停了吧"         → task_manager.cancel → OpenCut job 停止（能停则停）
```

每一步走 Mission Control `requires_confirm`（generate/render/export 默认确认，分析/规划只读不确认）。

---

## 6. 开发阶段规划

| 阶段 | 内容 | 验收 |
|---|---|---|
| Phase 1 环境 | `npm install`；拉起 API；`curl /generate` 与 `/facecam` 冒烟；首次渲染下载 Chrome | API 三个端点全通，产出一个测试 MP4 |
| Phase 2 Adapter | `opencut_client` + `job_manager` + `result_parser`（纯 Python，先不接语音） | `python -m py_compile` + 脚本端到端生成视频 |
| Phase 3 Agent | `video_agent` + `intent_parser` + `main.py` 拦截钩子 | 语音说"帮我生成一个xxx视频"→ 产出 MP4 + 口播 |
| Phase 4 Mission | `mission.py`/`agent_registry.py`/`planner.py` 接入 video | 目标式指令走 Mission Control 全流程 |
| Phase 5 打磨 | 素材个性化剪辑（时间线生成）、进度口播、清理策略、失败重试 | 中文素材 + 个性化需求全链路稳定 |

---

## 7. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 用户只有 DeepSeek key，OpenCut 依赖 Gemini | 分镜/转写不可用 | 首期让用户申请免费 Gemini key；Phase 2 用 Hermes(DeepSeek) 替换 planner、Whisper 替换转写 |
| 渲染耗时数分钟 | 用户等待 | 全程异步 job + 轮询 + 口播进度 phase；不做同步等待 |
| 首次渲染下载 Chrome ~150MB | 卡顿/失败 | Phase 1 提前触发下载；失败给明确提示 |
| 中文转写质量 | 字幕错 | facecam 用 Gemini/Whisper 双后端，软失败降级 |
| 磁盘膨胀（jobs/ 双份拷贝） | 磁盘满 | Adapter 每次任务结束清理 `jobs/<id>/assets` 与 `public/jobs/<id>`，仅留 output |
| API 无鉴权 | 本机其他进程可调用 | 只绑 127.0.0.1；后续可加 token |
| OpenCut 升级改 API | Adapter 失效 | 所有 API 依赖收敛在 `opencut_client.py` 单文件 |
| 用户素材路径/权限 | 误操作 | permission_manager 白名单 + 只读校验 |

---

## 8. 修改文件清单（待确认后开发）

新增：
```
src/assistants/video_agent/{__init__,prompt}.py
src/video_agent/{__init__,intent_parser,task,task_manager,permission_manager,
                 opencut_client,project_manager,asset_manager,job_manager,
                 export_manager,result_parser}.py
```

修改（最小、按 Phase 3/4 分步）：
```
src/main.py                      # _video_like/_handle_video_command/拦截顺序/_step_label
src/mission_control/mission.py   # ALLOWED_AGENTS + ALLOWED_ACTIONS["video"]
src/mission_control/agent_registry.py  # VideoAdapter 注册
src/mission_control/planner.py   # LLM 提示词 + 本地 fallback 模板
```

禁止修改：`scripts/start.sh`、launchd、杀进程保护、Vision、地图、现有 Agent 协议、OpenClaw/Hermes 核心通信。
