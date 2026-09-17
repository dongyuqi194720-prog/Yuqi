from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from launcher.browser_manager import BrowserManager
from launcher.diagnostics import check_codex_bridge, check_python


def _print_event(name, status, detail=""):
    event = {
        "time": datetime.now(timezone.utc).isoformat(),
        "event": name,
        "status": status,
    }

    if detail:
        event["detail"] = detail

    print(
        json.dumps(
            event,
            ensure_ascii=False,
        )
    )


def main():
    _print_event(
        "START",
        "BEGIN",
        "launcher startup",
    )

    checks = [
        check_python(),
        check_codex_bridge(),
    ]

    for check in checks:
        _print_event(
            check["name"],
            check["status"],
            check["detail"],
        )

        if check["status"] != "PASS":
            _print_event(
                "START",
                "STOP",
                "startup preflight failed",
            )
            return 1

    browser = BrowserManager()

    _print_event(
        "browser",
        "CHECK",
        "checking existing Chromium/CDP",
    )

    state = browser.wait_until_ready(
        timeout=5.0,
        interval=0.25,
    )

    if state["status"] != "READY":
        _print_event(
            "browser",
            "STOP",
            "CDP or ChatGPT page unavailable",
        )
        _print_event(
            "START",
            "STOP",
            "browser preflight failed",
        )
        return 1

    page = state["page"]

    _print_event(
        "cdp",
        "PASS",
        "existing Chromium/CDP reused",
    )

    _print_event(
        "chatgpt_page",
        "PASS",
        {
            "title": page.get("title"),
            "url": page.get("url"),
            "id": page.get("id"),
        },
    )

    _print_event(
        "START",
        "READY",
        "all startup checks passed; existing browser reused",
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
