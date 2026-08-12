#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Mission 规划器：目标 → 有序步骤。

主路径：Hermes LLM（DeepSeek 文本能力）输出结构化 JSON；
失败/不可用时：本地关键词模板 fallback。
规划结果统一经 MissionPermissionManager.validate_plan 白名单清洗。
"""

import json
import re
import threading

from .permission_manager import MissionPermissionManager

_PLAN_PROMPT = (
    "You are JARVIS mission planner. Break the user's goal into a short ordered "
    "list of concrete steps. Use ONLY these agents and actions:\n"
    "agents: coding(actions: analyze, review, test, modify, git), "
    "computer(actions: open_app, close_app, switch_app, type_text, press_keys, "
    "click_element, take_screenshot, get_screen_state, list_apps), "
    "llm(actions: summarize, translate, generate, ask), "
    "vision(actions: scan, describe), map(actions: locate, news, reset), "
    "video(actions: clip, generate, render, export, status).\n"
    "Rules:\n"
    "- coding.modify MUST set requires_confirm=true.\n"
    "- on_failure is one of abort|skip|retry.\n"
    "- params: for coding use {\"task\": <one short instruction>, \"project\": <path or empty>}; "
    "for computer use {\"text\": <exact instruction like \"open Chrome\" or \"screenshot\">}; "
    "for llm use {\"text\": <instruction>}.\n"
    "- At most 8 steps. Prefer the minimal number of steps.\n"
    "Reply with ONLY a JSON object, no markdown:\n"
    '{"steps": [{"agent": "...", "action": "...", "params": {...}, '
    '"requires_confirm": false, "on_failure": "abort"}]}'
)

# ── 本地模板 fallback（确定性指令）──────────────────────────
_OPEN_RE = re.compile(r"(?:打开|开启|启动|运行|open|launch|start)\s*(.+)$", re.I)
_SCREENSHOT_RE = re.compile(r"(?:截屏|截图|拍屏|screenshot)", re.I)
_ANALYZE_RE = re.compile(r"(?:分析|检查|看看|了解|analyze|review|inspect)", re.I)
_TEST_RE = re.compile(r"(?:测试|跑测试|运行测试|test)", re.I)
_MODIFY_RE = re.compile(r"(?:优化|修改|修复|重构|加|增加|实现|implement|fix|refactor|optimize|improve)", re.I)
_LOCATE_RE = re.compile(r"(?:定位到|定位|地图|locate|navigate to)\s*(.+)$", re.I)
_CLIP_RE = re.compile(
    r"(?:(?:剪辑|制作|生成|做一个|渲染|剪)[^。\n]{0,30}视频|"
    r"视频|video|clip|render|generate)", re.I
)


def _extract_json(text: str):
    """从模型回复中提取 JSON 对象（容忍代码块/前后缀）。失败返回 None。"""
    if not text:
        return None
    s = re.sub(r"^```(?:json)?\s*", "", text.strip())
    s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except Exception:
        pass
    start, end = s.find("{"), s.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(s[start:end + 1])
        except Exception:
            return None
    return None


class Planner:
    """目标 → 步骤。plan() 返回清洗后的 MissionStep 列表，失败返回 None。"""

    def __init__(self):
        self._perms = MissionPermissionManager()
        self._lock = threading.Lock()

    def plan(self, goal: str, role: str = "jarvis"):
        steps = self._plan_llm(goal, role)
        if not steps:
            steps = self._plan_template(goal)
        if not steps:
            return None
        return self._perms.validate_plan(steps)

    # ── LLM 主路径 ─────────────────────────────────────────
    def _plan_llm(self, goal: str, role: str):
        try:
            from hermes_bridge import HermesBridge

            bridge = HermesBridge(agent_id=(role or "jarvis").replace("-", "_"))
            if not bridge.gateway_url or not bridge.key:
                return None
            prompt = _PLAN_PROMPT + f"\nUser goal: {goal[:400]}"
            with self._lock:
                reply = bridge.send_and_wait(prompt)
            if not reply:
                return None
            data = _extract_json(reply)
            if not isinstance(data, dict):
                return None
            steps = data.get("steps")
            if isinstance(steps, list) and steps:
                return steps
            return None
        except Exception as e:
            print(f"[Mission] LLM 规划失败: {e}")
            return None

    # ── 本地模板 fallback ──────────────────────────────────
    def _plan_template(self, goal: str):
        t = (goal or "").strip()
        if not t:
            return None
        steps = []
        # 定位：定位到 X
        m = _LOCATE_RE.search(t)
        if m:
            steps.append(
                {"agent": "map", "action": "locate",
                 "params": {"name": m.group(1).strip()[:100]},
                 "requires_confirm": False, "on_failure": "skip"}
            )
        # 视频：制作/剪辑/渲染（requires_confirm=True，执行前语音确认）
        m = _CLIP_RE.search(t)
        if m:
            steps.append(
                {"agent": "video", "action": "generate",
                 "params": {"prompt": t[:300]},
                 "requires_confirm": True, "on_failure": "abort"}
            )
        # 打开应用
        m = _OPEN_RE.search(t)
        if m:
            steps.append(
                {"agent": "computer", "action": "open_app",
                 "params": {"text": f"open {m.group(1).strip()[:100]}"},
                 "requires_confirm": False, "on_failure": "skip"}
            )
        # 截屏
        if _SCREENSHOT_RE.search(t):
            steps.append(
                {"agent": "computer", "action": "take_screenshot",
                 "params": {"text": "screenshot"},
                 "requires_confirm": False, "on_failure": "skip"}
            )
        # 分析
        if _ANALYZE_RE.search(t):
            steps.append(
                {"agent": "coding", "action": "analyze",
                 "params": {"task": t[:200], "project": ""},
                 "requires_confirm": False, "on_failure": "abort"}
            )
        # 测试
        if _TEST_RE.search(t) and not _ANALYZE_RE.search(t):
            steps.append(
                {"agent": "coding", "action": "test",
                 "params": {"task": t[:200], "project": ""},
                 "requires_confirm": False, "on_failure": "abort"}
            )
        # 修改
        if _MODIFY_RE.search(t) and not _ANALYZE_RE.search(t):
            steps.append(
                {"agent": "coding", "action": "modify",
                 "params": {"task": t[:200], "project": ""},
                 "requires_confirm": True, "on_failure": "abort"}
            )
        # 纯文本类（总结/翻译）
        if not steps and len(t) <= 200:
            steps.append(
                {"agent": "llm", "action": "ask",
                 "params": {"text": t[:200]},
                 "requires_confirm": False, "on_failure": "abort"}
            )
        return steps or None
