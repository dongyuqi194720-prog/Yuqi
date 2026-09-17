from __future__ import annotations

import time
from typing import Optional

import requests


CDP_BASE = "http://127.0.0.1:9222"


class BrowserManager:
    """Safe Chromium/CDP manager.

    Phase 4 intentionally supports detection and reuse first.
    It never kills an existing browser.
    """

    def __init__(self, cdp_base: str = CDP_BASE):
        self.cdp_base = cdp_base.rstrip("/")

    def _get(self, path: str):
        return requests.get(
            self.cdp_base + path,
            proxies={"http": None, "https": None},
            timeout=3,
        )

    def cdp_available(self) -> bool:
        try:
            response = self._get("/json/version")
            response.raise_for_status()
            data = response.json()
            return bool(
                data.get("Browser")
                and data.get("webSocketDebuggerUrl")
            )
        except Exception:
            return False

    def chatgpt_page(self) -> Optional[dict]:
        try:
            response = self._get("/json/list")
            response.raise_for_status()

            pages = response.json()

            for page in pages:
                if page.get("type") != "page":
                    continue

                url = str(page.get("url") or "")

                if not url.startswith(
                    (
                        "https://chatgpt.com/",
                        "https://chat.openai.com/",
                    )
                ):
                    continue

                if not page.get("webSocketDebuggerUrl"):
                    continue

                return page

        except Exception:
            return None

        return None

    def status(self) -> dict:
        cdp = self.cdp_available()
        page = self.chatgpt_page() if cdp else None

        if page:
            return {
                "status": "READY",
                "cdp": True,
                "chatgpt": True,
                "page": page,
            }

        return {
            "status": "STOP",
            "cdp": cdp,
            "chatgpt": False,
            "page": None,
        }

    def wait_until_ready(
        self,
        timeout: float = 15.0,
        interval: float = 0.25,
    ) -> dict:
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            state = self.status()

            if state["status"] == "READY":
                return state

            time.sleep(interval)

        return self.status()


if __name__ == "__main__":
    manager = BrowserManager()
    print(manager.status())
