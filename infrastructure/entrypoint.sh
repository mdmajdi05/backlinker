#!/bin/sh
# Container entry point: apply the migrations and then run the given command.
#
# The migration step is idempotent, so restarting a container never loses data.
# Set AUTOBL_RUN_MIGRATIONS=0 to disable it (for example for the worker).
set -e

if [ "${AUTOBL_RUN_MIGRATIONS:-1}" = "1" ]; then
  echo "==> applying database migrations"
  alembic upgrade head
fi

exec "$@"
