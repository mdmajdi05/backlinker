#!/usr/bin/env bash
#
# Push the repository to GitHub with a personal access token.
#
# The token is used for this call only - it is neither written into the git
# configuration nor into the shell history.
#
#   GITHUB_TOKEN=ghp_xxx ./scripts/push_github.sh [remote] [branch]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

REMOTE="${1:-origin}"
BRANCH="${2:-$(git branch --show-current)}"
TOKEN="${GITHUB_TOKEN:-}"

if [[ -z "$TOKEN" ]]; then
  echo "GITHUB_TOKEN is not set." >&2
  echo "Usage: GITHUB_TOKEN=ghp_xxx $0 [remote] [branch]" >&2
  exit 2
fi

BASE="$(git remote get-url "$REMOTE")"
BASE="${BASE#https://}"
BASE="${BASE#git@}"
URL="https://x-access-token:${TOKEN}@${BASE}"

echo "==> pushing $(git rev-list --count HEAD) commits to ${BASE} (${BRANCH})"
git push "$URL" "HEAD:${BRANCH}"
echo "==> done: https://${BASE}/tree/${BRANCH}"
