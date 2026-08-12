#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Jarvis Video Agent — 语音 AI 视频制作能力模块。

Capability 而非 Agent：任何角色（jarvis / lin-meimei）都可语音触发。
Phase 2：文本生成视频(generate) / 素材剪辑(facecam) / 项目渲染(render) /
        进度查询(status) / 取消(cancel)；generate/render 需语音确认。

用法：
    from video_agent import get_video_agent
    agent = get_video_agent()
    res = agent.handle("帮我做一个1分钟的深圳旅游短视频")  # Future | dict | False
"""

import threading

from . import intent_parser, project_manager
from .action_log import VideoLog
from .opencut_client import get_opencut_client
from .permission_manager import PermissionManager
from .task import VideoMode, VideoResult, VideoTask
from .task_manager import TaskManager


class VideoAgent:
    """视频能力入口：handle(text) / run_sync(text) / status() / confirm()。"""

    def __init__(self):
        self.log = VideoLog()
        self.permissions = PermissionManager()
        self.client = get_opencut_client()
        self.tasks = TaskManager(self.client, self.log, self.permissions)

    # ── 入口 ────────────────────────────────────────────
    def handle(self, text: str, source_video: str = ""):
        """解析意图并（异步）执行/登记确认。

        返回：
          - False    → 未消费（非视频指令，放行大模型）；
          - Future   → auto 任务已入队执行；
          - dict     → 消费结果：waiting_confirmation / denied / success(status)。
        """
        intent = intent_parser.parse(text)
        if intent is None:
            return False

        if intent.mode == VideoMode.STATUS.value:
            res = self.status()
            return {
                "status": "success" if res else "failed",
                "summary": res or "当前没有进行中的视频任务",
            }
        if intent.mode == VideoMode.CANCEL.value:
            ok = self.tasks.cancel_current()
            return {
                "status": "success" if ok else "failed",
                "summary": "已停止视频渲染" if ok else "当前没有可停止的视频任务",
            }

        task = VideoTask(
            mode=intent.mode,
            prompt=intent.prompt,
            source_video=source_video or intent.source_video,
            project=intent.project,
            duration_sec=intent.duration_sec,
            video_format=intent.video_format,
            voice=intent.voice,
        )
        verdict = self.permissions.guard(task)
        if verdict == "deny":
            reason = ""
            if task.mode == VideoMode.FACECAM.value:
                reason = "素材路径不合法，请把视频放到 影片/桌面/下载/文稿 目录后重试"
            else:
                reason = "该任务命中危险模式黑名单，已拒绝"
            self.log.record(
                {
                    "agent": "video", "task": task.prompt[:200],
                    "mode": task.mode, "source_video": task.source_video,
                    "status": "denied", "detail": reason,
                }
            )
            print(f"[Video] 拒绝: {reason[:80]}")
            return VideoResult(
                status="denied", summary=reason, task_id=task.id
            ).to_dict()
        if verdict == "confirm":
            info = self.tasks.submit(task)
            print(f"[Video] 等待确认({info.get('confirm_id')}): {task.mode}")
            return info
        future = self.tasks.submit(task)
        print(f"[Video] 已入队: {task.mode} project={task.project}")
        return future

    def run_sync(self, text: str, source_video: str = "",
                 timeout: float = 1800.0) -> dict:
        """同步执行（测试/确认后调用）。"""
        intent = intent_parser.parse(text)
        if intent is None:
            return VideoResult(status="failed", summary="无法解析为视频任务").to_dict()
        task = VideoTask(
            mode=intent.mode,
            prompt=intent.prompt,
            source_video=source_video or intent.source_video,
            project=intent.project,
            duration_sec=intent.duration_sec,
            video_format=intent.video_format,
            voice=intent.voice,
        )
        verdict = self.permissions.guard(task)
        if verdict == "deny":
            return VideoResult(status="denied", summary="任务被拒绝", task_id=task.id).to_dict()
        if verdict == "confirm":
            return self.tasks.submit(task)
        future = self.tasks.submit(task)
        if hasattr(future, "result"):
            return future.result(timeout=timeout)
        return future

    # ── 查询 ────────────────────────────────────────────
    def status(self) -> str:
        """当前任务进度（口播文本）。"""
        if not self.client.health():
            return "OpenCut 服务未启动，当前没有视频任务"
        last = self.tasks.last_result()
        if not last:
            return "当前没有进行中的视频任务"
        s = last.get("status", "")
        if s == "success":
            return f"上一个视频任务已完成：{last.get('video_path') or last.get('summary', '')}"
        if s == "failed":
            return f"上一个视频任务失败：{last.get('summary', '')}"
        if s == "waiting":
            return f"视频任务进行中：{last.get('phase', '')}"
        return "当前没有进行中的视频任务"

    def pending_confirmations(self) -> list:
        return self.tasks.pending_confirmations()

    def confirm(self, confirm_id: str, approved: bool):
        """语音确认回调（main.py 用）。"""
        return self.tasks.confirm_result(confirm_id, approved)

    def cancel_current(self) -> bool:
        return self.tasks.cancel_current()

    def available_projects(self) -> list:
        return project_manager.list_projects()


# ── 单例 ────────────────────────────────────────────────
_agent = None
_agent_lock = threading.Lock()


def get_video_agent() -> VideoAgent:
    global _agent
    with _agent_lock:
        if _agent is None:
            _agent = VideoAgent()
        return _agent
