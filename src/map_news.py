#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""城市热点资讯抓取（供地图定位后展示）。

数据源优先级：
  1. Bing News RSS（无需 key，海外可达）
  2. 百度新闻（国内可达）
  3. DeepSeek 生成摘要（兜底，读取 hermes jarvis profile 的 DEEPSEEK_API_KEY）

返回 [{"title": str, "source": str, "time": str}, ...]
"""

import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"


def _fmt_time(pub_date: str) -> str:
    """RFC2822 → 'MM-DD HH:MM' 或 'HH:MM'"""
    try:
        dt = parsedate_to_datetime(pub_date)
        now = time.localtime()
        if dt.year == now.tm_year and dt.timetuple().tm_yday == now.tm_yday:
            return dt.strftime("%H:%M")
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return ""


def _bing(city: str, limit: int) -> list:
    q = urllib.parse.quote(f"{city} 热点")
    url = f"https://www.bing.com/news/search?q={q}&format=rss&setlang=zh-cn"
    r = requests.get(url, headers={"User-Agent": UA}, timeout=6)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items: list = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        src = ""
        for child in it:
            if child.tag.lower().endswith("source"):
                src = (child.text or "").strip()
                break
        pub = (it.findtext("pubDate") or "").strip()
        items.append({"title": title, "source": src, "time": _fmt_time(pub)})
        if len(items) >= limit:
            break
    return items


def _baidu(city: str, limit: int) -> list:
    word = urllib.parse.quote(f"{city} 热点")
    url = f"https://www.baidu.com/s?tn=news&rtt=4&word={word}"
    r = requests.get(url, headers={"User-Agent": UA}, timeout=6)
    r.raise_for_status()
    html = r.text
    titles = re.findall(r"<h3[^>]*>.*?<a[^>]*>(.*?)</a>", html, re.S)
    items: list = []
    for t in titles:
        t = re.sub(r"<[^>]+>", "", t)
        t = re.sub(r"\s+", " ", t).strip()
        if not t:
            continue
        items.append({"title": t, "source": "百度新闻", "time": ""})
        if len(items) >= limit:
            break
    return items


def _deepseek_key() -> str:
    path = os.path.expanduser("~/.hermes/profiles/jarvis/.env")
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DEEPSEEK_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return os.environ.get("DEEPSEEK_API_KEY", "")


def _deepseek(city: str, limit: int) -> list:
    key = _deepseek_key()
    if not key:
        return []
    prompt = (
        f"请用简体中文提供关于「{city}」的{limit}条最新本地热点资讯，"
        "每条严格一行，格式为：标题|来源或媒体名。只输出资讯，不要序号以外的说明。"
    )
    r = requests.post(
        DEEPSEEK_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 400,
            "temperature": 0.7,
        },
        timeout=15,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    items: list = []
    for line in content.splitlines():
        line = re.sub(r"^\s*[\d一二三四五六七八九十]+[.、)]\s*", "", line).strip()
        if not line:
            continue
        parts = line.split("|")
        title = parts[0].strip()
        if not title:
            continue
        src = parts[1].strip() if len(parts) > 1 else "AI 摘要"
        items.append(
            {"title": title, "source": src, "time": time.strftime("%H:%M")}
        )
        if len(items) >= limit:
            break
    return items


def _deepseek_global(limit: int) -> list:
    key = _deepseek_key()
    if not key:
        return []
    prompt = (
        f"请用简体中文提供当前全球最重要的{limit}条新闻要闻，"
        "每条严格一行，格式为：标题|来源或媒体名。只输出资讯，不要序号以外的说明。"
    )
    r = requests.post(
        DEEPSEEK_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 400,
            "temperature": 0.7,
        },
        timeout=15,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    items: list = []
    for line in content.splitlines():
        line = re.sub(r"^\s*[\d一二三四五六七八九十]+[.、)]\s*", "", line).strip()
        if not line:
            continue
        parts = line.split("|")
        title = parts[0].strip()
        if not title:
            continue
        src = parts[1].strip() if len(parts) > 1 else "AI 摘要"
        items.append(
            {"title": title, "source": src, "time": time.strftime("%H:%M")}
        )
        if len(items) >= limit:
            break
    return items


# 全球资讯缓存（10 分钟 TTL），避免每次唤醒都重新抓取
_GLOBAL_CACHE: list = []
_GLOBAL_CACHE_TS: float = 0.0
_GLOBAL_CACHE_TTL = 600.0


def fetch_global_news(limit: int = 4) -> list:
    """抓取全球当前热点资讯（球体右侧资讯面板），全部失败返回空列表。"""
    global _GLOBAL_CACHE, _GLOBAL_CACHE_TS
    now = time.time()
    if _GLOBAL_CACHE and now - _GLOBAL_CACHE_TS < _GLOBAL_CACHE_TTL:
        return _GLOBAL_CACHE[:limit]
    items: list = []
    for q in ("国际", "全球热点", "世界新闻", "国际要闻"):
        try:
            items = _bing(q, limit)
            if items:
                print(f"[MapNews] global bing({q}) -> {len(items)} 条")
                break
        except Exception as e:
            print(f"[MapNews] global bing({q}) 失败: {e}")
    if not items:
        try:
            items = _baidu("全球热点", limit)
            if items:
                print(f"[MapNews] global baidu -> {len(items)} 条")
        except Exception as e:
            print(f"[MapNews] global baidu 失败: {e}")
    if not items:
        items = _deepseek_global(limit)
        if items:
            print(f"[MapNews] global deepseek -> {len(items)} 条")
    if items:
        _GLOBAL_CACHE = items
        _GLOBAL_CACHE_TS = now
    return items


def fetch_city_news(city: str, limit: int = 4) -> list:
    """按优先级抓取城市热点资讯，全部失败返回空列表。"""
    city = (city or "").strip()
    if not city:
        return []
    for fn in (_bing, _baidu, _deepseek):
        try:
            items = fn(city, limit)
            if items:
                print(f"[MapNews] {fn.__name__} -> {len(items)} 条 ({city})")
                return items
        except Exception as e:
            print(f"[MapNews] {fn.__name__} 失败: {e}")
    return []
