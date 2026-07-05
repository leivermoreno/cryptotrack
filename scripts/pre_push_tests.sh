#!/usr/bin/env bash
#
# Run the Django suite from pre-commit's pre-push hook.
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -x "$ROOT_DIR/venv/bin/python" ]]; then
    PYTHON="$ROOT_DIR/venv/bin/python"
else
    PYTHON="python"
fi

exec "$PYTHON" manage.py test --noinput
