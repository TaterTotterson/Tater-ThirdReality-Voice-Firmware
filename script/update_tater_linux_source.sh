#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_MK="$ROOT_DIR/buildroot/package/thirdreality/tater-linux-satellite/tater-linux-satellite.mk"
REMOTE_URL="https://github.com/TaterTotterson/Tater-Linux-Satellite.git"
MODE="${1:---check}"

case "$MODE" in
    --check|--update) ;;
    *)
        echo "Usage: $0 [--check|--update]" >&2
        exit 2
        ;;
esac

CURRENT=$(sed -n 's/^TATER_LINUX_SATELLITE_VERSION = //p' "$PACKAGE_MK")
LATEST=$(git ls-remote "$REMOTE_URL" refs/heads/main | awk '{print $1}')

[[ "$CURRENT" =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid pinned SHA: $CURRENT" >&2; exit 1; }
[[ "$LATEST" =~ ^[0-9a-f]{40}$ ]] || { echo "Unable to resolve Tater Linux main" >&2; exit 1; }

if [ "$CURRENT" = "$LATEST" ]; then
    echo "Tater Linux source is current at $CURRENT"
    exit 0
fi

if [ "$MODE" = "--check" ]; then
    echo "Tater Linux source is behind: pinned=$CURRENT latest=$LATEST" >&2
    exit 1
fi

sed -i.bak "s/^TATER_LINUX_SATELLITE_VERSION = .*/TATER_LINUX_SATELLITE_VERSION = $LATEST/" "$PACKAGE_MK"
rm -f "$PACKAGE_MK.bak"
echo "Updated Tater Linux source: $CURRENT -> $LATEST"
