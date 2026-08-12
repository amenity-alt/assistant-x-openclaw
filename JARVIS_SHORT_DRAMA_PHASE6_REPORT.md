# Jarvis Short Drama Mode — Phase 6 情绪化配音 + 发布包完善

> 分支：`codex/chat-panel-merged` ｜ 状态：完成 ｜ 承接 Phase 5 分声线配音 + 一键发布

## 1. 新增内容
| 能力 | 实现 |
|---|---|
| 情绪化配音 | 新增 `_MOOD_RATE` 镜头情绪词库，按 mood（紧张/愤怒/爆发/悲伤/温柔/平静/神秘…）叠加语速偏移，叠加在声线关键词之上 |
| 情绪词库 | 8 组：爆发/暴怒 +18、紧张/焦虑 +12、激动/激昂 +12、冲突 +10、悲伤/绝望 -10、温柔/治愈 -6、平静/舒缓 -5、神秘/悬疑 -8 |
| 横版海报 | 发布包新增 `POSTER.jpg`（1920x1080 JARVIS HUD 风格：剧名/类型/演员/集数） |
| 发布说明 | 发布包新增 `README.md`（文件说明 + macOS 播放指引），`RELEASE_INFO.txt` 增加发布包清单段 |

## 2. 配音效果示例
- 情绪「紧张/爆发」→ 语速 +12~+18，配合声线关键词（如 低沉）叠加
- 情绪「悲伤/绝望」→ 语速 -10，情绪低落时更慢更沉
- 优先级不变：角色显式音色 > 台词声线标注/性格关键词 > 性别+语言默认，情绪只做语速调制

## 3. 发布包结构（~/Movies/JarvisReleases/<剧名>_vN.zip）
```
RELEASE_INFO.txt   发布清单（含发布包说明段）
POSTER.jpg         全剧横版海报
README.md          发布说明（播放指引）
episode_XX.mp4     成片（+ srt/md/poster/project.json/SERIES_INDEX.txt）
```

## 4. 文件变更
- `src/drama_agent/production.py` — `_MOOD_RATE`、`_voice_plan(mood=)`、`_release_poster()`、`_release_readme()`、`publish_series()` 增加海报/README
- `tests/test_drama_agent.py` — 情绪语速 + 发布包内容 8 项新断言

## 5. 测试结果
- `python -m py_compile` 全部通过
- `tests/test_drama_agent.py`：**152/152 通过**（含真实 ffmpeg 渲染 + 发布包含横版海报/README + 情绪语速映射）
- `git diff --check` 通过

## 6. 下一步（Phase 7 候选）
- 真实视频模型后端（即梦/可灵/本地 Wan）接入 `ShotRenderer` 抽象，替换 ffmpeg 场景卡
- 多音色情绪：悲伤/愤怒切换不同音色（不只用语速）
- 发布包自动上传（S3/OSS）与分享链接
