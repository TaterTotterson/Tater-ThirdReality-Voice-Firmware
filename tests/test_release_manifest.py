import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReleaseManifestTests(unittest.TestCase):
    def test_packages_distinct_factory_and_signed_ota_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            images = temp / "images"
            release = temp / "release"
            images.mkdir()
            factory_data = b"amlogic-factory-image"
            ota_data = b"signed-swupdate-image"
            (images / "trspk_0.2.0.img").write_bytes(factory_data)
            (images / "trspk_0.2.0.swu").write_bytes(ota_data)

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "script/build_release_manifest.py"),
                    "--version",
                    "0.2.0",
                    "--image-dir",
                    str(images),
                    "--release-dir",
                    str(release),
                    "--release-tag",
                    "s420-0.2.0",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            latest = json.loads((release / "latest.json").read_text(encoding="utf-8"))
            manifest_path = next(release.glob("*-manifest.json"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            device = manifest["devices"][0]
            self.assertEqual(device["key"], "thirdreality_s420")
            self.assertEqual(device["firmware_version"], "tater-thirdreality-0.2.0")
            self.assertEqual(device["artifacts"]["factory"]["flash_transport"], "amlogic_usb_burn")
            self.assertFalse(device["artifacts"]["factory"]["browser_flash_supported"])
            self.assertEqual(device["artifacts"]["ota"]["flash_transport"], "tater_native_ota")
            self.assertEqual(device["artifacts"]["factory"]["sha256"], hashlib.sha256(factory_data).hexdigest())
            self.assertEqual(device["artifacts"]["ota"]["sha256"], hashlib.sha256(ota_data).hexdigest())
            self.assertIn("/releases/download/s420-0.2.0/", latest["manifest"])


if __name__ == "__main__":
    unittest.main()
