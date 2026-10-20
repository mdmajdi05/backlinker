#!/usr/bin/env bash
# Master verification harness for the Auto Backlinker monorepo.
#
# Runs every check that can run on the current machine and prints a summary.
# Usage: scripts/verify_all.sh [--fast]
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
WEB_DIR="$ROOT/apps/web"
DESKTOP_DIR="$ROOT/apps/desktop"
RESULTS=()
FAILED=0

step() {
  local name="$1"; shift
  echo ""
  echo "=== $name ==="
  if "$@"; then
    RESULTS+=("PASS  $name")
  else
    RESULTS+=("FAIL  $name")
    FAILED=1
  fi
}

api_lint() {
  (cd "$ROOT/apps/api" && "$PY" -m ruff check app tests scripts)
}
api_import() {
  (cd "$ROOT/apps/api" && AUTOBL_DATA_DIR="$(mktemp -d)" "$PY" -c "from app.main import app; print(len(app.routes), 'routes registered')")
}
api_smoke() {
  local output
  output="$(cd "$ROOT/apps/api" && "$PY" scripts/smoke_core.py 2>&1)"
  local status=$?
  echo "$output" | grep -E "^\[(PASS|FAIL)\]" | tail -25
  if [ $status -ne 0 ]; then
    echo "smoke test exited with $status"
    return 1
  fi
  if echo "$output" | grep -q "^\[FAIL\]"; then
    return 1
  fi
  return 0
}
api_tests() {
  (cd "$ROOT/apps/api" && "$PY" -m pytest -q)
}
api_migrate() {
  local db
  db="$(mktemp -d)/migrate.db"
  (cd "$ROOT/apps/api" && AUTOBL_DATABASE_URL="sqlite:///$db" "$PY" -m alembic upgrade head \
    && AUTOBL_DATABASE_URL="sqlite:///$db" "$PY" -m alembic downgrade base \
    && AUTOBL_DATABASE_URL="sqlite:///$db" "$PY" -m alembic upgrade head)
}
web_typecheck() {
  (cd "$WEB_DIR" && npx tsc --noEmit)
}
web_build() {
  (cd "$WEB_DIR" && npm run build)
}
desktop_typecheck() {
  (cd "$DESKTOP_DIR" && npx tsc --noEmit)
}
desktop_build() {
  (cd "$DESKTOP_DIR" && npm run build)
}

export PATH="$HOME/.local/bin:$HOME/.local/node/bin:$PATH"

step "API lint (ruff)" api_lint
step "API import + route registration" api_import
step "API core smoke test" api_smoke
step "API database migrations (up/down/up)" api_migrate
if [ "${1:-}" != "--fast" ]; then
  step "API test suite (pytest)" api_tests
fi
if [ -d "$WEB_DIR/node_modules" ]; then
  step "Web typecheck" web_typecheck
  step "Web production build" web_build
else
  RESULTS+=("SKIP  Web typecheck (apps/web/node_modules missing)")
  RESULTS+=("SKIP  Web production build (apps/web/node_modules missing)")
fi
if [ -d "$DESKTOP_DIR/node_modules" ]; then
  step "Desktop typecheck" desktop_typecheck
  step "Desktop frontend build" desktop_build
else
  RESULTS+=("SKIP  Desktop typecheck (apps/desktop/node_modules missing)")
  RESULTS+=("SKIP  Desktop frontend build (apps/desktop/node_modules missing)")
fi

echo ""
echo "================ SUMMARY ================"
for line in "${RESULTS[@]}"; do
  echo "  $line"
done
echo "========================================="
exit $FAILED
