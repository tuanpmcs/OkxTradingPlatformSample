#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="$ROOT_DIR/docs/build"

if ! command -v doxygen >/dev/null 2>&1; then
  echo "Error: doxygen is not installed."
  echo "Install on macOS with: brew install doxygen"
  exit 1
fi

if ! command -v dot >/dev/null 2>&1; then
  echo "Warning: Graphviz 'dot' is not installed. Doxygen will run, but graph output may be limited."
  echo "Install on macOS with: brew install graphviz"
fi

if [ -x "$ROOT_DIR/scripts/refresh_svg_exports.sh" ]; then
  bash "$ROOT_DIR/scripts/refresh_svg_exports.sh"
fi

echo "Generating documentation into $OUTPUT_DIR ..."
cd "$ROOT_DIR"
mkdir -p "$OUTPUT_DIR"
doxygen Doxyfile

echo "Documentation generated at $OUTPUT_DIR/html/index.html"
