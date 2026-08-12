# Jarvis Short Drama Mode — Phase 2 渲染流水线报告

> 分支：`codex/chat-panel-merged` ｜ 状态：完成 ｜ 承接 `JARVIS_SHORT_DRAMA_ARCHITECTURE.md` Phase 1

## 1. 目标
把 Phase 1 的「开始制作第X集」占位升级为真实渲染：
**镜头 Prompt → 时间线 → 剪辑 → 导出 MP4**，语音全程可指挥、可停止。

## 2. 渲染架构
```
DramaAgent._start_production（后台线程）
        │  on_progress(state, shot, total, pct, msg)
        ▼
EpisodeProducer.render(project, number, backend)
        │
        ├─ backend=ffmpeg（默认，离线可用）
        │    每镜头：PIL 场景卡（JARVIS HUD 深空风格）→ ffmpeg Ken Burns 缩放运镜
        │           → macOS say 角色配音（对白语言/角色性别选声线）→ 统一 h264+aac
        │    镜头间检查 cancel（threading.Event）→ concat demuxer 拼接
        │    → 导出 ~/Movies/JarvisDramas/<剧名>/episode_XX.mp4
        │
        └─ backend=opencut（语音「用AI制作」触发）
              每镜头：video_agent.run_sync(shot.video_prompt)（OpenCut AI 视频）
              统一转码到 1920x1080/25fps 后拼接；未配置 AI key 时明确报错并提示回退
```

## 3. 场景卡视觉（PIL，无需 WebView/外部素材）
- 深空渐变底 + 中心径向光晕 + 四角 HUD 亮角 + 细边框（JARVIS 蓝/青绿/紫/金轮换）
- 顶栏：`JARVIS DRAMA · 剧名` + `EP XX · SHOT NN/TT`
- 中央：场景名（STHeiti 中文字体）+ 人物 chip + 动作折行
- 左下：CAM / LIT / MOOD / STY / SFX·BGM 镜头参数行；右下时长
- 底部：对白引号框 + 配音声线标识（Tingting/Reed/Samantha/Alex 按语言与性别）

## 4. 语音命令
| 命令 | 动作 |
|---|---|
| `开始制作第一集` | 请求确认 → 本地(ffmpeg)渲染第1集 → 导出 MP4 并汇报路径 |
| `用AI制作第二集` | 请求确认 → OpenCut AI 后端渲染（需已配置 DeepSeek/Gemini key） |
| `停止制作` / `停止渲染` | 镜头间安全停止，汇报「已停止制作」 |
| `查看短剧进度` | 汇报当前阶段；渲染中会显示制作进度 |

制作进度通过 `drama:status` 推送给 Flutter 面板：状态（queued/preparing/rendering/concatenating/finalizing/done/failed/cancelled）+ 镜头进度 + 百分比，面板显示 `RENDER 02/07 · 42%`。

## 5. 文件变更
- `src/drama_agent/production.py`（新）— ShotRenderer 抽象、FFmpegShotRenderer、OpenCutShotRenderer、EpisodeProducer
- `src/drama_agent/models.py` — `DramaProject.production` 字段
- `src/drama_agent/__init__.py` — `produce` 确认流、`_start_production` 后台线程、`_stop_production`、进度推送、成品路径记录
- `src/drama_agent/intent_parser.py` — `stop` 指令 + `用AI制作` 后端标记
- `src/main.py` — `_DRAMA_LIKE_RE` 增加 停止制作/用AI制作；口播增加 producing
- `assistant_overlay/lib/drama_hud_controller.dart` — 解析 `production` 字段
- `assistant_overlay/lib/short_drama_panel.dart` — 制作进度条 + 后端标识
- `tests/test_drama_agent.py` — 新增真实 ffmpeg 渲染冒烟 + 取消 + 制作流程

## 6. 测试结果
- `python -m py_compile`（全部新增/修改文件）通过
- `tests/test_drama_agent.py`：**102/102 通过**（意图 30 条、状态机、全流程、持久化、真实 ffmpeg 渲染 640x360 双镜头、取消语义）
- `flutter analyze`：无 error，新文件 0 问题
- 成片校验：`~/Movies/JarvisDramas/<剧名>/episode_01.mp4`，4.02s / 176KB，h264+aac，画面含渐变/HUD/文字（非黑帧）

## 7. 已知边界与下一步（Phase 3）
- 默认后端为「分镜动画片」风格（场景卡 + 运镜 + 配音），不是真实实拍素材；OpenCut AI 后端可出真实素材但依赖 key 与网络
- BGM 暂未合成（对白音轨已就绪），Phase 3 可在 `_scene_card`/时间线加 `sine`/环境音混音
- 真实视频模型（即梦/可灵/本地 Wan）可在 `ShotRenderer` 抽象下新增后端，无需改动编排层
