#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""键盘控制：输入文字 / 按组合键（System Events，零依赖）。

- type_text：ASCII 直接 keystroke；含非 ASCII 时走「剪贴板 + Cmd+V」（保存并恢复剪贴板）。
- press_keys：解析 "Command+Space" 风格组合键 → `keystroke` / `key code` + modifiers。
"""

import re

from .apple_script import osascript, quote

# 具名键 → macOS key code（常用子集）
KEY_CODES = {
    "return": 36, "enter": 36, "回车": 36,
    "tab": 48,
    "space": 49, "空格": 49,
    "delete": 51, "backspace": 51, "退格": 51,
    "escape": 53, "esc": 53,
    "capslock": 57, "caps lock": 57,
    "left": 123, "左": 123, "arrowleft": 123,
    "right": 124, "右": 124, "arrowright": 124,
    "down": 125, "下": 125, "arrowdown": 125,
    "up": 126, "上": 126, "arrowup": 126,
    "home": 115, "end": 119,
    "pageup": 116, "pagedown": 121,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118,
    "f5": 96, "f6": 97, "f7": 98, "f8": 100,
    "f9": 101, "f10": 109, "f11": 103, "f12": 111,
}

# 修饰键 → AppleScript 修饰语
MODIFIERS = {
    "command": "command down", "cmd": "command down",
    "control": "control down", "ctrl": "control down",
    "option": "option down", "alt": "option down", "opt": "option down",
    "shift": "shift down",
}

# 可安全直接 keystroke 的字符（无需 shift / 剪贴板）
_SAFE_KEYS = set("abcdefghijklmnopqrstuvwxyz0123456789 .,!?;:'-")

# 剪贴板操作（保存/恢复，避免破坏用户剪贴板）
_CLIP_GET = "the clipboard as text"
_CLIP_SET = "set the clipboard to {text}"


def _get_clipboard() -> str:
    code, out, err = osascript(_CLIP_GET, timeout=5.0)
    return out if code == 0 else ""


def _set_clipboard(text: str):
    script = f"set the clipboard to {quote(text)}"
    osascript(script, timeout=5.0)


def type_text(text: str) -> dict:
    """向当前前台应用的焦点位置输入文字。返回 {ok, message}。"""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "message": "没有可输入的内容"}
    try:
        if all(c in _SAFE_KEYS for c in text):
            script = f'tell application "System Events" to keystroke {quote(text)}'
            code, out, err = osascript(script, timeout=20.0)
            if code == 0:
                return {"ok": True, "message": f"已输入: {text}"}
            return {"ok": False, "message": f"输入失败: {err or out}"}
        # 非 ASCII（中文等）→ 剪贴板粘贴（先保存再恢复）
        old = _get_clipboard()
        _set_clipboard(text)
        code, out, err = osascript(
            'tell application "System Events" to keystroke "v" using command down',
            timeout=20.0,
        )
        if old:
            _set_clipboard(old)
        if code == 0:
            return {"ok": True, "message": f"已输入: {text}"}
        return {"ok": False, "message": f"输入失败: {err or out}"}
    except Exception as e:
        return {"ok": False, "message": f"输入异常: {e}"}


def is_valid_combo(combo: str) -> bool:
    """校验组合键描述是否可解析（供 intent 层过滤误判）。"""
    parts = [p.strip().lower() for p in re.split(r"[+\s]+", (combo or "").strip()) if p.strip()]
    if not parts:
        return False
    has_key = False
    for p in parts:
        if p in MODIFIERS:
            continue
        if p in KEY_CODES or (len(p) == 1 and p.isalnum()):
            has_key = True
            continue
        return False
    return has_key


def press_keys(combo: str) -> dict:
    """按组合键，如 "Command+Space" / "Shift+A" / "回车"。返回 {ok, message}。"""
    parts = [p.strip().lower() for p in re.split(r"[+\s]+", (combo or "").strip()) if p.strip()]
    if not parts:
        return {"ok": False, "message": "组合键为空"}
    mods = [MODIFIERS[p] for p in parts if p in MODIFIERS]
    keys = [p for p in parts if p not in MODIFIERS]
    if not keys:
        return {"ok": False, "message": f"缺少按键: {combo}"}
    key = keys[0]
    mod_clause = ""
    if mods:
        mod_clause = " using {" + ", ".join(mods) + "}"
    try:
        if key in KEY_CODES:
            script = (
                f'tell application "System Events" to key code {KEY_CODES[key]}{mod_clause}'
            )
        elif len(key) == 1:
            script = (
                f'tell application "System Events" to keystroke {quote(key)}{mod_clause}'
            )
        else:
            return {"ok": False, "message": f"不认识的按键: {key}"}
        code, out, err = osascript(script, timeout=20.0)
        if code == 0:
            return {"ok": True, "message": f"已按: {combo}"}
        return {"ok": False, "message": f"按键失败: {err or out}"}
    except Exception as e:
        return {"ok": False, "message": f"按键异常: {e}"}
