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

URL="https://x-access-token:${TOKEN}@github.com/itnegbuy/backlinker-by-majdi.git"

echo "==> pushing $(git rev-list --count HEAD) commits to ${REMOTE} (${BRANCH})"
git push "$URL" "HEAD:${BRANCH}" "$@"
echo "==> done: https://github.com/itnegbuy/backlinker-by-majdi/tree/${BRANCH}"
