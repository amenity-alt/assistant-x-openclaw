#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Codex JSONL 事件流 → 结构化结果。

事件类型（codex exec --json）：
  item.completed
    item.type=agent_message      → 最终文本（summary）
    item.type=file_change        → changes[{path, kind}]（files_changed）
    item.type=command_execution  → {command, exit_code}（commands）
  turn.completed                 → usage{input_tokens, output_tokens, ...}
"""

import json


def parse_events(stdout: str) -> dict:
    """解析 JSONL 事件流，返回
    {summary, files_changed, commands, usage}。"""
    summary = ""
    files_changed = []
    commands = []
    usage = {}
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue  # 过滤插件 WARN 噪音与空行
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        et = ev.get("type")
        if et == "item.completed":
            item = ev.get("item") or {}
            itype = item.get("type")
            if itype == "agent_message" and item.get("text"):
                summary = item["text"]
            elif itype == "file_change":
                for ch in item.get("changes") or []:
                    if isinstance(ch, dict) and ch.get("path"):
                        files_changed.append(
                            {"path": ch["path"], "kind": ch.get("kind", "change")}
                        )
            elif itype == "command_execution":
                commands.append(
                    {
                        "command": item.get("command", ""),
                        "exit_code": item.get("exit_code"),
                    }
                )
        elif et == "turn.completed":
            usage = ev.get("usage") or {}
    return {
        "summary": summary.strip(),
        "files_changed": files_changed,
        "commands": commands,
        "usage": usage,
    }
