#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Codex CLI 客户端：codex exec / codex review 的受控调用。

- 固定参数组合（--json -s -C --color never），不拼接用户输入进 shell；
- 超时后杀进程组，绝不悬挂；
- stdout 的 JSONL 事件流交给 result_parser 解析，stderr 仅作错误采集。
"""

import json
import os
import shutil
import subprocess
import time

from .result_parser import parse_events
from .task import CodingMode, CodingResult, CodingTask

DEFAULT_TIMEOUT = 300.0
_DEFAULT_BIN = "/Applications/ChatGPT.app/Contents/Resources/codex"


class CodexClient:
    def __init__(self, codex_bin: str = None, timeout: float = DEFAULT_TIMEOUT):
        self.bin = codex_bin or shutil.which("codex") or _DEFAULT_BIN
        self.timeout = timeout

    # ── 状态 ─────────────────────────────────────────────
    def version(self) -> str:
        try:
            p = subprocess.run(
                [self.bin, "--version"], capture_output=True, text=True, timeout=10.0
            )
            if p.returncode == 0:
                return p.stdout.strip().splitlines()[0]
        except Exception as e:
            print(f"[Coding] codex --version 失败: {e}")
        return ""

    # ── 执行 ─────────────────────────────────────────────
    def run(self, task: CodingTask) -> CodingResult:
        started = time.time()
        result = CodingResult(task_id=task.id)
        try:
            if task.mode == CodingMode.REVIEW.value:
                stdout, stderr, code = self._run_review(task)
            else:
                stdout, stderr, code = self._run_exec(task)
            result.elapsed = round(time.time() - started, 2)
            if stdout:
                parsed = parse_events(stdout)
                result.summary = parsed["summary"]
                result.files_changed = parsed["files_changed"]
                result.commands = parsed["commands"]
                result.usage = parsed["usage"]
            if code != 0:
                result.status = "failed"
                result.stderr = (stderr or "")[:2000]
                if not result.summary:
                    result.summary = f"Codex 退出码 {code}"
            else:
                result.status = "success"
            return result
        except subprocess.TimeoutExpired:
            result.status = "failed"
            result.elapsed = round(time.time() - started, 2)
            result.stderr = f"执行超时（>{self.timeout:.0f}s），已终止"
            return result
        except Exception as e:
            result.status = "failed"
            result.stderr = str(e)[:500]
            return result

    def _run_exec(self, task: CodingTask):
        """codex exec --json -s <sandbox> -C <project> <prompt>"""
        cmd = [
            self.bin, "exec", "--json",
            "-s", task.sandbox,
            "-C", task.project,
            "--color", "never",
            task.task,
        ]
        return self._subprocess(cmd, task.project)

    def _run_review(self, task: CodingTask):
        """codex review --uncommitted（cwd=项目；review 无 --json，取文本输出）"""
        cmd = [self.bin, "review", "--uncommitted", task.task]
        return self._subprocess(cmd, task.project)

    def _subprocess(self, cmd, cwd: str):
        """带超时 + 进程组杀除的 subprocess 封装。返回 (stdout, stderr, returncode)。"""
        try:
            p = subprocess.Popen(
                cmd,
                cwd=cwd or None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,  # 独立进程组，超时后可整组终止
            )
            try:
                stdout, stderr = p.communicate(timeout=self.timeout)
                return stdout, stderr, p.returncode
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(p.pid), 9)
                except Exception:
                    p.kill()
                p.wait(timeout=5)
                raise
        except FileNotFoundError:
            print(f"[Coding] 找不到 Codex CLI: {self.bin}")
            raise
