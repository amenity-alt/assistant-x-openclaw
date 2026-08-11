#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""项目工作区管理：发现 git 仓库、按名称/路径解析目标项目。

默认项目 = 本仓库（assistant-x-openclaw）。可发现根：
~/.openclaw/workspace、~/Documents/ChatGPT、~/workspace（若存在）。
"""

import os
import subprocess
import time

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

_DISCOVER_ROOTS = [
    os.path.expanduser("~/.openclaw/workspace"),
    os.path.expanduser("~/Documents/ChatGPT"),
    os.path.expanduser("~/workspace"),
]


class WorkspaceManager:
    def __init__(self):
        self._cache = None  # (mtime 指纹, projects)

    # ── 项目发现 ─────────────────────────────────────────
    def discover(self, force: bool = False) -> list:
        """发现所有 git 仓库：[{name, path}]。结果缓存（30s）。"""
        now = time.time()
        if self._cache and not force and now - self._cache[0] < 30:
            return self._cache[1]
        projects = []
        seen = set()
        for root in _DISCOVER_ROOTS:
            if not os.path.isdir(root):
                continue
            for entry in sorted(os.listdir(root)):
                p = os.path.join(root, entry)
                if p in seen or not os.path.isdir(p):
                    continue
                seen.add(p)
                if os.path.isdir(os.path.join(p, ".git")):
                    projects.append({"name": entry, "path": p})
        if not projects:
            projects = [{"name": os.path.basename(_PROJECT_ROOT), "path": _PROJECT_ROOT}]
        self._cache = (now, projects)
        return projects

    def is_git_repo(self, path: str) -> bool:
        if not path:
            return False
        if os.path.isdir(os.path.join(path, ".git")):
            return True
        try:
            p = subprocess.run(
                ["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
                capture_output=True, text=True, timeout=5.0,
            )
            return p.returncode == 0 and p.stdout.strip() == "true"
        except Exception:
            return False

    # ── 解析 ─────────────────────────────────────────────
    def resolve(self, hint: str = "") -> dict:
        """按提示解析项目 → {name, path}；无提示返回默认项目。

        匹配顺序：绝对路径 → 已知项目名精确 → 包含匹配 → 默认项目。
        """
        hint = (hint or "").strip()
        default = {"name": os.path.basename(_PROJECT_ROOT), "path": _PROJECT_ROOT}
        if hint and hint not in ("当前项目", "这个项目", "本项目"):
            p = os.path.expanduser(hint)
            if os.path.isdir(p) and self.is_git_repo(p):
                return {"name": os.path.basename(p), "path": p}
            hl = hint.lower()
            for proj in self.discover():
                if proj["name"].lower() == hl:
                    return proj
            for proj in self.discover():
                if hl in proj["name"].lower():
                    return proj
        return default

    def describe(self) -> str:
        """项目列表描述（「现在有哪些项目」用）。"""
        projects = self.discover()
        return "、".join(p["name"] for p in projects) or "未发现项目"
