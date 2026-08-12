# OpenCut 项目分析

> 状态：已完成调研 ｜ 克隆位置：`~/Documents/ChatGPT/opencut` ｜ 上游：`github.com/floomhq/opencut`（MIT）
> 目的：为 Jarvis 语音控制 OpenCut 提供技术依据（仅分析，未改任何代码）。

---

## 1. 项目定位

**OpenCut — AI Video Production Engine（AI 视频制作引擎）**，v0.1.0，MIT 协议。

核心思想：**用 TypeScript 定义时间线（代码即剪辑）**，而不是鼠标拖拽剪辑；配合 AI（Gemini 规划分镜、Whisper/Gemini 字幕、Pexels 素材、ElevenLabs 配音）自动生成成品 MP4。

- 语言/运行时：TypeScript 5.8 + Node ≥ 20（本机 v22.23.2 满足）
- 渲染核心：Remotion 4.0.454（`@remotion/bundler` / `@remotion/renderer` / `@remotion/cli`）
- UI：React 19.1 + react-dom
- 服务层：Express 5.2 + multer（文件上传）
- AI：`@google/generative-ai`（Gemini：分镜规划 + 视频转写）、axios（Pexels 素材 / ElevenLabs TTS）
- 系统依赖：ffmpeg / ffprobe（text-only 流水线拼接用）
- 测试：Node 内置 test runner + ts-node，125 个用例

---

## 2. 目录结构

```
src/
  engine/                  # 可复用 Remotion 组件与工具（核心渲染库）
    types.ts               # TimelineSegment / SubtitleSegment / VideoConfig 等全部接口
    Composition.tsx        # 时间线 + 音频编排
    Segment.tsx            # 单个片段渲染（背景+叠加层）
    FaceBubble.tsx         # 人像 PiP 圆形气泡
    SubtitleOverlay.tsx    # 词级字幕（当前词高亮）
    KeywordOverlay.tsx     # 大字关键词
    TitleCard.tsx / EndCard.tsx / NotificationBanner.tsx
    BackgroundEffects.tsx  # 程序化背景（orbs/particles/dots/...）
    plugin.ts              # 插件注册机制（registerPlugin/getPlugins）
    animation/             # easing / spring / kenburns / particles / audio 等动画工具
  compositions/            # 已注册 Remotion Composition（FacecamVideo / index.tsx）
  examples/                # 7 个示例项目：quickstart / openslides / floom-launch /
                           #   hyperniche-launch / opendraft-research / ai-engineer-basics / format-demo
                           #   每个含 config.ts / timeline.ts / subtitles.ts / Root.tsx / index.ts
  cli/                     # init / init-core / transcribe / render / validate / fetch-broll / run-visual-plan
  api/                     # ★ REST API（Express）— 未被 README 文档化，但代码完整可用
    server.ts              #   POST /render, /generate, /facecam; GET /jobs/:id, /jobs/:id/download
    jobs.ts                #   本地磁盘 Job 存储（jobs/<uuid>/status.json + output.mp4 + assets/）
    renderer.ts            #   Remotion bundle→selectComposition→renderMedia 封装
  orchestrator/            # 完整流水线
    text-only.ts           #   提示词→Gemini分镜→TTS→Pexels素材→ffmpeg→MP4
    facecam.ts             #   上传视频→转写→构建时间线→Remotion→MP4
  ai/                      # gemini.ts(客户端) / planner.ts(分镜规划) / visual-planner.ts(视觉注入)
  tools/                   # elevenlabs.ts / pexels.ts / gemini-transcribe.ts / ffmpeg.ts
  workflow/                # 项目文件体系（JSON/YAML 项目配置）
    types.ts               # VideoProjectConfig / ProjectSegment
    loader.ts              # JSON/YAML → 配置
    validator.ts           # 配置校验
    generator.ts           # 配置 → 生成 config.ts/timeline.ts/Root.tsx/index.ts
    templates/             # facecam.json / product-demo.json / text-only.json
bin/                       # opencut-init / validate / transcribe / render（ts-node 包装）
```

---

## 3. 视频处理流程（三条流水线）

### 3.1 CLI 手工流程（项目脚手架 + Remotion 渲染）
```
opencut-init my-video        → 生成 src/examples/my-video/（config/timeline/subtitles/Root/index）
放素材到 public/             → facecam.mp4 / bg-music.mp3 / screenshot.png
opencut-transcribe facecam   → Gemini 转写 → subtitles.ts（可选）
编辑 timeline.ts / config.ts
opencut-validate my-video    → 校验时间线
opencut-render my-video      → out/my-video.mp4（支持 --watch 热渲染 / --preview 开 studio）
```

### 3.2 Text-only 全 AI 流水线（POST /generate）
```
prompt → Gemini 分镜(ScenePlan: title/narration/scenes)
      → ElevenLabs TTS 配音（无 key 时降级 gTTS）
      → Pexels 按分镜并行下载素材（失败有通用兜底 query）
      → ffprobe 实测时长，按配音长度等比缩放片段
      → ffmpeg 拼接 + 生成 SRT 字幕 → output.mp4
```

### 3.3 Facecam 流水线（POST /facecam）
```
上传视频 → Gemini 转写(句子级时间戳) → 拆词级字幕
       → 构建 facecam-full 时间线（字幕开/气泡样式/倍速）
       → 复制视频到 public/jobs/<jobId>/（Remotion staticFile 可访问）
       → Remotion renderMedia(h264) → output.mp4
```

### 3.4 直接渲染 API（POST /render）
```
{ compositionId, entryPoint, inputProps } → Remotion bundle → selectComposition → renderMedia → MP4
```
这是最底层的可控点：**任意时间线只要编译成 Remotion Composition，就能经此接口渲染**。

---

## 4. 可被外部调用的位置（自动化控制点）

| 层 | 入口 | 方式 | 说明 |
|---|---|---|---|
| REST API | `POST /render` | HTTP | 任意 composition + inputProps 渲染，返回 jobId |
| REST API | `POST /generate` | HTTP | 全 AI 文生视频（需 Gemini/ElevenLabs/Pexels） |
| REST API | `POST /facecam` | HTTP multipart | 上传视频→转写→渲染（需 Gemini） |
| REST API | `GET /jobs/:id` | HTTP 轮询 | status: queued/running/done/error + phase（无百分比） |
| REST API | `GET /jobs/:id/download` | HTTP | 下载成品 MP4 |
| CLI | `bin/opencut-*` | 子进程 | init/validate/transcribe/render，ts-node 包装 |
| 程序化 | `src/engine` / `src/workflow` | npm 包 | 组件、时间线类型、项目生成器可直接 import |
| 插件 | `registerPlugin()` | 代码 | 渲染期扩展（对语音控制意义不大，可忽略） |

关键结论：**OpenCut 自带一个未被文档化的完整 REST API（Express + 磁盘 Job 队列），无需新增控制层即可由 Jarvis 调用。** 所有异步任务统一走 `jobId + 轮询` 模式，天然适合 Python 侧做 Adapter。

---

## 5. 环境依赖

| 依赖 | 必需 | 用途 | 备注 |
|---|---|---|---|
| `GEMINI_API_KEY` | 是 | 分镜规划 / 视频转写 | 与用户现有 DeepSeek key 不同，需单独申请 |
| `PEXELS_API_KEY` | text-only 必需 | 素材下载 | 免费申请 |
| `ELEVENLABS_API_KEY` | 否 | TTS 配音 | 缺失自动降级 gTTS |
| ffmpeg / ffprobe | 是 | 拼接/探测 | 需在 PATH |
| Chrome（Remotion） | 渲染时 | 无头渲染 | 首次渲染自动下载 ~150MB |
| `PORT` | 否 | API 端口 | 默认 3000 |

---

## 6. 对 Jarvis 集成的关键结论与风险

1. **REST API 是首选控制面**：Python Adapter 直接 `POST /render` + 轮询 `GET /jobs/:id`，比包一层 CLI 更稳定、可拿到 phase。
2. **Gemini 依赖冲突**：用户目前只有 DeepSeek key。OpenCut 的 AI 依赖点集中在 `src/ai/planner.ts`（分镜）与 `src/tools/gemini-transcribe.ts`（转写）。后续可用 Jarvis 的 Hermes/DeepSeek 替换分镜（接口是纯文本 JSON），转写可换本地 Whisper 或复用 Jarvis ASR——**首期可保留 Gemini（免费额度），替换作为 Phase 2 优化**。
3. **渲染是重活**：1 分钟视频渲染可能耗时数分钟，必须异步 job + 轮询，绝不能阻塞语音主循环；渲染期间 Jarvis 应口播"渲染中"。
4. **磁盘增长**：`jobs/<uuid>/`（素材+output.mp4）+ `public/jobs/` 双份拷贝，需要清理策略。
5. **API 无鉴权**：只应监听 `127.0.0.1`，不做公网暴露。
6. **"剪辑"的本质**：OpenCut 不做帧级精剪，它的"剪辑"= 生成/修改 `timeline.ts` + 渲染。用户已有素材的个性化剪辑（剪掉废片段/选精彩片段）需要 Video Agent 先做规划（用 LLM 把需求翻译成时间线/分镜），再交给 OpenCut 渲染。
7. **转写质量决定字幕**：facecam 流水线靠 Gemini 转写；中文视频需确认 Gemini 中文转写可用（可换 Whisper 兜底）。
8. **`/generate` 与 `/facecam` 未在 README 文档化**：代码可直接用，但升级上游时注意 API 变动；Adapter 应把对 API 的依赖收敛到一个文件。
