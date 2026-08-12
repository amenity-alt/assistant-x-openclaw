#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Short Drama Agent Phase 1 测试：意图解析 / 状态机 / 全流程(模板兜底) / 持久化。

运行：venv/bin/python tests/test_drama_agent.py
"""

import json
import os
import zipfile as _zipfile
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

# ── 打桩：跳过真实 LLM（Hermes/DeepSeek），走本地模板兜底 ──
import drama_agent._llm as _llm_mod
import drama_agent.planner as _planner_mod
import drama_agent.character_agent as _char_mod
import drama_agent.episode_writer as _writer_mod
import drama_agent.prompt_agent as _prompt_mod

for _mod in (_llm_mod, _planner_mod, _char_mod, _writer_mod, _prompt_mod):
    _mod.llm_json = lambda *a, **k: None
    if hasattr(_mod, "llm_text"):
        _mod.llm_text = lambda *a, **k: None

FAIL = []
PASS = []


def check(name, cond, extra=""):
    if cond:
        PASS.append(name)
        print(f"  ✓ {name}")
    else:
        FAIL.append(name)
        print(f"  ✗ {name}  {extra}")


# ── 1. 意图解析 ──────────────────────────────────────────
from drama_agent import intent_parser

CASES = [
    ("短剧剪辑", "enter"),
    ("开启短剧模式", "enter"),
    ("short drama mode", "enter"),
    ("帮我做一个10集每集1分钟的都市逆袭短剧", "enter"),
    ("查看短剧进度", "status"),
    ("短剧进度怎么样", "status"),
    ("重新规划剧情", "plan"),
    ("重新设计", "plan"),
    ("修改人物", "character"),
    ("把女主角改成短发", "character"),
    ("查看第一集", "episode_view"),
    ("看看第二集", "episode_view"),
    ("重新写第一集", "episode_rewrite"),
    ("重写第2集", "episode_rewrite"),
    ("生成第一集提示词", "prompts"),
    ("生成第一集镜头提示词", "prompts"),
    ("开始制作第一集", "produce"),
    ("开始制作", "produce"),
    ("用AI制作第二集", "produce"),
    ("制作全部集", "produce_all"),
    ("全部制作", "produce_all"),
    ("停止制作", "stop"),
    ("停止渲染", "stop"),
    ("打包发布", "publish"),
    ("发布短剧", "publish"),
    ("一键发布", "publish"),
    ("release drama", "publish"),
    ("暂停短剧", "pause"),
    ("继续短剧", "resume"),
    ("进入下一集", "next"),
    ("重新剪辑这一集", "reclip"),
    ("确认", "yes"),
    ("好的", "yes"),
    ("取消", "no"),
    ("退出短剧", "exit"),
    ("关闭短剧模式", "exit"),
]

print("== 1. 意图解析 ==")
for text, want in CASES:
    got = intent_parser.parse(text).cmd
    check(f"parse({text!r}) -> {want}", got == want, f"got {got}")

fields = intent_parser.collect_fields("帮我做一个10集每集1分钟的都市逆袭短剧，赛博朋克风格")
check("collect_fields: 10集", fields.get("episodes") == 10, str(fields))
check("collect_fields: 每集1分钟", fields.get("duration") == 60, str(fields))
check("collect_fields: 都市", fields.get("genre") == "都市", str(fields))
check("collect_fields: 赛博朋克", fields.get("style") == "赛博朋克", str(fields))
check("collect_fields: 主题(都市逆袭)", fields.get("theme") == "都市逆袭", str(fields))

# ── 2. 状态机 ────────────────────────────────────────────
print("== 2. 状态机 ==")
from drama_agent.models import DramaProject, DramaStatus
from drama_agent.state_machine import DramaStateMachine

sm = DramaStateMachine()
p = DramaProject(status=DramaStatus.COLLECTING)
check("COLLECTING->PLANNING", sm.can(DramaStatus.COLLECTING, DramaStatus.PLANNING))
check("PLANNING->AWAITING_CONFIRM", sm.can(DramaStatus.PLANNING, DramaStatus.AWAITING_CONFIRM))
check("AWAITING_CONFIRM->EPISODE_DESIGN", sm.can(DramaStatus.AWAITING_CONFIRM, DramaStatus.EPISODE_DESIGN))
check("AWAITING_CONFIRM->PROMPTS", sm.can(DramaStatus.AWAITING_CONFIRM, DramaStatus.PROMPTS))
check("AWAITING_CONFIRM->PLANNING", sm.can(DramaStatus.AWAITING_CONFIRM, DramaStatus.PLANNING))
check("EPISODE_DESIGN->AWAITING_CONFIRM", sm.can(DramaStatus.EPISODE_DESIGN, DramaStatus.AWAITING_CONFIRM))
check("PROMPTS->AWAITING_CONFIRM", sm.can(DramaStatus.PROMPTS, DramaStatus.AWAITING_CONFIRM))
check("非法迁移拒绝(IDLE->COMPLETED)", not sm.can(DramaStatus.IDLE, DramaStatus.COMPLETED))
try:
    sm.transition(p, DramaStatus.EPISODE_DESIGN)
    check("非法迁移抛异常", False)
except ValueError:
    check("非法迁移抛异常", True)

# ── 3. 全流程（模板兜底，无 LLM）──────────────────────────
print("== 3. 全流程 ==")
from drama_agent import DramaAgent
from drama_agent.store import DramaProjectStore

# 隔离 store：临时目录
tmp_root = tempfile.mkdtemp(prefix="drama_test_")

def _fresh_agent():
    a = DramaAgent()
    a._store = DramaProjectStore(root=tmp_root)
    return a

agent = _fresh_agent()
messages = []
agent.on_message = lambda d: messages.append(d.get("message", ""))
agent.on_confirm_request = lambda pid, ph, smy: messages.append(f"[确认:{ph}] {smy[:50]}")

def wait_idle(target=None, timeout=60):
    target = target or agent
    t0 = time.time()
    while target._busy and time.time() - t0 < timeout:
        time.sleep(0.2)
    return not target._busy

r = agent.handle("短剧剪辑")
check("enter 只问需求", r.get("status") == "collecting", str(r))
r = agent.handle("做一个10集每集1分钟的都市逆袭短剧，赛博朋克风格")
check("需求收集后开始规划", r.get("status") == "planning", str(r))
check("规划在后台完成", wait_idle())
p = agent.current_project
check("项目标题", p.title == "都市逆袭", p.title)
check("总集数=10", p.total_episodes == 10, str(p.total_episodes))
check("人物已生成", len(p.characters) >= 2, str(len(p.characters)))
check("分集目标=10", len(p.episode_goals) == 10, str(len(p.episode_goals)))
check("进入待确认", p.status.value == "awaiting_confirm", p.status.value)

r = agent.handle("确认")
check("确认规划 → 写剧本", r.get("status") == "writing", str(r))
check("剧本后台完成", wait_idle())
p = agent.current_project
ep1 = p.episode(1)
check("第1集剧本就绪", ep1 is not None and ep1.status == "script_ready")
check("第1集镜头数>=3", len(ep1.shots) >= 3, str(len(ep1.shots)))
check("剧本文件已写", os.path.isfile(ep1.files.get("script.md", "")))
check("分镜文件已写", os.path.isfile(ep1.files.get("storyboard.json", "")))

r = agent.handle("好的")
check("确认剧本 → 生成提示词", r.get("status") == "prompting", str(r))
check("提示词后台完成", wait_idle())
p = agent.current_project
ep1 = p.episode(1)
check("第1集 prompts_ready", ep1.status == "prompts_ready", ep1.status)
check("镜头含 video_prompt", all(s.video_prompt for s in ep1.shots))
prompts_dir = os.path.join(tmp_root, p.id, "episodes", "episode_01", "prompts")
check("prompts 目录已写", len(os.listdir(prompts_dir)) == len(ep1.shots), os.listdir(prompts_dir))

r = agent.handle("查看第一集")
check("查看第一集", r.get("status") == "ok", str(r.get("message", ""))[:60])
r = agent.handle("短剧进度")
check("进度汇报", "第 1/10 集" in r.get("message", ""), str(r.get("message", ""))[:80])

r = agent.handle("确认")
check("确认提示词 → 下一集", r.get("status") == "writing", str(r))
check("下一集后台完成", wait_idle())
p = agent.current_project
check("当前集=2", p.current_episode == 2, str(p.current_episode))

r = agent.handle("把女主角改成短发")
check("修改人物请求确认", r.get("status") == "confirm", str(r.get("message", ""))[:80])
p = agent.current_project
check("人物已改短发", p.characters[0].hairstyle == "短发", p.characters[0].hairstyle)
r = agent.handle("确认")
check("人物同步完成", r.get("status") == "ok", str(r.get("message", ""))[:80])

r = agent.handle("暂停短剧")
check("暂停", r.get("status") == "ok")
r = agent.handle("继续短剧")
check("继续", r.get("status") == "ok")

r = agent.handle("开始制作第一集")
check("制作需确认", r.get("status") == "confirm", str(r))
# 用假 producer 快速走完制作流程（真实 ffmpeg 渲染在 §5 单测）
class _FakeProducer:
    def render(self, *a, **k):
        return {"status": "success", "output": "/tmp/fake_ep01.mp4",
                "shots": 3, "duration": 15, "backend": "ffmpeg"}

agent._producer = _FakeProducer()
r = agent.handle("确认")
check("确认后开始制作", r.get("status") == "producing", str(r))
check("制作后台完成", wait_idle())
p = agent.current_project
check("第1集已制作", p.episode(1).status == "produced", str(p.episode(1).status))
check("成品路径记录", p.episode(1).files.get("video") == "/tmp/fake_ep01.mp4")
check("production done", p.production.get("state") == "done", str(p.production))
r = agent.handle("制作全部集")
check("批量制作需确认", r.get("status") == "confirm", str(r))
r = agent.handle("确认")
check("确认后批量制作", r.get("status") == "producing", str(r))
check("批量后台完成", wait_idle())
p = agent.current_project
check("全部集已制作", all(e.status == "produced" for e in p.episodes),
      str([(e.number, e.status) for e in p.episodes[:4]]))
r = agent.handle("打包发布")
check("一键发布", r.get("status") == "publishing", str(r))
check("发布后台完成", wait_idle())
r = agent.handle("重新剪辑这一集")
check("重剪占位(Phase2)", r.get("status") == "phase2", str(r))
r = agent.handle("退出短剧")
check("退出", r.get("status") == "exit", str(r))
r = agent.handle("短剧进度")
check("退出后无项目提示", r.get("status") == "idle", str(r))

# ── 4. 持久化 ────────────────────────────────────────────
print("== 4. 持久化 ==")
# 重新进一个项目，直接检查 drama.json 结构
agent2 = _fresh_agent()
agent2.on_message = lambda d: None
agent2.on_confirm_request = lambda *a: None
agent2.handle("短剧剪辑")
agent2.handle("做一个3集都市爱情短剧")
check("持久化: 规划完成", wait_idle(agent2))
p2 = agent2.current_project
drama_path = os.path.join(tmp_root, p2.id, "drama.json")
check("drama.json 存在", os.path.isfile(drama_path))
with open(drama_path, encoding="utf-8") as f:
    raw = json.load(f)
for key in ("id", "title", "genre", "total_episodes", "status", "phase",
            "characters", "episode_goals", "episodes"):
    check(f"drama.json 字段: {key}", key in raw)
from drama_agent.models import DramaProject
reloaded = DramaProject.from_dict(raw)
check("重载项目一致", reloaded.title == p2.title and len(reloaded.characters) == len(p2.characters))
agent2.handle("确认")
check("持久化: 剧本完成", wait_idle(agent2))
p2 = agent2.current_project
check("第1集剧本文件存在", os.path.isfile(p2.episode(1).files.get("script.md", "")))

print()
print(f"PASS={len(PASS)} FAIL={len(FAIL)}")
if FAIL:
    print("失败项:")
    for x in FAIL:
        print("  -", x)
    sys.exit(1)
print("ALL TESTS PASSED")


# ── 5. 制作渲染（真实 ffmpeg，小分辨率冒烟）────────────────
print("== 5. 制作渲染（ffmpeg 小分辨率） ==")
import shutil as _shutil

_ffmpeg = _shutil.which("ffmpeg")
if not _ffmpeg:
    check("ffmpeg 存在（跳过渲染）", True)
else:
    import threading as _th
    from drama_agent.production import EpisodeProducer, ProductionCancelled
    from drama_agent.models import DramaProject, Episode, StoryboardShot

    prod_project = DramaProject(title="测试短剧", total_episodes=3)
    prod_project.episodes = [Episode(number=1, title="第一集", status="script_ready")]
    prod_project.episodes[0].script = "# 第一集\n\n测试剧本正文"
    prod_project.episodes[0].shots = [
        StoryboardShot(shot_id="shot_01", scene="开场城市街道", character="主角",
                       action="主角出场", camera="cinematic medium shot",
                       lighting="自然光", environment="街道", style="cinematic realistic",
                       mood="紧张", dialogue="这是命运的转折。", voice="Tingting",
                       duration=2),
        StoryboardShot(shot_id="shot_02", scene="核心冲突", character="主角",
                       action="主角面对冲突", camera="close-up",
                       lighting="对比光", environment="室内", style="cinematic realistic",
                       mood="冲突", dialogue="", duration=2),
    ]
    producer = EpisodeProducer(width=640, height=360, fps=25)
    progress_log = []
    res = producer.render(
        prod_project, 1, backend="ffmpeg",
        on_progress=lambda st, sh, tot, pct, msg: progress_log.append((st, sh, pct)),
    )
    check("渲染成功", res.get("status") == "success", str(res))
    check("成品文件存在", os.path.isfile(res.get("output", "")), res.get("output", ""))
    check("进度回调已上报", len(progress_log) >= 3, str(len(progress_log)))
    check("进度到 100", progress_log[-1][2] == 100 if progress_log else False, str(progress_log[-1] if progress_log else None))
    dur = res.get("duration", 0)
    # 片头3s + 镜头2+2 + 片尾3s = 10s，0.5s 淡入淡出 × 3 处 → ≈8.5s
    check("时长=片头+镜头+片尾-转场", abs(dur - 8.5) <= 0.7, f"dur={dur}")
    check("海报已生成", os.path.isfile(res.get("poster", "")), res.get("poster", ""))
    srt = res.get("subtitles", "")
    check("字幕已生成", os.path.isfile(srt), srt)
    if srt:
        with open(srt, encoding="utf-8") as f:
            check("字幕含对白", "这是命运的转折。" in f.read())
    out_dir = os.path.dirname(res.get("output", ""))
    check("剧本副本已打包", os.path.isfile(os.path.join(out_dir, "episode_01.md")))
    check("工程快照已打包", os.path.isfile(os.path.join(out_dir, "project.json")))
    check("全剧索引已更新", os.path.isfile(os.path.join(out_dir, "SERIES_INDEX.txt")))

    # 取消
    ev = _th.Event()
    ev.set()
    try:
        producer.render(prod_project, 1, cancel=ev)
        check("取消抛异常", False)
    except ProductionCancelled:
        check("取消抛异常", True)

    # 一键发布（把真实渲染目录打包成 zip，发布目录重定向到临时目录）
    import drama_agent.production as _prod_mod
    _tmp_pub = tempfile.mkdtemp(prefix="drama_release_")
    _orig_rel = _prod_mod._RELEASE_ROOT
    _prod_mod._RELEASE_ROOT = os.path.join(_tmp_pub, "releases")
    try:
        pub = _prod_mod.publish_series(
            prod_project, on_progress=lambda st, n, pct, msg: None)
        check("真实渲染后发布成功", pub.get("status") == "success", str(pub))
        check("发布包含成片", os.path.isfile(pub.get("zip_path", "")),
              pub.get("zip_path", ""))
        with _zipfile.ZipFile(pub["zip_path"]) as zf:
            names = zf.namelist()
            check("发布包含清单", "RELEASE_INFO.txt" in names)
            check("发布包含MP4", "episode_01.mp4" in names)
            check("发布包含字幕", "episode_01.srt" in names)
            check("发布包含海报", "poster.jpg" in names)
            check("发布包含横版海报", "POSTER.jpg" in names)
            check("发布包含说明", "README.md" in names)
            info = zf.read("RELEASE_INFO.txt").decode("utf-8")
            check("清单含剧名", "测试短剧" in info, info[:80])
            check("清单含文件大小", "episode_01.mp4" in info)
        pub2 = _prod_mod.publish_series(prod_project)
        check("发布版本递增 v2", pub2.get("version") == 2, str(pub2.get("version")))
    finally:
        _prod_mod._RELEASE_ROOT = _orig_rel

# ── 6. 声线映射（分角色配音细化）────────────────────────
print("== 6. 声线映射 ==")
from drama_agent.production import _voice_plan

chars = [
    {"name": "林晓", "gender": "女", "personality": "坚韧甜美", "voice": ""},
    {"name": "陈峰", "gender": "男", "personality": "冷酷沉稳", "voice": ""},
    {"name": "爷爷", "gender": "男", "personality": "慈祥和蔼", "voice": "Grandpa"},
]
v, r = _voice_plan("林晓", chars, "", "你好呀")
check("中文女声默认 Tingting", v == "Tingting", v)
check("甜美性格语速加快", r > 190, f"rate={r}")
v, r = _voice_plan("陈峰", chars, "", "来了")
check("中文男声默认 Reed", v == "Reed", v)
check("冷酷性格语速放慢", r < 190, f"rate={r}")
v, r = _voice_plan("林晓", chars, "", "hello world")
check("英文女声默认 Samantha", v == "Samantha", v)
v, r = _voice_plan("陈峰", chars, "低沉,沙哑", "hello")
check("台词声线标注优先(Daniel)", v == "Daniel", v)
v, r = _voice_plan("爷爷", chars, "", "孩子过来")
check("角色显式音色优先(Grandpa)", v == "Grandpa", v)
v, r = _voice_plan("路人", chars, "", "你好")
check("无匹配角色回退女声", v == "Tingting", v)
v, r = _voice_plan("林晓", chars, "", "快跑", mood="紧张")
check("紧张情绪语速加快", r > 198, f"rate={r}")
v, r = _voice_plan("林晓", chars, "", "再见了", mood="悲伤")
check("悲伤情绪语速放慢", r < 198, f"rate={r}")
v, r = _voice_plan("陈峰", chars, "", "冷静点", mood="爆发")
check("爆发情绪叠加加快", r > 175, f"rate={r}")
v, r = _voice_plan("陈峰", chars, "", "she is gone", mood="悲伤")
check("悲伤英文切 Whisper", v == "Whisper", v)
v, r = _voice_plan("陈峰", chars, "", "don't mess with me", mood="愤怒")
check("愤怒英文切 Daniel", v == "Daniel", v)
v, r = _voice_plan("林晓", chars, "", "你太过分了", mood="暴怒")
check("愤怒中文女声切 Meijia", v == "Meijia", v)
v, r = _voice_plan("林晓", chars, "", "reboot the system", mood="机械")
check("机械切 Zarvox", v == "Zarvox", v)
v, r = _voice_plan("林晓", chars, "", "系统重启", mood="机械")
check("机械中文女声切 Sandy", v == "Sandy", v)
v, r = _voice_plan("爷爷", chars, "", "我很难过", mood="悲伤")
check("显式音色优先于情绪", v == "Grandpa", v)

# ── 7. 一键发布（纯单元，假成片目录）────────────────────
print("== 7. 一键发布（假成片目录） ==")
import drama_agent.production as _pub_mod
_tmp_pub2 = tempfile.mkdtemp(prefix="drama_pub_")
_fake_out = os.path.join(_tmp_pub2, "测试发布剧")
os.makedirs(_fake_out)
for _n in ("episode_01.mp4", "episode_01.srt", "poster.jpg",
           "project.json", "SERIES_INDEX.txt"):
    with open(os.path.join(_fake_out, _n), "wb") as f:
        f.write(b"x" * 100)
_orig_out = _pub_mod._OUTPUT_ROOT
_orig_rel2 = _pub_mod._RELEASE_ROOT
_pub_mod._OUTPUT_ROOT = _tmp_pub2
_pub_mod._RELEASE_ROOT = os.path.join(_tmp_pub2, "releases")
try:
    _pp = DramaProject(title="测试发布剧", total_episodes=2)
    _pr = _pub_mod.publish_series(_pp, on_progress=lambda st, n, pct, msg: None)
    check("发布成功", _pr.get("status") == "success", str(_pr))
    check("发布包存在", os.path.isfile(_pr.get("zip_path", "")))
    check("发布包版本 v1", _pr.get("version") == 1, str(_pr.get("version")))
    with _zipfile.ZipFile(_pr["zip_path"]) as zf:
        check("清单在包内", "RELEASE_INFO.txt" in zf.namelist())
        check("成片在包内", "episode_01.mp4" in zf.namelist())
        check("横版海报在包内", "POSTER.jpg" in zf.namelist())
        check("README在包内", "README.md" in zf.namelist())
        check("README含播放说明",
              "QuickTime" in zf.read("README.md").decode("utf-8"))
    _pr2 = _pub_mod.publish_series(_pp)
    check("重复发布版本 v2", _pr2.get("version") == 2, str(_pr2.get("version")))
    os.remove(os.path.join(_fake_out, "episode_01.mp4"))
    try:
        _pub_mod.publish_series(_pp)
        check("无成片报错", False)
    except _pub_mod.ProductionError:
        check("无成片报错", True)

    # 上传框架：未配置 / 本地目录 / none
    _env_backup = dict(os.environ)
    try:
        os.environ.pop("JARVIS_UPLOAD_TARGET", None)
        up = _pub_mod.upload_release(_pr["zip_path"])
        check("未配置上传目标→跳过", not up.get("uploaded") and "未配置" in up.get("reason", ""),
              str(up))
        up = _pub_mod.upload_release(_pr["zip_path"], provider="none")
        check("provider=none 不上传", not up.get("uploaded"), str(up))
        _up_dir = tempfile.mkdtemp(prefix="drama_upload_")
        os.environ["JARVIS_UPLOAD_TARGET"] = _up_dir
        up = _pub_mod.upload_release(_pr["zip_path"])
        check("本地目录上传成功", up.get("uploaded") and os.path.isfile(up.get("url", "")),
              str(up))
        check("上传文件名一致",
              os.path.basename(up.get("url", "")) == os.path.basename(_pr["zip_path"]))
    finally:
        os.environ.clear()
        os.environ.update(_env_backup)
finally:
    _pub_mod._OUTPUT_ROOT = _orig_out
    _pub_mod._RELEASE_ROOT = _orig_rel2

print()
print(f"PASS={len(PASS)} FAIL={len(FAIL)}")
if FAIL:
    print("失败项:")
    for x in FAIL:
        print("  -", x)
    sys.exit(1)
print("ALL TESTS PASSED")
