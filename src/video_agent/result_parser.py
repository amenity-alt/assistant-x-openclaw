#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""结果归一化：OpenCut job / 异常 → VideoResult。"""

from .task import VideoResult


def parse_job(job: dict, task_id: str = "", elapsed: float = 0.0) -> VideoResult:
    """把 OpenCut job dict 归一化为 VideoResult。"""
    status = job.get("status", "failed")
    if status == "done":
        r = VideoResult(
            status="success",
            summary="视频渲染完成",
            phase=job.get("phase", "done"),
            job_id=job.get("jobId", ""),
            task_id=task_id,
            elapsed=elapsed,
        )
    elif status == "error":
        r = VideoResult(
            status="failed",
            summary="视频渲染失败",
            error=job.get("error", "")[:300],
            phase=job.get("phase", ""),
            job_id=job.get("jobId", ""),
            task_id=task_id,
            elapsed=elapsed,
        )
    else:
        r = VideoResult(
            status="waiting",
            summary=f"视频任务进行中（{status}）",
            phase=job.get("phase", status),
            job_id=job.get("jobId", ""),
            task_id=task_id,
            elapsed=elapsed,
        )
    return r


def friendly_error(err: Exception) -> str:
    """把异常转成用户可读口播文本。"""
    msg = str(err)
    if "GEMINI_API_KEY" in msg or "DEEPSEEK_API_KEY" in msg or "requireEnv" in msg:
        return "OpenCut 需要配置 AI API key（DeepSeek 或 Gemini）才能进行 AI 生成与转写，请在 OpenCut 的 .env 里配置"
    if "ConnectionError" in msg or "请求失败" in msg or "连接" in msg:
        return "OpenCut 服务未就绪，视频任务无法启动"
    if "Pexels" in msg or "pexels" in msg:
        return "素材库获取失败，请检查 Pexels API key"
    if len(msg) > 160:
        msg = msg[:160] + "..."
    return msg
