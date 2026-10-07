#!/usr/bin/env bash
# Downloads the latest Pikafish release for this OS/arch into engine/pikafish
# (plus its NNUE weight file), so the backend has a real UCI engine to talk to.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE_DIR="$ROOT_DIR/engine"
mkdir -p "$ENGINE_DIR"

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Darwin)
    if [ "$ARCH" != "arm64" ]; then
      echo "This script currently only auto-selects the Apple Silicon build." >&2
      echo "Download a Linux/other build manually from https://github.com/official-pikafish/Pikafish/releases" >&2
      exit 1
    fi
    ASSET_PATH_IN_ARCHIVE="MacOS/pikafish-apple-silicon"
    ;;
  Linux)
    ASSET_PATH_IN_ARCHIVE="Linux/pikafish-avx2"
    echo "Note: picking the generic Linux/pikafish-avx2 build. If your CPU lacks" >&2
    echo "AVX2, edit this script to pick Linux/pikafish-sse41-popcnt instead." >&2
    ;;
  *)
    echo "Unsupported OS: $OS. Download a build manually from" >&2
    echo "https://github.com/official-pikafish/Pikafish/releases" >&2
    exit 1
    ;;
esac

if ! command -v 7z >/dev/null 2>&1; then
  echo "This script needs '7z' (p7zip) to extract the release archive." >&2
  echo "Install it first, e.g.: brew install p7zip   (macOS)" >&2
  echo "                        apt install p7zip-full (Debian/Ubuntu)" >&2
  exit 1
fi

echo "Fetching latest Pikafish release info..."
DOWNLOAD_URL="$(curl -s https://api.github.com/repos/official-pikafish/Pikafish/releases/latest \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["assets"][0]["browser_download_url"])')"

echo "Downloading $DOWNLOAD_URL ..."
TMP_ARCHIVE="$ENGINE_DIR/pikafish_download.7z"
curl -L -o "$TMP_ARCHIVE" "$DOWNLOAD_URL"

echo "Extracting engine binary + NNUE weights..."
(cd "$ENGINE_DIR" && 7z e "$TMP_ARCHIVE" "$ASSET_PATH_IN_ARCHIVE" pikafish.nnue -y)

BASENAME="$(basename "$ASSET_PATH_IN_ARCHIVE")"
mv -f "$ENGINE_DIR/$BASENAME" "$ENGINE_DIR/pikafish"
chmod +x "$ENGINE_DIR/pikafish"
if [ "$OS" = "Darwin" ]; then
  xattr -d com.apple.quarantine "$ENGINE_DIR/pikafish" 2>/dev/null || true
fi
rm -f "$TMP_ARCHIVE"

echo "Done. Engine installed at $ENGINE_DIR/pikafish"
echo "Quick check:"
printf 'uci\nquit\n' | "$ENGINE_DIR/pikafish" | head -3
