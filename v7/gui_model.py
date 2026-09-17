from __future__ import annotations
from dataclasses import dataclass, field, asdict
import hashlib, json, re
from typing import Any

@dataclass(frozen=True)
class WindowSnapshot:
    window_id: str
    pid: str
    wm_class: str
    title: str
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    active: bool = False

@dataclass
class GUISnapshot:
    timestamp: float
    active_window: WindowSnapshot | None
    windows: list[WindowSnapshot] = field(default_factory=list)
    screenshot: str | None = None
    ocr_text: str = ""
    browser_text: str = ""
    browser_elements: list[dict[str, Any]] = field(default_factory=list)
    source: str = "desktop"
    stable: bool = True

    def fingerprint(self) -> str:
        data = {
            "active": self.active_window.title if self.active_window else "",
            "active_class": self.active_window.wm_class if self.active_window else "",
            "windows": sorted((w.wm_class, w.title, w.x, w.y, w.width, w.height) for w in self.windows),
            "ocr": normalize_text(self.ocr_text),
            "browser": normalize_text(self.browser_text),
            "elements": sorted((str(e.get("role", "")), str(e.get("name", "")), str(e.get("text", ""))) for e in self.browser_elements),
        }
        return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]

@dataclass
class PageModel:
    fingerprint: str
    title: str
    app: str
    evidence: dict[str, Any]
    visits: int = 1
    controls: list[str] = field(default_factory=list)

@dataclass
class NavigationEdge:
    before: str
    action: str
    after: str
    verified: bool

@dataclass
class GUIModel:
    pages: dict[str, PageModel] = field(default_factory=dict)
    edges: list[NavigationEdge] = field(default_factory=list)

    def add(self, snap: GUISnapshot) -> tuple[PageModel, bool]:
        fp = snap.fingerprint()
        if fp in self.pages:
            self.pages[fp].visits += 1
            return self.pages[fp], False
        active = snap.active_window
        page = PageModel(
            fingerprint=fp,
            title=active.title if active else "",
            app=active.wm_class if active else "",
            evidence={
                "screenshot": snap.screenshot,
                "ocr_text": snap.ocr_text,
                "browser_text": snap.browser_text,
                "windows": [asdict(w) for w in snap.windows],
            },
            controls=extract_controls(snap.ocr_text, snap.browser_elements),
        )
        self.pages[fp] = page
        return page, True

    def connect(self, before: GUISnapshot, action: str, after: GUISnapshot, verified: bool) -> None:
        self.edges.append(NavigationEdge(before.fingerprint(), action, after.fingerprint(), bool(verified)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "pages": [asdict(p) for p in self.pages.values()],
            "navigation": [asdict(e) for e in self.edges],
        }

def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()

def extract_controls(ocr: str, elements: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for e in elements or []:
        value = e.get("name") or e.get("text")
        if value and str(value).strip():
            value = str(value).strip()
            if value not in out:
                out.append(value)
    for line in str(ocr or "").splitlines():
        line = line.strip()
        if 1 <= len(line) <= 80 and line not in out:
            out.append(line)
    return out[:200]
