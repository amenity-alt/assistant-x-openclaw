# Jarvis Short Drama Mode — Phase 4 字幕与成片交付报告

> 分支：`codex/chat-panel-merged` ｜ 状态：完成 ｜ 承接 Phase 3 成片质量升级

## 1. 新增内容
| 能力 | 实现 |
|---|---|
| 对白字幕 | 每集生成 `episode_XX.srt`（按片头/转场偏移精确计算时间轴），并用 libass 将中文对白烧录进成片（`Heiti SC` 字体，白字黑边底部居中） |
| 场景卡去重 | 移除场景卡内的对白引号框，对白统一由烧录字幕承载，避免画面重复文本 |
| 成片目录打包 | 每集输出目录同时生成：`episode_XX.md`（剧本副本）、`project.json`（工程快照）、`SERIES_INDEX.txt`（全剧索引：EP/标题/时长/文件清单） |
| 进度阶段 | 渲染进度新增 `subtitles`（91-93%）/ `packaging`（97%）阶段，Flutter 面板实时显示 |

## 2. 一集成片产物（~/Movies/JarvisDramas/<剧名>/）
```
episode_XX.mp4        成片（片头+镜头+片尾+转场+BGM+烧录字幕）
episode_XX.srt        对白字幕文件（可外部使用/二次压制）
episode_XX.md         剧本副本
poster.jpg            剧集海报
project.json          工程快照
SERIES_INDEX.txt      全剧索引
```

## 3. 修复：xfade 时间线 bug
- 现象：多镜头淡入淡出后**视频流被截断为片头长度（3.04s）**，音频却正常（8.5s）——成片前 3 秒后就冻结。
- 根因：`xfade` offset 计算错误（`前缀和 - (t-1)*fade`，比正确时间点晚 0.5s；首个转场 offset 恰好等于片头时长，导致 xfade 无法渲染后续帧）。
- 修复：offset_t = Σ_{i≤t} d_i − t·fade（t 为转场序号，1-based）。
- 验证：视频流 8.52s = 音频 8.50s；4s 处字幕带检出 6050 白色像素（对白已烧录）。

## 4. 文件变更
- `src/drama_agent/production.py` — SRT/ASS 生成、字幕烧录、成片目录打包、xfade offset 修复
- `src/drama_agent/__init__.py` — 记录 `files["subtitles"]`、摘要带字幕路径
- `tests/test_drama_agent.py` — 字幕/打包/工程快照断言

## 5. 测试结果
- `python -m py_compile` 全部通过
- `tests/test_drama_agent.py`：**114/114 通过**（含真实 ffmpeg 渲染：片头/片尾/转场/BGM/海报/字幕/打包/取消）
- 成片校验：视频流 8.52s / 音频 8.50s / 音轨峰值 -13.9dB / 字幕带 6050 白像素
- `git diff --check` 通过

## 6. 下一步（Phase 5 候选）
- 真实视频模型后端（即梦/可灵/本地 Wan）接入 `ShotRenderer` 抽象
- 多角色分声线配音细化（已按性别/语言选声线，可扩展音色映射）
- 一键打包发布：全剧 zip（成片+字幕+海报+剧本+工程）
