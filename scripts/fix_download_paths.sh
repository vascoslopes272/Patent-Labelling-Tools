#!/usr/bin/env bash
# Repair Image_Path in a wizard download, in place, with a timestamped backup.
# The wizard overwrites ~/Downloads on every export, so this has to be re-run
# after each one until the batch is promoted.
#   scripts/fix_download_paths.sh [path-to-xlsx]     (default: newest Batch_04 download)
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-$HOME/Downloads/reviewed_patents_Batch_04.xlsx}"
cd "$REPO" && python scripts/conformance/fix_image_paths.py --file "$TARGET" --apply
