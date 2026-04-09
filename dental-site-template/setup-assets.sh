#!/bin/bash
# ─────────────────────────────────────────────────────────
# Asset Pipeline — downloads logo and generates favicons
# Usage: ./setup-assets.sh <logo-url> [output-dir]
# ─────────────────────────────────────────────────────────
# All warnings/errors go to stderr so build.py's subprocess capture shows them.
#
# Output contract:
#   - Always writes EITHER logo.svg (if source is SVG) OR logo.png (if raster).
#   - Always writes favicon.svg.
#   - Writes favicon.png + apple-touch-icon.png + favicon-512.png only if source is raster
#     (modern browsers use favicon.svg fine, so this is optional for SVG sources).
#
# Exit codes:
#   0  success
#   1  bad args
#   2  logo URL is a data: URI (not downloadable; scraper bug)
#   3  curl HTTP failure
#   4  download empty or missing
#   5  downloaded file is not an image (e.g. HTML error page)
#   6  Pillow/Python raster pipeline failed

set -eu

LOGO_URL="${1:-}"
OUTPUT_DIR="${2:-.}"

if [ -z "$LOGO_URL" ]; then
    echo "Usage: ./setup-assets.sh <logo-url> [output-dir]" >&2
    exit 1
fi

if [[ "$LOGO_URL" == data:* ]]; then
    echo "ERROR: Logo URL is a data URI (not a downloadable file)." >&2
    echo "       This usually means the scraper picked up a lazy-load placeholder." >&2
    echo "       URL: ${LOGO_URL:0:60}..." >&2
    exit 2
fi

TMP_DOWNLOAD="$OUTPUT_DIR/_logo_download.tmp"
echo "Downloading logo from $LOGO_URL..." >&2
if ! curl -fsSL -o "$TMP_DOWNLOAD" "$LOGO_URL"; then
    echo "ERROR: curl failed to download logo from $LOGO_URL" >&2
    rm -f "$TMP_DOWNLOAD"
    exit 3
fi

if [ ! -s "$TMP_DOWNLOAD" ]; then
    echo "ERROR: Downloaded logo is empty or missing" >&2
    rm -f "$TMP_DOWNLOAD"
    exit 4
fi

# Detect MIME type. If it's not an image, curl probably got an HTML error page.
FILE_TYPE="$(file -b --mime-type "$TMP_DOWNLOAD" 2>/dev/null || echo unknown)"
if [[ "$FILE_TYPE" != image/* ]]; then
    echo "ERROR: Downloaded file is not an image (got $FILE_TYPE)." >&2
    echo "       URL: $LOGO_URL" >&2
    rm -f "$TMP_DOWNLOAD"
    exit 5
fi

# Split flow: SVG vs raster
if [[ "$FILE_TYPE" == "image/svg+xml" ]]; then
    # SVG source — keep as logo.svg, copy to favicon.svg, skip raster favicons.
    # Modern browsers render SVG in <img> and <link rel=icon>, so this is enough.
    mv "$TMP_DOWNLOAD" "$OUTPUT_DIR/logo.svg"
    cp "$OUTPUT_DIR/logo.svg" "$OUTPUT_DIR/favicon.svg"
    # Remove any stale raster logo.png so build.py can detect the format cleanly.
    rm -f "$OUTPUT_DIR/logo.png" "$OUTPUT_DIR/favicon.png" "$OUTPUT_DIR/apple-touch-icon.png" "$OUTPUT_DIR/favicon-512.png"
    echo "SVG logo saved. logo.svg + favicon.svg generated. Skipping raster favicons." >&2
    ls -la "$OUTPUT_DIR"/logo.svg "$OUTPUT_DIR"/favicon.svg 2>&1 >&2
    exit 0
fi

# Raster source — save as logo.png and generate PNG favicon set via Pillow.
mv "$TMP_DOWNLOAD" "$OUTPUT_DIR/logo.png"
# Remove any stale SVG logo to keep the output clean.
rm -f "$OUTPUT_DIR/logo.svg"

echo "Generating PNG favicons..." >&2
python3 <<PYEOF
from PIL import Image
import base64, os, sys

output_dir = "$OUTPUT_DIR"
try:
    logo = Image.open(os.path.join(output_dir, "logo.png")).convert("RGBA")
except Exception as e:
    sys.stderr.write(f"ERROR: Pillow failed to open logo.png: {e}\n")
    sys.exit(6)

w, h = logo.size
size = max(w, h)
square = Image.new("RGBA", (size, size), (0, 0, 0, 0))
square.paste(logo, ((size - w) // 2, (size - h) // 2))

for target, px in [("favicon.png", 32), ("apple-touch-icon.png", 180), ("favicon-512.png", 512)]:
    square.resize((px, px), Image.LANCZOS).save(os.path.join(output_dir, target), "PNG")

# Build an SVG favicon that embeds the 32px PNG as a data URI — valid SVG
# that modern browsers render identically to a real PNG favicon.
with open(os.path.join(output_dir, "favicon.png"), "rb") as f:
    b64 = base64.b64encode(f.read()).decode()
svg = (
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    f'<image href="data:image/png;base64,{b64}" width="32" height="32"/>'
    f'</svg>'
)
with open(os.path.join(output_dir, "favicon.svg"), "w") as f:
    f.write(svg)

print("Generated favicon.png (32), apple-touch-icon.png (180), favicon-512.png (512), favicon.svg", file=sys.stderr)
PYEOF

echo "Asset pipeline complete." >&2
ls -la "$OUTPUT_DIR"/logo.* "$OUTPUT_DIR"/favicon.* "$OUTPUT_DIR"/apple-touch-icon.png 2>&1 >&2 || true
