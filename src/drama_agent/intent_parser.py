#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Short Drama — 语音意图解析（中英 + 集数/人物/修改提取）。"""

import re
from dataclasses import dataclass

_PREFIX = re.compile(r"^(?:请|帮我|麻烦|给我|帮|jarvis|贾维斯)\s*", re.I)

_ENTER_RE = re.compile(
    r"(?:短剧|短剧剪辑|开启短剧|进入短剧|short\s*drama|drama\s*mode)", re.I
)
_EXIT_RE = re.compile(
    r"(?:退出短剧|关闭短剧|结束短剧|短剧(?:模式)?(?:退出|关闭|结束)|exit\s*drama|"
    r"close\s*drama)", re.I
)
_STATUS_RE = re.compile(
    r"(?:短剧|drama)(?:的)?(?:进度|状态|情况)|(?:进度|状态)(?:如何|怎么样)?$|"
    r"短剧到哪|drama\s*status|drama\s*progress", re.I
)
_PLAN_RE = re.compile(
    r"(?:重新规划剧情|重新.*剧情|重写.*规划|重新设计|replan|replan\s*story)", re.I
)
_CHARACTER_RE = re.compile(
    r"(?:修改人物|改人物|改一下(?:女|男)?主角|把[^。\n]{0,20}(?:改成|换成|变成)|"
    r"change\s*character|update\s*character)", re.I
)

# ── 集数（阿拉伯数字 + 中文数字）─────────────────────────
_CN_NUM = r"(?:\d{1,2}|[一二两三四五六七八九十]{1,3})"
_NUMS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
         "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_to_int(s: str) -> int:
    if not s:
        return 0
    if s.isdigit():
        return int(s)
    if "十" not in s:
        return sum(_NUMS.get(c, 0) for c in s) if len(s) <= 2 else 0
    parts = s.split("十")
    tens = _NUMS.get(parts[0], 1) if parts[0] else 1
    ones = _NUMS.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
    return tens * 10 + ones


_EPISODE_VIEW_RE = re.compile(
    r"(?:查看|看看|看下|读一下|介绍一下)\s*(?:第)?\s*(?P<a>" + _CN_NUM + r")\s*集(?:的)?"
    r"(?:内容|剧情|剧本)?$|查看第\s*(?P<b>" + _CN_NUM + r")\s*集"
    r"|show\s*episode\s*(?P<c>\d+)", re.I
)
_EPISODE_REWRITE_RE = re.compile(
    r"(?:重写|重新写|重做)\s*第?\s*(?P<a>" + _CN_NUM + r")?\s*集"
    r"|第\s*(?P<b>" + _CN_NUM + r")\s*集(?:重写|重新写|重做)"
    r"|rewrite\s*episode\s*(?P<c>\d+)", re.I
)
_PROMPTS_RE = re.compile(
    r"(?:生成|做|出)?第?\s*(?P<a>" + _CN_NUM + r")?\s*集?(?:的)?(?:镜头|分镜|提示词|prompt|prompts)"
    r"|generate\s*(?:episode\s*(?P<b>" + _CN_NUM + r")\s*)?prompts", re.I
)
_PRODUCE_RE = re.compile(
    r"(?:开始)?(?:制作|做|开拍)\s*第?\s*(?P<a>" + _CN_NUM + r")?\s*集"
    r"|start\s*(?:episode\s*(?P<b>" + _CN_NUM + r"))?"
    r"|开始制作", re.I
)
_NEXT_RE = re.compile(r"(?:进入|开始|做)?(?:下一集|第二集|下集)|next\s*episode", re.I)
_RECLIP_RE = re.compile(
    r"(?:重新剪辑|重剪)\s*(?:第|这|本)?\s*(?P<a>" + _CN_NUM + r")?\s*集"
    r"|re(?:clip|edit)", re.I
)
_PAUSE_RE = re.compile(r"(?:暂停短剧|短剧暂停|暂停制作)|pause\s*drama", re.I)
_STOP_RE = re.compile(
    r"(?:停止制作|停止渲染|取消制作|停一下|别做了|stop\s*(?:production|rendering)|cancel\s*production)", re.I
)
_AI_PRODUCE_RE = re.compile(r"(?:用\s*ai|ai\s*制作|ai制作)", re.I)
_RESUME_RE = re.compile(r"(?:继续短剧|恢复短剧|短剧继续)|resume\s*drama", re.I)

YES_RE = re.compile(
    r"^(?:确认|好的|可以|嗯|对|同意|行|好|是|确认继续|继续吧|ok|yes|yep|sure|"
    r"go ahead|confirmed)$", re.I
)
NO_RE = re.compile(
    r"^(?:取消|算了|不用|不了|不要|不行|否|不对|no|cancel|never\s*mind|nope)$", re.I
)

# 需求收集：主题/类型/集数/时长/风格
_COUNT_RE = re.compile(r"(\d+)\s*集")
_DURATION_RE = re.compile(r"(?:每集|每)?(\d+)\s*(?:分钟|分|min|秒|s)")
_GENRE_RE = re.compile(
    r"(都市|古装|玄幻|科幻|悬疑|惊悚|爱情|喜剧|家庭|校园|职场|逆袭|复仇|"
    r"重生|穿越|战神|甜宠|仙侠|武侠|历史|年代|都市异能)", re.I
)
_STYLE_RE = re.compile(
    r"(写实|现实主义|电影感|赛博朋克|动漫|二次元|水墨|国风|暗黑|治愈|"
    r"高清|胶片|霓虹|realistic|anime|cyberpunk|cinematic)", re.I
)
_THEME_RE = re.compile(
    r"(?:主题|关于|题材)[:：是]?\s*([^。，,\n]{2,30})"
)
_START_RE = re.compile(
    r"^(?:开始规划|开始吧|开始|规划吧|就这样|可以了|想好了|就这些|开工|start|go)$", re.I
)


@dataclass
class DramaIntent:
    cmd: str                       # enter/exit/status/plan/character/episode_view/
                                   # episode_rewrite/prompts/produce/next/reclip/
                                   # pause/resume/stop/yes/no/collect/help
    episode: int = 0
    text: str = ""
    target: str = ""               # 修改人物目标（如 女主角/林晓）
    change: str = ""               # 修改内容（如 短发）
    ai: bool = False               # 是否要求 AI(OpenCut) 渲染后端


def _clean(text: str) -> str:
    t = _PREFIX.sub("", text.strip())
    return t.strip()


def _ep(groups: tuple) -> int:
    for g in groups:
        if g:
            return _cn_to_int(g)
    return 0


def parse(text: str) -> DramaIntent:
    t = _clean(text)
    if not t:
        return DramaIntent(cmd="none")

    if YES_RE.match(t):
        return DramaIntent(cmd="yes")
    if NO_RE.match(t):
        return DramaIntent(cmd="no")
    if _EXIT_RE.search(t):
        return DramaIntent(cmd="exit")
    if _STATUS_RE.search(t):
        return DramaIntent(cmd="status")
    if _PAUSE_RE.search(t):
        return DramaIntent(cmd="pause")
    if _RESUME_RE.search(t):
        return DramaIntent(cmd="resume")
    if _STOP_RE.search(t):
        return DramaIntent(cmd="stop", text=t)

    m = _EPISODE_REWRITE_RE.search(t)
    if m:
        return DramaIntent(cmd="episode_rewrite",
                           episode=_ep((m.group("a"), m.group("b"), m.group("c"))),
                           text=t)

    m = _PROMPTS_RE.search(t)
    if m:
        return DramaIntent(cmd="prompts",
                           episode=_ep((m.group("a"), m.group("b"))),
                           text=t)

    m = _PRODUCE_RE.search(t)
    if m:
        return DramaIntent(cmd="produce",
                           episode=_ep((m.group("a"), m.group("b"))),
                           text=t, ai=bool(_AI_PRODUCE_RE.search(t)))

    m = _EPISODE_VIEW_RE.search(t)
    if m:
        return DramaIntent(cmd="episode_view",
                           episode=_ep((m.group("a"), m.group("b"), m.group("c"))),
                           text=t)

    if _NEXT_RE.search(t):
        return DramaIntent(cmd="next", text=t)

    m = _RECLIP_RE.search(t)
    if m:
        return DramaIntent(cmd="reclip", episode=_ep((m.group("a"),)), text=t)

    if _CHARACTER_RE.search(t):
        m = _CHARACTER_RE.search(t)
        change = ""
        cm = re.search(r"(?:改成|换成|变成)\s*([^。，,\n]{1,20})", t)
        if cm:
            change = cm.group(1).strip()
        target = ""
        tm = re.search(r"(女|男)?主角|(\w{1,6}(?:晓|琳|峰|宇|婷|雪|菲|琳|杰))", t)
        if tm:
            target = tm.group(0)
        return DramaIntent(cmd="character", target=target, change=change, text=t)

    if _PLAN_RE.search(t):
        return DramaIntent(cmd="plan", text=t)

    if _ENTER_RE.search(t):
        return DramaIntent(cmd="enter", text=t)

    if _START_RE.match(t):
        return DramaIntent(cmd="start", text=t)

    return DramaIntent(cmd="collect", text=t)


def collect_fields(text: str) -> dict:
    """从需求文本提取 {theme, genre, episodes, duration, style}。"""
    fields = {}
    t = _clean(text)
    m = _THEME_RE.search(t)
    if m:
        fields["theme"] = m.group(1).strip()
    m = _COUNT_RE.search(t)
    if m:
        fields["episodes"] = int(m.group(1))
    m = _DURATION_RE.search(t)
    if m:
        v = int(m.group(1))
        fields["duration"] = v * 60 if "分" in t or "min" in t.lower() else v
    m = _GENRE_RE.search(t)
    if m:
        fields["genre"] = m.group(1)
    m = _STYLE_RE.search(t)
    if m:
        fields["style"] = m.group(1)
    # 主题兜底 1：做X短剧 结构
    if not fields.get("theme"):
        m = re.search(
            r"(?:做一个|做|拍一个|拍个|要做一个|来一个|来)?\s*([^，,。\n]{2,20}?)(?:短剧|电视剧|剧|视频)",
            t,
        )
        if m:
            theme = m.group(1)
            theme = _COUNT_RE.sub("", theme)
            theme = _DURATION_RE.sub("", theme)
            theme = _STYLE_RE.sub("", theme)
            theme = theme.strip(" ，,。的")
            if 2 <= len(theme) <= 20:
                fields["theme"] = theme
    # 主题兜底 2：去掉已识别的数字/类型词后剩余文本
    if not fields.get("theme"):
        rest = _COUNT_RE.sub("", t)
        rest = _DURATION_RE.sub("", rest)
        rest = _STYLE_RE.sub("", rest)
        rest = re.sub(r"^(?:我想|我要|请|帮我|给我|做一个|做|拍一个|拍个|来|要|的)?", "", rest)
        rest = re.sub(r"(短剧|电视剧|剧|视频)?$", "", rest).strip(" ，,。")
        rest = re.sub(r"(风格|模式)$", "", rest).strip(" ，,。")
        rest = re.sub(r"^的", "", rest).strip(" ，,。")
        if 2 <= len(rest) <= 30:
            theme = rest
            if len(theme) <= 4 and fields.get("genre") and theme not in fields["genre"]:
                theme = fields["genre"] + theme
            fields["theme"] = theme
    return fields
