from __future__ import annotations
from dataclasses import dataclass
import re
from .gui_model import GUISnapshot

def _norm(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()

@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    reason: str

def verify_same_window(before: GUISnapshot, after: GUISnapshot) -> VerificationResult:
    if not before.stable or not after.stable:
        return VerificationResult(False, "unstable observation")
    if not before.active_window or not after.active_window:
        return VerificationResult(False, "missing active window")
    try:
        same = int(before.active_window.window_id, 16) == int(after.active_window.window_id, 16)
    except (TypeError, ValueError):
        same = before.active_window.window_id.casefold() == after.active_window.window_id.casefold()
    return VerificationResult(bool(same), "same window" if same else "active window changed")

def verify_expected_marker(after: GUISnapshot, markers: list[str] | tuple[str, ...]) -> VerificationResult:
    hay = _norm(f"{after.ocr_text}\n{after.browser_text}")
    elements = [_norm(str(e.get("name") or e.get("text") or "")) for e in after.browser_elements]
    wanted = [_norm(x) for x in markers if _norm(x)]
    if not wanted:
        return VerificationResult(False, "no expected marker")
    if any(m in hay or any(m in e for e in elements) for m in wanted):
        return VerificationResult(True, "expected marker observed")
    return VerificationResult(False, "expected marker not observed")

def verify_text_visible(after: GUISnapshot, text: str) -> VerificationResult:
    return verify_expected_marker(after, [text])
