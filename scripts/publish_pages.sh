#!/usr/bin/env bash
# Rebuild the public dashboard from committed results and commit it to the gh-pages branch.
# Run after a V3 freeze or score lands on main. Pushing is a separate, explicit step:
#   git push origin gh-pages
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[ "$(git config user.name)" = "jennycruzy" ] || { echo "refusing: repository identity is not jennycruzy" >&2; exit 1; }
WORK="$(mktemp -d)"
trap 'git worktree remove --force "$WORK" >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT
git fetch -q origin gh-pages
git worktree add -q -B gh-pages "$WORK" origin/gh-pages
.venv/bin/python scripts/build_pages.py --output "$WORK"
cd "$WORK"
git add -A
if git diff --cached --quiet; then echo "gh-pages already up to date"; exit 0; fi
git commit -q -m "Publish Exnight evidence snapshot from $(git -C "$ROOT" rev-parse --short HEAD)"
echo "committed $(git rev-parse --short HEAD) on gh-pages; push with: git push origin gh-pages"
