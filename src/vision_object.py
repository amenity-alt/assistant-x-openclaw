#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Jarvis Spatial Vision — 手持物体视觉识别（Capability 模块）。

分层后端（软失败，逐级回退）：
  A. Hermes 视觉 LLM（默认）：复用现有 Hermes 网关（OpenAI 兼容
     /v1/chat/completions + image_url base64）——零新依赖，支持自由描述；
  B. MediaPipe ImageClassifier（离线兜底）：EfficientNet-Lite0 粗分类
     （ImageNet 1000 类，模型 ~7MB 首次自动下载）；
  C. YOLO/MobileSAM（预留接口）：torch 环境启用时实现。

统一识别结果：
    {"label": "MacBook Pro", "category": "Laptop", "confidence": 0.95,
     "info": "…型号/用途/特点…", "bbox": null | [x, y, w, h]}

设计原则（与 vision.py 一致）：软失败。任何后端不可用/网关不支持图像输入
都回退下一层；全部失败返回 None，由调用方提示，绝不崩、不阻塞语音主流程。
"""

import base64
import json
import os
import re
import socket
import threading
import urllib.request

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 提示词（角色语言由 main.py 口播层决定，识别本身固定英文 JSON）─────────
RECOGNITION_PROMPT = (
    "You are JARVIS spatial vision. Analyze the object(s) the user is holding "
    "in this camera image. Reply with ONLY a JSON object, no other text, no "
    "code fences:\n"
    '{"label": "short object name in English", '
    '"category": "one of Laptop/Phone/Keyboard/Mouse/Book/Cup/Bottle/Earbuds/'
    'Wearable/Remote/Hand/Paper/Unknown", '
    '"confidence": 0.0-1.0, '
    '"info": "one concise sentence with model/use/features if identifiable"}\n'
    'If nothing is identifiable, reply {"label": "Unknown", "category": "Unknown", '
    '"confidence": 0.0, "info": ""}'
)

DESCRIBE_PROMPT = (
    "Describe in detail what the user is holding in this image: object name, "
    "category, model hints, typical use, and notable features. Keep it concise, "
    "2-4 sentences, plain text only."
)


class _quiet_fd2:
    """临时把 stderr(fd 2) 指向 /dev/null：吞掉 MediaPipe C++ 一次性日志。"""

    def __enter__(self):
        self._saved = os.dup(2)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        os.close(devnull)
        return self

    def __exit__(self, *exc):
        os.dup2(self._saved, 2)
        os.close(self._saved)
        return False


def _extract_json(text: str):
    """从模型回复中提取 JSON 对象（容忍代码块/前后缀）。失败返回 None。"""
    if not text:
        return None
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except Exception:
        pass
    start, end = s.find("{"), s.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(s[start:end + 1])
        except Exception:
            return None
    return None


_VISION_UNAVAILABLE_RE = re.compile(
    r"isn't configured for vision|image didn't reach|does not support image|"
    r"not configured for vision|no vision support|vision tasks",
    re.I,
)


class HermesVisionBackend:
    """后端 A：Hermes 网关图像理解（OpenAI 兼容 image_url）。"""

    def __init__(self):
        self._lock = threading.Lock()

    def _bridge(self, role: str):
        from hermes_bridge import HermesBridge

        return HermesBridge(agent_id=(role or "jarvis").replace("-", "_"))

    def recognize(self, jpeg: bytes, role: str = "jarvis") -> dict | None:
        reply = self._ask(jpeg, role, RECOGNITION_PROMPT)
        if not reply:
            return None
        data = _extract_json(reply)
        if not isinstance(data, dict):
            return None
        return {
            "label": str(data.get("label") or "Unknown")[:80],
            "category": str(data.get("category") or "Unknown")[:40],
            "confidence": round(float(data.get("confidence") or 0.0), 2),
            "info": str(data.get("info") or "")[:300],
            "bbox": data.get("bbox"),
            "backend": "hermes",
        }

    def describe(self, jpeg: bytes, role: str = "jarvis") -> str | None:
        return self._ask(jpeg, role, DESCRIBE_PROMPT)

    def _ask(self, jpeg: bytes, role: str, prompt: str) -> str | None:
        if not jpeg:
            return None
        try:
            bridge = self._bridge(role)
            if not bridge.gateway_url or not bridge.key:
                print("[VisionObject] Hermes 端点未就绪，回退本地识别")
                return None
            b64 = base64.b64encode(jpeg).decode("ascii")
            with self._lock:
                reply = bridge.send_image_and_wait(b64, prompt, timeout=25.0)
            if reply and _VISION_UNAVAILABLE_RE.search(reply):
                print("[VisionObject] Hermes 网关未配置视觉能力，跳过")
                return None
            return reply
        except Exception as e:
            print(f"[VisionObject] Hermes 图像理解异常: {e}")
            return None


class MediaPipeClassifier:
    """后端 B：MediaPipe ImageClassifier（离线粗分类，软失败）。"""

    _MODEL_URL = "https://storage.googleapis.com/mediapipe-tasks/image_classifier/efficientnet_lite0_fp32.tflite"
    _MODEL_PATH = os.path.join(_PROJECT_DIR, "models", "efficientnet_lite0.tflite")

    def __init__(self):
        self._lock = threading.Lock()
        self._classifier = None
        self._fail = False

    def _ensure_model(self) -> str | None:
        if os.path.exists(self._MODEL_PATH) and os.path.getsize(self._MODEL_PATH) > 0:
            return self._MODEL_PATH
        try:
            print(f"[VisionObject] 下载 ImageClassifier 模型: {self._MODEL_URL}")
            os.makedirs(os.path.dirname(self._MODEL_PATH), exist_ok=True)
            with socket.create_connection(("storage.googleapis.com", 443), timeout=15):
                pass
            tmp = self._MODEL_PATH + ".download"
            socket.setdefaulttimeout(30)
            try:
                urllib.request.urlretrieve(self._MODEL_URL, tmp)
            finally:
                socket.setdefaulttimeout(None)
            if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                os.replace(tmp, self._MODEL_PATH)
                print(f"[VisionObject] ImageClassifier 模型已下载: {self._MODEL_PATH}")
                return self._MODEL_PATH
        except Exception as e:
            print(f"[VisionObject] ImageClassifier 模型下载失败: {e}")
        return None

    def _ensure_classifier(self):
        if self._classifier is not None or self._fail:
            return
        try:
            model = self._ensure_model()
            if not model:
                self._fail = True
                return
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision as mp_vision

            base = mp_python.BaseOptions(model_asset_path=model)
            options = mp_vision.ImageClassifierOptions(
                base_options=base,
                max_results=1,
                score_threshold=0.25,
            )
            with _quiet_fd2():
                self._classifier = mp_vision.ImageClassifier.create_from_options(options)
            print("[VisionObject] MediaPipe ImageClassifier 就绪")
        except Exception as e:
            self._fail = True
            print(f"[VisionObject] ImageClassifier 加载失败: {e}")

    def recognize(self, jpeg: bytes, role: str = "jarvis") -> dict | None:
        if not jpeg:
            return None
        try:
            self._ensure_classifier()
            if self._classifier is None:
                return None
            rgb = self._decode_rgb(jpeg)
            if rgb is None:
                return None
            import mediapipe as mp

            img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            with self._lock:
                res = self._classifier.classify(img)
            cats = res.classifications[0].categories if res.classifications else []
            if not cats:
                return None
            top = cats[0]
            name = (top.category_name or f"class_{top.index}").strip()
            if not name or name.lower().startswith("class_"):
                return None
            return {
                "label": name[:80],
                "category": name[:40],
                "confidence": round(float(top.score or 0.0), 2),
                "info": "",
                "bbox": None,
                "backend": "mediapipe",
            }
        except Exception as e:
            print(f"[VisionObject] 本地分类异常: {e}")
            return None

    def _decode_rgb(self, jpeg: bytes):
        try:
            import cv2
            import numpy as np

            arr = np.frombuffer(jpeg, dtype=np.uint8)
            bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if bgr is not None:
                return np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        except Exception:
            pass
        try:
            from PIL import Image
            import io

            im = Image.open(io.BytesIO(jpeg)).convert("RGB")
            import numpy as np

            return np.ascontiguousarray(np.asarray(im))
        except Exception:
            return None

    def stop(self):
        c = self._classifier
        self._classifier = None
        if c is not None:
            try:
                c.close()
            except Exception:
                pass


class YoloBackend:
    """后端 C（预留）：torch/ultralytics 环境启用时实现检测框。"""

    def recognize(self, jpeg: bytes, role: str = "jarvis") -> dict | None:
        return None


class VisionObjectRecognizer:
    """统一入口：A 优先 → B 兜底 → C 预留；describe 走 A。"""

    def __init__(self, prefer: str = "local"):
        # 当前部署（DeepSeek）无视觉能力：默认本地 MediaPipe 优先，秒回；
        # 配置了支持图像的网关后可改 "hermes" 优先。
        self._prefer = prefer if prefer in ("hermes", "local") else "local"
        self._hermes = HermesVisionBackend()
        self._local = MediaPipeClassifier()
        self._yolo = YoloBackend()

    def recognize(self, jpeg: bytes, role: str = "jarvis") -> dict | None:
        if self._prefer != "local":
            r = self._hermes.recognize(jpeg, role)
            if r:
                return r
            r = self._local.recognize(jpeg, role)
            if r:
                return r
            return self._yolo.recognize(jpeg, role)
        r = self._local.recognize(jpeg, role)
        if r:
            return r
        return self._hermes.recognize(jpeg, role)

    def describe(self, jpeg: bytes, role: str = "jarvis") -> str | None:
        text = self._hermes.describe(jpeg, role)
        if text:
            return text
        r = self._local.recognize(jpeg, role)
        if r and r.get("label"):
            return f"This appears to be a {r['label']}."

    def stop(self):
        try:
            self._local.stop()
        except Exception:
            pass


# ── 单例 ────────────────────────────────────────────────
_recognizer = None
_recognizer_lock = threading.Lock()


def get_object_recognizer() -> VisionObjectRecognizer:
    global _recognizer
    with _recognizer_lock:
        if _recognizer is None:
            _recognizer = VisionObjectRecognizer()
        return _recognizer
