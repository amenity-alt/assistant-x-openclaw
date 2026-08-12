# Jarvis Short Drama Mode — Phase 3 成片质量升级报告

> 分支：`codex/chat-panel-merged` ｜ 状态：完成 ｜ 承接 Phase 2 渲染流水线

## 1. 新增内容
在 Phase 2「分镜动画片」流水线基础上，离线打磨成片质感：

| 能力 | 实现 |
|---|---|
| 多样运镜 | 每镜头按序号轮换 6 种 Ken Burns：推近/拉远/左→右/右→左/上→下/下→上平移，避免千篇一律 |
| 片头片尾卡 | 片头「JARVIS DRAMA PRESENTS + 剧名 + EPISODE XX/YY」；片尾按集数显示 `TO BE CONTINUED` / `THE END` |
| 淡入淡出转场 | 视/音频双 `xfade` 链，镜头间 0.5s 淡入淡出（自动按镜头时长计算 offset） |
| BGM 氛围音 | 棕色噪声低通 + 音量 0.10 + 首尾淡入淡出，`amix` 混入成片（不压对白） |
| 剧集海报 | 竖版 1280x1600 `poster.jpg`（剧名/EP/人物/工作室落款），与成片同目录导出 |
| 批量制作 | 「制作全部集 / 全部制作」→ 确认 → 顺序渲染所有未完成集，逐集汇报、可随时停止 |
| 取消语义 | 批量模式下镜头间/集间检查 `cancel`，停止后保留已完成集 |

## 2. 成片结构（一集）
```
片头卡(3s) → 镜头1(4-8s, 运镜轮换+配音) → … → 镜头N → 片尾卡(3s)
  全部经 0.5s 淡入淡出拼接；总时长 = 片头+Σ镜头+片尾-转场重叠
```

## 3. 语音命令
| 命令 | 动作 |
|---|---|
| `开始制作第一集` | 确认 → 渲染单集（片头+镜头+片尾+BGM+海报） |
| `用AI制作第二集` | 确认 → OpenCut AI 后端（需 AI key） |
| `制作全部集` / `全部制作` | 确认 → 顺序渲染所有未完成集 |
| `停止制作` / `停止渲染` | 安全停止（已完成的集保留） |

## 4. 文件变更
- `src/drama_agent/production.py` — 运镜变体、片头片尾卡、xfade 转场、BGM 混音、海报、批量进度回调
- `src/drama_agent/__init__.py` — `produce_all` 确认流、`_start_batch_production`、批量进度推送
- `src/drama_agent/intent_parser.py` — `produce_all` 指令
- `src/main.py` — `_DRAMA_LIKE_RE` 增加 制作全部/全部制作
- `tests/test_drama_agent.py` — 批量制作流程 + 新渲染特性断言

## 5. 测试结果
- `python -m py_compile` 全部通过
- `tests/test_drama_agent.py`：**109/109 通过**（含真实 ffmpeg 渲染：片头/片尾/转场/BGM/海报/取消）
- 成片校验：`~/Movies/JarvisDramas/测试短剧/episode_01.mp4` = 8.5s / 189KB / h264+aac，音轨峰值 -13.9dB（非静音），`poster.jpg` 67KB
- `git diff --check` 通过

## 6. 下一步（Phase 4 候选）
- 真实视频模型后端（即梦/可灵/本地 Wan）接入 `ShotRenderer` 抽象
- 对白字幕烧录（libass 中文字体）与多声道混音细化
- 自动发布/一键成片目录打包（含海报+字幕文件+工程文件）
