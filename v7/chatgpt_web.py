from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path


class ChatGPTWebReasoner:
    """Use the real ChatGPT webpage as the reasoning engine."""

    # SEND GUARD: a message may be sent only after this round's full
    # unique marker is verified in the ChatGPT input area.
    SEND_MARKER_PREFIX = "V7_DONGYUQI_"

    ACTIONS = (
        "LIST_FILES",
        "READ_FILE",
        "WRITE_FILE",
        "DELETE_FILE",
        "RUN_COMMAND",
        "OBSERVE_GUI",
        "OBSERVE_DESKTOP",
        "FIND_WINDOW",
        "WAIT_FOR_WINDOW",
        "LAUNCH_APP",
        "ACTIVATE_WINDOW",
        "CLICK_TEXT",
        "TYPE_TEXT",
        "DONE",
    )

    ACTION_RE = re.compile(
        r"ACTION:\s*(?:" + "|".join(ACTIONS) + r")\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        window_id: str | None = None,
        ocr_lang: str = "chi_sim+eng",
    ):
        self.display = os.environ.get("DISPLAY", ":0")
        self.window_id = window_id
        self.ocr_lang = ocr_lang
        self.request_counter = 0

    def find_window(self) -> str:
        if self.window_id:
            return self.window_id

        result = subprocess.run(
            ["wmctrl", "-lxG"],
            text=True,
            capture_output=True,
            env={**os.environ, "DISPLAY": self.display},
            check=False,
        )

        candidates = []
        for line in result.stdout.splitlines():
            parts = line.split(None, 7)
            if len(parts) >= 7:
                window_id = parts[0]
                wm_class = parts[6]
                title = parts[7] if len(parts) >= 8 else ""
                if "chromium" in wm_class.lower():
                    candidates.append((window_id, title))

        for window_id, _title in candidates:
            try:
                text = self._read_window_text(window_id)
            except Exception:
                continue

            if "chatgpt" in text.lower():
                self.window_id = window_id
                return window_id

        raise RuntimeError("ChatGPT Chromium window not found")

    def _read_window_text(self, window_id: str) -> str:
        with tempfile.NamedTemporaryFile(
            prefix="v7_chatgpt_probe_",
            suffix=".png",
            delete=False,
        ) as handle:
            screenshot = Path(handle.name)

        try:
            subprocess.run(
                [
                    "import",
                    "-window",
                    window_id,
                    str(screenshot),
                ],
                text=True,
                capture_output=True,
                env={**os.environ, "DISPLAY": self.display},
                check=True,
            )

            result = subprocess.run(
                [
                    "tesseract",
                    str(screenshot),
                    "stdout",
                    "-l",
                    self.ocr_lang,
                    "--psm",
                    "11",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            return result.stdout.strip()
        finally:
            screenshot.unlink(missing_ok=True)

    def read_text(self) -> str:
        return self._read_window_text(self.find_window())

    def _new_request_id(self) -> str:
        self.request_counter += 1
        return f"V7-{self.request_counter:04d}-{uuid.uuid4().hex[:8]}"

    def _build_prompt(self, prompt: str, request_id: str) -> str:
        return (
            f"{prompt}\n\n"
            "你必须严格遵守下面的通信协议。\n"
            f"本轮请求编号：{request_id}\n"
            "你的回复必须包含且只包含本轮协议结果，格式如下：\n"
            f"V7_REQUEST_ID: {request_id}\n"
            "ACTION: <一个合法 ACTION>\n"
            "如果 ACTION 需要参数，继续按协议字段输出。\n"
            "不要输出 Markdown 代码围栏，不要解释，不要输出其他 ACTION。\n"
            "如果任务完成，输出：\n"
            f"V7_REQUEST_ID: {request_id}\n"
            "ACTION: DONE\n"
        )

    def _read_input_text(self, window_id: str) -> str:
        """Read the exact current ChatGPT input text via X clipboard."""
        env = {**os.environ, "DISPLAY": self.display}

        # Never trust the caller's current focus. Re-activate Chromium and
        # explicitly focus the ChatGPT input before reading its contents.
        subprocess.run(
            ["xdotool", "windowactivate", "--sync", window_id],
            env=env,
            check=True,
        )
        time.sleep(0.3)

        geometry = subprocess.check_output(
            ["xdotool", "getwindowgeometry", "--shell", window_id],
            env=env,
            text=True,
        )
        values = {}
        for line in geometry.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = int(value)

        input_x = values["WIDTH"] // 2
        input_y = values["HEIGHT"] - 20

        subprocess.run(
            ["xdotool", "mousemove", "--window", window_id,
             str(input_x), str(input_y)],
            env=env,
            check=True,
        )
        subprocess.run(
            ["xdotool", "click", "1"],
            env=env,
            check=True,
        )
        time.sleep(0.3)

        subprocess.run(
            ["xdotool", "key", "--window", window_id, "ctrl+a"],
            env=env,
            check=True,
        )
        subprocess.run(
            ["xdotool", "key", "--window", window_id, "ctrl+c"],
            env=env,
            check=True,
        )
        time.sleep(0.3)

        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.update()
        try:
            return root.clipboard_get()
        finally:
            root.destroy()

    def send_message(self, prompt: str) -> str:
        """Send text only after exact input-box verification."""
        request_id = self._new_request_id()
        input_marker = f"{self.SEND_MARKER_PREFIX}{uuid.uuid4().hex[:8].upper()}"
        full_prompt = self._build_prompt(prompt, request_id) + "\n" + input_marker

        window_id = self.find_window()
        env = {**os.environ, "DISPLAY": self.display}

        subprocess.run(
            ["xdotool", "windowactivate", "--sync", window_id],
            env=env,
            check=True,
        )
        time.sleep(0.5)

        # Focus the ChatGPT input area using the current window geometry.
        geometry = subprocess.check_output(
            ["xdotool", "getwindowgeometry", "--shell", window_id],
            env=env,
            text=True,
        )
        values = {}
        for line in geometry.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = int(value)

        width = values["WIDTH"]
        height = values["HEIGHT"]
        input_x = width // 2
        input_y = height - 20

        subprocess.run(
            ["xdotool", "mousemove", "--window", window_id,
             str(input_x), str(input_y)],
            env=env,
            check=True,
        )
        subprocess.run(
            ["xdotool", "click", "1"],
            env=env,
            check=True,
        )
        time.sleep(0.3)

        subprocess.run(
            ["xdotool", "type", "--window", window_id, "--delay", "1", full_prompt],
            env=env,
            check=True,
        )
        time.sleep(0.5)

        # IRON RULE:
        # Never send unless the exact complete text is read back from
        # the ChatGPT input box. No OCR fallback, timeout fallback,
        # coordinate fallback, or unconditional send is permitted.
        try:
            actual_text = self._read_input_text(window_id)
        except Exception as exc:
            raise RuntimeError(
                f"ChatGPT input verification failed; SEND FORBIDDEN: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        if actual_text != full_prompt:
            raise RuntimeError(
                "ChatGPT input verification failed; SEND FORBIDDEN: "
                "input text does not exactly match the generated request"
            )

        if input_marker not in actual_text:
            raise RuntimeError(
                "ChatGPT input verification failed; SEND FORBIDDEN: "
                f"complete marker missing: {input_marker}"
            )

        # Marker was verified from the exact input-box contents.
        # Only now is the send-button click permitted.
        send_x = width - 56
        send_y = height - 20

        subprocess.run(
            ["xdotool", "mousemove", "--window", window_id,
             str(send_x), str(send_y)],
            env=env,
            check=True,
        )
        subprocess.run(
            ["xdotool", "click", "1"],
            env=env,
            check=True,
        )

        return request_id

    def send(self, prompt: str) -> None:
        window_id = self.find_window()

        self.send_message(prompt)

    def extract_action(self, text: str, request_id: str) -> str:
        marker = f"V7_REQUEST_ID: {request_id}"

        positions = [
            m.start()
            for m in re.finditer(
                re.escape(marker),
                text,
                flags=re.IGNORECASE,
            )
        ]

        if not positions:
            raise RuntimeError(
                f"current request marker not found: {request_id}"
            )

        start = positions[-1]
        candidate = text[start:]

        match = self.ACTION_RE.search(candidate)
        if not match:
            raise RuntimeError(
                f"current request has no valid ACTION: {request_id}"
            )

        return candidate[match.start():].strip()

    def wait_for_action(
        self,
        request_id: str,
        timeout: float = 90.0,
        stable_seconds: float = 2.0,
    ) -> str:
        deadline = time.monotonic() + timeout
        last_action = ""
        stable_since = None

        while time.monotonic() < deadline:
            text = self.read_text()

            try:
                action_text = self.extract_action(text, request_id)
            except RuntimeError:
                time.sleep(1.0)
                continue

            if action_text == last_action:
                if stable_since is None:
                    stable_since = time.monotonic()
                elif time.monotonic() - stable_since >= stable_seconds:
                    return action_text
            else:
                last_action = action_text
                stable_since = time.monotonic()

            time.sleep(1.0)

        raise TimeoutError(
            f"ChatGPT webpage action timeout: {request_id}"
        )

    def __call__(self, prompt: str) -> str:
        request_id = self.send_message(prompt)
        return self.wait_for_action(request_id=request_id)
