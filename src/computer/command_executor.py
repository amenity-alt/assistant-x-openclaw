#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Action 派发执行器：后台线程执行 + 统一超时 + 操作日志。

原则：Jarvis 主循环只做意图解析与入队，实际系统操作在这里的
ThreadPoolExecutor(1) 后台执行，绝不阻塞语音主循环。
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .action import Action, Risk
from .action_log import ActionLog
from . import (
    application_controller,
    keyboard_controller,
    mouse_controller,
    screen_analyzer,
    screen_capture,
    screen_ocr,
)

_EXEC_TIMEOUT = 20.0  # 单个 Action 执行上限（秒）


class CommandExecutor:
    def __init__(self, log: ActionLog = None):
        self._log = log or ActionLog()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="computer")
        self._lock = threading.Lock()
        self._last_result = None  # 最近一次执行结果（Phase 5 口播用）

    # ── 提交与执行 ──────────────────────────────────────
    def submit(self, action: Action):
        """入队执行（异步）。返回 future，不阻塞调用方。"""
        return self._pool.submit(self.execute, action)

    def execute(self, action: Action) -> dict:
        """同步执行单个 Action（内部自带超时）。"""
        if action.risk == Risk.DENY:
            return self._finish(action, ok=False, detail="该操作已被安全策略拒绝")
        started = time.time()
        try:
            result = self._dispatch(action)
        except Exception as e:
            result = {"ok": False, "message": f"执行异常: {e}"}
        result.setdefault("ok", False)
        result.setdefault("message", "")
        elapsed = round(time.time() - started, 2)
        result["elapsed"] = elapsed
        self._finish(
            action,
            ok=result["ok"],
            detail=result["message"],
            elapsed=elapsed,
            extra=result,
        )
        return result

    # ── 派发表（Phase 2：应用控制 + 键盘 + 语义点击；后续按 action 扩充） ──
    def _dispatch(self, action: Action) -> dict:
        a = action.action
        target = action.target
        if a == "open_app":
            return application_controller.open_app(target)
        if a == "close_app":
            return application_controller.close_app(target)
        if a == "switch_app":
            display, _path = application_controller.resolve(target)
            return application_controller.activate_app(display)
        if a == "type_text":
            return keyboard_controller.type_text(target)
        if a == "press_keys":
            return keyboard_controller.press_keys(target)
        if a == "click_element":
            return self._click_element(target, double=False)
        if a == "double_click_element":
            return self._click_element(target, double=True)
        if a == "mouse_move":
            x, y = action.params.get("x", 0), action.params.get("y", 0)
            return mouse_controller.move(x, y)
        if a == "scroll":
            return mouse_controller.scroll(action.params.get("amount", -3))
        if a == "take_screenshot":
            path = screen_capture.capture()
            if not path:
                return {
                    "ok": False,
                    "message": "截图失败：请检查终端是否已授予屏幕录制权限",
                }
            return {"ok": True, "message": f"已截图: {path}", "path": path}
        if a == "get_screen_state":
            return self._screen_state()
        if a == "list_apps":
            apps = application_controller.list_running_apps()
            if not apps:
                return {"ok": False, "message": "无法获取运行中的应用列表"}
            return {
                "ok": True,
                "message": "正在运行: " + "、".join(apps),
                "apps": apps,
            }
        return {"ok": False, "message": f"未知操作: {a}"}

    def _screen_state(self) -> dict:
        """查看屏幕：截图 + AX 描述 + OCR 文字层。"""
        app = screen_analyzer.frontmost_app()
        desc = screen_analyzer.describe_screen(app)
        path = screen_capture.capture()
        ocr_texts = []
        if path:
            ocr_texts = screen_ocr.recognize(path)
        texts = [t["text"] for t in ocr_texts[:10]]
        msg = f"前台应用 {desc['app']}。{desc['summary']}"
        if texts:
            msg += "。屏幕可见文字: " + "；".join(texts[:8])
        result = {
            "ok": True,
            "message": msg,
            "app": desc["app"],
            "window": desc["window"],
            "screenshot": path,
            "elements_count": desc["count"],
            "texts": texts,
        }
        return result

    def _click_element(self, text: str, double: bool = False) -> dict:
        """语义点击：前台 App AX 树里找「text」元素 → 中心坐标 → 鼠标点击。"""
        app = screen_analyzer.frontmost_app()
        if not app:
            return {"ok": False, "message": "无法获取前台应用"}
        el = screen_analyzer.find_element(app, text)
        if not el:
            return {
                "ok": False,
                "message": f"在 {app} 中找不到「{text}」按钮/元素（该应用可能不暴露界面元素）",
            }
        x, y = el["center"]
        kind = "双击" if double else "单击"
        result = mouse_controller.click(x, y, double=double)
        if result["ok"]:
            result["message"] = f"已{kind}「{text}」({int(x)},{int(y)})"
        return result

    # ── 日志与结果 ──────────────────────────────────────
    def _finish(
        self,
        action: Action,
        ok: bool,
        detail: str = "",
        elapsed: float = 0.0,
        extra: dict = None,
    ):
        entry = {
            "agent": "computer",
            "action": action.action,
            "target": action.target,
            "params": action.params,
            "risk": action.risk.value,
            "ok": ok,
            "detail": detail,
            "elapsed": elapsed,
            "action_id": action.id,
        }
        if extra:
            for k, v in extra.items():
                entry.setdefault(k, v)
        with self._lock:
            self._last_result = entry
        self._log.record(entry)
        return entry

    def last_result(self) -> dict:
        with self._lock:
            return dict(self._last_result) if self._last_result else {}

    def shutdown(self):
        self._pool.shutdown(wait=False)
