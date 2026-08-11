# Tater ThirdReality Voice Firmware

Tater firmware for the
[ThirdReality Voice & Music Assistant](https://github.com/thirdreality/voice-music-assistant).
This is an independent firmware fork that retains the vendor's Amlogic board
support while replacing its voice application with
[Tater Linux Voice](https://github.com/TaterTotterson/Tater-Linux-Satellite).

The hardware is not a Pine64 board. It is an Amlogic A113X/S420 Linux appliance
with 256 MB RAM and 512 MB NAND. It belongs in the same broad embedded-Linux
satellite category, but it requires ThirdReality's kernel, bootloader, device
tree, audio routing, LEDs, and recovery image format.

## Architecture

```text
ThirdReality Amlogic BSP / Buildroot
├── Tater Linux Voice (pinned Git commit)
│   ├── local Hey Tater wake word and microphone capture
│   ├── outbound authenticated Tater WebSocket
│   ├── timers, live settings, and signed OTA
│   └── localhost hardware API
├── ThirdReality hardware bridge
│   ├── LED ring
│   ├── home and mute buttons
│   └── system volume and microphone mute
└── Tater-native voice and media playback
    └── audio-session v2 stereo and synchronized multi-room playback
```

The application source is pinned in
`buildroot/package/thirdreality/tater-linux-satellite/tater-linux-satellite.mk`.
A weekly CI check reports when Tater Linux Voice `main` moves ahead.

## Current status

The software integration, security baseline, configuration checks, bridge unit
tests, and a full signed Amlogic image build are complete. The remaining gate is
an on-device audio and provisioning regression pass on physical S420 hardware.

See [the parity matrix](docs/PARITY.md) for the exact supported and deferred
features. See [the runtime network policy](docs/NETWORK.md) for every fixed or
configured outbound destination in the Tater image.

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
  ./go --docker trspk 0.2.3
```

Artifacts are written to `image/` as an Amlogic USB-burn image and a signed
SWUpdate package. Production builds must use an externally escrowed OTA signing
key; see [the security model](docs/SECURITY.md).

For release packaging, first-install requirements, artifact verification, and
recovery instructions, see [Flashing the S420](docs/FLASHING.md).

## Provision and operate

On first boot, the speaker creates an open `Tater-Setup-XXXX` Wi-Fi network.
Join it and use the captive portal (or open `http://192.168.4.1`) to enter the
2.4 GHz Wi-Fi credentials, Tater server, pairing code or token, room, and
speaker name. The setup network has no internet route and disappears after the
speaker saves its configuration and restarts.

Bluetooth, Improv, Sendspin, and mDNS are not included in the production image.
The local serial recovery console can still configure Tater directly:

```sh
tater-configure \
  --server-url https://tater.example.com \
  --pairing-code YOUR_ONE_TIME_CODE \
  --room Kitchen \
  --name "Kitchen Tater"
```

Long-press the Tap button to erase Wi-Fi and Tater pairing and reopen the setup
hotspot. See [provisioning](docs/PROVISIONING.md) for the full flow, storage
paths, and recovery controls.

## Validate without building an image

```sh
python3 script/validate_firmware.py
python3 -m unittest discover -s tests -v
```

## Upstreams

- Board support: [thirdreality/voice-music-assistant](https://github.com/thirdreality/voice-music-assistant)
- Voice application: [TaterTotterson/Tater-Linux-Satellite](https://github.com/TaterTotterson/Tater-Linux-Satellite)

This fork retains the upstream Apache-2.0 license.
