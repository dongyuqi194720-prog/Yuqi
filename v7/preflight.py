from __future__ import annotations
import os, shutil, subprocess, sys
from dataclasses import dataclass, asdict

@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def _cmd(name: str) -> Check:
    p = shutil.which(name)
    return Check(name, bool(p), p or f'{name} not found')


def run() -> dict:
    checks = [_cmd('python3'), _cmd('wmctrl'), _cmd('xprop')]
    checks.append(Check('DISPLAY', bool(os.environ.get('DISPLAY')), os.environ.get('DISPLAY','unset')))
    if os.environ.get('DISPLAY') and shutil.which('wmctrl'):
        try:
            p = subprocess.run(['wmctrl','-m'], text=True, capture_output=True, timeout=3)
            detail = (p.stdout or p.stderr).strip().splitlines()[0] if (p.stdout or p.stderr).strip() else 'wmctrl probe'
            checks.append(Check('GUI_ACCESS', p.returncode == 0, detail))
        except Exception as exc:
            checks.append(Check('GUI_ACCESS', False, str(exc)))
    else:
        checks.append(Check('GUI_ACCESS', False, 'DISPLAY or wmctrl unavailable'))
    # Optional tools: V7 can install/headless-test without them, but full OCR capture needs them.
    checks.append(_cmd('tesseract'))
    checks[-1].required = False
    checks.append(_cmd('import'))
    checks[-1].required = False
    required_ok = all(c.ok for c in checks if c.required)
    return {'ok': required_ok, 'checks': [asdict(c) for c in checks], 'python': sys.version.split()[0]}


def main() -> int:
    result = run()
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 2

if __name__ == '__main__':
    raise SystemExit(main())
