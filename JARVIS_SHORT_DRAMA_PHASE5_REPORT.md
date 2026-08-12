# Jarvis Short Drama Mode — Phase 5 分声线配音 + 一键打包发布

> 分支：`codex/chat-panel-merged` ｜ 状态：完成 ｜ 承接 Phase 4 字幕与成片交付

## 1. 新增内容
| 能力 | 实现 |
|---|---|
| 多角色分声线配音 | 新增 `_voice_plan()`：角色显式音色 > 台词声线标注/性格关键词 > 性别+语言默认，三级优先；同时输出语速 |
| 声线关键词库 | 11 组性格/声线关键词（苍老/慈祥/小孩/沉稳/冷酷/霸气/阴险/低沉/甜美/活泼/激动），映射到中文/英文、男/女音色并调整语速（130–260） |
| 角色显式音色 | 人物配置 `voice` 字段填 macOS say 内置音色名（如 Grandpa/Meijia）时直接采用，自动校验可用性并缓存 |
| 一键打包发布 | `publish_series()`：全剧成片目录 → 单个 zip（`RELEASE_INFO.txt` 清单 + 全部 mp4/srt/md/poster/project.json/SERIES_INDEX.txt） |
| 版本递增 | 发布包自动递增 `<剧名>_v1.zip / v2 / …`，输出到 `~/Movies/JarvisReleases/`，不覆盖旧包 |
| 语音入口 | 新增意图 `publish`：说「打包发布 / 发布短剧 / 一键发布 / release」即触发，后台线程打包，完成后口播路径并推 HUD `DRAMA RELEASED` |

## 2. 声线映射示例
- 台词标注「低沉,沙哑」→ 英文男声 `Daniel`、中文男声 `Reed`，语速 -15
- 性格「甜美/活泼/可爱」→ `Tingting`/`Samantha`/`Alice`，语速 +8~+15
- 性格「苍老/慈祥」→ `Grandpa`/`Grandma`/`Fred`，语速 -10~-25
- 角色 `voice: "Meijia"` 显式指定 → 直接用 `Meijia`

## 3. 一键发布产物（~/Movies/JarvisReleases/）
```
<剧名>_v1.zip
├── RELEASE_INFO.txt   发布清单（剧名/类型/集数/文件清单+大小/生成时间）
├── episode_01.mp4     成片
├── episode_01.srt     字幕
├── episode_01.md      剧本副本
├── poster.jpg         剧集海报
├── project.json       工程快照
└── SERIES_INDEX.txt   全剧索引
```

## 4. 文件变更
- `src/drama_agent/production.py` — `_voice_plan()`、声线关键词库、`publish_series()`、`_release_manifest()`、`render_card/render_shot` 支持语速
- `src/drama_agent/intent_parser.py` — 新增 `publish` 意图
- `src/drama_agent/__init__.py` — `_publish()` 后台线程入口 + 分发
- `tests/test_drama_agent.py` — 意图/声线/发布 30 项新断言

## 5. 测试结果
- `python -m py_compile` 全部通过
- `tests/test_drama_agent.py`：**144/144 通过**（含真实 ffmpeg 渲染 + 真实渲染目录打包发布 + 声线映射 + 版本递增 + 无成片报错）
- `git diff --check` 通过

## 6. 下一步（Phase 6 候选）
- 真实视频模型后端（即梦/可灵/本地 Wan）接入 `ShotRenderer` 抽象，替换 ffmpeg 场景卡
- 配音情绪化：按镜头 mood（紧张/愤怒/悲伤）叠加语速与音色变化
- 发布包自动生成 `POSTER.png` 横版海报与 README 说明页
