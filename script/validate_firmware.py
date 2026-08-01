#!/usr/bin/env python3
"""Fast structural checks for the Tater production defconfig."""

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFCONFIG = ROOT / "buildroot/configs/3reality_trspk_defconfig"
PACKAGE_MK = ROOT / "buildroot/package/thirdreality/tater-linux-satellite/tater-linux-satellite.mk"
LAUNCHER = ROOT / "buildroot/package/thirdreality/tater-linux-satellite/files/tater-satellite-launcher"
ADB_INIT = ROOT / "buildroot/board/thirdreality/trspk/rootfs/etc/init.d/S55adbd"
OTA_SCRIPT = ROOT / "buildroot/board/thirdreality/common/ota/swu/ota_package_create.sh"
BUILD_SCRIPT = ROOT / "go"
PRIVATE_KEY = ROOT / "buildroot/board/thirdreality/common/ota/swu/swupdate-priv.pem"
PUBLIC_KEY = ROOT / "buildroot/board/thirdreality/common/rootfs/etc/swupdate-public.pem"


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []
    defconfig = DEFCONFIG.read_text(encoding="utf-8")
    package_mk = PACKAGE_MK.read_text(encoding="utf-8")
    launcher = LAUNCHER.read_text(encoding="utf-8")
    adb_init = ADB_INIT.read_text(encoding="utf-8")
    ota_script = OTA_SCRIPT.read_text(encoding="utf-8")
    build_script = BUILD_SCRIPT.read_text(encoding="utf-8")

    require('BR2_TARGET_GENERIC_ROOT_PASSWD="*"' in defconfig, "root account is not locked", errors)
    require("BR2_PACKAGE_DROPBEAR=y" not in defconfig, "Dropbear is enabled", errors)
    require("BR2_PACKAGE_ANDROID_TOOLS5_ADBD=y" not in defconfig, "adbd is enabled", errors)
    require("BR2_PACKAGE_TATER_LINUX_SATELLITE=y" in defconfig, "Tater package is disabled", errors)
    require("BR2_PACKAGE_LINUX_VOICE_ASSISTANT_CPP=y" not in defconfig, "legacy C++ assistant is enabled", errors)
    require("ADB_ENABLED=0" in adb_init and "ADB_TCP_PORT=\n" in adb_init, "ADB defaults are unsafe", errors)
    require("--peripheral-host 127.0.0.1" in launcher, "peripheral API is not loopback-only", errors)
    require("--tater-board thirdreality_s420" in launcher, "board identity is missing", errors)
    require(not PRIVATE_KEY.exists(), "private OTA key is present in the source tree", errors)
    require(not PUBLIC_KEY.exists(), "generated OTA public key is present in the source tree", errors)
    require("cp swupdate-priv.pem" not in ota_script, "OTA archive copies its signing key", errors)
    require("rm -f swupdate-priv.pem" in ota_script, "OTA staging does not delete its signing key", errors)
    require(
        'export TATER_SWUPDATE_PRIVATE_KEY_FILE="${ROOT_DIR}/buildroot/board/thirdreality/common/ota/swu/swupdate-priv.pem"' in build_script,
        "build does not use the staged absolute signing-key path",
        errors,
    )

    match = re.search(r"^TATER_LINUX_SATELLITE_VERSION = ([0-9a-f]{40})$", package_mk, re.MULTILINE)
    require(match is not None, "Tater Linux source is not pinned to a full commit SHA", errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Tater firmware structure is valid (Linux source {match.group(1)[:12]}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
