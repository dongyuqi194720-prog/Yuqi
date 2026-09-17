from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from launcher.browser_manager import BrowserManager
from launcher.diagnostics import check_codex_bridge, check_python


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX_FILE = PROJECT_ROOT / "ui" / "templates" / "index.html"


def get_status():
    checks = [
        check_python(),
        check_codex_bridge(),
    ]

    browser = BrowserManager()
    browser_state = browser.status()

    checks.append(
        {
            "name": "cdp",
            "status": "PASS"
            if browser_state["cdp"]
            else "STOP",
            "detail": "Chromium/CDP available"
            if browser_state["cdp"]
            else "CDP unavailable",
        }
    )

    checks.append(
        {
            "name": "chatgpt_page",
            "status": "PASS"
            if browser_state["chatgpt"]
            else "STOP",
            "detail": (
                browser_state["page"]
                if browser_state["chatgpt"]
                else "ChatGPT page unavailable"
            ),
        }
    )

    ready = all(
        check["status"] == "PASS"
        for check in checks
    )

    return {
        "status": "READY" if ready else "STOP",
        "checks": checks,
    }


class UIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/status":
            body = json.dumps(
                get_status(),
                ensure_ascii=False,
            ).encode("utf-8")

            self.send_response(200)
            self.send_header(
                "Content-Type",
                "application/json; charset=utf-8",
            )
            self.send_header(
                "Content-Length",
                str(len(body)),
            )
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path not in ("/", "/index.html"):
            self.send_response(404)
            self.end_headers()
            return

        body = INDEX_FILE.read_bytes()

        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(body)),
        )
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def run(host="127.0.0.1", port=8765):
    server = HTTPServer((host, port), UIHandler)

    print(
        "AI Agent UI READY:",
        "http://%s:%d" % (host, port),
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
