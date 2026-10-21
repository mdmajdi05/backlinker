#!/usr/bin/env bash
#
# Assemble the backend that is bundled into the desktop application.
#
# The result supports BOTH macOS architectures, so a single build can be
# handed to friends with an Intel *and* an Apple Silicon Mac:
#
#   src-tauri/Resources/backend/
#   ├── x86_64/      runtime (standalone CPython) + site-packages + app
#   └── aarch64/     runtime (standalone CPython) + site-packages + app
#
# The Rust side picks the folder that matches the machine it runs on, so the
# application never needs a system Python, Docker or a manually started
# backend.
#
# Usage:
#   scripts/build-backend.sh [--arch x86_64,aarch64] [--no-download]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="$(cd "${DESKTOP_DIR}/../.." && pwd)"
API_DIR="${REPO_DIR}/apps/api"
OUT_DIR="${DESKTOP_DIR}/src-tauri/Resources/backend"
CACHE_DIR="${DESKTOP_DIR}/.backend-cache"

PYTHON_VERSION="3.12.15"
PYTHON_ABI="cp$(printf '%s' "${PYTHON_VERSION}" | cut -d. -f1,2 | tr -d '.')"
# The interpreter that unpacks the wheels of a foreign architecture.
HOST_PYTHON="${HOST_PYTHON:-python3}"
PBS_TAG="20261013"
ARCHES="x86_64,aarch64"
DOWNLOAD=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --arch) ARCHES="$2"; shift 2 ;;
    --no-download) DOWNLOAD=0; shift ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

# The runtime dependencies of the backend.  Pure Python packages are shared
# between the architectures, compiled ones (pydantic-core, greenlet, lxml,
# uvloop, ...) are downloaded per architecture.
RUNTIME_REQUIREMENTS=(
  "fastapi"
  "uvicorn[standard]"
  "sqlalchemy>=2.0"
  "pydantic>=2.9"
  "pydantic-settings>=2.6"
  "alembic>=1.14"
  "httpx>=0.27"
  "openpyxl>=3.1"
  "python-multipart>=0.0.12"
  "pyjwt>=2.9"
  "email-validator>=2.2"
  "beautifulsoup4>=4.12"
  "lxml>=5.3"
  "tenacity>=9.0"
  "structlog>=24.4"
)
# The Playwright package is *not* bundled - it weighs 135 MB per architecture
# (it contains its own Node runtime).  It is installed on demand into the
# application data directory, together with the browser build.

# The wheels of the compiled packages are published for different macOS
# versions - pip is told about all of them so it can pick the best match.
PYPI_PLATFORMS_x86_64="macosx_11_0_x86_64 macosx_10_13_x86_64 macosx_10_9_x86_64 macosx_10_6_x86_64"
PYPI_PLATFORMS_aarch64="macosx_14_0_arm64 macosx_13_0_arm64 macosx_12_0_arm64 macosx_11_0_arm64"

echo "==> Assembling the bundled backend in ${OUT_DIR}"
mkdir -p "${OUT_DIR}"

for arch in ${ARCHES//,/ }; do
  dest="${OUT_DIR}/${arch}"
  echo ""
  echo "==> ${arch}"
  rm -rf "${dest}"
  mkdir -p "${dest}"

  # ---------------------------------------------------------------- python
  if [[ "${DOWNLOAD}" == "1" || ! -x "${dest}/runtime/bin/python3.12" ]]; then
    archive="cpython-${PYTHON_VERSION}+${PBS_TAG}-${arch}-apple-darwin-install_only_stripped.tar.gz"
    url="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${archive}"
    mkdir -p "${CACHE_DIR}"
    archive_path="${CACHE_DIR}/${archive}"
    if [[ ! -s "${archive_path}" ]]; then
      echo "    downloading the standalone CPython (${archive})"
      curl -sSL --retry 3 -o "${archive_path}.part" "${url}"
      mv "${archive_path}.part" "${archive_path}"
    else
      echo "    using the cached CPython (${archive})"
    fi
    tmp="$(mktemp -d)"
    tar -xzf "${archive_path}" -C "${tmp}"
    mv "${tmp}/python" "${dest}/runtime"
    rm -rf "${tmp}"
  fi
  if [[ "${arch}" == "$(uname -m)" ]]; then
    "${dest}/runtime/bin/python3.12" -c "import sys; print('    runtime', sys.version.split()[0])"
  else
    echo "    runtime ${PYTHON_VERSION} (for ${arch}, not executed on this $(uname -m) machine)"
  fi

  # --------------------------------------------------------- dependencies
  echo "    installing the dependencies"
  platforms_var="PYPI_PLATFORMS_${arch}"
  platform_args=()
  for platform in ${!platforms_var}; do
    platform_args+=(--platform "${platform}")
  done
  # uv uses a simplified platform name.
  uv_platform_args=(--python-platform "${arch}-apple-darwin")
  rm -rf "${dest}/site-packages"
  mkdir -p "${dest}/site-packages"
  # The wheels of a foreign architecture are installed with the *host*
  # interpreter - pip only needs it to unpack the wheels.
  if [[ "${arch}" == "$(uname -m)" ]]; then
    pip_python="${dest}/runtime/bin/python3.12"
  else
    pip_python="${HOST_PYTHON}"
  fi
  # uv resolves and unpacks the wheels of a foreign architecture in seconds;
  # pip needs minutes for the same job.
  if command -v uv >/dev/null 2>&1; then
    uv pip install \
      --quiet --no-cache \
      --target "${dest}/site-packages" \
      "${uv_platform_args[@]}" \
      --python-version "${PYTHON_VERSION}" \
      "${RUNTIME_REQUIREMENTS[@]}" >/dev/null
  else
    "${pip_python}" -m pip install \
      --quiet --no-compile \
      --target "${dest}/site-packages" \
      "${platform_args[@]}" \
      --python-version "${PYTHON_VERSION}" \
      --implementation cp \
      --abi "${PYTHON_ABI}" \
      --only-binary=:all: \
      "${RUNTIME_REQUIREMENTS[@]}" >/dev/null
  fi

  # ----------------------------------------------------------- the backend
  rm -rf "${dest}/app"
  cp -R "${API_DIR}/app" "${dest}/app"
  find "${dest}/app" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
  cp "${SCRIPT_DIR}/sidecar_launcher.py" "${dest}/sidecar_launcher.py"

  # ----------------------------------------------------------- slimming down
  # pip is not needed at runtime, the test suites and the type stubs are dead
  # weight - removing them saves about 15 MB per architecture.
  rm -rf "${dest}/runtime/lib/python3.12/site-packages/pip" \
         "${dest}/runtime/lib/python3.12/site-packages/pip-"* \
         "${dest}/runtime/lib/python3.12/site-packages/setuptools" \
         "${dest}/runtime/lib/python3.12/site-packages/setuptools-"* \
         "${dest}/runtime/lib/python3.12/site-packages/pkg_resources" 2>/dev/null || true
  find "${dest}/site-packages" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
  find "${dest}/site-packages" -name "*.pyi" -delete 2>/dev/null || true
  find "${dest}/site-packages" -name "tests" -maxdepth 2 -type d -exec rm -rf {} + 2>/dev/null || true

  size="$(du -sh "${dest}" | cut -f1)"
  echo "    done (${size})"
done

echo ""
echo "==> Verifying the assembled backends"
for arch in ${ARCHES//,/ }; do
  dest="${OUT_DIR}/${arch}"
  if [[ "${arch}" != "$(uname -m)" ]]; then
    echo "    ${arch}: assembled (${arch} binaries cannot be executed on this $(uname -m) machine)"
    continue
  fi
  PYTHONPATH="${dest}/site-packages:${dest}" "${dest}/runtime/bin/python3.12" -c "
import sys
from app.main import app
print(f'    ${arch}: {len(app.openapi()[\"paths\"])} API paths, {len(sys.modules)} modules')
"
done

echo ""
echo "The backend is bundled in ${OUT_DIR}"
du -sh "${OUT_DIR}"
