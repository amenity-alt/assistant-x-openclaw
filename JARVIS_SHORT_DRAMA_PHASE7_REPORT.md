# Jarvis Short Drama Mode — Phase 7 情绪音色切换 + 发布上传框架

> 分支：`codex/chat-panel-merged` ｜ 状态：完成 ｜ 承接 Phase 6 情绪语速 + 发布包完善

## 1. 新增内容
| 能力 | 实现 |
|---|---|
| 情绪切换音色 | 新增 `_MOOD_VOICES` 强情绪音色表：悲伤→`Whisper`、愤怒/爆发→`Daniel`(en)/`Meijia`(zh女)、神秘→`Whisper`/`Sandy`、机械→`Zarvox`，优先级：角色显式音色 > 情绪音色 > 声线关键词 > 默认 |
| 语速叠加 | 情绪音色仍叠加 `_MOOD_RATE` 语速调制（悲伤 -10、愤怒 +18 等） |
| 发布上传框架 | 新增 `upload_release()`：`auto`（读 `JARVIS_UPLOAD_TARGET`：本地目录复制 / `s3://bucket/prefix` boto3 上传）/ `local` / `none` |
| 优雅降级 | 未配置上传目标、未装 boto3、上传失败均不中断发布流程，仅口播说明原因 |

## 2. 情绪音色示例
- `mood="悲伤"` + 英文对白 → `Whisper`（耳语感），语速 -10
- `mood="愤怒/暴怒"` → 英文男声 `Daniel`、中文女声 `Meijia`，语速 +18
- `mood="机械/AI"` → `Zarvox` 电子音
- 角色显式 `voice: "Grandpa"` 始终优先于情绪音色

## 3. 上传配置
```bash
# 本地目录（默认，无额外依赖）
export JARVIS_UPLOAD_TARGET=~/Movies/JarvisReleases/upload
# S3（需 pip install boto3 并配置 AWS 凭证）
export JARVIS_UPLOAD_TARGET=s3://my-bucket/jarvis-dramas
```
说「打包发布」后，Jarvis 汇报：`打包完成：N 集成片…（X MB）。已上传：<url>`
未配置时：`…（未上传：未配置上传目标…）`，不影响成片与本地 zip。

## 4. 文件变更
- `src/drama_agent/production.py` — `_MOOD_VOICES`、`_voice_plan` 情绪音色分支、`upload_release()`
- `src/drama_agent/__init__.py` — `_publish` 完成后自动尝试上传并口播结果
- `tests/test_drama_agent.py` — 情绪音色 + 上传框架 10 项新断言

## 5. 测试结果
- `python -m py_compile` 全部通过
- `tests/test_drama_agent.py`：**162/162 通过**（含情绪音色中英映射、显式音色优先、上传跳过/本地复制）
- `git diff --check` 通过

## 6. 下一步（Phase 8 候选）
- 真实视频模型后端（即梦/可灵/本地 Wan）接入 `ShotRenderer` 抽象 —— 需提供平台 API key
- 多角色剧本级音色指定（在剧本中直接写「用 Meijia 配林晓」）
- 发布包自动生成分享短链（本地 HTTP 服务 / 网盘上传）
