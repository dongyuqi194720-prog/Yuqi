#!/usr/bin/env bash
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPECTED_BRIDGE_SHA256="062a15572b12583aae9e1005e9409769a05c204f04ca6017ae68b37d9c5df662"

echo "AI Agent installer"
echo "PROJECT_ROOT=$PROJECT_ROOT"

if [ ! -d "$PROJECT_ROOT" ]; then
    echo "INSTALL STOP: project root unavailable"
    exit 1
fi

PYTHON="$PROJECT_ROOT/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
    echo "INSTALL STOP: .venv/bin/python unavailable"
    exit 1
fi

for required in \
    VERSION \
    codex_bridge.py \
    start_agent.sh \
    launcher/start.py \
    launcher/browser_manager.py \
    launcher/diagnostics.py \
    ui/app.py \
    ui/templates/index.html
do
    if [ ! -f "$PROJECT_ROOT/$required" ]; then
        echo "INSTALL STOP: missing $required"
        exit 1
    fi
done

ACTUAL_BRIDGE_SHA256="$(
    sha256sum "$PROJECT_ROOT/codex_bridge.py" |
    awk '{print $1}'
)"

if [ "$ACTUAL_BRIDGE_SHA256" != "$EXPECTED_BRIDGE_SHA256" ]; then
    echo "INSTALL STOP: CodexBridge integrity mismatch"
    exit 1
fi

"$PYTHON" -m py_compile \
    "$PROJECT_ROOT/codex_bridge.py" \
    "$PROJECT_ROOT/launcher/start.py" \
    "$PROJECT_ROOT/launcher/browser_manager.py" \
    "$PROJECT_ROOT/launcher/diagnostics.py" \
    "$PROJECT_ROOT/ui/app.py"

if [ "$?" -ne 0 ]; then
    echo "INSTALL STOP: Python compile failed"
    exit 1
fi

chmod +x "$PROJECT_ROOT/start_agent.sh"

echo "INSTALL CHECK: PASS"
echo "VERSION=$(cat "$PROJECT_ROOT/VERSION")"
echo "CODEX_BRIDGE_SHA256=$ACTUAL_BRIDGE_SHA256"
echo "PYTHON=$("$PYTHON" --version 2>&1)"
echo "START_AGENT=READY"
echo "INSTALLER_BROWSER_ACTION=NONE"
echo "INSTALLER_SEND_ACTION=NONE"

exit 0
