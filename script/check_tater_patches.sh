#!/usr/bin/env bash
# Apply the complete Buildroot patch set to the exact pinned runtime source.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_DIR="$ROOT_DIR/buildroot/package/thirdreality/tater-linux-satellite"
VERSION=$(sed -n 's/^TATER_LINUX_SATELLITE_VERSION = //p' "$PACKAGE_DIR/tater-linux-satellite.mk")
[[ "$VERSION" =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid pinned runtime SHA: $VERSION" >&2; exit 1; }
ARCHIVE="${1:-$ROOT_DIR/buildroot/dl/tater-linux-satellite/tater-linux-satellite-${VERSION}.tar.gz}"
WORK_DIR=$(mktemp -d)
DOWNLOAD=""
trap 'rm -rf "$WORK_DIR"; if [ -n "$DOWNLOAD" ]; then rm -f "$DOWNLOAD"; fi' EXIT

if [ ! -f "$ARCHIVE" ]; then
    mkdir -p "$(dirname "$ARCHIVE")"
    DOWNLOAD=$(mktemp "${ARCHIVE}.XXXXXX")
    curl --fail --location --silent --show-error --retry 3 \
        --connect-timeout 15 --max-time 180 \
        "https://github.com/TaterTotterson/Tater-Linux-Satellite/archive/${VERSION}.tar.gz" \
        --output "$DOWNLOAD"
    mv "$DOWNLOAD" "$ARCHIVE"
    DOWNLOAD=""
fi

tar -xzf "$ARCHIVE" --strip-components=1 -C "$WORK_DIR"
bash "$ROOT_DIR/buildroot/support/scripts/apply-patches.sh" \
    "$WORK_DIR" "$PACKAGE_DIR" '*.patch'
python3 -m compileall -q "$WORK_DIR/linux_voice_assistant"
echo "All Tater runtime patches apply and compile for $VERSION."
