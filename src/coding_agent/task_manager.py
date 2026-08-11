#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Coding 任务队列：ThreadPoolExecutor(1) 异步执行，不阻塞语音主循环。

流程：guard(deny/confirm/auto)
  - auto   → 立即入队执行
  - confirm → 登记待确认（Phase 2 语音确认接入 approve/deny）；
              approve 后入队执行，deny/超时记入日志
"""

import threading
from concurrent.futures import ThreadPoolExecutor

from . import git_manager as _git
from .action_log import CodingLog
from .codex_client import CodexClient
from .permission_manager import PermissionManager
from .result_parser import parse_events  # noqa: F401  (测试直接引用)
from .task import CodingMode, CodingResult, CodingTask


class TaskManager:
    def __init__(self, client: CodexClient = None, log: CodingLog = None,
                 perms: PermissionManager = None, git=None):
        self.client = client or CodexClient()
        self.log = log or CodingLog()
        self.perms = perms or PermissionManager()
        self.git = git or _git.GitManager()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="coding")
        self._lock = threading.Lock()
        self._last_result = None
        self._last_future = None
        self._pending_tasks = {}

    # ── 提交与执行 ────────────────────────────────────────
    def submit(self, task: CodingTask):
        """auto 任务直接入队；confirm 任务登记待确认并返回 confirm_id。"""
        verdict = self.perms.guard(task)
        if verdict == "deny":
            return self._finish(
                task, CodingResult(status="denied", summary="该任务命中危险模式黑名单，已拒绝", task_id=task.id)
            )
        if verdict == "confirm":
            confirm_id = self.perms.request_confirm(task)
            with self._lock:
                self._pending_tasks[confirm_id] = task
            self.log.record(
                {
                    "agent": "coding",
                    "task": task.task[:200],
                    "mode": task.mode,
                    "project": task.project,
                    "status": "waiting_confirmation",
                    "confirm_id": confirm_id,
                    "task_id": task.id,
                }
            )
            return {
                "status": "waiting_confirmation",
                "confirm_id": confirm_id,
                "task_id": task.id,
            }
        future = self._pool.submit(self._execute, task)
        with self._lock:
            self._last_future = future
        return future

    def submit_approved(self, task: CodingTask):
        """已由外部（如 Mission Control）确认的任务直接入队执行，跳过 guard。

        仅供上层编排器在完成自己的确认/黑名单检查后调用；普通入口仍走 submit()。
        """
        future = self._pool.submit(self._execute, task)
        with self._lock:
            self._last_future = future
        return future

    def confirm_result(self, confirm_id: str, approved: bool):
        """确认回调（Phase 2 语音接入）。

        approved → 校验通过后入队执行；
        denied/超时/未知 confirm_id → 取消并记日志，绝不执行任务。
        """
        ok = self.perms.approve(confirm_id) if approved else self.perms.deny(confirm_id)
        if not ok:
            return {"status": "unknown_confirm", "confirm_id": confirm_id}
        with self._lock:
            task = self._pending_tasks.pop(confirm_id, None)
        verdict = self.perms.wait(confirm_id)
        if verdict == "approved" and task is not None:
            future = self._pool.submit(self._execute, task)
            with self._lock:
                self._last_future = future
            return future
        if verdict == "denied":
            result = CodingResult(
                status="denied", summary="用户拒绝了该任务", task_id=confirm_id
            )
        else:
            result = CodingResult(
                status="cancelled", summary="确认超时，任务已取消", task_id=confirm_id
            )
        return self._finish(task, result) if task else result.to_dict()

    def pending_confirmations(self) -> list:
        """待确认任务列表（Phase 2 语音确认接入用）。"""
        meta = self.perms.pending()
        with self._lock:
            out = []
            for m in meta:
                task = self._pending_tasks.get(m["confirm_id"])
                out.append(
                    {
                        "confirm_id": m["confirm_id"],
                        "mode": task.mode if task else m.get("mode", ""),
                        "project": task.project if task else m.get("project", ""),
                        "task": task.task[:200] if task else "",
                        "remaining": round(m["remaining"], 1),
                    }
                )
            return out

    def _execute(self, task: CodingTask) -> dict:
        """执行任务：Codex 运行 + git diff 摘要 + 日志。返回结果 dict。"""
        result = self.client.run(task)
        if result.status == "success" and task.mode in (
            CodingMode.MODIFY.value, CodingMode.TEST.value
        ):
            result.git_diff = self.git.diff_stat(task.project)
        if task.mode == CodingMode.GIT.value:
            result = self._run_git(task, result)
        return self._finish(task, result)

    def _run_git(self, task: CodingTask, result: CodingResult) -> CodingResult:
        """git 模式：status/log/diff 只读执行；commit/push 已由确认层放行。"""
        t = (task.task or "").lower()
        if "status" in t or "状态" in task.task:
            out = self.git.status(task.project)
            result.summary = out or "工作区干净"
            result.status = "success"
        elif "diff" in t or "改动" in task.task:
            result.summary = self.git.diff_stat(task.project) or "无改动"
            result.status = "success"
        elif "log" in t or "提交记录" in task.task or "昨天" in task.task:
            result.summary = self.git.log(task.project, 10)
            result.status = "success"
        elif "commit" in t or "提交" in task.task:
            r = self.git.commit(task.project, task.task)
            result.status = "success" if r["ok"] else "failed"
            result.summary = (r["out"] or r["err"]).strip()
        elif "push" in t or "推送" in task.task:
            r = self.git.push(task.project)
            result.status = "success" if r["ok"] else "failed"
            result.summary = (r["out"] or r["err"]).strip()
        else:
            result.summary = self.git.status(task.project) or "工作区干净"
            result.status = "success"
        return result

    # ── 结果与日志 ────────────────────────────────────────
    def _finish(self, task, result: CodingResult) -> dict:
        d = result.to_dict()
        if task is not None:
            d["mode"] = task.mode
            d["project"] = task.project
        with self._lock:
            self._last_result = d
        self.log.record(
            {
                "agent": "coding",
                "task_id": result.task_id,
                "mode": task.mode if task else "",
                "project": task.project if task else "",
                "status": result.status,
                "summary": (result.summary or "")[:300],
                "files_changed": len(result.files_changed),
                "elapsed": result.elapsed,
            }
        )
        return d

    def last_result(self) -> dict:
        with self._lock:
            return dict(self._last_result) if self._last_result else {}

    def last_future(self):
        with self._lock:
            return self._last_future
