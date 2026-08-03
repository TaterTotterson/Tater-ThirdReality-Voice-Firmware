import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PORTAL_PATH = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/tater-provisioning-server.py"
)
SPEC = importlib.util.spec_from_file_location("tater_provisioning_server", PORTAL_PATH)
assert SPEC and SPEC.loader
portal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(portal)


class ProvisioningValidationTests(unittest.TestCase):
    def valid_fields(self, **overrides: str) -> dict[str, str]:
        fields = {
            "ssid": "Tater WiFi",
            "wifi_password": "spud-spud",
            "tater_server": "http://192.168.1.20:8080",
            "pairing_code": "one-time-code",
            "room": "Kitchen",
            "name": "Kitchen Tater",
        }
        fields.update(overrides)
        return fields

    def test_accepts_secured_and_open_wifi(self) -> None:
        self.assertEqual(portal.validate_fields(self.valid_fields())["ssid"], "Tater WiFi")
        self.assertEqual(
            portal.validate_fields(self.valid_fields(wifi_password=""))["wifi_password"], ""
        )

    def test_rejects_invalid_wifi_lengths_and_control_characters(self) -> None:
        for fields in (
            self.valid_fields(ssid=""),
            self.valid_fields(ssid="x" * 33),
            self.valid_fields(wifi_password="short"),
            self.valid_fields(ssid="bad\nnetwork"),
            self.valid_fields(tater_server="ftp://tater.example.test"),
            self.valid_fields(tater_server="https://bad host"),
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                portal.validate_fields(fields)

    def test_wpa_config_escapes_values(self) -> None:
        rendered = portal.render_wpa_config('Tater "Lab"', r"eight\chars")
        self.assertIn(r'ssid="Tater \"Lab\""', rendered)
        self.assertIn(r'psk="eight\\chars"', rendered)
        self.assertNotIn("key_mgmt=NONE", rendered)

        open_network = portal.render_wpa_config("Guest", "")
        self.assertIn("key_mgmt=NONE", open_network)
        self.assertNotIn("psk=", open_network)


class ProvisioningPersistenceTests(unittest.TestCase):
    def test_save_writes_private_wifi_and_tater_configs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            wpa_path = root / "etc/wpa_supplicant.conf"
            tater_path = root / "data/conf/tater.json"
            default_path = root / "defaults/tater.json"
            token_path = root / "data/conf/tater-device-token"
            default_path.parent.mkdir(parents=True)
            default_path.write_text(
                json.dumps({"wake_word": "okay_nabu", "debug": False}), encoding="utf-8"
            )
            token_path.parent.mkdir(parents=True)
            token_path.write_text("old-token", encoding="utf-8")

            portal.save_configuration(
                {
                    "ssid": "My Network",
                    "wifi_password": "potato-pass",
                    "tater_server": "https://tater.example.test",
                    "pairing_code": "pair-me",
                    "room": "Den",
                    "name": "Den Speaker",
                },
                wpa_path=wpa_path,
                tater_path=tater_path,
                default_tater_path=default_path,
                token_path=token_path,
            )

            self.assertIn('ssid="My Network"', wpa_path.read_text(encoding="utf-8"))
            saved = json.loads(tater_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["server_url"], "https://tater.example.test")
            self.assertEqual(saved["pairing_code"], "pair-me")
            self.assertEqual(saved["wake_word"], "okay_nabu")
            self.assertFalse(token_path.exists())
            self.assertEqual(stat.S_IMODE(wpa_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(tater_path.stat().st_mode), 0o600)

    def test_page_contains_all_local_setup_fields(self) -> None:
        for field_name in (
            "ssid",
            "wifi_password",
            "tater_server",
            "pairing_code",
            "room",
            "name",
        ):
            self.assertIn(f'name="{field_name}"', portal.PAGE)
        self.assertNotIn("http://", portal.PAGE.replace("http://tater.local:8080", ""))
        self.assertNotIn("https://", portal.PAGE)


if __name__ == "__main__":
    unittest.main()
