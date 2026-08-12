# Jarvis Short Drama Mode — 短剧剪辑模式架构

> 状态：Phase 1 架构方案 ｜ 分支：`codex/chat-panel-merged`
> 范围：本方案仅覆盖第一阶段（模式入口 / Mission / 剧情规划 / 人物 / 分集 / 剧本 / 镜头 Prompt / 确认机制 / 状态保存 / Flutter 展示）。
> 第二阶段（视频生成模型、OpenCut 自动剪辑、自动音频、自动发布）只做预留接口，不实现。

---

## 1. 当前架构分析（已读代码结论）

### 1.1 语音拦截链（src/main.py）
主识别循环按固定顺序拦截指令，命中后本地执行、不再进大模型：

```
编码确认 → 视频确认 → Mission 确认/控制 → 地图 → 视觉 → 视频指令
→ 编码指令 → 电脑控制 → Mission 目标指令 → 大模型兜底
```

每条链路 = 一个 `_xxx_like()` 正则门 + 一个 `_handle_xxx_command()` + 若干 `_handle_xxx_confirm()`。

### 1.2 Mission Control（src/mission_control/）
- `MissionTask(goal, steps[], status)` + `MissionStep(agent, action, params, requires_confirm)`，dataclass + `to_dict()`，无数据库。
- `Planner`：LLM（HermesBridge）→ JSON 步骤，失败回退本地模板。
- `StateMachine`：Mission/Step 合法迁移表 + 线程安全单例。
- `Executor`：串行执行步骤，`requires_confirm` 步骤进入 `request_confirm/wait_confirm`（超时由 `permission_manager` 控制，60s），支持 pause/resume/cancel/skip。
- `AgentRegistry`：`coding / computer / llm / vision / map / video` 薄适配器。
- 已有 `video` 适配器：`clip / generate / render / export / status`，直接调用 `src/video_agent/`。

### 1.3 Video Agent（src/video_agent/ + src/assistants/video_agent/）
- Capability 模式：不注册进 `assistants.json`、不占唤醒词，由 main.py 拦截调用。
- `OpenCutClient`：REST 客户端 + 进程拉起/回收 + `.env` 注入 + AI key 检测（DeepSeek/Gemini）。
- 已具备：`generate`（DeepSeek 分镜 → macOS say 配音 → Coverr 素材 → ffmpeg 渲染）、`facecam`、`render`、`status`、`cancel`。
- `assistants/video_agent/__init__.py` 提供 `VideoCapability` 门面（`clip/generate/status`）。

### 1.4 Flutter Overlay（assistant_overlay/）
- Python ↔ Flutter 走 TCP 127.0.0.1:17889，文本行协议：`user:` / `ai:` / `map_*` / `vision:*` / `agent:` / `audio_level:` 等。
- 右下角聊天面板（用户/AI 逐句）、左上角 3D 地球卡（`MapGlobeCard`）、中央视觉 HUD（`VisionHudController`）。
- 面板模式：Python 推送命令 → Flutter `handleCommand()` 分发 → Controller → HUD 组件。

### 1.5 结论
短剧模式应沿用 **Capability + 语音拦截钩子 + TCP 面板推送** 三件套，与 video/vision 完全同构；
Mission Control 作为上层编排（注册 `drama` agent），drama 自身维护项目级状态机与持久化。

---

## 2. Short Drama Mode 架构

```
Jarvis Master Agent (main.py 语音循环)
        │  拦截钩子：_drama_like / _handle_drama_command / _handle_drama_confirm
        ▼
Drama Agent（src/drama_agent/，Capability）
        │
        ├── DramaProjectStore  项目/人物/分集/剧本/镜头 Prompt 持久化 (projects/short_drama/)
        ├── DramaPlanner       故事→世界观→人物→主线→分集规划（HermesBridge LLM + 模板兜底）
        ├── CharacterAgent     人物设定 + 一致性约束 + 修改影响范围分析
        ├── EpisodeWriter      单集剧本（剧情/对白/镜头列表/动作/运镜/音效/BGM/旁白）
        ├── PromptAgent        每镜头 VIDEO_PROMPT / NEGATIVE_PROMPT / 一致性 Prompt
        ├── DramaStateMachine  阶段状态机（PLANNING→AWAITING_CONFIRM→EPISODE→…）
        └── ConfirmGate        每阶段 WAITING_CONFIRMATION（复用 mission 确认模式，60s 超时）
        │
        ▼
Mission Control（注册 drama agent，Phase 1 仅编排；Phase 2 挂 VideoAdapter → OpenCut）
```

## 3. Mission Control 集成

- `ALLOWED_AGENTS` 增加 `"drama"`；`ALLOWED_ACTIONS["drama"]` = `(start, plan, character, episode, prompts, rewrite, pause, resume, status, confirm)`。
- `AgentRegistry` 增加 `DramaAdapter`（薄封装，调用 `get_drama_agent()`）。
- 一个短剧 = 一个 Mission：`goal` = 用户创意；`steps` = 阶段链（Phase 1-9），每步 `requires_confirm=True`，步骤间插入用户确认。
- 与现有 Mission 的关系：Drama 项目状态机是**主状态**，Mission 是它的**执行载体**。Phase 1 中每个阶段产出物（规划/人物/剧本/Prompt）由 Drama Agent 直接生成并保存，阶段推进时通过 `confirm_step` 走统一确认通道（复用 `MissionPermissionManager` 的 60s 超时与语音确认）。

## 4. 数据结构（dataclass + JSON 持久化，风格与 mission.py 一致）

```
projects/short_drama/
  index.json                        # 项目列表
  <project_id>/
    drama.json                      # 项目主文件（全部状态）
    characters/<char_id>.json       # 人物卡（可选外置，便于单文件编辑）
    episodes/
      episode_01/
        script.md                   # 完整剧本
        storyboard.json             # 镜头列表
        prompts/shot_01.json        # 每镜头完整 Prompt 包
        assets/  audio/  video/  project/   # Phase 2 使用
```

核心 dataclass：

```python
class DramaStatus(str, Enum):
    CREATED, PLANNING, AWAITING_CONFIRM, CHARACTER_DESIGN,
    EPISODE_DESIGN, PROMPTS, ASSET_PREP, EDITING,
    COMPLETED, PAUSED, FAILED

class DramaPhase(str, Enum):
    STORY_SETTING, CHARACTER_DESIGN, PLOT, EPISODE_PLAN,
    EPISODE_SCRIPT, EPISODE_PROMPTS, ASSETS, EDIT, REVIEW, NEXT_EPISODE

@dataclass
class DramaProject:
    id: str
    title: str                 # 《都市异能者》
    genre: str
    total_episodes: int
    duration_per_episode: int  # 秒
    visual_style: str
    status: DramaStatus
    current_phase: DramaPhase
    current_episode: int
    logline: str               # 核心冲突一句话
    worldview: str
    characters: list            # List[Character]
    relationship_map: list      # 人物关系
    main_plot: str
    episode_goals: list         # 每集目标（第1集 觉醒 / 第2集 第一次使用能力…）
    episodes: list              # List[Episode]
    pending_confirm: dict       # 当前等待确认的阶段+产出摘要
    history: list               # 阶段变更审计
    created_at / updated_at: float

@dataclass
class Character:
    id: str                     # "lin-xiao"
    name: str                   # 林晓
    age / gender / hairstyle / outfit / personality / voice / background: str
    appearance_prompt: str      # 一致性外貌描述（供视频生成）
    consistency_prompt: str     # 全剧一致性约束文本

@dataclass
class Episode:
    number: int
    title: str
    goal: str
    synopsis: str               # 本集剧情
    script: str                 # 完整剧本（含对白）
    shots: list                 # List[StoryboardShot]
    status: str                 # planned / script_ready / prompts_ready / ...
    files: dict                 # script.md / storyboard.json / prompts/ 路径

@dataclass
class StoryboardShot:
    shot_id: str                # "shot_01"
    scene: str                  # 雨夜城市街道
    character: str              # 林晓
    appearance: str             # 外貌描述（含 Character 一致性引用）
    action: str                 # 林晓站在街角…
    camera: str                 # cinematic medium shot
    lighting: str               # neon blue lighting
    environment: str
    style: str                  # cinematic realistic
    mood: str
    dialogue: str               # 本镜头对白（可空）
    voice: str                  # 配音人声/语速
    sfx: str
    bgm: str
    duration: int               # 秒
    video_prompt: str           # 完整生成提示词
    negative_prompt: str        # 负面提示词
    consistency_prompt: str     # 人物一致性约束
```

## 5. Prompt 结构

- `StoryPlanPrompt`：标题/类型/核心冲突/世界观/人物/人物关系/主线/分集目标，输出 JSON（`_extract_json` 同款容忍）。
- `CharacterPrompt`：年龄/性别/发型/服装/性格/声音/背景 + `appearance_prompt`（用于视频模型）+ `consistency_prompt`（"后续每一集不得改变…"）。
- `EpisodeScriptPrompt`：本集剧情/完整剧本/对白/镜头列表/场景/人物动作/摄像机运动/音效/BGM/旁白 → `script.md` + `storyboard.json`。
- `ShotPromptAgent`：把每个镜头扩成完整 Prompt 包（含 VIDEO_PROMPT / NEGATIVE_PROMPT / 一致性）。
- 所有生成走 `HermesBridge`（= 用户的 DeepSeek 后端），失败时本地模板兜底（保证断网可给出结构化骨架）。

## 6. 状态机

```
CREATED ──收集需求──▶ PLANNING ──规划完成──▶ AWAITING_CONFIRM
  ▲                                              │ 用户确认
  │                                              ▼
  │  ┌──────────────────── EPISODE_DESIGN（第N集剧本）──▶ AWAITING_CONFIRM
  │  │                                                      │ 确认
  │  │                                                      ▼
  │  │                                            PROMPTS（镜头Prompt）──▶ AWAITING_CONFIRM
  │  │                                                              │ 确认 → 下一集 / 进入 Phase2 素材
  └──┴── PAUSED（任意阶段可暂停/继续）
```

- 任意阶段 → `PAUSED`（"暂停短剧"）→ 恢复原阶段（"继续短剧"）。
- 阶段推进必须经过 `AWAITING_CONFIRM`；确认超时（60s）保持等待，不自动推进。
- 修改类指令（改人物/重写剧集）→ 计算影响范围：人物卡变更提示"会影响第 1-5 集人物一致性，是否同步修改？"；单集重写只影响该集。

## 7. 语音命令（正则拦截，中英）

| 命令 | 动作 |
|---|---|
| `短剧剪辑` / `short drama` | 进入短剧模式，收集需求（主题/类型/集数/每集时长/视觉风格），未填项由 Jarvis 建议 |
| `查看短剧进度` / `短剧进度` | 汇报项目状态/当前阶段/下一步 |
| `重新规划剧情` | 回到 PLANNING（先确认，防误触） |
| `修改人物` / `把女主角改成短发` | CharacterAgent 修改 + 影响范围确认 |
| `查看第一集` | 读 `episodes/episode_01/script.md` 摘要 |
| `重新写第一集` | 重生成单集剧本（确认后） |
| `生成第一集提示词` | 生成全部镜头 Prompt 包 |
| `开始制作第一集` | Phase 1 标记 ASSET_PREP 待命（Phase 2 接素材）；当前提示"进入第二阶段后接入" |
| `暂停短剧` / `继续短剧` | PAUSED ↔ 原阶段 |
| `进入下一集` | 下一集 EPISODE_DESIGN |
| `重新剪辑这一集` | Phase 2 预留（VideoAdapter 重新渲染） |
| `确认` / `好的` / `取消` | ConfirmGate 统一答复 |

## 8. UI 设计（Flutter Overlay）

- 新增 TCP 命令：`drama:status <json>`（Python 推送 `DramaProject` 摘要）+ `drama:reset`（退出模式隐藏）。
- 新增 `ShortDramaPanel`（HUD 卡片，风格对齐 `MapGlobeCard`）：左上角地图卡下方/独立左侧浮窗：

```
SHORT DRAMA MODE
《都市异能者》   EPISODE 03 / 10
阶段：PROMPTS
进度：[███████░░░]
下一步：等待确认 → 生成第3集镜头Prompt
[确认继续] [暂停]
```

- 面板状态由 `DramaHudController` 管理（对齐 `MapGlobeController`/`VisionHudController` 模式），`handleCommand()` 分发 `drama:*`。
- 语音确认仍走现有对话确认链（复用 `_handle_mission_control` 的确认通道）。

## 9. 后续 OpenCut 集成方案（Phase 2 预留）

- 不直接操作 OpenCut：`DramaAdapter` → `VideoAdapter`（现有）→ `OpenCutClient`。
- 每集流程：镜头 Prompt → 素材（视频模型 API / 本地生成 / 用户提供）→ 按 storyboard 时间线组装 → `generate/render` 渲染 `episode_XX.mp4` → 导出 `~/Movies/JarvisDramas/`。
- 字幕/对白走现有 ffmpeg subtitles 链路；配音走 macOS say / Hermes TTS。
- 接口占位：`DramaProject.episodes[i].files.project/`（OpenCut 项目配置），`VideoAdapter` 已具备能力，Phase 2 只补"storyboard→剪辑参数"转换器。

## 10. 后续视频生成模型接入方案（Phase 2 预留）

- 分层抽象 `ShotRenderer`：
  - 方案 A（本地免费）：Wan2.x / AnimateDiff 文生视频，人物一致性弱，适合剪影/氛围镜头；
  - 方案 B（API）：即梦/可灵 Kling/Runway/Pika，质量高、需 key 与网络（国内可用即梦）；
  - 方案 C（图生视频）：先用图像模型生成角色一致性立绘 → 图生视频，人物一致性最好；
  - 回退：无模型时用 OpenCut 现有 generate 流水线（DeepSeek 分镜 + Coverr 素材 + ffmpeg），保证全链路可跑。
- 一致性方案：`Character.appearance_prompt` + `consistency_prompt` 注入每个镜头 Prompt，模型支持 reference/seed 时复用。

## 11. 文件规划（Phase 1）

```
src/drama_agent/
  __init__.py            # DramaAgent 入口：handle(text)/start/confirm/status/pause/resume
  models.py              # DramaProject / Character / Episode / StoryboardShot / DramaStatus / DramaPhase
  state_machine.py       # 阶段迁移表（复用 mission 风格）
  store.py               # projects/short_drama/ JSON 读写 + 原子写 + 审计 history
  planner.py             # 故事/世界观/人物/分集规划（HermesBridge + 模板兜底）
  character_agent.py     # 人物设定 + 一致性 + 影响范围计算
  episode_writer.py      # 单集剧本 + 镜头列表 + storyboard
  prompt_agent.py        # 每镜头 VIDEO_PROMPT/NEGATIVE/一致性
  confirm_gate.py        # 阶段确认（60s 超时 + 语音确认，复用 mission 模式）
  intent_parser.py       # 12+ 语音命令正则
src/assistants/drama_agent/__init__.py   # DramaCapability 门面（与 video/vision 同构）
src/mission_control/agent_registry.py    # +DramaAdapter；ALLOWED_AGENTS/ACTIONS
src/mission_control/planner.py           # 模板 fallback +drama 分支
src/main.py                              # 3 个钩子：_drama_like/_handle_drama_command/_handle_drama_confirm
assistant_overlay/lib/drama_hud_controller.dart   # 新
assistant_overlay/lib/short_drama_panel.dart      # 新
assistant_overlay/lib/jarvis_overlay.dart         # handleCommand +drama:* 分发
```

## 12. 禁止事项

- 不修改 `scripts/start.sh`、launchd、进程保护、Vision/Video/Voice 现有协议。
- 不创建第三个唤醒 Agent（drama 是 Capability，不注册 assistants.json）。
- 不引入大型依赖（生成走现有 Hermes/DeepSeek；存储走 JSON）。
- 第二阶段能力只留接口，不在 Phase 1 实现。

## 13. 测试（Phase 1）

1. `python -m py_compile`（全部新增/修改文件）。
2. 意图解析用例：`短剧剪辑 / 查看短剧进度 / 重新规划剧情 / 修改人物 / 查看第一集 / 重新写第一集 / 生成第一集提示词 / 开始制作第一集 / 暂停短剧 / 继续短剧 / 进入下一集 / 重新剪辑这一集` 12+ 条。
3. 状态机：规划→确认→剧本→确认→Prompt→确认→暂停→恢复→修改人物（影响范围提示）。
4. 持久化：每阶段推进后重载 `drama.json` 校验字段完整。
5. `flutter analyze`（新增面板代码）。
6. 语音端到端：`短剧剪辑` → 输入需求 → 生成 10 集规划 → 确认 → 生成第一集 → 确认 → 生成镜头 Prompt → 确认。
