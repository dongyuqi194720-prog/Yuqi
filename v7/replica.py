from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
from typing import Any

class ReplicaBuilder:
    def __init__(self, model: dict[str, Any], output: str | Path | None = None):
        self.model = model
        self.output = Path(output or Path.home() / "tongxin_fangzhi")

    def build(self) -> Path:
        self.output.mkdir(parents=True, exist_ok=True)
        for name in ("gui_model.json", "index.html", "app.py", "README.md"):
            if (self.output / name).is_symlink():
                raise RuntimeError(f"refusing to overwrite symlink: {name}")
        (self.output / "gui_model.json").write_text(json.dumps(self.model, ensure_ascii=False, indent=2), encoding="utf-8")
        pages = self.model.get("pages", [])
        cards = []
        for i, page in enumerate(pages, 1):
            controls = "".join(f'<button data-control="{_html(c)}">{_html(c)}</button>' for c in page.get("controls", [])[:40])
            cards.append(f'<section><h2>页面 {i}: {_html(page.get("title", "未命名"))}</h2><div class="controls">{controls}</div></section>')
        html = f'''<!doctype html><meta charset="utf-8"><title>同心共育仿制版</title>
<style>body{{font-family:sans-serif;margin:32px}}section{{border:1px solid #ddd;border-radius:12px;padding:18px;margin:14px 0}}button{{margin:4px;padding:8px 12px}}</style>
<h1>同心共育仿制版</h1><p>仅展示 V7 实际观察到的页面证据；未确认功能不会被编造。</p>{''.join(cards)}
<script>
const graph = __NAV__;
const pages = [...document.querySelectorAll('section')];
for (const b of document.querySelectorAll('button')) b.onclick=()=>{{
  document.title='已观察: '+b.dataset.control;
  b.dataset.state='observed';
}};
window.tongxinModel = {{pages: pages.length, navigation: graph}};
</script>'''
        html = html.replace('__NAV__', json.dumps(self.model.get('navigation', []), ensure_ascii=False))
        (self.output / "index.html").write_text(html, encoding="utf-8")
        (self.output / "app.py").write_text("""from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import os

ROOT=Path(__file__).parent
os.chdir(ROOT)
host = os.environ.get("V7_HOST", "127.0.0.1")
port = int(os.environ.get("V7_PORT", "8765"))
server = ThreadingHTTPServer((host, port), SimpleHTTPRequestHandler)
print(f"同心共育仿制版: http://{host}:{server.server_address[1]}")
server.serve_forever()
""", encoding="utf-8")
        (self.output / "README.md").write_text("# 同心共育仿制版\n\n由 V7 根据实际 GUI 观察证据生成。\n", encoding="utf-8")
        return self.output


    def text_context(self, max_chars: int = 9000) -> str:
        """Compact source/test context for a text-only reasoning pass."""
        chunks = []
        for name in ("app.py", "index.html", "README.md", "gui_model.json"):
            path = self.output / name
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace")
                chunks.append(f"FILE: {name}\n{text[:3500]}")
        return "\n\n".join(chunks)[:max_chars]

    def apply_text_patch(self, relative_path: str, content: str) -> tuple[bool, str]:
        """Apply a reasoner-supplied file replacement inside the replica only."""
        rel = Path(relative_path)
        if rel.is_absolute() or ".." in rel.parts or rel.name == "":
            return False, "unsafe patch path"
        if len(content.encode("utf-8")) > 100_000:
            return False, "patch too large"
        target = (self.output / rel).resolve()
        root = self.output.resolve()
        if root not in target.parents and target != root:
            return False, "patch escapes replica root"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.is_symlink():
            return False, "refusing to overwrite symlink"
        target.write_text(content, encoding="utf-8")
        return True, f"patched {rel.as_posix()}"
    def smoke_test(self) -> tuple[bool, str]:
        old_cwd = Path.cwd()
        server = None
        thread = None
        try:
            subprocess.run(
                [sys.executable, "-m", "py_compile", str(self.output / "app.py")],
                check=True, capture_output=True, text=True, timeout=10,
            )
            if not (self.output / "index.html").exists() or not (self.output / "gui_model.json").exists():
                return False, "replica artifacts missing"

            import http.client
            import os
            import threading
            import time
            from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

            os.chdir(self.output)

            class Quiet(SimpleHTTPRequestHandler):
                def log_message(self, *args):
                    pass

            # Bind directly to port 0. This avoids reserve/rebind races and
            # keeps the smoke test independent of HTTP_PROXY/HTTPS_PROXY.
            server = ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            last_error = "server did not become ready"
            for _ in range(20):
                conn = None
                try:
                    # http.client connects directly and never consults proxy env vars.
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                    conn.request("GET", "/index.html")
                    resp = conn.getresponse()
                    body = resp.read(4096).decode("utf-8", "replace")
                    if resp.status == 200 and "同心共育仿制版" in body:
                        return True, "replica compile + HTTP smoke test passed"
                    last_error = f"HTTP {resp.status}"
                except (OSError, http.client.HTTPException) as exc:
                    last_error = str(exc)
                finally:
                    if conn is not None:
                        conn.close()
                time.sleep(0.05)
            return False, f"replica HTTP smoke test failed: {last_error}"
        except Exception as exc:
            return False, str(exc)
        finally:
            if server is not None:
                try:
                    server.shutdown()
                except Exception:
                    pass
                try:
                    server.server_close()
                except Exception:
                    pass
            if thread is not None:
                try:
                    thread.join(timeout=2)
                except Exception:
                    pass
            try:
                os.chdir(old_cwd)
            except Exception:
                pass

def _html(value: Any) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))
