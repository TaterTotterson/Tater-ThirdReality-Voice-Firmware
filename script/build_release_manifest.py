#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE_DIR = ROOT / "image"
RELEASE_REPO = "TaterTotterson/Tater-ThirdReality-Voice-Firmware"
DEVICE_KEY = "thirdreality_s420"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_url(repo: str, tag: str, name: str) -> str:
    if "/" not in repo.strip("/"):
        raise SystemExit("--release-repo must use OWNER/REPO format.")
    return f"https://github.com/{repo.strip('/')}/releases/download/{quote(tag, safe='')}/{quote(name, safe='')}"


def artifact(path: Path, *, kind: str, target: str, transport: str) -> dict[str, object]:
    return {
        "kind": kind,
        "path": target,
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
        "flash_transport": transport,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Package Tater S420 release artifacts and manifest.")
    parser.add_argument("--version", required=True, help="Firmware version, for example 0.2.0.")
    parser.add_argument("--image-dir", type=Path, default=DEFAULT_IMAGE_DIR)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--release-repo", default=RELEASE_REPO)
    parser.add_argument("--release-tag", help="GitHub release tag; enables absolute release URLs.")
    args = parser.parse_args()

    version = str(args.version).strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9_.-]+)?", version):
        raise SystemExit(f"Invalid S420 firmware version: {version!r}")

    image_dir = args.image_dir.resolve()
    source_factory = image_dir / f"trspk_{version}.img"
    source_ota = image_dir / f"trspk_{version}.swu"
    for source in (source_factory, source_ota):
        if not source.is_file():
            raise SystemExit(f"Missing build artifact: {source}")

    release_dir = args.release_dir.resolve()
    release_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"tater-thirdreality-s420-{version}"
    factory_name = f"{prefix}-factory.img"
    ota_name = f"{prefix}-ota.swu"
    manifest_name = f"{prefix}-manifest.json"
    factory_path = release_dir / factory_name
    ota_path = release_dir / ota_name
    shutil.copy2(source_factory, factory_path)
    shutil.copy2(source_ota, ota_path)

    def target(name: str) -> str:
        return release_url(args.release_repo, args.release_tag, name) if args.release_tag else name

    instructions_url = f"https://github.com/{args.release_repo}/blob/main/docs/FLASHING.md"
    factory = artifact(factory_path, kind="factory", target=target(factory_name), transport="amlogic_usb_burn")
    factory.update(
        {
            "soc": "axg",
            "requires_debug_board": True,
            "browser_flash_supported": False,
            "instructions_url": instructions_url,
        }
    )
    ota = artifact(ota_path, kind="ota", target=target(ota_name), transport="tater_native_ota")
    manifest = {
        "schema": 1,
        "kind": "tater_native_satellite_firmware",
        "version": version,
        "display_version": version,
        "project": "tater.thirdreality_s420",
        "devices": [
            {
                "key": DEVICE_KEY,
                "label": "Tater ThirdReality S420",
                "board": DEVICE_KEY,
                "firmware_version": f"tater-thirdreality-{version}",
                "display_version": version,
                "project": "tater.thirdreality_s420",
                "flash_transport": "amlogic_usb_burn",
                "artifacts": {"ota": ota, "factory": factory},
            }
        ],
    }
    manifest_path = release_dir / manifest_name
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    latest = {
        "schema": 1,
        "kind": "tater_native_satellite_firmware_latest",
        "version": version,
        "display_version": version,
        "manifest": target(manifest_name),
        "boards": {
            DEVICE_KEY: {
                "label": "Tater ThirdReality S420",
                "board": DEVICE_KEY,
                "version": f"tater-thirdreality-{version}",
                "display_version": version,
                "manifest": target(manifest_name),
            }
        },
    }
    (release_dir / "latest.json").write_text(json.dumps(latest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
