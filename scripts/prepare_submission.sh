#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TIMESTAMP="${1:-$(date +%Y%m%d_%H%M%S)}"
OUT_ROOT="$ROOT_DIR/submission"
PACKAGE_NAME="okx_trading_platform_sample_submission_${TIMESTAMP}"
STAGE_DIR="$OUT_ROOT/$PACKAGE_NAME"
ZIP_PATH="$OUT_ROOT/${PACKAGE_NAME}.zip"

mkdir -p "$OUT_ROOT"

if [[ -e "$STAGE_DIR" || -e "$ZIP_PATH" ]]; then
  printf 'Refusing to overwrite existing submission artifact: %s\n' "$PACKAGE_NAME" >&2
  printf 'Pass a new timestamp/name or remove the old artifact first.\n' >&2
  exit 1
fi

# Copy the repo into a clean staging area without local caches, datasets, or build outputs.
rsync -a \
  --exclude '.git/' \
  --exclude 'submission/' \
  --exclude 'build/' \
  --exclude 'Build/' \
  --exclude 'cmake-build-*/' \
  --exclude 'CMakeFiles/' \
  --exclude 'CMakeCache.txt' \
  --exclude 'compile_commands.json' \
  --exclude 'Feature Engineering HFT.md' \
  --exclude 'frontend/electron/node_modules/' \
  --exclude 'frontend/electron/dist/' \
  --exclude 'frontend/web/' \
  --exclude 'deploy/containers/gateway/node_modules/' \
  --exclude 'reports/aws_fargate_delivery/node_modules/' \
  --exclude '.venv/' \
  --exclude 'venv/' \
  --exclude 'env/' \
  --exclude 'ml_pipeline/.venv/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.mypy_cache/' \
  --exclude '.ruff_cache/' \
  --exclude '.ipynb_checkpoints/' \
  --exclude 'data/' \
  --exclude 'models/' \
  --exclude 'logs/' \
  --exclude 'output/' \
  --exclude 'vcpkg_installed/' \
  --exclude '*.pyc' \
  --exclude '*.pyo' \
  --exclude '*.log' \
  --exclude 'missfont.log' \
  --exclude '*.tmp' \
  --exclude '*.aux' \
  --exclude '*.bbl' \
  --exclude '*.blg' \
  --exclude '*.fdb_latexmk' \
  --exclude '*.fls' \
  --exclude '*.nav' \
  --exclude '*.snm' \
  --exclude '*.synctex.gz' \
  --exclude '*.toc' \
  --exclude '*.vrb' \
  --exclude '.DS_Store' \
  "$ROOT_DIR/" "$STAGE_DIR/"

(
  cd "$OUT_ROOT"
  zip -X -rq "${PACKAGE_NAME}.zip" "$PACKAGE_NAME"
)

printf 'Staged submission at: %s\n' "$STAGE_DIR"
printf 'Created zip at: %s\n' "$ZIP_PATH"
