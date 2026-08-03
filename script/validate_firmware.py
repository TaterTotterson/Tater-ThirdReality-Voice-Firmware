#!/usr/bin/env python3
"""Fast structural checks for the Tater production defconfig."""

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFCONFIG = ROOT / "buildroot/configs/3reality_trspk_defconfig"
PACKAGE_MK = ROOT / "buildroot/package/thirdreality/tater-linux-satellite/tater-linux-satellite.mk"
PACKAGE_CONFIG = ROOT / "buildroot/package/thirdreality/tater-linux-satellite/Config.in"
ZEROCONF_REMOVAL_PATCH = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/0001-remove-zeroconf-discovery.patch"
)
LAUNCHER = ROOT / "buildroot/package/thirdreality/tater-linux-satellite/files/tater-satellite-launcher"
HARDWARE_BRIDGE = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/tater-thirdreality-bridge.py"
)
PROVISIONING = (
    ROOT / "buildroot/package/thirdreality/tater-linux-satellite/files/tater-provisioning"
)
PROVISIONING_SERVER = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/tater-provisioning-server.py"
)
SUPERVISOR = ROOT / "buildroot/package/thirdreality/tr-proj-ha-speaker/script/S99ha-speaker"
WIFI_INIT = ROOT / "buildroot/board/thirdreality/common/rootfs/etc/init.d/S39wifi"
KERNEL_FRAGMENT = ROOT / "buildroot/board/thirdreality/trspk/linux-no-bluetooth.fragment"
KEY_HANDLER = (
    ROOT / "buildroot/board/thirdreality/trspk/rootfs/etc/adckey/adckey_function.sh"
)
AIOESPHOMEAPI_CONFIG = ROOT / "buildroot/package/thirdreality/python-aioesphomeapi/Config.in"
AIOESPHOMEAPI_MK = (
    ROOT
    / "buildroot/package/thirdreality/python-aioesphomeapi/python-aioesphomeapi.mk"
)
BROADCOM_MK = ROOT / "buildroot/package/thirdreality/broadcom/broadcom.mk"
SENDSPIN_PACKAGE = ROOT / "buildroot/package/thirdreality/sendspin-client"
BUSYBOX_FRAGMENT = ROOT / "buildroot/board/thirdreality/trspk/busybox-tater.fragment"
POST_BUILD = ROOT / "buildroot/board/thirdreality/trspk/post_build.sh"
NETMONITOR = ROOT / "buildroot/package/thirdreality/tr-proj-ha-speaker/script/netmonitor"
OTA_SCRIPT = ROOT / "buildroot/board/thirdreality/common/ota/swu/ota_package_create.sh"
BUILD_SCRIPT = ROOT / "go"
PRIVATE_KEY = ROOT / "buildroot/board/thirdreality/common/ota/swu/swupdate-priv.pem"
PUBLIC_KEY = ROOT / "buildroot/board/thirdreality/common/rootfs/etc/swupdate-public.pem"
NTP_DEFAULT = ROOT / "buildroot/package/ntp/ntpd.etc.default"
NTP_BOOT = ROOT / "buildroot/package/ntp/ntpdate.sh"
NTP_CONF = ROOT / "buildroot/board/thirdreality/trspk/rootfs/etc/ntp.conf"
NTP_DHCP_HOOK = (
    ROOT
    / "buildroot/board/thirdreality/trspk/rootfs/usr/share/udhcpc/default.script.d/ntp-from-dhcp"
)
FORBIDDEN_NTP_ENDPOINTS = (
    "ntp.aliyun.com",
    "ntp.tencent.com",
    "cn.pool.ntp.org",
    "203.107.6.88",
    "120.25.115.20",
)
US_NTP_SERVERS = ("time-a-g.nist.gov", "time-a-b.nist.gov", "time-a-wwv.nist.gov")


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []
    defconfig = DEFCONFIG.read_text(encoding="utf-8")
    package_mk = PACKAGE_MK.read_text(encoding="utf-8")
    package_config = PACKAGE_CONFIG.read_text(encoding="utf-8")
    zeroconf_removal_patch = ZEROCONF_REMOVAL_PATCH.read_text(encoding="utf-8")
    launcher = LAUNCHER.read_text(encoding="utf-8")
    hardware_bridge = HARDWARE_BRIDGE.read_text(encoding="utf-8")
    provisioning = PROVISIONING.read_text(encoding="utf-8")
    provisioning_server = PROVISIONING_SERVER.read_text(encoding="utf-8")
    supervisor = SUPERVISOR.read_text(encoding="utf-8")
    wifi_init = WIFI_INIT.read_text(encoding="utf-8")
    kernel_fragment = KERNEL_FRAGMENT.read_text(encoding="utf-8")
    key_handler = KEY_HANDLER.read_text(encoding="utf-8")
    aioesphomeapi_config = AIOESPHOMEAPI_CONFIG.read_text(encoding="utf-8")
    aioesphomeapi_mk = AIOESPHOMEAPI_MK.read_text(encoding="utf-8")
    broadcom_mk = BROADCOM_MK.read_text(encoding="utf-8")
    busybox_fragment = BUSYBOX_FRAGMENT.read_text(encoding="utf-8")
    post_build = POST_BUILD.read_text(encoding="utf-8")
    netmonitor = NETMONITOR.read_text(encoding="utf-8")
    ota_script = OTA_SCRIPT.read_text(encoding="utf-8")
    build_script = BUILD_SCRIPT.read_text(encoding="utf-8")
    ntp_files = {
        "initial-sync defaults": NTP_DEFAULT.read_text(encoding="utf-8"),
        "boot sync": NTP_BOOT.read_text(encoding="utf-8"),
        "daemon defaults": NTP_CONF.read_text(encoding="utf-8"),
        "DHCP hook": NTP_DHCP_HOOK.read_text(encoding="utf-8"),
    }

    require('BR2_TARGET_GENERIC_ROOT_PASSWD="*"' in defconfig, "root account is not locked", errors)
    require("BR2_PACKAGE_DROPBEAR=y" not in defconfig, "Dropbear is enabled", errors)
    require("BR2_PACKAGE_ANDROID_TOOLS5_ADBD=y" not in defconfig, "adbd is enabled", errors)
    require("BR2_PACKAGE_TATER_LINUX_SATELLITE=y" in defconfig, "Tater package is disabled", errors)
    require("BR2_PACKAGE_LINUX_VOICE_ASSISTANT=y" not in defconfig, "legacy Python assistant is enabled", errors)
    require("BR2_PACKAGE_LINUX_VOICE_ASSISTANT_CPP=y" not in defconfig, "legacy C++ assistant is enabled", errors)
    require("BR2_PACKAGE_SENDSPIN_CLIENT=y" not in defconfig, "Sendspin is enabled", errors)
    require("BR2_PACKAGE_AVAHI=y" not in defconfig, "Avahi is enabled", errors)
    require("BR2_PACKAGE_AVAHI_DAEMON=y" not in defconfig, "Avahi daemon is enabled", errors)
    require("BR2_PACKAGE_BLUEZ5_UTILS=y" not in defconfig, "BlueZ is enabled", errors)
    require(
        "# BR2_PACKAGE_BLUEZ5_UTILS is not set" in defconfig,
        "BlueZ is not explicitly disabled against the vendor default",
        errors,
    )
    require(
        'BR2_LINUX_KERNEL_CONFIG_FRAGMENT_FILES="board/thirdreality/trspk/linux-no-bluetooth.fragment"'
        in defconfig,
        "Bluetooth-free kernel fragment is not selected",
        errors,
    )
    require("# CONFIG_BT is not set" in kernel_fragment, "kernel Bluetooth stack is enabled", errors)
    require("BR2_PACKAGE_HOSTAPD=y" in defconfig, "hostapd is disabled", errors)
    require("BR2_PACKAGE_DNSMASQ_DHCP=y" in defconfig, "dnsmasq DHCP is disabled", errors)
    require("BR2_PACKAGE_PYTHON_ZEROCONF" not in package_config, "Tater selects Zeroconf", errors)
    require("python-zeroconf" not in package_mk, "Tater depends on Zeroconf", errors)
    require("BR2_PACKAGE_PYTHON_ZEROCONF" not in aioesphomeapi_config, "aioesphomeapi selects Zeroconf", errors)
    require("python-zeroconf" not in aioesphomeapi_mk, "aioesphomeapi depends on Zeroconf", errors)
    require(
        not SENDSPIN_PACKAGE.exists() or not any(SENDSPIN_PACKAGE.iterdir()),
        "Sendspin package remains in the source tree",
        errors,
    )
    require("sendspin" not in supervisor.lower(), "supervisor still manages Sendspin", errors)
    require("avahi" not in supervisor.lower(), "supervisor still starts Avahi", errors)
    require("sendspin" not in hardware_bridge.lower(), "hardware bridge still controls Sendspin", errors)
    active_runtime = "\n".join((supervisor, ntp_files["boot sync"], key_handler))
    require("S44bluetooth" not in active_runtime, "active runtime still calls Bluetooth setup", errors)
    require("/etc/bluetooth" not in broadcom_mk, "Broadcom package still installs Bluetooth firmware", errors)
    require("tater-provisioning" in package_mk, "Tater provisioning tools are not installed", errors)
    require('ssid="Tater-Setup-$suffix"' in provisioning, "Tater setup SSID is missing", errors)
    require("192.168.4.1" in provisioning, "Tater setup address is missing", errors)
    require("--address=/#/192.168.4.1" in provisioning, "captive DNS is missing", errors)
    require("$MULTI_WIFI ap 1" in wifi_init, "Wi-Fi init cannot load AP mode", errors)
    require('"$PROVISIONING" needs-setup' in supervisor, "first-boot setup gate is missing", errors)
    require("Tater Satellite Setup" in provisioning_server, "setup page is missing", errors)
    for field in ("ssid", "wifi_password", "tater_server", "pairing_code", "room", "name"):
        require(f'name="{field}"' in provisioning_server, f"setup field is missing: {field}", errors)
    require("<script src=" not in provisioning_server, "setup page loads a remote script", errors)
    require("<link " not in provisioning_server, "setup page loads a remote resource", errors)
    require('LVAEvent.CONNECTION' in zeroconf_removal_patch, "Tater connection event is not patched", errors)
    require('-from .zeroconf import HomeAssistantZeroconf' in zeroconf_removal_patch, "Zeroconf removal patch is incomplete", errors)
    for applet in ("INETD", "TELNET", "TELNETD", "TFTP", "TFTPD"):
        require(
            f"# CONFIG_{applet} is not set" in busybox_fragment,
            f"BusyBox network debug applet is not disabled: {applet}",
            errors,
        )
    for path in ("S41inetd", "S55adbd", "telnetd", "module-rtp-recv.so", "module-raop-sink.so"):
        require(path in post_build, f"post-build hardening does not remove {path}", errors)
    for endpoint in (
        "connectivitycheck.gstatic.com",
        "captive.apple.com",
        "8.8.8.8",
        "ota.cloud.3reality.com",
    ):
        require(endpoint not in netmonitor, f"network monitor calls third party: {endpoint}", errors)
    require("get_tater_check_url" in netmonitor, "network monitor does not probe the paired Tater server", errors)
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
    for label, text in ntp_files.items():
        for endpoint in FORBIDDEN_NTP_ENDPOINTS:
            require(endpoint not in text, f"forbidden NTP endpoint is active in {label}: {endpoint}", errors)
    for label in ("initial-sync defaults", "daemon defaults", "DHCP hook"):
        for server in US_NTP_SERVERS:
            require(server in ntp_files[label], f"US NTP server is missing from {label}: {server}", errors)
    require("NTPSERVERS_IP" not in ntp_files["initial-sync defaults"], "hard-coded public NTP IPs are enabled", errors)
    require("iburst" not in ntp_files["daemon defaults"], "NIST servers use iburst", errors)
    require("iburst" not in ntp_files["DHCP hook"], "DHCP NTP configuration uses iburst", errors)
    require("RETRY_DELAY=4" in ntp_files["boot sync"], "NTP retry delay is too aggressive", errors)
    require("-p 1" in ntp_files["initial-sync defaults"], "initial NTP sync sends multiple samples", errors)

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
