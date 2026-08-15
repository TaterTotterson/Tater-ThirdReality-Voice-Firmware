#!/usr/bin/env python3
"""Fast structural checks for the Tater production defconfig."""

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = ROOT / ".github/workflows/release-firmware.yml"
RELEASE_HIGHLIGHTS = ROOT / "RELEASE_HIGHLIGHTS.md"
RELEASE_NOTES_RENDERER = ROOT / "script/render_release_notes.py"
DEFCONFIG = ROOT / "buildroot/configs/3reality_trspk_defconfig"
PACKAGE_MK = ROOT / "buildroot/package/thirdreality/tater-linux-satellite/tater-linux-satellite.mk"
PACKAGE_CONFIG = ROOT / "buildroot/package/thirdreality/tater-linux-satellite/Config.in"
ZEROCONF_REMOVAL_PATCH = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/0001-remove-zeroconf-discovery.patch"
)
TATER_FEATURE_PATCH = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/0002-enable-tater-native-features.patch"
)
TATER_METADATA_PATCH = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/0003-use-tater-package-metadata.patch"
)
TATER_NATIVE_ONLY_PATCH = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/0004-remove-legacy-listener.patch"
)
TATER_NO_FRAME_SENDER_PATCH = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/0005-remove-legacy-frame-sender.patch"
)
TATER_SYNC_PLAYER_PATCH = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/0006-add-tater-synchronized-mpv-controls.patch"
)
TATER_BARGE_IN_PATCH = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/0007-enable-tater-tts-barge-in.patch"
)
TATER_WAKE_SOUND_PATCH = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/0008-follow-tater-wake-sound-settings.patch"
)
TATER_FEATURES = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/tater_features.py"
)
TATER_WAKE_SOUNDS = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/wake_sounds"
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
NETWORK_PERSISTENCE = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/S38tater-network-persistence"
)
NAND_OTA_DESCRIPTION = (
    ROOT / "buildroot/board/thirdreality/common/ota/ota-axg/sw-description-nand"
)
NAND_OTA_FILELIST = (
    ROOT / "buildroot/board/thirdreality/common/ota/ota-axg/ota-package-filelist-nand"
)
SUPERVISOR = ROOT / "buildroot/package/thirdreality/tater-s420-firmware/script/S99tater-satellite"
WIFI_INIT = ROOT / "buildroot/board/thirdreality/common/rootfs/etc/init.d/S39wifi"
KERNEL_FRAGMENT = ROOT / "buildroot/board/thirdreality/trspk/linux-no-bluetooth.fragment"
KEY_HANDLER = (
    ROOT / "buildroot/board/thirdreality/trspk/rootfs/etc/adckey/adckey_function.sh"
)
PROTOCOL_COMPAT_CONFIG = ROOT / "buildroot/package/thirdreality/python-tater-protocol-compat/Config.in"
PROTOCOL_COMPAT_MK = (
    ROOT
    / "buildroot/package/thirdreality/python-tater-protocol-compat/python-tater-protocol-compat.mk"
)
PROTOCOL_COMPAT_NO_MDNS_PATCH = (
    ROOT
    / "buildroot/package/thirdreality/python-tater-protocol-compat/0001-allow-import-without-zeroconf.patch"
)
BROADCOM_MK = ROOT / "buildroot/package/thirdreality/broadcom/broadcom.mk"
SENDSPIN_PACKAGE = ROOT / "buildroot/package/thirdreality/sendspin-client"
BUSYBOX_FRAGMENT = ROOT / "buildroot/board/thirdreality/trspk/busybox-tater.fragment"
BLACKLIST = ROOT / "buildroot/board/thirdreality/trspk/blacklist.txt"
POST_BUILD = ROOT / "buildroot/board/thirdreality/trspk/post_build.sh"
NETMONITOR = ROOT / "buildroot/package/thirdreality/tater-s420-firmware/script/netmonitor"
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
    release_workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    release_highlights = RELEASE_HIGHLIGHTS.read_text(encoding="utf-8")
    release_notes_renderer = RELEASE_NOTES_RENDERER.read_text(encoding="utf-8")
    defconfig = DEFCONFIG.read_text(encoding="utf-8")
    package_mk = PACKAGE_MK.read_text(encoding="utf-8")
    package_config = PACKAGE_CONFIG.read_text(encoding="utf-8")
    zeroconf_removal_patch = ZEROCONF_REMOVAL_PATCH.read_text(encoding="utf-8")
    tater_feature_patch = TATER_FEATURE_PATCH.read_text(encoding="utf-8")
    tater_metadata_patch = TATER_METADATA_PATCH.read_text(encoding="utf-8")
    tater_native_only_patch = TATER_NATIVE_ONLY_PATCH.read_text(encoding="utf-8")
    tater_no_frame_sender_patch = TATER_NO_FRAME_SENDER_PATCH.read_text(encoding="utf-8")
    tater_sync_player_patch = TATER_SYNC_PLAYER_PATCH.read_text(encoding="utf-8")
    tater_barge_in_patch = TATER_BARGE_IN_PATCH.read_text(encoding="utf-8")
    tater_wake_sound_patch = TATER_WAKE_SOUND_PATCH.read_text(encoding="utf-8")
    tater_features = TATER_FEATURES.read_text(encoding="utf-8")
    launcher = LAUNCHER.read_text(encoding="utf-8")
    hardware_bridge = HARDWARE_BRIDGE.read_text(encoding="utf-8")
    provisioning = PROVISIONING.read_text(encoding="utf-8")
    provisioning_server = PROVISIONING_SERVER.read_text(encoding="utf-8")
    network_persistence = NETWORK_PERSISTENCE.read_text(encoding="utf-8")
    nand_ota_description = NAND_OTA_DESCRIPTION.read_text(encoding="utf-8")
    nand_ota_filelist = NAND_OTA_FILELIST.read_text(encoding="utf-8")
    supervisor = SUPERVISOR.read_text(encoding="utf-8")
    wifi_init = WIFI_INIT.read_text(encoding="utf-8")
    kernel_fragment = KERNEL_FRAGMENT.read_text(encoding="utf-8")
    key_handler = KEY_HANDLER.read_text(encoding="utf-8")
    protocol_compat_config = PROTOCOL_COMPAT_CONFIG.read_text(encoding="utf-8")
    protocol_compat_mk = PROTOCOL_COMPAT_MK.read_text(encoding="utf-8")
    protocol_compat_no_mdns_patch = PROTOCOL_COMPAT_NO_MDNS_PATCH.read_text(encoding="utf-8")
    broadcom_mk = BROADCOM_MK.read_text(encoding="utf-8")
    busybox_fragment = BUSYBOX_FRAGMENT.read_text(encoding="utf-8")
    blacklist = BLACKLIST.read_text(encoding="utf-8")
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
    require("BR2_PACKAGE_TATER_S420_FIRMWARE=y" in defconfig, "Tater S420 integration is disabled", errors)
    require("BR2_PACKAGE_TR_PROJ_HA_SPEAKER" not in defconfig, "legacy HA project package is selected", errors)
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
    require(
        "Resolve protocol compatibility version" in package_mk
        and "COMMANDS FROM TATER" in package_mk,
        "legacy Home Assistant/ESPHome comments are not rewritten",
        errors,
    )
    require("BR2_PACKAGE_PYTHON_ZEROCONF" not in protocol_compat_config, "protocol compatibility schema selects Zeroconf", errors)
    require("python-zeroconf" not in protocol_compat_mk, "protocol compatibility schema depends on Zeroconf", errors)
    require(
        "+from .client" not in protocol_compat_no_mdns_patch
        and "+from .reconnect_logic" not in protocol_compat_no_mdns_patch,
        "protocol compatibility schema still exports its removed network client",
        errors,
    )
    require(
        not SENDSPIN_PACKAGE.exists() or not any(SENDSPIN_PACKAGE.iterdir()),
        "Sendspin package remains in the source tree",
        errors,
    )
    require("sendspin" not in supervisor.lower(), "supervisor still manages Sendspin", errors)
    require("avahi" not in supervisor.lower(), "supervisor still starts Avahi", errors)
    require("sendspin" not in hardware_bridge.lower(), "hardware bridge still controls Sendspin", errors)
    require("/usr/bin/dbus-send" not in blacklist, "release blacklist removes the LED bridge dependency", errors)
    active_runtime = "\n".join((supervisor, ntp_files["boot sync"], key_handler))
    require("S44bluetooth" not in active_runtime, "active runtime still calls Bluetooth setup", errors)
    require("/etc/bluetooth" not in broadcom_mk, "Broadcom package still installs Bluetooth firmware", errors)
    require("tater-provisioning" in package_mk, "Tater provisioning tools are not installed", errors)
    require(
        "S38tater-network-persistence" in package_mk,
        "persistent Wi-Fi migration is not installed before station startup",
        errors,
    )
    require(
        "/data/conf/wpa_supplicant.conf" in provisioning
        and "/data/conf/wpa_supplicant.conf" in provisioning_server
        and "/data/conf/wpa_supplicant.conf" in network_persistence,
        "Wi-Fi provisioning is not stored on the persistent data partition",
        errors,
    )
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
    require(
        "rootfs.ubifs" in nand_ota_description
        and "boot.img" in nand_ota_description
        and "dtb.img" in nand_ota_description,
        "routine NAND OTA is missing a system image",
        errors,
    )
    for forbidden in ("u-boot.bin", "uboot:", "upgrade_step", "partition_migration"):
        require(
            forbidden not in nand_ota_description and forbidden not in nand_ota_filelist,
            f"routine NAND OTA can reset persistent state through {forbidden}",
            errors,
        )
    require('LVAEvent.CONNECTION' in zeroconf_removal_patch, "Tater connection event is not patched", errors)
    require('-from .zeroconf import HomeAssistantZeroconf' in zeroconf_removal_patch, "Zeroconf removal patch is incomplete", errors)
    require("--tater-url is required" in tater_feature_patch, "Linux voice runtime can still enter ESPHome server mode", errors)
    require("-                server = await loop.create_server(" in tater_native_only_patch, "legacy TCP listener removal patch is incomplete", errors)
    require("+                server = await loop.create_server(" not in tater_native_only_patch, "legacy TCP listener is still enabled", errors)
    require(
        "-from aioesphomeapi._frame_helper.packets import make_plain_text_packets"
        in tater_no_frame_sender_patch,
        "legacy packet-framing import is still active",
        errors,
    )
    require(
        "production image has no legacy TCP listener or packet sender."
        in tater_no_frame_sender_patch,
        "legacy packet sender is not disabled",
        errors,
    )
    require('"tater_connected": state.connected' in tater_feature_patch, "peripheral snapshot still uses HA connection naming", errors)
    require('version     = "1.1.13.post1"' in tater_metadata_patch, "Tater Linux package version metadata is not fixed", errors)
    require('description = "Tater-native Linux voice satellite runtime"' in tater_metadata_patch, "legacy assistant metadata remains active", errors)
    for capability in (
        "live_settings",
        "timers",
        "ota",
        "setup_mode",
        "persistent_media_sessions",
        "tts_overlays",
        "barge_in",
        "wake_sounds",
        "custom_wake_sounds",
    ):
        require(f'"{capability}": True' in tater_features, f"Tater feature is missing: {capability}", errors)
    for capability in (
        "synchronized_media_sessions",
        "stereo_channel_selection",
        "media_playhead_telemetry",
        "media_drift_correction",
        "media_rate_slew",
        "media_render_clock",
    ):
        require(
            f'"{capability}": self._sync_player_available' in tater_features,
            f"synchronized media capability is not guarded by the mpv runtime: {capability}",
            errors,
        )
    require(
        '"audio_session_version": 2 if self._sync_player_available else 1' in tater_features,
        "Tater audio-session v2 is not advertised with the synchronized player",
        errors,
    )
    for capability in (
        "audio_scenes",
        "looping_background_audio",
        "synchronized_tts_overlays",
    ):
        require(
            f'"{capability}": self._sync_overlay_available' in tater_features,
            f"audio mixer capability is not guarded by both mpv players: {capability}",
            errors,
        )
    require(
        '"media_underrun_recovery": self._sync_player_available' in tater_features,
        "media underrun recovery is not guarded by synchronized mpv",
        errors,
    )
    require(
        '"audio_scene_version": 1 if self._sync_overlay_available else 0' in tater_features,
        "Tater audio-scene v1 is not advertised with both synchronized players",
        errors,
    )
    require(
        '"media_output_latency_frames"' in tater_features
        and "_MEDIA_DEFAULT_OUTPUT_LATENCY_FRAMES" in tater_features,
        "S420 synchronized playback does not advertise its output render lead",
        errors,
    )
    for primitive in (
        "prepare_synchronized",
        "synchronized_snapshot",
        "seek_synchronized",
        "set_synchronized_speed",
        "reset_synchronized",
    ):
        require(
            primitive in tater_sync_player_patch,
            f"synchronized mpv primitive is missing: {primitive}",
            errors,
        )
    require(
        'self._mpv_property("audio_pts")' in tater_sync_player_patch,
        "synchronized mpv telemetry does not use the rendered-audio clock",
        errors,
    )
    require(
        "self._mpv.audio_pitch_correction = False" in tater_sync_player_patch,
        "synchronized mpv rate correction can still insert the audible pitch filter",
        errors,
    )
    require(
        'getattr(self, "_tater_barge_in_enabled", False)' in tater_barge_in_patch
        and "self.tts_response_active" in tater_barge_in_patch
        and "self.stop()" in tater_barge_in_patch,
        "Tater barge-in patch does not safely interrupt active TTS",
        errors,
    )
    require(
        'getattr(self, "_tater_wakeup_sound", self.state.wakeup_sound)'
        in tater_wake_sound_patch
        and "self._on_wakeup_sound_finished(wake_word_phrase)" in tater_wake_sound_patch,
        "Tater wake-sound patch does not honor the selected sound or silence setting",
        errors,
    )
    require(
        "files/wake_sounds/." in package_mk,
        "Tater wake-sound assets are not installed into the Linux runtime",
        errors,
    )
    for sound_file in (
        "blip2.wav",
        "message-notification-4.wav",
        "notification-ding.wav",
        "notification-squeak.wav",
        "phone-chime.wav",
        "pop-up-sound.wav",
        "short-definite-fart.wav",
        "star_treck_communications_start_transmission.wav",
        "star_treck_computer_work_beep.wav",
        "tater_notify_digital_blip.wav",
        "turning-off-microphone-percussion-1.wav",
        "wake_word_triggered.wav",
        "waterdrop.wav",
    ):
        require(
            (TATER_WAKE_SOUNDS / sound_file).is_file(),
            f"Tater wake-sound asset is missing: {sound_file}",
            errors,
        )
    for primitive in (
        "_apply_wake_sound_selection",
        "_download_custom_wake_sound",
        "_cached_custom_wake_sound",
        "wake_sound_enabled",
        "wake_sound_url",
    ):
        require(
            primitive in tater_features,
            f"Tater wake-sound runtime primitive is missing: {primitive}",
            errors,
        )
    for primitive in (
        "_run_audio_scene",
        "_run_overlay",
        "_recover_media_timeline",
        "rejoin_count",
        "rejoin_frames",
    ):
        require(
            primitive in tater_features,
            f"Tater audio parity primitive is missing: {primitive}",
            errors,
        )
    require(
        '_OTA_PATH = Path("/data/software.swu")' in tater_features,
        "OTA is not staged at the path consumed by S420 recovery",
        errors,
    )
    require(
        "expected_sha256=expected_sha256" in tater_features
        and "expected_size=expected_size" in tater_features,
        "OTA download is not bound to the release manifest hash and size",
        errors,
    )
    require(
        '"/usr/bin/swupdate",' in tater_features
        and '"-G",' in tater_features
        and '"-k",' in tater_features
        and "str(_SWUPDATE_KEY)" in tater_features,
        "OTA does not arm the signed vendor recovery installer",
        errors,
    )
    require(
        '"-i",' not in tater_features,
        "runtime OTA incorrectly bypasses the vendor recovery install path",
        errors,
    )
    for applet in ("INETD", "TELNET", "TELNETD", "TFTP", "TFTPD"):
        require(
            f"# CONFIG_{applet} is not set" in busybox_fragment,
            f"BusyBox network debug applet is not disabled: {applet}",
            errors,
        )
    for path in ("S41inetd", "S55adbd", "S99ha-speaker", "telnetd", "module-rtp-recv.so", "module-raop-sink.so"):
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
    require("WAKE_WORD=hey_tater" in launcher, "Hey Tater is not the launcher default", errors)
    require("okay_nabu" not in launcher, "launcher retains the old Home Assistant wake word", errors)
    require("-iname '*nabu*'" in package_mk, "Home Assistant wake-word assets are not pruned", errors)
    require("-iname '*nabu*'" in post_build, "incremental builds can retain Home Assistant wake-word assets", errors)
    require(not PRIVATE_KEY.exists(), "private OTA key is present in the source tree", errors)
    require(not PUBLIC_KEY.exists(), "generated OTA public key is present in the source tree", errors)
    require("cp swupdate-priv.pem" not in ota_script, "OTA archive copies its signing key", errors)
    require("rm -f swupdate-priv.pem" in ota_script, "OTA staging does not delete its signing key", errors)
    require(
        'export TATER_SWUPDATE_PRIVATE_KEY_FILE="${ROOT_DIR}/buildroot/board/thirdreality/common/ota/swu/swupdate-priv.pem"' in build_script,
        "build does not use the staged absolute signing-key path",
        errors,
    )
    require(
        "script/render_release_notes.py" in release_workflow
        and '"$RELEASE_DIR/RELEASE_NOTES.md"' in release_workflow,
        "release workflow does not render structured GitHub release notes",
        errors,
    )
    require(
        "## What's Changed" in release_notes_renderer
        and "RELEASE_HIGHLIGHTS.md" in release_notes_renderer,
        "release notes do not include the tracked What's Changed highlights",
        errors,
    )
    require(
        any(line.strip().startswith("- ") for line in release_highlights.splitlines()),
        "release highlights do not contain any What's Changed entries",
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
    require(
        "ready_to_connect_ha" not in ntp_files["boot sync"],
        "NTP startup still plays the Home Assistant onboarding prompt",
        errors,
    )
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
