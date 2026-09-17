#!/usr/bin/env bash
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT" || exit 1

if [ ! -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    echo "START STOP: Python virtual environment unavailable"
    exit 1
fi

exec "$PROJECT_ROOT/.venv/bin/python" -m launcher.start
