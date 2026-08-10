#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Accessibility C API（AXUIElement）轻量封装 — 语义定位主通道。

用 ctypes 直接调 macOS ApplicationServices 的 AX 接口（零 pip 依赖），
比 AppleScript 逐元素取属性快一个数量级：每个元素用一次
AXUIElementCopyAttributeValues 批量取 role/title/desc/value/position/size。

坐标与 CGEvent 同为全局点坐标（原点左上）。
"""

import ctypes
import subprocess
import threading

_APP_SVC = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"

_kCFStringEncodingUTF8 = 0x08000100
_kAXValueTypeCGPoint = 1
_kAXValueTypeCGSize = 2

# AXError
_ERR_SUCCESS = 0
_ERR_APIDISABLED = -25211

# 常量属性名
_ATTR_WINDOWS = "AXWindows"
_ATTR_FOCUSED_WINDOW = "AXFocusedWindow"
_ATTR_ROLE = "AXRole"
_ATTR_TITLE = "AXTitle"
_ATTR_DESC = "AXDescription"
_ATTR_VALUE = "AXValue"
_ATTR_POSITION = "AXPosition"
_ATTR_SIZE = "AXSize"
_ATTR_CHILDREN = "AXChildren"
_ATTR_CHILDREN_NAV = "AXChildrenInNavigationOrder"


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("w", ctypes.c_double), ("h", ctypes.c_double)]


class _AX:
    """AX C API 绑定（惰性加载 + 线程锁）。"""

    def __init__(self):
        self.lib = ctypes.CDLL(_APP_SVC)
        l = self.lib
        l.CFStringGetTypeID.restype = ctypes.c_ulong
        l.CFGetTypeID.restype = ctypes.c_ulong
        l.CFGetTypeID.argtypes = [ctypes.c_void_p]
        l.CFStringGetCString.restype = ctypes.c_ubyte
        l.CFStringGetCString.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32,
        ]
        l.CFNumberGetTypeID.restype = ctypes.c_ulong
        l.CFNumberGetValue.restype = ctypes.c_ubyte
        l.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
        l.CFArrayGetCount.restype = ctypes.c_long
        l.CFArrayGetCount.argtypes = [ctypes.c_void_p]
        l.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
        l.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
        l.CFArrayCreate.restype = ctypes.c_void_p
        l.CFArrayCreate.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_long, ctypes.c_void_p]
        l.CFRelease.argtypes = [ctypes.c_void_p]
        l.CFRetain.restype = ctypes.c_void_p
        l.CFRetain.argtypes = [ctypes.c_void_p]
        l.AXUIElementCreateApplication.restype = ctypes.c_void_p
        l.AXUIElementCreateApplication.argtypes = [ctypes.c_int]
        l.AXUIElementCopyAttributeValue.restype = ctypes.c_int
        l.AXUIElementCopyAttributeValue.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
        ]
        l.AXUIElementCopyAttributeValues.restype = ctypes.c_int
        l.AXUIElementCopyAttributeValues.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p),
        ]
        l.AXValueGetTypeID.restype = ctypes.c_ulong
        l.AXValueGetValue.restype = ctypes.c_ubyte
        l.AXValueGetValue.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        self._string_type_id = l.CFStringGetTypeID()
        self._number_type_id = l.CFNumberGetTypeID()
        self._axvalue_type_id = l.AXValueGetTypeID()
        # 缓存常量 CFString（进程生命周期内不释放）
        self._attrs = {}
        for name in (
            _ATTR_WINDOWS, _ATTR_FOCUSED_WINDOW, _ATTR_ROLE, _ATTR_TITLE,
            _ATTR_DESC, _ATTR_VALUE, _ATTR_POSITION, _ATTR_SIZE,
            _ATTR_CHILDREN, _ATTR_CHILDREN_NAV,
        ):
            self._attrs[name] = self._make_cfstring(name)

    def _make_cfstring(self, s: str) -> int:
        l = self.lib
        l.CFStringCreateWithCString.restype = ctypes.c_void_p
        l.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        ref = l.CFStringCreateWithCString(None, s.encode("utf-8"), _kCFStringEncodingUTF8)
        if not ref:
            raise RuntimeError(f"CFStringCreateWithCString failed: {s}")
        return ref

    def _attr(self, el, name: str):
        """取单个属性（CFTypeRef 或 None）。"""
        ref = ctypes.c_void_p()
        err = self.lib.AXUIElementCopyAttributeValue(el, self._attrs[name], ctypes.byref(ref))
        if err != _ERR_SUCCESS:
            return None
        return ref.value

    def _attr_batch(self, el, names):
        """批量取多个属性（逐个 AXUIElementCopyAttributeValue；C 调用本身极快，
        避开 AXUIElementCopyAttributeValues 批量 API 的稳定性问题）。"""
        return [self._attr(el, name) for name in names]

    def _children(self, el):
        """元素的子元素 refs 列表（AXChildren，兼容导航序）。"""
        ref = self._attr(el, _ATTR_CHILDREN)
        if ref is None:
            ref = self._attr(el, _ATTR_CHILDREN_NAV)
        if ref is None:
            return []
        kids = []
        for i in range(self.lib.CFArrayGetCount(ref)):
            kid = self.lib.CFArrayGetValueAtIndex(ref, i)
            self.lib.CFRetain(kid)  # 借用引用 → 持有，防止数组释放后失效
            kids.append(kid)
        self.lib.CFRelease(ref)
        return kids

    # ── CFTypeRef → Python ─────────────────────────────
    def _text(self, ref) -> str:
        if not ref or self.lib.CFGetTypeID(ref) != self._string_type_id:
            return ""
        buf = ctypes.create_string_buffer(4096)
        ok = self.lib.CFStringGetCString(ref, buf, 4096, _kCFStringEncodingUTF8)
        return buf.value.decode("utf-8", "replace") if ok else ""

    def _number(self, ref):
        if not ref or self.lib.CFGetTypeID(ref) != self._number_type_id:
            return None
        v = ctypes.c_double()
        if self.lib.CFNumberGetValue(ref, 13, ctypes.byref(v)):  # kCFNumberDoubleType
            return v.value
        return None

    def _point_size(self, ref):
        """AXValue → (x, y) 或 (w, h) 或 None。"""
        if not ref or self.lib.CFGetTypeID(ref) != self._axvalue_type_id:
            return None
        g = _CGPoint()
        if self.lib.AXValueGetValue(ref, _kAXValueTypeCGPoint, ctypes.byref(g)):
            return (g.x, g.y)
        s = _CGSize()
        if self.lib.AXValueGetValue(ref, _kAXValueTypeCGSize, ctypes.byref(s)):
            return (s.w, s.h)
        return None


_ax = None
_ax_lock = threading.Lock()


def _get_ax():
    global _ax
    with _ax_lock:
        if _ax is None:
            _ax = _AX()
        return _ax


def _pid_of(app: str):
    """应用名 → pid（pgrep 精确匹配；取第一个）。"""
    try:
        p = subprocess.run(
            ["pgrep", "-x", app], capture_output=True, text=True, timeout=5.0
        )
        if p.returncode == 0 and p.stdout.strip():
            return int(p.stdout.splitlines()[0].strip())
    except Exception:
        pass
    return None


def list_elements(app: str, max_depth: int = 20, max_elements: int = 500):
    """遍历 app 前台窗口的 AX 树，返回元素 dict 列表。

    [{role,title,desc,value,x,y,w,h,center}]；不可用/未授权返回空列表。
    """
    try:
        ax = _get_ax()
    except Exception as e:
        print(f"[Computer] AX 初始化失败: {e}")
        return []
    pid = _pid_of(app)
    if pid is None:
        return []
    app_el = ax.lib.AXUIElementCreateApplication(pid)
    if not app_el:
        return []
    try:
        win = ax._attr(app_el, _ATTR_FOCUSED_WINDOW)
        if win is None:
            wins_ref = ax._attr(app_el, _ATTR_WINDOWS)
            win = None
            if wins_ref is not None:
                win = ax.lib.CFArrayGetValueAtIndex(wins_ref, 0)
                ax.lib.CFRelease(wins_ref)
        if win is None:
            return []
        out = []
        held = [win]  # 需释放的引用（窗口 + 所有持有过的子元素）
        stack = [(win, 0)]
        while stack and len(out) < max_elements:
            el, depth = stack.pop()
            if depth > max_depth:
                continue
            vals = ax._attr_batch(
                el,
                [_ATTR_ROLE, _ATTR_TITLE, _ATTR_DESC, _ATTR_VALUE, _ATTR_POSITION, _ATTR_SIZE],
            )
            role = ax._text(vals[0])
            if not role:
                continue
            pos = ax._point_size(vals[4]) if vals[4] else None
            size = ax._point_size(vals[5]) if vals[5] else None
            if pos and size and size[0] > 0 and size[1] > 0:
                x, y = pos
                w, h = size
                out.append(
                    {
                        "role": role,
                        "title": ax._text(vals[1]),
                        "desc": ax._text(vals[2]),
                        "value": ax._text(vals[3]),
                        "x": x, "y": y, "w": w, "h": h,
                        "center": (x + w / 2.0, y + h / 2.0),
                    }
                )
            for kid in reversed(ax._children(el)):
                held.append(kid)
                stack.append((kid, depth + 1))
        for ref in held:
            ax.lib.CFRelease(ref)
        return out
    except Exception as e:
        print(f"[Computer] AX 遍历失败({app}): {e}")
        return []
    finally:
        ax.lib.CFRelease(app_el)
