#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""本地 OCR 备用通道（macOS Vision VNRecognizeTextRequest）。

一次性用 swiftc 编译小助手（Command Line Tools 自带），二进制缓存到
~/Library/Caches/jarvis-computer/ocr_helper，后续调用零编译开销。

输出：[{text, x, y, w, h}]，坐标为像素（原点左上），与截图对应。
"""

import os
import subprocess
import tempfile

_SWIFT_SOURCE = r'''
import Foundation
import Vision
import AppKit

guard CommandLine.arguments.count > 1 else { exit(2) }
let path = CommandLine.arguments[1]
guard let data = try? Data(contentsOf: URL(fileURLWithPath: path)),
      let rep = NSBitmapImageRep(data: data),
      let cg = rep.cgImage else { exit(3) }

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: cg, options: [:])
do { try handler.perform([request]) } catch { exit(4) }

for obs in request.results ?? [] {
    guard let cand = obs.topCandidates(1).first else { continue }
    let bb = obs.boundingBox
    let x = bb.origin.x * CGFloat(cg.width)
    let y = (1.0 - bb.origin.y - bb.height) * CGFloat(cg.height)
    let w = bb.width * CGFloat(cg.width)
    let h = bb.height * CGFloat(cg.height)
    let s = cand.string.replacingOccurrences(of: "\t", with: " ")
    print("\(s)\t\(Int(x)),\(Int(y)),\(Int(w)),\(Int(h))")
}
'''

_BIN_DIR = os.path.expanduser("~/Library/Caches/jarvis-computer")
_BIN = os.path.join(_BIN_DIR, "ocr_helper")


def _ensure_bin() -> str:
    """首次编译并缓存 OCR 助手二进制。"""
    if os.path.exists(_BIN):
        return _BIN
    os.makedirs(_BIN_DIR, exist_ok=True)
    src = os.path.join(_BIN_DIR, "ocr_helper.swift")
    with open(src, "w", encoding="utf-8") as f:
        f.write(_SWIFT_SOURCE)
    p = subprocess.run(
        ["swiftc", "-O", "-o", _BIN, src],
        capture_output=True,
        text=True,
        timeout=180.0,
    )
    if p.returncode != 0:
        print(f"[Computer] OCR 助手编译失败: {p.stderr[-500:]}")
        return ""
    return _BIN


def recognize(image_path: str, timeout: float = 30.0) -> list:
    """识别截图中的文字 → [{text, x, y, w, h}]；失败返回空列表。"""
    bin_path = _ensure_bin()
    if not bin_path or not os.path.exists(image_path):
        return []
    try:
        p = subprocess.run(
            [bin_path, image_path], capture_output=True, text=True, timeout=timeout
        )
    except Exception as e:
        print(f"[Computer] OCR 异常: {e}")
        return []
    out = []
    for ln in p.stdout.splitlines():
        parts = ln.split("\t")
        if len(parts) != 2:
            continue
        text, box = parts[0], parts[1]
        try:
            x, y, w, h = (int(v) for v in box.split(","))
        except ValueError:
            continue
        if text.strip():
            out.append({"text": text.strip(), "x": x, "y": y, "w": w, "h": h})
    return out
