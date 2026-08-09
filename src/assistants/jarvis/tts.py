#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Jarvis TTS — 英文走 Piper 英音，中文走 MeloTTS 女声

引擎: Piper (VITS) / MeloTTS (VITS, zh_en 女声)
模型: jgkawell/jarvis (en-GB-x-rp, 22050Hz) / vits-melo-tts-zh_en (44100Hz)
"""

import re
import threading
from threading import Event

import numpy as np

from assistants.tts import AssistantTTS

# 中日韩统一表意文字等：命中即视为需要中文语音
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


# 中文女声默认配置（MeloTTS zh_en 单女声，中英双语）
_ZH_TTS_DEFAULT_CONFIG = {
    "engine": "vits",
    "model_dir": "models/vits-melo-tts-zh_en",
    "speed": 1.0,
}


class JarvisTTS(AssistantTTS):

    def __init__(self, config: dict = None):
        # 注入 assistants.json 的 tts_config（金属感后处理等）到引擎模块
        from assistants.jarvis import tts_piper
        tts_piper.configure(config or {})
        # 允许在 tts_config.zh_tts 里覆盖中文女声配置（engine/model_dir/speed）
        self._zh_config = (config or {}).get("zh_tts") or _ZH_TTS_DEFAULT_CONFIG
        self._zh_tts = None
        self._zh_tts_lock = threading.Lock()
        # 后台预热中文女声，首次中文播报无需等待模型加载
        threading.Thread(target=self._warm_zh_tts, daemon=True).start()

    def _get_zh_tts(self):
        if self._zh_tts is not None:
            return self._zh_tts
        with self._zh_tts_lock:
            if self._zh_tts is not None:
                return self._zh_tts
            from assistants.custom_tts import CustomTTS
            self._zh_tts = CustomTTS(self._zh_config)
            return self._zh_tts

    def _warm_zh_tts(self):
        try:
            tts = self._get_zh_tts()
            if tts.is_available():
                tts._get_tts()
                print("[TTS] 中文女声（MeloTTS）已预热")
        except Exception as e:
            print(f"[TTS] 中文女声预热失败: {e}")

    def _pick(self, text: str):
        if _contains_cjk(text):
            zh = self._get_zh_tts()
            if zh.is_available():
                return zh
        from assistants.jarvis import tts_piper
        return tts_piper

    def is_available(self) -> bool:
        return self._get_zh_tts().is_available() or self._zh_piper_available()

    @staticmethod
    def _zh_piper_available() -> bool:
        from assistants.jarvis import tts_piper
        return tts_piper.is_available()

    def synthesize(self, text: str, output_path: str = None, **kwargs) -> str | None:
        return self._pick(text).synthesize(text, output_path=output_path, **kwargs)

    def synthesize_to_array(self, text: str, **kwargs) -> tuple[np.ndarray, int] | None:
        return self._pick(text).synthesize_to_array(text, **kwargs)

    def synthesize_streaming(self, text: str, stop_event: Event = None,
                             volume: float = 1.5) -> bool:
        return self._pick(text).synthesize_streaming(
            text, stop_event=stop_event, volume=volume,
        )
