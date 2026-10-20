#!/usr/bin/env bash
#
# Bootstrap the Python environment of the Auto Backlinker API.
#
# The script is idempotent: running it again on an existing environment only
# refreshes the installed packages and re-applies the migrations.
#
#   apps/api/scripts/bootstrap.sh
#
# Environment variables:
#   AUTOBL_VENV              path of the virtual environment
#                            (default: <repo root>/.venv)
#   AUTOBL_PYTHON            interpreter used to create the environment
#                            (default: the newest python3.11+ on the PATH)
#   AUTOBL_SKIP_MIGRATIONS   set to 1 to skip "alembic upgrade head"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${API_DIR}/../.." && pwd)"

VENV_DIR="${AUTOBL_VENV:-${REPO_ROOT}/.venv}"
REQUIREMENTS="${API_DIR}/requirements.txt"
MIN_PYTHON="3.11"

# uv installs its binaries here - add it to the PATH when it exists.
export PATH="${HOME}/.local/bin:${PATH}"

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m==> %s\033[0m\n' "$*" >&2; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# --------------------------------------------------------------------------
# 0. Interpreter
# --------------------------------------------------------------------------
python_ok() {
  local candidate="$1"
  [ -x "${candidate}" ] || command -v "${candidate}" >/dev/null 2>&1 || return 1
  "${candidate}" -c "import sys; sys.exit(0 if sys.version_info[:2] >= tuple(int(p) for p in '${MIN_PYTHON}'.split('.')) else 1)" \
    >/dev/null 2>&1
}

find_python() {
  if [ -n "${AUTOBL_PYTHON:-}" ]; then
    if python_ok "${AUTOBL_PYTHON}"; then
      echo "${AUTOBL_PYTHON}"
      return 0
    fi
    die "AUTOBL_PYTHON=${AUTOBL_PYTHON} is not a Python ${MIN_PYTHON}+ interpreter"
  fi
  for candidate in python3.13 python3.12 python3.11 python3; do
    if python_ok "${candidate}"; then
      command -v "${candidate}"
      return 0
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python || true)"
if [ -z "${PYTHON_BIN}" ]; then
  die "no Python ${MIN_PYTHON}+ interpreter found (looked for python3.13, python3.12, python3.11, python3).
       Install one or set AUTOBL_PYTHON to the interpreter you want to use."
fi

# --------------------------------------------------------------------------
# 1. Virtual environment
# --------------------------------------------------------------------------
if [[ -x "${VENV_DIR}/bin/python" ]]; then
  log "reusing the virtual environment at ${VENV_DIR}"
else
  if command -v uv >/dev/null 2>&1; then
    log "creating the virtual environment at ${VENV_DIR} (uv)"
    uv venv --python "${PYTHON_BIN}" "${VENV_DIR}"
  else
    log "creating the virtual environment at ${VENV_DIR} (${PYTHON_BIN} -m venv)"
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  fi
fi

PY="${VENV_DIR}/bin/python"
[[ -x "${PY}" ]] || die "the virtual environment was not created (${PY} is missing)"

# --------------------------------------------------------------------------
# 2. Dependencies
# --------------------------------------------------------------------------
install_with_pip() {
  "${PY}" -m pip install --upgrade pip >/dev/null
  "${PY}" -m pip install -r "${REQUIREMENTS}"
}

install_requirements() {
  if "${PY}" -m pip --version >/dev/null 2>&1; then
    log "installing the requirements with pip"
    install_with_pip
    return
  fi
  # Some environments (uv, slim containers) ship a virtual environment
  # without pip - try to restore it before giving up.
  if "${PY}" -m ensurepip --version >/dev/null 2>&1; then
    log "restoring pip inside the virtual environment"
    "${PY}" -m ensurepip --upgrade >/dev/null
    install_with_pip
    return
  fi
  if command -v uv >/dev/null 2>&1; then
    log "installing the requirements with uv (pip is not available)"
    uv pip install --python "${PY}" -r "${REQUIREMENTS}"
    return
  fi
  die "neither pip nor uv is available - install the requirements manually"
}

install_requirements

# --------------------------------------------------------------------------
# 3. Database schema
# --------------------------------------------------------------------------
if [[ "${AUTOBL_SKIP_MIGRATIONS:-0}" == "1" ]]; then
  warn "skipping the migrations (AUTOBL_SKIP_MIGRATIONS=1)"
else
  log "applying the database migrations"
  (cd "${API_DIR}" && "${PY}" -m alembic upgrade head)
fi

# --------------------------------------------------------------------------
# 4. Next steps
# --------------------------------------------------------------------------
cat <<'EOF'

Setup complete.

Next steps:

  1. Start the API (from apps/api):

       ../../.venv/bin/python -m uvicorn app.main:app --reload --port 8000

     Then open http://localhost:8000/docs for the interactive API documentation.

  2. Start the background worker (from apps/api):

       ../../.venv/bin/python -m app.workers.runner

  3. Start the web client (from apps/web):

       npm install && npm run dev

  Notes:
    * The schema is created automatically for local / desktop use while
      AUTOBL_AUTO_CREATE_SCHEMA=true (the default).  Set it to false and run
      "scripts/migrate.sh" to manage the schema with Alembic only.
    * Copy .env.example to .env in the repository root to configure the
      database, the AI provider and the automation limits.

EOF
