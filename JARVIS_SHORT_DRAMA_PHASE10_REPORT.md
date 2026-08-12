# Jarvis Short Drama Mode — Phase 10 Jarvis HUD 模板 + 成片播放

> 分支：`codex/chat-panel-merged` ｜ 状态：完成 ｜ 承接 Phase 9 流式渲染进度

## 1. 新增内容
| 能力 | 实现 |
|---|---|
| Jarvis HUD 模板 | `_write_project()` 新增 `shots` 参数，为每个镜头叠加：暗角蓝光背景（vignette #2F8CFF）、右上角 `EP 01 · SHOT 01` 角标、场景关键词（大写淡入淡出，#8CC1FA PingFang SC 44px） |
| 对白音波动画 | 仅对白镜头注入 `audioWaveform`（48 条 / 高 52 / 底部 / #46E0A8 / intensity 0.5），随音乐节拍律动 |
| 成片播放 | 语音「播放第一集 / 打开第二集成片 / play episode 3」→ `cmd=play` → `_play()` 用 `open` 调 QuickTime 打开成品 mp4 |

## 2. 音波动画不显示的根因（引擎层）
- 现象：隔离测试与真实成片底部音波绿色像素均为 0，其它 HUD 元素正常。
- 排查：逐层二分定位到 **Remotion 的 `AbsoluteFill` 默认样式为 `display:flex; flexDirection:column`**；`AudioWaveform` 只覆盖了 `display`，未覆盖 `flexDirection`，导致 48 根 bar 沿纵向排列、交叉轴（宽度）为 0，全部不可见。
- 修复：`opencut/src/engine/AudioWaveform.tsx` 显式加 `flexDirection:"row"`（opencut 本地提交 `8686fa2`，仅 1 行，不动上游语义）。
- 验证：隔离 still 从 0 → 3446 绿色像素；真实成片两帧差分仅在底部 y 671-674 出现 360px 变化，确认音波律动生效。

## 3. 实测验证
- 真实渲染 still：1280x720，关键词 #8CC1FA、右上角角标、底部绿色音波全部出现。
- 播放：`play` 意图打桩验证 `subprocess.Popen(["open", video])` 调用与路径正确；无成片/不存在的集返回明确提示。
- `tests/test_drama_agent.py`：**210/210 通过**（新增：play 意图 3 例、模板断言 6 项、无重复 keywordStyle、播放流程 3 例）。

## 4. 文件变更
- `src/drama_agent/production.py` — `_write_project()` 新签名（shots/episode_number）与 HUD 模板生成
- `src/drama_agent/__init__.py` — `play` 分发与 `_play()`
- `src/drama_agent/intent_parser.py` — `_PLAY_RE` 意图解析
- `tests/test_drama_agent.py` — play + 模板断言
- opencut 侧：`src/engine/AudioWaveform.tsx`（本地提交 `8686fa2`，未推送上游）

## 5. 下一步（Phase 11 候选）
- 片头/片尾动效模板：标题卡 + 结尾「下集预告」入场动画
- 多集批量渲染队列：连续制作并预览 N 集
- OpenCut 成片自动上传后附上播放链接（含封面）
