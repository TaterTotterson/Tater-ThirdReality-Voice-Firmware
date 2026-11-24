"""Source adoption checks against the runtime actually installed by S420."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import threading
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
            "atomic_file.py",
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

    def test_installed_atomic_writer_handles_overlapping_downloads(self):
        spec = importlib.util.spec_from_file_location(
            "s420_atomic_file", shared.get_test_runtime() / "atomic_file.py"
        )
        writer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(writer)
        barrier = threading.Barrier(2)
        replace = writer.os.replace

        def publish(source, target):
            barrier.wait(timeout=5)
            replace(source, target)

        with tempfile.TemporaryDirectory() as work:
            target = Path(work) / "wake.onnx"
            payloads = (b"first-model" * 1024, b"second-model" * 1024)
            with mock.patch.object(writer.os, "replace", side_effect=publish):
                with ThreadPoolExecutor(max_workers=2) as workers:
                    pending = [
                        workers.submit(writer.write_bytes_atomic, target, payload)
                        for payload in payloads
                    ]
                    for future in pending:
                        future.result(timeout=10)
            self.assertIn(target.read_bytes(), payloads)
            self.assertEqual(list(target.parent.iterdir()), [target])

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
