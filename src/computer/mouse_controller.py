#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""鼠标控制：移动 / 单击 / 双击 / 滚动。

主实现用 macOS CoreGraphics C API（ctypes 直接调系统框架，零 pip 依赖）；
CGEvent 坐标与 AX 元素 position 同为全局点坐标（原点左上），语义定位结果可直接用。
失败时降级 System Events `click at`。
"""

import ctypes
import time

from .apple_script import osascript

_CG = None
_CG_EVENT_TYPES = {
    "mousemoved": 5,
    "leftmousedown": 1,
    "leftmouseup": 2,
    "rightmousedown": 3,
    "rightmouseup": 4,
    "scroll": 22,
}
_CG_TAP = 0  # kCGHIDEventTap


def _load_cg():
    """惰性加载 CoreGraphics（失败返回 None，走 System Events 降级）。"""
    global _CG
    if _CG is not None:
        return _CG
    try:
        lib = ctypes.CDLL(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        # 注意：CGPoint 是按值传递的结构体，不能设置 argtypes
        # （否则 ctypes 会尝试转 void* 报 TypeError）；只设 restype 防指针截断。
        lib.CGEventCreateMouseEvent.restype = ctypes.c_void_p
        lib.CGEventCreateScrollWheelEvent.restype = ctypes.c_void_p
        lib.CGEventCreateScrollWheelEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int32,
        ]
        lib.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        _CG = lib
    except Exception as e:
        print(f"[Computer] CoreGraphics 加载失败，鼠标降级 System Events: {e}")
        _CG = False
    return _CG


def _point(x: float, y: float):
    class _Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_float), ("y", ctypes.c_float)]
    return _Point(float(x), float(y))


def _post_mouse(ev_type: str, x: float, y: float, button: int = 0):
    cg = _load_cg()
    if not cg:
        return False
    ev = cg.CGEventCreateMouseEvent(None, _CG_EVENT_TYPES[ev_type], _point(x, y), button)
    if not ev:
        return False
    cg.CGEventPost(_CG_TAP, ev)
    return True


def move(x: float, y: float) -> dict:
    """移动鼠标到 (x, y)，不点击。"""
    if _post_mouse("mousemoved", x, y):
        return {"ok": True, "message": f"鼠标已移动到 ({int(x)},{int(y)})"}
    # 降级：System Events 无纯移动，用 click 近似不可靠 → 报错
    return {"ok": False, "message": "鼠标移动不可用（CoreGraphics 加载失败）"}


def click(x: float, y: float, double: bool = False, button: str = "left") -> dict:
    """在 (x, y) 单击/双击。返回 {ok, message}。"""
    try:
        cg = _load_cg()
        if cg:
            if button == "right":
                down, up = "rightmousedown", "rightmouseup"
            else:
                down, up = "leftmousedown", "leftmouseup"
            n = 2 if double else 1
            for _ in range(n):
                _post_mouse(down, x, y)
                time.sleep(0.03)
                _post_mouse(up, x, y)
                time.sleep(0.05)
            kind = "双击" if double else "单击"
            return {"ok": True, "message": f"已{kind} ({int(x)},{int(y)})"}
        return _fallback_click(x, y, double)
    except Exception as e:
        return {"ok": False, "message": f"点击异常: {e}"}


def _fallback_click(x: float, y: float, double: bool = False) -> dict:
    n = 2 if double else 1
    for _ in range(n):
        code, out, err = osascript(
            f"tell application \"System Events\" to click at {{{int(x)}, {int(y)}}}",
            timeout=15.0,
        )
        if code != 0:
            return {"ok": False, "message": f"点击失败: {err or out}"}
        time.sleep(0.1)
    return {"ok": True, "message": f"已点击 ({int(x)},{int(y)})"}


def scroll(amount: int = -3) -> dict:
    """滚动（amount>0 向上，<0 向下）。"""
    cg = _load_cg()
    if not cg:
        return {"ok": False, "message": "滚动不可用（CoreGraphics 加载失败）"}
    try:
        ev = cg.CGEventCreateScrollWheelEvent(None, 0, 1, int(amount))
        if not ev:
            return {"ok": False, "message": "滚动事件创建失败"}
        cg.CGEventPost(_CG_TAP, ev)
        return {"ok": True, "message": f"已滚动 ({amount})"}
    except Exception as e:
        return {"ok": False, "message": f"滚动异常: {e}"}
