# Jarvis Short Drama Mode — Phase 8 OpenCut 成片渲染后端

> 分支：`codex/chat-panel-merged` ｜ 状态：完成 ｜ 承接 Phase 7 情绪音色 + 发布上传

## 1. 背景
用户确认「方案 A」：把 OpenCut 作为 Jarvis 短剧的**成片渲染后端**，替换 ffmpeg 拼装层。
原 `OpenCutShotRenderer` 引用不存在的 `video_agent` Python 模块，必然报错；已整体重写。

## 2. OpenCut 是什么（实测确认）
- OpenCut = Remotion（React 逐帧渲染）+ 程序化时间线引擎，**不是文生视频模型**
- 能力：把素材 + 字幕 + 时间线渲染成专业 MP4；本机 `~/Documents/ChatGPT/opencut` 已装好依赖
- Jarvis 接入方式：生成 OpenCut 工程（index/Root/config/timeline/subtitles）→ `npx remotion render` 一次渲染整集

## 3. 新后端 OpenCutRenderBackend
| 环节 | 实现 |
|---|---|
| 工程位置 | `<opencut>/out/jarvis-dramas/<剧名>_epXX/`（opencut 的 `.gitignore` 已忽略 `out/`，不污染源码目录） |
| 引擎导入 | 绝对路径导入 `<opencut>/src/engine`（实测 Remotion 可打包），避免相对路径限制 |
| 素材 | 片头卡 / 每镜头 HUD 场景卡 / 片尾卡 → `public/`，`--public-dir` 指定静态目录 |
| 配音 | `facecam.mp4` = 黑底视频 + 各镜头对白按时间轴 `adelay` 排布；BGM 走 `bgMusicAsset` |
| 字幕 | 生成 `subtitles.ts`（无词级时间戳时按字/词均匀合成），Remotion 字幕叠加渲染进画面，带黄色活动词高亮，中文字体 PingFang SC |
| 渲染 | `npx remotion render index.ts JarvisDramaEpXX out.mp4`（cwd=opencut 根，超时 30min） |
| 编排 | `EpisodeProducer.render(backend="opencut")` 整集渲染后仍走统一打包（SRT/海报/剧本/工程快照/索引） |

## 4. 修复的关键问题
| 问题 | 修复 |
|---|---|
| 旧后端引用不存在的 `video_agent` | 整类重写为 OpenCutRenderBackend |
| `_build_facecam` 命令重复 `ffmpeg` 参数 | 去掉 inputs 前缀重复，命令恢复正确 |
| Remotion 静态资源 404 | 加 `--public-dir=<proj>/public` |
| macOS `zh_CN` 男声（Reed/Eddy/Grandpa 等）合成中文为 0.01s 静音 | `_dialogue_wav` 增加 `_is_silent_audio` 静音检测 + 自动回退 Tingting/Samantha（实测 Reed→Tingting，-17dB） |

## 5. 实测验证（真实渲染）
- `EpisodeProducer(width=1280x720, fps=25).render(backend="opencut")` 成功
- 成片：12.05s（片头3s + 2镜头各3s + 片尾3s），h264+aac，视频/音频流完整
- 音轨峰值 -7.6dB（对白 + BGM 均在）；字幕带检出白像素 604 + 黄色高亮词 102
- 生成工程位于 `out/jarvis-dramas/`，可用 `npx remotion studio` 预览；OpenCut 仓库 git status 干净
- Remotion bundle 已缓存，后续渲染更快（9s 时长示例约 8s 完成渲染）

## 6. 文件变更
- `src/drama_agent/production.py` — OpenCutRenderBackend（整类重写）、`_run` 支持 cwd/timeout、`_is_silent_audio`、`_dialogue_wav` 静音回退、render() opencut 分支
- `tests/test_drama_agent.py` — 后端解析/工程生成/合成词/静音回退/opencut 编排 26 项新断言

## 7. 测试结果
- `python -m py_compile` 全部通过
- `tests/test_drama_agent.py`：**188/188 通过**
- `git diff --check` 通过
- 真实 OpenCut 渲染冒烟：通过（含音画时长/音量/字幕像素校验）

## 8. 语音入口
「用AI制作第X集」→ `backend="opencut"` → OpenCut 渲染（无需 API key，纯本地）。

## 9. 下一步（Phase 9 候选）
- 即梦/可灵真实镜头画面生成：先产出镜头素材视频，再经 OpenCut 拼接（方案 B）
- OpenCut 模板化：把片头/片尾/字幕动效固化成 Jarvis 专属模板
- 渲染进度细化：Remotion `renderProgress` 回调接入 on_progress
