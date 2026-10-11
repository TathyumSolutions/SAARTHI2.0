#!/usr/bin/env bash
# Rebuilds docs/Saarthi_Design_Document.pdf from docs/SAARTHI_DESIGN_DOCUMENT.md.
#
# Needs: pandoc, python3, node. First run: `npm install` in this folder
# (and `npx playwright install chromium` unless PLAYWRIGHT_CHROMIUM_PATH
# points at an existing Chromium).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SRC="$REPO/docs/SAARTHI_DESIGN_DOCUMENT.md"
OUT="${1:-$REPO/docs/Saarthi_Design_Document.pdf}"

if [ ! -d "$HERE/node_modules/mermaid" ]; then
  (cd "$HERE" && npm install --no-audit --no-fund)
fi

WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT

pandoc "$SRC" -f gfm -t html5 -o "$WORK/body.html"
DOC_DATE="${DOC_DATE:-$(date '+%d %B %Y')}" python3 "$HERE/build_html.py" "$WORK"
(cd "$HERE" && node print.js "$WORK" "$OUT")
echo "Wrote $OUT"
