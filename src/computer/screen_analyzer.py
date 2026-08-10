#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""屏幕语义定位：System Events AX 元素树 → 语义目标 → 坐标。

核心原则：不做 click(300,500)。先按 role/title/description 在前台 App 的
元素树里找到目标元素，取其 position/size 中心坐标，再交给鼠标控制器。
坐标与 CGEvent 同为全局点坐标（原点左上）。
"""

from .apple_script import osascript, quote
from . import ax_walker

# AX role 归一化映射（System Events 返回的 role 可能与标准 AXRole 命名略异）
_ROLE_HINTS = {
    "button": ("button", "按钮"),
    "textfield": ("textfield", "text area", "输入框", "文本框"),
    "statictext": ("static text", "文本"),
    "checkbox": ("checkbox", "复选框"),
    "menu": ("menu", "菜单"),
    "window": ("window", "窗口"),
}


def frontmost_app() -> str:
    """当前前台应用进程名（如 WeChat / Safari）。"""
    code, out, err = osascript(
        'tell application "System Events" to get name of first application '
        'process whose frontmost is true',
        timeout=10.0,
    )
    return out if code == 0 else ""


def _role_matches(role: str, want: str) -> bool:
    """role 是否匹配期望（支持 'button' / '按钮' / 'AXButton' 等写法）。"""
    if not role:
        return False
    r = role.lower().replace("ax", "")
    w = want.lower().replace("ax", "")
    if w in r or r in w:
        return True
    hints = _ROLE_HINTS.get(w, (w,))
    return any(h in r or r in h for h in hints)


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def list_elements(app: str, timeout: float = 12.0) -> list:
    """列出前台窗口 AX 元素：[{role,title,desc,value,x,y,w,h}]。

    主通道：Accessibility C API（快）；失败时降级 AppleScript `entire contents`。
    """
    fast = ax_walker.list_elements(app)
    if fast:
        return fast
    script = (
        f'tell application "System Events" to tell process {quote(app)}\n'
        "  try\n"
        "    set allEls to entire contents of front window\n"
        "  on error\n"
        "    return \"\"\n"
        "  end try\n"
        '  set out to ""\n'
        "  repeat with el in allEls\n"
        "    try\n"
        '      set info to get {role, title, description, value, position, size} of el\n'
        '      set r to item 1 of info\n'
        '      set t to item 2 of info\n'
        '      set d to item 3 of info\n'
        '      set v to item 4 of info\n'
        '      set p to item 5 of info\n'
        '      set s to item 6 of info\n'
        "      set out to out & r & \"||\" & t & \"||\" & d & \"||\" & v & \"||\" & "
        "(item 1 of p) & \",\" & (item 2 of p) & \"||\" & "
        "(item 1 of s) & \",\" & (item 2 of s) & linefeed\n"
        "    end try\n"
        "  end repeat\n"
        "  return out\n"
        "end tell"
    )
    code, out, err = osascript(script, timeout=timeout)
    if code != 0:
        return []
    els = []
    for ln in out.splitlines():
        parts = ln.split("||")
        if len(parts) != 6:
            continue
        role, title, desc, value, pos, size = parts
        try:
            x, y = (float(v) for v in pos.split(","))
            w, h = (float(v) for v in size.split(","))
        except ValueError:
            continue
        els.append(
            {
                "role": role.strip(),
                "title": title.strip(),
                "desc": desc.strip(),
                "value": value.strip(),
                "x": x, "y": y, "w": w, "h": h,
                "center": (x + w / 2.0, y + h / 2.0),
            }
        )
    return els


def find_element(app: str, text: str, role: str = "button") -> dict:
    """在 app 的 AX 树里找「文本匹配 + role 匹配」的第一个元素。

    匹配优先级：title → description → value（包含匹配，忽略大小写）。
    返回元素 dict（含 center）或 None。
    """
    t = _norm(text)
    if not t:
        return None
    for el in list_elements(app):
        if role and not _role_matches(el["role"], role):
            continue
        for field in ("title", "desc", "value"):
            v = _norm(el[field])
            if v and (t in v or v in t):
                return el
    return None


def describe_screen(app: str = None, max_items: int = 12) -> dict:
    """描述前台屏幕：窗口标题 + 可交互元素摘要（语义定位的结果喂给大脑/语音）。

    返回 {app, window, buttons[], fields[], summary, count}。
    """
    app = app or frontmost_app()
    els = list_elements(app)
    window = ""
    for e in els:
        if e["role"].lower() == "axwindow" and e["title"]:
            window = e["title"]
            break
    buttons = []
    fields = []
    others = []
    for e in els:
        r = e["role"].lower()
        label = e["title"] or e["desc"] or e["value"]
        if not label or label == "missing value":
            continue
        item = {"label": label, "role": e["role"], "center": e["center"]}
        if "button" in r:
            buttons.append(item)
        elif "textfield" in r or "text area" in r or "searchfield" in r:
            fields.append(item)
        elif "checkbox" in r or "menu" in r or "popup" in r:
            others.append(item)
    bnames = [b["label"] for b in buttons[:max_items]]
    fnames = [f["label"] for f in fields[:max_items]]
    parts = []
    if window:
        parts.append(f"窗口「{window}」")
    if bnames:
        parts.append("可点击按钮: " + "、".join(bnames))
    if fnames:
        parts.append("输入框: " + "、".join(fnames))
    if not parts:
        parts.append("未找到可交互元素（该应用可能不暴露界面信息）")
    return {
        "app": app,
        "window": window,
        "buttons": buttons,
        "fields": fields,
        "summary": "。".join(parts),
        "count": len(els),
    }
