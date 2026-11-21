"""Source adoption checks against the runtime actually installed by S420."""

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from script import check_shared_runtime as shared


class SharedRuntimeSourceTests(unittest.TestCase):
    def test_pin_archive_and_buildroot_hash_agree(self):
        version = shared.source_version()
        manifest = json.loads((shared.FILES / "shared-runtime.json").read_text())
        archive = (
            shared.ROOT
            / f"buildroot/dl/tater-linux-satellite/tater-linux-satellite-{version}.tar.gz"
        )
        shared.get_test_runtime()
        self.assertEqual(manifest["source_commit"], version)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertEqual(manifest["source_archive_sha256"], digest)
        self.assertIn(
            f"{digest}  {archive.name}",
            (shared.PACKAGE / "tater-linux-satellite.hash").read_text(),
        )

    def test_shared_modules_come_from_the_pinned_source(self):
        runtime = shared.get_test_runtime()
        for name in (
            "tater_oww_onnx.py",
            "wake_boundary.py",
            "bluetooth_proxy.py",
            "bluez_agent.py",
            "bluez_backend.py",
        ):
            self.assertTrue((runtime / name).is_file(), name)
            self.assertFalse((shared.FILES / name).exists(), name)
        self.assertFalse((shared.FILES / "shared_features.py").exists())
        self.assertIn(
            "class TaterFeatureManager", (runtime / "shared_features.py").read_text()
        )
        self.assertIn(
            "shared.TaterFeatureManager", (runtime / "tater_features.py").read_text()
        )
        self.assertIn("wake_preroll_end", (runtime / "tater_native.py").read_text())
        self.assertIn("Tater-Sendspin", (runtime / "sendspin.py").read_text())

    def test_incompatible_update_restores_pin_and_checksums(self):
        version = shared.source_version()
        archive = (
            shared.ROOT
            / f"buildroot/dl/tater-linux-satellite/tater-linux-satellite-{version}.tar.gz"
        )
        shared.get_test_runtime()
        with tempfile.TemporaryDirectory() as work:
            package = Path(work) / "package"
            files = package / "files"
            files.mkdir(parents=True)
            paths = [
                package / "tater-linux-satellite.mk",
                files / "shared-runtime.json",
                package / "tater-linux-satellite.hash",
            ]
            for target in paths:
                original = (
                    shared.FILES / target.name
                    if target.name.endswith("json")
                    else shared.PACKAGE / target.name
                )
                shutil.copyfile(original, target)
            before = {path: path.read_bytes() for path in paths}

            def download(command, **_kwargs):
                shutil.copyfile(archive, command[command.index("--output") + 1])

            with mock.patch.object(shared, "PACKAGE", package), mock.patch.object(
                shared, "FILES", files
            ), mock.patch.object(
                shared.subprocess, "run", side_effect=download
            ), mock.patch.object(
                shared,
                "prepare_runtime",
                side_effect=ValueError("incompatible hardware patch"),
            ):
                with self.assertRaisesRegex(ValueError, "incompatible hardware patch"):
                    shared.advance_source("f" * 40)
            self.assertEqual(before, {path: path.read_bytes() for path in paths})


if __name__ == "__main__":
    unittest.main()
