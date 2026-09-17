from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VisualMatch:
    text: str
    confidence: float
    x: int
    y: int
    width: int
    height: int
    source: str = "qwen2.5-vl"

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.update(center_x=self.center_x, center_y=self.center_y)
        return d


class VisionGrounder:
    """Optional local visual grounding via Ollama + Qwen2.5-VL.

    Fail-closed: unavailable Ollama/model, malformed output, or low confidence
    never becomes a click. The existing OCR locator remains the fallback.
    """

    def __init__(self, model: str | None = None, host: str | None = None,
                 timeout: float = 20.0, min_confidence: float = 0.70,
                 enabled: bool | None = None):
        self.model = model or os.environ.get("V7_VISION_MODEL", "qwen2.5vl:3b")
        self.host = (host or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout = max(2.0, float(timeout))
        self.min_confidence = max(0.0, min(1.0, float(min_confidence)))
        self.enabled = enabled if enabled is not None else os.environ.get("V7_VISION", "off").lower() != "off"
        self.calls = 0
        self.failures = 0

    def available(self) -> bool:
        if not self.enabled:
            return False
        try:
            req = urllib.request.Request(self.host + "/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=min(2.0, self.timeout)) as r:
                if r.status != 200:
                    return False
                payload = json.loads(r.read().decode("utf-8", "replace"))
            names = {str(x.get("name", "")) for x in payload.get("models", [])}
            return self.model in names
        except Exception:
            return False

    @staticmethod
    def _extract_json(text: str) -> Any:
        text = str(text or "").strip()
        if not text:
            return None
        # Accept fenced JSON and a JSON object/array embedded in a short reply.
        fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.I | re.S)
        candidates = [fenced.group(1)] if fenced else []
        candidates.append(text)
        for candidate in candidates:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        for opener, closer in (("[", "]"), ("{", "}")):
            a, b = text.find(opener), text.rfind(closer)
            if a >= 0 and b > a:
                try:
                    return json.loads(text[a:b + 1])
                except json.JSONDecodeError:
                    pass
        return None

    def _request(self, image_path: str, target: str) -> str:
        raw = Path(image_path).read_bytes()
        prompt = (
            "你是本地 GUI 视觉定位器。只根据这张截图定位目标。"
            f"目标文字：{target}\n"
            "如果看见目标，输出严格 JSON："
            '{"found":true,"matches":[{"text":"目标","confidence":0.0,"bbox":[x,y,w,h]}]}。'
            "bbox 是截图像素坐标 [x,y,width,height]。"
            "看不见就输出 {\"found\":false,\"matches\":[]}。"
            "不要输出解释、Markdown 或其他文字。"
        )
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "images": [base64.b64encode(raw).decode("ascii")],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }).encode("utf-8")
        req = urllib.request.Request(self.host + "/api/generate", data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            if r.status != 200:
                raise RuntimeError(f"vision HTTP {r.status}")
            response = json.loads(r.read().decode("utf-8", "replace"))
        return str(response.get("response", ""))

    def locate(self, image_path: str | None, target: str) -> list[VisualMatch]:
        if not self.enabled or not image_path or not target or not Path(image_path).is_file():
            return []
        self.calls += 1
        try:
            result = self._extract_json(self._request(image_path, target))
            if not isinstance(result, dict) or not result.get("found"):
                return []
            out: list[VisualMatch] = []
            for item in result.get("matches", []):
                if not isinstance(item, dict):
                    continue
                try:
                    conf = float(item.get("confidence", 0))
                    x, y, w, h = [int(v) for v in item.get("bbox", [])]
                    text = str(item.get("text", "")).strip()
                except (TypeError, ValueError):
                    continue
                if not text or conf < self.min_confidence or w <= 0 or h <= 0 or x < 0 or y < 0:
                    continue
                out.append(VisualMatch(text, conf, x, y, w, h))
            return sorted(out, key=lambda m: (-m.confidence, m.width * m.height))
        except Exception:
            self.failures += 1
            return []
