from __future__ import annotations
import re
import subprocess
import time
import shutil
from pathlib import Path
from typing import Any

from .gui_model import GUISnapshot, GUIModel, WindowSnapshot
from .safety import action_allowed, reversible_target
from .reasoning import TextReasoningBudget, TextReasoningContext
from .gui_locator import OCRBox, resolve_text, validate_match
from .vision_grounder import VisionGrounder

class V7Explorer:
    def __init__(self, project_root: str | Path | None = None, max_steps: int = 40, settle: float = 0.12, llm_budget: int = 0):
        self.project_root = Path(project_root or Path.cwd())
        self.max_steps = max(1, max_steps)
        self.settle = max(0.05, settle)
        self.model = GUIModel()
        self.history: list[dict[str, Any]] = []
        self.snapshots: list[GUISnapshot] = []
        self.step = 0
        self._clicked_labels: set[tuple[str, str]] = set()
        self._router = None
        self.timings: list[dict[str, Any]] = []
        # GUI 阶段默认禁止网页版普通 GPT；只有显式预算才允许上层注入调用。
        self.reasoning = TextReasoningBudget(max_calls=max(0, int(llm_budget)))
        self.llm_budget = self.reasoning.max_calls
        self.llm_calls = 0
        self.llm_time_total = 0.0
        # Optional local Qwen2.5-VL fallback. OCR remains the fast path.
        self.vision = VisionGrounder()

    @staticmethod
    def _parse_windows(raw: str) -> list[WindowSnapshot]:
        windows: list[WindowSnapshot] = []
        # Real wmctrl -lxG: id desktop pid x y width height wm_class host title.
        # Some test fixtures omit host/pid; accept both layouts.
        for line in raw.splitlines():
            p = line.split(None, 8)
            if len(p) < 8:
                continue
            try:
                if len(p) >= 9 and p[2].lstrip("-").isdigit() and p[6].lstrip("-").isdigit():
                    pid, x, y, width, height, wm_class, title = p[2], *map(int, p[3:7]), p[7], p[8]
                else:
                    # Real wmctrl -lxG without a PID: id desktop x y width height wm_class host title.
                    # Compact fixtures use id desktop x y width height wm_class title.
                    pid = ""
                    x, y, width, height = map(int, p[2:6])
                    wm_class = p[6]
                    title = p[8] if len(p) >= 9 else " ".join(p[7:])
                windows.append(WindowSnapshot(window_id=p[0], pid=pid, wm_class=wm_class, title=title,
                                              x=x, y=y, width=width, height=height, active=False))
            except (ValueError, IndexError):
                continue
        return windows

    def _windows(self) -> list[WindowSnapshot]:
        try:
            raw = subprocess.check_output(["wmctrl", "-lxG"], text=True, stderr=subprocess.DEVNULL, timeout=3)
        except (OSError, subprocess.SubprocessError):
            return []
        return self._parse_windows(raw)

    def _active_window(self, windows: list[WindowSnapshot]) -> WindowSnapshot | None:
        try:
            raw = subprocess.check_output(["xprop", "-root", "_NET_ACTIVE_WINDOW"], text=True, stderr=subprocess.DEVNULL, timeout=2)
            match = re.search(r"0x[0-9a-fA-F]+", raw)
            wid = match.group(0) if match else ""
            for w in windows:
                try:
                    if int(w.window_id, 16) == int(wid, 16):
                        return WindowSnapshot(**{**w.__dict__, "active": True})
                except ValueError:
                    if w.window_id.casefold() == wid.casefold():
                        return WindowSnapshot(**{**w.__dict__, "active": True})
        except (OSError, subprocess.SubprocessError):
            pass
        return None

    @staticmethod
    def _capture_desktop(path: str) -> bool:
        """Capture the root desktop so observation is not limited to one window."""
        try:
            subprocess.run(["import", "-window", "root", path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            return True
        except (OSError, subprocess.SubprocessError):
            return False

    def observe_desktop(self, reason: str = "desktop-wide observation") -> GUISnapshot:
        """Capture a coherent desktop observation; unstable evidence is unusable."""
        started = time.monotonic()
        windows = self._windows()
        active = self._active_window(windows)
        shot = None
        stable = False
        for attempt in range(2):
            candidate = f"/tmp/v7_desktop_{self.step:03d}_{time.time_ns()}.png"
            shot = candidate if self._capture_desktop(candidate) else None
            latest_windows = self._windows()
            latest_active = self._active_window(latest_windows)
            same_active = (not active and not latest_active) or self._same_window(active, latest_active)
            if shot and same_active:
                windows, active = latest_windows, latest_active
                stable = True
                break
            windows, active = latest_windows, latest_active
            stable = False
        if not stable:
            # Do not expose mixed pixels + metadata as actionable evidence.
            shot = None
            ocr = ""
        else:
            ocr = self._ocr(shot)
        self.timings.append({"operation": "observe_desktop", "ocr": True, "capture": True, "stable": stable, "seconds": round(time.monotonic() - started, 3), "llm_calls": self.llm_calls})
        snap = GUISnapshot(time.time(), active, windows, shot, ocr_text=ocr, source="desktop", stable=stable)
        _, new_page = self.model.add(snap); self.snapshots.append(snap)
        self.history.append({"step": self.step, "kind": "OBSERVE_DESKTOP", "reason": reason, "fingerprint": snap.fingerprint(), "new_page": new_page, "active_window": active.title if active else "", "ocr": ocr[:5000], "stable": stable})
        return snap

    @staticmethod
    def _capture(window_id: str, path: str) -> bool:
        try:
            subprocess.run(["import", "-window", window_id, path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            return True
        except (OSError, subprocess.SubprocessError):
            return False

    @staticmethod
    def _ocr(path: str | None) -> str:
        if not path or not Path(path).exists():
            return ""
        # Prefer the installed Simplified-Chinese model; fall back without a
        # second long timeout. Tesseract itself is the expensive operation, so
        # keep the timeout bounded for interactive use.
        for lang in ("chi_sim+eng", "HanS+eng", "eng"):
            try:
                return subprocess.check_output(["tesseract", path, "stdout", "-l", lang, "--psm", "11"], text=True, stderr=subprocess.DEVNULL, timeout=3)
            except (OSError, subprocess.SubprocessError):
                continue
        return ""

    def observe(self, reason: str = "", with_ocr: bool = True, capture: bool | None = None) -> GUISnapshot:
        """Capture coherent window evidence; mixed evidence is explicitly unstable."""
        if capture is None:
            capture = bool(with_ocr)
        started = time.monotonic()
        windows = self._windows()
        active = self._active_window(windows)
        shot = None
        stable = False
        for attempt in range(2):
            shot = None
            if active and capture:
                candidate = f"/tmp/v7_gui_{self.step:03d}_{time.time_ns()}.png"
                if self._capture(active.window_id, candidate):
                    shot = candidate
            latest = self._find_window_by_id(active.window_id) if active else None
            if not capture:
                windows = self._windows(); active = self._active_window(windows)
                stable = True
                break
            if shot and latest and (latest.x, latest.y, latest.width, latest.height) == (active.x, active.y, active.width, active.height):
                latest_windows = self._windows()
                latest_active = self._active_window(latest_windows)
                if latest_active and self._same_window(latest_active, active):
                    windows, active = latest_windows, latest_active
                    stable = True
                    break
            stable = False
            windows = self._windows()
            active = self._active_window(windows)
        if stable and shot and with_ocr:
            ocr = self._ocr(shot)
        elif stable:
            ocr = ""
        else:
            # Never return OCR from a screenshot whose window metadata could not
            # be reconciled after the retry budget.
            shot = None
            ocr = ""
        self.timings.append({"operation": "observe", "ocr": bool(with_ocr), "capture": bool(capture), "stable": stable, "seconds": round(time.monotonic() - started, 3), "llm_calls": self.llm_calls})
        snap = GUISnapshot(time.time(), active, windows, shot, ocr_text=ocr, stable=stable)
        _, new_page = self.model.add(snap); self.snapshots.append(snap)
        self.history.append({"step": self.step, "kind": "OBSERVE", "reason": reason, "fingerprint": snap.fingerprint(), "new_page": new_page, "active_window": active.title if active else "", "ocr": snap.ocr_text[:3000], "stable": stable})
        return snap

    @staticmethod
    def _launcher_candidates(*terms: str) -> list[Path]:
        """Find safe application launchers without requiring an existing window."""
        needles = [t.casefold() for t in terms if t]
        roots = [
            Path.home() / "桌面",
            Path.home() / "Desktop",
            Path.home() / ".local/share/applications",
            Path("/usr/share/applications"),
        ]
        found: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            if not root.exists():
                continue
            try:
                entries = list(root.glob("*.desktop"))
                # Desktop folders can also contain launcher files with unusual
                # names; only inspect direct children to keep startup bounded.
                if root.name in ("桌面", "Desktop"):
                    entries += [p for p in root.iterdir() if p.is_file() and p.suffix.lower() == ".desktop"]
            except OSError:
                continue
            for path in entries:
                key = str(path.resolve())
                if key in seen:
                    continue
                seen.add(key)
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")[:20000]
                except OSError:
                    continue
                hay = f"{path.name} {text}".casefold()
                if needles and any(n in hay for n in needles):
                    found.append(path)
        # Prefer a desktop-local launcher over a system launcher when both exist.
        found.sort(key=lambda x: (0 if x.parent.name in ("桌面", "Desktop") else 1, len(str(x))))
        return found

    def launch_app(self, *terms: str) -> tuple[bool, str]:
        """Launch an unopened app from a desktop/application .desktop entry.

        This is deliberately limited to application launchers discovered from
        the real desktop/application menus; it never executes an arbitrary
        command supplied by the task.
        """
        candidates = self._launcher_candidates(*terms)
        if not candidates:
            return False, "未找到应用启动图标/desktop launcher"
        launcher = candidates[0]
        errors: list[str] = []
        commands = []
        if shutil.which("gtk-launch"):
            commands.append(["gtk-launch", launcher.stem])
        if shutil.which("gio"):
            commands.append(["gio", "launch", str(launcher)])
        if shutil.which("xdg-open"):
            commands.append(["xdg-open", str(launcher)])
        for cmd in commands:
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=5)
                self.history.append({
                    "step": self.step, "kind": "LAUNCH_APP",
                    "launcher": str(launcher), "method": cmd[0], "verified": False,
                })
                return True, f"已启动应用入口: {launcher.name}"
            except (OSError, subprocess.SubprocessError) as exc:
                errors.append(f"{cmd[0]}: {exc}")
        return False, "应用启动失败: " + "; ".join(errors)

    def wait_for_window(self, *terms: str, timeout: float = 15.0) -> WindowSnapshot | None:
        deadline = time.monotonic() + max(0.5, timeout)
        while time.monotonic() < deadline:
            window = self.find_window(*terms)
            if window:
                return window
            time.sleep(min(0.25, self.settle))
        return self.find_window(*terms)

    def find_window(self, *terms: str) -> WindowSnapshot | None:
        needles = [t.casefold() for t in terms if t]
        if not needles:
            return None
        windows = self._windows()
        active = self._active_window(windows)
        candidates = []
        for w in windows:
            title = w.title.casefold()
            wm_class = w.wm_class.casefold()
            scores = []
            for n in needles:
                if n == title:
                    scores.append(100)
                elif n == wm_class:
                    scores.append(95)
                elif n in title:
                    scores.append(80)
                elif n in wm_class:
                    scores.append(70)
            if scores:
                score = max(scores)
                if active and self._same_window(active, w):
                    score += 50
                # Prefer real, non-zero geometry over stale/minimized fixtures.
                if w.width > 0 and w.height > 0:
                    score += 2
                candidates.append((score, w))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item[0], item[1].window_id))
        return candidates[0][1]

    @staticmethod
    def _same_window(a: WindowSnapshot | None, b: WindowSnapshot | None) -> bool:
        if not a or not b:
            return False
        try:
            return int(a.window_id, 16) == int(b.window_id, 16)
        except (TypeError, ValueError):
            return a.window_id.casefold() == b.window_id.casefold()

    def _find_window_by_id(self, window_id: str) -> WindowSnapshot | None:
        for w in self._windows():
            try:
                if int(w.window_id, 16) == int(window_id, 16):
                    return w
            except (TypeError, ValueError):
                if w.window_id.casefold() == str(window_id).casefold():
                    return w
        return None

    def activate(self, window: WindowSnapshot) -> bool:
        if not action_allowed("WINDOW_ACTIVATE", window.title):
            return False
        try:
            # Some KWin/X11 windows remain hidden/shaded even after -a. Remove
            # those states first, then activate, and finally verify the active id.
            for state in (("remove", "hidden"), ("remove", "shaded")):
                subprocess.run(["wmctrl", "-ir", window.window_id, "-b", f"{state[0]},{state[1]}"],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            subprocess.run(["wmctrl", "-ia", window.window_id], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            time.sleep(self.settle)
            verified = self._active_window(self._windows())
            return self._same_window(verified, window)
        except (OSError, subprocess.SubprocessError):
            return False

    @staticmethod
    def _ocr_boxes(path: str | None) -> list[OCRBox]:
        if not path or not Path(path).exists():
            return []
        for lang in ("chi_sim+eng", "eng"):
            try:
                raw = subprocess.check_output(["tesseract", path, "stdout", "-l", lang, "--psm", "11", "tsv"], text=True, stderr=subprocess.DEVNULL, timeout=4)
            except (OSError, subprocess.SubprocessError):
                continue
            out = []
            for line in raw.splitlines()[1:]:
                p = line.split("\t")
                if len(p) < 12:
                    continue
                try:
                    text = p[11].strip(); conf = float(p[10])
                    if text and conf >= 20:
                        out.append(OCRBox(text, int(p[6]), int(p[7]), int(p[8]), int(p[9]), conf))
                except (ValueError, IndexError):
                    pass
            return out
        return []

    def click_text_local(self, text: str, window: WindowSnapshot | None = None) -> tuple[bool, str, dict]:
        if not reversible_target(text):
            return False, "blocked by safety policy", {}
        window = window or self._active_window(self._windows())
        if not window:
            return False, "no active window", {}
        # Re-validate the supplied window immediately before capture. A stale
        # WindowSnapshot can otherwise make a later click land in a different
        # window after a workspace switch, resize, or app restart.
        current = self._find_window_by_id(window.window_id)
        if not current:
            # Never substitute another same-title/same-class window: that can
            # silently redirect the click to a different application instance.
            return False, "target window disappeared", {"window_id": window.window_id}
        window = current
        if not self.activate(window):
            return False, "target window is not active", {"window_id": window.window_id}
        shot = f"/tmp/v7_gui_click_{self.step:03d}_{time.time_ns()}.png"
        if not self._capture(window.window_id, shot):
            return False, "screenshot capture failed", {}
        boxes = self._ocr_boxes(shot)
        matches = resolve_text(text, boxes)
        if not matches:
            # OCR missed it: use the proven local Qwen2.5-VL path. This is a
            # fallback, never the sole dependency, so installation still works
            # on machines without Ollama or a vision model.
            visual = self.vision.locate(shot, text)
            if visual:
                vm = visual[0]
                evidence = vm.to_dict()
                evidence.update({"screenshot": shot, "vision_fallback": True})
                if not (vm.x + vm.width <= window.width and vm.y + vm.height <= window.height):
                    return False, "visual bbox outside captured window", evidence
                latest = self._find_window_by_id(window.window_id)
                if not latest or not self._same_window(latest, window):
                    return False, "target window changed before visual click", evidence
                if (latest.x, latest.y, latest.width, latest.height) != (window.x, window.y, window.width, window.height):
                    return False, "window geometry changed before visual click", evidence
                if not shutil.which("xdotool"):
                    return False, "xdotool not found", evidence
                screen_x = int(window.x) + vm.center_x
                screen_y = int(window.y) + vm.center_y
                try:
                    subprocess.run(["xdotool", "mousemove", str(screen_x), str(screen_y), "click", "1"], check=True, timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except (OSError, subprocess.SubprocessError) as exc:
                    return False, f"visual mouse click failed: {exc}", evidence
                evidence.update({"screen_x": screen_x, "screen_y": screen_y, "window_x": window.x, "window_y": window.y})
                self.history.append({"step": self.step, "kind": "CLICK", "target": text, "evidence": evidence, "verified": False})
                return True, f"clicked {text} at ({vm.center_x},{vm.center_y}) via vision", evidence
            return False, f"target not found: {text}", {"ocr_boxes": len(boxes), "vision_calls": self.vision.calls, "vision_failures": self.vision.failures}
        # Rank candidates by evidence instead of trusting OCR enumeration order.
        # Exact/high-confidence matches win; ties favor the anchor with more
        # target-local evidence. Never silently pick the first OCR result.
        valid_matches = []
        for candidate in matches:
            ok_geometry, geometry_reason = validate_match(candidate, boxes)
            if ok_geometry:
                valid_matches.append(candidate)
        if not valid_matches:
            return False, f"target found but geometry cross-check failed: {text}", {"matches": [m.to_dict() for m in matches]}
        match = max(valid_matches, key=lambda m: (m.score, len(m.boxes), -abs(m.anchor_x - sum(b.center_x for b in m.boxes) / len(m.boxes))))
        if not shutil.which("xdotool"):
            return False, "xdotool not found", match.to_dict()
        try:
            # OCR coordinates are local to the captured window; xdotool expects
            # root/screen coordinates. Translate using the observed window origin.
            # Verify geometry once more after OCR. Window managers can move or
            # resize a window while OCR is running; clicking with stale geometry
            # is a silent, high-risk failure.
            latest = self._find_window_by_id(window.window_id)
            if not latest:
                return False, "target window disappeared before click", match.to_dict()
            if not self._same_window(latest, window):
                return False, "target window changed before click", match.to_dict()
            # OCR coordinates belong to the exact geometry that was captured.
            # If the window moved/resized during OCR, recapture and resolve from
            # fresh pixels instead of translating stale coordinates.
            geometry_changed = (latest.x, latest.y, latest.width, latest.height) != (window.x, window.y, window.width, window.height)
            if geometry_changed:
                window = latest
                fresh_shot = f"/tmp/v7_gui_click_{self.step:03d}_{time.time_ns()}_fresh.png"
                if not self._capture(window.window_id, fresh_shot):
                    return False, "window geometry changed and recapture failed", match.to_dict()
                fresh_boxes = self._ocr_boxes(fresh_shot)
                fresh_matches = resolve_text(text, fresh_boxes)
                if not fresh_matches:
                    return False, "window geometry changed and target disappeared", match.to_dict()
                fresh_valid = [m for m in fresh_matches if validate_match(m, fresh_boxes)[0]]
                if not fresh_valid:
                    return False, "window geometry changed and geometry cross-check failed", match.to_dict()
                match = max(fresh_valid, key=lambda m: (m.score, len(m.boxes), -abs(m.anchor_x - sum(b.center_x for b in m.boxes) / len(m.boxes))))
                shot = fresh_shot
            else:
                window = latest
            if not (0 <= match.anchor_x < window.width and 0 <= match.anchor_y < window.height):
                return False, "anchor outside target window", match.to_dict()
            screen_x = int(window.x) + int(match.anchor_x)
            screen_y = int(window.y) + int(match.anchor_y)
            subprocess.run(["xdotool", "mousemove", str(screen_x), str(screen_y), "click", "1"], check=True, timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"mouse click failed: {exc}", match.to_dict()
        evidence = match.to_dict(); evidence["screenshot"] = shot; evidence["screen_x"] = screen_x; evidence["screen_y"] = screen_y; evidence["window_x"] = window.x; evidence["window_y"] = window.y
        self.history.append({"step": self.step, "kind": "CLICK", "target": text, "evidence": evidence, "verified": False})
        return True, f"clicked {text} at ({match.anchor_x},{match.anchor_y}) via {match.anchor_kind}", evidence

    @staticmethod
    def _normalize_for_locator(text: str) -> str:
        return re.sub(r"\s+", "", str(text or "")).casefold()

    def find_input_anchor(self, window: WindowSnapshot | None = None, labels=("输入消息", "发消息", "输入内容", "搜索")) -> tuple[int, int] | None:
        """Locate an input control only from fresh OCR evidence.

        This is intentionally fail-closed: an empty region is not treated as an
        input box. The caller must observe a visible input/search affordance first.
        """
        window = window or self._active_window(self._windows())
        if not window or not self._same_window(self._active_window(self._windows()), window):
            return None
        shot = f"/tmp/v7_gui_input_{self.step:03d}_{time.time_ns()}.png"
        if not self._capture(window.window_id, shot):
            return None
        boxes = self._ocr_boxes(shot)
        wanted = {str(x).casefold() for x in labels if str(x).strip()}
        candidates = []
        for b in boxes:
            value = self._normalize_for_locator(b.text)
            if not value:
                continue
            if value in wanted or any(w and (w in value or value in w) for w in wanted):
                candidates.append(b)
        if not candidates:
            return None
        # Prefer explicit message-input labels over generic search labels.
        def rank(b):
            v = self._normalize_for_locator(b.text)
            message = 2 if any(k in v for k in ("输入消息", "发消息", "输入内容")) else 0
            return (message, b.confidence, -b.center_y)
        chosen = max(candidates, key=rank)
        return (chosen.center_x, chosen.center_y)

    def type_text_local(self, text: str, window: WindowSnapshot | None = None, input_anchor: tuple[int, int] | None = None) -> tuple[bool, str]:
        """Type content without treating destructive words inside the content as a destructive action."""
        from .safety import typing_allowed
        if not typing_allowed(text):
            return False, "typing blocked by safety policy"
        window = window or self._active_window(self._windows())
        if not window or not self.activate(window):
            return False, "target window is not active"
        verified = self._active_window(self._windows())
        if not self._same_window(verified, window):
            return False, "target window activation could not be verified"
        if input_anchor is None:
            return False, "input focus evidence required; refusing blind typing"
        ax, ay = int(input_anchor[0]), int(input_anchor[1])
        if not (0 <= ax < window.width and 0 <= ay < window.height):
            return False, "input anchor outside target window"
        screen_x, screen_y = int(window.x) + ax, int(window.y) + ay
        try:
            subprocess.run(["xdotool", "mousemove", str(screen_x), str(screen_y), "click", "1"], check=True, timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            verified = self._active_window(self._windows())
            if not self._same_window(verified, window):
                return False, "target window lost focus before typing"
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"input focus click failed: {exc}"
        if not shutil.which("xdotool"):
            return False, "xdotool not found"
        try:
            subprocess.run(["xdotool", "type", "--delay", "1", str(text)], check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"text input failed: {exc}"
        self.history.append({"step": self.step, "kind": "TYPE_TEXT", "chars": len(str(text)), "verified": False})
        return True, "text typed; caller must re-observe to verify"

    def call_web_gpt(self, prompt: str, caller=None) -> str:
        """Explicit text-only escape hatch for ordinary web GPT.

        The contract rejects image payloads/paths so GUI evidence remains cheap.
        """
        if self.llm_calls >= self.llm_budget:
            raise RuntimeError("web GPT budget exhausted/disabled for GUI phase")
        if caller is None:
            raise RuntimeError("web GPT caller not configured")
        if any(token in str(prompt).lower() for token in ("/tmp/v7_gui_", "data:image", "base64,")):
            raise ValueError("GUI screenshots are forbidden in web-GPT prompts; use text evidence")
        started = time.monotonic()
        self.llm_calls += 1
        try:
            return str(caller(str(prompt)))
        finally:
            self.llm_time_total += time.monotonic() - started

    def text_reasoning_prompt(self, goal: str, phase: str = "GUI",
                              current_state: str = "", action_result: str = "",
                              test_output: str = "") -> str:
        observations = [h.get("ocr", "") for h in self.history if h.get("kind") == "OBSERVE"]
        files = []
        return TextReasoningContext(
            goal=goal, phase=phase, observations=[x[:2000] for x in observations if x],
            current_state=current_state, action_result=action_result, test_output=test_output,
            files=files, constraints=["no screenshots", "no irreversible business actions", "use observed evidence only"],
        ).render()

    def click_text(self, text: str) -> tuple[bool, str]:
        if not reversible_target(text):
            return False, "blocked by safety policy"
        page_key = self.snapshots[-1].fingerprint() if self.snapshots else ""
        click_key = (page_key, text.casefold())
        if click_key in self._clicked_labels:
            return False, "already explored on current observed page"
        ok, msg, evidence = self.click_text_local(text)
        self.timings.append({"operation": "click_text_local", "direct": True, "anchor": evidence.get("anchor_kind", "")})
        if ok:
            self._clicked_labels.add(click_key)
            return True, msg
        # Test/integration escape hatch: an injected router can still be used
        # when the host provides its own computer tool. The default package
        # never requires that router.
        if self._router is not None:
            try:
                result = self._router.call("click_text_local", {"text": text})
                result_text = str(result)
                failed = "失败" in result_text or "error" in result_text.casefold() or "不存在" in result_text
                if not failed:
                    self._clicked_labels.add(click_key)
                    return True, result_text
            except Exception as exc:
                msg = f"{msg}; router fallback: {exc}"
        return False, msg

    def transition(self, before: GUISnapshot, action: str, after: GUISnapshot, verified: bool) -> None:
        self.model.connect(before, action, after, verified)
        self.history.append({
            "step": self.step, "kind": "TRANSITION", "action": action,
            "before": before.fingerprint(), "after": after.fingerprint(), "verified": bool(verified),
        })
