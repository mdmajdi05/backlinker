#!/usr/bin/env bash
#
# Apply the database migrations.
#
# Usage:
#   scripts/migrate.sh                 # upgrade to the latest revision
#   scripts/migrate.sh upgrade head
#   scripts/migrate.sh downgrade -1
#   scripts/migrate.sh current
#   scripts/migrate.sh history
#
# The database URL is taken from the application settings, i.e. from
# ``AUTOBL_DATABASE_URL`` or - when that variable is unset - from the local
# SQLite file in the application data directory.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${API_DIR}/../.." && pwd)"

VENV_PY="${REPO_ROOT}/.venv/bin/python"
if [[ ! -x "${VENV_PY}" ]]; then
  VENV_PY="${API_DIR}/.venv/bin/python"
fi
if [[ ! -x "${VENV_PY}" ]]; then
  echo "error: no Python interpreter found." >&2
  echo "       Run apps/api/scripts/bootstrap.sh first." >&2
  exit 1
fi

cd "${API_DIR}"

if [[ $# -eq 0 ]]; then
  set -- upgrade head
fi

echo "==> alembic $* (database: ${AUTOBL_DATABASE_URL:-<local sqlite file>})"
exec "${VENV_PY}" -m alembic "$@"
