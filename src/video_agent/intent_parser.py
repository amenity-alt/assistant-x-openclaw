#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Video 意图本地解析：语音文本 → VideoIntent。

解析确定性视频指令（生成/剪辑/渲染/进度/取消）；未知返回 None。
中文 + 英文关键词；支持提取时长、竖屏/方形格式、素材路径提示。
"""

import re
from dataclasses import dataclass

_PREFIX_NOISE = re.compile(
    r"^(?:请|帮我|麻烦|给我|帮|please|plz|jarvis|贾维斯)\s*", re.I
)

_DURATION_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(分钟|分|min\b|minute|m\b|秒|s\b|sec|second)"
)
_VERTICAL_RE = re.compile(r"(?:竖屏|vertical|9:16|9：16|短视频)", re.I)
_SQUARE_RE = re.compile(r"(?:方形|square|1:1|1：1)", re.I)

# ── 模式规则 ─────────────────────────────────────────────
_GENERATE_RE = re.compile(
    r"(?:制作|生成|创建|做一个|做|生成一个|给我做|帮我做|make|create|generate)"
    r".{0,60}(?:视频|短视频|video|clip|宣传片|vlog)"
    r"|(?:视频|短视频|video)\s*(?:制作|生成|剪辑)"
    r"|ai\s*(?:video|clip|movie)"
    r"|(?:用|通过)?\s*(?:提示词|prompt)\s*(?:生成|制作)\s*(?:视频|video)",
    re.I,
)
_FACECAM_RE = re.compile(
    r"(?:剪辑|剪一下|剪个|剪一剪|编辑|修剪|cut|trim|edit)\s*(?:这个|那个|一下|我的)?"
    r".{0,40}(?:视频|录像|素材|video|footage|clip)"
    r"|(?:视频|录像|素材)\s*(?:剪辑|剪一下|trim|cut)"
    r"|(?:用|把|对)\s*([^\s，。]+?)\s*(?:视频|录像|素材)?\s*(?:剪|剪辑|剪成|做成视频|trim|cut)"
    r"|(?:facecam|上传素材)",
    re.I,
)
_RENDER_RE = re.compile(
    r"(?:渲染|导出|render|export)\s*(?:这个|那个|一下|我的)?\s*(?:项目|视频|时间线|project|video)?"
    r"\s*([\w\-_.]{1,24})?"
    r"|(?:渲染|导出)\s*([\w\-_.]{1,24})\s*(?:项目|视频)"
)
_STATUS_RE = re.compile(
    r"^(?:(?:视频|渲染|剪辑){1,2}\s*)?(?:进度|状态|好了吗|完成了吗|完事了吗|"
    r"完了吗|怎么样了|进行到哪|status|progress|is it done|finished)"
    r"(?:如何|怎样|怎么样)?了?$",
    re.I,
)
_CANCEL_RE = re.compile(
    r"^(?:停止|取消|终止|停掉|别渲染了)\s*(?:渲染|视频|剪辑|任务)?"
    r"|(?:cancel|stop|abort)\s*(?:the\s+)?(?:render|video|job)?$",
    re.I,
)


@dataclass
class VideoIntent:
    mode: str                  # VideoMode 值
    prompt: str = ""           # 需求文本（generate）
    source_video: str = ""     # 素材路径（facecam，后续由权限层校验）
    project: str = ""          # 渲染项目名（render）
    duration_sec: int = 0
    video_format: str = "horizontal"
    voice: str = ""
    task_text: str = ""        # 原始需求（去噪后）


def _clean(text: str) -> str:
    return _PREFIX_NOISE.sub("", text or "").strip()


def _parse_duration(text: str) -> int:
    m = _DURATION_RE.search(text)
    if not m:
        return 0
    val = float(m.group(1))
    unit = m.group(2)
    if unit in ("分", "分钟", "min", "minute", "m"):
        return int(val * 60)
    return int(val)


def parse(text: str) -> VideoIntent:
    t = _clean(text)
    if not t:
        return None

    if _STATUS_RE.match(t):
        return VideoIntent(mode="status", task_text=t)
    if _CANCEL_RE.match(t):
        return VideoIntent(mode="cancel", task_text=t)

    m = _FACECAM_RE.search(t)
    if m:
        # 提取素材路径提示（“用 xxx 视频/把 xxx 素材”）
        src = ""
        if m.lastindex and m.group(1):
            cand = m.group(1).strip()
            if not cand.lower() in ("这个", "那个", "一下", "我的"):
                src = cand
        dur = _parse_duration(t)
        return VideoIntent(
            mode="facecam",
            prompt=t,
            source_video=src,
            duration_sec=dur,
            video_format="vertical" if _VERTICAL_RE.search(t) else
                          ("square" if _SQUARE_RE.search(t) else "horizontal"),
            task_text=t,
        )

    if _RENDER_RE.search(t):
        m = _RENDER_RE.search(t)
        proj = ""
        if m and m.lastindex and m.group(1):
            proj = m.group(1).strip()
        elif m and m.lastindex and m.group(2):
            proj = m.group(2).strip()
        return VideoIntent(
            mode="render",
            prompt=t,
            project=proj,
            task_text=t,
        )

    if _GENERATE_RE.search(t):
        return VideoIntent(
            mode="generate",
            prompt=t,
            duration_sec=_parse_duration(t),
            video_format="vertical" if _VERTICAL_RE.search(t) else
                          ("square" if _SQUARE_RE.search(t) else "horizontal"),
            task_text=t,
        )

    return None
