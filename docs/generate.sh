#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if ! command -v doxygen >/dev/null 2>&1; then
  echo "Error: doxygen is not installed."
  echo "Install on macOS with: brew install doxygen"
  exit 1
fi

echo "Generating documentation..."
cd "$ROOT_DIR"
doxygen Doxyfile

echo "Documentation generated at docs/build/html/index.html"