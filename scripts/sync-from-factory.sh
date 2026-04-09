#!/bin/bash
# ─────────────────────────────────────────────────────────
# sync-from-factory.sh
#
# Copies the build-pipeline-critical files from the kaiser-site-factory
# monorepo into this bot's bundled dental-site-template/.
#
# Run this whenever the factory receives updates (scraper fixes, build.py
# improvements, new book-portal templates, nginx rules, etc.) so the bot's
# Railway deploys stay in sync with the Glasgow Smile Gallery quality bar.
#
# Files copied (factory → bot):
#   scraper.py
#   setup-assets.sh
#   build.py
#   nginx.conf
#   book-template.html
#   book-app-template.js
#
# Files deliberately NOT copied (bot has its own / factory's would regress):
#   deploy.sh                  (bot has stdout/stderr routing for subprocess parsing)
#   Dockerfile                 (bot's Dockerfile is container-specific)
#   bot.py                     (bot logic, lives outside dental-site-template/)
#   index-template.html etc.   (identical — no need to touch)
#   styles-template.css        (identical)
#   validate.sh                (identical)
#   fonts/                     (identical)
#
# Usage: ./scripts/sync-from-factory.sh
# ─────────────────────────────────────────────────────────

set -eu

FACTORY="${FACTORY:-$HOME/Downloads/kaiser-site-factory/dental-site-template}"
BOT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOT_TEMPLATE="$BOT_ROOT/dental-site-template"

if [ ! -d "$FACTORY" ]; then
    echo "ERROR: Factory not found at $FACTORY" >&2
    echo "       Clone it: git clone https://github.com/seanpuenteorg/kaiser-site-factory.git ~/Downloads/kaiser-site-factory" >&2
    exit 1
fi

if [ ! -d "$BOT_TEMPLATE" ]; then
    echo "ERROR: Bot template directory not found at $BOT_TEMPLATE" >&2
    exit 2
fi

echo "Syncing factory → bot"
echo "  Factory: $FACTORY"
echo "  Bot:     $BOT_TEMPLATE"
echo ""

changed=0
for f in scraper.py setup-assets.sh build.py nginx.conf book-template.html book-app-template.js; do
    src="$FACTORY/$f"
    dst="$BOT_TEMPLATE/$f"
    if [ ! -f "$src" ]; then
        echo "  WARNING: $f missing in factory, skipping" >&2
        continue
    fi
    if [ -f "$dst" ] && diff -q "$src" "$dst" >/dev/null 2>&1; then
        echo "  $f: no change"
    else
        cp "$src" "$dst"
        echo "  $f: updated"
        changed=$((changed + 1))
    fi
done

# Preserve executable bits on the scripts and build.py
chmod +x "$BOT_TEMPLATE/setup-assets.sh" "$BOT_TEMPLATE/build.py" "$BOT_TEMPLATE/scraper.py" 2>/dev/null || true

echo ""
if [ "$changed" -eq 0 ]; then
    echo "Already in sync. Nothing to do."
else
    echo "Synced $changed file(s). Next steps:"
    echo "  1. Test: python3 dental-site-template/build.py https://cubedental.ie --output-dir /tmp/bot-sync-test --no-deploy --no-claude"
    echo "  2. Commit: git add dental-site-template && git commit -m 'Sync build pipeline from kaiser-site-factory'"
    echo "  3. Push: git push  (triggers Railway redeploy)"
fi
