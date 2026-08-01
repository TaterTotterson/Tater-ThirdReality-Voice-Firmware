#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEY_FILE="${1:-$ROOT_DIR/.secrets/swupdate-development-private.pem}"

mkdir -p "$(dirname "$KEY_FILE")"
umask 077

if [ -e "$KEY_FILE" ]; then
    echo "Refusing to overwrite existing key: $KEY_FILE" >&2
    exit 1
fi

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out "$KEY_FILE"
chmod 600 "$KEY_FILE"

echo "Development-only OTA key written to: $KEY_FILE"
if [[ "$KEY_FILE" = "$ROOT_DIR/"* ]]; then
    BUILD_KEY="${KEY_FILE#"$ROOT_DIR/"}"
else
    BUILD_KEY="$KEY_FILE"
fi
echo "Build with: TATER_SWUPDATE_PRIVATE_KEY_FILE=$BUILD_KEY ./go --docker trspk"
