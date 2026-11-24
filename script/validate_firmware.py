#!/usr/bin/env python3
"""Fast structural checks for the Tater production defconfig."""

from pathlib import Path
import hashlib
import re
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = ROOT / ".github/workflows/release-firmware.yml"
SOURCE_UPDATE_WORKFLOW = ROOT / ".github/workflows/tater-source-parity.yml"
SOURCE_UPDATE_SCRIPT = ROOT / "script/update_tater_linux_source.sh"
RELEASE_HIGHLIGHTS = ROOT / "RELEASE_HIGHLIGHTS.md"
RELEASE_NOTES_RENDERER = ROOT / "script/render_release_notes.py"
DEFCONFIG = ROOT / "buildroot/configs/3reality_trspk_defconfig"
PACKAGE_MK = ROOT / "buildroot/package/thirdreality/tater-linux-satellite/tater-linux-satellite.mk"
PACKAGE_CONFIG = ROOT / "buildroot/package/thirdreality/tater-linux-satellite/Config.in"
TATER_OWW_BRIDGE = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/tater_oww_ort.c"
)
TATER_OWW_ASSETS = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/openwakeword"
)
ONNXRUNTIME_MK = (
    ROOT
    / "buildroot/package/thirdreality/onnxruntime-aarch64/onnxruntime-aarch64.mk"
)
ONNXRUNTIME_HASH = (
    ROOT
    / "buildroot/package/thirdreality/onnxruntime-aarch64/onnxruntime-aarch64.hash"
)
WEBRTC_AEC_PATCH = (
    ROOT
    / "buildroot/package/thirdreality/python-webrtc-noise-gain/0001-add-playback-reference-aec.patch"
)
TATER_FEATURES = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/tater_features.py"
)
S420_AUDIO = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/s420_audio.py"
)
BLUETOOTH_INIT = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/S44tater-bluetooth"
)
S420_AUDIO_DIAGNOSTIC = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/tater-s420-audio-diagnostic"
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
KERNEL_FRAGMENT = ROOT / "buildroot/board/thirdreality/trspk/linux-tater.fragment"
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
SENDSPIN_MK = SENDSPIN_PACKAGE / "sendspin-client.mk"
SENDSPIN_WRAPPER = SENDSPIN_PACKAGE / "files/tater-sendspin"
SENDSPIN_ROUTING_PATCH = SENDSPIN_PACKAGE / "0001-add-tater-output-channel-routing.patch"
SENDSPIN_OPUS_PATCH = SENDSPIN_PACKAGE / "0002-filter-disabled-opus-from-advertisement.patch"
SENDSPIN_LEGACY_NOISE_PATCH = (
    SENDSPIN_PACKAGE / "0003-accept-legacy-noise-handshake-without-psk-category.patch"
)
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
    source_update_workflow = SOURCE_UPDATE_WORKFLOW.read_text(encoding="utf-8")
    source_update_script = SOURCE_UPDATE_SCRIPT.read_text(encoding="utf-8")
    release_highlights = RELEASE_HIGHLIGHTS.read_text(encoding="utf-8")
    release_notes_renderer = RELEASE_NOTES_RENDERER.read_text(encoding="utf-8")
    defconfig = DEFCONFIG.read_text(encoding="utf-8")
    package_mk = PACKAGE_MK.read_text(encoding="utf-8")
    package_config = PACKAGE_CONFIG.read_text(encoding="utf-8")
    # Import here so --help and packaging tools don't fetch runtime sources.
    sys.path.insert(0, str(ROOT / "script"))
    from check_shared_runtime import get_test_runtime
    runtime = get_test_runtime()
    runtime_main = (runtime / "__main__.py").read_text()
    runtime_native = (runtime / "tater_native.py").read_text()
    runtime_satellite = (runtime / "satellite.py").read_text()
    runtime_api = (runtime / "api_server.py").read_text()
    runtime_player = (runtime / "player/libmpv.py").read_text()
    runtime_metadata = (runtime.parent / "pyproject.toml").read_text()
    tater_oww_python = (runtime / "tater_oww_onnx.py").read_text()
    tater_oww_bridge = TATER_OWW_BRIDGE.read_text(encoding="utf-8")
    onnxruntime_mk = ONNXRUNTIME_MK.read_text(encoding="utf-8")
    onnxruntime_hash = ONNXRUNTIME_HASH.read_text(encoding="utf-8")
    webrtc_aec_patch = WEBRTC_AEC_PATCH.read_text(encoding="utf-8")
    hardware_features = TATER_FEATURES.read_text(encoding="utf-8")
    tater_features = (runtime / "shared_features.py").read_text() + "\n" + hardware_features
    s420_audio = S420_AUDIO.read_text(encoding="utf-8")
    bluetooth_proxy = (runtime / "bluetooth_proxy.py").read_text()
    bluetooth_init = BLUETOOTH_INIT.read_text(encoding="utf-8")
    s420_audio_diagnostic = S420_AUDIO_DIAGNOSTIC.read_text(encoding="utf-8")
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
    sendspin_mk = SENDSPIN_MK.read_text(encoding="utf-8")
    sendspin_wrapper = SENDSPIN_WRAPPER.read_text(encoding="utf-8")
    sendspin_routing_patch = SENDSPIN_ROUTING_PATCH.read_text(encoding="utf-8")
    sendspin_opus_patch = SENDSPIN_OPUS_PATCH.read_text(encoding="utf-8")
    sendspin_legacy_noise_patch = SENDSPIN_LEGACY_NOISE_PATCH.read_text(encoding="utf-8")
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
    require("BR2_PACKAGE_SENDSPIN_CLIENT=y" in defconfig, "Sendspin is disabled", errors)
    require("BR2_PACKAGE_BLUEZ5_UTILS=y" in defconfig, "BlueZ GATT backend is disabled", errors)
    require(
        "BR2_PACKAGE_PYTHON_BLEAK=y" in defconfig,
        "Bleak GATT backend is disabled",
        errors,
    )
    require(
        'BR2_LINUX_KERNEL_CONFIG_FRAGMENT_FILES="board/thirdreality/trspk/linux-tater.fragment"'
        in defconfig,
        "Tater kernel fragment is not selected",
        errors,
    )
    require("CONFIG_BT=y" in kernel_fragment, "kernel Bluetooth stack is disabled", errors)
    require("CONFIG_BT_LE=y" in kernel_fragment, "kernel BLE support is disabled", errors)
    require("CONFIG_BT_HCIUART=y" in kernel_fragment, "kernel HCI UART support is disabled", errors)
    require("# CONFIG_BT_BREDR is not set" in kernel_fragment, "Bluetooth Classic is enabled", errors)
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
    require("github,Sendspin,sendspin-cpp-cli" in sendspin_mk, "official Sendspin CLI is not pinned", errors)
    require("github,Sendspin,sendspin-cpp" in sendspin_mk, "official Sendspin library is not pinned", errors)
    require("SENDSPIN_CLIENT_NOISE_C_VERSION" in sendspin_mk, "Sendspin Noise dependency is not pinned", errors)
    require("SENDSPIN_CLI_WITH_PULSE=ON" in sendspin_mk, "Sendspin PulseAudio output is disabled", errors)
    require("BUILD_SHARED_LIBS=OFF" in sendspin_mk, "Sendspin bundled libraries are not static", errors)
    require("SENDSPIN_CLI_WITH_MDNS=ON" in sendspin_mk, "Sendspin mDNS discovery is disabled", errors)
    for primitive in (
        "--allow-unpaired",
        "--port 8928",
        "--output pulse",
        "--mdns-name",
        "TATER_SENDSPIN_OUTPUT_CHANNEL",
    ):
        require(primitive in sendspin_wrapper, f"Sendspin runtime option is missing: {primitive}", errors)
    require("--no-config" not in sendspin_wrapper, "Sendspin uses an unsupported --no-config flag", errors)
    require("return {{48000}, {16}, {2}};" in sendspin_routing_patch, "Sendspin format is not bounded for S420 audio", errors)
    require(
        "#ifdef SENDSPIN_ENABLE_OPUS" in sendspin_opus_patch
        and "std::array<SendspinCodecFormat, 2> CODEC_PREFERENCE" in sendspin_opus_patch
        and "SendspinCodecFormat::FLAC, SendspinCodecFormat::PCM" in sendspin_opus_patch,
        "Opus-disabled Sendspin build can still advertise an unavailable decoder",
        errors,
    )
    require(
        "psk_category_code.empty()" in sendspin_legacy_noise_patch
        and "PskCategory::LONG_TERM" in sendspin_legacy_noise_patch
        and "PskCategory::PAIRING" in sendspin_legacy_noise_patch
        and "PskCategory::SENTINEL" in sendspin_legacy_noise_patch,
        "Sendspin does not accept Music Assistant's legacy Noise handshake",
        errors,
    )
    for primitive in ("OutputChannel::Left", "OutputChannel::Right", "OutputChannel::Mono"):
        require(primitive in sendspin_routing_patch, f"Sendspin output route is missing: {primitive}", errors)
    require("start_sendspin" in supervisor, "supervisor does not manage Sendspin", errors)
    require("sendspin" not in hardware_bridge.lower(), "hardware bridge still controls Sendspin", errors)
    require("/usr/bin/dbus-send" not in blacklist, "release blacklist removes the LED bridge dependency", errors)
    require("S44tater-bluetooth" in package_mk, "Tater BLE controller init is not installed", errors)
    require("brcm_patchram_plus" in bluetooth_init, "Broadcom BLE firmware loader is missing", errors)
    require("/dev/ttyS1" in bluetooth_init, "Broadcom BLE UART is not configured", errors)
    require("bcm4343a1.hcd" in broadcom_mk, "Broadcom BLE firmware is not installed", errors)
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
    require('LVAEvent.CONNECTION' in runtime_main, "Tater connection event is missing", errors)
    require('from .zeroconf import' not in runtime_main, "Legacy mDNS discovery remains enabled", errors)
    require('Tater native server URL is required' in runtime_main, "Firmware can still enter legacy server mode", errors)
    require('loop.create_server(' not in runtime_main, "Legacy TCP listener remains enabled", errors)
    require('make_plain_text_packets' not in runtime_api, "Legacy packet sender remains enabled", errors)
    require('"tater_connected": state.connected' in (runtime / "peripheral_api.py").read_text(), "Peripheral snapshot uses legacy connection naming", errors)
    project_metadata = tomllib.loads(runtime_metadata)["project"]
    require(
        project_metadata.get("version")
        == (runtime.parent / "version.txt").read_text().strip()
        and "version" not in project_metadata.get("dynamic", []),
        "Firmware package metadata does not match the pinned runtime version",
        errors,
    )
    require('description = "Tater-native Linux voice satellite runtime"' in runtime_metadata, "Firmware metadata is missing", errors)
    for capability in (
        "live_settings",
        "timers",
        "ota",
        "setup_mode",
        "tts_overlays",
        "barge_in",
        "wake_sounds",
        "custom_wake_sounds",
        "wake_verifier",
        "wake_sensitivity",
        "wake_environment_profiles",
        "wake_during_playback",
        "playback_reference_aec",
        "openwakeword",
        "nanowakeword",
        "wake_detector_selection",
        "dual_wake_confirmation",
        "sendspin_player",
        "sendspin_output_channel_selection",
        "ble_advertisements",
    ):
        require(f'"{capability}":' in tater_features or f'{capability}=True' in tater_features, f"Tater feature is missing: {capability}", errors)
    require(
        "submit_wake_audio(audio_chunk)" in runtime_main
        and "resolve_wake_detection(activated)" in runtime_main,
        "the one-stream MWW/OWW/NWW wake fan-out patch is incomplete",
        errors,
    )
    for primitive in (
        "class OWWWorker",
        "queue.Queue(maxsize=2)",
        "os.sched_setaffinity",
        "_reset_requested",
        "tater_oww_push",
    ):
        require(primitive in tater_oww_python, f"ONNX OWW worker primitive is missing: {primitive}", errors)
    for primitive in (
        "OWW_CHUNK_SAMPLES 1280",
        "OWW_MEL_WINDOW 76",
        "OWW_FEATURE_DIM 96",
        "OWW_FEATURE_WINDOW 16",
        "SetIntraOpNumThreads(options, 1)",
        "ORT_SEQUENTIAL",
    ):
        require(primitive in tater_oww_bridge, f"ONNX OWW native primitive is missing: {primitive}", errors)
    require(
        "ONNXRUNTIME_AARCH64_VERSION = 1.22.0" in onnxruntime_mk
        and "ONNXRUNTIME_AARCH64_INSTALL_TARGET_CMDS" in onnxruntime_mk,
        "the pinned ARM64 ONNX Runtime package is incomplete",
        errors,
    )
    require(
        "bb76395092d150b52c7092dc6b8f2fe4d80f0f3bf0416d2f269193e347e24702"
        in onnxruntime_hash,
        "the ARM64 ONNX Runtime source hash is missing",
        errors,
    )
    onnxruntime_archive = ONNXRUNTIME_MK.parent / "onnxruntime-linux-aarch64-1.22.0.tgz"
    require(onnxruntime_archive.is_file(), "the bundled ARM64 ONNX Runtime archive is missing", errors)
    if onnxruntime_archive.is_file():
        require(
            hashlib.sha256(onnxruntime_archive.read_bytes()).hexdigest()
            == "bb76395092d150b52c7092dc6b8f2fe4d80f0f3bf0416d2f269193e347e24702",
            "the bundled ARM64 ONNX Runtime archive failed SHA-256 verification",
            errors,
        )
    onnx_wake_asset_hashes = {
        "melspectrogram.onnx": "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f",
        "embedding_model.onnx": "70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f",
        "hey_tater.oww.onnx": "11d4b310e8f6caf2d7e85a68fc92a10a9ded917bb90c123de78432aacb867b5a",
        "hey_tater.oww.json": "01b70e9e1aa2c2adbf97e683bf7acfa8615c67a51bac7ae6186fe737ed4b6b0a",
        "hey_tater.nww.cnn.onnx": "0b259e7a806e2eed9ad9f1931430d6a6e9546dceb31652e4a29c71925e42e470",
        "hey_tater.nww.gru.onnx": "1a2b3c348c2c75bb8558fa6a710d7b8e7a720d7d3aa6c21b8e5a4f6be67ec94c",
        "hey_tater.wake-bundle.json": "16cc233878dc15b0b210981aa25d7a23ab297b8aab1bb914ac65ae53dc0696d2",
        "hey_tater.boundary.tflite": "75e3e5886be64ce67be15a75197a01dfce2e9136a2a26f455d82cc7ac92c2991",
    }
    for asset_name, expected_hash in onnx_wake_asset_hashes.items():
        asset = TATER_OWW_ASSETS / asset_name
        require(asset.is_file(), f"ONNX wake asset is missing: {asset_name}", errors)
        if asset.is_file():
            actual_hash = hashlib.sha256(asset.read_bytes()).hexdigest()
            require(actual_hash == expected_hash, f"ONNX wake asset hash changed: {asset_name}", errors)
    for module in ("bluetooth_proxy.py", "bluez_backend.py", "bluez_agent.py"):
        require((runtime / module).is_file(), f"Bluetooth proxy module is not installed: {module}", errors)
    require("ble_scanner.py" not in package_mk, "obsolete presence scanner is still installed", errors)
    require('action in {"scan", "stop_scan"}' in bluetooth_proxy, "bounded discovery commands are missing", errors)
    require("self.backend.connected()" in bluetooth_proxy, "active GATT connections do not retain the radio", errors)
    require("--tosleep=200000" in bluetooth_init, "BLE patchram sleep syntax is invalid", errors)
    require("--patchram" in bluetooth_init, "BLE patchram firmware syntax is invalid", errors)
    require("should_pause=self._ble_should_pause" in runtime_native, "Bluetooth discovery is not audio-aware", errors)
    require("self._bluetooth.handle_message(body)" in runtime_native, "Bluetooth proxy commands are not routed", errors)
    require(
        'sendspin_version=1' in hardware_features
        and 'sendspin_output_channel_modes=["stereo", "left", "right", "mono"]' in hardware_features,
        "Sendspin v1 capabilities are incomplete",
        errors,
    )
    for capability in (
        "audio_scenes",
        "looping_background_audio",
    ):
        require(
            f'"{capability}": self._sync_overlay_available' in tater_features,
            f"audio mixer capability is not guarded by both mpv players: {capability}",
            errors,
        )
    require(
        '"audio_scene_version": 1 if self._sync_overlay_available else 0' in tater_features,
        "Tater audio-scene v1 is not advertised with both synchronized players",
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
            primitive in runtime_player,
            f"synchronized mpv primitive is missing: {primitive}",
            errors,
        )
    require(
        'self._mpv_property("audio_pts")' in runtime_player,
        "synchronized mpv telemetry does not use the rendered-audio clock",
        errors,
    )
    require(
        "self._mpv.audio_pitch_correction = False" in runtime_player,
        "synchronized mpv rate correction can still insert the audible pitch filter",
        errors,
    )
    require(
        'getattr(self, "_tater_barge_in_enabled", False)' in runtime_satellite
        and "self.tts_response_active" in runtime_satellite
        and "self.stop()" in runtime_satellite,
        "Tater barge-in patch does not safely interrupt active TTS",
        errors,
    )
    require(
        'wakeup_sound = self.state.wakeup_sound' in runtime_satellite
        and 'self.state.wakeup_sound = self.satellite._tater_wakeup_sound' in tater_features
        and "self._on_wakeup_sound_finished(wake_word_phrase)" in runtime_satellite,
        "Tater wake-sound patch does not honor the selected sound or silence setting",
        errors,
    )
    for primitive in (
        "_wake_audio_snapshot",
        "_queue_wake_verification",
        "_start_local_wake",
    ):
        require(
            primitive in runtime_native,
            f"Tater wake-verifier runtime hook is missing: {primitive}",
            errors,
        )
    for primitive in (
        'struct.Struct("<4sBBHIII")',
        'b"TWV1"',
        "wake.verify.result",
        "wake_verifier_mode",
        "wake_verifier_window_ms",
        "wake_verifier_timeout_ms",
        "_wake_verifier_status",
    ):
        require(
            primitive in runtime_native,
            f"Tater STT wake-verifier primitive is missing: {primitive}",
            errors,
        )
    for primitive in (
        "--s420-four-channel-device",
        "reference_audio",
        "far_end_active",
        "echo_cancellation=use_aec",
    ):
        require(
            primitive in runtime_main,
            f"S420 playback-reference AEC hook is missing: {primitive}",
            errors,
        )
    for primitive in (
        "SetEchoCancellation",
        "ProcessReverse10ms",
        "ProcessReverseStream",
    ):
        require(
            primitive in webrtc_aec_patch,
            f"WebRTC playback-reference primitive is missing: {primitive}",
            errors,
        )
    require(
        'samples[:, 0]' in s420_audio
        and 'samples[:, 2]' in s420_audio
        and 'samples[:, 3]' in s420_audio,
        "S420 four-channel mapping is incomplete",
        errors,
    )
    require(
        "soundcard_fallback" in s420_audio,
        "S420 direct capture does not preserve the existing mono fallback",
        errors,
    )
    require(
        "No PCM is saved" in s420_audio_diagnostic,
        "S420 audio diagnostic does not document its non-recording behavior",
        errors,
    )
    for primitive in (
        "wake_sensitivity",
        "wake_environment",
        "tv_nearby",
        "require_verification",
        "_wake_detection_policy",
    ):
        require(
            primitive in tater_features,
            f"S420 wake policy primitive is missing: {primitive}",
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
    require(
        "--s420-four-channel-device hw:0,4" in launcher,
        "S420 synchronized capture is not enabled by the launcher",
        errors,
    )
    require(
        '--mic-volume "$MIC_VOLUME"' in launcher and "MIC_VOLUME=1600" not in launcher,
        "S420 launcher does not preserve its configured 1x microphone gain",
        errors,
    )
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
        "name: Tater Linux Update Check" in source_update_workflow
        and "update_tater_linux_source.sh --report" in source_update_workflow,
        "scheduled Tater Linux update check is not using non-failing report mode",
        errors,
    )
    require(
        "--check|--report|--update" in source_update_script
        and "GITHUB_STEP_SUMMARY" in source_update_script,
        "Tater Linux source updater does not preserve report and strict-check modes",
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
