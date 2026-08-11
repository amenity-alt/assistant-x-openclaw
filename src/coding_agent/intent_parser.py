#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Coding 意图本地解析（Phase 1 最小版）：文本 → CodingTask 字段。

只解析确定性的编码指令（分析/审查/测试/修改/git）；未知返回 None。
项目提示（用XX项目/切换到XX项目）提取后交给 WorkspaceManager。
"""

import re
from dataclasses import dataclass

_PREFIX_NOISE = re.compile(
    r"^(?:请|帮我|麻烦|给我|帮|please|plz|jarvis)\s*", re.I
)
_PROJECT_HINT = re.compile(
    r"(?:用|在|切换到|把|对)\s*([\w\-_.]+?)\s*(?:项目|仓库|工程)"
)

_WORKSPACE_RE = re.compile(
    r"^(?:请|帮我|麻烦)?(?:切换到|切到)\s*([\w\-_.]+?)\s*(?:项目|仓库|工程)$"
)


_MODE_RULES = [
    # (mode, 正则, 默认任务模板)
    ("review", re.compile(r"(?:审查|评审|检查|review|昨天)", re.I),
     "审查当前项目的改动，列出问题与改进建议。"),
    ("test", re.compile(r"(?:运行|跑|执行|启动)?\s*测试|run.*tests|run.*test", re.I), "运行项目现有测试并报告结果。"),
    ("git", re.compile(r"(?:git\s+(?:status|log|diff)|提交记录|项目状态|工作区状态|"
                       r"查看状态|commit\b|push\b|推送|提交(?:一下)?(?:代码|改动)?$)", re.I), ""),
    ("analyze", re.compile(r"(?:分析|看看这个项目|项目分析|看看项目|analyze|describe this project|"
                           r"what does this project)", re.I),
     "分析当前项目的架构、技术栈、主要模块、构建与测试方式，输出简明报告。"),
    ("modify", re.compile(r"(?:优化|修改|实现|增加|添加|重构|修复|改造|improve|implement|add|fix|"
                          r"refactor|build)", re.I), ""),
]


@dataclass
class CodingIntent:
    mode: str
    task: str
    project_hint: str = ""


def _clean(text: str) -> str:
    return _PREFIX_NOISE.sub("", text or "").strip()


def parse(text: str) -> CodingIntent:
    t = _clean(text)
    if not t:
        return None
    m = _WORKSPACE_RE.match(t)
    if m:
        return CodingIntent(
            mode="workspace", task=f"切换到 {m.group(1)} 项目", project_hint=m.group(1)
        )
    # 项目提示（尽量靠前的“用/切换到 XX 项目”）
    hint = ""
    m = _PROJECT_HINT.search(t)
    if m:
        cand = m.group(1)
        if cand not in ("这个", "那", "我", "你", "一下", "当前"):
            hint = cand
    for mode, rx, default_task in _MODE_RULES:
        if rx.search(t):
            # 分析类：去掉触发词后的细节并入任务；无细节用默认模板
            if mode == "analyze" and len(t) <= 12:
                task = default_task
            elif mode == "review":
                task = f"代码审查：{t}。列出问题与改进建议。"
            elif mode == "test":
                task = f"运行测试并报告结果：{t}"
            elif mode == "modify":
                task = f"编码任务：{t}。只修改当前工作区内的文件，不要触碰凭证/密钥文件。"
            else:
                task = t
            return CodingIntent(mode=mode, task=task, project_hint=hint)
    return None
