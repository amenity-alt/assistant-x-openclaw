# Jarvis Short Drama Mode — Phase 9 OpenCut 渲染进度 + 中途取消

> 分支：`codex/chat-panel-merged` ｜ 状态：完成 ｜ 承接 Phase 8 OpenCut 成片后端

## 1. 新增内容
| 能力 | 实现 |
|---|---|
| 流式渲染进度 | `_render_remotion()` 用 Popen 管道流式读取 `npx remotion render` 输出，解析 `Rendered X/N` 帧进度并映射到 55%→97%，Flutter 面板实时看到逐帧推进 |
| 中途取消 | 渲染过程中检测 cancel 事件 → 终止 remotion 子进程（SIGTERM，超时 SIGKILL）→ 抛 `ProductionCancelled`，语音「停止制作」可中断渲染 |
| 超时保护 | 渲染超时 30 分钟自动终止并报错 |
| 进度映射 | `_oc_progress_pct(done, total)`：55% + done/total×42，帧推进可视化 |

## 2. 修复的问题
- **进度回调静默丢失**：`render()` 内部 `progress` 闭包为 4 参数，`render_episode.report` 却按 5 参数调用，TypeError 被 `except: pass` 吞掉，导致 OpenCut 阶段进度完全不上报。已统一为 4 参数约定（外部回调仍为 `(state, shot, total, pct, msg)` 5 参数，由 `render()` 补全）。
- 渲染阶段此前卡在 55% 直到结束；现在按帧推进。

## 3. 实测验证
- 真实渲染：12s 成片，进度档位 22→35→55→56…→97→100，311 个进度事件，全部上报
- 中途取消：渲染开始 2s 后置 cancel → `ProductionCancelled` 生效，子进程终止
- `tests/test_drama_agent.py`：**196/196 通过**（新增 8 项：进度解析/映射/取消处理）

## 4. 文件变更
- `src/drama_agent/production.py` — `_render_remotion()`、`_on_render_line()`、`_render_progress()`、`_oc_progress_pct()`、report 参数修正
- `tests/test_drama_agent.py` — 进度解析与取消 8 项断言

## 5. 下一步（Phase 10 候选）
- 即梦/可灵真实镜头画面：先生成镜头素材视频，再经 OpenCut 拼接（需对应平台 API key）
- OpenCut 模板化：片头/片尾/字幕动效固化成 Jarvis 专属模板
- 渲染完成自动预览：渲染后直接打开成片（`open <mp4>`）
