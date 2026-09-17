from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CODEX_BRIDGE = PROJECT_ROOT / "codex_bridge.py"

EXPECTED_CODEX_BRIDGE_SHA256 = (
    "062a15572b12583aae9e1005e9409769a05c204f04ca6017ae68b37d9c5df662"
)

CDP_BASE = "http://127.0.0.1:9222"


def _check(name, ok, detail):
    return {
        "name": name,
        "status": "PASS" if ok else "STOP",
        "detail": str(detail),
    }


def check_python():
    version = sys.version.split()[0]
    return _check(
        "python",
        sys.version_info >= (3, 8),
        version,
    )


def check_codex_bridge():
    if not CODEX_BRIDGE.is_file():
        return _check(
            "codex_bridge",
            False,
            "codex_bridge.py not found",
        )

    digest = hashlib.sha256(
        CODEX_BRIDGE.read_bytes()
    ).hexdigest()

    return _check(
        "codex_bridge",
        digest == EXPECTED_CODEX_BRIDGE_SHA256,
        digest,
    )


def _request(path):
    return requests.get(
        CDP_BASE + path,
        proxies={"http": None, "https": None},
        timeout=3,
    )


def check_cdp():
    try:
        response = _request("/json/version")
        response.raise_for_status()
        data = response.json()
        browser = data.get("Browser", "")
        return _check(
            "cdp",
            bool(browser and data.get("webSocketDebuggerUrl")),
            browser,
        )
    except Exception as exc:
        return _check("cdp", False, repr(exc))


def check_chatgpt_page():
    try:
        response = _request("/json/list")
        response.raise_for_status()
        pages = response.json()

        chatgpt_pages = [
            page
            for page in pages
            if page.get("type") == "page"
            and str(page.get("url", "")).startswith(
                (
                    "https://chatgpt.com/",
                    "https://chat.openai.com/",
                )
            )
            and page.get("webSocketDebuggerUrl")
        ]

        if not chatgpt_pages:
            return _check(
                "chatgpt_page",
                False,
                "no ChatGPT page with CDP websocket",
            )

        page = chatgpt_pages[0]

        return _check(
            "chatgpt_page",
            True,
            {
                "title": page.get("title"),
                "url": page.get("url"),
                "id": page.get("id"),
            },
        )
    except Exception as exc:
        return _check(
            "chatgpt_page",
            False,
            repr(exc),
        )


def run_all():
    checks = [
        check_python(),
        check_codex_bridge(),
        check_cdp(),
        check_chatgpt_page(),
    ]

    ready = all(
        item["status"] == "PASS"
        for item in checks
    )

    return {
        "status": "READY" if ready else "STOP",
        "checks": checks,
    }


if __name__ == "__main__":
    print(
        json.dumps(
            run_all(),
            ensure_ascii=False,
            indent=2,
        )
    )
