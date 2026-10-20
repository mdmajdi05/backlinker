#!/usr/bin/env bash
#
# Build the backend sidecar that is bundled with the desktop application.
#
#   scripts/build-sidecar.sh [--api-dir PATH] [--no-playwright]
#
# The result is written to:
#   src-tauri/binaries/autobacklinker-api-<target-triple>
#
# Tauri looks the binary up by that exact name (plus ".exe" on Windows), so the
# script has to be executed on every platform that is going to be shipped.
#
# Playwright
# ---------
# Browser automation needs the Playwright browsers. They are *not* bundled
# into the executable (they are ~400 MB). Two options:
#
#   1. Set PLAYWRIGHT_BROWSERS_PATH to a folder inside the bundle and copy the
#      browsers next to the app (see --playwright-path below).
#   2. Let the backend download the browsers on the first run:
#        AUTOBL_PLAYWRIGHT_BROWSERS_PATH=1 python -m playwright install chromium
#      The desktop build keeps this opt-in because it needs a network
#      connection and disk space.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="$(cd "${DESKTOP_DIR}/../.." && pwd)"
API_DIR="${REPO_DIR}/apps/api"
BINARIES_DIR="${DESKTOP_DIR}/src-tauri/binaries"
VENV_DIR="${DESKTOP_DIR}/.sidecar-venv"
PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-}"
INCLUDE_PLAYWRIGHT=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-dir) API_DIR="$2"; shift 2 ;;
    --no-playwright) INCLUDE_PLAYWRIGHT=0; shift ;;
    --playwright-path) PLAYWRIGHT_BROWSERS_PATH="$2"; shift 2 ;;
    -h|--help) sed -n '2,30p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

detect_triple() {
  local os arch
  case "$(uname -s)" in
    Darwin) os="apple-darwin" ;;
    Linux) os="unknown-linux-gnu" ;;
    MINGW*|MSYS*|CYGWIN*) os="pc-windows-msvc" ;;
    *) echo "Unsupported operating system: $(uname -s)" >&2; exit 1 ;;
  esac
  case "$(uname -m)" in
    arm64|aarch64) arch="aarch64" ;;
    x86_64|amd64) arch="x86_64" ;;
    *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
  esac
  echo "${arch}-${os}"
}

TRIPLE="$(detect_triple)"
EXT=""
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) EXT=".exe" ;;
esac

TARGET="${BINARIES_DIR}/autobacklinker-api-${TRIPLE}${EXT}"
echo "==> Building the backend sidecar for ${TRIPLE}"

if [[ ! -d "${API_DIR}/app" ]]; then
  echo "The API sources were not found in ${API_DIR}" >&2
  exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  # The backend needs CPython >= 3.11.  Prefer an explicit interpreter, then
  # the newest one we can find on this machine.
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      if "${candidate}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
        PYTHON_BIN="${candidate}"
        break
      fi
    fi
  done
fi
if [[ -z "${PYTHON_BIN}" ]]; then
  echo "No CPython >= 3.11 was found. Set PYTHON_BIN to a suitable interpreter." >&2
  exit 1
fi

if [[ ! -d "${VENV_DIR}/bin" ]]; then
  echo "==> Creating the build virtual environment (${VENV_DIR})"
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi
VENV_PY="${VENV_DIR}/bin/python"

echo "==> Installing the backend dependencies"
"${VENV_PY}" -m pip install --upgrade pip wheel >/dev/null
# The desktop bundle is SQLite only, therefore the PostgreSQL driver and the
# development tools are not part of the sidecar.  Everything else comes from
# the shared requirements file so the two never drift apart.
#
# Playwright (the Python package, not the browsers) is required at build
# time: PyInstaller analyses the imports of the backend, and the adapter
# package imports Playwright. Without it the dynamic provider imports
# (app/services/discovery/impl/*) would be missing from the bundle.
"${VENV_PY}" -m pip install \
  "fastapi" "uvicorn[standard]" "sqlalchemy>=2.0" "pydantic>=2.9" "pydantic-settings>=2.6" \
  "alembic>=1.14" "httpx>=0.27" "openpyxl>=3.1" "python-multipart>=0.0.12" "pyjwt>=2.9" \
  "email-validator>=2.2" "beautifulsoup4>=4.12" "lxml>=5.3" "tenacity>=9.0" "structlog>=24.4" \
  "playwright>=1.44"
"${VENV_PY}" -m pip install pyinstaller

mkdir -p "${BINARIES_DIR}"
BUILD_DIR="${DESKTOP_DIR}/.sidecar-build"
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

cat > "${BUILD_DIR}/sidecar.spec" <<EOF
# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_submodules

api_dir = os.environ.get("AUTOBL_API_DIR", "${API_DIR}")

# Every module of the backend package is collected explicitly: the API uses
# lazy imports inside functions, which the static analysis alone misses.
hiddenimports = collect_submodules("app") + [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "sqlalchemy.dialects.sqlite",
    "playwright.sync_api",
]

a = Analysis(
    ["${SCRIPT_DIR}/sidecar_launcher.py"],
    pathex=[api_dir],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="autobacklinker-api",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
EOF

echo "==> Running PyInstaller"
# A .spec file may not be combined with --specpath, the spec already lives in
# the build directory and defines the output paths itself.
# PYTHONPATH makes the backend package importable for the isolated
# subprocess that PyInstaller uses to collect the submodules.
AUTOBL_API_DIR="${API_DIR}" \
PYTHONPATH="${API_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
  "${VENV_PY}" -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath "${BUILD_DIR}/dist" \
  --workpath "${BUILD_DIR}/work" \
  "${BUILD_DIR}/sidecar.spec" >/dev/null

BUILT="${BUILD_DIR}/dist/autobacklinker-api${EXT}"
if [[ ! -f "${BUILT}" ]]; then
  echo "PyInstaller did not produce ${BUILT}" >&2
  exit 1
fi

cp "${BUILT}" "${TARGET}"
chmod +x "${TARGET}"
echo "==> Wrote ${TARGET}"

if [[ "${INCLUDE_PLAYWRIGHT}" == "1" ]]; then
  if [[ -n "${PLAYWRIGHT_BROWSERS_PATH}" ]]; then
    echo "==> Copying the Playwright browsers from ${PLAYWRIGHT_BROWSERS_PATH}"
    rm -rf "${BINARIES_DIR}/playwright-browsers"
    mkdir -p "${BINARIES_DIR}/playwright-browsers"
    cp -R "${PLAYWRIGHT_BROWSERS_PATH}/." "${BINARIES_DIR}/playwright-browsers/"
    echo "    Add \"binaries/playwright-browsers\" to bundle.resources in tauri.conf.json"
  else
    cat <<'EOF'

==> Playwright browsers are NOT bundled.
    Install them on the target machine with:
        python -m playwright install chromium
    or rebuild with:
        PLAYWRIGHT_BROWSERS_PATH=./.playwright-browsers scripts/build-sidecar.sh
EOF
  fi
fi

echo
echo "Done. The desktop bundle now contains:"
ls -la "${BINARIES_DIR}"
