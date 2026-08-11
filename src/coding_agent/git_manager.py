#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Git 只读包装 + 确认后的 commit/push。

只读命令（status/diff/log/diff_stat）直接执行；
commit/push 由 PermissionManager 确认后才调用（本模块不自动执行）。
"""

import subprocess


class GitManager:
    @staticmethod
    def _run(project: str, args, timeout: float = 15.0) -> dict:
        try:
            p = subprocess.run(
                ["git", "-C", project, *args],
                capture_output=True, text=True, timeout=timeout,
            )
            return {"ok": p.returncode == 0, "out": p.stdout, "err": p.stderr}
        except Exception as e:
            return {"ok": False, "out": "", "err": str(e)}

    # ── 只读 ─────────────────────────────────────────────
    def status(self, project: str) -> str:
        return self._run(project, ["status", "--short"])["out"].strip()

    def diff(self, project: str) -> str:
        return self._run(project, ["diff"])["out"]

    def diff_stat(self, project: str) -> str:
        return self._run(project, ["diff", "--stat"])["out"].strip()

    def log(self, project: str, n: int = 10) -> str:
        return self._run(project, ["log", "--oneline", f"-{n}"])["out"].strip()

    def last_commit(self, project: str) -> str:
        return self._run(project, ["log", "-1", "--oneline"])["out"].strip()

    # ── 确认后执行（调用方保证已确认） ───────────────────────
    def commit(self, project: str, message: str = "codex: apply changes") -> dict:
        r = self._run(project, ["add", "-A"])
        if not r["ok"]:
            return r
        return self._run(project, ["commit", "-m", message])

    def push(self, project: str) -> dict:
        return self._run(project, ["push"])
