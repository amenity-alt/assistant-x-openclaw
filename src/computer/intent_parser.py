#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""自然语言 → Action 本地解析器（Phase 1 最小版：应用控制）。

仅解析确定性的应用控制指令（打开/关闭/切换到 X）；未知返回 None，
后续 Phase 4 可接大脑约束 JSON 解析兜底。解析只产出 Action，不执行。
"""

import re

from .action import Action

# 指令前常见敬语/语气词（解析时剥离）
_PREFIX_NOISE = re.compile(
    r"^(?:请帮我|麻烦你|帮我把|给我把|please|plz|请|帮我|麻烦|给我|可以|把)\s*", re.I
)
_SUFFIX_NOISE = re.compile(
    r"\s*(?:一下|一下吧|吧|好吗|好嘛|谢谢|多谢|please|plz|the|app|application|应用|程序)$",
    re.I,
)

_OPEN_RE = re.compile(r"^(?:打开一下|帮我打开|打开|开启|启动|运行)\s*(.+)$")
_LAUNCH_RE = re.compile(r"^(?:open|launch|start|run)\s+(.+)$", re.I)
_CLOSE_RE = re.compile(r"^(?:关一下|关掉|关闭|退出|结束)\s*(.+)$")
_QUIT_RE = re.compile(r"^(?:close|quit|exit|kill)\s+(.+)$", re.I)
_SWITCH_RE = re.compile(r"^(?:切换到|切换|切到|转到|切一下到)\s*(.+)$")
_SWITCH_EN_RE = re.compile(r"^(?:switch to|switch|bring up|focus)\s+(.+)$", re.I)


def _clean_target(raw: str) -> str:
    t = _PREFIX_NOISE.sub("", raw or "").strip()
    t = re.sub(r"^一下\s*", "", t)  # 「打开一下微信」残留的前导语气词
    t = _SUFFIX_NOISE.sub("", t).strip()
    return t


def parse(text: str) -> Action:
    """解析指令文本 → Action；无法确定时返回 None。"""
    t = _PREFIX_NOISE.sub("", text or "").strip()
    if not t:
        return None
    m = _OPEN_RE.match(t) or _LAUNCH_RE.match(t)
    if m:
        target = _clean_target(m.group(1))
        if target:
            return Action(action="open_app", target=target)
    m = _CLOSE_RE.match(t) or _QUIT_RE.match(t)
    if m:
        target = _clean_target(m.group(1))
        if target:
            return Action(action="close_app", target=target)
    m = _SWITCH_RE.match(t) or _SWITCH_EN_RE.match(t)
    if m:
        target = _clean_target(m.group(1))
        if target:
            return Action(action="switch_app", target=target)
    return None
