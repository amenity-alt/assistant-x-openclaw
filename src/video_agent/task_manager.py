#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Video 任务队列：ThreadPoolExecutor(1) 异步执行，不阻塞语音主循环。

流程：guard(deny/confirm/auto)
  - auto   → 立即入队执行（facecam 素材合法时）
  - confirm → 登记待确认（generate/render）；approve 后入队，deny/超时记日志
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .action_log import VideoLog
from .asset_manager import cleanup_job_assets
from .export_manager import export_video
from .job_manager import JobPoller
from .opencut_client import OpenCutClient, OpenCutError, get_opencut_client
from .permission_manager import PermissionManager
from .project_manager import resolve_render
from .result_parser import friendly_error, parse_job
from .task import VideoMode, VideoResult, VideoTask


class TaskManager:
    def __init__(self, client: OpenCutClient = None, log: VideoLog = None,
                 perms: PermissionManager = None):
        self.client = client or get_opencut_client()
        self.log = log or VideoLog()
        self.perms = perms or PermissionManager()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video")
        self._lock = threading.Lock()
        self._last_result = None
        self._last_future = None
        self._pending_tasks = {}
        self._current_poller = None

    # ── 提交与执行 ────────────────────────────────────────
    def submit(self, task: VideoTask):
        """auto 任务直接入队；confirm 任务登记待确认并返回 confirm_id。"""
        verdict = self.perms.guard(task)
        if verdict == "deny":
            reason = ""
            if task.mode == VideoMode.FACECAM.value:
                reason = "素材路径不合法或不在允许目录内"
            else:
                reason = "该任务命中危险模式黑名单，已拒绝"
            return self._finish(
                task, VideoResult(status="denied", summary=reason, task_id=task.id)
            )
        if verdict == "confirm":
            confirm_id = self.perms.request_confirm(task)
            with self._lock:
                self._pending_tasks[confirm_id] = task
            self.log.record(
                {
                    "agent": "video",
                    "task": task.prompt[:200],
                    "mode": task.mode,
                    "project": task.project,
                    "source_video": task.source_video,
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

    def submit_approved(self, task: VideoTask):
        """确认已放行（Mission Control 等上层已确认）→ 直接入队。"""
        verdict = self.perms.guard(task)
        if verdict == "deny":
            return self._finish(
                task, VideoResult(status="denied", summary="任务被拒绝", task_id=task.id)
            )
        future = self._pool.submit(self._execute, task)
        with self._lock:
            self._last_future = future
        return future

    def confirm_result(self, confirm_id: str, approved: bool):
        """确认回调：approved → 入队执行；否则取消并记日志。"""
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
            result = VideoResult(
                status="denied", summary="用户拒绝了该任务", task_id=confirm_id
            )
        else:
            result = VideoResult(
                status="cancelled", summary="确认超时，任务已取消", task_id=confirm_id
            )
        return self._finish(task, result) if task else result.to_dict()

    def pending_confirmations(self) -> list:
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
                        "task": task.prompt[:200] if task else "",
                        "remaining": round(m["remaining"], 1),
                    }
                )
            return out

    def cancel_current(self) -> bool:
        """取消当前正在轮询的任务（尽力而为）。"""
        with self._lock:
            poller = self._current_poller
        if poller is not None:
            poller.cancel()
            return True
        return False

    # ── 执行 ─────────────────────────────────────────────
    def _execute(self, task: VideoTask) -> dict:
        t0 = time.time()
        try:
            if not self.client.ensure_server():
                return self._finish(
                    task, VideoResult(
                        status="failed", summary="OpenCut 服务不可用",
                        error="ensure_server failed", task_id=task.id,
                    )
                )
            if task.mode == VideoMode.GENERATE.value:
                job_id = self._submit_generate(task)
            elif task.mode == VideoMode.FACECAM.value:
                job_id = self.client.submit_facecam(task.source_video, task.playback_rate)
            elif task.mode == VideoMode.RENDER.value:
                job_id = self._submit_render(task)
            else:
                return self._finish(
                    task, VideoResult(
                        status="failed", summary=f"未知模式: {task.mode}",
                        task_id=task.id,
                    )
                )
        except OpenCutError as e:
            return self._finish(
                task, VideoResult(
                    status="failed", summary=friendly_error(e),
                    error=str(e), task_id=task.id,
                )
            )
        except Exception as e:
            return self._finish(
                task, VideoResult(
                    status="failed", summary=friendly_error(e),
                    error=str(e), task_id=task.id,
                )
            )

        poller = JobPoller(self.client)
        with self._lock:
            self._current_poller = poller
        try:
            job = poller.wait(job_id)
        finally:
            with self._lock:
                self._current_poller = None
        elapsed = time.time() - t0
        result = parse_job(job, task_id=task.id, elapsed=elapsed)
        if result.status == "success":
            try:
                name = task.project or (task.prompt[:20] if task.prompt else "jarvis-video")
                result.video_path = export_video(self.client, job_id, name)
                result.summary = f"视频已生成：{result.video_path}"
            except Exception as e:
                result.status = "failed"
                result.summary = f"渲染完成但导出失败: {friendly_error(e)}"
        # 清理素材双份拷贝（尽力而为）
        try:
            cleanup_job_assets(job_id)
        except Exception:
            pass
        return self._finish(task, result)

    def _submit_generate(self, task: VideoTask) -> str:
        if not self.client.has_ai_key():
            raise OpenCutError("AI API key required")
        return self.client.submit_generate(
            task.prompt, task.duration_sec or 60, task.voice
        )

    def _submit_render(self, task: VideoTask) -> str:
        resolved = resolve_render(task.project)
        if resolved is None:
            raise OpenCutError(f"未知渲染项目: {task.project or '(空)'}")
        entry_point, composition_id = resolved
        return self.client.submit_render(composition_id, entry_point)

    # ── 结果与日志 ────────────────────────────────────────
    def _finish(self, task, result: VideoResult) -> dict:
        d = result.to_dict()
        if task is not None:
            d["mode"] = task.mode
            d["project"] = task.project
        with self._lock:
            self._last_result = d
        self.log.record(
            {
                "agent": "video",
                "task_id": result.task_id,
                "mode": task.mode if task else "",
                "project": task.project if task else "",
                "status": result.status,
                "summary": (result.summary or "")[:300],
                "video_path": result.video_path,
                "job_id": result.job_id,
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
