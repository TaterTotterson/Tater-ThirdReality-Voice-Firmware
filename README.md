# Tater ThirdReality Voice Firmware

Tater firmware for the
[ThirdReality Voice & Music Assistant](https://github.com/thirdreality/voice-music-assistant).
This is an independent firmware fork that retains the vendor's Amlogic board
support and Sendspin music client while replacing its voice application with
[Tater Linux Voice](https://github.com/TaterTotterson/Tater-Linux-Satellite).

The hardware is not a Pine64 board. It is an Amlogic A113X/S420 Linux appliance
with 256 MB RAM and 512 MB NAND. It belongs in the same broad embedded-Linux
satellite category, but it requires ThirdReality's kernel, bootloader, device
tree, audio routing, LEDs, and recovery image format.

## Architecture

```text
ThirdReality Amlogic BSP / Buildroot
├── Tater Linux Voice (pinned Git commit)
│   ├── local wake word and microphone capture
│   ├── outbound authenticated Tater WebSocket
│   └── localhost peripheral API
├── ThirdReality hardware bridge
│   ├── LED ring
│   ├── home and mute buttons
│   ├── system volume and microphone mute
│   └── Sendspin duck / resume
└── Sendspin client for Music Assistant
```

The application source is pinned in
`buildroot/package/thirdreality/tater-linux-satellite/tater-linux-satellite.mk`.
A weekly CI check reports when Tater Linux Voice `main` moves ahead.

## Current status

The software integration, security baseline, configuration checks, and bridge
unit tests are complete. A full Linux image build and on-device audio regression
pass still require the ThirdReality toolchain submodule, a signing key, and
physical S420 hardware.

See [the parity matrix](docs/PARITY.md) for the exact supported and deferred
features.

## Build

Linux CI from a case-sensitive checkout is authoritative. The vendor kernel
and toolchain contain filenames that differ only by case, so neither a native
build nor a bind-mounted Docker build from case-insensitive macOS can faithfully
represent every source path. The Docker builder explicitly uses `linux/amd64`
for compatibility with ThirdReality's x86_64 toolchains.

Initialize the vendor toolchain:

```sh
git submodule update --init --depth 1
```

For a disposable development build:

```sh
./script/generate_development_ota_key.sh
TATER_SWUPDATE_PRIVATE_KEY_FILE=.secrets/swupdate-development-private.pem \
  ./go --docker trspk 0.1.0
```

Artifacts are written to `image/` as an Amlogic USB-burn image and a signed
SWUpdate package. Production builds must use an externally escrowed OTA signing
key; see [the security model](docs/SECURITY.md).

## Provision and operate

Wi-Fi provisioning continues to use ThirdReality's Bluetooth Improv flow.
Tater enrollment currently uses the physical serial recovery console:

```sh
tater-configure \
  --server-url https://tater.example.com \
  --pairing-code YOUR_ONE_TIME_CODE \
  --room Kitchen \
  --name "Kitchen Tater"
```

See [provisioning](docs/PROVISIONING.md) for storage paths and service controls.

## Validate without building an image

```sh
python3 script/validate_firmware.py
python3 -m unittest discover -s tests -v
```

## Upstreams

- Board support: [thirdreality/voice-music-assistant](https://github.com/thirdreality/voice-music-assistant)
- Voice application: [TaterTotterson/Tater-Linux-Satellite](https://github.com/TaterTotterson/Tater-Linux-Satellite)
- Original Linux voice application: [OHF-Voice/linux-voice-assistant](https://github.com/OHF-Voice/linux-voice-assistant)

This fork retains the upstream Apache-2.0 license.
