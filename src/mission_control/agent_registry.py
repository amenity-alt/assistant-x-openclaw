#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Agent 适配器注册表：把 MissionStep 翻译成各能力模块的调用。

Phase 1：coding / computer / llm 可执行；vision / map 注册占位（Phase 2 完成）。
不修改各 Agent 本体，只做薄封装。
"""

import threading
import time

from .mission import AgentResult


def _ok(status: str = "success", summary: str = "", data: dict = None,
        task_id: str = "", elapsed: float = 0.0) -> AgentResult:
    return AgentResult(
        status=status, summary=summary or "",
        data=data or {}, task_id=task_id, elapsed=elapsed,
    )


class CodingAdapter:
    name = "coding"

    def __init__(self):
        self._agent = None

    def _get(self):
        if self._agent is None:
            from coding_agent import get_coding_agent
            self._agent = get_coding_agent()
        return self._agent

    def execute(self, step, role: str) -> AgentResult:
        t0 = time.time()
        agent = self._get()
        mode = step.action
        params = step.params
        task_text = params.get("task") or params.get("text") or ""
        project = params.get("project") or ""
        if not task_text:
            return _ok("failed", "编码步骤缺少任务描述", elapsed=time.time() - t0)
        # Mission 层已确认/黑名单检查过，直接走 submit_approved 绕过二次 guard
        from coding_agent.task import CodingTask
        task = CodingTask(
            mode=mode,
            task=task_text[:500],
            project=project or agent.current_project or "",
        )
        future = agent.tasks.submit_approved(task)
        try:
            result = future.result(timeout=330.0)
        except Exception as e:
            return _ok("failed", f"编码执行异常: {e}", elapsed=time.time() - t0)
        status = "success" if result.get("status") == "success" else "failed"
        return _ok(
            status, result.get("summary", ""), data=result,
            task_id=task.id, elapsed=time.time() - t0,
        )

    def cancel(self, step) -> bool:
        return False


class ComputerAdapter:
    name = "computer"

    def __init__(self):
        self._executor = None

    def _get(self):
        if self._executor is None:
            from computer.command_executor import CommandExecutor
            self._executor = CommandExecutor()
        return self._executor

    def execute(self, step, role: str) -> AgentResult:
        t0 = time.time()
        text = (step.params.get("text") or "").strip()
        if not text:
            return _ok("failed", "电脑操作步骤缺少指令文本", elapsed=time.time() - t0)
        from computer import intent_parser
        action = intent_parser.parse(text)
        if action is None:
            return _ok("failed", f"无法解析电脑操作: {text}", elapsed=time.time() - t0)
        ex = self._get()
        try:
            result = ex.execute(action)
        except Exception as e:
            return _ok("failed", f"电脑操作异常: {e}", elapsed=time.time() - t0)
        ok = bool(result.get("ok"))
        return _ok(
            "success" if ok else "failed",
            result.get("message", ""),
            data=result, task_id=action.id, elapsed=time.time() - t0,
        )

    def cancel(self, step) -> bool:
        return False


class LLMAdapter:
    name = "llm"

    def execute(self, step, role: str) -> AgentResult:
        t0 = time.time()
        text = (step.params.get("text") or "").strip()
        if not text:
            return _ok("failed", "LLM 步骤缺少指令", elapsed=time.time() - t0)
        try:
            from hermes_bridge import HermesBridge
            bridge = HermesBridge(agent_id=(role or "jarvis").replace("-", "_"))
            if not bridge.gateway_url or not bridge.key:
                return _ok("failed", "Hermes 网关未就绪", elapsed=time.time() - t0)
            reply = bridge.send_and_wait(text[:800])
        except Exception as e:
            return _ok("failed", f"LLM 调用异常: {e}", elapsed=time.time() - t0)
        if not reply:
            return _ok("failed", "LLM 无返回", elapsed=time.time() - t0)
        return _ok("success", reply.strip(), elapsed=time.time() - t0)

    def cancel(self, step) -> bool:
        return False


class VideoAdapter:
    name = "video"

    def __init__(self):
        self._agent = None

    def _get(self):
        if self._agent is None:
            from video_agent import get_video_agent
            self._agent = get_video_agent()
        return self._agent

    def execute(self, step, role: str) -> AgentResult:
        t0 = time.time()
        mode = step.action
        params = step.params
        # Mission 层已确认过，直接走 submit_approved 绕过二次 guard
        from video_agent.task import VideoTask
        if mode in ("status", "cancel"):
            text = params.get("text") or params.get("task") or ""
            try:
                from video_agent import get_video_agent
                agent = get_video_agent()
                if mode == "status":
                    return _ok("success", agent.status(), elapsed=time.time() - t0)
                ok = agent.cancel_current()
                return _ok(
                    "success" if ok else "failed",
                    "已停止视频渲染" if ok else "当前没有可停止的视频任务",
                    elapsed=time.time() - t0,
                )
            except Exception as e:
                return _ok("failed", f"视频操作异常: {e}", elapsed=time.time() - t0)
        task = VideoTask(
            mode=mode,
            prompt=params.get("prompt") or params.get("task") or params.get("text") or "",
            source_video=params.get("source_video") or "",
            project=params.get("project") or "",
            duration_sec=int(params.get("duration_sec") or 0),
            video_format=params.get("video_format") or "horizontal",
            voice=params.get("voice") or "",
        )
        if not task.prompt and mode != "render":
            return _ok("failed", "视频步骤缺少任务描述", elapsed=time.time() - t0)
        agent = self._get()
        try:
            from video_agent.task_manager import TaskManager
            future = agent.tasks.submit_approved(task)
            result = future.result(timeout=3600.0)
        except Exception as e:
            return _ok("failed", f"视频执行异常: {e}", elapsed=time.time() - t0)
        status = "success" if result.get("status") == "success" else "failed"
        return _ok(
            status, result.get("summary", ""), data=result,
            task_id=task.id, elapsed=time.time() - t0,
        )

    def cancel(self, step) -> bool:
        try:
            from video_agent import get_video_agent
            return get_video_agent().cancel_current()
        except Exception:
            return False


class _NotImplementedAdapter:
    """vision / map 占位：Phase 2 接入真实实现。"""

    def __init__(self, name: str):
        self.name = name

    def execute(self, step, role: str) -> AgentResult:
        return _ok("failed", f"{self.name} Agent 将在 Phase 2 接入", task_id=step.id)

    def cancel(self, step) -> bool:
        return False


class AgentRegistry:
    def __init__(self):
        self._adapters = {}
        self._lock = threading.Lock()
        self.register(CodingAdapter())
        self.register(ComputerAdapter())
        self.register(LLMAdapter())
        self.register(VideoAdapter())
        self.register(_NotImplementedAdapter("vision"))
        self.register(_NotImplementedAdapter("map"))

    def register(self, adapter):
        with self._lock:
            self._adapters[adapter.name] = adapter

    def get(self, name: str):
        with self._lock:
            return self._adapters.get(name)

    def available(self) -> list:
        with self._lock:
            return sorted(self._adapters.keys())


_registry = None
_registry_lock = threading.Lock()


def get_agent_registry() -> AgentRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = AgentRegistry()
        return _registry
