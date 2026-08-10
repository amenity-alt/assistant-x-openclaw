#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""大脑 Tool 接入（Phase 4，路径 A）：本地解析兜底 → 约束 JSON 解析。

本地 intent_parser 无法解析时，用现有 bridge（Hermes/OpenClaw）发一次
「只输出 JSON」的约束解析请求；拿到的 Action 仍走本地 Permission/Executor，
LLM 永远不能直接碰系统。解析使用独立会话（computer-parse-*），不污染语音会话。
"""

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from .action import Action

_PARSE_TIMEOUT = 20.0  # 大脑解析单次超时（秒）

# LLM 常见动作词 → 规范 action（提示词里已给规范名，这里再做一层防御）
_ACTION_SYNONYMS = {
    "open": "open_app", "launch": "open_app", "start": "open_app",
    "open_application": "open_app", "openapp": "open_app",
    "close": "close_app", "quit": "close_app", "exit_app": "close_app",
    "close_application": "close_app", "closeapp": "close_app",
    "switch": "switch_app", "switch_app": "switch_app", "switchto": "switch_app",
    "type": "type_text", "type_text": "type_text", "input": "type_text", "input_text": "type_text",
    "press": "press_keys", "press_keys": "press_keys", "key": "press_keys", "hotkey": "press_keys",
    "click": "click_element", "click_element": "click_element", "click_button": "click_element",
    "double_click": "double_click_element", "doubleclick": "double_click_element",
    "screenshot": "take_screenshot", "take_screenshot": "take_screenshot", "capture": "take_screenshot",
    "screen": "get_screen_state", "get_screen_state": "get_screen_state", "screen_state": "get_screen_state",
    "list_apps": "list_apps", "apps": "list_apps", "running_apps": "list_apps",
    "scroll": "scroll",
    "none": "none", "noop": "none", "null": "none",
}

_PROMPT = """你是电脑控制指令解析器。只输出一个 JSON 对象，不要输出任何其他文字、不要用代码块。
把用户指令解析成电脑操作：
{"action": "open_app", "target": "应用名"}  打开/启动应用
{"action": "close_app", "target": "应用名"}  关闭应用
{"action": "switch_app", "target": "应用名"}  切换到应用
{"action": "type_text", "target": "要输入的文本"}  输入文字
{"action": "press_keys", "target": "组合键，如 Command+C / Command+Space / 回车"}  按键
{"action": "click_element", "target": "界面元素名，如 发送"}  点击按钮/元素
{"action": "double_click_element", "target": "界面元素名"}  双击
{"action": "take_screenshot"}  截图
{"action": "get_screen_state"}  查看屏幕
{"action": "list_apps"}  列出运行中的应用
{"action": "scroll", "params": {"amount": -3}}  滚动（正数向上、负数向下）
如果这不是电脑操作指令，输出 {"action": "none"}。
用户指令：{text}"""

_JSON_RE = re.compile(r"\{.*\}", re.S)


class BrainParser:
    """约束 JSON 解析器：bridge + 独立解析会话 + 超时。"""

    def __init__(self, bridge=None):
        self.bridge = bridge
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="brain-parse")

    def bind_bridge(self, bridge):
        self.bridge = bridge

    # ── 会话隔离：解析请求不写进语音会话 ──────────────────────
    @staticmethod
    def _parse_headers(bridge) -> dict:
        hour = time.strftime("%Y%m%d%H")
        sid = f"computer-parse-{getattr(bridge, 'profile', 'main')}-{hour}"
        skey = f"computer-parse:{getattr(bridge, 'profile', 'main')}:{hour}"
        return {
            "Authorization": f"Bearer {bridge.key}",
            "Content-Type": "application/json",
            "X-Hermes-Session-Id": sid,
            "X-Hermes-Session-Key": skey,
        }

    def _request(self, text: str):
        """同步发一次约束解析请求，返回 LLM 原文；失败返回 ""。"""
        bridge = self.bridge
        if bridge is None or not getattr(bridge, "gateway_url", None) or not getattr(bridge, "key", None):
            return ""
        import requests

        try:
            resp = requests.post(
                f"{bridge.gateway_url}/v1/chat/completions",
                headers=self._parse_headers(bridge),
                json={
                    "model": getattr(bridge, "profile", "main"),
                    "messages": [{"role": "user", "content": _PROMPT.replace("{text}", text)}],
                    "stream": False,
                    "temperature": 0.0,
                    "max_tokens": 200,
                },
                timeout=_PARSE_TIMEOUT,
            )
            if resp.status_code != 200:
                print(f"[Computer] 大脑解析 HTTP {resp.status_code}: {resp.text[:200]}")
                return ""
            choices = resp.json().get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "") or ""
            return ""
        except Exception as e:
            print(f"[Computer] 大脑解析请求失败: {e}")
            return ""

    # ── 解析与校验 ─────────────────────────────────────────
    def parse(self, text: str) -> Action:
        """大脑解析 → 白名单校验 → Action；无法解析返回 None。"""
        future = self._pool.submit(self._request, text)
        try:
            raw = future.result(timeout=_PARSE_TIMEOUT + 5)
        except TimeoutError:
            print("[Computer] 大脑解析超时")
            return None
        return self._to_action(raw)

    def _to_action(self, raw: str) -> Action:
        raw = (raw or "").strip()
        # 去掉可能的 markdown 代码块
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
        m = _JSON_RE.search(raw)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
        action = str(data.get("action", "")).strip().lower()
        action = _ACTION_SYNONYMS.get(action, action)
        if action == "none":
            return None
        if action not in _ACTION_SYNONYMS.values() and action not in (
            "open_app", "close_app", "switch_app", "type_text", "press_keys",
            "click_element", "double_click_element", "take_screenshot",
            "get_screen_state", "list_apps", "scroll",
        ):
            return None
        target = str(data.get("target", "")).strip()[:100]
        params = data.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        return Action(action=action, target=target, params=params)
