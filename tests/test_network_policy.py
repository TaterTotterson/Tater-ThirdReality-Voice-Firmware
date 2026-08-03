from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
NETMONITOR = ROOT / "buildroot/package/thirdreality/tr-proj-ha-speaker/script/netmonitor"
NTP_CONFIG = ROOT / "buildroot/board/thirdreality/trspk/rootfs/etc/ntp.conf"
BUSYBOX_FRAGMENT = ROOT / "buildroot/board/thirdreality/trspk/busybox-tater.fragment"
POST_BUILD = ROOT / "buildroot/board/thirdreality/trspk/post_build.sh"


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


if __name__ == "__main__":
    unittest.main()
