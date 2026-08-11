#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""场景/物体详细描述（“详细介绍一下”）。"""


def describe(jpeg: bytes, role: str = "jarvis") -> str | None:
    from .. import get_vision_agent

    return get_vision_agent().describe(jpeg, role)
