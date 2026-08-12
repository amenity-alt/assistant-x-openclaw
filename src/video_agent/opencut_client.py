#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""OpenCut REST 客户端（唯一允许访问 OpenCut 的地方）。

- 负责 OpenCut API 进程的生命周期（首次使用时拉起，随 Jarvis 退出回收）；
- 提供 generate / facecam / render / status / download 五个动作；
- 全部走 127.0.0.1，超时受控，失败抛 OpenCutError 由上层软失败处理。
"""

import os
import re
import shutil
import subprocess
import threading
import time

import requests

# ── 配置 ──────────────────────────────────────────────────
_DEFAULT_OPENCUT_DIR = os.path.expanduser("~/Documents/ChatGPT/opencut")
OPENCUT_DIR = os.environ.get("OPENCUT_DIR", _DEFAULT_OPENCUT_DIR)
OPENCUT_PORT = int(os.environ.get("OPENCUT_PORT", "3100"))
BASE_URL = f"http://127.0.0.1:{OPENCUT_PORT}"

_HTTP_TIMEOUT = 10.0          # 单次 HTTP 请求超时
_SERVER_WAIT_SEC = 25.0       # 拉起后等待健康的最长时间
_JOB_POLL_INTERVAL = 4.0      # 任务轮询间隔

_REQ_TIMEOUT = (3.0, _HTTP_TIMEOUT)


class OpenCutError(Exception):
    pass


class OpenCutClient:
    """OpenCut API 客户端（单例，含进程管理）。"""

    def __init__(self, base_url: str = BASE_URL, opencut_dir: str = OPENCUT_DIR,
                 port: int = OPENCUT_PORT):
        self.base_url = base_url
        self.opencut_dir = os.path.expanduser(opencut_dir)
        self.port = port
        self._proc = None
        self._lock = threading.Lock()
        self._started = False

    # ── 生命周期 ─────────────────────────────────────────
    def available(self) -> bool:
        """OpenCut 目录存在且可启动。"""
        return (
            os.path.isdir(self.opencut_dir)
            and os.path.isfile(os.path.join(self.opencut_dir, "package.json"))
        )

    def health(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/health", timeout=2.0)
            return r.status_code == 200
        except Exception:
            return False

    def ensure_server(self) -> bool:
        """确保 OpenCut API 在运行。返回 True 表示可用。"""
        if self.health():
            return True
        if not self.available():
            print(f"[Video] OpenCut 目录不可用: {self.opencut_dir}")
            return False
        with self._lock:
            if self.health():
                return True
            if self._started and self._proc is not None:
                # 上次已拉起但进程死了 → 清理句柄后重拉
                try:
                    self._proc.poll()
                except Exception:
                    pass
            server_ts = os.path.join(self.opencut_dir, "src", "api", "server.ts")
            if not os.path.isfile(server_ts):
                print(f"[Video] OpenCut server.ts 缺失: {server_ts}")
                return False
            log_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)))), "logs", "opencut_api.log"
            )
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            env = dict(os.environ)
            env["PORT"] = str(self.port)
            try:
                cmd = [
                    "node", "--require", "ts-node/register",
                    os.path.join(self.opencut_dir, "src", "api", "server.ts"),
                ]
                # OpenCut 不自行加载 .env，Node 22.9+ 支持 --env-file-if-exists
                if os.path.isfile(os.path.join(self.opencut_dir, ".env")):
                    cmd.insert(1, "--env-file-if-exists=.env")
                self._proc = subprocess.Popen(
                    cmd,
                    cwd=self.opencut_dir,
                    env=env,
                    stdout=open(log_path, "a", encoding="utf-8"),
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                self._started = True
            except Exception as e:
                print(f"[Video] 拉起 OpenCut API 失败: {e}")
                return False
        # 等待健康
        deadline = time.time() + _SERVER_WAIT_SEC
        while time.time() < deadline:
            if self.health():
                print(f"[Video] OpenCut API 就绪: {self.base_url}")
                return True
            time.sleep(1.0)
        print("[Video] OpenCut API 启动超时")
        return False

    def shutdown(self):
        """回收 OpenCut API 进程（Jarvis 退出时调用，软失败）。"""
        with self._lock:
            proc = self._proc
            self._proc = None
            self._started = False
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass

    # ── AI key 检查 ──────────────────────────────────────
    def has_gemini_key(self) -> bool:
        """OpenCut 的 .env 里是否有 GEMINI_API_KEY（generate/facecam 需要）。"""
        return self._env_has("GEMINI_API_KEY")

    def has_ai_key(self) -> bool:
        """是否有任一可用的 AI key（DeepSeek 或 Gemini）。"""
        return self._env_has("DEEPSEEK_API_KEY") or self._env_has("GEMINI_API_KEY")

    def _env_has(self, name: str) -> bool:
        env_file = os.path.join(self.opencut_dir, ".env")
        if not os.path.isfile(env_file):
            return False
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(f"{name}=") and line.split("=", 1)[1]:
                        return True
        except Exception:
            return False
        return False

    # ── 提交任务 ─────────────────────────────────────────
    def submit_generate(self, prompt: str, duration_sec: int = 60,
                        voice: str = "") -> str:
        body = {"prompt": prompt, "targetDurationSec": duration_sec or 60}
        if voice:
            body["voice"] = voice
        return self._post("/generate", body)

    def submit_facecam(self, video_path: str, playback_rate: float = 1.0) -> str:
        if not os.path.isfile(video_path):
            raise OpenCutError(f"素材不存在: {video_path}")
        with open(video_path, "rb") as f:
            files = {"video": (os.path.basename(video_path), f, "video/mp4")}
            data = {"playbackRate": str(playback_rate)}
            try:
                r = requests.post(
                    f"{self.base_url}/facecam", files=files, data=data,
                    timeout=_REQ_TIMEOUT,
                )
            except Exception as e:
                raise OpenCutError(f"上传素材失败: {e}")
        if r.status_code != 202:
            raise OpenCutError(f"/facecam 返回 {r.status_code}: {r.text[:200]}")
        return self._job_id(r)

    def submit_render(self, composition_id: str, entry_point: str,
                      input_props: dict = None) -> str:
        body = {
            "compositionId": composition_id,
            "entryPoint": entry_point,
        }
        if input_props:
            body["inputProps"] = input_props
        return self._post("/render", body)

    def job_status(self, job_id: str) -> dict:
        try:
            r = requests.get(f"{self.base_url}/jobs/{job_id}", timeout=_REQ_TIMEOUT)
        except Exception as e:
            raise OpenCutError(f"查询任务失败: {e}")
        if r.status_code != 200:
            raise OpenCutError(f"任务不存在: {job_id}")
        return r.json()

    def download(self, job_id: str, dest_path: str) -> str:
        """下载成品 MP4 到 dest_path，返回路径。"""
        try:
            r = requests.get(
                f"{self.base_url}/jobs/{job_id}/download", stream=True,
                timeout=(3.0, 60.0),
            )
        except Exception as e:
            raise OpenCutError(f"下载失败: {e}")
        if r.status_code != 200:
            raise OpenCutError(
                f"下载失败(status={r.status_code}): {r.text[:200]}"
            )
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        tmp = dest_path + ".part"
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
        shutil.move(tmp, dest_path)
        return dest_path

    # ── 内部 ─────────────────────────────────────────────
    def _post(self, path: str, body: dict) -> str:
        try:
            r = requests.post(
                f"{self.base_url}{path}", json=body, timeout=_REQ_TIMEOUT
            )
        except Exception as e:
            raise OpenCutError(f"{path} 请求失败: {e}")
        if r.status_code != 202:
            raise OpenCutError(f"{path} 返回 {r.status_code}: {r.text[:200]}")
        return self._job_id(r)

    @staticmethod
    def _job_id(r) -> str:
        try:
            data = r.json()
        except Exception:
            raise OpenCutError("响应不是 JSON")
        job_id = data.get("jobId") or data.get("job_id")
        if not job_id:
            raise OpenCutError(f"响应缺少 jobId: {data}")
        return str(job_id)


# ── 单例 ─────────────────────────────────────────────────
_client = None
_client_lock = threading.Lock()


def get_opencut_client() -> OpenCutClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = OpenCutClient()
        return _client


# 供 main.py 退出钩子调用
def shutdown_opencut():
    global _client
    with _client_lock:
        c = _client
        _client = None
    if c is not None:
        try:
            c.shutdown()
        except Exception:
            pass
