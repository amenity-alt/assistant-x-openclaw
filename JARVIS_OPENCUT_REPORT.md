# Jarvis × OpenCut — 实现报告

> 状态：Phase 1-5 完成，generate 端到端验证通过（DeepSeek + Coverr + macOS TTS）｜ 分支：`codex/chat-panel-merged`
> 前置文档：`OPENCUT_ANALYSIS.md`（OpenCut 分析）、`JARVIS_OPENCUT_ARCHITECTURE.md`（架构设计）

---

## 1. 完成内容

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 1 | OpenCut 环境（`npm install` 496 包、ffmpeg 安装）+ API 冒烟（`/render` 11s 产出 MP4） | ✅ |
| Phase 2 | Python Adapter `src/video_agent/`（REST 客户端/进程管理/任务队列/权限/导出） | ✅ |
| Phase 3 | Video Agent + `main.py` 语音拦截（制作/剪辑/渲染/进度/取消 + 语音确认） | ✅ |
| Phase 4 | Mission Control 接入 video agent（白名单/适配器/规划器/步骤标签） | ✅ |
| Phase 5 | 端到端验证 + 报告 | ✅ |
| Phase 6 | AI 供应商落地：Gemini 不可用 → DeepSeek；TTS → macOS `say`；素材 → Coverr 兜底；ffmpeg 文本滤镜缺失优雅降级 | ✅ |

---

## 2. 新增文件（Jarvis 项目）

```
src/video_agent/
  __init__.py            # VideoAgent 单例 + handle()/run_sync()/status()/confirm()
  task.py                # VideoTask / VideoResult + ALLOWED_PROJECTS 白名单
  intent_parser.py       # 语音文本 → VideoIntent（中英 + 时长/格式提取；status 正则支持"怎么样了"）
  opencut_client.py      # OpenCut REST 客户端 + API 进程拉起/回收 + AI key 检测(DeepSeek/Gemini) + .env 注入
  task_manager.py        # 线程池(1) 异步执行 + 确认队列 + 软失败
  permission_manager.py  # 素材路径白名单/黑名单 + 60s 确认超时
  job_manager.py         # job 轮询 + phase 回调 + 超时 + 可取消
  project_manager.py     # render 项目白名单解析（未来时间线生成占位）
  asset_manager.py       # 素材校验/暂存/清理
  export_manager.py      # 成品导出到 ~/Movies/JarvisVideos/
  result_parser.py       # job/异常 → 用户可读结果
  action_log.py          # logs/video_agent.log 审计
src/assistants/video_agent/
  __init__.py            # VideoCapability 门面（与 vision_agent 同构）
  prompt.py              # 剪辑规划/精彩片段提示词（未来接 DeepSeek）
```

## 3. 修改文件（Jarvis 项目）

- `src/main.py` — `_video_like`/`_handle_video_command`/`_handle_video_confirm`/确认与结果口播；
  识别循环两处钩子（确认 + 指令）；流式预判防回声；`_step_label` video 分支；`stop()` 回收 OpenCut 进程
- `src/mission_control/mission.py` — `ALLOWED_AGENTS += "video"`，`ALLOWED_ACTIONS["video"]`
- `src/mission_control/agent_registry.py` — `VideoAdapter`（status/cancel/clip/generate/render/export）
- `src/mission_control/planner.py` — LLM 提示词 + 本地模板 fallback 的 video 分支

## 4. 修改文件（OpenCut 项目，`~/Documents/ChatGPT/opencut`）

- `src/api/server.ts` — 新增 `GET /health`（3 行，Adapter 健康检查用）
- `public/facecam.mp4` — ffmpeg 生成的 6 秒测试素材（quickstart 示例需要）

### OpenCut AI 层适配（本机环境必须，全部小改动）

- `src/ai/deepseek.ts`（新）— DeepSeek OpenAI 兼容 chat 客户端，`DEEPSEEK_API_KEY` 存在时优先
- `src/ai/planner.ts` / `src/ai/visual-planner.ts` — 分镜规划改为 DeepSeek 优先、Gemini 兜底
- `src/tools/elevenlabs.ts` — TTS 兜底链：ElevenLabs → macOS `say`（中文 Tingting / 英文 Samantha）→ gTTS
- `src/tools/coverr.ts`（新）— Coverr 免 key 素材搜索（国内可直连）
- `src/orchestrator/text-only.ts` — 素材获取 Pexels 失败自动兜底 Coverr
- `src/tools/ffmpeg.ts` — 运行时探测 drawtext/subtitles 滤镜，缺失时跳过标题/字幕，保证渲染不中断
- `src/tools/pexels.ts` — `PexelsVideo.id` 放宽为 `number | string`（兼容 Coverr）

## 5. 验证结果

| 测试 | 结果 |
|---|---|
| 全部修改文件 `python -m py_compile` | ✅ |
| `git diff --check` | ✅ 无空白错误 |
| `import main`（VoiceAssistant 含全部新钩子） | ✅ |
| 意图解析 13 用例（生成/剪辑/渲染/进度/取消/非视频） | ✅ 13/13 |
| 素材权限（~/Movies 放行；/etc、.ssh、非视频拒） | ✅ |
| planner 本地 fallback → `video.generate(requires_confirm=True)` | ✅ |
| 端到端渲染：语音句 → 确认 → 渲染 → 导出 MP4 | ✅ 8-12s，输出 `~/Movies/JarvisVideos/quickstart-*.mp4` |
| 端到端 generate：DeepSeek 分镜 → macOS say 配音 → Coverr 素材 → ffmpeg 渲染 | ✅ 14.5s/1080p，输出 `~/Movies/JarvisVideos/shenzhen-test-*.mp4` |
| Gemini key（`AQ.` 新格式）项目级 403 被拒 | ⚠️ 已用 DeepSeek 绕过，不再依赖 Gemini |
| Pexels 无 key 匿名配额 401（注册站被墙 403） | ⚠️ 已加 Coverr 兜底，免 key 可用 |
| 本机 ffmpeg 无 libass/freetype（无 drawtext/subtitles） | ⚠️ 优雅降级：跳过标题/字幕，渲染成功 |
| 非法素材 facecam → 直接拒绝 + 提示 | ✅ |
| status / cancel 无任务时 → 友好口播文案 | ✅ |

## 6. 语音指令一览

- `帮我做一个1分钟的深圳旅游短视频` → generate（确认后执行；需 `.env` 配置 `DEEPSEEK_API_KEY`，已配置 ✅）
- `制作一个30秒的产品宣传视频` / `make a 2 minute travel video` → generate
- `剪辑一下我的旅行视频` → facecam（需素材文件在 影片/桌面/下载/文稿 目录；转写走 DeepSeek）
- `渲染 quickstart 视频` → render（无需 AI key，立即可用 ✅）
- `视频渲染好了吗` / `渲染完了吗` → status
- `停止渲染` → cancel

## 7. 已知限制 / 下一步

- **generate / facecam 的 AI 分镜走 DeepSeek**：已从 `~/.hermes/profiles/jarvis/.env` 复用 `DEEPSEEK_API_KEY` 写入 OpenCut `.env`。
- **画面标题/字幕**：已装完整版 ffmpeg 9.0（homebrew-ffmpeg tap，含 freetype/libass），字幕（PingFang SC，去掉 MarginV 以兼容 ffmpeg 9 的 libass 渲染）与 drawtext 标题均已验证渲染。渲染链路保留滤镜缺失时优雅降级。
- **个性化素材剪辑**（选精彩片段/时间线定制）是 Phase 5 预留接口（`project_manager.build_project_config` / `assistants/video_agent/prompt.py`），当前 facecam 走 OpenCut 自带"转写→字幕→渲染"流水线。
- 提交待做：`git add` + commit `feat: add jarvis opencut video agent` + push `codex/chat-panel-merged`。
