#!/usr/bin/env bash
#
# The master gate.
#
# Everything that has to be green before a change is finished.  The agents
# work in parallel on their own files; this script is the single place that
# decides whether the result may be shipped.
#
#   scripts/master.sh              # everything
#   scripts/master.sh --quick      # without the packaging step
#   scripts/master.sh --package    # only the packaging step
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="$HOME/.local/bin:$HOME/.local/node/bin:$HOME/.cargo/bin:$PATH"

QUICK=0
PACKAGE=0
for arg in "$@"; do
  case "$arg" in
    --quick) QUICK=1 ;;
    --package) PACKAGE=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

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

api_tests() { (cd apps/api && ../../.venv/bin/python -m pytest -q); }
api_lint() { (cd apps/api && ../../.venv/bin/python -m ruff check app tests scripts); }
api_smoke() { (cd apps/api && ../../.venv/bin/python scripts/smoke_core.py | tail -3); }
acceptance() { ./.venv/bin/python scripts/acceptance.py; }
browser_check() { ./.venv/bin/python scripts/check_browser_automation.py; }
desktop_check() { (cd apps/desktop && ../../.venv/bin/python scripts/check-desktop.py); }
desktop_offline_check() { (cd apps/desktop && ../../.venv/bin/python scripts/check-offline.py); }
web_build() { (cd apps/web && npm run build); }
desktop_build() { (cd apps/desktop && npm run build); }
ui_check() { ./.venv/bin/python scripts/check_add_website_ui.py; }
automation_ui_check() { ./.venv/bin/python scripts/check_automation_ui.py; }
migrations() {
  local db; db="$(mktemp -d)/m.db"
  (cd apps/api && AUTOBL_DATABASE_URL="sqlite:///$db" ../../.venv/bin/python -m alembic upgrade head \
    && AUTOBL_DATABASE_URL="sqlite:///$db" ../../.venv/bin/python -m alembic downgrade base \
    && AUTOBL_DATABASE_URL="sqlite:///$db" ../../.venv/bin/python -m alembic upgrade head)
}
package_desktop() {
  # The .app bundle is built by Tauri; the disk image is created afterwards
  # with `build-dmg.sh` (plain hdiutil) because the Tauri step needs the
  # Finder via AppleScript, which is not available on a headless machine.
  (cd apps/desktop && npm run backend) \
    && (cd apps/desktop && npx tauri build --target universal-apple-darwin --bundles app) \
    && (cd apps/desktop && bash scripts/build-dmg.sh \
        --app src-tauri/target/universal-apple-darwin/release/bundle/macos/"Auto Backlinker.app" \
        --output src-tauri/target/universal-apple-darwin/release/bundle/dmg/"Auto Backlinker_1.0.0_universal.dmg") \
    && rm -rf release/macos \
    && mkdir -p release/macos \
    && cp -R apps/desktop/src-tauri/target/universal-apple-darwin/release/bundle/macos/"Auto Backlinker.app" release/macos/ \
    && cp apps/desktop/src-tauri/target/universal-apple-darwin/release/bundle/dmg/"Auto Backlinker_1.0.0_universal.dmg" release/macos/
}

if [[ "$PACKAGE" == "0" ]]; then
  step "API lint" api_lint
  step "API tests" api_tests
  step "API smoke" api_smoke
  step "Migrations (up / down / up)" migrations
  step "Acceptance - the complete product loop" acceptance
  step "Browser automation (real Chromium)" browser_check
  step "Web production build" web_build
  step "Desktop production build" desktop_build
fi

# The user interface checks need a running backend and a running web client.
if [[ "$QUICK" == "0" ]]; then
  echo ""
  echo "=== Starting the API and the web client for the interface checks ==="
  (cd apps/api && AUTOBL_DATA_DIR="$(mktemp -d)" nohup ../../.venv/bin/python -m uvicorn app.main:app \
    --host 127.0.0.1 --port 8000 >/tmp/master_api.log 2>&1 &)
  (cd apps/web && nohup npm run dev >/tmp/master_web.log 2>&1 &)
  for _ in $(seq 1 40); do
    if curl -s -o /dev/null --max-time 2 http://127.0.0.1:8000/health \
      && curl -s -o /dev/null --max-time 2 http://localhost:3000/login; then
      break
    fi
    sleep 2
  done
  ./.venv/bin/python scripts/seed_demo.py >/dev/null 2>&1 || true

  step "Web client UI check" ui_check
  step "Automation UI check" automation_ui_check

  echo ""
  echo "=== Stopping the development servers ==="
  /usr/bin/pkill -f "next dev" >/dev/null 2>&1 || true
  /usr/bin/pkill -f "uvicorn app.main:app" >/dev/null 2>&1 || true
fi

if [[ "$QUICK" == "0" || "$PACKAGE" == "1" ]]; then
  step "Package the universal macOS app" package_desktop
fi

# The packaged checks run last - they test the artifact that was just built.
if [[ "$QUICK" == "0" ]]; then
  step "Desktop app (packaged)" desktop_check
  step "Desktop runs completely offline" desktop_offline_check
fi

echo ""
echo "======================= MASTER GATE ======================="
for line in "${RESULTS[@]}"; do
  echo "  $line"
done
echo "==========================================================="
exit $FAILED
