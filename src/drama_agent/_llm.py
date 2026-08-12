#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Short Drama — Hermes/DeepSeek LLM 共用调用（JSON + 纯文本，超时可控）。

与 mission_control/planner.py 同款调用方式：HermesBridge → DeepSeek 后端。
失败/不可用时返回 None，由各模块本地模板兜底。
"""

import json
import re
import threading
import time

_CALL_LOCK = threading.Lock()


def _extract_json(text: str):
    """从模型回复提取 JSON（容忍代码块/前后缀）。失败返回 None。"""
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


def _bridge(role: str = "jarvis", timeout: float = 150.0):
    from hermes_bridge import HermesBridge

    return HermesBridge(agent_id=(role or "jarvis").replace("-", "_"),
                        timeout=timeout)


def llm_json(prompt: str, role: str = "jarvis", timeout: float = 150.0) -> dict | None:
    """LLM → JSON 对象。失败返回 None。"""
    bridge = _bridge(role, timeout=timeout)
    if not bridge.gateway_url or not bridge.key:
        return None
    try:
        with _CALL_LOCK:
            reply = bridge.send_and_wait(prompt)
    except Exception as e:
        print(f"[Drama] LLM 调用异常: {e}")
        return None
    if not reply:
        return None
    return _extract_json(reply)


def llm_text(prompt: str, role: str = "jarvis", timeout: float = 150.0) -> str | None:
    """LLM → 纯文本。失败返回 None。"""
    bridge = _bridge(role, timeout=timeout)
    if not bridge.gateway_url or not bridge.key:
        return None
    try:
        with _CALL_LOCK:
            reply = bridge.send_and_wait(prompt)
    except Exception as e:
        print(f"[Drama] LLM 调用异常: {e}")
        return None
    return (reply or "").strip() or None
