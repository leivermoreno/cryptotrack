#!/usr/bin/env bash
#
# verify_setup.sh — confirm a fresh CryptoTrack checkout is correctly configured.
#
# Runs the same steps a new contributor performs after Installation, in order,
# and stops at the first failure so the broken step is obvious:
#
#   1. manage.py check            — settings import + system checks pass
#   2. manage.py migrate          — database reachable, migrations apply
#   3. manage.py createcachetable — DB-backed cache table exists (idempotent)
#   4. manage.py test             — the suite passes against real PostgreSQL
#
# Every step is idempotent, so this is safe to re-run. Runs in DEBUG by default
# (DJANGO_DEBUG defaults to true below) so a fresh checkout needs no secrets;
# SECRET_KEY/ALLOWED_HOSTS/CSRF_TRUSTED_ORIGINS are required only in production
# (DJANGO_DEBUG unset/false — see README). Requires a running PostgreSQL instance
# with the privileges from Installation step 2.
#
# Usage:
#   scripts/verify_setup.sh            # full verification
#   scripts/verify_setup.sh coins      # pass args through to `manage.py test`
#
set -euo pipefail

# Resolve the project root from this script's location so it works from any cwd.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Fresh-checkout convenience: run in DEBUG unless the caller opts out. Keeps a
# no-.env checkout running check/test without requiring production secrets.
# Override with DJANGO_DEBUG=false to exercise the production import path.
export DJANGO_DEBUG="${DJANGO_DEBUG:-true}"

# Prefer the checked-in virtualenv interpreter; fall back to whatever `python`
# is active (e.g. an already-activated venv).
if [[ -x "$ROOT_DIR/venv/bin/python" ]]; then
    PYTHON="$ROOT_DIR/venv/bin/python"
else
    PYTHON="python"
fi

step() {
    printf '\n\033[1;34m==> %s\033[0m\n' "$1"
}

step "1/4 manage.py check"
"$PYTHON" manage.py check

step "2/4 manage.py migrate"
"$PYTHON" manage.py migrate

step "3/4 manage.py createcachetable"
"$PYTHON" manage.py createcachetable

step "4/4 manage.py test"
"$PYTHON" manage.py test "$@"

printf '\n\033[1;32m✓ Setup verified.\033[0m\n'
