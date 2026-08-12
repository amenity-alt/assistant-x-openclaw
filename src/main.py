#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
语音助手程序 - 基于 sherpa-onnx
语音唤醒 + 流式语音识别
为 OpenClaw 联动预留接口
"""

import argparse
import json
import os
import platform
import random
import re
import signal
import sys
import time
import threading
import queue
import tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path


def _detect_best_provider() -> str:
    """根据硬件平台自动选择最优 provider"""
    if platform.system() != "Darwin":
        return "cpu"
    if platform.machine() == "arm64":
        return "coreml"
    return "mps"

_assistant_instance = None
PID_FILE = os.path.join(tempfile.gettempdir(), "voice_assistant.pid")
API_PORT = 18790

# 天地图（Tianditu）地理编码：任意地点名 → 经纬度，实现"具体地点定位"
TIANDITU_KEY = "f6eff7213d1409c324f32588057ff535"
_TDT_GEO_URL = "https://api.tianditu.gov.cn/geocoder"


def _geocode_city(name: str):
    """天地图地理编码：地点名 → (lat, lon)；失败返回 None。"""
    try:
        import urllib.parse
        import urllib.request

        ds = urllib.parse.quote(json.dumps({"keyWord": name}, ensure_ascii=False))
        url = f"{_TDT_GEO_URL}?ds={ds}&tk={TIANDITU_KEY}"
        with urllib.request.urlopen(url, timeout=6) as r:
            data = json.loads(r.read().decode("utf-8"))
        loc = data.get("location") or {}
        lon, lat = loc.get("lon"), loc.get("lat")
        if lon is not None and lat is not None:
            lat, lon = float(lat), float(lon)
            # 中国大陆范围防御（73~135E, 18~54N），过滤模糊匹配的境外/异常结果
            if 18.0 <= lat <= 54.0 and 73.0 <= lon <= 135.0:
                return lat, lon
            print(f"[Map] geocode 结果超出大陆范围，忽略: {name} ({lat},{lon})")
    except Exception as e:
        print(f"[Map] geocode 失败({name}): {e}")
    return None


class _ExitAPIHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        global _dnd_mode
        if self.path == "/exit":
            if _assistant_instance is not None:
                threading.Thread(
                    target=_assistant_instance.exit_standby, daemon=True
                ).start()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode())
            else:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "assistant not ready"}).encode())
        elif self.path == "/dnd":
            _dnd_mode = True
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "dnd": True}).encode())
        elif self.path == "/dnd/disable":
            _dnd_mode = False
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "dnd": False}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        # 摄像头抓帧：抓一帧 JPEG 直接回给调用方（Hermes 用 curl -o 落地后交 vision_analyze）
        if self.path.startswith("/camera/snapshot"):
            import tempfile
            from camera import get_camera_controller

            cam = get_camera_controller()
            if not cam.is_available():
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "camera unavailable"}).encode())
                return
            out = os.path.join(tempfile.gettempdir(), "jarvis_cam_snapshot.jpg")
            path = cam.capture(out)
            if path and os.path.exists(path) and os.path.getsize(path) > 0:
                data = open(path, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(
                    {"error": "capture failed (摄像头未授权？首次需在控制中心授权)"}
                ).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def _start_api_server():
    # start.sh 清理端口与本进程绑定之间存在竞争窗口（僵尸进程刚退出、TIME_WAIT
    # 未释放等），单次绑定失败不代表端口长期不可用，重试几次再放弃。
    server = None
    last_err = None
    for attempt in range(5):
        try:
            server = HTTPServer(("127.0.0.1", API_PORT), _ExitAPIHandler)
            break
        except OSError as e:
            last_err = e
            time.sleep(0.5)
    if server is None:
        print(f"[API] 退出/勿扰接口启动失败：端口 {API_PORT} 持续被占用 ({last_err})。"
              f"/exit 与声纹录入的勿扰联动将不可用，可 lsof -ti:{API_PORT} | xargs kill 后重启。")
        return
    server.serve_forever()


try:
    import sounddevice as sd
except ImportError:
    print("请先安装 sounddevice：pip install sounddevice")
    sys.exit(1)

try:
    import numpy as np
except ImportError:
    print("请先安装 numpy：pip install numpy")
    sys.exit(1)

try:
    import sherpa_onnx
except ImportError:
    print("请先安装 sherpa-onnx：pip install sherpa-onnx")
    sys.exit(1)

try:
    import soxr as _soxr
except ImportError:
    _soxr = None  # 无 soxr 时退回原始采样率，ASR 精度会下降

from tts import (
    text_to_speech_play,
    is_tts_playing,
    play_prebuilt_voice,
    stop_tts,
    set_tts,
)
from log_setup import setup_logging, get_diag_logger
from lifecycle import get_lifecycle_manager
from media_pause import MediaPauseHook
from dock_control import DockAutohideHook
from map_dashboard import MapDashboardHook

# 文件级诊断/错误日志（只落盘，不进控制中心）
_diag = get_diag_logger()
from assistants import (
    AssistantManager,
    AssistantInstance,
    get_manager,
)

# ── assistants.json 配置加载 ─────────────────────────────────
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ASSISTANTS_CFG_PATH = os.path.join(_PROJECT_DIR, "assistants.json")

# assistants.json 按 (mtime, size) 缓存：启动时四个 _load_* 不再各读一遍文件，
# 文件被外部修改时仍会自动重读（保留热重载语义）。
_assistants_json_cache = {"key": None, "data": {}}


def _load_assistants_json() -> dict:
    """读取 assistants.json 顶层配置；失败返回空 dict（调用方各自回退默认值）。"""
    try:
        st = os.stat(_ASSISTANTS_CFG_PATH)
        key = (st.st_mtime, st.st_size)
    except OSError:
        key = None
    if key is not None and _assistants_json_cache["key"] == key:
        return _assistants_json_cache["data"]
    try:
        with open(_ASSISTANTS_CFG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    _assistants_json_cache["key"] = key
    _assistants_json_cache["data"] = data
    return data


# ── 主脑引擎选择（assistants.json 顶层 engine 字段，默认 openclaw）──────────
def _load_engine() -> str:
    """读取 assistants.json 顶层 engine：openclaw（默认）| hermes。"""
    return (_load_assistants_json().get("engine") or "openclaw").strip().lower()


def _load_overlay_debug() -> bool:
    """读取 assistants.json 顶层 overlay_debug_mode：true 时特效召唤后不隐藏。"""
    return bool(_load_assistants_json().get("overlay_debug_mode", False))


def _load_dock_autohide() -> bool:
    """读取 assistants.json 顶层 dock_autohide_on_wake：true 时激活期自动隐藏 Dock。"""
    return bool(_load_assistants_json().get("dock_autohide_on_wake", False))


def _load_map_dashboard() -> bool:
    """读取 assistants.json 顶层 map_dashboard_on_wake：true 时唤醒确保地图服务在线（overlay 卡片）。"""
    return bool(_load_assistants_json().get("map_dashboard_on_wake", True))


_ENGINE = _load_engine()
if _ENGINE == "hermes":
    from hermes_bridge import get_bridge  # noqa: E402

    print("[引擎] 主脑：Hermes（一角色一 profile 一网关）")
else:
    from openclaw_bridge_websocket import get_bridge  # noqa: E402

    if _ENGINE != "openclaw":
        print(f"[引擎] 未知 engine='{_ENGINE}'，回退 OpenClaw")
    else:
        print("[引擎] 主脑：OpenClaw")

# ── 声纹验证配置 ────────────────────────────────────────────
_SPEAKER_MODEL_PATH = os.path.join(_PROJECT_DIR, "models", "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx")
_SPEAKER_DIR = os.path.join(_PROJECT_DIR, "data", "enrollment")
_SPEAKER_FILE = os.path.join(_SPEAKER_DIR, "speakers.json")
_SPEAKER_THRESHOLD = 0.55  # 声纹相似度阈值
_SPEAKER_NOTIFY_PORT = 18792  # control_center TCP 通知端口

# 音频流假死看门狗：macOS CoreAudio 在反复关停/重开 InputStream 后偶发
# "start 成功但回调不再送帧"。健康时即使无人说话也会持续产生静音帧，
# 因此"持续 N 秒拿不到任何帧"是死流的可靠信号，不会被正常静默误触发。
_AUDIO_STALL_TIMEOUT = 15  # 秒

_dnd_mode = False  # Do Not Disturb 模式，注册时不响应唤醒词


# ── 文本纠错表（兜底修复 sherpa-onnx ASR 误识别人名/术语）──────────────────
# 加载逻辑：读取 text_corrections.txt，每行格式 `<错误> : <正确>`，
# 在 ASR 最终结果（_process_recognition_result）送视觉/送 LLM 之前整词大小写
# 不敏感替换。sherpa hotwords 对 cjkchar+bpe 模型下 OOV 英文整词的偏置几乎
# 无效（整词 token 找不到就静默跳过），所以这条兜底是真正的可靠修复路径。
# 文件与 hotwords.txt 同级，main 启动时一次性加载，运行期可热重载（按需）。
import re as _re_corrections

_TEXT_CORRECTIONS_PATH = os.path.join(_PROJECT_DIR, "text_corrections.txt")
_TEXT_CORRECTIONS = []  # list[(compiled_pattern, replacement)]


def _load_text_corrections(path=None):
    """加载 text_corrections.txt 到 _TEXT_CORRECTIONS，返回加载条数。

    文件不存在时静默返回 0（纠错是可选功能）。运行期可重复调用做热重载。
    """
    global _TEXT_CORRECTIONS
    p = path or _TEXT_CORRECTIONS_PATH
    rules = []
    if not os.path.exists(p):
        _TEXT_CORRECTIONS = []
        return 0
    try:
        with open(p, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" not in line:
                    continue
                bad, good = line.split(":", 1)
                bad = bad.strip()
                good = good.strip()
                if not bad:
                    continue
                # 整词大小写不敏感：re.escape 后用 \b...\b 包裹
                # flags 设为 re.IGNORECASE，匹配时保形替换为 good（good 自带期望大小写）
                pat = _re_corrections.compile(
                    r"(?<![A-Za-z0-9_])" + _re_corrections.escape(bad) + r"(?![A-Za-z0-9_])",
                    _re_corrections.IGNORECASE,
                )
                rules.append((pat, good))
    except Exception as e:
        print(f"[文本纠错] 加载失败: {e}")
        _TEXT_CORRECTIONS = []
        return 0
    _TEXT_CORRECTIONS = rules
    return len(rules)


def _apply_text_corrections(text):
    """应用所有纠错规则到 text，返回修正后字符串。无规则时返回原串。"""
    if not _TEXT_CORRECTIONS or not text:
        return text
    out = text
    for pat, repl in _TEXT_CORRECTIONS:
        out = pat.sub(repl, out)
    return out


_load_text_corrections()


def _notify_speaker_rejected():
    """通知 control_center 声纹验证被拒绝"""
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(("127.0.0.1", _SPEAKER_NOTIFY_PORT))
        sock.sendall(b"speaker_rejected\n")
        sock.close()
    except Exception:
        pass


def _set_dnd_mode(enabled: bool):
    """设置勿扰模式"""
    global _dnd_mode
    _dnd_mode = enabled
    print(f"[勿扰] 唤醒词监听{'已暂停' if _dnd_mode else '已恢复'}")


def _check_speaker_model():
    """检查声纹模型是否存在"""
    return os.path.exists(_SPEAKER_MODEL_PATH)


def _load_speakers():
    """加载已注册的声纹列表；文件不存在/损坏时返回空列表，不让启动崩溃。"""
    try:
        with open(_SPEAKER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_speakers(speakers):
    """原子保存声纹列表：先写同目录临时文件再 rename，避免写入中断损坏数据。"""
    os.makedirs(_SPEAKER_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=_SPEAKER_DIR, prefix="speakers.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(speakers, f, indent=2, ensure_ascii=False)
        os.replace(tmp, _SPEAKER_FILE)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _create_speaker_extractor():
    """创建声纹提取器"""
    if not _check_speaker_model():
        return None
    try:
        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=_SPEAKER_MODEL_PATH, num_threads=2
        )
        return sherpa_onnx.SpeakerEmbeddingExtractor(config)
    except Exception as e:
        print(f"[声纹] 初始化提取器失败: {e}")
        return None


def _create_speaker_manager(dim):
    """创建声纹管理器"""
    return sherpa_onnx.SpeakerEmbeddingManager(dim)


def _extract_embedding(extractor, samples, sample_rate=16000):
    """从音频样本中提取声纹嵌入"""
    try:
        # 检查样本是否有效
        if not samples or len(samples) == 0:
            print("[声纹] 提取嵌入失败: 样本为空")
            return None
        
        # 确保样本是列表类型
        if hasattr(samples, 'tolist'):
            samples = samples.tolist()
        elif not isinstance(samples, list):
            samples = list(samples)
        
        stream = extractor.create_stream()
        stream.accept_waveform(sample_rate=sample_rate, waveform=samples)
        stream.input_finished()
        
        # 检查是否就绪
        if not extractor.is_ready(stream):
            print(f"[声纹调试] 提取嵌入失败: 流未就绪 (样本过短)，samples={len(samples)}")
            return None

        embedding = extractor.compute(stream)
        embedding = np.array(embedding)
        print(f"[声纹调试] 嵌入提取成功，shape: {embedding.shape}, 前5值: {embedding[:5].tolist()}")
        return embedding
    except Exception as e:
        print(f"[声纹] 提取嵌入失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def _verify_speaker(extractor, manager, samples, sample_rate=16000, threshold=None):
    """验证说话人身份
    
    Returns:
        (is_verified, speaker_name, score)
    """
    if extractor is None or manager is None:
        return False, None, 0.0
    
    embedding = _extract_embedding(extractor, samples, sample_rate)
    if embedding is None:
        return False, None, 0.0
    
    # 搜索最匹配的声纹
    try:
        emb_list = embedding.tolist()
        print(f"[声纹调试] 嵌入向量前5值: {emb_list[:5]}")
        print(f"[声纹调试] 已注册声纹: {manager.all_speakers}")
        thr = _SPEAKER_THRESHOLD if threshold is None else threshold
        result = manager.search(emb_list, thr)
        print(f"[声纹调试] search result: '{result}', threshold: {thr}")
        if result:
            # 计算相似度分数
            score = manager.score(result, emb_list)
            print(f"[声纹调试] score for '{result}': {score}")
            return True, result, score
    except Exception as e:
        print(f"[声纹] 验证失败: {e}")
    
    return False, None, 0.0


def _load_all_assistant_configs() -> tuple[dict, list]:
    """加载所有启用的 assistant 配置

    Returns:
        (default_config, list_of_all_enabled_configs)
    """
    with open(_ASSISTANTS_CFG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    default_id = cfg.get("default")
    all_assistants = cfg.get("assistants", [])

    # 过滤启用的 assistant
    enabled_assistants = [a for a in all_assistants if a.get("enabled", True)]

    if not enabled_assistants:
        raise ValueError("assistants.json 中没有启用的 assistant")

    # 找到默认配置
    default_config = None
    for a in enabled_assistants:
        if a["id"] == default_id:
            default_config = a
            break

    # 如果默认不在启用列表中，使用第一个启用的
    if default_config is None:
        default_config = enabled_assistants[0]

    return default_config, enabled_assistants


def _load_assistant_config(assistant_id: str = None) -> dict:
    """从 assistants.json 加载指定 assistant 的配置，返回 dict（兼容旧代码）"""
    with open(_ASSISTANTS_CFG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    target_id = assistant_id or cfg.get("default")
    for a in cfg.get("assistants", []):
        if a["id"] == target_id:
            return a
    raise ValueError(f"assistants.json 中未找到 assistant: {target_id}")


# _merge_keywords_files 函数已废弃
# 唤醒词合并逻辑已移至 start.sh 脚本中
# 程序直接使用 global.txt 文件


# ── 运行时变量（由 _apply_assistant_config 填充） ────────────
EXIT_KEYWORDS: set = set()
INSTANT_EXIT_KEYWORDS: set = set()
INSTANT_EXIT_FUZZY: tuple = ()
RESTART_KEYWORDS: set = set()
WAKE_LINES: list = []
EXIT_LINES: list = []


def _apply_assistant_config(cfg: dict):
    """将 assistant 配置写入模块级变量"""
    global EXIT_KEYWORDS, INSTANT_EXIT_KEYWORDS, INSTANT_EXIT_FUZZY
    global RESTART_KEYWORDS
    global WAKE_LINES, EXIT_LINES

    EXIT_KEYWORDS = set(cfg.get("exit_keywords", []))
    EXIT_KEYWORDS.update({"QUIT", "quit", "EXIT", "exit"})
    INSTANT_EXIT_KEYWORDS = set(cfg.get("instant_exit_keywords", []))
    INSTANT_EXIT_FUZZY = tuple(cfg.get("instant_exit_fuzzy", []))
    RESTART_KEYWORDS = set(cfg.get("restart_keywords", []))
    WAKE_LINES = list(cfg.get("wake_lines", []))
    EXIT_LINES = list(cfg.get("exit_lines", []))


def _is_instant_exit(text: str) -> bool:
    return text in INSTANT_EXIT_KEYWORDS or text in INSTANT_EXIT_FUZZY


# ── 唤醒 / 退出随机话术 ──────────────────────────────────────


def _random_wake_line() -> str:
    return random.choice(WAKE_LINES)


def _random_exit_line() -> str:
    return random.choice(EXIT_LINES)


# 预编译：_clean_for_tts 每段 TTS 文本都会调用，避免反复 re.sub 内联编译
_TTS_MARKDOWN_RE = re.compile(r"[*`#>\-]+")
_TTS_EMOJI_RE = re.compile(r"[\U0001f300-\U0001f9ff\u2600-\u26ff\u2700-\u27bf]")
_TTS_WHITESPACE_RE = re.compile(r"\s+")


def _clean_for_tts(text: str) -> str:
    """清理文本，适合 TTS 朗读"""
    # 去掉 markdown 符号
    text = _TTS_MARKDOWN_RE.sub("", text)
    # 去掉 emoji
    text = _TTS_EMOJI_RE.sub("", text)
    # 合并多余空白和换行
    text = _TTS_WHITESPACE_RE.sub(" ", text).strip()
    # 截断过长文本（取前500字符，尽量在句号处截断）
    if len(text) > 500:
        cut = text[:500]
        last_period = max(
            cut.rfind("。"), cut.rfind("！"), cut.rfind("？"), cut.rfind(".")
        )
        if last_period > 100:
            text = cut[: last_period + 1]
        else:
            text = cut + "。"
    return text


def _batch_sentences(text: str, sent_end: str, max_sentences: int = 4):
    """把一段文本按句末标点切分，每 max_sentences 句合成一批。

    长句/长段落不再一次性整段合成，而是每 4 句切一刀，逐批送去合成播放，
    降低首句延迟并避免长文合成阻塞。返回若干文本片段（保留原标点）。
    """
    batches = []
    cur = []
    count = 0
    for ch in text:
        cur.append(ch)
        if ch in sent_end:
            count += 1
            if count >= max_sentences:
                batches.append("".join(cur))
                cur = []
                count = 0
    tail = "".join(cur)
    if tail.strip():
        batches.append(tail)
    return batches


class VoiceAssistant:
    def __init__(
        self, args, default_cfg: dict, all_assistants: list, keyword_mapping: dict
    ):
        self.args = args
        self.default_cfg = default_cfg
        self.all_assistants = {a["id"]: a for a in all_assistants}
        self.keyword_mapping = keyword_mapping  # keyword_text -> assistant_id

        # 初始化 assistant manager
        self.assistant_manager = get_manager()

        # 注册所有启用的 assistant
        for cfg in all_assistants:
            assistant_id = cfg["id"]
            self.assistant_manager.register(
                assistant_id,
                cfg,
                sound_enabled=True,
                hud_enabled=True,
                notification_enabled=True,
            )

        # 切换到默认 assistant
        self.current_cfg = default_cfg
        self._switch_assistant(default_cfg["id"])

        self.sample_rate = 48000
        # sherpa-onnx 模型训练采样率为 16kHz，accept_waveform 必须喂 16kHz 数据；
        # 输入流保持 48kHz 兼容其他应用，在处理循环里用 soxr 重采样到 16kHz 再喂模型。
        self._asr_rate = 16000
        # 激活生命周期联动：is_awake 是 property（见下），在 False↔True
        # 边沿自动派发钩子。先建注册表并接入已有联动（暂停媒体），
        # 再触发首次赋值——此时 manager 已就绪。
        self._is_awake = False
        self._lifecycle = get_lifecycle_manager()
        self._lifecycle.register(MediaPauseHook())
        if _load_dock_autohide():
            self._lifecycle.register(DockAutohideHook())
            print("[Dock] 激活期自动隐藏 Dock：已启用（dock_autohide_on_wake）")
        if _load_map_dashboard():
            self._lifecycle.register(MapDashboardHook())
            print("[Map] 唤醒时确保地图服务在线（overlay 左上角卡片）：已启用（map_dashboard_on_wake）")
        self.is_awake = False
        self.continuous_mode = False
        self.audio_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.last_voice_time = time.time()
        self.idle_timeout = 30
        self.last_activity_time = time.time()
        self._wake_audio_buffer = []  # 用于声纹验证的音频缓冲区
        self._wake_buffer_max_samples = int(self._asr_rate * 3)  # 最多存3秒（16kHz）
        self._wake_verify_max_samples = int(self._asr_rate * 1.2)  # 打断验证取最近1.2秒
        self._prev_dnd_mode = False  # 上一轮勿扰状态，用于检测 DND 解除瞬间清流

        # VAD 前置缓存（用于待机时轻量级语音检测）
        self._vad_buffer = []
        self._vad_buffer_max_seconds = 2
        self._vad_buffer_max_samples = int(self._asr_rate * self._vad_buffer_max_seconds)

        # 连续对话模式音频缓冲（用于声纹验证）
        self._conv_audio_buffer = []
        self._conv_buffer_max_seconds = 3
        self._conv_buffer_max_samples = int(self._asr_rate * self._conv_buffer_max_seconds)
        self._speaker_verified = False  # 标记唤醒者是否已通过声纹验证
        self._speaker_embeddings = {}  # name -> embedding array，用于渐进更新
        self._verified_speaker_name = None  # 当前验证通过的说话人

        self._is_openclaw_busy = False
        self._is_processing = False  # True: 从指令发出到TTS播报完毕的全流程
        self._openclaw_request_active = threading.Event()
        self._stop_openclaw_request = threading.Event()
        self._ignore_next_result = False
        self._suppress_recognition_until_tts_done = False
        self._last_diag_log = 0.0  # 监听循环诊断日志节流时间戳（文件级，不进控制中心）
        self._last_interrupt_time = 0  # 记录上次打断时间，用于防止误触发
        self._last_wake_time = 0  # 记录上次唤醒时间，唤醒后保护期内跳过退出检测
        self._keyword_stream_reset_event = (
            threading.Event()
        )  # 用于通知主循环重置 keyword_stream

        self.keyword_spotter = self._create_keyword_spotter()
        # 始终创建流式识别器（用于连续对话模式）
        self.recognizer = self._create_recognizer()

        # 根据 assistant 配置决定使用哪种识别模式
        asr_mode = self.current_cfg.get("asr_mode", "streaming")
        if asr_mode == "sense_voice_en":
            # 使用 SenseVoice 英文模式
            sense_result = self._create_sense_voice_recognizer(language="en")
            if sense_result and sense_result[0] is not None:
                self.offline_recognizer, self.vad_config = sense_result
                self._use_offline_asr = True
                print("[配置] 贾维斯使用 SenseVoice 英文识别模式 (English only)")
            else:
                self._use_offline_asr = False
                print("[配置] SenseVoice 不可用，使用流式识别模式（热词增强）")
        elif asr_mode == "sense_voice":
            # 使用 SenseVoice 自动语言检测
            sense_result = self._create_sense_voice_recognizer(language="auto")
            if sense_result and sense_result[0] is not None:
                self.offline_recognizer, self.vad_config = sense_result
                self._use_offline_asr = True
                print("[配置] 使用 SenseVoice 多语言识别模式")
            else:
                self._use_offline_asr = False
                print("[配置] SenseVoice 不可用，使用流式识别模式（热词增强）")
        elif asr_mode == "offline":
            # 尝试创建 Qwen3-ASR 离线识别器
            offline_result = self._create_offline_recognizer()
            if offline_result and offline_result[0] is not None:
                self.offline_recognizer, self.vad_config, _ = offline_result
                self._use_offline_asr = True
                print("[配置] 使用 Qwen3-ASR 离线识别模式")
            else:
                self._use_offline_asr = False
                print("[配置] Qwen3-ASR 不可用，使用流式识别模式（热词增强）")
        else:
            self._use_offline_asr = False
            print("[配置] 使用流式识别模式（热词增强）")

        self._check_microphone()

        # ── 声纹验证初始化 ──────────────────────────────────────
        self._speaker_extractor = None
        self._speaker_manager = None
        self._speaker_enabled = False
        self._init_speaker_verification()

        # ── VAD 配置初始化（用于待机时轻量级语音检测）───────────
        self._init_vad_config()

        # OpenClaw bridge 会在切换 assistant 时动态创建
        self.openclaw = None
        self._init_openclaw()

        print("语音助手初始化完成！")
        print(
            f"已加载 {len(all_assistants)} 个 assistant: {[a['name'] for a in all_assistants]}"
        )
        print(f"唤醒词: {self._get_keywords()}")
        print("正在检测 OpenClaw 连接...")
        print("提示: 说出任意唤醒词即可唤醒对应的 assistant，支持连续对话")

    def _init_speaker_verification(self):
        """初始化声纹验证系统"""
        speakers = _load_speakers()

        if not speakers:
            print("[声纹] 未检测到已注册的声纹样本")
            print("[声纹] 声纹验证已启用（强制模式）")
            print("[声纹] 请使用 control_center 应用注册声纹")
            print("[声纹] 在未注册声纹前，语音助手将拒绝唤醒")
            self._speaker_enabled = True
            self._speaker_extractor = None
            self._speaker_manager = None
            self._speaker_embeddings = {}
            self._verified_speaker_name = None
            return

        if not _check_speaker_model():
            print("[声纹] 声纹模型不存在，跳过声纹验证")
            print(f"[声纹] 请下载模型: {_SPEAKER_MODEL_PATH}")
            return

        print(f"[声纹] 发现 {len(speakers)} 个已注册声纹，初始化验证系统...")

        self._speaker_extractor = _create_speaker_extractor()
        if self._speaker_extractor is None:
            print("[声纹] 提取器初始化失败，禁用声纹验证")
            return

        dim = self._speaker_extractor.dim
        self._speaker_manager = _create_speaker_manager(dim)
        self._speaker_embeddings = {}
        self._verified_speaker_name = None

        import soundfile as sf
        loaded_count = 0
        for speaker_info in speakers:
            wav_file = os.path.join(_SPEAKER_DIR, speaker_info.get('wav_file', ''))
            if not os.path.exists(wav_file):
                print(f"[声纹] 警告: 音频文件不存在: {wav_file}")
                continue

            try:
                name = speaker_info.get('name', f"user_{speaker_info.get('timestamp', 0)}")
                emb_list = None

                if 'embedding' in speaker_info and speaker_info['embedding']:
                    emb_list = speaker_info['embedding']
                    print(f"[声纹调试] 从JSON加载嵌入: {name}, 前5值: {emb_list[:5]}")
                else:
                    samples, sr = sf.read(wav_file, dtype='float32')
                    if len(samples.shape) > 1:
                        samples = samples.mean(axis=1)
                    print(f"[声纹调试] 加载声纹文件: {wav_file}, 样本长度: {len(samples)}")
                    embedding = _extract_embedding(self._speaker_extractor, samples.tolist(), sr)
                    if embedding is not None:
                        emb_list = embedding.tolist()
                        speaker_info['embedding'] = emb_list
                        _save_speakers(speakers)
                        print(f"[声纹] 已提取并保存嵌入: {name}")

                if emb_list is not None:
                    success = self._speaker_manager.add(name, emb_list)
                    if success:
                        self._speaker_embeddings[name] = np.array(emb_list)
                        loaded_count += 1
                        print(f"[声纹] 已加载: {name}")
                        print(f"[声纹调试] 当前已注册: {self._speaker_manager.all_speakers}")
                    else:
                        print(f"[声纹] 加载失败: {name}")
            except Exception as e:
                print(f"[声纹] 处理文件失败 {wav_file}: {e}")

        if loaded_count > 0:
            self._speaker_enabled = True
            print(f"[声纹] 验证系统已启用（{loaded_count} 个声纹已加载）")
            print(f"[声纹] 唤醒时将验证说话人身份")
        else:
            print("[声纹] 没有成功加载任何声纹，禁用验证")

    @property
    def is_awake(self) -> bool:
        return self._is_awake

    @is_awake.setter
    def is_awake(self, value: bool):
        """激活态写入口：仅在 False↔True 边沿派发生命周期联动钩子。

        全项目所有 `self.is_awake = X` 都经由此处，重复赋值不会重复触发，
        看门狗强制回待机、重启等角落也天然纳管。新增联动只需 register，
        主流程无需改动。
        """
        value = bool(value)
        changed = value != self._is_awake
        self._is_awake = value
        if changed:
            self._lifecycle.notify(value)

    def _init_vad_config(self):
        """初始化 VAD 配置（用于待机时轻量级语音检测）"""
        vad_model = os.path.expanduser(self.args.vad_model)
        if not os.path.exists(vad_model):
            print("[VAD] VAD 模型不存在: {}，待机时将不使用 VAD 预检测".format(vad_model))
            self.vad_config = None
            return

        try:
            self.vad_config = sherpa_onnx.VadModelConfig(
                silero_vad=sherpa_onnx.SileroVadModelConfig(
                    model=vad_model,
                    threshold=0.1,
                    min_silence_duration=0.3,
                    min_speech_duration=0.1,
                    max_speech_duration=30,
                    window_size=512,
                ),
                sample_rate=16000,
                num_threads=1,
                provider=self.args.provider,
            )
            print("[VAD] VAD 配置创建成功（待机预检测模式）")
        except Exception as e:
            print("[VAD] provider={} 不可用，回退到 cpu: {}".format(self.args.provider, e))
            try:
                self.vad_config = sherpa_onnx.VadModelConfig(
                    silero_vad=sherpa_onnx.SileroVadModelConfig(
                        model=vad_model,
                        threshold=0.1,
                        min_silence_duration=0.3,
                        min_speech_duration=0.1,
                        max_speech_duration=30,
                        window_size=512,
                    ),
                    sample_rate=16000,
                    num_threads=1,
                    provider="cpu",
                )
                print("[VAD] VAD 配置创建成功（cpu fallback）")
            except Exception as e2:
                print("[VAD] VAD 配置创建失败: {}".format(e2))
                self.vad_config = None

    def _verify_speaker_on_wake(self, samples, sample_rate=16000, threshold=None):
        """唤醒/打断时验证声纹

        threshold: 相似度阈值，None 用全局 _SPEAKER_THRESHOLD（0.55）。
        打断场景传更低阈值（如 0.40）：TTS 混音会稀释声纹特征，降低阈值
        提高真人在播报中打断的通过率，同时纯 TTS 回声（实测相似度 0.00）
        仍会被可靠拒绝。
        
        Returns:
            bool: 验证是否通过
        """
        if not self._speaker_enabled:
            return True  # 未启用时默认通过
        
        # 检查是否有注册声纹
        speakers = _load_speakers()
        if not speakers:
            print("\n[声纹] ⚠️ 拒绝唤醒: 未检测到已注册声纹")
            print("[声纹] 请先使用 control_center 应用注册声纹")
            print("[声纹] 注册完成后请重启语音助手")
            return False
        
        if self._speaker_extractor is None or self._speaker_manager is None:
            print("[声纹] 验证系统未就绪，拒绝唤醒")
            return False
        
        # 检查音频样本是否有效
        if not samples or len(samples) == 0:
            print("[声纹] 警告: 音频样本为空，跳过验证")
            return True  # 空样本时允许唤醒，避免阻塞
        
        # 样本过短时允许唤醒（暂不强制验证，唤醒词本身已提供基本安全）
        min_samples = int(sample_rate * 0.1)  # 0.1秒最低要求（约1600采样点）
        if len(samples) < min_samples:
            print(f"[声纹] 警告: 音频样本过短 ({len(samples)} samples, 需要{min_samples})，跳过验证")
            return True
        
        is_verified, speaker_name, score = _verify_speaker(
            self._speaker_extractor,
            self._speaker_manager,
            samples,
            sample_rate,
            threshold,
        )
        _diag.info(
            "[声纹] threshold=%s verified=%s name=%s score=%.3f",
            threshold if threshold is not None else _SPEAKER_THRESHOLD,
            is_verified,
            speaker_name,
            score,
        )

        if is_verified:
            print(f"[声纹] 验证通过: {speaker_name} (score: {score:.3f})")
            self._verified_speaker_name = speaker_name
            self._update_speaker_progressive(samples, sample_rate)
            return True
        else:
            print(f"[声纹] 验证失败: 未识别到已注册声纹 (score: {score:.3f})")
            print("[声纹] 请使用已注册声纹的用户唤醒，或使用 control_center 注册新声纹")
            return False

    def _update_speaker_progressive(self, samples, sample_rate=16000):
        """用最新对话音频渐进更新已验证用户的声纹嵌入

        取前5秒音频，静音过滤后提取嵌入，与旧嵌入各50%平均融合，
        然后持久化到文件并更新内存中的manager。
        """
        if not self._speaker_enabled or self._verified_speaker_name is None:
            return

        if self._speaker_extractor is None or self._speaker_manager is None:
            return

        import soundfile as sf
        import librosa

        max_samples = int(sample_rate * 5)
        if len(samples) > max_samples:
            samples = samples[-max_samples:]

        try:
            trimmed, _ = librosa.effects.trim(samples, top_db=20)
        except Exception:
            trimmed = samples

        if len(trimmed) < sample_rate * 0.5:
            print(f"[声纹] 渐进更新跳过: 静音过滤后音频太短 ({len(trimmed)} samples)")
            return

        embedding = _extract_embedding(self._speaker_extractor, trimmed, sample_rate)
        if embedding is None:
            print("[声纹] 渐进更新跳过: 嵌入提取失败")
            return

        name = self._verified_speaker_name
        old_emb = self._speaker_embeddings.get(name)
        if old_emb is not None:
            new_emb = 0.5 * old_emb + 0.5 * embedding
        else:
            new_emb = embedding

        new_emb_list = new_emb.tolist()
        self._speaker_embeddings[name] = new_emb

        self._speaker_manager.remove(name)
        success = self._speaker_manager.add(name, new_emb_list)
        if success:
            print(f"[声纹] 渐进更新成功: {name}")
        else:
            print(f"[声纹] 渐进更新失败: manager更新失败")

        speakers = _load_speakers()
        for sp in speakers:
            if sp.get('name') == name:
                sp['embedding'] = new_emb_list
                wav_file = os.path.join(_SPEAKER_DIR, sp.get('wav_file', ''))
                if wav_file:
                    sf.write(wav_file, trimmed, sample_rate)
                    print(f"[声纹] 已更新音频文件: {wav_file}")
                break
        _save_speakers(speakers)

    def _verify_current_speaker(self) -> bool:
        """连续对话模式中验证当前说话人是否为已注册用户

        Returns:
            bool: 验证是否通过
        """
        if not self._speaker_enabled:
            return True

        if self._speaker_extractor is None or self._speaker_manager is None:
            return True  # 验证系统未就绪时允许通过，避免阻塞对话

        # 合并缓冲音频
        audio_samples = []
        for buf in self._conv_audio_buffer:
            audio_samples.extend(buf)

        if len(audio_samples) < self._conv_buffer_max_samples // 2:
            return True  # 音频不足，跳过验证

        is_verified, name, score = _verify_speaker(
            self._speaker_extractor,
            self._speaker_manager,
            audio_samples,
            self._asr_rate
        )

        if is_verified:
            print("[声纹] 连续对话验证通过: {} (score: {:.3f})".format(name, score))
            if self._verified_speaker_name is None:
                self._verified_speaker_name = name
            elif self._verified_speaker_name != name:
                self._verified_speaker_name = name
                print("[声纹] 警告: 检测到说话人变更，更新验证用户")
            return True
        else:
            print("[声纹] 连续对话验证失败: 陌生人声音已忽略 (score: {:.3f})".format(score))
            self._conv_audio_buffer.clear()
            return False

    def _switch_assistant(self, assistant_id: str):
        """切换到指定的 assistant"""
        if assistant_id not in self.all_assistants:
            print(f"[错误] 未知的 assistant: {assistant_id}")
            return False

        # 切换到新的 assistant
        instance = self.assistant_manager.switch_to(assistant_id)
        if not instance:
            return False

        self.current_cfg = self.all_assistants[assistant_id]
        _apply_assistant_config(self.current_cfg)

        # 根据 assistant 配置决定使用哪种识别模式
        asr_mode = self.current_cfg.get("asr_mode", "streaming")
        if asr_mode == "sense_voice_en":
            if (
                hasattr(self, "offline_recognizer")
                and self.offline_recognizer is not None
            ):
                self._use_offline_asr = True
                print(f"[配置] {self.current_cfg['name']} 使用 SenseVoice 英文模式")
            else:
                sense_result = self._create_sense_voice_recognizer(language="en")
                if sense_result and sense_result[0] is not None:
                    self.offline_recognizer, self.vad_config = sense_result
                    self._use_offline_asr = True
                    print(
                        f"[配置] {self.current_cfg['name']} 使用 SenseVoice 英文模式 (English only)"
                    )
                else:
                    self._use_offline_asr = False
                    print(
                        f"[配置] {self.current_cfg['name']} SenseVoice 不可用，使用流式识别"
                    )
        elif asr_mode == "sense_voice":
            if (
                hasattr(self, "offline_recognizer")
                and self.offline_recognizer is not None
            ):
                self._use_offline_asr = True
                print(f"[配置] {self.current_cfg['name']} 使用 SenseVoice 多语言模式")
            else:
                sense_result = self._create_sense_voice_recognizer(language="auto")
                if sense_result and sense_result[0] is not None:
                    self.offline_recognizer, self.vad_config = sense_result
                    self._use_offline_asr = True
                    print(
                        f"[配置] {self.current_cfg['name']} 使用 SenseVoice 多语言模式"
                    )
                else:
                    self._use_offline_asr = False
                    print(
                        f"[配置] {self.current_cfg['name']} SenseVoice 不可用，使用流式识别"
                    )
        elif asr_mode == "offline":
            if (
                hasattr(self, "offline_recognizer")
                and self.offline_recognizer is not None
            ):
                self._use_offline_asr = True
                print(f"[配置] {self.current_cfg['name']} 使用 Qwen3-ASR 离线识别模式")
            else:
                offline_result = self._create_offline_recognizer()
                if offline_result and offline_result[0] is not None:
                    self.offline_recognizer, self.vad_config, _ = offline_result
                    self._use_offline_asr = True
                    print(
                        f"[配置] {self.current_cfg['name']} 使用 Qwen3-ASR 离线识别模式"
                    )
                else:
                    self._use_offline_asr = False
                    print(
                        f"[配置] {self.current_cfg['name']} Qwen3-ASR 不可用，使用流式识别"
                    )
        else:
            self._use_offline_asr = False
            print(f"[配置] {self.current_cfg['name']} 使用流式识别模式")

        # 更新当前使用的组件
        self.jarvis = instance.feedback
        self.visual = instance.visual
        self.tts = instance.tts
        set_tts(self.tts)

        # Vision 能力跟随当前角色 visual：切换角色时若视觉模式激活则先关闭，
        # 并把帧推送目标绑定到新角色（摄像头/帧流随角色释放，避免泄漏）
        try:
            from vision import get_vision_manager
            get_vision_manager().stop_if_active()
            get_vision_manager().bind_visual(self.visual)
            get_vision_manager().set_role(self.current_cfg.get("id", "jarvis"))
        except Exception as e:
            print(f"[Vision] 角色切换联动失败: {e}")

        # 特效调试模式（assistants.json 顶层 overlay_debug_mode）：
        # 开启后，召唤出来的特效不再被隐藏/清空，方便调样式
        if hasattr(self.visual, "set_debug_mode"):
            self.visual.set_debug_mode(_load_overlay_debug())

        print(f"[切换] 已切换到: {self.current_cfg['name']} ({assistant_id})")
        return True

    def _init_openclaw(self):
        """初始化 OpenClaw bridge"""
        assistant_id = self.current_cfg["id"]
        if self.openclaw:
            # 如果有旧的，先发送停止，再关闭其 WebSocket 长连接（避免切换时连接泄漏）
            self.openclaw.send_stop_command()
            close = getattr(self.openclaw, "close", None)
            if callable(close):
                close()
        # namespace 与 agent_id 一致 → session key = agent:<id>:<id>（如 agent:jarvis:jarvis），
        # 与历史会话 lane 保持一致；WS 桥用 chat.abort/sessions.reset 控制面 RPC，
        # 不再把 /stop、/clear 作为聊天消息排进同一 lane，从根上消除 "Command lane cleared"。
        agent_id = assistant_id.replace("-", "_")
        self.openclaw = get_bridge(agent_id=agent_id, namespace=agent_id)
        self.openclaw.precheck_async()

    def _detect_assistant_from_keyword(self, keyword_result: str) -> str:
        """从唤醒词检测结果识别是哪个 assistant"""
        if not keyword_result:
            return self.current_cfg["id"]

        # 在 keyword_mapping 中查找
        for keyword_text, assistant_id in self.keyword_mapping.items():
            if keyword_text in keyword_result or keyword_result in keyword_text:
                return assistant_id

        # 如果没找到，返回当前 assistant
        return self.current_cfg["id"]

    def _check_microphone(self):
        """检查麦克风设备"""
        devices = sd.query_devices()
        if len(devices) == 0:
            print("未找到麦克风设备")
            sys.exit(0)

        print("可用设备:")
        for i, device in enumerate(devices):
            name = (
                device.get("name", f"设备 {i}")
                if hasattr(device, "get")
                else f"设备 {i}"
            )
            print(f"  {i}: {name}")

        default_idx = sd.default.device[0]
        if default_idx is not None and default_idx < len(devices):
            dev = devices[default_idx]
            name = (
                dev.get("name", f"设备 {default_idx}")
                if hasattr(dev, "get")
                else f"设备 {default_idx}"
            )
            print(f"使用默认设备: {name}")

    def _create_keyword_spotter(self):
        """创建关键词检测器"""
        try:
            spotter = sherpa_onnx.KeywordSpotter(
                tokens=self.args.kws_tokens,
                encoder=self.args.kws_encoder,
                decoder=self.args.kws_decoder,
                joiner=self.args.kws_joiner,
                num_threads=1,
                keywords_file=self.args.keywords_file,
                keywords_score=self.args.keywords_score,
                keywords_threshold=self.args.keywords_threshold,
                max_active_paths=8,
                num_trailing_blanks=2,
                provider=self.args.provider,
            )
            print(f"[KWS] 使用 provider: {self.args.provider}")
            return spotter
        except Exception as e:
            print(f"[KWS] provider={self.args.provider} 不可用，回退到 cpu: {e}")
            return sherpa_onnx.KeywordSpotter(
                tokens=self.args.kws_tokens,
                encoder=self.args.kws_encoder,
                decoder=self.args.kws_decoder,
                joiner=self.args.kws_joiner,
                num_threads=1,
                keywords_file=self.args.keywords_file,
                keywords_score=self.args.keywords_score,
                keywords_threshold=self.args.keywords_threshold,
                max_active_paths=8,
                num_trailing_blanks=2,
                provider="cpu",
            )

    def _create_recognizer(self):
        """创建语音识别器"""
        hotwords_file = os.path.expanduser(self.args.hotwords_file)
        use_hotwords = os.path.exists(hotwords_file)
        if use_hotwords:
            print(f"[ASR] 加载热词文件: {hotwords_file}")
        else:
            print(f"[ASR] 热词文件不存在: {hotwords_file}，不启用热词")

        return sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=self.args.asr_tokens,
            encoder=self.args.asr_encoder,
            decoder=self.args.asr_decoder,
            joiner=self.args.asr_joiner,
            num_threads=1,
            sample_rate=self._asr_rate,
            feature_dim=80,
            decoding_method="modified_beam_search" if use_hotwords else "greedy_search",
            hotwords_file=hotwords_file if use_hotwords else "",
            hotwords_score=self.args.hotwords_score,
            modeling_unit="cjkchar+bpe",
            bpe_vocab=self.args.asr_tokens,
            provider=self.args.provider,
        )

    def _create_sense_voice_recognizer(self, language="auto"):
        """创建 SenseVoice 离线识别器和 VAD 配置

        Args:
            language: 语言参数，auto/zh/en/ko/ja/yue
        """
        sense_voice_model = os.path.expanduser(self.args.sense_voice_model)
        sense_voice_tokens = os.path.expanduser(self.args.sense_voice_tokens)
        vad_model = os.path.expanduser(self.args.vad_model)

        if not os.path.exists(sense_voice_model):
            print(f"[警告] SenseVoice 模型不存在: {sense_voice_model}")
            return None, None

        print(f"[SenseVoice] 初始化离线识别器 (language={language})...")
        print(f"  model: {sense_voice_model}")
        print(f"  tokens: {sense_voice_tokens}")
        print(f"  use_itn: {self.args.sense_voice_use_itn}")

        try:
            recognizer = (
                sherpa_onnx.offline_recognizer.OfflineRecognizer.from_sense_voice(
                    model=sense_voice_model,
                    tokens=sense_voice_tokens,
                    num_threads=2,
                    use_itn=bool(self.args.sense_voice_use_itn),
                    language=language,
                )
            )
            print("[SenseVoice] 离线识别器创建成功")
        except Exception as e:
            print(f"[SenseVoice] 创建离线识别器失败: {e}")
            return None, None

        if not os.path.exists(vad_model):
            print(f"[警告] VAD 模型不存在: {vad_model}")
            print("[警告] 无法使用 SenseVoice")
            return recognizer, None

        print(f"[VAD] 初始化 VAD...")
        try:
            vad_config = sherpa_onnx.VadModelConfig(
                silero_vad=sherpa_onnx.SileroVadModelConfig(
                    model=vad_model,
                    threshold=0.1,
                    min_silence_duration=0.3,
                    min_speech_duration=0.1,
                    max_speech_duration=30,
                    window_size=512,
                ),
                sample_rate=16000,
                num_threads=1,
                provider=self.args.provider,
            )
            print("[VAD] VAD 配置创建成功")
        except Exception as e:
            print(f"[VAD] provider={self.args.provider} 不可用，回退到 cpu: {e}")
            vad_config = sherpa_onnx.VadModelConfig(
                silero_vad=sherpa_onnx.SileroVadModelConfig(
                    model=vad_model,
                    threshold=0.1,
                    min_silence_duration=0.3,
                    min_speech_duration=0.1,
                    max_speech_duration=30,
                    window_size=512,
                ),
                sample_rate=16000,
                num_threads=1,
                provider="cpu",
            )

        return recognizer, vad_config

    def _create_offline_recognizer(self):
        """创建 Qwen3-ASR 离线识别器和 VAD 配置"""
        qwen3_conv_frontend = os.path.expanduser(self.args.qwen3_conv_frontend)
        qwen3_encoder = os.path.expanduser(self.args.qwen3_encoder)
        qwen3_decoder = os.path.expanduser(self.args.qwen3_decoder)
        qwen3_tokenizer = os.path.expanduser(self.args.qwen3_tokenizer)
        vad_model = os.path.expanduser(self.args.vad_model)

        if not os.path.exists(qwen3_encoder):
            print(f"[警告] Qwen3-ASR 模型不存在: {qwen3_encoder}")
            print("[警告] 使用流式识别器替代")
            return None, None, None

        print(f"[Qwen3-ASR] 初始化离线识别器...")
        print(f"  conv_frontend: {qwen3_conv_frontend}")
        print(f"  encoder: {qwen3_encoder}")
        print(f"  decoder: {qwen3_decoder}")
        print(f"  tokenizer: {qwen3_tokenizer}")

        try:
            recognizer = (
                sherpa_onnx.offline_recognizer.OfflineRecognizer.from_qwen3_asr(
                    conv_frontend=qwen3_conv_frontend,
                    encoder=qwen3_encoder,
                    decoder=qwen3_decoder,
                    tokenizer=qwen3_tokenizer,
                    num_threads=2,
                )
            )
            print("[Qwen3-ASR] 离线识别器创建成功")
        except Exception as e:
            print(f"[Qwen3-ASR] 创建离线识别器失败: {e}")
            return None, None, None

        if not os.path.exists(vad_model):
            print(f"[警告] VAD 模型不存在: {vad_model}")
            print("[警告] 无法使用 Qwen3-ASR")
            return None, None, None

        print(f"[VAD] 初始化 VAD...")
        try:
            vad_config = sherpa_onnx.VadModelConfig(
                silero_vad=sherpa_onnx.SileroVadModelConfig(
                    model=vad_model,
                    threshold=0.1,
                    min_silence_duration=0.3,
                    min_speech_duration=0.1,
                    max_speech_duration=30,
                    window_size=512,
                ),
                sample_rate=16000,
                num_threads=1,
                provider=self.args.provider,
            )
            print("[VAD] VAD 配置创建成功")
        except Exception as e:
            print(f"[VAD] provider={self.args.provider} 不可用，回退到 cpu: {e}")
            vad_config = sherpa_onnx.VadModelConfig(
                silero_vad=sherpa_onnx.SileroVadModelConfig(
                    model=vad_model,
                    threshold=0.1,
                    min_silence_duration=0.3,
                    min_speech_duration=0.1,
                    max_speech_duration=30,
                    window_size=512,
                ),
                sample_rate=16000,
                num_threads=1,
                provider="cpu",
            )

        return recognizer, vad_config, None

    def _process_recognition_result(self, recognition_result):
        """处理识别结果，返回是否继续循环"""
        if not recognition_result:
            return True

        _recog = recognition_result.strip()
        # 文本纠错：兜底修复 sherpa hotwords 救不了的 OOV 英文整词误识别
        # （如 "TONY STOCK" → "Tony Stark"）。幂等安全，流式中间态替换不影响 final。
        _corrected = _apply_text_corrections(_recog)
        if _corrected != _recog:
            print(f"[文本纠错] {_recog!r} → {_corrected!r}")
        _recog = _corrected
        _is_exit = _recog in EXIT_KEYWORDS or _recog in INSTANT_EXIT_FUZZY
        if _is_exit:
            print(f"收到退出指令: {recognition_result.strip()}")
            self._interrupt_openclaw()
            # self._clear_openclaw_context()
            self.jarvis.on_exit()
            self.visual.clear_texts()
            self.visual.hide_effects()
            if not _is_instant_exit(_recog):
                play_prebuilt_voice("exit", _random_exit_line())
                while is_tts_playing():
                    time.sleep(0.05)
            self._clear_queue()
            self.is_awake = False
            self.continuous_mode = False
            self._vad_stream = None
            self._audio_buffer = []
            self._speech_started = False
            print("\n已退出监听，等待唤醒词...")
            return False

        self.visual.show_user_text(_recog)
        if not self._ignore_next_result:
            threading.Thread(
                target=self._on_recognized,
                args=(_recog,),
                daemon=True,
            ).start()
        else:
            self._ignore_next_result = False
            print("[打断] 已忽略识别结果")
        return True

    def _get_keywords(self):
        """获取关键词列表"""
        keywords = []
        if os.path.exists(self.args.keywords_file):
            with open(self.args.keywords_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and "@" in line:
                        keyword = line.split("@")[-1].strip()
                        keywords.append(keyword)
        return keywords

    def _resample_for_asr(self, samples):
        """将输入流采样率的音频重采样到 ASR 模型期望的 16kHz。
        输入流保持 48kHz 兼容其他应用，sherpa-onnx 模型训练时为 16kHz，
        必须重采样才能正确提取 fbank 特征。"""
        if self.sample_rate == self._asr_rate:
            return samples
        if _soxr is not None:
            return _soxr.resample(samples, self.sample_rate, self._asr_rate).astype(np.float32)
        # 无 soxr 时退回：简单每 N 取 1（粗略降采样，精度差但不会像错采样率那样完全乱套）
        ratio = self.sample_rate // self._asr_rate
        return samples[::ratio]

    def _audio_callback(self, indata, frames, time_info, status):
        """音频回调函数"""
        if status:
            print(status)
        # 播放期间也持续入队，保证能用唤醒词打断播报。自身播报被麦克风重新
        # 拾取引发的自唤醒，由打断路径的 VAD + 声纹验证拦截（见 _is_processing 分支）。
        if self.audio_queue.qsize() < 100:
            self.audio_queue.put(indata.copy())

    def _clear_queue(self):
        """清空音频队列"""
        try:
            while True:
                self.audio_queue.get_nowait()
        except queue.Empty:
            pass

    def _process_audio(self):
        """主音频处理循环 - 支持 Qwen3-ASR + VAD 模式"""

        recognition_stream = None
        recognition_result = ""
        keyword_stream = self.keyword_spotter.create_stream()
        audio_stream = None
        vad_stream = None
        audio_buffer = []
        speech_started = False
        speech_start_time = 0

        def start_audio_stream():
            nonlocal audio_stream
            if audio_stream is None:
                audio_stream = sd.InputStream(
                    channels=1,
                    dtype="float32",
                    samplerate=self.sample_rate,
                    callback=self._audio_callback,
                )
                audio_stream.start()

        def stop_audio_stream():
            # 【不要再调用 PortAudio 的 stop()/close()】——它们在 macOS CoreAudio 上
            # 会偶发永久死锁（卡在 C 调用里，try/except 兜不住），是"说完话后一直卡在
            # listening、不重启不恢复"的根因（尤其打断后 stop→start→端点→又 stop 的
            # 快速开关流场景）。而 _audio_callback 本就【始终入队】（TTS/处理期间也要
            # 检测唤醒词打断），即麦克风流本应常开。故这里改为"保持流常开、只清空已
            # 缓冲音频"——语义等价于原来的"丢弃这段输入"，并彻底规避死锁。
            # 真正的释放在进程退出时由系统回收。
            self._clear_queue()

        def reset_audio_stream():
            # 错误恢复路径：可能卡住的 stop()/close() 丢到后台守护线程执行（不阻塞
            # 主循环），立即置空并重建一个新流。即使旧流的 close 在后台卡死，主循环也
            # 不受影响。
            nonlocal audio_stream
            old = audio_stream
            audio_stream = None
            if old is not None:
                def _close_old(s):
                    try:
                        s.stop()
                        s.close()
                    except Exception:
                        pass
                threading.Thread(target=_close_old, args=(old,), daemon=True).start()
            self._clear_queue()
            start_audio_stream()

        def _create_vad_stream():
            nonlocal vad_stream
            if self.vad_config:
                try:
                    vad_stream = sherpa_onnx.VoiceActivityDetector(
                        config=self.vad_config,
                        buffer_size_in_seconds=60,
                    )
                    return True
                except Exception as e:
                    print("[VAD] 创建失败: {}".format(e))
                    return False
            return False

        def _do_recognize(audio_samples):
            """使用 SenseVoice 离线识别器识别音频片段"""
            if not self._use_offline_asr or not self.offline_recognizer:
                return None

            try:
                stream = self.offline_recognizer.create_stream()
                if hasattr(audio_samples, "tolist"):
                    samples_list = audio_samples.tolist()
                else:
                    samples_list = list(audio_samples)
                stream.accept_waveform(16000, samples_list)
                self.offline_recognizer.decode_stream(stream)
                return stream.result.text
            except Exception as e:
                print(f"[离线识别] 识别失败: {e}")
                return None

        start_audio_stream()
        print("开始监听...")
        print("提示: 说出唤醒词后可进入连续对话模式")

        # 创建 VAD 流（用于待机时轻量级语音检测）
        vad_stream = None
        if self.vad_config:
            if _create_vad_stream():
                print("[VAD] VAD 流已创建（待机预检测模式）")
            else:
                print("[VAD] VAD 流创建失败，待机时将不使用预检测")

        while not self.stop_event.is_set():
            try:
                # 检查是否需要重置 keyword_stream（由 exit_standby 触发）
                if self._keyword_stream_reset_event.is_set():
                    self._keyword_stream_reset_event.clear()
                    print(
                        "[重置] 检测到退出信号，正在重置 keyword_stream 和 audio_stream..."
                    )
                    stop_audio_stream()
                    time.sleep(0.05)
                    self._clear_queue()
                    keyword_stream = self.keyword_spotter.create_stream()
                    start_audio_stream()
                    time.sleep(0.05)
                    self._clear_queue()
                    print("[重置] 已完成，继续等待唤醒词...")
                    continue

                # 处理中（OpenClaw请求→TTS播报完毕），只检测唤醒词以支持打断
                if self._is_processing:
                    try:
                        audio_data = self.audio_queue.get(timeout=0.5)
                    except queue.Empty:
                        # 处理期间麦克风假死会让打断监听失效；重建音频流以恢复，
                        # 但不动 _is_processing 等标志（由请求/TTS 线程负责复位）。
                        if time.time() - self.last_activity_time > _AUDIO_STALL_TIMEOUT:
                            print("[看门狗] 处理期间音频流假死，重建以恢复打断监听...")
                            stop_audio_stream()
                            time.sleep(0.1)
                            self._clear_queue()
                            keyword_stream = self.keyword_spotter.create_stream()
                            start_audio_stream()
                            time.sleep(0.1)
                            self._clear_queue()
                            self.last_activity_time = time.time()
                        continue

                    self.last_activity_time = time.time()
                    samples = audio_data.reshape(-1)
                    asr_samples = self._resample_for_asr(samples)

                    # 滚动缓冲最近音频（复用待机唤醒的声纹缓冲），打断时取末尾窗口验证
                    self._wake_audio_buffer.append(asr_samples.tolist())
                    _buf_len = sum(len(b) for b in self._wake_audio_buffer)
                    while _buf_len > self._wake_buffer_max_samples:
                        _removed = self._wake_audio_buffer.pop(0)
                        _buf_len -= len(_removed)

                    # VAD 预检测：有真实语音才考虑打断候选（抑制环境噪音误触发）
                    _vad_has_speech = False
                    if vad_stream is not None:
                        vad_stream.accept_waveform(asr_samples)
                        if vad_stream.is_speech_detected():
                            _vad_has_speech = True

                    keyword_stream.accept_waveform(self._asr_rate, asr_samples)

                    while self.keyword_spotter.is_ready(keyword_stream):
                        self.keyword_spotter.decode_stream(keyword_stream)
                        kw_result = self.keyword_spotter.get_result(keyword_stream)
                        if kw_result:
                            _diag.info(
                                "[打断] 处理中 KWS 触发 kw=%s vad=%s",
                                kw_result,
                                _vad_has_speech,
                            )
                            detected_id = self._detect_assistant_from_keyword(kw_result)
                            if detected_id != self.current_cfg["id"]:
                                continue

                            # VAD 过滤：无语音不打断
                            if vad_stream is not None and not _vad_has_speech:
                                self.keyword_spotter.reset_stream(keyword_stream)
                                keyword_stream = self.keyword_spotter.create_stream()
                                continue

                            # 声纹验证：只放行注册用户。Jarvis 自身播报被麦克风重新
                            # 拾取触发唤醒词时，末尾窗口是合成音 → 验证失败 → 忽略，
                            # 避免"自己打断自己"造成复读死循环。
                            if self._speaker_enabled:
                                _int_samples = []
                                for _b in self._wake_audio_buffer:
                                    _int_samples.extend(_b)
                                _int_samples = _int_samples[-self._wake_verify_max_samples:]
                                # 打断用更低阈值（0.40）：TTS 混音会稀释声纹，
                                # 实测纯 TTS 相似度 0.00，仍可拒绝回声。
                                if not self._verify_speaker_on_wake(
                                    _int_samples,
                                    self._asr_rate,
                                    threshold=0.40,
                                ):
                                    print(
                                        f"\n[打断] 唤醒词 {kw_result} 未通过声纹验证，"
                                        "忽略（疑似自身播报）"
                                    )
                                    self.keyword_spotter.reset_stream(keyword_stream)
                                    keyword_stream = self.keyword_spotter.create_stream()
                                    continue

                            print(f"\n[打断] 检测到唤醒词: {kw_result}")
                            # 打断整个处理流程：停止TTS + 中断OpenClaw
                            stop_tts()
                            self._interrupt_openclaw()
                            # 保持唤醒状态，允许直接继续说话
                            self.is_awake = True
                            self.continuous_mode = True
                            # 打断后重置空闲计时：否则 silence_duration 仍是打断前
                            # 的陈旧值（任务可能已执行数十秒），会立即触发 30s 空闲超时退出
                            self.last_voice_time = time.time()
                            # 重置识别器，准备接收新指令
                            recognition_stream = self.recognizer.create_stream()
                            recognition_result = ""
                            self.keyword_spotter.reset_stream(keyword_stream)
                            keyword_stream = self.keyword_spotter.create_stream()
                            self._wake_audio_buffer.clear()
                            # 英文口头确认（打断成功），播放期间抑制识别避免误收自身确认音
                            self._suppress_recognition_until_tts_done = True
                            threading.Thread(
                                target=self._play_interrupt_ack, daemon=True
                            ).start()
                            print("\n请说出指令...")
                            break

                    self._clear_queue()
                    continue

                if audio_stream is None:
                    start_audio_stream()

                try:
                    audio_data = self.audio_queue.get(timeout=0.5)
                except queue.Empty:
                    # 音频流假死兜底：不论待机还是已唤醒，只要持续拿不到帧就重建。
                    # 旧逻辑仅在 not is_awake 时重建，导致"唤醒态麦克风假死"时主循环
                    # 在此处静默空转——既不打印日志、回不了待机、也唤不醒。
                    stalled = time.time() - self.last_activity_time
                    if stalled > _AUDIO_STALL_TIMEOUT:
                        was_awake = self.is_awake
                        print(
                            f"[看门狗] 音频流 {stalled:.0f}s 无数据，判定假死，正在重建"
                            + ("（并强制回到待机）..." if was_awake else "...")
                        )
                        # 死流期间可能卡住的状态全部复位，确保能重新被唤醒
                        if was_awake:
                            self.is_awake = False
                            self.continuous_mode = False
                            recognition_stream = None
                            recognition_result = ""
                        stop_audio_stream()
                        time.sleep(0.1)
                        self._clear_queue()
                        keyword_stream = self.keyword_spotter.create_stream()
                        start_audio_stream()
                        time.sleep(0.1)
                        self._clear_queue()
                        self.last_activity_time = time.time()
                        print("[看门狗] 音频流已重建，等待唤醒词...")
                    continue

                samples = audio_data.reshape(-1)
                asr_samples = self._resample_for_asr(samples)
                self.last_activity_time = time.time()

                if not self.is_awake:
                    # 持续缓冲音频用于声纹验证（16kHz，与模型匹配）
                    self._wake_audio_buffer.append(asr_samples.tolist())
                    total_len = sum(len(b) for b in self._wake_audio_buffer)
                    while total_len > self._wake_buffer_max_samples:
                        removed = self._wake_audio_buffer.pop(0)
                        total_len -= len(removed)

                    # 维护 VAD 前后缓存（最近 2 秒，16kHz）
                    self._vad_buffer.append(asr_samples.tolist())
                    vad_total = sum(len(b) for b in self._vad_buffer)
                    while vad_total > self._vad_buffer_max_samples:
                        self._vad_buffer.pop(0)
                        vad_total = sum(len(b) for b in self._vad_buffer)

                    # VAD 检测：有语音时才继续处理，抑制非人声（如电脑播放的人声/TTS）
                    vad_has_speech = False
                    if vad_stream is not None:
                        vad_stream.accept_waveform(asr_samples)
                        if vad_stream.is_speech_detected():
                            vad_has_speech = True

                    # DND 解除瞬间：重建 KWS 流，清掉跨越勿扰边界残留的半个唤醒词，
                    # 避免声纹录入刚结束就被尾音误唤醒（边沿触发，仅在 True→False 时执行一次）
                    if self._prev_dnd_mode and not _dnd_mode:
                        keyword_stream = self.keyword_spotter.create_stream()
                    self._prev_dnd_mode = _dnd_mode

                    # KWS 实时检测
                    keyword_stream.accept_waveform(self._asr_rate, asr_samples)

                    while self.keyword_spotter.is_ready(keyword_stream):
                        self.keyword_spotter.decode_stream(keyword_stream)
                        result = self.keyword_spotter.get_result(keyword_stream)
                        if result:
                            if _dnd_mode:
                                keyword_stream = self.keyword_spotter.create_stream()
                                continue
                            if result.strip() in EXIT_KEYWORDS:
                                print(f"\n检测到退出指令: {result}")
                                stop_audio_stream()
                                self._clear_queue()
                                play_prebuilt_voice("exit", "Standing by.")
                                while is_tts_playing():
                                    time.sleep(0.05)
                                time.sleep(0.1)
                                self._clear_queue()
                                keyword_stream = self.keyword_spotter.create_stream()
                                start_audio_stream()
                                time.sleep(0.05)
                                self._clear_queue()
                                continue

                            # VAD 前置过滤：KWS 检测到候选唤醒词时，用 VAD 确认是否有真实语音
                            if vad_stream is not None and not vad_has_speech:
                                self.keyword_spotter.reset_stream(keyword_stream)
                                keyword_stream = self.keyword_spotter.create_stream()
                                continue

                            print(f"\n检测到唤醒词: {result}")

                            # ── 声纹验证 ──────────────────────────────────────
                            if self._speaker_enabled:
                                # 从缓冲区取出最近 3 秒音频用于验证
                                wake_samples = []
                                for buf in self._wake_audio_buffer:
                                    wake_samples.extend(buf)
                                if len(wake_samples) > self._wake_buffer_max_samples:
                                    wake_samples = wake_samples[-self._wake_buffer_max_samples:]
                                print(f"[声纹] 唤醒词检测成功，准备验证声纹 (样本长度: {len(wake_samples)})")
                                is_verified = self._verify_speaker_on_wake(wake_samples, self._asr_rate)
                                if not is_verified:
                                    print("[声纹] 唤醒被拒绝: 未通过声纹验证")
                                    # 异步发送通知，避免 2 秒 connect 超时阻塞主循环
                                    threading.Thread(target=_notify_speaker_rejected, daemon=True).start()
                                    self._wake_audio_buffer.clear()
                                    self.keyword_spotter.reset_stream(keyword_stream)
                                    print("[声纹] 继续监听...")
                                    continue
                                self._wake_audio_buffer.clear()
                                self._speaker_verified = True  # 标记唤醒者已通过声纹验证

                            # 识别是哪个 assistant 的唤醒词，并切换
                            detected_assistant_id = self._detect_assistant_from_keyword(
                                result
                            )
                            if detected_assistant_id != self.current_cfg["id"]:
                                print(
                                    f"[切换] 检测到 {self.keyword_mapping.get(result, detected_assistant_id)} 的唤醒词，正在切换..."
                                )
                                self._switch_assistant(detected_assistant_id)
                                self._init_openclaw()

                            self._ignore_next_result = True
                            self._suppress_recognition_until_tts_done = True

                            if self.is_awake and self._is_openclaw_busy:
                                self._interrupt_openclaw()
                            elif self.is_awake:
                                pass

                            print("已进入连续对话模式，可以连续说出指令...")
                            print('说"退出连续对话模式"可返回唤醒模式')

                            self.is_awake = True
                            self.continuous_mode = True
                            self.last_voice_time = time.time()

                            stop_audio_stream()
                            self._clear_queue()
                            recognition_result = ""
                            recognition_stream = self.recognizer.create_stream()
                            self.recognizer.reset(recognition_stream)
                            keyword_stream = self.keyword_spotter.create_stream()

                            if self._use_offline_asr:
                                vad_stream = None
                                _create_vad_stream()
                                audio_buffer = []
                                speech_started = False

                            self.visual.show_wake_effect()
                            # 唤醒时推送全球热点资讯到地图球体右侧面板（后台抓取）
                            threading.Thread(
                                target=self._push_global_news, daemon=True
                            ).start()
                            # 唤醒后发"voice-assistant-wake-up"给后端引擎，由引擎返回
                            # 问候播报。改为在线程里跑 + 立即恢复音频流，支持唤醒后打断。
                            _wake_ts = time.strftime("%Y-%m-%d %H:%M:%S")
                            wake_thread = threading.Thread(
                                target=self._on_recognized,
                                args=(f"voice-assistant-wake-up-{_wake_ts}",),
                                daemon=True,
                            )
                            wake_thread.start()

                            # 唤醒线程在后台跑，主循环恢复音频流后检测打断。
                            # 返回后必须复位 suppress（它在上方 1597 行附近被置 True），否则
                            # 后续用户每句识别结果都会被丢弃，最终静音超时误退出。
                            self._suppress_recognition_until_tts_done = False
                            self._ignore_next_result = False
                            self._last_wake_time = (
                                time.time()
                            )  # 记录唤醒时间，唤醒后保护期内跳过退出检测

                            for _ in range(20):
                                self._clear_queue()
                            recognition_result = ""
                            start_audio_stream()
                            time.sleep(0.05)
                            for _ in range(20):
                                self._clear_queue()
                            continue
                    if not self.is_awake:
                        continue

                else:
                    # 已唤醒且不在处理中，正常处理语音识别
                    if recognition_stream is None:
                        recognition_stream = self.recognizer.create_stream()

                    # 持续缓冲音频用于声纹渐进更新（16kHz，与模型匹配）
                    self._conv_audio_buffer.append(asr_samples.tolist())
                    conv_total = sum(len(b) for b in self._conv_audio_buffer)
                    while conv_total > self._conv_buffer_max_samples:
                        removed = self._conv_audio_buffer.pop(0)
                        conv_total -= len(removed)

                    recognition_stream.accept_waveform(self._asr_rate, asr_samples)

                    while self.recognizer.is_ready(recognition_stream):
                        self.recognizer.decode_stream(recognition_stream)

                    result = self.recognizer.get_result(recognition_stream)
                    if result and result != recognition_result:
                        recognition_result = result
                        self.last_voice_time = time.time()
                        if not self._suppress_recognition_until_tts_done:
                            print(f"\r✓ 识别: {result}", end="", flush=True)
                        # 地图/视觉/电脑/编码类指令在流式阶段不刷输入框（避免 ASR 回声把话术重复打入），
                        # 最终判定为真指令时在下方统一显示一次。
                        if (
                            not self._map_like(result)
                            and not self._vision_like(result)
                            and not self._computer_like(result)
                            and not self._coding_like(result)
                            and not self._video_like(result)
                            and not self._drama_like(result)
                        ):
                            self.visual.show_user_text(result)

                    _early_recog = (
                        recognition_result.strip() if recognition_result else ""
                    )
                    # 打断后 2 秒内、唤醒后 2 秒内跳过退出检测，避免残留音频误触发
                    _recent_interrupt = (time.time() - self._last_interrupt_time) < 2.0
                    _recent_wake = (time.time() - self._last_wake_time) < 2.0
                    _early_exit = (
                        _early_recog
                        and not _recent_interrupt
                        and not _recent_wake
                        and (
                            _early_recog in EXIT_KEYWORDS
                            or _early_recog in INSTANT_EXIT_FUZZY
                        )
                    )
                    if _early_exit:
                        _is_instant = _is_instant_exit(_early_recog)
                        if _is_instant:
                            print(f"\n收到退出指令（立即执行）: {_early_recog}")
                        else:
                            print(f"\n收到退出指令（延时1s执行）: {_early_recog}")
                            time.sleep(1.0)
                        self.exit_standby(instant=_is_instant)
                        recognition_result = ""
                        recognition_stream = self.recognizer.create_stream()
                        stop_audio_stream()
                        self._clear_queue()
                        start_audio_stream()
                        keyword_stream = self.keyword_spotter.create_stream()
                        continue

                    current_time = time.time()
                    silence_duration = current_time - self.last_voice_time
                    idle_duration = current_time - self.last_activity_time

                    if (
                        self.continuous_mode
                        and silence_duration > self.idle_timeout
                        # 任务执行中（OpenClaw 请求/TTS 播报）不计空闲超时，
                        # 防止线程标志设置窗口或回复延迟期间被误判待机
                        and not self._is_processing
                        and not self._is_openclaw_busy
                    ):
                        print(
                            f"\n连续对话超时（{self.idle_timeout}秒无活动），自动退出"
                        )
                        self.exit_standby()
                        recognition_result = ""
                        self.keyword_spotter.reset_stream(keyword_stream)
                        keyword_stream = self.keyword_spotter.create_stream()
                        continue

                    _ep = self.recognizer.is_endpoint(recognition_stream)
                    # 文件级诊断（节流 2s，仅落盘、不进控制中心）：专抓"说完话后
                    # 一直卡在 listening"的现行——记录决定断句的全部变量，下次卡住
                    # 看 jarvis_diag_*.log 即可判明是哪个条件没满足。
                    if self.is_awake and (current_time - self._last_diag_log) > 2.0:
                        self._last_diag_log = current_time
                        _diag.info(
                            "LISTEN ep=%s sil=%.1f res_len=%d sup=%s proc=%s busy=%s cont=%s",
                            _ep, silence_duration, len(recognition_result or ""),
                            self._suppress_recognition_until_tts_done,
                            self._is_processing, self._is_openclaw_busy,
                            self.continuous_mode,
                        )

                    if _ep or (recognition_result and silence_duration > 1.5):
                        if recognition_result:
                            should_suppress = self._suppress_recognition_until_tts_done

                            if should_suppress:
                                print("[打断] TTS播放中/等待稳定，忽略识别结果")
                                _diag.warning(
                                    "断句命中但 suppress=True → 丢弃结果(%r)并继续监听"
                                    "（若反复出现即 suppress 标志卡死）",
                                    (recognition_result or "")[:40],
                                )
                                recognition_result = ""
                                recognition_stream = self.recognizer.create_stream()
                                start_audio_stream()
                                continue

                            print("\n识别结果:", recognition_result)

                            stop_audio_stream()
                            self._clear_queue()

                            _recog = recognition_result.strip()
                            # 打断后 2 秒内、唤醒后 2 秒内跳过退出检测，避免残留音频误触发
                            _recent_interrupt = (
                                time.time() - self._last_interrupt_time
                            ) < 2.0
                            _recent_wake = (time.time() - self._last_wake_time) < 2.0
                            _is_exit = (
                                not _recent_interrupt
                                and not _recent_wake
                                and (
                                    _recog in EXIT_KEYWORDS
                                    or _recog in INSTANT_EXIT_FUZZY
                                )
                            )
                            if _is_exit:
                                print(f"收到退出指令: {recognition_result.strip()}")
                                self._interrupt_openclaw()
                                # self._clear_openclaw_context()
                                stop_audio_stream()
                                self._clear_queue()
                                self.jarvis.on_exit()
                                self.visual.clear_texts()
                                self.visual.hide_effects()
                                if not _is_instant_exit(_recog):
                                    play_prebuilt_voice("exit", _random_exit_line())
                                    while is_tts_playing():
                                        time.sleep(0.05)
                                self._clear_queue()
                                self.is_awake = False
                                self.continuous_mode = False
                                recognition_result = ""
                                print("\n已退出监听，等待唤醒词...")
                                start_audio_stream()
                                time.sleep(0.05)
                                self._clear_queue()
                                keyword_stream = self.keyword_spotter.create_stream()
                                continue

                            # 检测重启关键词
                            _is_restart = _recog in RESTART_KEYWORDS
                            if _is_restart:
                                print(f"收到重启指令: {recognition_result.strip()}")
                                self._restart_assistant()
                                recognition_result = ""
                                continue

                            # 编码任务确认答复（确认/取消/超时）→ 优先于其他指令处理
                            if self._handle_coding_confirm(recognition_result):
                                self.visual.show_user_text(recognition_result)
                                recognition_result = ""
                                recognition_stream = self.recognizer.create_stream()
                                start_audio_stream()
                                continue

                            # 视频任务确认答复（确认/取消/超时）→ 优先于其他指令处理
                            if self._handle_video_confirm(recognition_result):
                                self.visual.show_user_text(recognition_result)
                                recognition_result = ""
                                recognition_stream = self.recognizer.create_stream()
                                start_audio_stream()
                                continue

                            # 短剧确认答复（确认/取消/超时）→ 优先于其他指令处理
                            if self._handle_drama_confirm(recognition_result):
                                self.visual.show_user_text(recognition_result)
                                recognition_result = ""
                                recognition_stream = self.recognizer.create_stream()
                                start_audio_stream()
                                continue

                            # Mission Control 确认/控制（任务确认/取消/暂停/继续/跳过/状态）
                            if self._handle_mission_control(recognition_result):
                                self.visual.show_user_text(recognition_result)
                                recognition_result = ""
                                recognition_stream = self.recognizer.create_stream()
                                start_audio_stream()
                                continue

                            # 地图指令（定位/缩放/重置）→ 直接驱动 overlay，不进大模型
                            if self._handle_map_command(recognition_result):
                                if self._map_show_user_text:
                                    self.visual.show_user_text(recognition_result)
                                recognition_result = ""
                                recognition_stream = self.recognizer.create_stream()
                                start_audio_stream()
                                continue

                            # 视觉模式指令（开启/关闭视觉扫描）→ 直接驱动 overlay，不进大模型
                            if self._handle_vision_command(recognition_result):
                                self.visual.show_user_text(recognition_result)
                                recognition_result = ""
                                recognition_stream = self.recognizer.create_stream()
                                start_audio_stream()
                                continue

                            # Video Agent（OpenCut 视频制作）指令 → 本地执行/确认，不进大模型
                            if self._handle_video_command(recognition_result):
                                self.visual.show_user_text(recognition_result)
                                recognition_result = ""
                                recognition_stream = self.recognizer.create_stream()
                                start_audio_stream()
                                continue

                            # Short Drama（短剧剪辑模式）指令 → 本地执行/确认，不进大模型
                            if self._handle_drama_command(recognition_result):
                                self.visual.show_user_text(recognition_result)
                                recognition_result = ""
                                recognition_stream = self.recognizer.create_stream()
                                start_audio_stream()
                                continue

                            # Coding Agent（Codex CLI 编码能力）指令 → 本地执行/确认，不进大模型
                            if self._handle_coding_command(recognition_result):
                                self.visual.show_user_text(recognition_result)
                                recognition_result = ""
                                recognition_stream = self.recognizer.create_stream()
                                start_audio_stream()
                                continue

                            # 电脑控制指令（打开/输入/点击/截图等）→ 本地能力执行，不进大模型
                            if self._handle_computer_command(recognition_result):
                                self.visual.show_user_text(recognition_result)
                                recognition_result = ""
                                recognition_stream = self.recognizer.create_stream()
                                start_audio_stream()
                                continue

                            # Mission Control 目标指令（任务/目标/规划）→ 规划 + 等待确认
                            if self._handle_mission_command(recognition_result):
                                self.visual.show_user_text(recognition_result)
                                recognition_result = ""
                                recognition_stream = self.recognizer.create_stream()
                                start_audio_stream()
                                continue

                            self.visual.show_user_text(recognition_result)
                            if not self._ignore_next_result:
                                threading.Thread(
                                    target=self._on_recognized,
                                    args=(recognition_result,),
                                    daemon=True,
                                ).start()
                            else:
                                self._ignore_next_result = False
                                print("[打断] 已忽略识别结果")

                            command_lower = recognition_result.lower()
                            exit_continuous = any(
                                kw in command_lower
                                for kw in [
                                    "退出连续对话",
                                    "退出连续模式",
                                    "退出对话模式",
                                ]
                            )

                            self._clear_queue()
                            start_audio_stream()

                            if self.continuous_mode and not exit_continuous:
                                recognition_result = ""
                                recognition_stream = self.recognizer.create_stream()
                                print("\n请继续说出指令...")
                            else:
                                if not self._is_openclaw_busy:
                                    self.visual.hide_effects()
                                self.visual.clear_texts()
                                self.is_awake = False
                                self.continuous_mode = False
                                recognition_result = ""
                                print("\n请说出唤醒词来激活...")
                                keyword_stream = self.keyword_spotter.create_stream()
                        else:
                            if self.continuous_mode:
                                recognition_stream = self.recognizer.create_stream()
                            else:
                                if not self._is_openclaw_busy:
                                    self.visual.hide_effects()
                                self.visual.clear_texts()
                                self.is_awake = False
                                print("\n请说出唤醒词来激活...")
                                keyword_stream = self.keyword_spotter.create_stream()

            except queue.Empty:
                continue
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"错误: {e}")
                import traceback

                traceback.print_exc()
                print("[恢复] 正在尝试重建音频流...")
                reset_audio_stream()
                self._clear_queue()
                keyword_stream = self.keyword_spotter.create_stream()
                recognition_stream = self.recognizer.create_stream()
                recognition_result = ""
                speech_started = False
                time.sleep(1)
                try:
                    start_audio_stream()
                    print("[恢复] 音频流已重建，继续监听...")
                    continue
                except Exception as ne:
                    print(f"[恢复] 音频流重建失败: {ne}")
                    print("[恢复] 将尝试在下一循环重建...")
                    time.sleep(2)
                    continue

        stop_audio_stream()

    def _interrupt_openclaw(self):
        """执行打断操作：发送 /stop、取消当前请求、停止 TTS"""
        print("\n[打断] 检测到唤醒词，执行打断...")
        # 发送 /stop 命令（异步）
        self.openclaw.send_stop_command()
        # 取消当前请求（同步标记）
        self.openclaw.cancel_current_request()
        # 设置停止标志，用于阻塞等待循环
        self._stop_openclaw_request.set()
        # 立即重置状态，确保可以重新唤醒
        self._is_openclaw_busy = False
        self._is_processing = False
        self.continuous_mode = False
        if hasattr(self, "_waiting_active"):
            self._waiting_active.clear()
        # 停止 TTS 播放
        stop_tts()
        # 记录打断时间，用于防止后续误触发退出检测
        self._last_interrupt_time = time.time()
        print("[打断] 已发出中断信号，状态已重置")

    def _interrupt_openclaw_silent(self):
        """静默中断：仅取消请求和重置状态，不发送 /stop 命令
        用于 exit_standby 等已经明确要退出的场景，避免重复发送 /stop
        """
        self.openclaw.cancel_current_request()
        self._stop_openclaw_request.set()
        self._is_openclaw_busy = False
        self._is_processing = False
        self.continuous_mode = False
        if hasattr(self, "_waiting_active"):
            self._waiting_active.clear()
        stop_tts()
        # 同样记录打断时间，防止误触发退出检测
        self._last_interrupt_time = time.time()

    def _current_lang(self) -> str:
        """当前角色的固定回复语言（Sir 制定）：贾维斯一律英文，林妹妹一律中文。"""
        if self.current_cfg.get("id") == "lin-meimei":
            return "zh"
        return "en"

    def _wake_greeting(self) -> str:
        """本地生成唤醒问候（不经大模型），语言跟随角色。

        林妹妹 → 中文古风；贾维斯 → 英文。

        长会话下大模型可能被历史中文语境带偏回中文，且唤醒时还会自动
        跑工具（查时间/系统状态）拖慢响应。本地按时间段轮换英文问候，
        保证唤醒始终是英文、即时可播。
        """
        if self._current_lang() == "zh":
            return random.choice(
                [
                    "哟，这会子才想起我来，我还以为哥哥早把我给忘了呢。",
                    "哥哥可算来了，妹妹在这儿候了许久了。",
                    "妹妹在呢，哥哥有何吩咐？",
                ]
            )
        hour = time.localtime().tm_hour
        if 5 <= hour < 12:
            period = "morning"
        elif 12 <= hour < 18:
            period = "afternoon"
        else:
            period = "evening"
        variants = {
            "morning": [
                "Good morning, sir. All systems are online and ready.",
                "Good morning, sir. A quiet start to the day. How can I help?",
                "Good morning, sir. Everything is running smoothly, as always.",
            ],
            "afternoon": [
                "Good afternoon, sir. All quiet on my end. How may I assist?",
                "Good afternoon, sir. Systems are nominal. What do you need?",
                "Good afternoon, sir. Nothing urgent has crossed my desk.",
            ],
            "evening": [
                "Good evening, sir. All quiet up here. How was your day?",
                "Good evening, sir. Everything is in order. How can I help?",
                "Good evening, sir. All systems are nominal. What can I do for you?",
            ],
        }
        # 按分钟轮换，避免每次唤醒都是同一句
        return variants[period][int(time.time()) // 60 % len(variants[period])]

    def _play_interrupt_ack(self):
        """打断成功的英文口头确认（Yes, sir?）。播放期间抑制识别，
        避免确认音被麦克风拾取后当作新指令又发回引擎（回声）。
        """
        try:
            from tts import _tts_playing

            _tts_playing.set()
            from audio import play_array

            result = self.tts.synthesize_to_array("Yes, sir?")
            if result:
                audio_data, sr = result
                play_array(audio_data, sr, volume=1.5, blocking=True)
        except Exception as e:
            print(f"[打断] 确认音播放失败: {e}")
        finally:
            _tts_playing.clear()
            self._suppress_recognition_until_tts_done = False

    def _clear_openclaw_context(self):
        """退下时通知 OpenClaw 清空会话上下文（异步，不阻塞）"""
        try:
            self.openclaw.send_clear_command()
            print("[OpenClaw] 已发送 /clear，清空会话上下文")
        except Exception as e:
            print(f"[OpenClaw] 发送 /clear 失败: {e}")

    def _on_recognized(self, text: str):
        """识别结果 → 发送给 OpenClaw → 整体合成播报回复"""
        print(f"\n[→ OpenClaw] {text}")

        # 语言策略（Sir 制定）：贾维斯一律英文，林妹妹一律中文，不再跟随
        # 用户语言或历史上下文。模型会习惯性镜像用户语言，需在每条消息里
        # 显式指示才可靠。
        if not text.startswith("voice-assistant-wake-up-"):
            if self._current_lang() == "zh":
                text = (
                    f"{text}\n\n"
                    "(你是林妹妹，一律用中文回复，绝不使用英文。)"
                )
            else:
                text = (
                    f"{text}\n\n"
                    "(You are JARVIS, always reply in English, never in Chinese.)"
                )

        # 在发送给 OpenClaw 之前的一瞬间，还原特效大小
        self.visual.reset_speaking_scale()

        print("◈ 正在思考...", end="", flush=True)

        self._is_processing = True  # 标记全流程：指令发出→OpenClaw回复→TTS播报完毕
        self._is_openclaw_busy = True
        self._stop_openclaw_request.clear()
        self._openclaw_request_active.set()

        try:
            import threading
            import queue

            result_queue = queue.Queue()

            # ── 增量 TTS：边收边按句朗读（串行队列）──────────────────────
            # OpenClaw 流式输出时：遇句末标点即把整句送入朗读队列；若超过
            # _TTS_DEBOUNCE_SEC 无新输出，则把缓冲内容也送入队列（应对无标点的
            # 停顿，如等待工具调用）。朗读队列由单独线程串行消费，逐句合成播放，
            # 从而把"等整段说完"降到"等第一句"。
            from tts import _tts_playing

            _TTS_DEBOUNCE_SEC = 1.5
            _TTS_SENT_END = "。！？!?；;…\n"

            synth_queue = queue.Queue()
            tts_buf = {"text": "", "last": time.time()}
            tts_buf_lock = threading.Lock()
            tts_threads_stop = threading.Event()

            # ── 合成/播放流水线：多线程并行合成 + 单线程有序播放 ──────────
            # 每个切片按入队顺序分配递增 seq。多个合成线程并行把切片合成成
            # 音频，结果按 seq 存入 results；单个播放线程严格按 seq 0,1,2… 顺序
            # 播放——靠后的切片即便先合成好也要等前面的，保证播报顺序不乱。
            # 好处：合成耗时被并行掉，句与句之间几乎无停顿。
            seq_ctr = {"n": 0}
            results = {}                  # seq -> (audio, sr) | None(失败/跳过)
            results_cond = threading.Condition()
            play_total = {"n": None}      # 生产结束后置为总切片数，播放线程据此收尾

            def _flush_segment(force=False):
                """把缓冲里的完整句子（force 时为剩余全部）按 4 句分批入队合成。"""
                with tts_buf_lock:
                    buf = tts_buf["text"]
                    if not buf:
                        return
                    if force:
                        seg, tts_buf["text"] = buf, ""
                    else:
                        idx = max(
                            (buf.rfind(c) for c in _TTS_SENT_END), default=-1
                        )
                        if idx < 0:
                            return
                        seg, tts_buf["text"] = buf[: idx + 1], buf[idx + 1 :]
                    seg = _clean_for_tts(seg)
                    if not seg.strip():
                        return
                    # 长句/长段落不一次性整段合成：每 4 句切一批。
                    # 在锁内分配 seq 并入队，保证多线程（chunk 回调 + flusher）
                    # 并发调用时切片顺序不乱。
                    for batch in _batch_sentences(seg, _TTS_SENT_END, 4):
                        if not batch.strip():
                            continue
                        seq = seq_ctr["n"]
                        seq_ctr["n"] += 1
                        synth_queue.put((seq, batch))

            def _synth_worker():
                """并行合成：取切片 → 合成 → 按 seq 存结果并通知播放线程。"""
                while True:
                    item = synth_queue.get()
                    if item is None:
                        break
                    seq, text = item
                    result = None
                    if not self._stop_openclaw_request.is_set():
                        result = self.tts.synthesize_to_array(text)
                    with results_cond:
                        results[seq] = result  # 即便失败/跳过也记 None，避免播放线程死等
                        results_cond.notify_all()

            def _play_worker():
                """有序播放：严格按 seq 0,1,2… 顺序，缺哪个等哪个。"""
                from audio import play_array

                next_seq = 0
                while True:
                    with results_cond:
                        while True:
                            if self._stop_openclaw_request.is_set():
                                return
                            if (play_total["n"] is not None
                                    and next_seq >= play_total["n"]):
                                return  # 全部切片已播完
                            if next_seq in results:
                                break
                            results_cond.wait(timeout=0.2)
                        result = results.pop(next_seq)
                    next_seq += 1
                    if not result or self._stop_openclaw_request.is_set():
                        continue
                    audio_data, sr = result
                    _tts_playing.set()
                    # 统一播放出口：重采样到设备原生采样率消除电流杂音，
                    # 打断时立即停掉当前句
                    play_array(
                        audio_data, sr, volume=1.5, blocking=True,
                        stop_check=self._stop_openclaw_request.is_set,
                    )

            def _tts_flusher():
                """监控停顿：缓冲非空且超过 debounce 无新输出则触发朗读。"""
                while not tts_threads_stop.is_set():
                    time.sleep(0.15)
                    if self._stop_openclaw_request.is_set():
                        return
                    with tts_buf_lock:
                        has = bool(tts_buf["text"].strip())
                        idle = time.time() - tts_buf["last"]
                    if has and idle >= _TTS_DEBOUNCE_SEC:
                        _flush_segment(force=True)

            # 合成线程数按设备逻辑核数动态决定（不硬编码）：约半数核、至少 1，
            # 兼顾并行加速与不过度抢占（合成为 CPU 密集，ONNX 内部亦用多线程）。
            num_synth_workers = max(1, (os.cpu_count() or 2) // 2)
            synth_threads = [
                threading.Thread(target=_synth_worker, daemon=True)
                for _ in range(num_synth_workers)
            ]
            play_thread = threading.Thread(target=_play_worker, daemon=True)
            tts_flusher_thread = threading.Thread(target=_tts_flusher, daemon=True)
            for _t in synth_threads:
                _t.start()
            play_thread.start()
            tts_flusher_thread.start()

            def _openclaw_request():
                self._waiting_active = threading.Event()
                self._waiting_active.set()

                def _waiting_sound_loop():
                    while self._waiting_active.is_set():
                        self.jarvis.play_sound("waiting")
                        for _ in range(10):
                            if not self._waiting_active.is_set():
                                return
                            time.sleep(0.3)

                waiting_thread = threading.Thread(
                    target=_waiting_sound_loop, daemon=True
                )
                waiting_thread.start()

                received_chunks = []
                stop_requested = threading.Event()

                def _on_stream_start():
                    if self._stop_openclaw_request.is_set():
                        stop_requested.set()
                        return
                    self._waiting_active.clear()
                    time.sleep(0.05)
                    print("\n[← OpenClaw] ", end="", flush=True)

                def _on_stream_chunk(chunk):
                    if self._stop_openclaw_request.is_set():
                        stop_requested.set()
                        return
                    received_chunks.append(chunk)
                    full_text = "".join(received_chunks)
                    print(chunk, end="", flush=True)
                    self.visual.show_ai_text(full_text)
                    # 累积到朗读缓冲，遇句末标点立即切句入队
                    with tts_buf_lock:
                        tts_buf["text"] += chunk
                        tts_buf["last"] = time.time()
                    _flush_segment(force=False)

                def _on_stream_end():
                    if not stop_requested.is_set():
                        self._waiting_active.clear()

                try:
                    if text.startswith("voice-assistant-wake-up-"):
                        # 唤醒问候本地生成（英文），不经过大模型：长会话下模型
                        # 可能回中文、还会自动跑工具拖慢响应。直接喂给 TTS 流水线。
                        _wake_reply = self._wake_greeting()
                        _on_stream_start()
                        _on_stream_chunk(_wake_reply)
                        _on_stream_end()
                        reply = _wake_reply
                    else:
                        reply = self.openclaw.send_and_wait_stream(
                            text,
                            on_chunk=_on_stream_chunk,
                            on_start=_on_stream_start,
                            on_end=_on_stream_end,
                        )
                    self._waiting_active.clear()
                    waiting_thread.join(timeout=0.5)
                    result_queue.put(("success", reply))
                except Exception as e:
                    self._waiting_active.clear()
                    result_queue.put(("error", str(e)))
                finally:
                    self._is_openclaw_busy = False
                    self._openclaw_request_active.clear()

            request_thread = threading.Thread(target=_openclaw_request, daemon=True)
            request_thread.start()

            while True:
                try:
                    status, data = result_queue.get(timeout=0.5)
                    break
                except queue.Empty:
                    if self._stop_openclaw_request.is_set():
                        self.openclaw.send_stop_command()
                        self.openclaw.cancel_current_request()
                        print("\n[打断] OpenClaw 请求已中断")
                        return

            if status == "success":
                reply = data
                if reply:
                    print()
                    # 流已结束：停止停顿监控，把剩余缓冲全部入队
                    tts_threads_stop.set()
                    if not self._stop_openclaw_request.is_set():
                        _flush_segment(force=True)
                    # 告知播放线程切片总数、唤醒它收尾；停掉各合成线程
                    with results_cond:
                        play_total["n"] = seq_ctr["n"]
                        results_cond.notify_all()
                    for _t in synth_threads:
                        synth_queue.put(None)
                    play_thread.join()

                    # TTS播报结束，检查是否被中断
                    if self._stop_openclaw_request.is_set():
                        print("\n[打断] TTS播报被中断，跳过收尾音效")
                        return

                    print("◈ 继续说吧，我在听着...", flush=True)
                    self.jarvis.play_sound("continue")
                    return
                else:
                    print("\n[← OpenClaw] (无回复)")
                    self.jarvis.on_error("无回复")
            else:
                print(f"[OpenClaw] 异常: {data}")
                self.jarvis.on_error(data)
        finally:
            # 兜底停掉增量 TTS 流水线与残留播放（打断/异常/无回复路径）
            try:
                tts_threads_stop.set()
                # 唤醒播放线程收尾（若未在成功分支设过总数）、停掉合成线程
                with results_cond:
                    if play_total["n"] is None:
                        play_total["n"] = seq_ctr["n"]
                    results_cond.notify_all()
                for _ in range(num_synth_workers):
                    synth_queue.put(None)
                _tts_playing.clear()
            except Exception:
                pass
            self.last_voice_time = time.time()
            self._is_processing = False
            self._is_openclaw_busy = False

    def run(self):
        """运行语音助手"""
        self.jarvis.system_ready()
        try:
            self._process_audio()
        except KeyboardInterrupt:
            print("\n收到中断信号，正在退出...")
            self.stop_event.set()
        finally:
            self.stop()

    def stop(self):
        """停止语音助手"""
        self.stop_event.set()
        try:
            from video_agent.opencut_client import shutdown_opencut
            shutdown_opencut()
        except Exception as e:
            print(f"[Video] OpenCut 进程回收失败: {e}")
        print("语音助手已关闭。")

    def exit_standby(self, instant: bool = False):
        """执行退下操作：从连续对话模式回到待机模式"""
        # 已经处于待机状态，跳过重复退出（防止 TTS 回声反复触发）
        if not self.is_awake and not self.continuous_mode:
            print("[exit_standby] 已在待机状态，跳过")
            return
        print("\n[收到退下信号]")
        # 使用静默中断，避免重复发送 /stop 命令
        self._interrupt_openclaw_silent()
        # self._clear_openclaw_context()
        if hasattr(self, "_waiting_active"):
            self._waiting_active.clear()
        self.jarvis.on_exit()
        self.visual.clear_texts()
        self.visual.hide_effects()
        try:
            from vision import get_vision_manager
            get_vision_manager().set_object_scan(False)
        except Exception as e:
            print(f"[Vision] 退下时关闭扫描失败: {e}")
        self.is_awake = False
        self.continuous_mode = False
        self._verified_speaker_name = None
        self._conv_audio_buffer.clear()
        self._coding_pending_confirm = None  # 退下时清空待确认编码任务
        self._video_pending_confirm = None  # 退下时清空待确认视频任务
        self._mission_step_pending = None  # 退下时清空待确认任务步骤
        play_prebuilt_voice("exit", _random_exit_line())
        while is_tts_playing():
            time.sleep(0.05)
        self._clear_queue()
        # 通知主循环重置 keyword_stream 和 audio_stream
        self._keyword_stream_reset_event.set()
        # 清除停止标志，确保不影响后续唤醒
        self._stop_openclaw_request.clear()
        print("\n已退出监听，等待唤醒词...")

    # ── 地图指令（定位 / 缩放 / 重置）────────────────────────────
    _MAP_RE_ZOOM = re.compile(r"放大地图|缩小地图|地图放大|地图缩小")
    # "关闭地图" 也视为重置：收起定位视图，回到原始大小展示完整球体
    _MAP_RE_RESET = re.compile(
        r"重置地图|恢复地图|地图重置|地图恢复|取消定位|退出定位|关闭地图|收起地图"
    )
    # 口语助词/命令前缀：定位前先剥离，避免被当成地点名（如"定位一下"→"一下"）
    _MAP_RE_CLEAN = re.compile(r"(请|麻烦|帮我|给我|帮我一下|一下)")
    # 地点名提取：贪婪 {2,12} 取尽可能长的地名
    _MAP_RE_LOCATE = re.compile(r"定位(?:到|去)?\s*([\u4e00-\u9fa5A-Za-z]{2,12})")
    # 尾部语气词 / ASR 噪音 / 指令残留，需剥离
    _MAP_CITY_TAIL = re.compile(
        r"(的|好了|好吧|吧|啊|哦|呀|呢|谢谢|感谢|地图|最新|热点|资讯|新闻|NIC)$"
    )
    # 定位窗口内"回声碎片"判定：含地点/语气/指令词，或短中文句
    _MAP_FRAGMENT_RE = re.compile(
        r"定位|地图|放大|缩小|关闭|重置|恢复|取消|深圳|北京|上海|广州|杭州|成都|"
        r"重庆|武汉|西安|南京|天津|苏州|青岛|厦门|长沙|郑州|合肥|昆明|大连|海口|"
        r"哈尔滨|台北|香港|澳门|宝安|南山|福田|龙岗|盐田|罗湖|光明|坪山|龙华|大鹏|好了|NIC|吧|啊|哦|"
        r"呀|呢|谢谢|感谢"
    )
    # 已知城市/片区名：用于从 ASR 乱码中提取真实地名（避免定位误报失败）
    _MAP_CITY_NAMES = (
        "哈尔滨", "乌鲁木齐", "呼和浩特", "石家庄", "郑州", "长春", "沈阳", "济南",
        "南京", "武汉", "成都", "重庆", "西安", "天津", "苏州", "青岛", "厦门",
        "长沙", "杭州", "昆明", "大连", "海口", "合肥", "广州", "深圳", "北京",
        "上海", "台北", "香港", "澳门",
        "宝安", "南山", "福田", "龙岗", "盐田", "罗湖", "光明", "坪山", "龙华", "大鹏",
    )
    # 定位语音回复用英文地名（贾维斯英文口播走 Piper 英音；含中文会切女声）
    _MAP_CITY_EN = {
        "哈尔滨": "Harbin", "乌鲁木齐": "Urumqi", "呼和浩特": "Hohhot",
        "石家庄": "Shijiazhuang", "郑州": "Zhengzhou", "长春": "Changchun",
        "沈阳": "Shenyang", "济南": "Jinan", "南京": "Nanjing", "武汉": "Wuhan",
        "成都": "Chengdu", "重庆": "Chongqing", "西安": "Xi'an", "天津": "Tianjin",
        "苏州": "Suzhou", "青岛": "Qingdao", "厦门": "Xiamen", "长沙": "Changsha",
        "杭州": "Hangzhou", "昆明": "Kunming", "大连": "Dalian", "海口": "Haikou",
        "合肥": "Hefei", "广州": "Guangzhou", "深圳": "Shenzhen", "北京": "Beijing",
        "上海": "Shanghai", "台北": "Taipei", "香港": "Hong Kong", "澳门": "Macau",
        "宝安": "Bao'an", "南山": "Nanshan", "福田": "Futian", "龙岗": "Longgang",
        "盐田": "Yantian", "罗湖": "Luohu", "光明": "Guangming", "坪山": "Pingshan",
        "龙华": "Longhua", "大鹏": "Dapeng",
    }
    # 地图指令状态机：防 ASR 回声/流式重发导致反复定位闪烁、永不退出
    _last_map_norm = ""
    _last_map_ts = 0.0
    _map_locating = False
    _map_locate_deadline = 0.0
    _map_locating_city = ""  # 当前定位的城市（用于识别同城市回声）
    _map_locating_key = ""  # 当前定位城市的比较键（提取最具体城市名）
    _map_located_city = ""  # 最近一次成功定位的城市（用于长时间同城去重）
    _map_located_key = ""
    _map_located_ts = 0.0
    _map_show_user_text = False  # 本次地图指令是否是真指令（回声吞掉时不显示输入框）
    _MAP_LOCATE_TIMEOUT = 45.0  # 定位窗口：期间吞掉回声碎片
    _MAP_DEDUP_TTL = 45.0  # 同指令去重时长（ASR 回声/流式重发持续数十秒）
    _MAP_SAME_CITY_TTL = 120.0  # 成功定位后同城市再触发的最小间隔

    def _map_norm(self, t: str) -> str:
        """归一化地图指令文本（剥离助词/尾部噪音），用于回声去重。"""
        t = self._MAP_RE_CLEAN.sub("", t)
        # 迭代清理尾部语气词/噪音（处理"好了 NIC"这类带空格残留）
        for _ in range(4):
            nxt = self._MAP_CITY_TAIL.sub("", t).strip()
            if nxt == t:
                break
            t = nxt
        return t

    def _map_fragment(self, t: str) -> bool:
        """定位窗口内的回声/碎片判定。"""
        return self._MAP_FRAGMENT_RE.search(t) is not None

    def _map_like(self, t: str) -> bool:
        """流式识别阶段的轻量地图指令预判（避免回声把文字刷进输入框）。"""
        return bool(
            "定位" in t
            or self._MAP_RE_ZOOM.search(t)
            or self._MAP_RE_RESET.search(t)
        )

    # ── 视觉模式（Vision Mode）指令：开启/关闭视觉扫描 ────────
    # 本地拦截、不进大模型（与地图指令同级）；确认口播跟随角色语言
    # （Jarvis 英文 / 林妹妹中文）。防 ASR 回声/流式重发的去重窗口。
    _VISION_DEDUP_TTL = 15.0
    _last_vision_norm = ""
    _last_vision_ts = 0.0

    def _vision_like(self, t: str) -> bool:
        """流式识别阶段的轻量视觉指令预判（避免回声把文字刷进输入框）。"""
        return bool(
            re.search(
                r"(?:开启|启动|打开|进入|开始|关闭|退出|停止|结束)\s*"
                r"(?:视觉扫描|视觉模式|视觉|扫描|模式)"
                r"|扫描(?:一下|这个|那个)?|识别(?:一下|这个|那个)?|这是什么"
                r"|关闭扫描|停止识别|退出扫描|详细介绍一下|详细介绍",
                t,
            )
        )

    def _handle_vision_command(self, text: str) -> bool:
        """识别视觉模式指令（开启/关闭/扫描/识别/详细介绍）：返回 True 表示已消费。"""
        t = (text or "").strip()
        if not t:
            return False
        start = bool(
            re.search(
                r"(?:开启|启动|打开|进入|开始)\s*(?:视觉扫描|视觉模式|视觉|扫描|模式)",
                t,
            )
        )
        stop = bool(
            re.search(
                r"(?:关闭|退出|停止|结束)\s*(?:视觉扫描|视觉模式|视觉|扫描|模式)",
                t,
            )
        )
        scan_on = bool(
            re.search(
                r"扫描(?:一下|这个|那个)\S*$|识别(?:一下|这个|那个)\S*$|这是什么$", t
            )
        )
        scan_off = bool(re.search(r"关闭扫描|停止识别|退出扫描", t))
        describe = bool(re.search(r"详细介绍一下|详细介绍|详细说说", t))
        try:
            from vision import get_vision_manager
            mgr = get_vision_manager()
        except Exception as e:
            print(f"[Vision] 模块加载失败: {e}")
            return False
        if not start and not stop and not scan_on and not scan_off and not describe:
            # 视觉模式激活时，裸"关闭/退出/停止"视为关闭视觉（"结束"是系统退出词，不抢）
            if mgr.is_active() and t in ("关闭", "退出", "停止"):
                stop = True
            else:
                return False
        # 「退出扫描」与通用「退出视觉」重叠：扫描关闭优先（仅停扫描，保留视觉模式）
        if scan_off:
            stop = False
        norm = (
            "scan_on" if scan_on
            else "scan_off" if scan_off
            else "describe" if describe
            else "start" if start
            else "stop"
        )
        now = time.time()
        _diag.info(
            "[Vision] cmd=%r norm=%s start=%s stop=%s scan_on=%s scan_off=%s describe=%s active=%s",
            t, norm, start, stop, scan_on, scan_off, describe, mgr.is_active(),
        )
        # 去重：同一指令 15 秒内重复（ASR 回声/流式重发）→ 忽略但仍消费
        if norm == self._last_vision_norm and now - self._last_vision_ts < self._VISION_DEDUP_TTL:
            print(f"[Vision] 重复指令忽略: {t}")
            return True
        self._last_vision_norm = norm
        self._last_vision_ts = now

        # 物体扫描 / 详细描述（Spatial Vision）
        if describe:
            return self._handle_vision_describe(mgr)
        if scan_off:
            mgr.set_object_scan(False)
            self.visual.send("vision:scan off", quiet=True)
            msg = "Object scan stopped." if self._current_lang() != "zh" else "已停止识别。"
            self.visual.show_ai_text("OBJECT SCAN OFF")
            threading.Thread(target=self._map_speak, args=(msg,), daemon=True).start()
            print("[Vision] 物体扫描关闭指令")
            return True
        if scan_on:
            mgr.on_object = self._on_vision_object
            if not mgr.is_active():
                mgr.start()
            mgr.set_object_scan(True)
            self.visual.send("vision:scan on", quiet=True)
            msg = "Scanning. Show me the object, sir." if self._current_lang() != "zh" else "开始识别，请把物体放到镜头前。"
            self.visual.show_ai_text("OBJECT SCAN ACTIVE")
            threading.Thread(target=self._map_speak, args=(msg,), daemon=True).start()
            print("[Vision] 物体扫描开启指令")
            return True

        if start:
            if mgr.is_active():
                print("[Vision] 已在视觉模式，忽略重复开启")
                return True
            mgr.start()
            msg = "Vision mode activated."
            hud = "VISION MODE ACTIVE"
            print("[Vision] 视觉模式开启指令")
        else:
            if not mgr.is_active():
                print("[Vision] 当前不在视觉模式，忽略关闭")
                return True
            mgr.stop()
            msg = "Vision mode deactivated."
            hud = "VISION MODE OFF"
            print("[Vision] 视觉模式关闭指令")
        # 确认口播跟随角色语言（贾维斯英文 / 林妹妹中文），复用 _map_speak
        # 的播报辅助：播放期间标记处理中、播完清空音频队列，防麦克风回声误识别
        if self._current_lang() == "zh":
            msg = "视觉模式已开启。" if start else "视觉模式已关闭。"
        self.visual.show_ai_text(hud)
        threading.Thread(target=self._map_speak, args=(msg,), daemon=True).start()
        return True

    def _handle_vision_describe(self, mgr) -> bool:
        """“详细介绍一下”：用当前帧调 vision-agent 描述（异步，不阻塞主循环）。"""
        zh = self._current_lang() == "zh"
        if not mgr.is_active():
            msg = "Vision mode is not active. Please start it first." if not zh else "请先开启视觉模式。"
            threading.Thread(target=self._map_speak, args=(msg,), daemon=True).start()
            return True
        frame = mgr.last_frame()
        if not frame:
            msg = "No camera frame available yet." if not zh else "暂时没有画面，请稍后再试。"
            threading.Thread(target=self._map_speak, args=(msg,), daemon=True).start()
            return True

        def _run():
            try:
                from assistants.vision_agent import get_vision_agent

                text = get_vision_agent().describe(frame, mgr.role)
                msg = text if text else ("无法获取更多细节。" if zh else "I couldn't extract more details.")
                self.visual.show_ai_text(msg)
                threading.Thread(target=self._map_speak, args=(msg,), daemon=True).start()
            except Exception as e:
                print(f"[Vision] 详细描述失败: {e}")

        threading.Thread(target=_run, daemon=True).start()
        return True

    def _on_vision_object(self, result: dict):
        """物体识别结果 → 角色语言口播（识别线程调用，另起线程播报）。"""
        try:
            zh = self._current_lang() == "zh"
            label = result.get("label") or "Unknown"
            conf = (result.get("confidence") or 0.0) * 100
            if zh:
                msg = f"识别到：{label}，置信度 {int(conf)}%。"
            else:
                msg = f"Object identified: {label}. Confidence {int(conf)} percent."
            self.visual.show_ai_text(msg)
            threading.Thread(target=self._map_speak, args=(msg,), daemon=True).start()
        except Exception as e:
            print(f"[Vision] 识别口播失败: {e}")

    # ── 电脑控制（Computer Control）指令 ────────────────────
    # 本地能力拦截（与地图/视觉同级）：打开/关闭/切换应用、输入文字、按键、
    # 语义点击、截图、查看屏幕、列出应用；确认口播跟随角色语言（贾维斯英文/林妹妹中文）。
    # 防 ASR 回声/流式重发的去重窗口（同视觉模式）。
    _COMPUTER_DEDUP_TTL = 15.0
    _last_computer_norm = ""
    _last_computer_ts = 0.0
    _COMPUTER_LIKE_RE = re.compile(
        r"^(?:(?:请|帮我|麻烦|给我)?(?:打开一下|帮我打开|打开|开启|启动|运行|关闭|关掉|"
        r"关一下|退出|结束|切换到|切换|切到|输入|打字|按下|按一下|快捷键|点击|点一下|单击|"
        r"双击|截屏|截图|查看屏幕|看屏幕|屏幕上有什么|现在开着什么|打开的应用|哪些应用在运行)"
        r"\s*.{0,40}"
        r"|(?:请|帮我|麻烦)?(?:把|将).{1,20}(?:打开|关闭|关掉|启动|运行|切到|切换到)"
        r"|(?:please |plz )?(?:open|launch|start|run|close|quit|switch to|switch|type|press|"
        r"click|double click|screenshot|take a screenshot|describe screen|list apps)"
        r"\s*.{0,40})$",
        re.I,
    )

    def _computer_like(self, t: str) -> bool:
        """流式识别阶段的电脑指令预判（避免回声把文字刷进输入框）。"""
        return bool(self._COMPUTER_LIKE_RE.match((t or "").strip()))

    def _handle_computer_command(self, text: str) -> bool:
        """识别电脑控制指令：返回 True 表示已消费，不进大模型。"""
        t = (text or "").strip()
        if not t or not self._computer_like(t):
            return False
        now = time.time()
        norm = re.sub(r"\s+", "", t).lower()
        if (
            norm == self._last_computer_norm
            and now - self._last_computer_ts < self._COMPUTER_DEDUP_TTL
        ):
            print(f"[Computer] 重复指令忽略: {t}")
            return True
        try:
            from computer import get_computer_agent

            agent = get_computer_agent()
            if agent.brain.bridge is None and getattr(self, "openclaw", None) is not None:
                agent.bind_bridge(self.openclaw)
            if not agent.handle(t):
                return False
        except Exception as e:
            print(f"[Computer] 模块加载失败: {e}")
            return False
        self._last_computer_norm = norm
        self._last_computer_ts = now
        # 异步执行完成 → 角色语言确认口播 + overlay 文本（不阻塞语音主循环）
        future = agent.executor.last_future()
        if future is not None:

            def _cb(f):
                try:
                    if not f.cancelled():
                        self._computer_speak(f.result())
                except Exception as e:
                    print(f"[Computer] 结果回调失败: {e}")

            future.add_done_callback(_cb)
        return True

    def _computer_speak(self, result: dict):
        """电脑操作结果确认（角色语言）+ overlay 文本。"""
        try:
            zh = self._current_lang() == "zh"
            action = result.get("action", "")
            ok = result.get("ok")
            target = result.get("target", "") or ""
            display = result.get("display") or target
            apps = result.get("apps")
            detail = result.get("message") or result.get("detail") or ""
            if not ok:
                msg = f"操作失败：{detail}" if zh else f"I couldn't complete that. {detail}"
            elif action == "open_app":
                msg = f"已打开 {target}。" if zh else f"Opened {display}."
            elif action == "close_app":
                msg = f"已关闭 {target}。" if zh else f"Closed {display}."
            elif action == "switch_app":
                msg = f"已切换到 {target}。" if zh else f"Switched to {display}."
            elif action == "type_text":
                msg = f"已输入 {target}。" if zh else "Done. Text entered."
            elif action == "press_keys":
                msg = f"已按下 {target}。" if zh else "Key command executed."
            elif action == "click_element":
                msg = f"已点击 {target}。" if zh else f"Clicked {target}."
            elif action == "double_click_element":
                msg = f"已双击 {target}。" if zh else f"Double-clicked {target}."
            elif action == "take_screenshot":
                msg = "截图完成。" if zh else "Screenshot taken."
            elif action == "get_screen_state":
                msg = detail if zh else "Screen captured and analyzed. I can describe what is on screen."
            elif action == "list_apps":
                msg = (
                    "正在运行：" + "、".join(apps or [])
                    if zh
                    else "Running: " + ", ".join(apps or [])
                )
            else:
                msg = detail if zh else "Done."
            overlay_msg = detail if detail else msg
            try:
                self.visual.show_ai_text(overlay_msg)
            except Exception as e:
                print(f"[Computer] overlay 文本失败: {e}")
            threading.Thread(target=self._map_speak, args=(msg,), daemon=True).start()
        except Exception as e:
            print(f"[Computer] 确认口播失败: {e}")

    # ── Coding Agent（Codex CLI 编码能力）指令 ────────────────
    # 本地拦截（与地图/视觉/电脑同级）：分析/审查/测试/修改/git 任务，不进大模型；
    # modify/commit/push 需语音确认（60s 超时自动拒绝）。确认口播跟随角色语言
    # （贾维斯英文 / 林妹妹中文）。防 ASR 回声/流式重发的去重窗口同其他模块。
    _CODING_DEDUP_TTL = 15.0
    _last_coding_norm = ""
    _last_coding_ts = 0.0
    _coding_pending_confirm = None  # {confirm_id, mode, project, task, deadline}
    # 编码指令预判：动词 + 编码域目标词（避免把普通聊天误判成编码任务）
    _CODING_LIKE_RE = re.compile(
        r"^(?:(?:请|帮我|麻烦|给我|帮)?"
        r"(?:分析|看看|审查|评审|检查|优化|修改|实现|增加|添加|重构|修复|改造|运行|跑|执行)"
        r"(?:一下|一遍|下)?\s*"
        r"(?:这个|一下|当前|我的)?\s*"
        r"[\w\-_.]{0,16}\s*"
        r"(?:项目|代码|仓库|工程|测试|代码库|功能|页面|接口|配置|文件|bug|昨天|提交)"
        r"\s*.{0,40}"
        r"|(?:git\s+(?:status|log|diff|commit|push)|提交记录|项目状态|工作区状态|查看状态|"
        r"提交(?:一下)?(?:代码|改动)?|推送(?:代码|一下)?)"
        r"|(?:切换到|切到|切到一下)\s*[\w\-_.]{1,24}\s*(?:项目|仓库|工程)"
        r"|(?:please |plz )?(?:analyze|review|optimize|improve|implement|add|fix|refactor|"
        r"build|run tests?|describe this project|what does this project)"
        r"\s*.{0,40})$",
        re.I,
    )
    _CODING_YES_RE = re.compile(
        r"^(?:确认|确认执行|同意|同意执行|可以|可以执行|执行|批准|好的|行|没问题|"
        r"yes|ok|okay|go ahead|approve|confirm|do it)$",
        re.I,
    )
    _CODING_NO_RE = re.compile(
        r"^(?:取消|取消执行|拒绝|不要|不要执行|算了|不用了|不了|停下|"
        r"no|nope|cancel|deny|stop|abort)$",
        re.I,
    )

    # ── Mission Control（任务编排）──────────────────────────
    _MISSION_DEDUP_TTL = 15.0
    _last_mission_norm = ""
    _last_mission_ts = 0.0
    _mission_step_pending = None   # 当前等待确认的步骤 id
    _mission_step_mission = None   # 当前等待确认步骤所属 mission id
    _mission_bound = False         # 回调是否已绑定
    _MISSION_LIKE_RE = re.compile(
        r"(?:创建|开始|安排|规划|制定|执行|做|建|设置)(?:一下)?\s*(?:一个)?\s*"
        r"(?:任务|目标|计划)"
        r"|(?:规划|计划|安排|制定|执行)(?:一下)?\s*[::：]"
        r"|(?:任务|目标|计划)\s*[::：]"
        r"|帮我(?:完成|处理|搞定|做|实现|执行).{2,80}(?:并|然后|再|以及|且)"
        r"|(?:create|start|plan|begin|execute)\s+(?:a\s+)?(?:mission|task|plan)"
        r"|(?:mission|task|plan|goal)\s*[:：]",
        re.I,
    )
    _MISSION_YES_RE = re.compile(
        r"^(?:确认|确认执行|确认任务|同意|同意执行|可以|可以执行|执行|批准|好的|行|没问题|"
        r"开始|开始吧|开始执行|执行吧|ok|okay|go ahead|approve|confirm|do it|sure|yes)"
        r"(?:任务|吧|了|的)?$",
        re.I,
    )
    _MISSION_NO_RE = re.compile(
        r"^(?:取消|取消任务|拒绝|不要|不要执行|算了|不用了|不了|停下|停止|"
        r"no|nope|cancel|deny|stop|abort)(?:任务|吧|了|的)?$",
        re.I,
    )
    _MISSION_PAUSE_RE = re.compile(r"^(?:暂停|先暂停|pause)(?:任务|一下|吧|了)?$", re.I)
    _MISSION_RESUME_RE = re.compile(r"^(?:继续|继续执行|接着|resume)(?:任务|吧|了|的)?$", re.I)
    _MISSION_SKIP_RE = re.compile(
        r"^(?:跳过|跳过这一步|跳过这个步骤|跳过下一步|skip)(?:吧|了)?$", re.I
    )
    _MISSION_STATUS_RE = re.compile(
        r"^(?:任务进度|任务状态|任务怎么样|进度|汇报进度|mission status|mission progress)"
        r"(?:如何|怎样|怎么样|如何了|了)?$",
        re.I,
    )

    def _coding_like(self, t: str) -> bool:
        """流式识别阶段的编码指令预判（避免回声把文字刷进输入框）。"""
        return bool(self._CODING_LIKE_RE.match((t or "").strip()))

    def _handle_coding_command(self, text: str) -> bool:
        """识别编码指令：返回 True 表示已消费，不进大模型。"""
        t = (text or "").strip()
        if not t or not self._coding_like(t):
            return False
        now = time.time()
        norm = re.sub(r"\s+", "", t).lower()
        if (
            norm == self._last_coding_norm
            and now - self._last_coding_ts < self._CODING_DEDUP_TTL
        ):
            print(f"[Coding] 重复指令忽略: {t}")
            return True
        try:
            from coding_agent import get_coding_agent

            agent = get_coding_agent()
            res = agent.handle(t)
        except Exception as e:
            print(f"[Coding] 模块加载失败: {e}")
            return False
        if not res:
            return False
        self._last_coding_norm = norm
        self._last_coding_ts = now
        if isinstance(res, dict):
            if res.get("status") == "waiting_confirmation":
                pending = agent.pending_confirmations()
                if pending:
                    last = pending[-1]
                    self._coding_pending_confirm = {
                        "confirm_id": last["confirm_id"],
                        "mode": last["mode"],
                        "project": last["project"],
                        "task": last["task"],
                        "deadline": time.time() + last["remaining"],
                    }
                    self._ask_coding_confirm()
            else:
                # 黑名单拒绝 / 项目切换等立即结果 → 直接口播
                self._coding_speak(res)
            return True
        res.add_done_callback(self._coding_done_cb)
        return True

    def _handle_coding_confirm(self, text: str) -> bool:
        """处理待确认编码任务的语音答复：确认/取消；超时自动拒绝。"""
        p = self._coding_pending_confirm
        if not p:
            return False
        t = (text or "").strip()
        if not t:
            return False
        expired = (p["deadline"] - time.time()) <= 0
        yes = bool(self._CODING_YES_RE.match(t))
        no = bool(self._CODING_NO_RE.match(t))
        if not yes and not no:
            if expired:
                # 超时静默清理，不打断当前话术
                self._coding_pending_confirm = None
                try:
                    from coding_agent import get_coding_agent

                    get_coding_agent().confirm(p["confirm_id"], False)
                except Exception as e:
                    print(f"[Coding] 超时清理失败: {e}")
            return False
        self._coding_pending_confirm = None
        try:
            from coding_agent import get_coding_agent

            res = get_coding_agent().confirm(p["confirm_id"], yes)
            if hasattr(res, "add_done_callback"):
                res.add_done_callback(self._coding_done_cb)
        except Exception as e:
            print(f"[Coding] 确认回调失败: {e}")
        self._coding_speak_confirm(expired=expired, approved=yes)
        return True

    def _ask_coding_confirm(self):
        """编码任务需确认：口播确认请求（角色语言）+ overlay 文本。"""
        zh = self._current_lang() == "zh"
        if zh:
            msg = "这个任务需要修改代码，是否确认执行？"
        else:
            msg = "This task will modify code. Shall I proceed, sir?"
        self.visual.show_ai_text(msg)
        threading.Thread(target=self._map_speak, args=(msg,), daemon=True).start()

    def _coding_speak_confirm(self, expired: bool = False, approved: bool = True):
        """确认答复口播（角色语言）。"""
        zh = self._current_lang() == "zh"
        if expired:
            msg = "Confirmation timed out. Task cancelled." if not zh else "确认超时，任务已取消。"
        elif approved:
            msg = "Understood. Running the task now, sir." if not zh else "好的，马上执行。"
        else:
            msg = "Task cancelled." if not zh else "已取消。"
        self.visual.show_ai_text(msg)
        threading.Thread(target=self._map_speak, args=(msg,), daemon=True).start()

    def _coding_done_cb(self, f):
        """编码任务异步完成 → 口播结果（角色语言）。"""
        try:
            if not f.cancelled():
                self._coding_speak(f.result())
        except Exception as e:
            print(f"[Coding] 结果回调失败: {e}")

    def _coding_speak(self, result: dict):
        """编码任务结果口播（角色语言）+ overlay 文本。"""
        try:
            zh = self._current_lang() == "zh"
            status = result.get("status", "")
            summary = (result.get("summary", "") or "").strip()
            if status == "success":
                if summary:
                    msg = summary if zh else f"Done. {summary}"
                else:
                    msg = "任务已完成。" if zh else "Done."
            elif status == "denied":
                msg = summary if zh else "Task denied."
            elif status == "cancelled":
                msg = "Task cancelled." if not zh else "任务已取消。"
            elif status == "failed":
                msg = f"Failed. {summary}" if not zh else f"任务失败：{summary}"
            else:
                msg = summary or ("Done." if not zh else "已完成。")
            if len(msg) > 200:
                msg = msg[:200]
            overlay_msg = msg
            try:
                self.visual.show_ai_text(overlay_msg)
            except Exception as e:
                print(f"[Coding] overlay 文本失败: {e}")
            threading.Thread(target=self._map_speak, args=(msg,), daemon=True).start()
        except Exception as e:
            print(f"[Coding] 结果口播失败: {e}")

    # ── Video Agent（OpenCut AI 视频制作）指令 ────────────────
    # 本地拦截（与地图/视觉/电脑/编码同级）：制作视频/剪辑素材/渲染项目/
    # 进度查询/取消任务，不进大模型；generate/render 需语音确认（60s 超时
    # 自动拒绝）。确认口播跟随角色语言。防回声去重窗口同其他模块。
    _VIDEO_DEDUP_TTL = 15.0
    _last_video_norm = ""
    _last_video_ts = 0.0
    _video_pending_confirm = None  # {confirm_id, mode, project, task, deadline}
    # 视频指令预判：动词 + 视频域目标词（避免把普通聊天误判成视频任务）
    _VIDEO_LIKE_RE = re.compile(
        r"^(?:(?:请|帮我|麻烦|给我|帮)?"
        r"(?:制作|生成|创建|做一个|做|剪|剪辑|剪一下|剪个|编辑|修剪|渲染|导出|"
        r"make|create|generate|render|export|cut|trim|edit)"
        r"(?:一下|个|一个)?\s*"
        r"(?:这个|那个|我的|当前)?\s*[\w\-_.]{0,16}\s*"
        r"(?:视频|短视频|宣传片|vlog|录像|素材|时间线|video|clip|footage|movie|project)"
        r"\s*.{0,50}"
        r"|(?:视频|渲染|剪辑)\s*(?:进度|状态|好了吗|完成了吗|完事了吗|完了吗|"
        r"怎么样了|进行到哪|status|progress|is it done)"
        r"|(?:停止|取消|终止|停掉)\s*(?:渲染|视频|剪辑|任务)"
        r"|(?:用|把|对)\s*.{0,40}(?:视频|素材|录像)\s*(?:剪|剪辑|做成视频|trim|cut)"
        r"|(?:ai\s*(?:video|clip|movie)|facecam|上传素材))$",
        re.I,
    )
    _VIDEO_YES_RE = re.compile(
        r"^(?:确认|确认执行|同意|同意执行|可以|可以执行|执行|批准|好的|行|没问题|"
        r"yes|ok|okay|go ahead|approve|confirm|do it)$",
        re.I,
    )
    _VIDEO_NO_RE = re.compile(
        r"^(?:取消|取消执行|拒绝|不要|不要执行|算了|不用了|不了|停下|"
        r"no|nope|cancel|deny|stop|abort)$",
        re.I,
    )

    def _video_like(self, t: str) -> bool:
        """流式识别阶段的视频指令预判（避免回声把文字刷进输入框）。"""
        return bool(self._VIDEO_LIKE_RE.match((t or "").strip()))

    def _handle_video_command(self, text: str) -> bool:
        """识别视频指令：返回 True 表示已消费，不进大模型。"""
        t = (text or "").strip()
        if not t or not self._video_like(t):
            return False
        now = time.time()
        norm = re.sub(r"\s+", "", t).lower()
        if (
            norm == self._last_video_norm
            and now - self._last_video_ts < self._VIDEO_DEDUP_TTL
        ):
            print(f"[Video] 重复指令忽略: {t}")
            return True
        try:
            from video_agent import get_video_agent

            agent = get_video_agent()
            res = agent.handle(t)
        except Exception as e:
            print(f"[Video] 模块加载失败: {e}")
            return False
        if not res:
            return False
        self._last_video_norm = norm
        self._last_video_ts = now
        if isinstance(res, dict):
            if res.get("status") == "waiting_confirmation":
                pending = agent.pending_confirmations()
                if pending:
                    last = pending[-1]
                    self._video_pending_confirm = {
                        "confirm_id": last["confirm_id"],
                        "mode": last["mode"],
                        "project": last["project"],
                        "task": last["task"],
                        "deadline": time.time() + last["remaining"],
                    }
                    self._ask_video_confirm()
            else:
                # 黑名单拒绝 / 进度 / 取消等立即结果 → 直接口播
                self._video_speak(res)
            return True
        res.add_done_callback(self._video_done_cb)
        return True

    def _handle_video_confirm(self, text: str) -> bool:
        """处理待确认视频任务的语音答复：确认/取消；超时自动拒绝。"""
        p = self._video_pending_confirm
        if not p:
            return False
        t = (text or "").strip()
        if not t:
            return False
        expired = (p["deadline"] - time.time()) <= 0
        yes = bool(self._VIDEO_YES_RE.match(t))
        no = bool(self._VIDEO_NO_RE.match(t))
        if not yes and not no:
            if expired:
                # 超时静默清理，不打断当前话术
                self._video_pending_confirm = None
                try:
                    from video_agent import get_video_agent

                    get_video_agent().confirm(p["confirm_id"], False)
                except Exception as e:
                    print(f"[Video] 超时清理失败: {e}")
            return False
        self._video_pending_confirm = None
        try:
            from video_agent import get_video_agent

            res = get_video_agent().confirm(p["confirm_id"], yes)
            if hasattr(res, "add_done_callback"):
                res.add_done_callback(self._video_done_cb)
        except Exception as e:
            print(f"[Video] 确认回调失败: {e}")
        self._video_speak_confirm(expired=expired, approved=yes)
        return True

    def _ask_video_confirm(self):
        """视频任务需确认：口播确认请求（角色语言）+ overlay 文本。"""
        zh = self._current_lang() == "zh"
        if zh:
            msg = "视频渲染需要一些时间，是否确认执行？"
        else:
            msg = "Rendering will take a while, sir. Shall I proceed?"
        self.visual.show_ai_text(msg)
        threading.Thread(target=self._map_speak, args=(msg,), daemon=True).start()

    def _video_speak_confirm(self, expired: bool = False, approved: bool = True):
        """确认答复口播（角色语言）。"""
        zh = self._current_lang() == "zh"
        if expired:
            msg = "Confirmation timed out. Task cancelled." if not zh else "确认超时，任务已取消。"
        elif approved:
            msg = "Understood. Rendering started, sir." if not zh else "好的，开始渲染。"
        else:
            msg = "Task cancelled." if not zh else "已取消。"
        self.visual.show_ai_text(msg)
        threading.Thread(target=self._map_speak, args=(msg,), daemon=True).start()

    def _video_done_cb(self, f):
        """视频任务异步完成 → 口播结果（角色语言）。"""
        try:
            if not f.cancelled():
                self._video_speak(f.result())
        except Exception as e:
            print(f"[Video] 结果回调失败: {e}")

    def _video_speak(self, result: dict):
        """视频任务结果口播（角色语言）+ overlay 文本。"""
        try:
            zh = self._current_lang() == "zh"
            status = result.get("status", "")
            summary = (result.get("summary", "") or "").strip()
            if status == "success":
                if summary:
                    msg = summary if zh else f"Done. {summary}"
                else:
                    msg = "视频已完成。" if zh else "Video done."
            elif status == "denied":
                msg = summary if zh else "Task denied."
            elif status == "cancelled":
                msg = "Task cancelled." if not zh else "任务已取消。"
            elif status == "failed":
                msg = f"Failed. {summary}" if not zh else f"任务失败：{summary}"
            else:
                msg = summary or ("Done." if not zh else "已完成。")
            if len(msg) > 220:
                msg = msg[:220]
            overlay_msg = msg
            try:
                self.visual.show_ai_text(overlay_msg)
            except Exception as e:
                print(f"[Video] overlay 文本失败: {e}")
            threading.Thread(target=self._map_speak, args=(msg,), daemon=True).start()
        except Exception as e:
            print(f"[Video] 结果口播失败: {e}")

    # ── Short Drama（短剧剪辑模式）语音接入 ─────────────────
    # 本地拦截（与地图/视觉/视频/编码同级）：短剧剪辑 → 需求收集 → 剧情规划 →
    # 单集剧本 → 镜头 Prompt，全程语音确认（60s 超时）；生成类后台执行。
    _DRAMA_DEDUP_TTL = 15.0
    _last_drama_norm = ""
    _last_drama_ts = 0.0
    # 入口类指令（无项目时也消费）；其余分集/人物/提示词指令需短剧模式内消费
    _DRAMA_ENTER_RE = re.compile(
        r"(?:短剧剪辑|短剧模式|开启短剧|进入短剧|开始短剧|做个短剧|做短剧|"
        r"制作短剧|拍个短剧|拍短剧|short\s*drama|drama\s*mode|start\s*drama|"
        r"退出短剧|关闭短剧|结束短剧|查看短剧进度|短剧进度|短剧到哪|暂停短剧|"
        r"继续短剧|恢复短剧)", re.I
    )
    _DRAMA_LIKE_RE = re.compile(
        r"(?:短剧|短剧剪辑|短剧模式|开启短剧|进入短剧|查看短剧进度|短剧进度|"
        r"短剧到哪|重新规划剧情|重新设计|修改人物|改人物|"
        r"把[^。\n]{0,20}(?:改成|换成|变成)|"
        r"(?:查看|看看|看下|读一下)\s*(?:第)?\s*[\d一二两三四五六七八九十]+\s*集|"
        r"(?:重写|重新写|重做)\s*第?\s*[\d一二两三四五六七八九十]+\s*集|"
        r"第\s*[\d一二两三四五六七八九十]+\s*集(?:重写|重新写|重做)|"
        r"(?:生成|做|出)?\s*第?\s*[\d一二两三四五六七八九十]+\s*集?(?:的)?"
        r"(?:镜头|分镜|提示词|prompt|prompts)|"
        r"(?:开始)?(?:制作|做|开拍)\s*第?\s*[\d一二两三四五六七八九十]+\s*集|"
        r"用\s*ai\s*(?:制作|做)|ai\s*制作|开始制作|停止制作|停止渲染|取消制作|"
        r"(?:制作|做|渲染)\s*(?:全部|所有|全部集|所有集)|全部制作|"
        r"进入下一集|重新剪辑|重剪|暂停短剧|继续短剧|恢复短剧|"
        r"short\s*drama|drama\s*mode|drama\s*status|exit\s*drama|close\s*drama)",
        re.I,
    )
    _DRAMA_YES_RE = re.compile(
        r"^(?:确认|好的|可以|嗯|对|同意|行|好|是|确认继续|继续吧|ok|yes|yep|sure|"
        r"go ahead|confirmed)$",
        re.I,
    )
    _DRAMA_NO_RE = re.compile(
        r"^(?:取消|算了|不用|不了|不要|不行|否|不对|no|cancel|never\s*mind|nope)$",
        re.I,
    )

    def _drama_like(self, t: str) -> bool:
        """流式识别阶段的短剧指令预判（避免回声把文字刷进输入框）。"""
        return bool(self._DRAMA_LIKE_RE.search((t or "").strip()))

    def _handle_drama_command(self, text: str) -> bool:
        """识别短剧指令：返回 True 表示已消费，不进大模型。"""
        t = (text or "").strip()
        if not t or not self._drama_like(t):
            return False
        now = time.time()
        norm = re.sub(r"\s+", "", t).lower()
        if (
            norm == self._last_drama_norm
            and now - self._last_drama_ts < self._DRAMA_DEDUP_TTL
        ):
            print(f"[Drama] 重复指令忽略: {t}")
            return True
        try:
            from drama_agent import get_drama_agent

            agent = get_drama_agent()
            self._bind_drama_callbacks(agent)
            # 没有短剧项目时，只消费入口/状态/暂停类指令，避免误吞普通聊天
            # （如「推荐一部短剧给我」「查看第一集」这类普通语句）
            if agent.current_project is None and not self._DRAMA_ENTER_RE.search(t):
                return False
            role = self.current_cfg.get("id", "jarvis") if self.current_cfg else "jarvis"
            res = agent.handle(t, role=role)
        except Exception as e:
            print(f"[Drama] 模块加载失败: {e}")
            return False
        if res is False:
            return False
        self._last_drama_norm = norm
        self._last_drama_ts = now
        self._drama_speak(res)
        return True

    def _handle_drama_confirm(self, text: str) -> bool:
        """处理短剧待确认步骤的语音答复：确认/取消；无待确认不消费。"""
        t = (text or "").strip()
        if not t:
            return False
        try:
            from drama_agent import get_drama_agent

            agent = get_drama_agent()
            self._bind_drama_callbacks(agent)
        except Exception:
            return False
        project = agent.current_project
        if project is None:
            return False
        if agent._gate.pending() is None:
            return False
        yes = bool(self._DRAMA_YES_RE.match(t))
        no = bool(self._DRAMA_NO_RE.match(t))
        if not yes and not no:
            return False
        res = agent._confirm(project, yes)
        if not isinstance(res, dict):
            return False
        self._drama_speak(res)
        return True

    def _bind_drama_callbacks(self, agent):
        agent.on_message = self._drama_on_message
        agent.on_confirm_request = self._drama_on_confirm
        agent.on_project_update = self._drama_push_status

    def _drama_on_message(self, payload: dict):
        """生成完成回调：口播 + overlay + 推送状态。"""
        try:
            msg = (payload.get("message") or "").strip()
            if not msg:
                return
            hud = payload.get("hud")
            self.visual.show_ai_text(hud if hud else msg)
            self._drama_push_status(payload.get("project"))
            threading.Thread(target=self._map_speak, args=(msg,), daemon=True).start()
        except Exception as e:
            print(f"[Drama] on_message 回调异常: {e}")

    def _drama_on_confirm(self, project_id: str, phase: str, summary: str):
        """确认请求：口播（跟随角色语言）+ overlay。"""
        zh = self._current_lang() == "zh"
        head = "请确认：" if zh else "Awaiting your confirmation, sir: "
        msg = f"{head}{summary[:140]}"
        self.visual.show_ai_text(msg)
        threading.Thread(target=self._map_speak, args=(msg,), daemon=True).start()

    def _drama_push_status(self, project_dict):
        """推送 drama:status <json> 给 Flutter overlay。"""
        try:
            if not project_dict:
                return
            payload = json.dumps(project_dict, ensure_ascii=False)
            self.visual.send(f"drama:status {payload}")
        except Exception as e:
            print(f"[Drama] push status 异常: {e}")

    def _drama_speak(self, res: dict):
        """短剧立即结果口播（跟随角色语言）+ overlay。"""
        try:
            zh = self._current_lang() == "zh"
            status = res.get("status", "")
            msg = (res.get("message") or "").strip()
            en_heads = {
                "collecting": "Short drama mode is on. Please tell me the theme, episode count and length per episode, e.g. a 10-episode urban drama, one minute each.",
                "planning": "Planning the story now, sir. One moment.",
                "writing": "Writing the episode script now, sir.",
                "prompting": "Generating shot prompts now, sir.",
                "busy": "Still generating, sir. Please wait a moment.",
                "expired": "Confirmation timed out. Task cancelled.",
                "cancelled": "Cancelled.",
                "no_pending": "No step is waiting for confirmation.",
                "completed": "All episodes are planned. Video generation connects in phase two.",
                "producing": "Rendering started, sir. I will report when done.",
                "phase2": "Production connects in phase two, sir. Script and prompts are ready.",
                "exit": "Short drama mode off.",
                "idle": "No drama project yet, sir. Say short drama to start.",
                "unhandled": "Sorry, I did not get that.",
            }
            if not zh:
                head = en_heads.get(status)
                if head:
                    msg = head
                elif msg:
                    msg = f"Done. {msg}"
            if len(msg) > 220:
                msg = msg[:220]
            self.visual.show_ai_text(msg)
            threading.Thread(target=self._map_speak, args=(msg,), daemon=True).start()
        except Exception as e:
            print(f"[Drama] 结果口播失败: {e}")

    # ── Mission Control 语音接入 ──────────────────────────
    def _mission_like(self, t: str) -> bool:
        """流式识别阶段的任务指令预判（避免回声把文字刷进输入框）。"""
        return bool(self._MISSION_LIKE_RE.search((t or "").strip()))

    def _mission_goal(self, t: str) -> str:
        """从触发语句中剥离任务壳子，提取目标文本。"""
        g = (t or "").strip()
        for pat in (
            r"^(?:请|麻烦|帮我|可以)?\s*(?:创建|开始|安排|规划|制定|执行|做|建|设置)"
            r"(?:一下)?\s*(?:一个)?\s*(?:任务|目标|计划)\s*[::：]?\s*",
            r"^(?:请|麻烦|帮我|可以)?\s*(?:规划|计划|安排|制定|执行)(?:一下)?\s*[::：]?\s*",
            r"^(?:create|start|plan|begin|execute)\s+(?:a\s+)?"
            r"(?:mission|task|plan)\s*[:：]?\s*",
            r"^(?:mission|task|plan|goal)\s*[:：]\s*",
            r"^帮我(?:完成|处理|搞定|做|实现|执行)\s*",
        ):
            g = re.sub(pat, "", g, flags=re.I)
        g = g.strip()
        return g[:300] or (t or "").strip()[:300]

    def _step_label(self, step) -> str:
        """步骤的人类可读标签（口播/HUD 用）。"""
        if isinstance(step, dict):
            agent, action = step.get("agent", ""), step.get("action", "")
        else:
            agent, action = step.agent, step.action
        if agent == "coding":
            return {
                "analyze": "Analyze project", "review": "Code review",
                "test": "Run tests", "modify": "Modify code",
                "git": "Git operation",
            }.get(action, action)
        if agent == "computer":
            return {
                "open_app": "Open app", "close_app": "Close app",
                "switch_app": "Switch app", "type_text": "Type text",
                "press_keys": "Press keys", "click_element": "Click element",
                "take_screenshot": "Take screenshot",
                "get_screen_state": "Describe screen", "list_apps": "List apps",
            }.get(action, action)
        if agent == "llm":
            return "Text task"
        if agent == "video":
            return {
                "clip": "Clip video", "generate": "Generate video",
                "render": "Render video", "export": "Export video",
                "status": "Video status",
            }.get(action, action)
        return f"{agent}.{action}"

    def _bind_mission_callbacks(self, agent):
        if self._mission_bound:
            return
        agent.on_plan = self._mission_on_plan
        agent.on_confirm_request = self._mission_on_confirm_request
        agent.on_step_done = self._mission_on_step_done
        agent.on_mission_done = self._mission_on_mission_done
        self._mission_bound = True

    def _mission_speak(self, msg: str, hud: str = None):
        """角色语言口播 + overlay 文本（防回声走 _map_speak）。"""
        self.visual.show_ai_text(hud if hud else msg)
        threading.Thread(target=self._map_speak, args=(msg,), daemon=True).start()

    def _handle_mission_command(self, text: str) -> bool:
        """识别任务目标指令：规划 → 展示计划 → 等待确认。返回 True 表示已消费。"""
        t = (text or "").strip()
        if not t or not self._mission_like(t):
            return False
        now = time.time()
        norm = re.sub(r"\s+", "", t).lower()
        if (
            norm == self._last_mission_norm
            and now - self._last_mission_ts < self._MISSION_DEDUP_TTL
        ):
            print(f"[Mission] 重复指令忽略: {t}")
            return True
        try:
            from mission_control import get_mission_agent

            agent = get_mission_agent()
            self._bind_mission_callbacks(agent)
            goal = self._mission_goal(t)
            role = self.current_cfg.get("id", "jarvis") if self.current_cfg else "jarvis"
            res = agent.plan_and_request(goal, role)
        except Exception as e:
            print(f"[Mission] 模块加载失败: {e}")
            return False
        self._last_mission_norm = norm
        self._last_mission_ts = now
        if not res.get("ok"):
            msg = res.get("message") or "无法规划该目标"
            zh = self._current_lang() == "zh"
            self._mission_speak(
                msg if not zh else "抱歉，我无法把这个目标拆解成可执行步骤。",
                hud="MISSION PLAN FAILED",
            )
        return True

    def _handle_mission_control(self, text: str) -> bool:
        """处理任务确认/控制：确认、取消、暂停、继续、跳过、状态查询。"""
        t = (text or "").strip()
        if not t:
            return False
        try:
            from mission_control import get_mission_agent

            agent = get_mission_agent()
        except Exception:
            return False
        self._bind_mission_callbacks(agent)
        st = agent.status()
        running = st.get("running")
        pending = st.get("pending_confirmation")
        yes = bool(self._MISSION_YES_RE.match(t))
        no = bool(self._MISSION_NO_RE.match(t))
        zh = self._current_lang() == "zh"
        # 步骤级确认优先（Mission 执行中某步请求确认）
        if self._mission_step_pending and (yes or no):
            ok = agent.confirm_step(self._mission_step_pending, yes)
            self._mission_step_pending = None
            if ok:
                self._mission_speak(
                    "Understood. Continuing, sir." if not zh else "好的，继续执行。"
                )
            return True
        # Mission 级确认
        if pending and (yes or no):
            agent.confirm(yes)
            self._mission_speak(
                "Understood. Starting the mission now, sir."
                if yes and not zh
                else "好的，开始执行任务。" if yes else "任务已取消。"
            )
            return True
        if not running:
            return False
        if self._MISSION_PAUSE_RE.match(t):
            self._mission_speak_control(agent.pause(running), zh)
            return True
        if self._MISSION_RESUME_RE.match(t):
            self._mission_speak_control(agent.resume(running), zh)
            return True
        if self._MISSION_SKIP_RE.match(t):
            m = st.get("mission") or {}
            cur = next(
                (s for s in m.get("steps", []) if s.get("status") == "running"), None
            )
            if cur:
                agent.skip_step(running, cur["id"])
                self._mission_speak(
                    "Step will be skipped, sir." if not zh else "好的，将跳过这一步。"
                )
            return True
        if self._MISSION_STATUS_RE.match(t):
            self._mission_report_status(agent, st)
            return True
        return False

    def _mission_speak_control(self, res: dict, zh: bool):
        msg = res.get("message") or ("操作完成" if zh else "Done.")
        self._mission_speak(msg)

    def _mission_report_status(self, agent, st: dict):
        zh = self._current_lang() == "zh"
        running = st.get("running")
        if not running:
            self._mission_speak(
                "No mission is running, sir." if not zh else "当前没有正在执行的任务。"
            )
            return
        m = st.get("mission") or {}
        steps = m.get("steps", [])
        done = sum(1 for s in steps if s.get("status") == "succeeded")
        cur = next((s for s in steps if s.get("status") == "running"), None)
        if zh:
            msg = f"任务进行中，已完成 {done}/{len(steps)} 步。"
            if cur:
                msg += f"当前正在执行：{self._step_label(cur)}。"
        else:
            msg = f"Mission running, {done}/{len(steps)} steps completed."
            if cur:
                msg += f" Now executing: {self._step_label(cur)}."
        self._mission_speak(msg)

    # ── Mission 回调（executor 线程 → 口播）────────────────
    def _mission_on_plan(self, mission):
        """计划生成：口播计划摘要 + 请求确认。"""
        zh = self._current_lang() == "zh"
        steps = mission.steps
        n = len(steps)
        labels = [self._step_label(s) for s in steps]
        if zh:
            head = f"计划共 {n} 步："
            body = "；".join(f"{i + 1}. {lb}" for i, lb in enumerate(labels))
            msg = head + body + "。是否开始执行？"
        else:
            head = f"Plan ready, sir. {n} step{'s' if n != 1 else ''}: "
            body = " ".join(f"{i + 1}. {lb}" for i, lb in enumerate(labels))
            msg = head + body + " Proceed?"
        self._mission_speak(msg, hud="MISSION PLAN")

    def _mission_on_confirm_request(self, mission_id, step):
        """步骤确认请求：记录 pending 并口播。"""
        zh = self._current_lang() == "zh"
        self._mission_step_pending = step["id"]
        self._mission_step_mission = mission_id
        idx = step.get("index", 0) + 1
        if zh:
            msg = f"第 {idx} 步需要你确认：{self._step_label(step)}。是否继续？"
        else:
            msg = (
                f"Step {idx} needs your approval: {self._step_label(step)}. "
                "Shall I proceed, sir?"
            )
        self._mission_speak(msg)

    def _mission_on_step_done(self, mission_id, step):
        """步骤完成/失败/跳过口播（成功与失败播报，跳过安静）。"""
        status = step.get("status")
        if status not in ("succeeded", "failed", "skipped"):
            return
        zh = self._current_lang() == "zh"
        idx = step.get("index", 0) + 1
        label = self._step_label(step)
        if status == "succeeded":
            msg = f"Step {idx} done: {label}." if not zh else f"第 {idx} 步完成：{label}。"
        elif status == "failed":
            reason = step.get("error") or (step.get("result") or {}).get("summary", "")
            msg = (
                f"Step {idx} failed: {reason or label}."
                if not zh
                else f"第 {idx} 步失败：{reason or label}。"
            )
        else:
            msg = f"Step {idx} skipped." if not zh else f"第 {idx} 步已跳过。"
        self._mission_speak(msg)

    def _mission_on_mission_done(self, mission_id, mission):
        """任务完成/失败/取消汇报。"""
        zh = self._current_lang() == "zh"
        status = mission.get("status")
        if status == "completed":
            msg = (
                f"Mission complete, sir. {mission.get('summary', '')}."
                if not zh
                else f"任务完成。{mission.get('summary', '')}。"
            )
        elif status == "failed":
            msg = (
                f"Mission failed: {mission.get('summary', '')}"
                if not zh
                else f"任务失败：{mission.get('summary', '')}"
            )
        elif status == "cancelled":
            msg = "Mission cancelled, sir." if not zh else "任务已取消。"
        else:
            msg = f"Mission {status}." if not zh else f"任务{status}。"
        self._mission_speak(msg)

    def _map_clean_city(self, candidate: str) -> str:
        """从 ASR 提取的地点名中归一化出真实地名。
        短且干净（≤6字）直接使用；含明显噪音时取已知城市名
        （最长匹配，同长取最靠右 = 更具体片区，如"深圳宝安"→宝安）。"""
        c = self._map_norm(candidate)
        if len(c) <= 6:
            return c
        return self._map_city_key(c)

    def _map_city_key(self, city: str) -> str:
        """城市比较键：从候选里提取已知城市名（同长取最靠右=更具体），
        用于判断"深圳宝安"与"宝安"是否同一城市。"""
        c = self._map_norm(city)
        best, best_len, best_pos = "", 0, -1
        for name in self._MAP_CITY_NAMES:
            pos = c.find(name)
            if pos >= 0 and (
                len(name) > best_len or (len(name) == best_len and pos > best_pos)
            ):
                best, best_len, best_pos = name, len(name), pos
        return best or c

    def _map_city_en(self, city: str) -> str:
        """定位语音回复用的英文地名（贾维斯英音）；无已知城市返回空串。
        按出现位置取已知城市名，更具体（靠右）的在前：如"深圳宝安"→Bao'an, Shenzhen。"""
        c = self._map_norm(city)
        hits = []
        for name in self._MAP_CITY_NAMES:
            pos = c.find(name)
            if pos >= 0:
                hits.append((pos, name))
        if not hits:
            return ""
        hits.sort(key=lambda x: -x[0])
        return ", ".join(self._MAP_CITY_EN.get(n, n) for _, n in hits)

    def _map_extract_city(self, t: str) -> str:
        """从一句定位指令中提取干净城市名（无匹配返回空串）。"""
        cleaned = self._MAP_RE_CLEAN.sub("", t)
        m = self._MAP_RE_LOCATE.search(cleaned)
        if m:
            return self._map_clean_city(m.group(1))
        return ""

    def _handle_map_command(self, text: str) -> bool:
        """识别地图指令（语音驱动 overlay）：返回 True 表示已消费，不再进大模型。"""
        t = (text or "").strip()
        if not t:
            return False
        self._map_show_user_text = False
        now = time.time()
        norm = self._map_norm(t)
        # 定位窗口内：缩放/重置正常放行；其他文本视为回声碎片吞掉
        if self._map_locating and now < self._map_locate_deadline:
            if (self._MAP_RE_RESET.search(t)
                    or self._MAP_RE_ZOOM.search(t) or t in ("放大", "缩小")):
                pass  # 走下方 zoom/reset 分支
            elif "定位" in t:
                c = self._map_extract_city(t)
                if c and self._map_city_key(c) == self._map_locating_key:
                    print(f"[Map] 定位中，吞掉回声: {t}")
                    return True
                self._map_locating = False  # 换地点/新指令，放行
            elif self._map_fragment(t):
                print(f"[Map] 定位中，吞掉回声片段: {t}")
                return True
            else:
                self._map_locating = False  # 全新指令，放行并结束定位窗口
        # 去重：同一（归一化）指令 15 秒内重复（回声/流式重发）→ 忽略但仍消费
        if norm == self._last_map_norm and now - self._last_map_ts < self._MAP_DEDUP_TTL:
            print(f"[Map] 重复指令忽略: {t}")
            return True
        self._last_map_norm = norm
        self._last_map_ts = now
        # 缩放：整句只有"放大/缩小"，或带"地图"二字
        if t in ("放大", "缩小") or self._MAP_RE_ZOOM.search(t):
            direction = "放大" if ("放大" in t) else "缩小"
            self.visual.send("map_zoom +" if direction == "放大" else "map_zoom -")
            print(f"[Map] 缩放指令: {direction}")
            self._map_show_user_text = True
            return True
        if self._MAP_RE_RESET.search(t):
            self.visual.send("map_reset")
            self._map_locating = False
            self._map_located_city = ""
            self._map_located_key = ""
            print("[Map] 重置地图")
            self._map_show_user_text = True
            # 退出定位/关闭地图 → 回到地球视图并告知用户（贾维斯英文口播）
            self.visual.show_ai_text("GLOBE VIEW · 已回到地球视图")
            threading.Thread(
                target=self._map_speak,
                args=("Returning to the global view.",),
                daemon=True,
            ).start()
            return True
        # 定位：定位(到/去)城市（先剥离"请/帮我/一下"等口语助词，再贪婪取地名）
        if "定位" in t:
            city = self._map_extract_city(t)
            if city:
                # 最近已成功定位过同一城市 → 视为回声，不再重复定位
                if (
                    self._map_city_key(city) == self._map_located_key
                    and now - self._map_located_ts < self._MAP_SAME_CITY_TTL
                ):
                    print(f"[Map] 同城市已定位，忽略重复: {city}")
                    return True
                # 进入定位窗口：期间吞掉回声，避免反复触发闪烁
                self._map_locating = True
                self._map_locating_city = city
                self._map_locating_key = self._map_city_key(city)
                self._map_locate_deadline = now + self._MAP_LOCATE_TIMEOUT
                print(f"[Map] 定位到: {city}")
                self._map_show_user_text = True
                # 先用本地城市表快速定位，后台天地图地理编码解析出精确坐标后覆盖
                self.visual.send(f"map_locate {city}")
                threading.Thread(
                    target=self._fetch_city_news_async, args=(city,), daemon=True
                ).start()
                threading.Thread(
                    target=self._geocode_and_locate, args=(city,), daemon=True
                ).start()
                return True
        return False

    def _geocode_and_locate(self, city: str):
        """后台：天地图解析精确经纬度 → map_locate lat,lon,name 覆盖定位。
        失败自动重试一次；仍失败则重置地图并播报定位失败（不再反复定位）。"""
        for attempt in (1, 2):
            try:
                ll = _geocode_city(city)
                if ll:
                    lat, lon = ll
                    self.visual.send(f"map_locate {lat:.6f},{lon:.6f},{city}")
                    print(f"[Map] 精确定位 {city}: {lat:.6f},{lon:.6f}")
                    self._map_locating = False
                    self._map_located_city = city
                    self._map_located_key = self._map_city_key(city)
                    self._map_located_ts = time.time()
                    # 定位成功后直接回复用户（Jarvis 英文口播）
                    self.visual.show_ai_text(f"LOCATED · {city}")
                    _en = self._map_city_en(city)
                    _spoken = f"Located at {_en}." if _en else "Located."
                    threading.Thread(
                        target=self._map_speak,
                        args=(_spoken,),
                        daemon=True,
                    ).start()
                    return
                print(f"[Map] 地理编码未命中（第 {attempt} 次）: {city}")
            except Exception as e:
                print(f"[Map] geocode-and-locate 异常（第 {attempt} 次）: {e}")
            if attempt == 1:
                time.sleep(1.5)
        self._map_locate_fail(city)

    def _map_locate_fail(self, city: str):
        """定位失败：重置地图并播报失败，退出定位状态。"""
        self._map_locating = False
        print(f"[Map] 定位失败，退出定位: {city}")
        self.visual.send("map_reset")
        self.visual.show_ai_text("LOCATION FAILED · 定位失败，请换一个更具体的地点")
        threading.Thread(
            target=self._map_speak,
            args=("Location failed. Please try a more specific place.",),
            daemon=True,
        ).start()

    def _map_speak(self, text: str):
        """定位结果播报：播报期间标记处理中（主循环只等唤醒词打断），
        播完复位并清空音频队列，避免播报内容被麦克风拾取后误识别。"""
        self._is_processing = True
        try:
            text_to_speech_play(text)
        finally:
            self._clear_queue()
            self.last_voice_time = time.time()
            self._is_processing = False

    def _fetch_city_news_async(self, city: str):
        """后台抓取城市热点并推送给 overlay 展示。"""
        try:
            from map_news import fetch_city_news

            items = fetch_city_news(city, limit=4)
            payload = json.dumps({"city": city, "items": items}, ensure_ascii=False)
            self.visual.send(f"map_news {payload}")
            print(f"[Map] 已推送 {city} 资讯 {len(items)} 条")
        except Exception as e:
            print(f"[MapNews] 异常: {e}")

    def _push_global_news(self):
        """后台抓取全球热点资讯并推送给 overlay（球体右侧资讯面板）。"""
        try:
            from map_news import fetch_global_news

            items = fetch_global_news(limit=4)
            if not items:
                print("[MapNews] 全球资讯为空，跳过推送")
                return
            payload = json.dumps({"city": "", "items": items}, ensure_ascii=False)
            self.visual.send(f"map_news {payload}")
            print(f"[Map] 已推送全球资讯 {len(items)} 条")
        except Exception as e:
            print(f"[MapNews] 全球资讯异常: {e}")

    def _restart_assistant(self):
        """重启语音助手：执行 start.sh 或 start.bat 脚本"""
        # 幂等保护：回声 / 重复识别可能在极短时间内再次触发重启，
        # 避免拉起多个 start.sh 导致出现多个助手进程
        if getattr(self, "_restarting", False):
            print("[重启] 已在重启流程中，忽略重复的重启指令")
            return
        self._restarting = True

        print("\n[重启] 检测到重启指令，正在重启语音助手...")

        self._interrupt_openclaw_silent()
        self.is_awake = False
        self.continuous_mode = False
        self._verified_speaker_name = None
        self._conv_audio_buffer.clear()
        self._clear_queue()
        self.stop_event.set()

        import subprocess
        import platform
        import os
        from pathlib import Path

        project_dir = Path(__file__).parent.parent
        is_windows = platform.system() == "Windows"

        if is_windows:
            script_path = project_dir / "scripts" / "start.bat"
        else:
            script_path = project_dir / "scripts" / "start.sh"

        if not script_path.exists():
            print(f"[重启] 错误: 找不到启动脚本 {script_path}")
            return

        print(f"[重启] 执行脚本: {script_path}")

        try:
            if is_windows:
                subprocess.Popen(
                    ["cmd", "/c", "start", "/b", str(script_path)],
                    cwd=str(project_dir),
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                    | subprocess.DETACHED_PROCESS,
                )
            else:
                subprocess.Popen(
                    ["bash", str(script_path)],
                    cwd=str(project_dir),
                    start_new_session=True,
                )
            print("[重启] 重启进程已启动，当前实例退出。")
            time.sleep(0.3)
            os._exit(0)
        except Exception as e:
            print(f"[重启] 执行重启脚本失败: {e}")


def _enforce_single_instance():
    """启动时确保只有一个实例：杀掉 PID 文件中记录的其它存活实例。

    重启竞态下可能并发拉起多个 main.py，此处兜底收敛到单个进程。
    注意：只终止「确实是本语音助手」的旧实例（校验命令行含 main.py 与
    本工作目录），PID 一旦被其他应用复用绝不误杀。
    """
    try:
        if not os.path.exists(PID_FILE):
            return
        with open(PID_FILE, encoding="utf-8") as f:
            content = f.read().strip()
        old_pid = int(content) if content else 0
    except (ValueError, OSError):
        return

    if old_pid <= 0 or old_pid == os.getpid():
        return

    try:
        os.kill(old_pid, 0)  # 探测是否存活，不存在会抛 OSError
    except OSError:
        return  # 旧进程已不存在

    if not _is_voice_assistant_pid(old_pid):
        print(
            f"[单例] PID={old_pid} 已被其他进程复用（不是本助手），"
            "跳过终止以避免误杀其他应用"
        )
        return

    print(f"[单例] 检测到已有助手实例 PID={old_pid}，正在终止以避免重复进程...")
    try:
        os.kill(old_pid, signal.SIGKILL)
    except OSError as e:
        print(f"[单例] 终止旧实例失败: {e}")
        return

    # 等待旧实例退出（最多 ~2 秒）
    for _ in range(20):
        try:
            os.kill(old_pid, 0)
            time.sleep(0.1)
        except OSError:
            break


def _is_voice_assistant_pid(pid: int) -> bool:
    """校验 PID 是否真的是本语音助手（main.py）进程。

    通过 `ps -p <pid> -o command=` 检查命令行是否同时包含 main.py 与
    本工作目录路径，防止 PID 复用导致误杀其他应用（如用户的语音控制助手）。
    """
    try:
        import subprocess

        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout or ""
    except Exception:
        return False
    return "main.py" in out and _PROJECT_DIR in out


def assert_file_exists(filename):
    """检查文件是否存在"""
    filename = os.path.expanduser(filename)
    assert Path(filename).is_file(), (
        f"{filename} 不存在！\n"
        "请参考 https://k2-fsa.github.io/sherpa/onnx/pretrained_models/index.html 下载模型"
    )


def get_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="语音助手 - 基于 sherpa-onnx 的语音唤醒 + 识别",
    )

    # 关键词检测模型参数（sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20，中英双语）
    parser.add_argument(
        "--kws-tokens",
        type=str,
        default="models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/tokens.txt",
    )
    parser.add_argument(
        "--kws-encoder",
        type=str,
        default="models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/encoder-epoch-13-avg-2-chunk-16-left-64.onnx",
    )
    parser.add_argument(
        "--kws-decoder",
        type=str,
        default="models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/decoder-epoch-13-avg-2-chunk-16-left-64.onnx",
    )
    parser.add_argument(
        "--kws-joiner",
        type=str,
        default="models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/joiner-epoch-13-avg-2-chunk-16-left-64.onnx",
    )
    parser.add_argument("--keywords-file", type=str, default="keywords/lin-meimei.txt")
    parser.add_argument("--keywords-score", type=float, default=0.15)
    parser.add_argument("--keywords-threshold", type=float, default=0.15)

    # 语音识别模型参数
    parser.add_argument(
        "--asr-tokens",
        type=str,
        default="models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/tokens.txt",
    )
    parser.add_argument(
        "--asr-encoder",
        type=str,
        default="models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/encoder-epoch-99-avg-1.onnx",
    )
    parser.add_argument(
        "--asr-decoder",
        type=str,
        default="models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/decoder-epoch-99-avg-1.onnx",
    )
    parser.add_argument(
        "--asr-joiner",
        type=str,
        default="models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/joiner-epoch-99-avg-1.onnx",
    )

    # SenseVoice 模型参数（离线识别）
    _project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _sense_voice_model_dir = os.path.join(
        _project_dir,
        "models",
        "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17",
    )
    parser.add_argument(
        "--sense-voice-model",
        type=str,
        default=os.path.join(_sense_voice_model_dir, "model.int8.onnx"),
    )
    parser.add_argument(
        "--sense-voice-tokens",
        type=str,
        default=os.path.join(_sense_voice_model_dir, "tokens.txt"),
    )
    parser.add_argument(
        "--sense-voice-use-itn",
        type=int,
        default=1,
        help="是否启用反向文本规范化（标点符号）",
    )
    parser.add_argument(
        "--sense-voice-language",
        type=str,
        default="auto",
        help="语言：auto, zh, en, ko, ja, yue",
    )

    # Qwen3-ASR 模型参数（离线识别）
    _qwen3_model_dir = os.path.join(
        _project_dir, "models", "sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25"
    )
    parser.add_argument(
        "--qwen3-conv-frontend",
        type=str,
        default=os.path.join(_qwen3_model_dir, "conv_frontend.onnx"),
    )
    parser.add_argument(
        "--qwen3-encoder",
        type=str,
        default=os.path.join(_qwen3_model_dir, "encoder.int8.onnx"),
    )
    parser.add_argument(
        "--qwen3-decoder",
        type=str,
        default=os.path.join(_qwen3_model_dir, "decoder.int8.onnx"),
    )
    parser.add_argument(
        "--qwen3-tokenizer",
        type=str,
        default=os.path.join(_qwen3_model_dir, "tokenizer"),
    )
    parser.add_argument(
        "--vad-model",
        type=str,
        default=os.path.join(_project_dir, "models", "silero_vad.onnx"),
    )

    parser.add_argument(
        "--hotwords-file", type=str, default=os.path.join(_project_dir, "hotwords.txt")
    )
    parser.add_argument("--hotwords-score", type=float, default=1.5)

    parser.add_argument("--provider", type=str, default=_detect_best_provider())

    return parser.parse_args()


def main():
    global _assistant_instance

    setup_logging(_PROJECT_DIR)

    args = get_args()

    # 加载所有 assistant 配置
    default_cfg, all_assistants = _load_all_assistant_configs()
    print(f"[配置] 激活 assistant: {default_cfg['name']} ({default_cfg['id']})")

    # 使用 global.txt 作为唤醒词文件（由 start.sh 脚本合并生成）
    args.keywords_file = os.path.join(_PROJECT_DIR, "keywords", "global.txt")

    # 构建 keyword_to_assistant_id 映射（从所有 assistant 配置中读取）
    keyword_mapping = {}
    for assistant in all_assistants:
        assistant_id = assistant["id"]
        keywords_file = assistant.get("keywords_file")
        if keywords_file:
            full_path = os.path.join(_PROJECT_DIR, keywords_file)
            if os.path.exists(full_path):
                with open(full_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        if "@" in line:
                            keyword_text = line.split("@")[-1].strip()
                            keyword_mapping[keyword_text] = assistant_id
                print(f"[配置] 加载 {assistant['name']} ({assistant_id}) 的唤醒词映射")

    print(f"[配置] 使用唤醒词文件: {args.keywords_file}")
    print(f"[配置] 唤醒词映射: {keyword_mapping}")

    for f in [
        args.kws_tokens,
        args.kws_encoder,
        args.kws_decoder,
        args.kws_joiner,
        args.keywords_file,
        args.asr_tokens,
        args.asr_encoder,
        args.asr_decoder,
        args.asr_joiner,
    ]:
        assert_file_exists(f)

    assistant = VoiceAssistant(args, default_cfg, all_assistants, keyword_mapping)
    _assistant_instance = assistant

    api_thread = threading.Thread(target=_start_api_server, daemon=True)
    api_thread.start()
    print(f"API server started on port {API_PORT}")

    _enforce_single_instance()
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

    try:
        assistant.run()
    finally:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"发生错误: {e}")
