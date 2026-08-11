#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""物体识别（分层后端，软失败）。"""


def recognize(jpeg: bytes, role: str = "jarvis") -> dict | None:
    from .. import get_vision_agent

    return get_vision_agent().scan(jpeg, role)
