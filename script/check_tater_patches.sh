#!/usr/bin/env bash
# Compile the exact pinned source with its S420 hardware adapter installed.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$ROOT_DIR/script/check_shared_runtime.py" "$@"
