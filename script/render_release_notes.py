#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE_HIGHLIGHTS_PATH = ROOT / "RELEASE_HIGHLIGHTS.md"


def text(value: Any) -> str:
    return str(value or "").strip()


def size_label(value: Any) -> str:
    try:
        size = int(value or 0)
    except (TypeError, ValueError):
        size = 0
    if size <= 0:
        return "-"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} bytes"


def release_highlights() -> list[str]:
    if not RELEASE_HIGHLIGHTS_PATH.is_file():
        return []
    return [
        line.strip()
        for line in RELEASE_HIGHLIGHTS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render GitHub release notes for Tater ThirdReality S420 firmware."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    version = text(manifest.get("display_version") or manifest.get("version"))
    if not version:
        raise SystemExit("Release manifest does not contain a firmware version.")
    highlights = release_highlights()
    lines = [
        f"# Tater ThirdReality S420 Firmware {version}",
        "",
        "Tater-native firmware for the ThirdReality Voice and Music Assistant Dev Edition.",
        "",
        "## What's Changed",
        "",
        *(highlights or ["- Maintenance firmware update."]),
        "",
        "## Updating",
        "",
        "- Existing Tater S420 satellites can install the signed `ota` artifact from Tater's Firmware tab.",
        "- First installation and recovery use the `factory` image through Tater Local USB.",
        "- Factory flashing requires the ThirdReality debug board, sold as the **With Log** option. Routine OTA updates do not require it.",
        "",
        "## Release Artifacts",
        "",
        "| Artifact | Size | SHA-256 |",
        "| --- | ---: | --- |",
    ]

    devices = manifest.get("devices") if isinstance(manifest.get("devices"), list) else []
    device = devices[0] if devices and isinstance(devices[0], dict) else {}
    artifacts = device.get("artifacts") if isinstance(device.get("artifacts"), dict) else {}
    for kind in ("ota", "factory"):
        artifact = artifacts.get(kind) if isinstance(artifacts.get(kind), dict) else {}
        digest = text(artifact.get("sha256")) or "-"
        lines.append(f"| `{kind}` | {size_label(artifact.get('size_bytes'))} | `{digest}` |")
    lines.extend(
        [
            "",
            "See [the flashing guide](../../blob/main/docs/FLASHING.md) for first-install and recovery instructions.",
            "",
        ]
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
