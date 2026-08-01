#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRIVATE_DEST="$ROOT_DIR/buildroot/board/thirdreality/common/ota/swu/swupdate-priv.pem"
PUBLIC_DEST="$ROOT_DIR/buildroot/board/thirdreality/common/rootfs/etc/swupdate-public.pem"

umask 077
PREPARED=0

cleanup_on_failure() {
    if [ "$PREPARED" -ne 1 ]; then
        rm -f "$PRIVATE_DEST" "$PUBLIC_DEST"
    fi
}
trap cleanup_on_failure EXIT

if [ -n "${TATER_SWUPDATE_PRIVATE_KEY_PEM:-}" ]; then
    printf '%s\n' "$TATER_SWUPDATE_PRIVATE_KEY_PEM" > "$PRIVATE_DEST"
elif [ -n "${TATER_SWUPDATE_PRIVATE_KEY_FILE:-}" ]; then
    if [[ "$TATER_SWUPDATE_PRIVATE_KEY_FILE" = /* ]]; then
        PRIVATE_SOURCE="$TATER_SWUPDATE_PRIVATE_KEY_FILE"
    else
        PRIVATE_SOURCE="$ROOT_DIR/$TATER_SWUPDATE_PRIVATE_KEY_FILE"
    fi
    [ -r "$PRIVATE_SOURCE" ] || {
        echo "Cannot read TATER_SWUPDATE_PRIVATE_KEY_FILE: $PRIVATE_SOURCE" >&2
        exit 1
    }
    cp "$PRIVATE_SOURCE" "$PRIVATE_DEST"
else
    cat >&2 <<'EOF'
No OTA signing key was supplied.

Set TATER_SWUPDATE_PRIVATE_KEY_PEM from a CI secret, or set
TATER_SWUPDATE_PRIVATE_KEY_FILE to a local key. For a disposable development
key, run: ./script/generate_development_ota_key.sh
EOF
    exit 1
fi

# SWUpdate uses RSA signatures. `openssl rsa -check` works with both the
# LibreSSL shipped by macOS and OpenSSL in the Linux build container.
openssl rsa -in "$PRIVATE_DEST" -check -noout >/dev/null
openssl pkey -in "$PRIVATE_DEST" -pubout -out "$PUBLIC_DEST"
chmod 600 "$PRIVATE_DEST"
chmod 644 "$PUBLIC_DEST"
PREPARED=1

echo "Prepared SWUpdate signing material from an external private key."
