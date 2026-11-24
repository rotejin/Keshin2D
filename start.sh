#!/bin/sh
# Keshin2D: open the avatar viewer in the browser (Google Chrome if installed, otherwise the default browser).
# Usage: ./start.sh [--model NAME] [--port N]
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then exec python3 tools/serve.py "$@"; fi
if command -v python >/dev/null 2>&1; then exec python tools/serve.py "$@"; fi
echo "Python 3.8 or later was not found." >&2
exit 1
