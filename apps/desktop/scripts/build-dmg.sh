#!/usr/bin/env bash
#
# Build the macOS disk image without the Finder automation.
#
# Tauri's `bundle_dmg.sh` asks Finder (via AppleScript) to lay out the disk
# image window.  That is impossible on a build machine without a GUI session
# or without the "Automation -> Finder" permission, and the bundler then
# aborts with "AppleEvent timed out (-1712)".
#
# This script produces the same deliverable - a compressed disk image that
# contains the application bundle and an /Applications symlink - using
# `hdiutil` only.  The result is a normal, installable .dmg; it simply does
# not carry the decorative background picture.
#
# Usage: scripts/build-dmg.sh [--app PATH] [--output PATH]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUNDLE_DIR="${DESKTOP_DIR}/src-tauri/target/release/bundle"
APP_PATH="${BUNDLE_DIR}/macos/Auto Backlinker.app"
OUTPUT="${BUNDLE_DIR}/dmg/Auto Backlinker_1.0.0_x64.dmg"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app) APP_PATH="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    -h|--help) sed -n '2,16p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ ! -d "${APP_PATH}" ]]; then
  echo "The application bundle was not found at ${APP_PATH}." >&2
  echo "Run 'npm run tauri:build' first (it produces the .app bundle)." >&2
  exit 1
fi

STAGING="$(mktemp -d)"
trap 'rm -rf "${STAGING}"' EXIT

cp -R "${APP_PATH}" "${STAGING}/"
ln -s /Applications "${STAGING}/Applications"

mkdir -p "$(dirname "${OUTPUT}")"
rm -f "${OUTPUT}"

hdiutil create \
  -volname "Auto Backlinker" \
  -srcfolder "${STAGING}" \
  -ov \
  -format UDZO \
  "${OUTPUT}"

echo "==> Wrote ${OUTPUT}"
ls -lh "${OUTPUT}"
