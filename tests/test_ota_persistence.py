from pathlib import Path
import os
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
OTA_DESCRIPTION = (
    ROOT / "buildroot/board/thirdreality/common/ota/ota-axg/sw-description-nand"
)
OTA_INCREMENT_DESCRIPTION = (
    ROOT
    / "buildroot/board/thirdreality/common/ota/ota-axg/sw-description-nand-increment"
)
OTA_FILELIST = (
    ROOT / "buildroot/board/thirdreality/common/ota/ota-axg/ota-package-filelist-nand"
)
NETWORK_PERSISTENCE = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/S38tater-network-persistence"
)
PROVISIONING = (
    ROOT / "buildroot/package/thirdreality/tater-linux-satellite/files/tater-provisioning"
)
PROVISIONING_SERVER = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/tater-provisioning-server.py"
)
PACKAGE = (
    ROOT / "buildroot/package/thirdreality/tater-linux-satellite/tater-linux-satellite.mk"
)


class OtaPersistenceTests(unittest.TestCase):
    def test_routine_ota_never_writes_bootloader_or_reset_environment(self) -> None:
        descriptions = (
            OTA_DESCRIPTION.read_text(encoding="utf-8"),
            OTA_INCREMENT_DESCRIPTION.read_text(encoding="utf-8"),
        )
        filelist = OTA_FILELIST.read_text(encoding="utf-8")

        self.assertIn('filename = "rootfs.ubifs"', descriptions[0])
        for description in descriptions:
            self.assertIn('filename = "boot.img"', description)
            self.assertIn('filename = "dtb.img"', description)
            for forbidden in ("u-boot.bin", "uboot:", "upgrade_step", "partition_migration"):
                self.assertNotIn(forbidden, description)
                self.assertNotIn(forbidden, filelist)

    def test_wifi_profile_lives_on_data_partition(self) -> None:
        self.assertIn(
            "WPA_CONFIG=/data/conf/wpa_supplicant.conf",
            PROVISIONING.read_text(encoding="utf-8"),
        )
        self.assertIn(
            '"/data/conf/wpa_supplicant.conf"',
            PROVISIONING_SERVER.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "S38tater-network-persistence",
            PACKAGE.read_text(encoding="utf-8"),
        )

    def test_first_boot_migrates_existing_wifi_profile_privately(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            system_config = root / "etc/wpa_supplicant.conf"
            persistent_config = root / "data/conf/wpa_supplicant.conf"
            system_config.parent.mkdir(parents=True)
            system_config.write_text(
                'ctrl_interface=/var/run/wpa_supplicant\nnetwork={\n    ssid="Office"\n}\n',
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "TATER_SYSTEM_WPA_CONFIG": str(system_config),
                    "TATER_PERSISTENT_WPA_CONFIG": str(persistent_config),
                }
            )

            subprocess.run(
                ["/bin/sh", str(NETWORK_PERSISTENCE), "start"],
                check=True,
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertTrue(system_config.is_symlink())
            self.assertEqual(system_config.resolve(), persistent_config.resolve())
            self.assertIn('ssid="Office"', persistent_config.read_text(encoding="utf-8"))
            self.assertEqual(stat.S_IMODE(persistent_config.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
