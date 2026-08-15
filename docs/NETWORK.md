# Runtime network policy

This document covers network traffic initiated by the Tater ThirdReality image.
Build-time source and dependency downloads are not device runtime traffic.

## Fixed public destinations

- NTP uses UDP port 123. A server supplied by DHCP Option 42 is preferred. If
  none is available, the firmware uses `time-a-g.nist.gov` in Gaithersburg,
  Maryland, plus `time-a-b.nist.gov` and `time-a-wwv.nist.gov` in Colorado. No
  Chinese NTP server or hard-coded public NTP address is present in the active
  configuration. Initial sync requests one sample per server and waits at least
  four seconds between retry rounds.
- After Wi-Fi has an address and default route, the network monitor tests only
  the explicitly configured Tater server. `ws://` and `wss://` endpoints are
  probed through their equivalent HTTP(S) transport. It does not contact a
  vendor connectivity service or install a public DNS fallback; DNS comes from
  the configured network.

## Configured or local destinations

- Tater Linux Voice connects only to the `server_url` written by
  `tater-configure`. The factory default is empty, so an unpaired image has no
  preconfigured Tater server destination. Once paired, the authenticated
  WebSocket hello reports the device ID, friendly name, board, firmware version,
  room, and capabilities. Microphone audio is sent only after a local wake or
  press-to-talk event starts a voice session.
- The authenticated Tater session can provide TTS/media URLs, external wake
  word model URLs, custom wake-sound URLs, and signed firmware URLs. The device
  fetches these only as part of an authenticated command or configuration from
  that Tater server. Built-in wake sounds are embedded and make no network call;
  a custom WAV is downloaded once and reused from a URL- and checksum-bound
  local cache.
  Firmware downloads are accepted by SWUpdate only when their signature matches
  the Tater public key embedded at build time.
- The Tater peripheral WebSocket is loopback-only at `127.0.0.1:6055`.
- When unconfigured, Wi-Fi provisioning uses an open local
  `Tater-Setup-XXXX` AP on `192.168.4.1`. DHCP leases are limited to
  `192.168.4.20` through `192.168.4.100`, wildcard DNS resolves to the captive
  portal, and the setup subnet has no upstream internet route. The portal saves
  Wi-Fi and Tater credentials locally, then reboots into station mode.

The production image does not include Sendspin, Music Assistant discovery,
Avahi, Zeroconf/mDNS service advertising, Bluetooth, BlueZ, telnet/inetd, or
ADB. PulseAudio's RTP, RAOP, and Rygel network modules are also pruned. Music
and media playback use the authenticated Tater connection instead.

## Retained but inactive vendor code

The legacy ThirdReality Python and C++ assistant packages, including their
vendor OTA client for `ota.cloud.3reality.com`, are not present in this fork.
The active Tater client does not call the vendor OTA service. Its remote OTA
path accepts only a URL delivered over the authenticated Tater session and
verifies the signed SWUpdate archive locally.

`script/validate_firmware.py` fails if either legacy assistant is selected, a
known Chinese NTP endpoint is reintroduced, a third-party connectivity probe is
added to the active monitor, or remote debug applets are enabled.
