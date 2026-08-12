#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""任务轮询器：OpenCut job 状态轮询 + 阶段回调 + 超时 + 可取消。

回调约定（供 TaskManager / main.py 使用）：
  on_phase(job_id, phase)   — 阶段变化（planning/tts/footage/rendering/...）
  on_done(job_id, job)      — status == done
  on_error(job_id, message) — status == error / 超时
"""

import threading
import time

from .opencut_client import OpenCutClient, OpenCutError

_JOB_MAX_WAIT_SEC = 3600.0    # 单个任务最长等待（1 小时）
_JOB_POLL_INTERVAL = 4.0


class JobPoller:
    def __init__(self, client: OpenCutClient,
                 on_phase=None, on_done=None, on_error=None,
                 max_wait: float = _JOB_MAX_WAIT_SEC,
                 poll_interval: float = _JOB_POLL_INTERVAL):
        self.client = client
        self.on_phase = on_phase
        self.on_done = on_done
        self.on_error = on_error
        self.max_wait = max_wait
        self.poll_interval = poll_interval
        self._stop = threading.Event()
        self._last_phase = ""
        self._thread = None

    def wait(self, job_id: str) -> dict:
        """阻塞轮询直到 done/error/超时/取消。返回最终 job dict。"""
        self._stop.clear()
        self._last_phase = ""
        deadline = time.time() + self.max_wait
        last_status = ""
        while not self._stop.is_set():
            if time.time() > deadline:
                err = "渲染超时，任务已中止"
                self._fire_error(job_id, err)
                return {"jobId": job_id, "status": "error", "error": err}
            try:
                job = self.client.job_status(job_id)
            except OpenCutError as e:
                time.sleep(self.poll_interval)
                continue
            status = job.get("status", "")
            phase = job.get("phase", "")
            if phase and phase != self._last_phase:
                self._last_phase = phase
                if self.on_phase:
                    try:
                        self.on_phase(job_id, phase)
                    except Exception as e:
                        print(f"[Video] on_phase 回调异常: {e}")
            if status == "done":
                if self.on_done:
                    try:
                        self.on_done(job_id, job)
                    except Exception as e:
                        print(f"[Video] on_done 回调异常: {e}")
                return job
            if status == "error":
                msg = job.get("error") or "渲染失败"
                self._fire_error(job_id, msg)
                return job
            if status and status != last_status:
                last_status = status
            time.sleep(self.poll_interval)
        err = "任务已取消"
        self._fire_error(job_id, err)
        return {"jobId": job_id, "status": "error", "error": err}

    def cancel(self):
        self._stop.set()

    def _fire_error(self, job_id: str, msg: str):
        if self.on_error:
            try:
                self.on_error(job_id, msg)
            except Exception as e:
                print(f"[Video] on_error 回调异常: {e}")
