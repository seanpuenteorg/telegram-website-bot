#!/bin/bash
# ─────────────────────────────────────────────────────────
# Asset Pipeline — downloads logo and generates all favicons
# Usage: ./setup-assets.sh "https://example.com/logo.png"
# ─────────────────────────────────────────────────────────

set -e

LOGO_URL="$1"
OUTPUT_DIR="${2:-.}"

if [ -z "$LOGO_URL" ]; then
    echo "Usage: ./setup-assets.sh <logo-url> [output-dir]"
    exit 1
fi

echo "Downloading logo from $LOGO_URL..."
curl -sL -o "$OUTPUT_DIR/logo.png" "$LOGO_URL"

if [ ! -f "$OUTPUT_DIR/logo.png" ]; then
    echo "ERROR: Failed to download logo"
    exit 1
fi

echo "Generating favicons..."

python3 -c "
from PIL import Image
import sys, os

output_dir = '$OUTPUT_DIR'
logo = Image.open(os.path.join(output_dir, 'logo.png')).convert('RGBA')

# Make square by padding
w, h = logo.size
size = max(w, h)
square = Image.new('RGBA', (size, size), (0, 0, 0, 0))
square.paste(logo, ((size - w) // 2, (size - h) // 2))

# favicon.png — 32x32
favicon_32 = square.resize((32, 32), Image.LANCZOS)
favicon_32.save(os.path.join(output_dir, 'favicon.png'), 'PNG')

# apple-touch-icon.png — 180x180
apple = square.resize((180, 180), Image.LANCZOS)
apple.save(os.path.join(output_dir, 'apple-touch-icon.png'), 'PNG')

# favicon-512.png — 512x512
big = square.resize((512, 512), Image.LANCZOS)
big.save(os.path.join(output_dir, 'favicon-512.png'), 'PNG')

print('Generated: favicon.png (32px), apple-touch-icon.png (180px), favicon-512.png (512px)')
"

# Create a simple SVG favicon from the PNG
# If the logo is already SVG, this step copies it; otherwise creates a data-URI SVG
if echo "$LOGO_URL" | grep -qi '\.svg'; then
    curl -sL -o "$OUTPUT_DIR/favicon.svg" "$LOGO_URL"
    echo "Downloaded SVG favicon directly"
else
    python3 -c "
import base64, os
output_dir = '$OUTPUT_DIR'
with open(os.path.join(output_dir, 'favicon.png'), 'rb') as f:
    b64 = base64.b64encode(f.read()).decode()
svg = f'''<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 32 32\">
  <image href=\"data:image/png;base64,{b64}\" width=\"32\" height=\"32\"/>
</svg>'''
with open(os.path.join(output_dir, 'favicon.svg'), 'w') as f:
    f.write(svg)
print('Generated favicon.svg from PNG')
"
fi

echo "Asset pipeline complete:"
ls -la "$OUTPUT_DIR"/logo.png "$OUTPUT_DIR"/favicon.* "$OUTPUT_DIR"/apple-touch-icon.png "$OUTPUT_DIR"/favicon-512.png 2>/dev/null
