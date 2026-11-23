#!/usr/bin/env python3
"""Prepare and validate the published Linux runtime used by S420 builds/tests."""

import argparse
import atexit
import compileall
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "buildroot/package/thirdreality/tater-linux-satellite"
FILES = PACKAGE / "files"
_test_directory = None


def source_version():
    version = re.search(
        r"^TATER_LINUX_SATELLITE_VERSION = ([0-9a-f]{40})$",
        (PACKAGE / "tater-linux-satellite.mk").read_text(),
        re.M,
    )
    if version is None:
        raise ValueError("The shared source pin must be a full commit SHA")
    return version[1]


def prepare_runtime(destination, archive=None):
    """Mirror the Buildroot source patches and S420 Python install overlays."""
    version = source_version()
    manifest = json.loads((FILES / "shared-runtime.json").read_text())
    if manifest["source_commit"] != version:
        raise ValueError("Shared source provenance does not match the build pin")
    if archive is None:
        archive = (
            ROOT
            / f"buildroot/dl/tater-linux-satellite/tater-linux-satellite-{version}.tar.gz"
        )
    if not archive.is_file():
        archive.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="tater-source-download-") as work:
            downloaded = Path(work) / "source.tar.gz"
            subprocess.run(
                [
                    "curl",
                    "--fail",
                    "--location",
                    "--silent",
                    "--show-error",
                    "--retry",
                    "3",
                    "--connect-timeout",
                    "15",
                    "--max-time",
                    "180",
                    f"https://github.com/TaterTotterson/Tater-Linux-Satellite/archive/{version}.tar.gz",
                    "--output",
                    str(downloaded),
                ],
                check=True,
            )
            if (
                hashlib.sha256(downloaded.read_bytes()).hexdigest()
                != manifest["source_archive_sha256"]
            ):
                raise ValueError("Downloaded shared source checksum mismatch")
            shutil.copyfile(downloaded, archive)
    if (
        hashlib.sha256(archive.read_bytes()).hexdigest()
        != manifest["source_archive_sha256"]
    ):
        raise ValueError("Cached shared source checksum mismatch")
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["tar", "-xzf", str(archive), "--strip-components=1", "-C", str(destination)],
        check=True,
    )
    subprocess.run(
        [
            "bash",
            str(ROOT / "buildroot/support/scripts/apply-patches.sh"),
            str(destination),
            str(PACKAGE),
            "*.patch",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    module = destination / "linux_voice_assistant"
    # The wheel supplies every shared module. Install the original manager
    # alongside the thin S420 subclass, exactly as the Buildroot resource hook.
    (module / "tater_features.py").rename(module / "shared_features.py")
    for name in ("tater_features.py", "s420_audio.py"):
        shutil.copyfile(FILES / name, module / name)
    # Match the production private protobuf dependency's import names.
    for path in module.glob("*.py"):
        source = path.read_text().replace("aioesphomeapi", "tater_protocol_compat")
        source = source.replace(
            "get_esphome_version", "get_protocol_compat_version"
        ).replace("esphome_version", "protocol_compat_version")
        source = (
            source.replace("ESPHomeEntity", "TaterEntity")
            .replace("ESPHome", "legacy API")
            .replace("Home Assistant", "legacy controller")
        )
        path.write_text(source)
    if not compileall.compile_dir(module, quiet=1):
        raise ValueError("Adapted S420 runtime does not compile")
    return module


def get_test_runtime():
    """Reuse one actual pinned runtime for structural and isolated unit tests."""
    global _test_directory
    if _test_directory is None:
        _test_directory = tempfile.TemporaryDirectory(prefix="tater-s420-runtime-")
        atexit.register(_test_directory.cleanup)
        prepare_runtime(Path(_test_directory.name))
    return Path(_test_directory.name) / "linux_voice_assistant"


def build_runtime_wheel(source):
    """Exercise the same PEP 517 packaging step used by Buildroot."""
    with tempfile.TemporaryDirectory(prefix="tater-s420-wheel-") as work:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--no-isolation",
                "--wheel",
                "--outdir",
                work,
                str(source),
            ],
            check=True,
        )
        wheels = list(Path(work).glob("*.whl"))
        if len(wheels) != 1:
            raise ValueError("The shared runtime must produce exactly one wheel")
        with zipfile.ZipFile(wheels[0]) as wheel:
            for name in (
                "linux_voice_assistant/tater_native.py",
                "linux_voice_assistant/wake_boundary.py",
                "linux_voice_assistant/shared_features.py",
                "linux_voice_assistant/tater_features.py",
                "linux_voice_assistant/s420_audio.py",
            ):
                if name not in wheel.namelist():
                    raise ValueError(f"Runtime wheel is missing {name}")


def advance_source(version):
    """Validate a new published source before keeping its pin/checksums."""
    if not re.fullmatch(r"[0-9a-f]{40}", version):
        raise ValueError("The new source must be a full commit SHA")
    paths = [
        PACKAGE / "tater-linux-satellite.mk",
        FILES / "shared-runtime.json",
        PACKAGE / "tater-linux-satellite.hash",
    ]
    previous = {path: path.read_bytes() for path in paths}
    with tempfile.TemporaryDirectory(prefix="tater-source-update-") as work:
        archive = Path(work) / f"tater-linux-satellite-{version}.tar.gz"
        subprocess.run(
            [
                "curl",
                "--fail",
                "--location",
                "--silent",
                "--show-error",
                "--retry",
                "3",
                "--connect-timeout",
                "15",
                "--max-time",
                "180",
                f"https://github.com/TaterTotterson/Tater-Linux-Satellite/archive/{version}.tar.gz",
                "--output",
                str(archive),
            ],
            check=True,
        )
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        with tarfile.open(archive) as source:
            license_name = next(
                name
                for name in source.getnames()
                if name.count("/") == 1 and name.endswith("/LICENSE.md")
            )
            license_digest = hashlib.sha256(
                source.extractfile(license_name).read()
            ).hexdigest()
        try:
            paths[0].write_text(
                re.sub(
                    r"^TATER_LINUX_SATELLITE_VERSION = .*$",
                    f"TATER_LINUX_SATELLITE_VERSION = {version}",
                    paths[0].read_text(),
                    flags=re.M,
                )
            )
            paths[1].write_text(
                json.dumps(
                    {
                        "source_repository": "https://github.com/TaterTotterson/Tater-Linux-Satellite",
                        "source_commit": version,
                        "source_archive_sha256": digest,
                    },
                    indent=2,
                )
                + "\n"
            )
            paths[2].write_text(
                f"# Published shared Linux source and license.\nsha256  {digest}  {archive.name}\nsha256  {license_digest}  LICENSE.md\n"
            )
            prepare_runtime(Path(work) / "runtime", archive)
        except BaseException:
            for path, contents in previous.items():
                path.write_bytes(contents)
            raise
        cached = ROOT / "buildroot/dl/tater-linux-satellite" / archive.name
        cached.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(archive, cached)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", type=Path)
    parser.add_argument(
        "--wheel",
        action="store_true",
        help="also build the runtime wheel (requires Buildroot's Python build tools)",
    )
    parser.add_argument(
        "--advance",
        metavar="COMMIT",
        help="update the pin/provenance only if its hardware patches compile",
    )
    args = parser.parse_args()
    if args.advance:
        advance_source(args.advance)
        print(
            f"Advanced the shared runtime to {source_version()}. Run CI and hardware tests before release."
        )
        return
    with tempfile.TemporaryDirectory(prefix="tater-s420-runtime-") as work:
        prepare_runtime(Path(work), args.archive)
        if args.wheel:
            build_runtime_wheel(Path(work))
    print(
        f"Published shared runtime patches, installs and compiles for {source_version()}."
    )


if __name__ == "__main__":
    main()
