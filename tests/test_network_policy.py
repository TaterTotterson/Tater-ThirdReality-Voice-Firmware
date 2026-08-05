from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
NETMONITOR = ROOT / "buildroot/package/thirdreality/tater-s420-firmware/script/netmonitor"
NTP_CONFIG = ROOT / "buildroot/board/thirdreality/trspk/rootfs/etc/ntp.conf"
BUSYBOX_FRAGMENT = ROOT / "buildroot/board/thirdreality/trspk/busybox-tater.fragment"
POST_BUILD = ROOT / "buildroot/board/thirdreality/trspk/post_build.sh"
NTP_BOOT = ROOT / "buildroot/package/ntp/ntpdate.sh"
SPEAKER_PACKAGE = (
    ROOT
    / "buildroot/package/thirdreality/tater-s420-firmware/tater-s420-firmware.mk"
)
VOICE_PACKAGE = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/tater-linux-satellite.mk"
)
VOICE_LAUNCHER = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/tater-satellite-launcher"
)
PROTOCOL_COMPAT_PATCH = (
    ROOT
    / "buildroot/package/thirdreality/python-tater-protocol-compat/0001-allow-import-without-zeroconf.patch"
)
NO_FRAME_SENDER_PATCH = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/0005-remove-legacy-frame-sender.patch"
)


class NetworkPolicyTests(unittest.TestCase):
    def test_connectivity_probe_only_uses_paired_tater_server(self) -> None:
        script = NETMONITOR.read_text(encoding="utf-8")
        self.assertIn('TATER_CONF="/data/conf/tater.json"', script)
        self.assertIn("get_tater_check_url", script)
        for forbidden in (
            "connectivitycheck.gstatic.com",
            "captive.apple.com",
            "8.8.8.8",
            "ota.cloud.3reality.com",
        ):
            self.assertNotIn(forbidden, script)

    def test_ntp_fallback_is_us_only(self) -> None:
        config = NTP_CONFIG.read_text(encoding="utf-8")
        self.assertIn(".nist.gov", config)
        for forbidden in (".cn", "aliyun", "tencent", "ntp.org.cn"):
            self.assertNotIn(forbidden, config.lower())

    def test_remote_debug_applets_are_disabled_and_pruned(self) -> None:
        fragment = BUSYBOX_FRAGMENT.read_text(encoding="utf-8")
        post_build = POST_BUILD.read_text(encoding="utf-8")
        for applet in ("INETD", "TELNET", "TELNETD", "TFTP", "TFTPD"):
            self.assertIn(f"# CONFIG_{applet} is not set", fragment)
        for path in ("S41inetd", "S55adbd", "telnetd"):
            self.assertIn(path, post_build)

    def test_tater_voice_import_does_not_restore_mdns(self) -> None:
        patch = PROTOCOL_COMPAT_PATCH.read_text(encoding="utf-8")
        post_build = POST_BUILD.read_text(encoding="utf-8")
        self.assertIn("Internal protocol compatibility types", patch)
        self.assertNotIn("+from .client", patch)
        self.assertNotIn("+from .reconnect_logic", patch)
        self.assertIn("aioesphomeapi-discover", post_build)
        self.assertIn("aioesphomeapi-logs", post_build)
        self.assertIn("aioesphomeapi-42.7.0-py3.11.egg-info", post_build)

    def test_tater_runtime_does_not_import_pruned_frame_helper(self) -> None:
        patch = NO_FRAME_SENDER_PATCH.read_text(encoding="utf-8")
        post_build = POST_BUILD.read_text(encoding="utf-8")
        self.assertIn(
            "-from aioesphomeapi._frame_helper.packets import make_plain_text_packets",
            patch,
        )
        self.assertIn('rm -rf "$PROTOCOL_COMPAT_DIR/_frame_helper"', post_build)

    def test_home_assistant_onboarding_prompt_is_not_shipped(self) -> None:
        ntp_boot = NTP_BOOT.read_text(encoding="utf-8")
        package = SPEAKER_PACKAGE.read_text(encoding="utf-8")
        post_build = POST_BUILD.read_text(encoding="utf-8")
        self.assertNotIn("ready_to_connect_ha", ntp_boot)
        self.assertNotIn("ready_to_connect_ha", package)
        self.assertIn("ready_to_connect_ha.wav", post_build)

    def test_legacy_ha_service_is_pruned(self) -> None:
        package = SPEAKER_PACKAGE.read_text(encoding="utf-8")
        post_build = POST_BUILD.read_text(encoding="utf-8")
        self.assertIn("S99tater-satellite", package)
        self.assertNotIn("S99ha-speaker", package)
        self.assertIn("S99ha-speaker", post_build)

    def test_home_assistant_wake_words_are_pruned(self) -> None:
        package = VOICE_PACKAGE.read_text(encoding="utf-8")
        launcher = VOICE_LAUNCHER.read_text(encoding="utf-8")
        post_build = POST_BUILD.read_text(encoding="utf-8")
        self.assertIn("-iname '*nabu*'", package)
        self.assertIn("-iname '*nabu*'", post_build)
        self.assertNotIn("okay_nabu", launcher)
        self.assertIn('[ ! -f "$WAKE_MODEL" ]', launcher)


if __name__ == "__main__":
    unittest.main()
