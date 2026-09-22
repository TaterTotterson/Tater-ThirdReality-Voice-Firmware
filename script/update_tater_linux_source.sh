#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_MK="$ROOT_DIR/buildroot/package/thirdreality/tater-linux-satellite/tater-linux-satellite.mk"
REMOTE_URL="https://github.com/TaterTotterson/Tater-Linux-Satellite.git"
MODE="${1:---check}"

case "$MODE" in
    --check|--report|--update) ;;
    *)
        echo "Usage: $0 [--check|--report|--update]" >&2
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

DRIFT_MESSAGE="Tater Linux source update available: pinned=$CURRENT latest=$LATEST"

if [ "$MODE" = "--check" ]; then
    echo "$DRIFT_MESSAGE" >&2
    exit 1
fi

if [ "$MODE" = "--report" ]; then
    if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
        echo "::warning title=Tater Linux update available::$DRIFT_MESSAGE"
    else
        echo "$DRIFT_MESSAGE"
    fi
    if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
        {
            echo "## Tater Linux update available"
            echo
            echo "The S420 firmware source pin remains unchanged so hardware-specific updates can be reviewed and tested before adoption."
            echo
            echo "- Pinned: \`$CURRENT\`"
            echo "- Latest: \`$LATEST\`"
        } >> "$GITHUB_STEP_SUMMARY"
    fi
    exit 0
fi

sed -i.bak "s/^TATER_LINUX_SATELLITE_VERSION = .*/TATER_LINUX_SATELLITE_VERSION = $LATEST/" "$PACKAGE_MK"
rm -f "$PACKAGE_MK.bak"
echo "Updated Tater Linux source: $CURRENT -> $LATEST"
